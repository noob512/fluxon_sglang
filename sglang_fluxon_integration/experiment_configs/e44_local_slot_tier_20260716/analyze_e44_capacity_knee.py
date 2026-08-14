#!/usr/bin/env python3
"""Estimate the Fluxon host-capacity knee from KV lineage events.

This is a trace model, not a replacement for the paired cluster experiment.
It reports two deliberately separate curves:

* owner-local: a per-GPU shadow LRU reuse-distance curve;
* CPU backing: a cluster-wide demand-only LRU upper bound for current remote
  hits.

The production caches use Moka TinyLFU, pinning, asynchronous admission and
ordinary Put traffic that the r60/r61 lineage marker does not fully record.
Those differences are kept explicit in the output instead of being hidden in
an over-confident QPS prediction.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from analyze_e44_r60_kv_lineage import load_events


SUCCESS_TERMINAL = "load_back_consumed"
GIB = 1 << 30
DEFAULT_VALUE_BYTES = 4_718_592
DEFAULT_PROFILES = (0.50, 0.625, 0.75, 0.8125, 0.875, 0.9375, 1.0)


class Fenwick:
    def __init__(self, size: int) -> None:
        self.values = [0] * (size + 1)

    def add(self, index: int, delta: int) -> None:
        values = self.values
        while index < len(values):
            values[index] += delta
            index += index & -index

    def prefix_sum(self, index: int) -> int:
        total = 0
        values = self.values
        while index > 0:
            total += values[index]
            index -= index & -index
        return total


def percentile(values: list[int], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = quantile * (len(ordered) - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return float(ordered[lower])
    fraction = rank - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def distribution(values: list[int]) -> dict[str, float | int | None]:
    return {
        "count": len(values),
        "mean": sum(values) / len(values) if values else None,
        "p50": percentile(values, 0.50),
        "p90": percentile(values, 0.90),
        "p99": percentile(values, 0.99),
        "max": max(values) if values else None,
    }


def capacity_entries(nominal_gib: float, ratio: float, value_bytes: int) -> int:
    return math.floor(math.floor(nominal_gib * GIB) * ratio) // value_bytes


def capture(distances: Iterable[int], entries: int) -> tuple[int, int, float | None]:
    values = list(distances)
    captured = sum(distance < entries for distance in values)
    return captured, len(values), captured / len(values) if values else None


def owner_local_distances(events: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    nodes = sorted({str(event["node"]) for event in events})
    for node in nodes:
        node_events = [event for event in events if event["node"] == node]
        subevents: list[tuple[int, int, str, int, dict[str, Any]]] = []
        for event in node_events:
            subevents.append(
                (
                    int(event["plan_unix_ns"]),
                    0,
                    str(event.get("req", "")),
                    int(event["tp_rank"]),
                    event,
                )
            )
            subevents.append(
                (
                    int(event["terminal_unix_ns"]),
                    1,
                    str(event.get("req", "")),
                    int(event["tp_rank"]),
                    event,
                )
            )
        subevents.sort(key=lambda item: item[:4])

        max_positions = sum(len(event["key_ids"]) for event in node_events) * 2 + 1
        fenwick = Fenwick(max_positions)
        last_position: dict[tuple[int, str], int] = {}
        active_entries = 0
        position = 0
        distances_by_source: dict[str, list[int]] = defaultdict(list)
        cold_by_source: dict[str, int] = defaultdict(int)

        for _timestamp, phase, _req, tp_rank, event in subevents:
            if phase == 0:
                for key_id, source in zip(event["key_ids"], event["sources"]):
                    if source not in "LR":
                        continue
                    identity = (tp_rank, str(key_id))
                    position += 1
                    previous = last_position.get(identity)
                    if previous is None:
                        cold_by_source[source] += 1
                    else:
                        distances_by_source[source].append(
                            active_entries - fenwick.prefix_sum(previous)
                        )

                    # A local hit refreshes the owner-local policy. A remote
                    # probe is not admitted until its successful CPU terminal.
                    if source == "L":
                        if previous is None:
                            active_entries += 1
                        else:
                            fenwick.add(previous, -1)
                        fenwick.add(position, 1)
                        last_position[identity] = position
                continue

            if (
                event.get("terminal") != SUCCESS_TERMINAL
                or event.get("materialization") != "cpu_h2d"
            ):
                continue
            for key_id, source in zip(event["key_ids"], event["sources"]):
                if source != "R":
                    continue
                identity = (tp_rank, str(key_id))
                position += 1
                previous = last_position.get(identity)
                if previous is None:
                    active_entries += 1
                else:
                    fenwick.add(previous, -1)
                fenwick.add(position, 1)
                last_position[identity] = position

        known_all = distances_by_source["L"] + distances_by_source["R"]
        result[node] = {
            "plan_events": len(node_events),
            "infinite_shadow_entries": active_entries,
            "cold_references": dict(sorted(cold_by_source.items())),
            "known_reuse_distance_entries": {
                "all": distribution(known_all),
                "actual_local_source": distribution(distances_by_source["L"]),
                "actual_remote_source": distribution(distances_by_source["R"]),
            },
            "_known_all": known_all,
            "_known_local": distances_by_source["L"],
        }
    return result


def cpu_backing_distances(events: list[dict[str, Any]]) -> dict[str, Any]:
    references: list[tuple[int, str, int, int, str]] = []
    for event in events:
        for index, (key_id, source) in enumerate(
            zip(event["key_ids"], event["sources"])
        ):
            if source == "R":
                references.append(
                    (
                        int(event["plan_unix_ns"]),
                        str(event.get("req", "")),
                        int(event["tp_rank"]),
                        index,
                        str(key_id),
                    )
                )
    references.sort()

    fenwick = Fenwick(len(references) + 1)
    last_position: dict[tuple[int, str], int] = {}
    active_entries = 0
    distances: list[int] = []
    for position, (_timestamp, _req, tp_rank, _index, key_id) in enumerate(
        references, 1
    ):
        identity = (tp_rank, key_id)
        previous = last_position.get(identity)
        if previous is None:
            active_entries += 1
        else:
            distances.append(active_entries - fenwick.prefix_sum(previous))
            fenwick.add(previous, -1)
        fenwick.add(position, 1)
        last_position[identity] = position

    return {
        "remote_plan_references": len(references),
        "unique_demanded_entries": active_entries,
        "cold_references": len(references) - len(distances),
        "known_reuse_distance_entries": distribution(distances),
        "_distances": distances,
    }


def parse_profiles(raw: str) -> list[float]:
    profiles = sorted({float(item) for item in raw.split(",") if item.strip()})
    if not profiles or any(profile <= 0 for profile in profiles):
        raise ValueError("profiles must be positive comma-separated ratios")
    return profiles


def analyze(
    events: list[dict[str, Any]],
    profiles: list[float],
    value_bytes: int,
    gpu_nominal_gib: float,
    cpu_nominal_gib: float,
    owner_hot_ratio: float,
    replica_capacity_ratio: float,
) -> dict[str, Any]:
    local = owner_local_distances(events)
    cpu = cpu_backing_distances(events)
    profile_rows: list[dict[str, Any]] = []

    baseline_local_entries = capacity_entries(
        gpu_nominal_gib, owner_hot_ratio, value_bytes
    )
    for profile in profiles:
        local_entries = capacity_entries(
            gpu_nominal_gib * profile, owner_hot_ratio, value_bytes
        )
        cpu_entries = capacity_entries(
            cpu_nominal_gib * profile, replica_capacity_ratio, value_bytes
        )
        per_node: dict[str, Any] = {}
        for node, node_result in local.items():
            known_all = node_result["_known_all"]
            known_local = node_result["_known_local"]
            all_capture = capture(known_all, local_entries)
            local_capture = capture(known_local, local_entries)
            baseline_local_capture = capture(known_local, baseline_local_entries)[0]
            per_node[node] = {
                "shadow_all_known_reuse_capture": {
                    "captured": all_capture[0],
                    "total": all_capture[1],
                    "ratio": all_capture[2],
                },
                "baseline_actual_local_reference_capture": {
                    "captured": local_capture[0],
                    "total": local_capture[1],
                    "ratio": local_capture[2],
                    "normalized_to_100pct_threshold": (
                        min(1.0, local_capture[0] / baseline_local_capture)
                        if baseline_local_capture
                        else None
                    ),
                },
            }
        cpu_capture = capture(cpu["_distances"], cpu_entries)
        profile_rows.append(
            {
                "profile_ratio": profile,
                "nominal_capacity_gib": {
                    "gpu_owner_0": gpu_nominal_gib * profile,
                    "gpu_owner_1": gpu_nominal_gib * profile,
                    "cpu_backing": cpu_nominal_gib * profile,
                    "total": (2 * gpu_nominal_gib + cpu_nominal_gib) * profile,
                },
                "policy_capacity_entries": {
                    "owner_local_each": local_entries,
                    "cpu_backing": cpu_entries,
                },
                "owner_local": per_node,
                "cpu_backing_demand_only_reuse_capture_upper_bound": {
                    "captured": cpu_capture[0],
                    "total": cpu_capture[1],
                    "ratio": cpu_capture[2],
                },
            }
        )

    # The first profile retaining at least 99.5% of recurrent CPU demand is a
    # useful capacity-availability candidate. It is not a QPS acceptance test.
    candidates = [
        row
        for row in profile_rows
        if (
            row["cpu_backing_demand_only_reuse_capture_upper_bound"]["ratio"]
            or 0.0
        )
        >= 0.995
    ]
    availability_candidate = candidates[0]["profile_ratio"] if candidates else None

    for node_result in local.values():
        node_result.pop("_known_all")
        node_result.pop("_known_local")
    cpu.pop("_distances")
    return {
        "schema": "e44_capacity_knee_trace_model_v1",
        "input_event_count": len(events),
        "assumptions": {
            "value_bytes_per_tp_shard": value_bytes,
            "tokens_per_page": 64,
            "tensor_parallel_ranks": 2,
            "gpu_nominal_gib_each_at_100pct": gpu_nominal_gib,
            "cpu_nominal_gib_at_100pct": cpu_nominal_gib,
            "owner_hot_capacity_ratio": owner_hot_ratio,
            "master_replica_capacity_ratio": replica_capacity_ratio,
        },
        "owner_local_trace": local,
        "cpu_backing_trace": cpu,
        "profiles": profile_rows,
        "candidate": {
            "capacity_availability_knee_ratio": availability_candidate,
            "recommended_first_bracket_ratio": 0.75,
            "recommended_refinement_ratios_if_75pct_degrades": [0.875, 0.9375],
        },
        "limits": [
            "production Moka uses TinyLFU admission plus LRU residency, not pure LRU",
            "lineage omits the complete ordinary-Put admission stream, so local distances are optimistic",
            "CPU backing replay admits a key on first observed remote demand and is therefore an upper bound",
            "pinning and asynchronous terminal order make instantaneous evictable capacity lower than the nominal boundary",
            "capacity changes can alter cache-aware routing and the future trace; paired deterministic routing is required",
            "one baseline trace cannot identify a QPS curve; cluster points are needed to fit throughput",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="+", help="lineage logs as [node=]PATH")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--profiles", default=",".join(str(value) for value in DEFAULT_PROFILES)
    )
    parser.add_argument("--value-bytes", type=int, default=DEFAULT_VALUE_BYTES)
    parser.add_argument("--gpu-nominal-gib", type=float, default=128.0)
    parser.add_argument("--cpu-nominal-gib", type=float, default=256.0)
    parser.add_argument("--owner-hot-ratio", type=float, default=0.90)
    parser.add_argument("--replica-capacity-ratio", type=float, default=0.95)
    args = parser.parse_args()
    if args.value_bytes <= 0:
        parser.error("--value-bytes must be positive")
    result = analyze(
        load_events(args.inputs),
        parse_profiles(args.profiles),
        args.value_bytes,
        args.gpu_nominal_gib,
        args.cpu_nominal_gib,
        args.owner_hot_ratio,
        args.replica_capacity_ratio,
    )
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")


if __name__ == "__main__":
    main()
