#!/usr/bin/env python3
"""Summarize E44 HCA JSONL samples into per-port and dual-HCA bandwidth."""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any


DATA_UNIT_BYTES = 4.0


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


def stats(values: list[float], capacity_gbps: float | None = None) -> dict[str, Any]:
    if not values:
        return {"count": 0}
    average = sum(values) / len(values)
    result: dict[str, Any] = {
        "count": len(values),
        "avg_gbps": average,
        "p50_gbps": percentile(values, 0.50),
        "p90_gbps": percentile(values, 0.90),
        "p99_gbps": percentile(values, 0.99),
        "peak_gbps": max(values),
        "zero_fraction_lt_0_1_gbps": sum(value < 0.1 for value in values) / len(values),
        "active_avg_gbps": None,
    }
    active = [value for value in values if value >= 0.1]
    if active:
        result["active_avg_gbps"] = sum(active) / len(active)
    if capacity_gbps:
        result["avg_utilization"] = average / capacity_gbps
        result["p99_utilization"] = float(result["p99_gbps"]) / capacity_gbps
        result["peak_utilization"] = max(values) / capacity_gbps
    return result


def load_jsonl(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    metadata: dict[str, Any] = {}
    samples: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: {exc}") from exc
            if record.get("type") == "metadata":
                metadata = record
            elif record.get("type") == "sample":
                samples.append(record)
    return metadata, samples


def summarize_file(
    path: Path,
    start_epoch_s: float | None,
    end_epoch_s: float | None,
) -> dict[str, Any]:
    metadata, raw_samples = load_jsonl(path)
    start_ns = int(start_epoch_s * 1e9) if start_epoch_s is not None else None
    end_ns = int(end_epoch_s * 1e9) if end_epoch_s is not None else None

    by_hca: dict[str, list[dict[str, Any]]] = defaultdict(list)
    sample_errors: list[dict[str, Any]] = []
    for record in raw_samples:
        for hca_sample in record.get("hcas", []):
            wall_ns = int(hca_sample.get("wall_mid_ns", 0))
            if start_ns is not None and wall_ns < start_ns:
                continue
            if end_ns is not None and wall_ns > end_ns:
                continue
            item = dict(hca_sample)
            item["sequence"] = int(record.get("sequence", -1))
            by_hca[str(item.get("hca"))].append(item)
            if item.get("error"):
                sample_errors.append(
                    {"sequence": item["sequence"], "hca": item.get("hca"), "error": item["error"]}
                )

    capacity_by_hca = {
        str(port.get("hca")): float(port["rate_gbps"])
        for port in metadata.get("ports", [])
        if port.get("rate_gbps") is not None
    }
    per_hca: dict[str, Any] = {}
    aggregate_by_sequence: dict[int, dict[str, float]] = defaultdict(
        lambda: {"rx_gbps": 0.0, "tx_gbps": 0.0}
    )

    for hca, samples in sorted(by_hca.items()):
        rx_rates: list[float] = []
        tx_rates: list[float] = []
        total_rx_bytes = 0.0
        total_tx_bytes = 0.0
        total_duration_s = 0.0
        xmit_wait_delta = 0
        reset_or_wrap_count = 0
        previous: dict[str, Any] | None = None
        for current in samples:
            if previous is None:
                previous = current
                continue
            duration_s = (
                int(current["monotonic_start_ns"]) - int(previous["monotonic_start_ns"])
            ) / 1e9
            prev_counters = previous.get("counters") or {}
            curr_counters = current.get("counters") or {}
            rx_units = int(curr_counters.get("PortRcvData", 0)) - int(
                prev_counters.get("PortRcvData", 0)
            )
            tx_units = int(curr_counters.get("PortXmitData", 0)) - int(
                prev_counters.get("PortXmitData", 0)
            )
            if duration_s <= 0 or rx_units < 0 or tx_units < 0:
                reset_or_wrap_count += 1
                previous = current
                continue
            rx_bytes = rx_units * DATA_UNIT_BYTES
            tx_bytes = tx_units * DATA_UNIT_BYTES
            rx_gbps = rx_bytes * 8.0 / duration_s / 1e9
            tx_gbps = tx_bytes * 8.0 / duration_s / 1e9
            rx_rates.append(rx_gbps)
            tx_rates.append(tx_gbps)
            total_rx_bytes += rx_bytes
            total_tx_bytes += tx_bytes
            total_duration_s += duration_s
            sequence = int(current["sequence"])
            aggregate_by_sequence[sequence]["rx_gbps"] += rx_gbps
            aggregate_by_sequence[sequence]["tx_gbps"] += tx_gbps
            wait_delta = int(curr_counters.get("PortXmitWait", 0)) - int(
                prev_counters.get("PortXmitWait", 0)
            )
            if wait_delta >= 0:
                xmit_wait_delta += wait_delta
            previous = current

        capacity = capacity_by_hca.get(hca)
        per_hca[hca] = {
            "capacity_gbps": capacity,
            "interval_duration_s": total_duration_s,
            "rx_bytes": total_rx_bytes,
            "tx_bytes": total_tx_bytes,
            "wire_avg_rx_gbps": (
                total_rx_bytes * 8.0 / total_duration_s / 1e9 if total_duration_s else None
            ),
            "wire_avg_tx_gbps": (
                total_tx_bytes * 8.0 / total_duration_s / 1e9 if total_duration_s else None
            ),
            "rx": stats(rx_rates, capacity),
            "tx": stats(tx_rates, capacity),
            "port_xmit_wait_delta": xmit_wait_delta,
            "reset_or_wrap_count": reset_or_wrap_count,
        }

    aggregate_rx = [item["rx_gbps"] for _, item in sorted(aggregate_by_sequence.items())]
    aggregate_tx = [item["tx_gbps"] for _, item in sorted(aggregate_by_sequence.items())]
    total_capacity = sum(capacity_by_hca.get(hca, 0.0) for hca in by_hca)
    return {
        "path": str(path),
        "node": metadata.get("node"),
        "hostname": metadata.get("hostname"),
        "interval_ms": metadata.get("interval_ms"),
        "perfquery_sha256": metadata.get("perfquery_sha256"),
        "input_sample_count": len(raw_samples),
        "selected_hcas": sorted(by_hca),
        "sample_error_count": len(sample_errors),
        "first_sample_errors": sample_errors[:20],
        "per_hca": per_hca,
        "dual_hca": {
            "capacity_gbps": total_capacity or None,
            "rx": stats(aggregate_rx, total_capacity or None),
            "tx": stats(aggregate_tx, total_capacity or None),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--start-epoch-s", type=float)
    parser.add_argument("--end-epoch-s", type=float)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = {
        "schema": "e44_hca_summary_v1",
        "data_counter_unit_bytes": DATA_UNIT_BYTES,
        "filter_start_epoch_s": args.start_epoch_s,
        "filter_end_epoch_s": args.end_epoch_s,
        "nodes": [
            summarize_file(path, args.start_epoch_s, args.end_epoch_s) for path in args.inputs
        ],
    }
    rendered = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
