#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
FIELD_RE = re.compile(r"([A-Za-z0-9_.-]+)=([^ ]+)")
TP_RE = re.compile(r"\bTP([0-9]+)\]")


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "min": min(values),
        "mean": sum(values) / len(values),
        "p50": percentile(values, 0.50),
        "p90": percentile(values, 0.90),
        "p99": percentile(values, 0.99),
        "max": max(values),
        "sum": sum(values),
    }


def as_int(fields: dict[str, str], key: str) -> int:
    return int(float(fields.get(key, "0")))


def as_float(fields: dict[str, str], key: str) -> float:
    return float(fields.get(key, "0"))


def parse_fields(text: str) -> dict[str, str]:
    return {match.group(1): match.group(2) for match in FIELD_RE.finditer(text)}


def summarize_reason(rows: list[dict[str, str]]) -> dict[str, Any]:
    capacities = [as_int(row, "gpu_direct_capacity_slots") for row in rows]
    requested = [as_int(row, "gpu_direct_requested_pages") for row in rows]
    transferable = [as_int(row, "final_transferable_pages") for row in rows]
    consumed_tokens = [as_int(row, "consumed_tokens") for row in rows]
    consumed_bytes = [as_int(row, "consumed_bytes") for row in rows]
    would_fit_after_start = [
        row
        for row in rows
        if as_int(row, "final_transferable_pages") > 0
        and as_int(row, "final_transferable_pages")
        <= as_int(row, "gpu_direct_capacity_slots")
    ]
    return {
        "count": len(rows),
        "requested_pages": stats([float(value) for value in requested]),
        "final_transferable_pages": stats(
            [float(value) for value in transferable]
        ),
        "consumed_tokens": sum(consumed_tokens),
        "consumed_bytes": sum(consumed_bytes),
        "would_fit_after_get_start_count": len(would_fit_after_start),
        "would_fit_after_get_start_pages": sum(
            as_int(row, "final_transferable_pages")
            for row in would_fit_after_start
        ),
        "capacity_slots": sorted(set(capacities)),
    }


def summarize_input(node: str, path: Path, tp_rank: int) -> dict[str, Any]:
    lifecycle_rows: list[dict[str, str]] = []
    lease_rows: list[dict[str, str]] = []
    pool_snapshots: list[dict[str, str]] = []
    lifecycle_all_ranks = 0
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for raw_line in stream:
            line = ANSI_RE.sub("", raw_line).strip()
            marker = "Fluxon hostless request lifecycle: "
            if marker in line:
                lifecycle_all_ranks += 1
                fields = parse_fields(line.split(marker, 1)[1])
                if as_int(fields, "tp_rank") == tp_rank:
                    lifecycle_rows.append(fields)
                continue
            marker = "Fluxon GPU staging lease released: "
            if marker in line:
                rank_match = TP_RE.search(line)
                fields = parse_fields(line.split(marker, 1)[1])
                fields["tp_rank"] = (
                    rank_match.group(1) if rank_match is not None else "-1"
                )
                if as_int(fields, "tp_rank") == tp_rank:
                    lease_rows.append(fields)
                continue
            marker = "Fluxon GPU staging pool Snapshot: "
            if marker in line:
                rank_match = TP_RE.search(line)
                fields = parse_fields(line.split(marker, 1)[1])
                fields["tp_rank"] = (
                    rank_match.group(1) if rank_match is not None else "-1"
                )
                if as_int(fields, "tp_rank") == tp_rank:
                    pool_snapshots.append(fields)

    req_counts = Counter(row.get("req", "") for row in lifecycle_rows)
    duplicates = {req: count for req, count in req_counts.items() if count != 1}
    by_reason: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in lifecycle_rows:
        by_reason[row.get("gpu_direct_admission", "missing")].append(row)

    selected_rows = by_reason.get("selected", [])
    selected_consumed = [
        row for row in selected_rows if as_int(row, "consumed_tokens") > 0
    ]
    fallback_rows = [
        row
        for reason, rows in by_reason.items()
        if reason not in ("selected", "not_observed")
        for row in rows
    ]
    fallback_that_fits = [
        row
        for row in fallback_rows
        if as_int(row, "final_transferable_pages") > 0
        and as_int(row, "final_transferable_pages")
        <= as_int(row, "gpu_direct_capacity_slots")
    ]

    lease_by_reason: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in lease_rows:
        lease_by_reason[row.get("reason", "missing")].append(row)

    return {
        "node": node,
        "path": str(path),
        "tp_rank": tp_rank,
        "lifecycle_all_ranks": lifecycle_all_ranks,
        "logical_lifecycle_rows": len(lifecycle_rows),
        "unique_request_ids": len(req_counts),
        "request_ids_with_multiple_lifecycle_rows": len(duplicates),
        "max_lifecycle_rows_per_request_id": max(req_counts.values(), default=0),
        "sample_request_ids_with_multiple_lifecycle_rows": dict(
            list(sorted(duplicates.items()))[:20]
        ),
        "admission_reasons": {
            reason: summarize_reason(rows)
            for reason, rows in sorted(by_reason.items())
        },
        "selected_count": len(selected_rows),
        "selected_consumed_count": len(selected_consumed),
        "selected_consumed_tokens": sum(
            as_int(row, "consumed_tokens") for row in selected_consumed
        ),
        "selected_consumed_bytes": sum(
            as_int(row, "consumed_bytes") for row in selected_consumed
        ),
        "fallback_would_fit_after_get_start_count": len(fallback_that_fits),
        "fallback_would_fit_after_get_start_pages": sum(
            as_int(row, "final_transferable_pages") for row in fallback_that_fits
        ),
        "lease_releases": {
            reason: {
                "count": len(rows),
                "held_ms": stats([as_float(row, "held_ms") for row in rows]),
                "initial_slots": stats(
                    [float(as_int(row, "initial_slots")) for row in rows]
                ),
                "released_slots": stats(
                    [float(as_int(row, "released_slots")) for row in rows]
                ),
            }
            for reason, rows in sorted(lease_by_reason.items())
        },
        "pool_snapshots": pool_snapshots,
    }


def merge_cluster(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    reasons: Counter[str] = Counter()
    reason_pages: Counter[str] = Counter()
    reason_fit: Counter[str] = Counter()
    for node in nodes:
        for reason, summary in node["admission_reasons"].items():
            reasons[reason] += int(summary["count"])
            reason_pages[reason] += int(summary["final_transferable_pages"]["sum"])
            reason_fit[reason] += int(summary["would_fit_after_get_start_count"])
    lifecycle_rows = sum(int(node["logical_lifecycle_rows"]) for node in nodes)
    admission_events = lifecycle_rows - reasons.get("not_observed", 0)
    non_candidate_reasons = {
        "not_observed",
        "not_eligible",
        "no_hash_values",
        "mamba_required",
    }
    gpu_candidate_events = sum(
        count for reason, count in reasons.items() if reason not in non_candidate_reasons
    )
    selected = reasons.get("selected", 0)
    fallback_fit = sum(
        int(node["fallback_would_fit_after_get_start_count"]) for node in nodes
    )
    return {
        "lifecycle_terminal_rows": lifecycle_rows,
        "admission_events": admission_events,
        "gpu_candidate_events": gpu_candidate_events,
        "admission_reason_counts": dict(sorted(reasons.items())),
        "admission_reason_final_transferable_pages": dict(
            sorted(reason_pages.items())
        ),
        "admission_reason_would_fit_after_get_start_counts": dict(
            sorted(reason_fit.items())
        ),
        "selected_count": selected,
        "selected_fraction_of_admission_events": (
            selected / admission_events if admission_events else None
        ),
        "selected_fraction_of_gpu_candidates": (
            selected / gpu_candidate_events if gpu_candidate_events else None
        ),
        "selected_consumed_count": sum(
            int(node["selected_consumed_count"]) for node in nodes
        ),
        "selected_consumed_tokens": sum(
            int(node["selected_consumed_tokens"]) for node in nodes
        ),
        "fallback_would_fit_after_get_start_count": fallback_fit,
        "fallback_would_fit_fraction_of_gpu_candidates": (
            fallback_fit / gpu_candidate_events if gpu_candidate_events else None
        ),
        "fallback_would_fit_after_get_start_pages": sum(
            int(node["fallback_would_fit_after_get_start_pages"])
            for node in nodes
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "inputs",
        nargs="+",
        help="NODE=PATH pairs",
    )
    parser.add_argument("--tp-rank", type=int, default=0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    nodes = []
    for raw in args.inputs:
        if "=" not in raw:
            raise ValueError(f"input must be NODE=PATH, got {raw!r}")
        node, raw_path = raw.split("=", 1)
        nodes.append(summarize_input(node, Path(raw_path), args.tp_rank))
    result = {
        "schema": "e44_r49_gpu_direct_admission_v1",
        "nodes": nodes,
        "cluster": merge_cluster(nodes),
    }
    rendered = json.dumps(result, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
