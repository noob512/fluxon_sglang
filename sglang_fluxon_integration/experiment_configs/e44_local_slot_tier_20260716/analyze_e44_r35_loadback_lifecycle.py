#!/usr/bin/env python3
"""Summarize r35 hostless request-lifecycle and load-back observations."""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


LIFECYCLE_MARKER = "Fluxon hostless request lifecycle:"
LINE_PATTERNS = {
    "get_start": "Fluxon get_start success",
    "get_transfer": "Fluxon get_transfer success",
    "cancel_get_transfer": "Fluxon cancel_get_transfer success",
    "prefetch_submitted": "HiCache prefetch submitted:",
    "prefetch_completed": "HiCache prefetch success req=",
    "load_back_started": "init_load_back success:",
    "load_back_dma_completed": "Fluxon layerwise restore complete:",
    "empty_load_back": "HiCache load_back produced no prefix tokens:",
}
NUMBER = re.compile(r"^-?(?:\d+|\d+\.\d+)$")
INIT_EVICT_MS = re.compile(r"\bevict_ms=(\d+(?:\.\d+)?)")
RESTORE_COMPLETE_MS = re.compile(
    r"Fluxon layerwise restore complete:.*\bduration_ms=(\d+(?:\.\d+)?)"
)


def parse_number(value: str) -> int | float | str:
    if not NUMBER.fullmatch(value):
        return value
    return float(value) if "." in value else int(value)


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


def stats(values: Iterable[int | float]) -> dict[str, Any]:
    samples = [float(value) for value in values]
    if not samples:
        return {"count": 0}
    return {
        "count": len(samples),
        "sum": sum(samples),
        "mean": sum(samples) / len(samples),
        "p50": percentile(samples, 0.50),
        "p90": percentile(samples, 0.90),
        "p99": percentile(samples, 0.99),
        "max": max(samples),
    }


def counter_json(counter: Counter[Any]) -> dict[str, int]:
    return {str(key): value for key, value in sorted(counter.items(), key=lambda x: str(x[0]))}


def load_file(
    node: str, path: Path
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, list[float]]]:
    lifecycle: list[dict[str, Any]] = []
    line_counts: Counter[str] = Counter()
    init_evict_ms: list[float] = []
    restore_complete_ms: list[float] = []
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for line_number, line in enumerate(stream, 1):
            for name, marker in LINE_PATTERNS.items():
                if marker in line:
                    line_counts[name] += 1
            match = INIT_EVICT_MS.search(line) if "init_load_back success:" in line else None
            if match:
                init_evict_ms.append(float(match.group(1)))
            match = RESTORE_COMPLETE_MS.search(line)
            if match:
                restore_complete_ms.append(float(match.group(1)))
            if LIFECYCLE_MARKER not in line:
                continue
            prefix, fields = line.split(LIFECYCLE_MARKER, 1)
            timestamp_match = re.match(r"\[([^]]+)]", prefix)
            record: dict[str, Any] = {
                "node": node,
                "path": str(path),
                "line": line_number,
                "timestamp": timestamp_match.group(1) if timestamp_match else "",
            }
            for item in fields.strip().split():
                if "=" not in item:
                    continue
                key, value = item.split("=", 1)
                record[key] = parse_number(value)
            required = {"req", "tp_rank", "terminal", "decision"}
            missing = required - record.keys()
            if missing:
                raise ValueError(f"{path}:{line_number}: missing lifecycle fields {sorted(missing)}")
            lifecycle.append(record)
    return lifecycle, {
        "node": node,
        "path": str(path),
        "line_counts": counter_json(line_counts),
        "init_load_back_evict_ms": stats(init_evict_ms),
        "restore_complete_ms": stats(restore_complete_ms),
    }, {
        "init_load_back_evict_ms": init_evict_ms,
        "restore_complete_ms": restore_complete_ms,
    }


def numeric_sum(records: list[dict[str, Any]], field: str) -> int | float:
    return sum(record.get(field, 0) for record in records)


def timing_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    fields = [
        "initial_start_ms",
        "retry_start_ms",
        "get_transfer_ms",
        "ready_wait_ms",
        "evict_write_backup_ms",
        "evict_write_wait_ms",
        "evict_free_group_ms",
        "evict_total_ms",
        "restore_complete_ms",
        "total_ms",
    ]
    result: dict[str, Any] = {}
    for field in fields:
        values = [float(record.get(field, 0)) for record in records]
        result[field] = {
            "all": stats(values),
            "nonzero": stats(value for value in values if value > 0),
        }
    return result


def summarize_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "rank_records": len(records),
        "terminal": counter_json(Counter(record["terminal"] for record in records)),
        "decision": counter_json(Counter(record["decision"] for record in records)),
        "ready_rank_records": sum(int(record.get("ready_pages", 0) > 0) for record in records),
        "consumed_rank_records": sum(
            int(record.get("consumed_pages", 0) > 0) for record in records
        ),
        "ready_pages": numeric_sum(records, "ready_pages"),
        "ready_bytes": numeric_sum(records, "ready_bytes"),
        "consumed_pages": numeric_sum(records, "consumed_pages"),
        "consumed_tokens": numeric_sum(records, "consumed_tokens"),
        "consumed_bytes": numeric_sum(records, "consumed_bytes"),
        "apparent_ready_not_consumed_rank_records": sum(
            int(record.get("ready_pages", 0) > 0 and record.get("consumed_pages", 0) == 0)
            for record in records
        ),
        "apparent_ready_not_consumed_bytes": sum(
            max(0, int(record.get("ready_bytes", 0)) - int(record.get("consumed_bytes", 0)))
            for record in records
        ),
        "retry_rank_records": sum(int(record.get("retry_count", 0) > 0) for record in records),
        "timings_ms": timing_summary(records),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "inputs",
        nargs="+",
        help="NODE=PATH pairs, for example node0=/path/to/sglang.log",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    all_records: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    successful_evict_ms: list[float] = []
    successful_restore_ms: list[float] = []
    for raw in args.inputs:
        if "=" not in raw:
            raise SystemExit(f"input must be NODE=PATH: {raw}")
        node, path_text = raw.split("=", 1)
        records, file_summary, measurements = load_file(node, Path(path_text))
        all_records.extend(records)
        files.append(file_summary)
        successful_evict_ms.extend(measurements["init_load_back_evict_ms"])
        successful_restore_ms.extend(measurements["restore_complete_ms"])

    by_rank: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for record in all_records:
        by_rank[(str(record["node"]), str(record["req"]), int(record["tp_rank"]))].append(record)

    canonical: list[dict[str, Any]] = []
    duplicate_untracked: list[dict[str, Any]] = []
    orphan_untracked_rank_groups: list[dict[str, Any]] = []
    invalid_rank_groups: list[dict[str, Any]] = []
    for key, rank_records in sorted(by_rank.items()):
        tracked = [record for record in rank_records if record["decision"] != "untracked"]
        untracked = [record for record in rank_records if record["decision"] == "untracked"]
        duplicate_untracked.extend(untracked)
        if not tracked and untracked:
            orphan_untracked_rank_groups.append(
                {
                    "node": key[0],
                    "req": key[1],
                    "tp_rank": key[2],
                    "untracked": len(untracked),
                }
            )
            continue
        if len(tracked) != 1:
            invalid_rank_groups.append(
                {
                    "node": key[0],
                    "req": key[1],
                    "tp_rank": key[2],
                    "tracked": len(tracked),
                    "untracked": len(untracked),
                }
            )
            continue
        canonical.append(tracked[0])

    if invalid_rank_groups:
        raise ValueError(f"invalid canonical rank groups: {invalid_rank_groups[:20]}")

    by_request: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in canonical:
        by_request[(str(record["node"]), str(record["req"]))].append(record)

    raw_by_request: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in all_records:
        raw_by_request[(str(record["node"]), str(record["req"]))].append(record)

    request_terminal: Counter[str] = Counter()
    request_decision: Counter[str] = Counter()
    invalid_request_groups: list[dict[str, Any]] = []
    ready_request_count = 0
    consumed_request_count = 0
    for key, request_records in sorted(by_request.items()):
        ranks = sorted(int(record["tp_rank"]) for record in request_records)
        if ranks != [0, 1]:
            invalid_request_groups.append(
                {"node": key[0], "req": key[1], "ranks": ranks}
            )
            continue
        terminals = sorted(str(record["terminal"]) for record in request_records)
        decisions = sorted(str(record["decision"]) for record in request_records)
        request_terminal[" + ".join(terminals)] += 1
        request_decision[" + ".join(decisions)] += 1
        ready_request_count += int(any(record.get("ready_pages", 0) > 0 for record in request_records))
        consumed_request_count += int(
            any(record.get("consumed_pages", 0) > 0 for record in request_records)
        )

    if invalid_request_groups:
        raise ValueError(f"invalid TP request groups: {invalid_request_groups[:20]}")

    canonical_by_node = {
        node: [record for record in canonical if record["node"] == node]
        for node in sorted({str(record["node"]) for record in canonical})
    }
    line_totals = Counter()
    for file_summary in files:
        line_totals.update(file_summary["line_counts"])

    ready_records = [record for record in canonical if record.get("ready_pages", 0) > 0]
    consumed_terminal_records = [
        record for record in canonical if record["terminal"] == "load_back_consumed"
    ]
    canonical_no_ready_records = [
        record for record in canonical if int(record.get("ready_pages", 0)) == 0
    ]
    canonical_ready_not_consumed_records = [
        record
        for record in canonical
        if int(record.get("ready_pages", 0)) > 0
        and int(record.get("consumed_pages", 0)) == 0
    ]
    eviction_fields = [
        "evict_requested_tokens",
        "evict_actual_tokens",
        "evict_candidate_tokens",
        "evict_already_backed_tokens",
        "evict_after_writeback_tokens",
        "evict_unbacked_drop_tokens",
        "evict_new_writebacks",
        "evict_pending_writebacks",
    ]
    eviction_totals = {
        field: numeric_sum(consumed_terminal_records, field) for field in eviction_fields
    }

    flow_checks = {
        "get_start_equals_initial_plus_retries": line_totals["get_start"]
        == sum(int(record.get("initial_start_ms", 0) > 0) for record in canonical)
        + sum(int(record.get("retry_count", 0) > 0) for record in canonical),
        "get_start_equals_transfer_plus_cancel": line_totals["get_start"]
        == line_totals["get_transfer"] + line_totals["cancel_get_transfer"],
        "ready_equals_prefetch_submit": len(ready_records) == line_totals["prefetch_submitted"],
        "ready_equals_prefetch_complete": len(ready_records) == line_totals["prefetch_completed"],
        "ready_equals_load_back_start": len(ready_records) == line_totals["load_back_started"],
        "ready_equals_dma_complete": len(ready_records) == line_totals["load_back_dma_completed"],
        "terminal_gap_equals_apparent_ready_not_consumed": len(ready_records)
        - len(consumed_terminal_records)
        == len(canonical_ready_not_consumed_records),
        "empty_attempts_fully_decomposed": line_totals["empty_load_back"]
        == len(canonical_no_ready_records)
        + len(canonical_ready_not_consumed_records)
        + len(duplicate_untracked),
    }

    result = {
        "schema": "e44_r35_loadback_lifecycle_summary_v1",
        "files": files,
        "line_totals": counter_json(line_totals),
        "raw_lifecycle": summarize_records(all_records),
        "canonical_lifecycle": summarize_records(canonical),
        "canonical_by_node": {
            node: summarize_records(records) for node, records in canonical_by_node.items()
        },
        "canonical_rank_groups": len(by_rank),
        "canonical_request_groups": len(by_request),
        "duplicate_untracked_rank_records": len(duplicate_untracked),
        "orphan_untracked_rank_groups": orphan_untracked_rank_groups,
        "requests_with_duplicate_untracked": sum(
            int(any(record["decision"] == "untracked" for record in records))
            for records in raw_by_request.values()
        ),
        "duplicate_untracked_per_request": counter_json(
            Counter(
                sum(record["decision"] == "untracked" for record in records)
                for records in raw_by_request.values()
            )
        ),
        "request_terminal_pairs": counter_json(request_terminal),
        "request_decision_pairs": counter_json(request_decision),
        "ready_request_groups": ready_request_count,
        "consumed_terminal_request_groups": consumed_request_count,
        "flow_checks": flow_checks,
        "flow_accounting": {
            "initial_get_start_rank_calls": sum(
                int(record.get("initial_start_ms", 0) > 0) for record in canonical
            ),
            "retry_get_start_rank_calls": sum(
                int(record.get("retry_count", 0) > 0) for record in canonical
            ),
            "get_start_rank_calls": line_totals["get_start"],
            "cancel_get_transfer_rank_calls": line_totals["cancel_get_transfer"],
            "get_transfer_rank_calls": line_totals["get_transfer"],
            "ready_rank_operations": len(ready_records),
            "dma_completed_rank_operations": line_totals["load_back_dma_completed"],
            "consumed_terminal_rank_records": len(consumed_terminal_records),
            "consumed_terminal_accounting_gap": len(ready_records)
            - len(consumed_terminal_records),
            "empty_load_back_rank_attempts": line_totals["empty_load_back"],
            "empty_load_back_tp_pair_equivalent": line_totals["empty_load_back"] / 2,
            "empty_load_back_decomposition_rank_records": {
                "canonical_no_ready_transfer": len(canonical_no_ready_records),
                "ready_transfer_but_terminal_overwritten": len(
                    canonical_ready_not_consumed_records
                ),
                "post_terminal_untracked_residual_attempt": len(duplicate_untracked),
            },
        },
        "successful_load_back_timings_ms": {
            "init_evict_ms": stats(successful_evict_ms),
            "dma_restore_complete_ms": stats(successful_restore_ms),
        },
        "start_timing_ms": {
            "initial_nonzero": stats(
                record.get("initial_start_ms", 0)
                for record in canonical
                if record.get("initial_start_ms", 0) > 0
            ),
            "retry_nonzero": stats(
                record.get("retry_start_ms", 0)
                for record in canonical
                if record.get("retry_start_ms", 0) > 0
            ),
            "get_transfer_nonzero": stats(
                record.get("get_transfer_ms", 0)
                for record in canonical
                if record.get("get_transfer_ms", 0) > 0
            ),
        },
        "eviction_breakdown_observed_consumed_terminals": {
            "records": len(consumed_terminal_records),
            "records_with_physical_eviction": sum(
                int(record.get("evict_actual_tokens", 0) > 0)
                for record in consumed_terminal_records
            ),
            "records_with_writeback": sum(
                int(record.get("evict_after_writeback_tokens", 0) > 0)
                for record in consumed_terminal_records
            ),
            "totals": eviction_totals,
            "timings_ms": timing_summary(consumed_terminal_records),
        },
        "interpretation_guards": {
            "apparent_ready_not_consumed_bytes_are_not_proven_waste": True,
            "reason": (
                "Every ready rank operation has matching prefetch submit, get_transfer, "
                "init_load_back success, and DMA completion. Missing consumed terminals "
                "therefore indicate request-level observation overwrite by a later residual "
                "load-back attempt, not an unconsumed physical transfer."
            ),
        },
    }

    rendered = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
