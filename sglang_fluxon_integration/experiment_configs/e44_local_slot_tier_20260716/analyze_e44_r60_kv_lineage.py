#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


MARKER = "Fluxon KV lineage: "
SCHEMA = "e44_r60_kv_lineage_v1"
SUCCESS_TERMINAL = "load_back_consumed"


def input_files(path: Path) -> list[Path]:
    if path.is_dir():
        return sorted(candidate for candidate in path.rglob("*.log") if candidate.is_file())
    return [path]


def parse_input_spec(spec: str) -> tuple[str, Path]:
    if "=" in spec:
        node, raw_path = spec.split("=", 1)
        if node and raw_path:
            return node, Path(raw_path)
    path = Path(spec)
    return path.stem, path


def parse_line(line: str, node: str, source: Path, line_number: int) -> dict[str, Any] | None:
    marker_offset = line.find(MARKER)
    if marker_offset < 0:
        return None
    fragment = line[marker_offset + len(MARKER) :].lstrip()
    try:
        payload, _ = json.JSONDecoder().raw_decode(fragment)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{source}:{line_number}: invalid lineage JSON: {exc}") from exc
    if payload.get("schema") != SCHEMA:
        raise ValueError(
            f"{source}:{line_number}: unexpected schema {payload.get('schema')!r}"
        )
    keys = payload.get("key_ids")
    sources = payload.get("sources")
    if not isinstance(keys, list) or not isinstance(sources, str):
        raise ValueError(f"{source}:{line_number}: invalid keys/sources payload")
    if len(keys) != len(sources):
        raise ValueError(
            f"{source}:{line_number}: key/source length mismatch "
            f"keys={len(keys)} sources={len(sources)}"
        )
    if any(state not in "LRU" for state in sources):
        raise ValueError(f"{source}:{line_number}: invalid source state {sources!r}")
    transferable = int(payload.get("transferable_pages", -1))
    if transferable != len(keys):
        raise ValueError(
            f"{source}:{line_number}: transferable/key length mismatch "
            f"transferable={transferable} keys={len(keys)}"
        )
    payload["node"] = node
    payload["source_file"] = str(source)
    payload["line_number"] = line_number
    return payload


def load_events(specs: Iterable[str]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    seen_files: set[tuple[str, Path]] = set()
    for spec in specs:
        node, path = parse_input_spec(spec)
        for source in input_files(path):
            identity = (node, source.resolve())
            if identity in seen_files:
                continue
            seen_files.add(identity)
            with source.open("r", encoding="utf-8", errors="replace") as handle:
                for line_number, line in enumerate(handle, 1):
                    event = parse_line(line, node, source, line_number)
                    if event is not None:
                        events.append(event)
    return events


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = quantile * (len(ordered) - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    fraction = rank - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def distribution(values: list[float]) -> dict[str, float | int | None]:
    return {
        "count": len(values),
        "mean": sum(values) / len(values) if values else None,
        "p50": percentile(values, 0.50),
        "p90": percentile(values, 0.90),
        "p99": percentile(values, 0.99),
        "max": max(values) if values else None,
    }


def depth_bucket(depth: int) -> str:
    start = max(0, depth // 32 * 32)
    return f"{start:04d}-{start + 31:04d}"


def new_key_state() -> dict[str, Any]:
    return {
        "resident": False,
        "origin": "none",
        "local_since_ns": 0,
        "last_local_seen_ns": 0,
        "generation_reused": False,
        "generation_bucket": None,
        "generation_depth": None,
        "first_reuse_ns": 0,
        "reuse_observations": 0,
    }


def analyze(events: list[dict[str, Any]]) -> dict[str, Any]:
    counters: Counter[str] = Counter()
    node_tp: dict[str, Counter[str]] = defaultdict(Counter)
    bucket_counters: dict[str, Counter[str]] = defaultdict(Counter)
    key_states: dict[tuple[str, int, str], dict[str, Any]] = defaultdict(new_key_state)
    reuse_latency_ms: list[float] = []
    residence_to_loss_ms: list[float] = []
    generation_records: list[dict[str, Any]] = []
    loss_records: list[dict[str, Any]] = []

    subevents: list[tuple[int, int, dict[str, Any]]] = []
    for event in events:
        plan_ns = int(event.get("plan_unix_ns", 0))
        terminal_ns = int(event.get("terminal_unix_ns", 0))
        if plan_ns <= 0 or terminal_ns < plan_ns:
            raise ValueError(
                "lineage event has invalid plan/terminal timestamps: "
                f"plan={plan_ns} terminal={terminal_ns} req={event.get('req')}"
            )
        subevents.append((plan_ns, 0, event))
        subevents.append((terminal_ns, 1, event))
    subevents.sort(key=lambda item: (item[0], item[1], str(item[2].get("req", ""))))

    for timestamp_ns, phase, event in subevents:
        node = str(event["node"])
        tp_rank = int(event["tp_rank"])
        node_key = f"{node}/tp{tp_rank}"
        start_depth = int(event.get("start_depth_pages", 0))
        keys = [str(key) for key in event["key_ids"]]
        sources = str(event["sources"])
        materialization = str(event.get("materialization", "none"))
        successful = event.get("terminal") == SUCCESS_TERMINAL

        if phase == 0:
            counters["plan_events"] += 1
            node_tp[node_key]["plan_events"] += 1
            counters[f"terminal.{event.get('terminal', 'unknown')}"] += 1
            counters[f"materialization.{materialization}"] += 1
            for index, (key_id, source_state) in enumerate(zip(keys, sources)):
                bucket = depth_bucket(start_depth + index)
                bucket_counters[bucket][f"plan_source_{source_state}"] += 1
                counters[f"plan_source_{source_state}"] += 1
                node_tp[node_key][f"plan_source_{source_state}"] += 1
                state = key_states[(node, tp_rank, key_id)]
                if source_state == "U":
                    continue
                if source_state == "L":
                    counters["local_hit_observations"] += 1
                    if not state["resident"]:
                        state.update(
                            resident=True,
                            origin="baseline_local",
                            local_since_ns=timestamp_ns,
                            generation_reused=False,
                            generation_bucket=bucket,
                            generation_depth=start_depth + index,
                        )
                        counters["baseline_local_first_observed"] += 1
                    elif state["origin"] == "remote_cpu" and not state["generation_reused"]:
                        state["generation_reused"] = True
                        state["first_reuse_ns"] = timestamp_ns
                        counters["remote_cpu_generations_reused"] += 1
                        generation_bucket = str(state["generation_bucket"])
                        bucket_counters[generation_bucket]["remote_cpu_reused"] += 1
                        reuse_latency_ms.append(
                            (timestamp_ns - int(state["local_since_ns"])) / 1_000_000.0
                        )
                    if state["origin"] == "remote_cpu":
                        state["reuse_observations"] = int(
                            state["reuse_observations"]
                        ) + 1
                        counters["remote_cpu_reuse_observations"] += 1
                    state["last_local_seen_ns"] = timestamp_ns
                    continue

                counters["remote_source_observations"] += 1
                if state["resident"]:
                    counters["observed_local_to_remote_losses"] += 1
                    residence_to_loss_ms.append(
                        (timestamp_ns - int(state["local_since_ns"])) / 1_000_000.0
                    )
                    generation_bucket = str(state["generation_bucket"])
                    loss_record = {
                        "node": node,
                        "tp_rank": tp_rank,
                        "key_id": key_id,
                        "origin": state["origin"],
                        "depth": state["generation_depth"],
                        "local_since_ns": int(state["local_since_ns"]),
                        "last_local_seen_ns": int(state["last_local_seen_ns"]),
                        "loss_observed_ns": timestamp_ns,
                        "residence_lower_bound_ms": (
                            timestamp_ns - int(state["local_since_ns"])
                        )
                        / 1_000_000.0,
                        "reused": bool(state["generation_reused"]),
                    }
                    loss_records.append(loss_record)
                    if state["origin"] == "remote_cpu":
                        generation_records.append(
                            {
                                **loss_record,
                                "materialized_ns": int(state["local_since_ns"]),
                                "first_reuse_ns": int(state["first_reuse_ns"]),
                                "reuse_observations": int(
                                    state["reuse_observations"]
                                ),
                                "status": (
                                    "lost_after_reuse"
                                    if state["generation_reused"]
                                    else "lost_before_reuse"
                                ),
                            }
                        )
                        if state["generation_reused"]:
                            counters["remote_cpu_lost_after_reuse"] += 1
                            bucket_counters[generation_bucket]["remote_cpu_lost_after_reuse"] += 1
                        else:
                            counters["remote_cpu_lost_before_reuse"] += 1
                            bucket_counters[generation_bucket]["remote_cpu_lost_before_reuse"] += 1
                    state.update(
                        resident=False,
                        origin="none",
                        local_since_ns=0,
                        last_local_seen_ns=0,
                        generation_reused=False,
                        generation_bucket=None,
                        generation_depth=None,
                        first_reuse_ns=0,
                        reuse_observations=0,
                    )
            continue

        if not successful:
            counters["non_success_terminal_events"] += 1
            continue
        counters["success_terminal_events"] += 1
        node_tp[node_key]["success_terminal_events"] += 1
        for index, (key_id, source_state) in enumerate(zip(keys, sources)):
            if source_state != "R":
                continue
            bucket = depth_bucket(start_depth + index)
            if materialization == "gdr_h2d":
                counters["gdr_remote_terminal_pages"] += 1
                node_tp[node_key]["gdr_remote_terminal_pages"] += 1
                bucket_counters[bucket]["gdr_remote_terminal_pages"] += 1
                continue
            if materialization != "cpu_h2d":
                counters["remote_terminal_unknown_materialization_pages"] += 1
                continue
            counters["cpu_remote_terminal_pages"] += 1
            node_tp[node_key]["cpu_remote_terminal_pages"] += 1
            state = key_states[(node, tp_rank, key_id)]
            if state["resident"]:
                counters["cpu_terminal_already_local"] += 1
                bucket_counters[bucket]["cpu_terminal_already_local"] += 1
                continue
            state.update(
                resident=True,
                origin="remote_cpu",
                local_since_ns=timestamp_ns,
                last_local_seen_ns=0,
                generation_reused=False,
                generation_bucket=bucket,
                generation_depth=start_depth + index,
                first_reuse_ns=0,
                reuse_observations=0,
            )
            counters["remote_cpu_materializations"] += 1
            bucket_counters[bucket]["remote_cpu_materialized"] += 1

    for (node, tp_rank, key_id), state in key_states.items():
        if not state["resident"] or state["origin"] != "remote_cpu":
            continue
        bucket = str(state["generation_bucket"])
        generation_records.append(
            {
                "node": node,
                "tp_rank": tp_rank,
                "key_id": key_id,
                "origin": "remote_cpu",
                "depth": state["generation_depth"],
                "local_since_ns": int(state["local_since_ns"]),
                "materialized_ns": int(state["local_since_ns"]),
                "last_local_seen_ns": int(state["last_local_seen_ns"]),
                "first_reuse_ns": int(state["first_reuse_ns"]),
                "loss_observed_ns": 0,
                "reuse_observations": int(state["reuse_observations"]),
                "reused": bool(state["generation_reused"]),
                "status": (
                    "resident_after_reuse_at_end"
                    if state["generation_reused"]
                    else "unresolved_without_reuse_at_end"
                ),
            }
        )
        if state["generation_reused"]:
            counters["remote_cpu_resident_after_reuse_at_end"] += 1
            bucket_counters[bucket]["remote_cpu_resident_after_reuse_at_end"] += 1
        else:
            counters["remote_cpu_unresolved_without_reuse_at_end"] += 1
            bucket_counters[bucket]["remote_cpu_unresolved_without_reuse_at_end"] += 1

    materializations = counters["remote_cpu_materializations"]
    reused = counters["remote_cpu_generations_reused"]
    resolved = reused + counters["remote_cpu_lost_before_reuse"]
    return {
        "schema": "e44_r60_kv_lineage_analysis_v1",
        "input_event_count": len(events),
        "physical_key_count": len(key_states),
        "counters": dict(sorted(counters.items())),
        "rates": {
            "reuse_lower_bound_over_all_materializations": (
                reused / materializations if materializations else None
            ),
            "reuse_over_resolved_materializations": (
                reused / resolved if resolved else None
            ),
            "lost_before_reuse_over_all_materializations": (
                counters["remote_cpu_lost_before_reuse"] / materializations
                if materializations
                else None
            ),
            "unknown_source_fraction": (
                counters["plan_source_U"]
                / (
                    counters["plan_source_L"]
                    + counters["plan_source_R"]
                    + counters["plan_source_U"]
                )
                if counters["plan_source_L"]
                + counters["plan_source_R"]
                + counters["plan_source_U"]
                else None
            ),
        },
        "reuse_latency_ms": distribution(reuse_latency_ms),
        "residence_until_observed_loss_ms": distribution(residence_to_loss_ms),
        "by_node_tp": {
            key: dict(sorted(value.items())) for key, value in sorted(node_tp.items())
        },
        "by_absolute_depth_32_pages": {
            key: dict(sorted(value.items()))
            for key, value in sorted(bucket_counters.items())
        },
        "remote_cpu_generations": generation_records,
        "observed_local_losses": loss_records,
        "interpretation_limits": [
            "local-to-remote is observed at the next plan, not at the exact Moka eviction instant",
            "materializations still resident at run end are unresolved and are not labelled pollution",
            "U means the CPU plan extends beyond the GPU-classifiable prefix",
            "concurrent CPU terminals for a key already local are counted separately as cpu_terminal_already_local",
        ],
    }


def synthetic_event(
    req: str,
    plan_ns: int,
    terminal_ns: int,
    key: str,
    source: str,
    materialization: str,
) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "req": req,
        "node": "node0",
        "tp_rank": 0,
        "terminal": SUCCESS_TERMINAL,
        "plan_unix_ns": plan_ns,
        "terminal_unix_ns": terminal_ns,
        "plan_handle": 1,
        "start_depth_pages": 0,
        "requested_pages": 1,
        "transferable_pages": 1,
        "cpu_plan_pages": 1,
        "gpu_plan_pages": 1,
        "materialization": materialization,
        "gpu_direct_selected": int(materialization == "gdr_h2d"),
        "key_ids": [key],
        "sources": source,
    }


def self_test() -> None:
    events = [
        synthetic_event("a-load", 100, 200, "a", "R", "cpu_h2d"),
        synthetic_event("b-load", 110, 210, "b", "R", "cpu_h2d"),
        synthetic_event("c-load", 120, 220, "c", "R", "cpu_h2d"),
        synthetic_event("a-reuse", 300, 310, "a", "L", "cpu_h2d"),
        synthetic_event("a-loss", 400, 410, "a", "R", "gdr_h2d"),
        synthetic_event("b-loss", 420, 430, "b", "R", "gdr_h2d"),
        synthetic_event("d-gdr", 500, 510, "d", "R", "gdr_h2d"),
    ]
    result = analyze(events)
    counters = result["counters"]
    expected = {
        "remote_cpu_materializations": 3,
        "remote_cpu_generations_reused": 1,
        "remote_cpu_lost_after_reuse": 1,
        "remote_cpu_lost_before_reuse": 1,
        "remote_cpu_unresolved_without_reuse_at_end": 1,
        "gdr_remote_terminal_pages": 3,
    }
    for key, value in expected.items():
        if counters.get(key) != value:
            raise AssertionError(f"self-test {key}: expected={value} got={counters.get(key)}")
    records = result["remote_cpu_generations"]
    if {record["key_id"] for record in records} != {"a", "b", "c"}:
        raise AssertionError(f"self-test generation records are incomplete: {records}")
    sample_line = (
        "prefix "
        + MARKER
        + json.dumps(events[0], separators=(",", ":"))
        + "\x1b[0m\n"
    )
    parsed = parse_line(sample_line, "node0", Path("synthetic.log"), 1)
    if parsed is None or parsed["key_ids"] != ["a"]:
        raise AssertionError(f"self-test parser rejected a valid ANSI-suffixed line: {parsed}")
    print("e44 r60 KV lineage analyzer self-test: passed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="*")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if not args.inputs:
        parser.error("at least one input is required unless --self-test is used")
    result = analyze(load_events(args.inputs))
    encoded = json.dumps(result, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.write_text(encoded + "\n", encoding="utf-8")
    else:
        print(encoded)


if __name__ == "__main__":
    main()
