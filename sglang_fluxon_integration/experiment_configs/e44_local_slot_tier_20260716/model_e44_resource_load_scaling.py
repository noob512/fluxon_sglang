#!/usr/bin/env python3
"""Model the Fluxon remote-capacity knee as GPU workers and load change.

The model deliberately separates three quantities that are often conflated:

* active serving workers (a TP2 worker is one replica in E44);
* unique active sessions, which determine the host-visible KV working set;
* request concurrency, which determines offered load and transient pressure.

It reconstructs each session's longest host-visible KV prefix from the r61
lineage trace, validates that every shorter observation is a prefix of that
chain, and converts pages to physical TP bytes.  The capacity model is:

    effective_remote_knee = kappa * host_visible_working_set
    nominal_remote_knee   = effective_remote_knee / replica_capacity_ratio

``kappa=1`` is the working-set prediction.  A calibrated value is derived
from the independently fitted fixed-load QPS breakpoint.  Cross-worker QPS
is only projected for *matched per-worker shapes* (sessions/worker and
concurrency/worker both unchanged); other profiles report capacity but refuse
to invent a throughput extrapolation.

This is a trace-calibrated scaling model, not a full SGLang continuous-
batching simulator.  A new cluster anchor is still required for validation.
"""

from __future__ import annotations

import argparse
import ast
import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from analyze_e44_r60_kv_lineage import load_events
from simulate_e44_capacity_knee import parse_prometheus


GIB = 1 << 30
GROUP_RE = re.compile(r":agent_group:(\d+)\]")
SESSION_TURN_RE = re.compile(r":session:(\d+):turn:(\d+)\]")
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


@dataclass(frozen=True)
class RequestMeta:
    request_id: str
    group: int
    session: int
    turn: int
    prompt_tokens: int
    cached_tokens: int
    queue_time_s: float
    received_s: float
    finished_s: float


@dataclass(frozen=True)
class ProfileSpec:
    name: str
    workers: int
    sessions: int
    concurrency: int


def parse_validation_run(raw: str) -> tuple[float, Path]:
    capacity, separator, artifact = raw.partition("=")
    if not separator or not capacity or not artifact:
        raise argparse.ArgumentTypeError(
            "validation run must be CAPACITY_GIB=ARTIFACT_DIR"
        )
    try:
        parsed_capacity = float(capacity)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid capacity: {capacity}") from exc
    return parsed_capacity, Path(artifact)


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = quantile * (len(ordered) - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return float(ordered[lower])
    fraction = rank - lower
    return float(ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction)


def distribution(values: Iterable[float]) -> dict[str, float | int | None]:
    materialized = list(values)
    return {
        "count": len(materialized),
        "mean": sum(materialized) / len(materialized) if materialized else None,
        "p50": percentile(materialized, 0.50),
        "p90": percentile(materialized, 0.90),
        "p99": percentile(materialized, 0.99),
        "max": max(materialized) if materialized else None,
    }


def input_files(path: Path) -> list[Path]:
    if path.is_dir():
        return sorted(candidate for candidate in path.rglob("*.log") if candidate.is_file())
    return [path]


def load_request_metrics(paths: Iterable[Path]) -> tuple[dict[str, RequestMeta], dict[str, int]]:
    requests: dict[str, RequestMeta] = {}
    counters = {
        "json_records": 0,
        "records_with_request_id": 0,
        "mapped_requests": 0,
        "ignored_without_workload_marker": 0,
        "duplicate_identical": 0,
    }
    seen_files: set[Path] = set()
    for path in paths:
        for source in input_files(path):
            resolved = source.resolve()
            if resolved in seen_files:
                continue
            seen_files.add(resolved)
            with source.open("r", encoding="utf-8", errors="replace") as handle:
                for line_number, line in enumerate(handle, 1):
                    if not line.startswith("{"):
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise ValueError(f"{source}:{line_number}: invalid metrics JSON") from exc
                    counters["json_records"] += 1
                    request_id = record.get("id")
                    if not isinstance(request_id, str) or not request_id:
                        continue
                    counters["records_with_request_id"] += 1
                    raw_parameters = record.get("request_parameters")
                    if not isinstance(raw_parameters, str):
                        counters["ignored_without_workload_marker"] += 1
                        continue
                    try:
                        parameters = json.loads(raw_parameters)
                    except json.JSONDecodeError as exc:
                        raise ValueError(
                            f"{source}:{line_number}: invalid nested request_parameters"
                        ) from exc
                    text = parameters.get("text")
                    if not isinstance(text, str):
                        counters["ignored_without_workload_marker"] += 1
                        continue
                    groups = GROUP_RE.findall(text)
                    session_turns = SESSION_TURN_RE.findall(text)
                    if not groups or not session_turns:
                        counters["ignored_without_workload_marker"] += 1
                        continue
                    group_values = {int(value) for value in groups}
                    session_values = {int(session) for session, _turn in session_turns}
                    if len(group_values) != 1 or len(session_values) != 1:
                        raise ValueError(
                            f"{source}:{line_number}: request spans multiple group/session ids"
                        )
                    group = next(iter(group_values))
                    session = next(iter(session_values))
                    turn = max(int(value) for _session, value in session_turns)
                    meta = RequestMeta(
                        request_id=request_id,
                        group=group,
                        session=session,
                        turn=turn,
                        prompt_tokens=int(record.get("prompt_tokens", 0)),
                        cached_tokens=int(record.get("cached_tokens", 0)),
                        queue_time_s=float(record.get("queue_time", 0.0)),
                        received_s=float(record.get("request_received_ts", 0.0)),
                        finished_s=float(record.get("request_finished_ts", 0.0)),
                    )
                    previous = requests.get(request_id)
                    if previous is not None:
                        if previous != meta:
                            raise ValueError(
                                f"request id {request_id} maps to conflicting metadata"
                            )
                        counters["duplicate_identical"] += 1
                        continue
                    requests[request_id] = meta
    counters["mapped_requests"] = len(requests)
    return requests, counters


def optional_metric_delta(
    before: dict[tuple[str, tuple[tuple[str, str], ...]], float],
    after: dict[tuple[str, tuple[tuple[str, str], ...]], float],
    metric: str,
    required_labels: dict[str, str | int],
) -> float:
    expected = {key: str(value) for key, value in required_labels.items()}
    matches: list[float] = []
    for identity, after_value in after.items():
        name, labels_tuple = identity
        if name != metric:
            continue
        labels = dict(labels_tuple)
        if all(labels.get(key) == value for key, value in expected.items()):
            matches.append(after_value - before.get(identity, 0.0))
    if len(matches) > 1:
        raise ValueError(
            f"multiple metric matches: metric={metric} labels={expected}"
        )
    return matches[0] if matches else 0.0


def load_validation_run(capacity_gib: float, artifact: Path) -> dict[str, Any]:
    summary = json.loads(
        (artifact / "workload_result" / "summary.json").read_text(encoding="utf-8")
    )["router_agent"]
    request = summary["request_summary"]
    cache = summary["cache_summary"]
    if int(request["error_count"]) != 0:
        raise ValueError(f"validation artifact has request errors: {artifact}")

    master_paths = sorted((artifact / "node0").glob("master_*.log"))
    if len(master_paths) != 1:
        raise ValueError(f"expected one master log in {artifact}")
    master_lines = [
        ANSI_RE.sub("", line)
        for line in master_paths[0]
        .read_text(encoding="utf-8", errors="replace")
        .splitlines()
    ]
    runtime = [
        line
        for line in master_lines
        if "replica cache runtime: owner=sglang_l13_owner_remote_cache_cpu0" in line
    ][-1]
    runtime_match = re.search(
        r"entries=(\d+) weighted_bytes=(\d+) effective_capacity_bytes=(\d+).*? "
        r"reclaim_completed=(\d+)",
        runtime,
    )
    if runtime_match is None:
        raise ValueError(f"cannot parse CPU runtime snapshot: {master_paths[0]}")
    entries, weighted_bytes, effective_bytes, reclaim = map(
        int, runtime_match.groups()
    )
    placement = [
        line for line in master_lines if "placement historical distribution" in line
    ][-1]
    raw_source_bytes = placement.split("get_requester_source_bytes=", 1)[1].split(
        " | get_allocation_mode_counts=", 1
    )[0]
    remote_source_bytes = sum(
        value for _identity, value in ast.literal_eval(raw_source_bytes)
    )

    local_size_evictions = 0
    for node in ("node0", "node1"):
        owner_lines = [
            ANSI_RE.sub("", line)
            for line in (artifact / node / "owner.log")
            .read_text(encoding="utf-8", errors="replace")
            .splitlines()
        ]
        snapshots = [
            line
            for line in owner_lines
            if "owner hot source-eviction policy snapshot" in line
        ]
        match = re.search(r"size_evictions=(\d+)", snapshots[-1])
        if match is None:
            raise ValueError(f"cannot parse owner size evictions: {artifact / node}")
        local_size_evictions += int(match.group(1))

    queue_sum = 0.0
    queue_count = 0.0
    compute_tokens = 0.0
    cache_tokens = 0.0
    metrics_dir = artifact / "workload_result" / "metrics"
    active_nodes: list[str] = []
    for node in ("node0", "node1"):
        node_prompt_tokens = float(cache["per_node"][node]["prompt_tokens_total"])
        if node_prompt_tokens > 0:
            active_nodes.append(node)
        before = parse_prometheus(metrics_dir / f"router_agent.before.{node}.sglang.prom")
        after = parse_prometheus(metrics_dir / f"router_agent.after.{node}.sglang.prom")
        rank0 = {"tp_rank": 0}
        queue_sum += optional_metric_delta(
            before, after, "sglang:queue_time_seconds_sum", rank0
        )
        queue_count += optional_metric_delta(
            before, after, "sglang:queue_time_seconds_count", rank0
        )
        compute_tokens += optional_metric_delta(
            before,
            after,
            "sglang:realtime_tokens_total",
            {"tp_rank": 0, "mode": "prefill_compute"},
        )
        cache_tokens += optional_metric_delta(
            before,
            after,
            "sglang:realtime_tokens_total",
            {"tp_rank": 0, "mode": "prefill_cache"},
        )

    hca = json.loads(
        (artifact / "hca_summary_formal.json").read_text(encoding="utf-8")
    )
    cpu_hca = next(node for node in hca["nodes"] if node["node"] == "cpu")
    cpu_tx_bytes = sum(item["tx_bytes"] for item in cpu_hca["per_hca"].values())
    return {
        "capacity_gib": capacity_gib,
        "artifact": str(artifact),
        "request_count": int(request["request_count"]),
        "qps": float(request["request_qps"]),
        "wall_s": float(request["wall_duration_s"]),
        "ttft_mean_s": float(request["ttft_mean_s"]),
        "total_hit_rate": float(cache["overall_hit_rate"]),
        "l1_hit_rate": float(cache["l1_hit_rate"]),
        "l3_hit_rate": float(cache["l3_hit_rate"]),
        "active_nodes": active_nodes,
        "prefill_compute_mtokens": compute_tokens / 1e6,
        "prefill_cache_mtokens": cache_tokens / 1e6,
        "queue_mean_s": queue_sum / queue_count if queue_count else 0.0,
        "cpu_entries": entries,
        "cpu_weighted_gib": weighted_bytes / GIB,
        "cpu_effective_gib": effective_bytes / GIB,
        "cpu_occupancy": weighted_bytes / effective_bytes,
        "reclaim_completed": reclaim,
        "remote_source_tb": remote_source_bytes / 1e12,
        "local_size_evictions": local_size_evictions,
        "cpu_hca_tx_tb": cpu_tx_bytes / 1e12,
        "hca_sample_errors": sum(
            int(node["sample_error_count"]) for node in hca["nodes"]
        ),
    }


def logical_lineage(
    events: list[dict[str, Any]],
    requests: dict[str, RequestMeta],
    tp_size: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    by_operation: dict[tuple[str, int], dict[int, dict[str, Any]]] = {}
    unmapped: set[str] = set()
    for event in events:
        request_id = str(event.get("req", ""))
        if request_id not in requests:
            unmapped.add(request_id)
            continue
        operation = (request_id, int(event.get("plan_handle", -1)))
        rank = int(event["tp_rank"])
        ranks = by_operation.setdefault(operation, {})
        if rank in ranks:
            raise ValueError(f"duplicate lineage rank for operation={operation} rank={rank}")
        ranks[rank] = event
    if unmapped:
        raise ValueError(f"lineage contains {len(unmapped)} unmapped request ids")

    logical: list[dict[str, Any]] = []
    key_depth_mismatch = 0
    source_mismatch = 0
    for operation, ranks in by_operation.items():
        if set(ranks) != set(range(tp_size)):
            raise ValueError(
                f"operation={operation} ranks={sorted(ranks)} expected=0..{tp_size - 1}"
            )
        reference = ranks[0]
        operation_key_depth_mismatch = False
        for rank in range(1, tp_size):
            peer = ranks[rank]
            if str(peer["node"]) != str(reference["node"]):
                raise ValueError(
                    f"operation={operation} spans nodes "
                    f"{reference['node']!r}/{peer['node']!r}"
                )
            if (
                peer["key_ids"] != reference["key_ids"]
                or int(peer["start_depth_pages"])
                != int(reference["start_depth_pages"])
            ):
                key_depth_mismatch += 1
                operation_key_depth_mismatch = True
            if peer["sources"] != reference["sources"]:
                source_mismatch += 1
        if operation_key_depth_mismatch:
            continue
        meta = requests[operation[0]]
        logical.append(
            {
                "request_id": operation[0],
                "plan_handle": operation[1],
                "group": meta.group,
                "session": meta.session,
                "turn": meta.turn,
                "node": str(reference["node"]),
                "plan_unix_ns": int(reference["plan_unix_ns"]),
                "terminal_unix_ns": int(reference["terminal_unix_ns"]),
                "keys": tuple(str(key) for key in reference["key_ids"]),
                "sources": str(reference["sources"]),
            }
        )
    if key_depth_mismatch:
        raise ValueError(
            f"{key_depth_mismatch} TP operations disagree on key/depth sequence"
        )
    logical.sort(key=lambda item: (item["plan_unix_ns"], item["request_id"]))
    return logical, {
        "physical_events": len(events),
        "logical_operations": len(logical),
        "tp_key_depth_mismatches": key_depth_mismatch,
        "tp_source_mismatches": source_mismatch,
        "unmapped_request_ids": len(unmapped),
    }


def build_session_chains(
    logical: list[dict[str, Any]], requests: dict[str, RequestMeta]
) -> tuple[dict[int, tuple[str, ...]], dict[str, Any]]:
    observations: dict[int, list[tuple[str, ...]]] = {}
    turns: dict[int, set[int]] = {}
    group_to_session: dict[int, int] = {}
    for meta in requests.values():
        previous = group_to_session.setdefault(meta.group, meta.session)
        if previous != meta.session:
            raise ValueError(f"group {meta.group} maps to multiple sessions")
    for event in logical:
        group = int(event["group"])
        observations.setdefault(group, []).append(event["keys"])
        turns.setdefault(group, set()).add(int(event["turn"]))

    chains: dict[int, tuple[str, ...]] = {}
    prefix_violations = 0
    for group, candidates in observations.items():
        longest = max(candidates, key=len)
        for candidate in candidates:
            if longest[: len(candidate)] != candidate:
                prefix_violations += 1
        chains[group] = longest
    if prefix_violations:
        raise ValueError(f"lineage has {prefix_violations} non-prefix session observations")

    request_turns: dict[int, set[int]] = {}
    prompt_tokens: dict[int, list[int]] = {}
    for meta in requests.values():
        request_turns.setdefault(meta.group, set()).add(meta.turn)
        prompt_tokens.setdefault(meta.group, []).append(meta.prompt_tokens)
    groups = sorted(group_to_session)
    missing_lineage_groups = [group for group in groups if group not in chains]
    return chains, {
        "groups_in_requests": len(groups),
        "groups_in_lineage": len(chains),
        "missing_lineage_groups": missing_lineage_groups,
        "group_equals_session_count": sum(
            group == session for group, session in group_to_session.items()
        ),
        "prefix_violations": prefix_violations,
        "requests_per_group": distribution(
            [float(len(request_turns[group])) for group in groups]
        ),
        "lineage_turns_per_group": distribution(
            [float(len(turns.get(group, set()))) for group in groups]
        ),
        "host_visible_pages_per_group": distribution(
            [float(len(chains.get(group, ()))) for group in groups]
        ),
        "max_prompt_tokens_per_group": distribution(
            [float(max(prompt_tokens[group])) for group in groups]
        ),
    }


def parse_profile(raw: str) -> ProfileSpec:
    parts = raw.split(":")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError(
            "profile must be NAME:WORKERS:SESSIONS:CONCURRENCY"
        )
    name, raw_workers, raw_sessions, raw_concurrency = parts
    try:
        workers = int(raw_workers)
        sessions = int(raw_sessions)
        concurrency = int(raw_concurrency)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid profile integers: {raw}") from exc
    if not name or min(workers, sessions, concurrency) <= 0:
        raise argparse.ArgumentTypeError(f"invalid profile: {raw}")
    return ProfileSpec(name, workers, sessions, concurrency)


def piecewise_predict(model: dict[str, Any], capacity_gib: float) -> float:
    intercept, pre_slope, slope_change = model["coefficients"]
    breakpoint = float(model["breakpoint_gib"])
    return float(
        intercept
        + pre_slope * capacity_gib
        + slope_change * max(0.0, capacity_gib - breakpoint)
    )


def selected_groups(chains: dict[int, tuple[str, ...]], sessions: int) -> list[int]:
    groups = sorted(chains)
    if sessions > len(groups):
        raise ValueError(
            f"profile requests {sessions} sessions but trace only has {len(groups)}"
        )
    expected = list(range(sessions))
    if groups[:sessions] != expected:
        raise ValueError("trace groups are not contiguous from zero")
    return expected


def make_profile(
    spec: ProfileSpec,
    chains: dict[int, tuple[str, ...]],
    *,
    tp_size: int,
    value_bytes: int,
    gpu_owner_nominal_gib: float,
    owner_payload_ratio: float,
    replica_capacity_ratio: float,
    calibration_kappa: float,
    base_workers: int,
    base_sessions: int,
    base_concurrency: int,
    base_wss_gib: float,
    base_plateau_qps: float,
    piecewise_model: dict[str, Any],
    validation_capacities: list[float],
) -> dict[str, Any]:
    groups = selected_groups(chains, spec.sessions)
    bytes_per_page = tp_size * value_bytes
    worker_pages = [0] * spec.workers
    for group in groups:
        worker_pages[group % spec.workers] += len(chains[group])
    worker_wss_gib = [pages * bytes_per_page / GIB for pages in worker_pages]
    global_wss_gib = sum(worker_wss_gib)
    local_effective_gib = gpu_owner_nominal_gib * owner_payload_ratio
    local_pressure = [value / local_effective_gib for value in worker_wss_gib]
    local_fit = max(local_pressure) <= 1.0
    theoretical_knee = global_wss_gib / replica_capacity_ratio
    calibrated_knee = (
        global_wss_gib * calibration_kappa / replica_capacity_ratio
    )

    base_sessions_per_worker = base_sessions / base_workers
    base_concurrency_per_worker = base_concurrency / base_workers
    sessions_per_worker = spec.sessions / spec.workers
    concurrency_per_worker = spec.concurrency / spec.workers
    matched_shape = math.isclose(
        sessions_per_worker, base_sessions_per_worker
    ) and math.isclose(concurrency_per_worker, base_concurrency_per_worker)
    qps_projection: dict[str, Any]
    if matched_shape:
        worker_scale = spec.workers / base_workers
        capacity_scale = global_wss_gib / base_wss_gib
        residual_band = (
            float(piecewise_model["rmse_qps"]) * worker_scale * 1.2815515655446004
        )
        candidates = []
        for capacity in validation_capacities:
            base_equivalent = capacity / capacity_scale
            predicted = piecewise_predict(piecewise_model, base_equivalent) * worker_scale
            candidates.append(
                {
                    "nominal_remote_gib": capacity,
                    "base_equivalent_remote_gib": base_equivalent,
                    "predicted_qps": predicted,
                    "empirical_residual_p10": predicted - residual_band,
                    "empirical_residual_p90": predicted + residual_band,
                }
            )
        qps_projection = {
            "available": True,
            "reason": "sessions/worker and concurrency/worker match the baseline",
            "plateau_qps": base_plateau_qps * worker_scale,
            "plateau_wall_s": (spec.sessions * 24)
            / (base_plateau_qps * worker_scale),
            "capacity_scale_vs_base": capacity_scale,
            "validation_candidates": candidates,
        }
    else:
        qps_projection = {
            "available": False,
            "reason": (
                "per-worker session or concurrency shape differs; one baseline cannot "
                "identify batching/queue scaling"
            ),
            "plateau_qps": None,
            "plateau_wall_s": None,
            "capacity_scale_vs_base": global_wss_gib / base_wss_gib,
            "validation_candidates": [],
        }

    return {
        **asdict(spec),
        "selected_group_range": [groups[0], groups[-1]],
        "host_visible_pages": sum(worker_pages),
        "global_host_visible_wss_gib": global_wss_gib,
        "worker_host_visible_wss_gib": worker_wss_gib,
        "worker_local_effective_gib": local_effective_gib,
        "worker_local_pressure_ratio": local_pressure,
        "all_worker_working_sets_fit_local": local_fit,
        "remote_knee_is_performance_critical": not local_fit,
        "remote_knee_interpretation": (
            "local working sets fit; remote remains durability/tier1 backing but is not "
            "predicted to set the hit-rate knee"
            if local_fit
            else "at least one worker churns local; global remote working-set coverage matters"
        ),
        "theoretical_nominal_remote_knee_gib": theoretical_knee,
        "calibrated_nominal_remote_knee_gib": calibrated_knee,
        "sessions_per_worker": sessions_per_worker,
        "concurrency_per_worker": concurrency_per_worker,
        "qps_projection": qps_projection,
    }


def validate_cluster_runs(
    runs: list[dict[str, Any]],
    primary_profile: dict[str, Any],
    service_anchor_capacity_gib: float,
) -> dict[str, Any]:
    if len(runs) < 2:
        raise ValueError("at least two validation runs are required")
    runs = sorted(runs, key=lambda run: float(run["capacity_gib"]))
    projected = {
        float(row["nominal_remote_gib"]): row
        for row in primary_profile["qps_projection"]["validation_candidates"]
    }
    for run in runs:
        capacity = float(run["capacity_gib"])
        if capacity not in projected:
            raise ValueError(f"no QPS projection for validation capacity {capacity}")
        predicted = float(projected[capacity]["predicted_qps"])
        run["raw_predicted_qps"] = predicted
        run["raw_qps_error_percent"] = 100.0 * (predicted - run["qps"]) / run["qps"]

    by_capacity = {float(run["capacity_gib"]): run for run in runs}
    if service_anchor_capacity_gib not in by_capacity:
        raise ValueError(
            f"service anchor {service_anchor_capacity_gib} is absent from validation runs"
        )
    anchor = by_capacity[service_anchor_capacity_gib]
    service_rate_factor = anchor["qps"] / anchor["raw_predicted_qps"]
    for run in runs:
        corrected = run["raw_predicted_qps"] * service_rate_factor
        run["anchor_corrected_predicted_qps"] = corrected
        run["anchor_corrected_qps_error_percent"] = (
            100.0 * (corrected - run["qps"]) / run["qps"]
        )
        run["is_service_anchor"] = (
            float(run["capacity_gib"]) == service_anchor_capacity_gib
        )

    positive_reclaim = [
        float(run["capacity_gib"])
        for run in runs
        if int(run["reclaim_completed"]) > 0
    ]
    zero_reclaim = [
        float(run["capacity_gib"])
        for run in runs
        if int(run["reclaim_completed"]) == 0
    ]
    lower = max(positive_reclaim) if positive_reclaim else None
    upper = min(zero_reclaim) if zero_reclaim else None
    predicted_knee = float(primary_profile["calibrated_nominal_remote_knee_gib"])
    knee_bracket_valid = (
        lower is not None and upper is not None and lower < predicted_knee <= upper
    )

    plateau_runs = [run for run in runs if int(run["reclaim_completed"]) == 0]
    plateau_qps_spread_percent = None
    if len(plateau_runs) >= 2:
        plateau_qps = [float(run["qps"]) for run in plateau_runs]
        plateau_qps_spread_percent = (
            100.0 * (max(plateau_qps) - min(plateau_qps)) / min(plateau_qps)
        )
    heldout = [run for run in runs if not run["is_service_anchor"]]
    max_raw_error = max(abs(float(run["raw_qps_error_percent"])) for run in runs)
    max_corrected_heldout_error = max(
        abs(float(run["anchor_corrected_qps_error_percent"])) for run in heldout
    )
    checks = {
        "capacity_knee_inside_reclaim_bracket": knee_bracket_valid,
        "plateau_qps_spread_le_1_percent": (
            plateau_qps_spread_percent is not None
            and plateau_qps_spread_percent <= 1.0
        ),
        "raw_cross_worker_qps_error_le_5_percent": max_raw_error <= 5.0,
        "one_anchor_corrected_heldout_qps_error_le_5_percent": (
            max_corrected_heldout_error <= 5.0
        ),
        "all_runs_single_active_worker": all(
            run["active_nodes"] == ["node0"] for run in runs
        ),
        "all_runs_hca_sample_errors_zero": all(
            int(run["hca_sample_errors"]) == 0 for run in runs
        ),
    }
    return {
        "schema": "e44_resource_load_scaling_validation_v1",
        "service_anchor_capacity_gib": service_anchor_capacity_gib,
        "service_rate_factor": service_rate_factor,
        "reclaim_knee_bracket_gib": [lower, upper],
        "predicted_knee_gib": predicted_knee,
        "plateau_qps_spread_percent": plateau_qps_spread_percent,
        "max_raw_qps_error_percent": max_raw_error,
        "max_anchor_corrected_heldout_qps_error_percent": (
            max_corrected_heldout_error
        ),
        "checks": checks,
        "capacity_model_validated": (
            checks["capacity_knee_inside_reclaim_bracket"]
            and checks["plateau_qps_spread_le_1_percent"]
        ),
        "raw_worker_linear_qps_scaling_rejected": not checks[
            "raw_cross_worker_qps_error_le_5_percent"
        ],
        "one_anchor_throughput_model_validated": checks[
            "one_anchor_corrected_heldout_qps_error_le_5_percent"
        ],
        "runs": runs,
    }


def render_markdown(result: dict[str, Any]) -> str:
    calibration = result["calibration"]
    audit = result["trace_audit"]
    lines = [
        "# Fluxon GPU/请求量—容量拐点联合模型",
        "",
        f"生成时间：{result['generated_at']}",
        "",
        "## 结论",
        "",
        f"- r61逐KV trace重建的96-session host-visible物理工作集为"
        f"`{calibration['base_host_visible_wss_gib']:.3f} GiB`；",
        f"- 不使用QPS拟合时，工作集模型预测名义remote knee="
        f"`{calibration['theoretical_base_knee_gib']:.1f} GiB`；实测QPS分段拐点="
        f"`{calibration['observed_breakpoint_gib']:.1f} GiB`，误差="
        f"`{calibration['theoretical_error_percent']:+.3f}%`；",
        f"- 校准系数`kappa={calibration['kappa']:.6f}`，即有效容量只需比trace工作集多"
        f"`{(calibration['kappa'] - 1.0) * 100:.3f}%`；",
        "- 只有sessions/worker与concurrency/worker同时保持不变时，当前数据才允许缩放QPS；"
        "其他组合只预测容量，并明确拒绝吞吐外推。",
        "",
        "## Trace 完整性",
        "",
        f"- request metrics映射`{audit['request_metrics']['mapped_requests']}`个正式请求；",
        f"- lineage物理/逻辑事件=`{audit['lineage']['physical_events']}/"
        f"{audit['lineage']['logical_operations']}`，TP key/depth mismatch="
        f"`{audit['lineage']['tp_key_depth_mismatches']}`，合法source mismatch="
        f"`{audit['lineage']['tp_source_mismatches']}`；",
        f"- session prefix violation=`{audit['sessions']['prefix_violations']}`，"
        f"host-visible pages/session均值=`{audit['sessions']['host_visible_pages_per_group']['mean']:.3f}`。",
        "",
        "## 资源与负载预测",
        "",
        "| Profile | workers | sessions | c | global WSS | max local pressure | remote knee | critical | plateau QPS |",
        "|---|---:|---:|---:|---:|---:|---:|:---:|---:|",
    ]
    for profile in result["profiles"]:
        plateau = profile["qps_projection"]["plateau_qps"]
        lines.append(
            f"| {profile['name']} | {profile['workers']} | {profile['sessions']} | "
            f"{profile['concurrency']} | {profile['global_host_visible_wss_gib']:.3f} GiB | "
            f"{max(profile['worker_local_pressure_ratio']):.3f} | "
            f"{profile['calibrated_nominal_remote_knee_gib']:.1f} GiB | "
            f"{'yes' if profile['remote_knee_is_performance_critical'] else 'no'} | "
            f"{f'{plateau:.3f}' if plateau is not None else '不可识别'} |"
        )
    validation = result.get("cluster_validation")
    if validation is not None:
        lines.extend(
            [
                "",
                "## 新集群验证",
                "",
                f"容量reclaim拐点区间=`({validation['reclaim_knee_bracket_gib'][0]:g}, "
                f"{validation['reclaim_knee_bracket_gib'][1]:g}] GiB`，模型预测="
                f"`{validation['predicted_knee_gib']:.3f} GiB`；",
                "",
                "| remote | QPS | hit | reclaim | raw预测 | 单锚点修正预测 | 修正误差 |",
                "|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for run in validation["runs"]:
            lines.append(
                f"| {run['capacity_gib']:g} GiB | {run['qps']:.6f} | "
                f"{run['total_hit_rate']*100:.3f}% | {run['reclaim_completed']} | "
                f"{run['raw_predicted_qps']:.3f} | "
                f"{run['anchor_corrected_predicted_qps']:.3f} | "
                f"{run['anchor_corrected_qps_error_percent']:+.2f}% |"
            )
        lines.extend(
            [
                "",
                f"- 145→160 GiB平台QPS spread=`{validation['plateau_qps_spread_percent']:.3f}%`；",
                f"- 原始worker线性缩放最大误差=`{validation['max_raw_qps_error_percent']:.2f}%`，"
                "已拒绝；",
                f"- 用145 GiB单点校准worker service rate后，128/160两个留出点最大误差="
                f"`{validation['max_anchor_corrected_heldout_qps_error_percent']:.2f}%`。",
            ]
        )
    lines.extend(
        [
            "",
            "## 模型边界",
            "",
            "- active worker指实际承载请求的TP2副本；空闲但仍启动的worker不计入消费能力；",
            "- session数量改变唯一KV工作集；单纯重复更多turn只有在产生新host-visible key时才增加容量；",
            "- concurrency主要改变batching、queue、pin和瞬态压力。当前只有c/worker=12的锚点，"
            "不能拟合任意concurrency的QPS；",
            "- local-fit profile中，remote仍可保存tier1/proactive副本，但预计不再决定命中和吞吐拐点；",
            "- 模型使用r61真实key轨迹和r69–r73/r67容量响应；新GPU/负载形状必须由集群点验收。",
            "",
        ]
    )
    return "\n".join(lines)


def self_test() -> None:
    model = {
        "breakpoint_gib": 100.0,
        "coefficients": [1.0, 0.1, -0.1],
        "rmse_qps": 0.2,
    }
    assert piecewise_predict(model, 50.0) == 6.0
    assert piecewise_predict(model, 150.0) == 11.0
    assert parse_profile("matched:1:48:12") == ProfileSpec("matched", 1, 48, 12)
    assert percentile([1.0, 3.0], 0.5) == 2.0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lineage", action="append", default=[])
    parser.add_argument("--request-metrics", type=Path, action="append", default=[])
    parser.add_argument("--capacity-model", type=Path)
    parser.add_argument("--profile", type=parse_profile, action="append", default=[])
    parser.add_argument(
        "--validation-capacity", type=float, action="append", default=[]
    )
    parser.add_argument(
        "--validation-run", type=parse_validation_run, action="append", default=[]
    )
    parser.add_argument("--service-anchor-capacity", type=float, default=145.0)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--generated-at", default="2026-07-24 HKT")
    parser.add_argument("--tp-size", type=int, default=2)
    parser.add_argument("--value-bytes", type=int, default=4_718_592)
    parser.add_argument("--gpu-owner-nominal-gib", type=float, default=128.0)
    parser.add_argument("--owner-payload-ratio", type=float, default=0.90)
    parser.add_argument("--replica-capacity-ratio", type=float, default=0.95)
    parser.add_argument("--base-workers", type=int, default=2)
    parser.add_argument("--base-sessions", type=int, default=96)
    parser.add_argument("--base-concurrency", type=int, default=24)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        print("self-test passed")
        if not args.lineage:
            return 0
    required = {
        "--lineage": args.lineage,
        "--request-metrics": args.request_metrics,
        "--capacity-model": args.capacity_model,
        "--output": args.output,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        parser.error(f"missing required arguments: {', '.join(missing)}")
    if not 0 < args.owner_payload_ratio <= 1:
        parser.error("owner payload ratio must be in (0,1]")
    if not 0 < args.replica_capacity_ratio <= 1:
        parser.error("replica capacity ratio must be in (0,1]")

    requests, request_counters = load_request_metrics(args.request_metrics)
    events = load_events(args.lineage)
    logical, lineage_audit = logical_lineage(events, requests, args.tp_size)
    chains, session_audit = build_session_chains(logical, requests)
    if session_audit["missing_lineage_groups"]:
        raise ValueError(
            "some request groups have no lineage: "
            f"{session_audit['missing_lineage_groups']}"
        )

    capacity_model = json.loads(args.capacity_model.read_text(encoding="utf-8"))
    piecewise_model = capacity_model["models"]["piecewise_qps"]
    observed_breakpoint = float(piecewise_model["breakpoint_gib"])
    base_groups = selected_groups(chains, args.base_sessions)
    bytes_per_page = args.tp_size * args.value_bytes
    base_pages = sum(len(chains[group]) for group in base_groups)
    base_wss_gib = base_pages * bytes_per_page / GIB
    theoretical_base_knee = base_wss_gib / args.replica_capacity_ratio
    kappa = observed_breakpoint * args.replica_capacity_ratio / base_wss_gib
    plateau_runs = [
        run
        for run in capacity_model["runs"]
        if float(run["capacity_gib"]) >= observed_breakpoint
    ]
    base_plateau_qps = sum(float(run["qps"]) for run in plateau_runs) / len(
        plateau_runs
    )

    profiles = args.profile or [
        ProfileSpec("base_w2_s96_c24", 2, 96, 24),
        ProfileSpec("matched_w1_s48_c12", 1, 48, 12),
        ProfileSpec("local_fit_w2_s48_c12", 2, 48, 12),
        ProfileSpec("w1_s24_c6", 1, 24, 6),
        ProfileSpec("w2_s72_c18", 2, 72, 18),
    ]
    validation_capacities = args.validation_capacity or [128.0, 145.0, 160.0]
    profile_rows = [
        make_profile(
            spec,
            chains,
            tp_size=args.tp_size,
            value_bytes=args.value_bytes,
            gpu_owner_nominal_gib=args.gpu_owner_nominal_gib,
            owner_payload_ratio=args.owner_payload_ratio,
            replica_capacity_ratio=args.replica_capacity_ratio,
            calibration_kappa=kappa,
            base_workers=args.base_workers,
            base_sessions=args.base_sessions,
            base_concurrency=args.base_concurrency,
            base_wss_gib=base_wss_gib,
            base_plateau_qps=base_plateau_qps,
            piecewise_model=piecewise_model,
            validation_capacities=validation_capacities,
        )
        for spec in profiles
    ]
    result = {
        "schema": "e44_resource_load_scaling_model_v1",
        "generated_at": args.generated_at,
        "trace_audit": {
            "request_metrics": request_counters,
            "lineage": lineage_audit,
            "sessions": session_audit,
        },
        "geometry": {
            "tp_size": args.tp_size,
            "value_bytes_per_tp_page": args.value_bytes,
            "physical_bytes_per_logical_page": bytes_per_page,
            "gpu_owner_nominal_gib": args.gpu_owner_nominal_gib,
            "owner_payload_ratio": args.owner_payload_ratio,
            "replica_capacity_ratio": args.replica_capacity_ratio,
        },
        "calibration": {
            "base_workers": args.base_workers,
            "base_sessions": args.base_sessions,
            "base_concurrency": args.base_concurrency,
            "base_host_visible_pages": base_pages,
            "base_host_visible_wss_gib": base_wss_gib,
            "theoretical_base_knee_gib": theoretical_base_knee,
            "observed_breakpoint_gib": observed_breakpoint,
            "theoretical_error_percent": 100.0
            * (theoretical_base_knee - observed_breakpoint)
            / observed_breakpoint,
            "kappa": kappa,
            "base_plateau_qps": base_plateau_qps,
            "plateau_run_capacities_gib": [
                float(run["capacity_gib"]) for run in plateau_runs
            ],
        },
        "profiles": profile_rows,
        "validation_plan": {
            "primary_profile": "matched_w1_s48_c12",
            "nominal_remote_capacity_gib": validation_capacities,
            "invariants": [
                "same r61 code and model",
                "TP2 and 128 GiB owner-local capacity",
                "48 sessions, 24 turns, concurrency 12 on one active worker",
                "same Get32, tier1 5%, end-depth288, GDR/DMA and dual HCA",
                "cold start for every capacity",
            ],
            "acceptance": [
                "capacity curve QPS prediction error <= 5% at all valid points",
                "predicted plateau capacity within one tested bracket",
                "145 and 160 GiB QPS differ by <= 1% if both complete without reclaim pressure",
                "128 GiB remains below plateau or has nonzero CPU reclaim",
            ],
        },
        "limits": [
            "only matched per-worker shapes receive QPS projections",
            "trace keys reflect r61 host-visible prefixes and current admission policy",
            "arbitrary TP changes alter value geometry and require a new trace",
            "arbitrary concurrency changes require at least one additional queue/service anchor",
            "production Moka TinyLFU, pinning and asynchronous admission remain empirical corrections",
        ],
    }
    if args.validation_run:
        primary = next(
            profile
            for profile in profile_rows
            if profile["name"] == result["validation_plan"]["primary_profile"]
        )
        validation_runs = [
            load_validation_run(capacity, artifact)
            for capacity, artifact in args.validation_run
        ]
        result["cluster_validation"] = validate_cluster_runs(
            validation_runs, primary, args.service_anchor_capacity
        )
    assert args.output is not None
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if args.markdown is not None:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(render_markdown(result), encoding="utf-8")
    print(
        json.dumps(
            {
                "calibration": result["calibration"],
                "profiles": result["profiles"],
                "validation_plan": result["validation_plan"],
                "cluster_validation": result.get("cluster_validation"),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
