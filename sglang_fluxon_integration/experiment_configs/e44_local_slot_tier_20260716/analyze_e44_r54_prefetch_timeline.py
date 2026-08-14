#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


MARKER = "Fluxon prefetch timeline: "
TOKEN_RE = re.compile(r"([a-zA-Z_]+)=([^\s]+)")
INT_FIELDS = {
    "tp_rank",
    "enqueue_pos",
    "enqueue_len",
    "enqueue_pending_tokens",
    "enqueue_uncached_tokens",
    "scheduler_scan_count",
    "consume_pos",
    "consume_len",
    "consume_pending_tokens",
    "consume_uncached_tokens",
    "backend_handle",
    "terminal_before_consume",
}
FLOAT_FIELDS = {
    "first_scan_age_ms",
    "plan_ready_age_ms",
    "reserve_attempt_age_ms",
    "reserve_age_ms",
    "execute_return_age_ms",
    "transfer_consume_start_age_ms",
    "rdma_start_age_ms",
    "rdma_terminal_age_ms",
    "rdma_transfer_wall_ms",
    "terminal_to_consume_ms",
    "rdma_finish_wait_ms",
    "load_back_consume_start_age_ms",
    "restore_queued_age_ms",
    "restore_complete_age_ms",
    "staging_release_age_ms",
    "total_ms",
}


def parse_value(field: str, value: str) -> Any:
    if field in INT_FIELDS:
        return int(value)
    if field in FLOAT_FIELDS:
        return float(value)
    return value


def parse_line(line: str, node: str, source: Path, line_number: int) -> dict[str, Any] | None:
    marker_at = line.find(MARKER)
    if marker_at < 0:
        return None
    payload = line[marker_at + len(MARKER) :]
    row = {
        field: parse_value(field, value)
        for field, value in TOKEN_RE.findall(payload)
    }
    required = {"req", "tp_rank", "terminal", "total_ms"}
    missing = required.difference(row)
    if missing:
        raise ValueError(f"{source}:{line_number}: missing fields {sorted(missing)}")
    row["node"] = node
    row["source"] = str(source)
    row["line"] = line_number
    return row


def input_files(path: Path) -> Iterable[Path]:
    if path.is_file():
        yield path
        return
    if not path.is_dir():
        raise FileNotFoundError(path)
    for candidate in sorted(path.rglob("*")):
        if candidate.is_file() and candidate.suffix in {".log", ".txt", ".out"}:
            yield candidate


def load_rows(inputs: list[tuple[str, Path]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen_files: set[tuple[str, Path]] = set()
    attempt_counts: dict[tuple[str, int, str], int] = defaultdict(int)
    for node, path in inputs:
        for source in input_files(path):
            source_identity = (node, source.resolve())
            if source_identity in seen_files:
                continue
            seen_files.add(source_identity)
            with source.open("r", encoding="utf-8", errors="replace") as handle:
                for line_number, line in enumerate(handle, 1):
                    row = parse_line(line, node, source, line_number)
                    if row is None:
                        continue
                    key = (node, int(row["tp_rank"]), str(row["req"]))
                    row["attempt_index"] = attempt_counts[key]
                    attempt_counts[key] += 1
                    rows.append(row)
    return sorted(
        rows,
        key=lambda row: (
            row["node"],
            row["tp_rank"],
            row["req"],
            row["attempt_index"],
        ),
    )


def percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * ratio
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def distribution(values: Iterable[float]) -> dict[str, float | int]:
    data = [float(value) for value in values]
    if not data:
        return {"count": 0, "mean": 0.0, "p50": 0.0, "p90": 0.0, "p99": 0.0, "max": 0.0}
    return {
        "count": len(data),
        "mean": statistics.fmean(data),
        "p50": percentile(data, 0.50),
        "p90": percentile(data, 0.90),
        "p99": percentile(data, 0.99),
        "max": max(data),
    }


def add_derived(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    pairs = {
        "plan_to_reserve_ms": ("plan_ready_age_ms", "reserve_age_ms"),
        "reserve_to_rdma_start_ms": ("reserve_age_ms", "rdma_start_age_ms"),
        "terminal_to_load_back_ms": (
            "rdma_terminal_age_ms",
            "load_back_consume_start_age_ms",
        ),
        "load_back_to_restore_queue_ms": (
            "load_back_consume_start_age_ms",
            "restore_queued_age_ms",
        ),
        "restore_queue_to_release_ms": (
            "restore_queued_age_ms",
            "staging_release_age_ms",
        ),
        "reserve_to_release_ms": ("reserve_age_ms", "staging_release_age_ms"),
        "terminal_to_release_ms": (
            "rdma_terminal_age_ms",
            "staging_release_age_ms",
        ),
    }
    for name, (start, end) in pairs.items():
        start_value = float(out.get(start, 0.0))
        end_value = float(out.get(end, 0.0))
        out[name] = end_value - start_value if start_value > 0 and end_value > 0 else 0.0
    lease = float(out["reserve_to_release_ms"])
    post_terminal = float(out["terminal_to_release_ms"])
    out["post_terminal_lease_fraction"] = post_terminal / lease if lease > 0 else 0.0
    out["gpu_selected"] = int(
        float(out.get("reserve_age_ms", 0.0)) > 0
        and int(out.get("backend_handle", -1)) >= 0
    )
    return out


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    attempts_per_request_rank: dict[tuple[str, int, str], int] = defaultdict(int)
    for row in rows:
        attempts_per_request_rank[
            (str(row["node"]), int(row["tp_rank"]), str(row["req"]))
        ] += 1
    selected = [row for row in rows if row["gpu_selected"]]
    successful = [row for row in selected if row["terminal"] == "load_back_consumed"]
    timing_fields = (
        "enqueue_pos",
        "enqueue_len",
        "enqueue_pending_tokens",
        "consume_pos",
        "consume_len",
        "consume_pending_tokens",
        "plan_ready_age_ms",
        "reserve_age_ms",
        "rdma_transfer_wall_ms",
        "terminal_to_consume_ms",
        "rdma_finish_wait_ms",
        "terminal_to_load_back_ms",
        "load_back_to_restore_queue_ms",
        "restore_queue_to_release_ms",
        "reserve_to_release_ms",
        "terminal_to_release_ms",
        "post_terminal_lease_fraction",
    )
    negative_intervals = {
        field: sum(float(row.get(field, 0.0)) < -0.05 for row in successful)
        for field in (
            "plan_to_reserve_ms",
            "reserve_to_rdma_start_ms",
            "terminal_to_load_back_ms",
            "load_back_to_restore_queue_ms",
            "restore_queue_to_release_ms",
        )
    }
    return {
        "rows": len(rows),
        "request_rank_keys": len(attempts_per_request_rank),
        "repeated_request_rank_keys": sum(
            attempts > 1 for attempts in attempts_per_request_rank.values()
        ),
        "max_attempts_per_request_rank": max(
            attempts_per_request_rank.values(), default=0
        ),
        "gpu_selected": len(selected),
        "gpu_selected_load_back_consumed": len(successful),
        "terminal_before_consume": sum(
            int(row.get("terminal_before_consume", 0)) for row in selected
        ),
        "terminal_before_consume_rate": (
            sum(int(row.get("terminal_before_consume", 0)) for row in selected)
            / len(selected)
            if selected
            else 0.0
        ),
        "negative_interval_counts": negative_intervals,
        "distributions": {
            field: distribution(row.get(field, 0.0) for row in successful)
            for field in timing_fields
        },
    }


def parse_input(value: str) -> tuple[str, Path]:
    node, separator, raw_path = value.partition("=")
    if not separator or not node or not raw_path:
        raise argparse.ArgumentTypeError("input must be NODE=PATH")
    return node, Path(raw_path)


def self_test() -> None:
    line = (
        "prefix Fluxon prefetch timeline: req=r1 tp_rank=0 terminal=load_back_consumed "
        "enqueue_pos=2 enqueue_len=3 enqueue_pending_tokens=100 enqueue_uncached_tokens=80 "
        "scheduler_scan_count=1 first_scan_age_ms=40 consume_pos=0 consume_len=3 "
        "consume_pending_tokens=100 consume_uncached_tokens=80 plan_ready_age_ms=10 "
        "reserve_attempt_age_ms=12 reserve_age_ms=12 execute_return_age_ms=15 "
        "backend_handle=7 transfer_consume_start_age_ms=40 rdma_start_age_ms=14 "
        "rdma_terminal_age_ms=24 rdma_transfer_wall_ms=10 terminal_before_consume=1 "
        "terminal_to_consume_ms=16 rdma_finish_wait_ms=0 load_back_consume_start_age_ms=45 "
        "restore_queued_age_ms=55 restore_complete_age_ms=75 staging_release_age_ms=75 total_ms=75"
    )
    row = parse_line(line, "node0", Path("synthetic.log"), 1)
    assert row is not None
    derived = add_derived(row)
    assert derived["gpu_selected"] == 1
    assert derived["terminal_to_load_back_ms"] == 21
    assert derived["reserve_to_release_ms"] == 63
    result = summarize([derived])
    assert result["terminal_before_consume_rate"] == 1.0
    repeated = line.replace("total_ms=75", "total_ms=76")
    with tempfile.TemporaryDirectory() as temp_dir:
        source = Path(temp_dir) / "timeline.log"
        source.write_text(line + "\n" + repeated + "\n", encoding="utf-8")
        attempts = load_rows([("node0", source), ("node0", source)])
    assert len(attempts) == 2
    assert [row["attempt_index"] for row in attempts] == [0, 1]
    repeated_result = summarize([add_derived(row) for row in attempts])
    assert repeated_result["repeated_request_rank_keys"] == 1
    assert repeated_result["max_attempts_per_request_rank"] == 2
    print("e44 r54 prefetch timeline analyzer self-test: passed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", action="append", type=parse_input, default=[])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--include-rows", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if not args.input or args.output is None:
        parser.error("--input NODE=PATH and --output are required")
    rows = [add_derived(row) for row in load_rows(args.input)]
    by_node: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_node[str(row["node"])].append(row)
    result: dict[str, Any] = {
        "inputs": [{"node": node, "path": str(path)} for node, path in args.input],
        "summary": summarize(rows),
        "by_node": {node: summarize(node_rows) for node, node_rows in sorted(by_node.items())},
    }
    if args.include_rows:
        result["rows"] = rows
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result["summary"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
