#!/usr/bin/env python3
"""Split hostless ``ready_wait`` into scheduler residence and real Get work.

The r38 SGLang lifecycle timer starts before Get Start and stops only when the
scheduler revisits the prefetch and publishes it as ready.  It is therefore not
a pure network timer.  This analyzer combines that existing lifecycle line with
the observation-only owner records added for r39.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


MARKERS = {
    "start": "external Get start lifecycle:",
    "consume": "external Get consume lifecycle:",
    "leader_start": "external Get leader start lifecycle:",
    "finish": "external Get finish lifecycle:",
    "sglang": "Fluxon hostless request lifecycle:",
}


def parse_value(raw: str) -> int | float | str:
    if raw == "true":
        return True
    if raw == "false":
        return False
    try:
        return int(raw)
    except ValueError:
        try:
            return float(raw)
        except ValueError:
            return raw


def parse_fields(text: str) -> dict[str, int | float | str]:
    fields: dict[str, int | float | str] = {}
    for token in text.strip().split():
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        fields[key] = parse_value(value.rstrip(","))
    return fields


def parse_line(line: str, marker: str) -> dict[str, int | float | str] | None:
    if marker not in line:
        return None
    return parse_fields(line.split(marker, 1)[1])


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


def stats(values: Iterable[int | float], scale: float = 1.0) -> dict[str, Any]:
    samples = [float(value) / scale for value in values]
    if not samples:
        return {"count": 0}
    total = sum(samples)
    return {
        "count": len(samples),
        "sum": total,
        "mean": total / len(samples),
        "p50": percentile(samples, 0.50),
        "p90": percentile(samples, 0.90),
        "p99": percentile(samples, 0.99),
        "max": max(samples),
    }


def numeric(record: dict[str, Any], field: str) -> int | float:
    value = record.get(field, 0)
    if not isinstance(value, (int, float)):
        raise ValueError(f"field {field!r} is not numeric: {value!r}")
    return value


def total(records: list[dict[str, Any]], field: str) -> int | float:
    return sum(numeric(record, field) for record in records)


def timing_fields(
    records: list[dict[str, Any]], fields: list[str], scale: float = 1.0
) -> dict[str, Any]:
    return {
        field: stats((numeric(record, field) for record in records), scale)
        for field in fields
    }


def parse_pairs(raw_pairs: list[str], kind: str) -> list[tuple[str, Path]]:
    pairs: list[tuple[str, Path]] = []
    for raw in raw_pairs:
        if "=" not in raw:
            raise SystemExit(f"{kind} input must be NODE=PATH: {raw}")
        node, path = raw.split("=", 1)
        pairs.append((node, Path(path)))
    return pairs


def load_records(
    pairs: list[tuple[str, Path]], marker_names: set[str]
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    records = {name: [] for name in marker_names}
    files: list[dict[str, Any]] = []
    for node, path in pairs:
        counts: Counter[str] = Counter()
        with path.open("r", encoding="utf-8", errors="replace") as stream:
            for line_number, line in enumerate(stream, 1):
                for name in marker_names:
                    parsed = parse_line(line, MARKERS[name])
                    if parsed is None:
                        continue
                    parsed.update(
                        node=node,
                        path=str(path),
                        line=line_number,
                    )
                    records[name].append(parsed)
                    counts[name] += 1
        files.append(
            {
                "node": node,
                "path": str(path),
                "records": dict(sorted(counts.items())),
            }
        )
    return records, files


def validate_required(
    name: str, records: list[dict[str, Any]], required: set[str]
) -> None:
    for record in records:
        missing = required - record.keys()
        if missing:
            raise ValueError(
                f"{record['path']}:{record['line']}: {name} missing {sorted(missing)}"
            )


def summarize_start(records: list[dict[str, Any]]) -> dict[str, Any]:
    phase_fields = [
        "local",
        "starting",
        "started",
        "finishing",
        "revoking",
        "ready",
        "failed",
    ]
    checks = [
        sum(int(numeric(record, field)) for field in phase_fields)
        == int(numeric(record, "transferable"))
        for record in records
    ]
    return {
        "records": len(records),
        "inline_local_records": sum(int(numeric(record, "inline_local")) for record in records),
        "requested_items": total(records, "requested"),
        "raw_prefix_items": total(records, "raw_prefix"),
        "transferable_items": total(records, "transferable"),
        "phase_items": {field: total(records, field) for field in phase_fields},
        "terminal_before_return_items": total(records, "terminal_before_return"),
        "pending_before_return_items": total(records, "pending_before_return"),
        "timings_ms": timing_fields(
            records,
            ["terminal_age_mean_us", "terminal_age_max_us", "total_us"],
            1000.0,
        ),
        "checks": {"phase_partition_matches_transferable": all(checks)},
    }


def summarize_consume(records: list[dict[str, Any]]) -> dict[str, Any]:
    phase_fields = [
        "local_before",
        "starting_before",
        "started_before",
        "finishing_before",
        "revoking_before",
        "ready_before",
        "failed_before",
    ]
    consumed_items = int(total(records, "consumed"))
    terminal_items = int(total(records, "terminal_before"))
    pending_items = int(total(records, "pending_before"))
    pending_records = [record for record in records if numeric(record, "pending_before") > 0]
    ready_records = [record for record in records if numeric(record, "pending_before") == 0]
    ok_records = [record for record in records if record.get("outcome") == "ok"]
    partition_checks = [
        int(numeric(record, "terminal_before"))
        + int(numeric(record, "pending_before"))
        == int(numeric(record, "consumed"))
        for record in records
    ]
    outcome_checks = [
        int(numeric(record, "hits"))
        + int(numeric(record, "misses"))
        + int(numeric(record, "errors"))
        == int(numeric(record, "consumed"))
        for record in ok_records
    ]
    return {
        "records": len(records),
        "outcomes": dict(sorted(Counter(str(r.get("outcome")) for r in records).items())),
        "consumed_items": consumed_items,
        "terminal_before_consume_items": terminal_items,
        "pending_before_consume_items": pending_items,
        "terminal_before_consume_ratio": (
            terminal_items / consumed_items if consumed_items else None
        ),
        "records_all_terminal_before_consume": len(ready_records),
        "records_with_real_terminal_wait": len(pending_records),
        "phase_items": {field: total(records, field) for field in phase_fields},
        "outcome_items": {
            field: total(records, field) for field in ["hits", "misses", "errors"]
        },
        "timings_ms": timing_fields(
            records,
            [
                "handle_age_us",
                "terminal_age_mean_us",
                "terminal_age_max_us",
                "finish_wait_us",
                "install_us",
                "total_us",
            ],
            1000.0,
        ),
        "finish_wait_ms_by_state": {
            "all_terminal_before_consume": stats(
                (numeric(record, "finish_wait_us") for record in ready_records), 1000.0
            ),
            "pending_before_consume": stats(
                (numeric(record, "finish_wait_us") for record in pending_records), 1000.0
            ),
        },
        "checks": {
            "state_partition_matches_consumed": all(partition_checks),
            "ok_outcome_partition_matches_consumed": all(outcome_checks),
        },
    }


def summarize_leader(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "records": len(records),
        "outcomes": dict(sorted(Counter(str(r.get("outcome")) for r in records).items())),
        "leaders": total(records, "leaders"),
        "hits": total(records, "hits"),
        "misses": total(records, "misses"),
        "errors": total(records, "errors"),
        "batch_get_start_ms": stats(
            (numeric(record, "batch_get_start_us") for record in records), 1000.0
        ),
    }


def summarize_finish(records: list[dict[str, Any]]) -> dict[str, Any]:
    count_fields = [
        "requested",
        "zero_copy_items",
        "transfer_items",
        "remote_transfer_items",
        "transfer_bytes",
        "remote_transfer_bytes",
        "done_items",
        "local_hot_admissions",
        "hits",
        "misses",
        "errors",
    ]
    timing = [
        "plan_us",
        "transfer_wall_us",
        "transfer_sum_us",
        "transfer_max_us",
        "transfer_cleanup_us",
        "install_us",
        "done_us",
        "publish_us",
        "total_us",
    ]
    return {
        "records": len(records),
        "totals": {field: total(records, field) for field in count_fields},
        "done_attempts": stats(numeric(record, "done_attempts") for record in records),
        "timings_ms": timing_fields(records, timing, 1000.0),
    }


def summarize_sglang(records: list[dict[str, Any]]) -> dict[str, Any]:
    consumed = [record for record in records if record.get("terminal") == "load_back_consumed"]
    timing = [
        "initial_start_ms",
        "get_transfer_ms",
        "ready_wait_ms",
        "evict_total_ms",
        "evict_free_group_ms",
        "restore_complete_ms",
        "total_ms",
    ]
    return {
        "lifecycle_records": len(records),
        "consumed_records": len(consumed),
        "timings_ms": timing_fields(consumed, timing),
    }


def run_self_test() -> None:
    consume = parse_line(
        "x external Get consume lifecycle: handle=1 available=2 consumed=2 "
        "released_tail=0 handle_age_us=5000 local_before=0 starting_before=0 "
        "started_before=0 finishing_before=1 revoking_before=0 ready_before=1 "
        "failed_before=0 terminal_before=1 pending_before=1 "
        "terminal_age_mean_us=3000 terminal_age_max_us=3000 finish_wait_us=2000 "
        "hits=2 misses=0 errors=0 install_us=10 total_us=2050 outcome=ok",
        MARKERS["consume"],
    )
    assert consume is not None
    consume.update(path="self", line=1, node="self")
    summary = summarize_consume([consume])
    assert summary["terminal_before_consume_ratio"] == 0.5
    assert summary["records_with_real_terminal_wait"] == 1
    assert summary["checks"]["state_partition_matches_consumed"]
    assert summary["checks"]["ok_outcome_partition_matches_consumed"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner", action="append", default=[], metavar="NODE=PATH")
    parser.add_argument("--sglang", action="append", default=[], metavar="NODE=PATH")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        run_self_test()
        print("self-test: ok")
        return 0
    if not args.owner or not args.sglang:
        parser.error("at least one --owner and one --sglang input are required")

    owner_records, owner_files = load_records(
        parse_pairs(args.owner, "owner"), {"start", "consume", "leader_start", "finish"}
    )
    sglang_records, sglang_files = load_records(
        parse_pairs(args.sglang, "sglang"), {"sglang"}
    )

    required = {
        "start": {"requested", "transferable", "inline_local", "total_us"},
        "consume": {
            "consumed",
            "terminal_before",
            "pending_before",
            "handle_age_us",
            "finish_wait_us",
            "outcome",
        },
        "leader_start": {"leaders", "batch_get_start_us", "outcome"},
        "finish": {"requested", "transfer_wall_us", "done_us", "total_us"},
        "sglang": {"terminal", "ready_wait_ms", "total_ms"},
    }
    for name, fields in required.items():
        source = sglang_records[name] if name == "sglang" else owner_records[name]
        validate_required(name, source, fields)

    result = {
        "schema": "e44_r39_get_ready_breakdown_v1",
        "files": owner_files + sglang_files,
        "owner_start": summarize_start(owner_records["start"]),
        "owner_consume": summarize_consume(owner_records["consume"]),
        "owner_leader_start": summarize_leader(owner_records["leader_start"]),
        "owner_finish": summarize_finish(owner_records["finish"]),
        "sglang": summarize_sglang(sglang_records["sglang"]),
        "interpretation": {
            "ready_wait_is_not_pure_network_time": True,
            "decision_rule": (
                "Use terminal_before_consume_ratio and finish_wait_ms to measure real "
                "data wait; handle_age_ms is scheduler/consumer residence after Start."
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
