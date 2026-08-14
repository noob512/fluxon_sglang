#!/usr/bin/env python3
"""Build a trace-calibrated model for the requester-local SSD capacity knee.

The model deliberately separates capacity from service cost:

* a per-owner reuse-distance curve estimates how local-DRAM misses and
  evictions change when the effective GPU-owner payload is reduced;
* production snapshots calibrate that curve to the observed Moka local/remote
  probe split, size evictions, last-backing candidates, admitted SSD writes,
  and local SSD reads;
* cluster anchors are still required to fit the QPS cost of additional remote
  DRAM traffic and SSD durability.  The script does not pretend an LRU trace is
  an exact simulation of Moka TinyLFU, pinning, or concurrent batch ordering.

The optimization target used by the generated report is:

    minimize 2 * C_local + C_remote

subject to a same-release no-loss QPS gate, requester-local SSD reads only,
zero correctness failures, and bounded SSD read/write service demand.
"""

from __future__ import annotations

import argparse
import bisect
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, pstdev
from typing import Any, Iterable

from analyze_e44_r60_kv_lineage import load_events


GIB = 1 << 30
VALUE_BYTES = 4_718_592
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
FIELD_RE = re.compile(r"\b([a-zA-Z_][a-zA-Z0-9_]*)=([0-9]+)\b")


class Fenwick:
    def __init__(self, size: int) -> None:
        self.tree = [0] * (size + 1)

    def add(self, index: int, delta: int) -> None:
        tree = self.tree
        size = len(tree)
        while index < size:
            tree[index] += delta
            index += index & -index

    def prefix_sum(self, index: int) -> int:
        total = 0
        tree = self.tree
        while index > 0:
            total += tree[index]
            index -= index & -index
        return total


@dataclass(frozen=True)
class NodeTrace:
    node: str
    accesses: int
    cold_misses: int
    unique_items: int
    reuse_distances: tuple[int, ...]
    source_counts: dict[str, int]

    def miss_count(self, slots: int) -> int:
        reused_hits = bisect.bisect_left(self.reuse_distances, slots)
        return self.cold_misses + len(self.reuse_distances) - reused_hits

    def eviction_count(self, slots: int) -> int:
        return max(0, self.miss_count(slots) - slots)


def parse_env(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator:
            result[key] = value
    return result


def parse_snapshot(path: Path, marker: str) -> dict[str, int]:
    selected = ""
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            plain = ANSI_RE.sub("", line)
            if marker in plain:
                selected = plain
    if not selected:
        raise ValueError(f"missing snapshot {marker!r}: {path}")
    fields = {key: int(value) for key, value in FIELD_RE.findall(selected)}
    if not fields:
        raise ValueError(f"snapshot has no numeric fields: {path}: {selected}")
    return fields


def find_single(directory: Path, pattern: str) -> Path:
    matches = sorted(directory.glob(pattern))
    if len(matches) != 1:
        raise ValueError(
            f"expected one {pattern!r} below {directory}, found {len(matches)}"
        )
    return matches[0]


def load_run(artifact: Path, *, expect_ssd: bool) -> dict[str, Any]:
    summary = json.loads(
        (artifact / "workload_result" / "summary.json").read_text(encoding="utf-8")
    )["router_agent"]
    request = summary["request_summary"]
    cache = summary["cache_summary"]
    if (
        int(request["request_count"]) != 2304
        or int(request["success_count"]) != 2304
        or int(request["error_count"]) != 0
    ):
        raise ValueError(f"run is not a complete 2304/2304/0 round: {artifact}")

    env = parse_env(artifact / "capacity.env")
    node_rows: dict[str, dict[str, Any]] = {}
    for node in ("node0", "node1"):
        owner = artifact / node / "owner.log"
        get_snapshot = parse_snapshot(owner, "owner Get lifecycle snapshot")
        eviction_snapshot = parse_snapshot(
            owner, "owner hot source-eviction policy snapshot"
        )
        ssd_snapshot: dict[str, int]
        if expect_ssd:
            ssd_snapshot = parse_snapshot(owner, "owner KV SSD storage snapshot")
        else:
            ssd_snapshot = {}
        node_rows[node] = {
            "get": get_snapshot,
            "eviction": eviction_snapshot,
            "ssd": ssd_snapshot,
        }

    def summed(section: str, field: str) -> int:
        return sum(int(node_rows[node][section].get(field, 0)) for node in node_rows)

    per_node_cache_hit_rates = {
        node: sum(float(value) for value in row["cached_by_source"].values())
        / float(row["prompt_tokens_total"])
        for node, row in cache.get("per_node", {}).items()
    }
    cache_hit_rate_spread = (
        max(per_node_cache_hit_rates.values())
        - min(per_node_cache_hit_rates.values())
        if per_node_cache_hit_rates
        else 0.0
    )

    return {
        "artifact": str(artifact),
        "qps": float(request["request_qps"]),
        "token_qps": float(request["total_token_qps"]),
        "wall_s": float(request["wall_duration_s"]),
        "ttft_mean_s": float(request["ttft_mean_s"]),
        "ttft_p99_s": float(request["ttft_p99_s"]),
        "e2e_mean_s": float(request["e2e_mean_s"]),
        "e2e_p99_s": float(request["e2e_p99_s"]),
        "prompt_tokens": int(request["prompt_tokens_total_client_est"]),
        "total_hit_rate": float(cache["overall_hit_rate"]),
        "per_node_cache_hit_rates": per_node_cache_hit_rates,
        "cache_hit_rate_spread": cache_hit_rate_spread,
        "gpu_dram_bytes_each": int(env["gpu_dram_bytes_each"]),
        "gpu_payload_bytes_each": int(env["gpu_payload_bytes_each"]),
        "cpu_dram_bytes": int(env["cpu_dram_bytes"]),
        "cpu_active_capacity_bytes": int(env["cpu_active_capacity_bytes"]),
        "capacity_control_enabled": env["capacity_control_enabled"] == "1",
        "ssd_scope": env["ssd_scope"],
        "ssd_read_source_policy": env["ssd_read_source_policy"],
        "size_evictions": summed("eviction", "size_evictions"),
        "local_probe_items": summed("get", "local_probe_items"),
        "local_probe_local_items": summed("get", "local_probe_local_items"),
        "local_probe_remote_items": summed("get", "local_probe_remote_items"),
        "write_candidate_items": summed("ssd", "write_candidate_items"),
        "write_admitted_items": summed("ssd", "write_admitted_items"),
        "write_dropped_items": summed("ssd", "write_dropped_items"),
        "persist_successes": summed("ssd", "persist_successes"),
        "persist_bytes": summed("ssd", "persist_bytes"),
        "persist_batch_requests": summed("ssd", "persist_batch_requests"),
        "persist_batch_duration_us": summed("ssd", "persist_batch_duration_us"),
        "load_successes": summed("ssd", "load_successes"),
        "load_bytes": summed("ssd", "load_bytes"),
        "load_duration_us": summed("ssd", "load_duration_us"),
        "persist_failures": summed("ssd", "persist_failures"),
        "load_failures": summed("ssd", "load_failures"),
        "load_misses": summed("ssd", "load_misses"),
        "node_rows": node_rows,
    }


def build_node_traces(trace_artifact: Path) -> dict[str, NodeTrace]:
    specs: list[str] = []
    for node in ("node0", "node1"):
        log = find_single(trace_artifact / node, "sglang_*.log")
        specs.append(f"{node}={log}")
    events = [
        event
        for event in load_events(specs)
        if event.get("terminal") == "load_back_consumed"
    ]
    events.sort(
        key=lambda event: (
            int(event["plan_unix_ns"]),
            str(event["node"]),
            int(event["tp_rank"]),
            str(event.get("req", "")),
        )
    )

    result: dict[str, NodeTrace] = {}
    for node in ("node0", "node1"):
        selected = [event for event in events if event["node"] == node]
        accesses = sum(len(event["key_ids"]) for event in selected)
        fenwick = Fenwick(accesses)
        last_position: dict[tuple[int, str], int] = {}
        reuse_distances: list[int] = []
        source_counts = {"L": 0, "R": 0, "U": 0}
        active = 0
        position = 0
        for event in selected:
            rank = int(event["tp_rank"])
            sources = str(event["sources"])
            for key, source in zip(event["key_ids"], sources):
                position += 1
                source_counts[source] = source_counts.get(source, 0) + 1
                identity = (rank, str(key))
                previous = last_position.get(identity)
                if previous is None:
                    active += 1
                else:
                    reuse_distances.append(active - fenwick.prefix_sum(previous))
                    fenwick.add(previous, -1)
                fenwick.add(position, 1)
                last_position[identity] = position
        reuse_distances.sort()
        result[node] = NodeTrace(
            node=node,
            accesses=accesses,
            cold_misses=len(last_position),
            unique_items=len(last_position),
            reuse_distances=tuple(reuse_distances),
            source_counts=source_counts,
        )
    return result


def average_field(runs: Iterable[dict[str, Any]], field: str) -> float:
    values = [float(run[field]) for run in runs]
    return mean(values)


def build_observed_capacity_curve(
    runs: Iterable[dict[str, Any]],
    qps_floor: float,
    *,
    capacity_axis: str,
) -> dict[str, Any]:
    if capacity_axis == "local_payload":
        capacity_field = "gpu_payload_bytes_each"
    elif capacity_axis == "remote_active":
        capacity_field = "cpu_active_capacity_bytes"
    else:
        raise ValueError(f"unsupported capacity axis: {capacity_axis}")

    grouped: dict[int, list[dict[str, Any]]] = {}
    for run in runs:
        grouped.setdefault(int(run[capacity_field]), []).append(run)

    rows: list[dict[str, Any]] = []
    for capacity_bytes, group in sorted(grouped.items()):
        qps_values = [float(run["qps"]) for run in group]
        pass_count = sum(value >= qps_floor for value in qps_values)
        status = (
            "pass"
            if pass_count == len(qps_values)
            else "fail"
            if pass_count == 0
            else "mixed"
        )
        rows.append(
            {
                "axis_bytes": capacity_bytes,
                "axis_gib": capacity_bytes / GIB,
                "payload_bytes_each": int(
                    average_field(group, "gpu_payload_bytes_each")
                ),
                "payload_gib_each": average_field(
                    group, "gpu_payload_bytes_each"
                )
                / GIB,
                "physical_dram_gib_each": average_field(
                    group, "gpu_dram_bytes_each"
                )
                / GIB,
                "cpu_active_capacity_bytes": int(
                    average_field(group, "cpu_active_capacity_bytes")
                ),
                "cpu_active_capacity_gib": average_field(
                    group, "cpu_active_capacity_bytes"
                )
                / GIB,
                "cpu_physical_dram_gib": average_field(group, "cpu_dram_bytes")
                / GIB,
                "runs": len(group),
                "qps_values": qps_values,
                "qps_mean": mean(qps_values),
                "qps_min": min(qps_values),
                "qps_max": max(qps_values),
                "qps_population_stddev": pstdev(qps_values),
                "qps_range": max(qps_values) - min(qps_values),
                "qps_range_percent_of_mean": (
                    (max(qps_values) - min(qps_values))
                    / mean(qps_values)
                    * 100.0
                ),
                "pass_count": pass_count,
                "status": status,
                "repeat_status": (
                    f"repeated_{status}" if len(group) >= 2 else f"single_{status}"
                ),
                "total_hit_rate_mean": average_field(group, "total_hit_rate"),
                "per_node_hit_spread_pp_mean": average_field(
                    group, "cache_hit_rate_spread"
                )
                * 100.0,
                "per_node_hit_spread_pp_max": max(
                    float(run["cache_hit_rate_spread"]) for run in group
                )
                * 100.0,
                "ttft_p99_s_mean": average_field(group, "ttft_p99_s"),
                "ttft_p99_s_max": max(float(run["ttft_p99_s"]) for run in group),
                "local_probe_remote_items_mean": average_field(
                    group, "local_probe_remote_items"
                ),
                "size_evictions_mean": average_field(group, "size_evictions"),
                "persist_successes_mean": average_field(
                    group, "persist_successes"
                ),
                "load_successes_mean": average_field(group, "load_successes"),
            }
        )

    # QPS should be non-decreasing with capacity. Pool adjacent violators so
    # obvious run-to-run inversions do not become a fake capacity benefit.
    blocks: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        block = {
            "start": index,
            "end": index,
            "weight": row["runs"],
            "weighted_qps": row["qps_mean"] * row["runs"],
        }
        blocks.append(block)
        while len(blocks) >= 2:
            left, right = blocks[-2], blocks[-1]
            left_mean = left["weighted_qps"] / left["weight"]
            right_mean = right["weighted_qps"] / right["weight"]
            if left_mean <= right_mean:
                break
            blocks[-2:] = [
                {
                    "start": left["start"],
                    "end": right["end"],
                    "weight": left["weight"] + right["weight"],
                    "weighted_qps": left["weighted_qps"]
                    + right["weighted_qps"],
                }
            ]
    for block in blocks:
        fitted = block["weighted_qps"] / block["weight"]
        for index in range(block["start"], block["end"] + 1):
            rows[index]["isotonic_qps"] = fitted

    def bracket(min_runs: int) -> dict[str, float | None]:
        passed = [
            row
            for row in rows
            if row["status"] == "pass" and row["runs"] >= min_runs
        ]
        failed = [
            row
            for row in rows
            if row["status"] == "fail" and row["runs"] >= min_runs
        ]
        lowest_pass = (
            min(passed, key=lambda row: row["axis_bytes"]) if passed else None
        )
        failed_below = (
            [
                row
                for row in failed
                if lowest_pass is not None
                and row["axis_bytes"] < lowest_pass["axis_bytes"]
            ]
            if lowest_pass is not None
            else []
        )
        highest_fail_below = (
            max(failed_below, key=lambda row: row["axis_bytes"])
            if failed_below
            else None
        )
        return {
            "failed_axis_gib": (
                highest_fail_below["axis_gib"]
                if highest_fail_below is not None
                else None
            ),
            "passed_axis_gib": (
                lowest_pass["axis_gib"] if lowest_pass is not None else None
            ),
        }

    observed_bracket = bracket(1)
    repeated_observed_bracket = bracket(2)

    crossing = None
    for left, right in zip(rows, rows[1:]):
        left_qps = float(left["isotonic_qps"])
        right_qps = float(right["isotonic_qps"])
        if left_qps < qps_floor <= right_qps and right_qps > left_qps:
            fraction = (qps_floor - left_qps) / (right_qps - left_qps)
            crossing = left["axis_gib"] + fraction * (
                right["axis_gib"] - left["axis_gib"]
            )
            break

    result = {
        "capacity_axis": capacity_axis,
        "qps_floor": qps_floor,
        "rows": rows,
        "observed_bracket": observed_bracket,
        "repeated_observed_bracket": repeated_observed_bracket,
        "isotonic_crossing_axis_gib": crossing,
        "warning": (
            "single-run rows are candidates; repeat both sides before sealing the knee"
        ),
    }
    if capacity_axis == "local_payload":
        result["observed_bracket"].update(
            {
                "failed_payload_gib_each": result["observed_bracket"][
                    "failed_axis_gib"
                ],
                "passed_payload_gib_each": result["observed_bracket"][
                    "passed_axis_gib"
                ],
            }
        )
        result["isotonic_crossing_payload_gib_each"] = crossing
    return result


def build_paired_capacity_comparison(
    ssd_curve: dict[str, Any], control_curve: dict[str, Any] | None
) -> list[dict[str, Any]]:
    if control_curve is None:
        return []
    ssd_by_capacity = {row["axis_bytes"]: row for row in ssd_curve["rows"]}
    control_by_capacity = {
        row["axis_bytes"]: row for row in control_curve["rows"]
    }
    rows: list[dict[str, Any]] = []
    for capacity_bytes in sorted(ssd_by_capacity.keys() & control_by_capacity):
        ssd = ssd_by_capacity[capacity_bytes]
        control = control_by_capacity[capacity_bytes]
        rows.append(
            {
                "axis_bytes": capacity_bytes,
                "axis_gib": capacity_bytes / GIB,
                "ssd_on_qps_mean": ssd["qps_mean"],
                "ssd_off_qps_mean": control["qps_mean"],
                "ssd_on_minus_off_qps": ssd["qps_mean"]
                - control["qps_mean"],
                "ssd_on_runs": ssd["runs"],
                "ssd_off_runs": control["runs"],
                "ssd_on_load_successes_mean": ssd["load_successes_mean"],
                "ssd_on_persist_successes_mean": ssd[
                    "persist_successes_mean"
                ],
            }
        )
    return rows


def build_capacity_gate_comparison(
    capacity_gate_curves: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    def compare_brackets(
        on_bracket: dict[str, float | None],
        off_bracket: dict[str, float | None] | None,
    ) -> dict[str, Any]:
        off = off_bracket or {}
        on_failed = on_bracket["failed_axis_gib"]
        on_passed = on_bracket["passed_axis_gib"]
        off_failed = off.get("failed_axis_gib")
        off_passed = off.get("passed_axis_gib")
        closed = all(
            value is not None
            for value in (on_failed, on_passed, off_failed, off_passed)
        )
        if not closed:
            return {
                "lowest_passing_point_shift_gib": None,
                "knee_delta_lower_open_gib": None,
                "knee_delta_upper_open_gib": None,
                "verdict": "unclosed",
            }
        assert on_failed is not None
        assert on_passed is not None
        assert off_failed is not None
        assert off_passed is not None
        lower_open = off_failed - on_passed
        upper_open = off_passed - on_failed
        if upper_open <= 0.0:
            verdict = "ssd_cannot_reduce_capacity"
        elif lower_open >= 0.0:
            verdict = "ssd_reduces_capacity"
        else:
            verdict = "overlap_unresolved"
        return {
            "lowest_passing_point_shift_gib": off_passed - on_passed,
            "knee_delta_lower_open_gib": lower_open,
            "knee_delta_upper_open_gib": upper_open,
            "verdict": verdict,
        }

    result: dict[str, dict[str, Any]] = {}
    for name, curves in capacity_gate_curves.items():
        ssd_on = curves["ssd_on"]
        ssd_off = curves.get("ssd_off")
        on_bracket = ssd_on["observed_bracket"]
        off_bracket = ssd_off["observed_bracket"] if ssd_off else {}
        on_repeated = ssd_on["repeated_observed_bracket"]
        off_repeated = (
            ssd_off["repeated_observed_bracket"] if ssd_off else None
        )
        candidate = compare_brackets(on_bracket, off_bracket)
        repeated = compare_brackets(on_repeated, off_repeated)
        result[name] = {
            "qps_floor": ssd_on["qps_floor"],
            "ssd_off_bracket": off_bracket or None,
            "ssd_on_bracket": on_bracket,
            "ssd_off_repeated_bracket": off_repeated,
            "ssd_on_repeated_bracket": on_repeated,
            "lowest_passing_point_shift_gib": candidate[
                "lowest_passing_point_shift_gib"
            ],
            "knee_delta_lower_open_gib": candidate[
                "knee_delta_lower_open_gib"
            ],
            "knee_delta_upper_open_gib": candidate[
                "knee_delta_upper_open_gib"
            ],
            "candidate_verdict": candidate["verdict"],
            "repeated_lowest_passing_point_shift_gib": repeated[
                "lowest_passing_point_shift_gib"
            ],
            "repeated_knee_delta_lower_open_gib": repeated[
                "knee_delta_lower_open_gib"
            ],
            "repeated_knee_delta_upper_open_gib": repeated[
                "knee_delta_upper_open_gib"
            ],
            "verdict": (
                repeated["verdict"]
                if repeated["verdict"] != "unclosed"
                else "unsealed"
            ),
        }
    return result


def candidate_row(
    payload_gib: float,
    *,
    current_payload_bytes: int,
    traces: dict[str, NodeTrace],
    current_lru_misses: int,
    current_lru_evictions: int,
    observed_remote_items: float,
    observed_size_evictions: float,
    observed_candidates: float,
    observed_admitted: float,
    observed_load_yield: float,
    wall_s: float,
    safe_persist_items: int,
) -> dict[str, Any]:
    requested_bytes = int(payload_gib * GIB)
    if math.isclose(payload_gib, current_payload_bytes / GIB, abs_tol=1e-9):
        requested_bytes = current_payload_bytes
    slots = requested_bytes // VALUE_BYTES
    physical_dram_bytes = (requested_bytes * 10 + 8) // 9
    misses = sum(trace.miss_count(slots) for trace in traces.values())
    evictions = sum(trace.eviction_count(slots) for trace in traces.values())
    miss_scale = misses / current_lru_misses if current_lru_misses else 1.0
    eviction_scale = (
        evictions / current_lru_evictions if current_lru_evictions else 1.0
    )
    predicted_remote_items = observed_remote_items * miss_scale
    predicted_size_evictions = observed_size_evictions * eviction_scale
    predicted_candidates = observed_candidates * eviction_scale
    predicted_admitted = observed_admitted * eviction_scale
    predicted_loads_lower_bound = predicted_admitted * observed_load_yield
    additional_remote_bytes = max(
        0.0, (predicted_remote_items - observed_remote_items) * VALUE_BYTES
    )
    return {
        "payload_gib_each": payload_gib,
        "payload_bytes_each": requested_bytes,
        "physical_dram_gib_each": physical_dram_bytes / GIB,
        "physical_dram_bytes_each": physical_dram_bytes,
        "slots_each": slots,
        "trace_lru_misses": misses,
        "trace_lru_evictions": evictions,
        "trace_miss_scale_vs_current": miss_scale,
        "trace_eviction_scale_vs_current": eviction_scale,
        "predicted_moka_remote_items": predicted_remote_items,
        "predicted_size_evictions": predicted_size_evictions,
        "predicted_last_backing_candidates": predicted_candidates,
        "predicted_persist_items_at_one_per_pressure": predicted_admitted,
        "predicted_persist_mib_per_s": (
            predicted_admitted * VALUE_BYTES / wall_s / (1 << 20)
        ),
        "predicted_local_ssd_loads_observed_selection_lower_bound": (
            predicted_loads_lower_bound
        ),
        "additional_remote_dram_gib": additional_remote_bytes / GIB,
        "additional_remote_dram_mib_per_s": additional_remote_bytes
        / wall_s
        / (1 << 20),
        "within_empirical_one_kv_write_envelope": (
            predicted_admitted <= safe_persist_items
        ),
    }


def format_optional(value: float | None, suffix: str = "") -> str:
    return "unknown" if value is None else f"{value:.3f}{suffix}"


def render_remote_markdown(result: dict[str, Any]) -> str:
    baseline = result["baseline"]
    observed = result["observed_capacity_curve"]
    control = result.get("control_capacity_curve")
    paired = result.get("paired_capacity_comparison", [])
    lines = [
        "# Fluxon local SSD 替代 remote DRAM 容量边界模型",
        "",
        f"生成时间：{result['generated_at']}",
        "",
        "## 当前问题",
        "",
        "固定两个 GPU owner 的 local DRAM，不再缩 local；只改变 CPU remote owner 的 active DRAM。"
        "SSD-on 只启用 requester-local SSD，读取顺序固定为 "
        "`local DRAM → local SSD → remote DRAM`。因此，只有 SSD-on 的 remote-DRAM knee "
        "低于 SSD-off，才能证明 local SSD 真正替代了 remote DRAM。",
        "",
        f"本组固定每个 GPU owner 物理 DRAM `{baseline['gpu_physical_dram_gib_each']:.3f} GiB`、"
        f"有效 local payload `{baseline['current_payload_gib_each']:.3f} GiB`；"
        f"纯内存锚点 QPS=`{baseline['pure_memory_qps']:.6f}`。",
        "",
        "## 模型定义",
        "",
        "对模式 `m ∈ {SSD-off, SSD-on}`，先对同一 remote active 容量的完整轮取均值，"
        "再用容量单调的 isotonic regression 得到 `Q_m(C_remote)`：",
        "",
        "```text",
        "C*(m, g) = inf { C_remote | Q_m(C_remote) ≥ g }",
        "SSD 可替代的 remote DRAM = C*(SSD-off, g) - C*(SSD-on, g)",
        "```",
        "",
        "同时保留两个门槛：`10 QPS` 是可接受吞吐硬线；相对纯内存低不超过 1% 是无损线。"
        "isotonic crossing 只用于选择下一个容量点，不能替代边界两侧的真实重复轮。",
        "",
        "## 当前主门槛的实测曲线",
        "",
        f"主门槛：`{observed['qps_floor']:.6f} QPS`。",
        "",
        "| 模式 | remote active | 轮数 | QPS 原始值 | QPS均值 | QPS极差 | isotonic QPS | 状态 | 总命中 | 节点命中差 | p99 TTFT | remote probe | eviction | persist | SSD load |",
        "|:---|---:|---:|:---|---:|---:|---:|:---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    def append_curve_rows(mode: str, curve: dict[str, Any]) -> None:
        for row in curve["rows"]:
            qps_values = "/".join(f"{value:.6f}" for value in row["qps_values"])
            lines.append(
                f"| {mode} | {row['axis_gib']:.1f} GiB | {row['runs']} | "
                f"{qps_values} | {row['qps_mean']:.6f} | "
                f"{row['qps_range_percent_of_mean']:.3f}% | "
                f"{row['isotonic_qps']:.6f} | {row['status']} | "
                f"{row['total_hit_rate_mean'] * 100.0:.3f}% | "
                f"{row['per_node_hit_spread_pp_mean']:.3f}pp | "
                f"{row['ttft_p99_s_mean']:.3f}s | "
                f"{row['local_probe_remote_items_mean']:.0f} | "
                f"{row['size_evictions_mean']:.0f} | "
                f"{row['persist_successes_mean']:.1f} | "
                f"{row['load_successes_mean']:.1f} |"
            )

    if control:
        append_curve_rows("SSD-off", control)
    append_curve_rows("SSD-on", observed)

    lines.extend(
        [
            "",
            "## 两套验收门槛的容量边界",
            "",
            "`(fail, pass]` 只有在同一模式下同时测到失败侧和通过侧才闭合；"
            "缺一侧时保持 unknown，不作外推封口。",
            "",
            "| 门槛 | QPS线 | SSD-off实测括号 | SSD-on实测括号 | off crossing | on crossing | 最低通过点位移 | 候选knee Δ区间 | 重复轮裁决 |",
            "|:---|---:|:---:|:---:|---:|---:|---:|:---:|:---|",
        ]
    )
    for name, curves in result["capacity_gate_curves"].items():
        on_curve = curves["ssd_on"]
        off_curve = curves.get("ssd_off")
        on_bracket = on_curve["observed_bracket"]
        off_bracket = off_curve["observed_bracket"] if off_curve else {}
        on_pass = on_bracket["passed_axis_gib"]
        off_pass = off_bracket.get("passed_axis_gib")
        comparison = result["capacity_gate_comparison"][name]
        lower = comparison["knee_delta_lower_open_gib"]
        upper = comparison["knee_delta_upper_open_gib"]
        interval = (
            "unknown"
            if lower is None or upper is None
            else f"({lower:.3f}, {upper:.3f}) GiB"
        )
        verdict = {
            "ssd_cannot_reduce_capacity": "SSD不能节省",
            "ssd_reduces_capacity": "SSD确认节省",
            "overlap_unresolved": "区间重叠，未决",
            "unclosed": "括号未闭合",
            "unsealed": "重复证据未闭合",
        }[comparison["verdict"]]
        lines.append(
            f"| {name} | {on_curve['qps_floor']:.6f} | "
            f"({format_optional(off_bracket.get('failed_axis_gib'))}, "
            f"{format_optional(off_pass)}] | "
            f"({format_optional(on_bracket['failed_axis_gib'])}, "
            f"{format_optional(on_pass)}] | "
            f"{format_optional(off_curve['isotonic_crossing_axis_gib'] if off_curve else None)} | "
            f"{format_optional(on_curve['isotonic_crossing_axis_gib'])} | "
            f"{format_optional(comparison['lowest_passing_point_shift_gib'], ' GiB')} | "
            f"{interval} | {verdict} |"
        )

    lines.extend(
        [
            "",
            "## 同容量配对差值",
            "",
            "同容量差值用于识别 SSD 路径本身的代价或收益；容量替代量仍以两条 knee 的水平位移裁决。",
            "",
            "| remote active | SSD-off QPS | SSD-on QPS | on-off | off轮数 | on轮数 | SSD persist | SSD load |",
            "|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    if paired:
        for row in paired:
            lines.append(
                f"| {row['axis_gib']:.1f} GiB | {row['ssd_off_qps_mean']:.6f} | "
                f"{row['ssd_on_qps_mean']:.6f} | "
                f"{row['ssd_on_minus_off_qps']:+.6f} | "
                f"{row['ssd_off_runs']} | {row['ssd_on_runs']} | "
                f"{row['ssd_on_persist_successes_mean']:.1f} | "
                f"{row['ssd_on_load_successes_mean']:.1f} |"
            )
    else:
        lines.append("| 尚无同容量完整配对轮 | - | - | - | - | - | - | - |")

    lines.extend(
        [
            "",
            "## 当前模型边界",
            "",
            "- 当前 remote 轴是集群锚点校准的经验单调模型，不假装能从 local reuse-distance trace 直接推导 remote knee；",
            "- 单轮波动不会被 isotonic 拟合改写为通过；边界候选两侧至少各复测一次后才封口；",
            "- SSD-on 低容量点若通过、但同容量 SSD-off 也通过，只能说明容量仍充足，不能算 SSD 节省；",
            "- 只有完整 `2304/2304/0` 且无 608/refill/OOM、无干扰进程的轮次进入模型。",
            "",
        ]
    )
    return "\n".join(lines)


def render_markdown(result: dict[str, Any]) -> str:
    if result.get("capacity_axis") == "remote_active":
        return render_remote_markdown(result)
    baseline = result["baseline"]
    trace = result["trace"]
    rows = result["capacity_candidates"]
    observed = result.get("observed_capacity_curve")
    control = result.get("control_capacity_curve")
    lines = [
        "# Fluxon requester-local SSD 容量边界模型",
        "",
        f"生成时间：{result['generated_at']}",
        "",
        "## 当前结论",
        "",
        "- 目标读取顺序固定为 `local DRAM → local SSD → remote DRAM`，其他 owner SSD 永不参与读取；",
        "- 容量目标不是让 SSD 提高 QPS，而是在用户给定的 QPS 门槛之上最小化总 DRAM；",
        f"- 当前容量形状锚点 QPS=`{baseline['local_only_qps_mean']:.6f}`，"
        f"纯内存 QPS=`{baseline['pure_memory_qps']:.6f}`，容量验收门槛="
        f"`{baseline['qps_floor']:.6f}`；",
        f"- 当前两侧 GPU owner 有效 payload 各 `{baseline['current_payload_gib_each']:.3f} GiB`，"
        f"trace 唯一物理 KV 工作集分别为 "
        f"`{trace['nodes']['node0']['unique_wss_gib']:.3f}/"
        f"{trace['nodes']['node1']['unique_wss_gib']:.3f} GiB`；",
        f"- 1-KV admission 当前平均每轮写 `{baseline['write_admitted_items_mean']:.1f}` 项，"
        f"只读回 `{baseline['load_successes_mean']:.1f}` 项；观察到的选择命中率仅 "
        f"`{baseline['observed_selection_load_yield_percent']:.3f}%`。",
        "",
        "## 数学目标",
        "",
        "```text",
        "minimize      M = 2 × C_local + C_remote",
        f"subject to    QPS(C_local, C_remote) ≥ {baseline['qps_floor']:.6f}",
        "              remote_SSD_reads = 0",
        "              2304/2304/0，608/refill/OOM = 0",
        "              SSD_write/read demand ≤ 可隐藏的设备与调度预算",
        "```",
        "",
        "本轮先固定 `C_remote=248 GiB`，只求 `C_local` 的一维切片。得到 local knee 后，"
        "再沿二维可行边界降低 remote DRAM；否则只缩 local 会把流量转给 remote DRAM，不能证明 SSD 替代了内存。",
        "",
        "## Trace 容量模型",
        "",
        "对每个 owner 的 KV 访问序列计算唯一 reuse distance `d`。payload 可容纳 "
        "`N=floor(C_local/value_bytes)` 个固定大小 KV 时：",
        "",
        "```text",
        "LRU_miss(N) = cold + count(d ≥ N)",
        "LRU_evict(N) = max(0, LRU_miss(N) - N)",
        "```",
        "",
        "LRU 只给出容量曲线形状；当前 payload 点用生产 Moka 的 local/remote probe、size eviction、"
        "last-backing candidate 和 SSD admission 做校准。Moka TinyLFU、pin 与并发 batch 的 QPS 代价必须由集群锚点拟合。",
        "",
        "| 每owner物理DRAM | 有效payload | slots | miss倍率 | eviction倍率 | 预计persist项 | 写MiB/s | 新增remote传输GiB/round | 1-KV经验写预算 |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|:---:|",
    ]
    if observed:
        bracket = observed["observed_bracket"]
        failed_text = (
            "unknown"
            if bracket["failed_payload_gib_each"] is None
            else f"{bracket['failed_payload_gib_each']:.3f}"
        )
        passed_text = (
            "unknown"
            if bracket["passed_payload_gib_each"] is None
            else f"{bracket['passed_payload_gib_each']:.3f}"
        )
        crossing_text = (
            "unknown"
            if observed["isotonic_crossing_payload_gib_each"] is None
            else f"{observed['isotonic_crossing_payload_gib_each']:.3f}"
        )
        failed_row = next(
            (
                row
                for row in observed["rows"]
                if bracket["failed_payload_gib_each"] is not None
                and math.isclose(
                    row["payload_gib_each"],
                    bracket["failed_payload_gib_each"],
                    abs_tol=1e-6,
                )
            ),
            None,
        )
        passed_row = next(
            (
                row
                for row in observed["rows"]
                if bracket["passed_payload_gib_each"] is not None
                and math.isclose(
                    row["payload_gib_each"],
                    bracket["passed_payload_gib_each"],
                    abs_tol=1e-6,
                )
            ),
            None,
        )
        boundary_repeated = (
            failed_row is not None
            and passed_row is not None
            and failed_row["runs"] >= 2
            and passed_row["runs"] >= 2
        )
        observed_lines = [
            "## 真实集群容量点",
            "",
            "表中QPS先保留原始值，再用容量单调的isotonic fit消除单轮反向波动。"
            "pass/fail仍只按原始完整轮与硬门槛裁决；拟合不能把失败轮改成通过。",
            "",
            "| 每owner物理DRAM | 有效payload | 轮数 | QPS原始值 | QPS均值 | isotonic QPS | 状态 | 总命中 | remote probe | eviction | persist | SSD load |",
            "|---:|---:|---:|:---|---:|---:|:---:|---:|---:|---:|---:|---:|",
        ]
        for row in observed["rows"]:
            qps_values = "/".join(f"{value:.6f}" for value in row["qps_values"])
            observed_lines.append(
                f"| {row['physical_dram_gib_each']:.1f} GiB | "
                f"{row['payload_gib_each']:.1f} GiB | {row['runs']} | "
                f"{qps_values} | {row['qps_mean']:.6f} | "
                f"{row['isotonic_qps']:.6f} | {row['status']} | "
                f"{row['total_hit_rate_mean'] * 100.0:.3f}% | "
                f"{row['local_probe_remote_items_mean']:.0f} | "
                f"{row['size_evictions_mean']:.0f} | "
                f"{row['persist_successes_mean']:.1f} | "
                f"{row['load_successes_mean']:.1f} |"
            )
        observed_lines.extend(
            [
                "",
                "当前原始点夹出的payload边界为 "
                f"`({failed_text}, {passed_text}] GiB/owner`；"
                f"isotonic线性穿越估计为 `{crossing_text}` GiB/owner。",
                (
                    "边界两侧均已有至少两轮，当前1 GiB physical分辨率的一维knee可以封口；"
                    "连续穿越值仍不替代已测部署点。"
                    if boundary_repeated
                    else "该数值只用于选下一实验点；边界两侧没有重复轮之前，不封为最终knee。"
                ),
                "",
            ]
        )
        if control:
            control_bracket = control["observed_bracket"]
            control_failed = control_bracket["failed_payload_gib_each"]
            control_passed = control_bracket["passed_payload_gib_each"]
            observed_passed = bracket["passed_payload_gib_each"]
            shift = (
                None
                if control_passed is None or observed_passed is None
                else control_passed - observed_passed
            )
            observed_lines.extend(
                [
                    "### 同容量 SSD-off 因果对照",
                    "",
                    "| 每owner物理DRAM | 有效payload | QPS | 状态 | 总命中 | remote probe | eviction |",
                    "|---:|---:|:---|:---:|---:|---:|---:|",
                ]
            )
            for row in control["rows"]:
                qps_values = "/".join(
                    f"{value:.6f}" for value in row["qps_values"]
                )
                observed_lines.append(
                    f"| {row['physical_dram_gib_each']:.1f} GiB | "
                    f"{row['payload_gib_each']:.1f} GiB | {qps_values} | "
                    f"{row['status']} | {row['total_hit_rate_mean'] * 100.0:.3f}% | "
                    f"{row['local_probe_remote_items_mean']:.0f} | "
                    f"{row['size_evictions_mean']:.0f} |"
                )
            shift_text = "unknown" if shift is None else f"{shift:.3f} GiB/owner"
            observed_lines.extend(
                [
                    "",
                    "SSD-off原始括号为 "
                    f"`({control_failed:.3f}, {control_passed:.3f}] GiB/owner`；"
                    f"相对SSD-on的实测knee shift=`{shift_text}`。",
                    "当前shift为0表示这组SSD写入/读取策略尚未把容量边界向下推；"
                    "不能把SSD-on下的DRAM缩减归因于SSD。",
                    "",
                ]
            )
        trace_index = lines.index("## Trace 容量模型")
        lines[trace_index:trace_index] = observed_lines
    for row in rows:
        lines.append(
            f"| {row['physical_dram_gib_each']:.1f} GiB | "
            f"{row['payload_gib_each']:.1f} GiB | {row['slots_each']} | "
            f"{row['trace_miss_scale_vs_current']:.3f}× | "
            f"{row['trace_eviction_scale_vs_current']:.3f}× | "
            f"{row['predicted_persist_items_at_one_per_pressure']:.0f} | "
            f"{row['predicted_persist_mib_per_s']:.2f} | "
            f"{row['additional_remote_dram_gib']:.2f} | "
            f"{'yes' if row['within_empirical_one_kv_write_envelope'] else 'needs anchor'} |"
        )
    boundary_loads = baseline["load_successes_mean"]
    if observed and passed_row is not None:
        boundary_loads = passed_row["load_successes_mean"]
    lines.extend(
        [
            "",
            "## 当前模型能与不能回答的内容",
            "",
            "- 能：给出 local DRAM 缩容后 miss/eviction/候选写入增长的单调形状，并据此选择少量实验点；",
            f"- 不能：仅凭当前边界点平均 `{boundary_loads:.1f}` 次local SSD读取"
            "推断介质收益，也不能把CPU remote DRAM接住的流量算作SSD收益；",
        ]
    )
    if control:
        lines.append(
            "- 同容量SSD-off得到相同knee括号，当前SSD策略没有可确认容量增益；"
            "下一步应先提高写入价值和真实读取密度，再重新扫描。"
        )
    elif observed and boundary_repeated:
        lines.append(
            f"- 当前一维knee已封为 `({failed_text}, {passed_text}] GiB/owner`；"
            "下一步需要同容量SSD-off因果对照。"
        )
    elif observed:
        lines.append(
            f"- 下一门禁是复测 `{passed_text}` GiB通过侧与 `{failed_text}` GiB失败侧；"
            "两侧没有重复轮之前，isotonic crossing只用于选点。"
        )
    else:
        lines.extend(
            [
                "- 下一锚点必须先使用 `gpu_local_only` scope在当前payload复测，去掉CPU SSD无效写入；",
                f"- 随后的首个缩容候选为 `{result['next_anchor']['payload_gib_each']:.1f} GiB/owner`。"
                "若该点保持门槛，再按模型跳到下一候选；若失败，在上一个通过点之间二分。",
            ]
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path, action="append", required=True)
    parser.add_argument("--capacity-anchor", type=Path, action="append")
    parser.add_argument("--control-anchor", type=Path, action="append")
    parser.add_argument(
        "--capacity-axis",
        choices=("local_payload", "remote_active"),
        default="local_payload",
    )
    parser.add_argument("--pure-memory-artifact", type=Path, required=True)
    parser.add_argument("--trace-artifact", type=Path, required=True)
    parser.add_argument("--candidate-payload-gib", type=float, action="append")
    parser.add_argument("--safe-persist-items", type=int, default=451)
    parser.add_argument("--no-loss-tolerance", type=float, default=0.01)
    parser.add_argument("--min-qps", type=float)
    parser.add_argument("--service-qps-floor", type=float, default=10.0)
    parser.add_argument("--target-first-eviction-scale", type=float, default=1.20)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    args = parser.parse_args()

    if args.safe_persist_items <= 0:
        parser.error("--safe-persist-items must be positive")
    if not 0.0 <= args.no_loss_tolerance < 1.0:
        parser.error("--no-loss-tolerance must be in [0,1)")
    if args.min_qps is not None and args.min_qps <= 0.0:
        parser.error("--min-qps must be positive")
    if args.service_qps_floor <= 0.0:
        parser.error("--service-qps-floor must be positive")

    local_runs = [load_run(path, expect_ssd=True) for path in args.artifact]
    capacity_runs = [
        load_run(path, expect_ssd=True)
        for path in (args.capacity_anchor or args.artifact)
    ]
    control_runs = [
        load_run(path, expect_ssd=False) for path in (args.control_anchor or [])
    ]
    pure_memory = load_run(args.pure_memory_artifact, expect_ssd=False)
    relative_qps_floor = pure_memory["qps"] * (1.0 - args.no_loss_tolerance)
    qps_floor = (
        args.min_qps
        if args.min_qps is not None
        else relative_qps_floor
    )
    payload_values = {run["gpu_payload_bytes_each"] for run in local_runs}
    if len(payload_values) != 1:
        raise ValueError(f"local-only runs disagree on payload: {payload_values}")
    current_payload_bytes = next(iter(payload_values))
    if any(run["ssd_read_source_policy"] != "local_ssd_only_first" for run in local_runs):
        raise ValueError("all SSD artifacts must use local_ssd_only_first")
    if any(
        run["ssd_read_source_policy"] != "local_ssd_only_first"
        or run["ssd_scope"] != "gpu_local_only"
        for run in capacity_runs
    ):
        raise ValueError(
            "all capacity anchors must use local_ssd_only_first and gpu_local_only"
        )
    if args.capacity_axis == "local_payload":
        if len({run["cpu_active_capacity_bytes"] for run in capacity_runs}) != 1:
            raise ValueError("capacity anchors disagree on remote CPU active capacity")
    else:
        all_axis_runs = capacity_runs + control_runs
        if len({run["gpu_payload_bytes_each"] for run in all_axis_runs}) != 1:
            raise ValueError(
                "remote-axis anchors must keep GPU owner local payload fixed"
            )
        if len({run["gpu_dram_bytes_each"] for run in all_axis_runs}) != 1:
            raise ValueError(
                "remote-axis anchors must keep GPU owner physical DRAM fixed"
            )
        if len({run["cpu_dram_bytes"] for run in all_axis_runs}) != 1:
            raise ValueError(
                "remote-axis anchors must keep CPU owner physical DRAM fixed"
            )
        if any(
            run["cpu_active_capacity_bytes"] < run["cpu_dram_bytes"]
            and not run["capacity_control_enabled"]
            for run in all_axis_runs
        ):
            raise ValueError(
                "a reduced remote-axis anchor did not enable physical capacity control"
            )
    observed_capacity_curve = build_observed_capacity_curve(
        capacity_runs, qps_floor, capacity_axis=args.capacity_axis
    )
    control_capacity_curve = (
        build_observed_capacity_curve(
            control_runs, qps_floor, capacity_axis=args.capacity_axis
        )
        if control_runs
        else None
    )
    if any(run["ssd_scope"] != "disabled" for run in control_runs):
        raise ValueError("all control anchors must have SSD disabled")
    if args.capacity_axis == "local_payload" and control_runs and {
        run["cpu_active_capacity_bytes"] for run in control_runs
    } != {run["cpu_active_capacity_bytes"] for run in capacity_runs}:
        raise ValueError("SSD-on/off anchors disagree on remote CPU active capacity")

    gate_specs = {
        "service_floor": args.service_qps_floor,
        "relative_no_loss": relative_qps_floor,
    }
    if not any(math.isclose(qps_floor, value) for value in gate_specs.values()):
        gate_specs = {"primary": qps_floor, **gate_specs}
    capacity_gate_curves = {
        name: {
            "ssd_on": build_observed_capacity_curve(
                capacity_runs, floor, capacity_axis=args.capacity_axis
            ),
            "ssd_off": (
                build_observed_capacity_curve(
                    control_runs, floor, capacity_axis=args.capacity_axis
                )
                if control_runs
                else None
            ),
        }
        for name, floor in gate_specs.items()
    }
    paired_capacity_comparison = build_paired_capacity_comparison(
        observed_capacity_curve, control_capacity_curve
    )
    capacity_gate_comparison = build_capacity_gate_comparison(
        capacity_gate_curves
    )

    traces = build_node_traces(args.trace_artifact)
    current_slots = current_payload_bytes // VALUE_BYTES
    current_lru_misses = sum(
        trace.miss_count(current_slots) for trace in traces.values()
    )
    current_lru_evictions = sum(
        trace.eviction_count(current_slots) for trace in traces.values()
    )

    candidates = args.candidate_payload_gib or [
        current_payload_bytes / GIB,
        114.3,
        113.4,
        112.5,
        111.6,
        108.0,
        100.8,
        93.6,
        86.4,
        72.0,
        57.6,
    ]
    candidates = sorted(set(candidates), reverse=True)
    if not any(
        math.isclose(value, current_payload_bytes / GIB, abs_tol=1e-9)
        for value in candidates
    ):
        candidates.insert(0, current_payload_bytes / GIB)

    observed_remote_items = average_field(local_runs, "local_probe_remote_items")
    observed_size_evictions = average_field(local_runs, "size_evictions")
    observed_candidates = average_field(local_runs, "write_candidate_items")
    observed_admitted = average_field(local_runs, "write_admitted_items")
    observed_loads = average_field(local_runs, "load_successes")
    observed_load_yield = observed_loads / observed_admitted
    wall_s = average_field(local_runs, "wall_s")

    rows = [
        candidate_row(
            value,
            current_payload_bytes=current_payload_bytes,
            traces=traces,
            current_lru_misses=current_lru_misses,
            current_lru_evictions=current_lru_evictions,
            observed_remote_items=observed_remote_items,
            observed_size_evictions=observed_size_evictions,
            observed_candidates=observed_candidates,
            observed_admitted=observed_admitted,
            observed_load_yield=observed_load_yield,
            wall_s=wall_s,
            safe_persist_items=args.safe_persist_items,
        )
        for value in candidates
    ]
    below_current = [
        row
        for row in rows
        if row["payload_bytes_each"] < current_payload_bytes
    ]
    next_anchor = min(
        below_current,
        key=lambda row: abs(
            row["trace_eviction_scale_vs_current"]
            - args.target_first_eviction_scale
        ),
    )

    result = {
        "schema": "e44_local_ssd_capacity_knee_model_v2",
        "generated_at": args.generated_at,
        "capacity_axis": args.capacity_axis,
        "objective": {
            "minimize": "2 * gpu_owner_local_payload + cpu_remote_active_capacity",
            "fixed_first_slice_cpu_remote_gib": pure_memory[
                "cpu_active_capacity_bytes"
            ]
            / GIB,
            "no_loss_tolerance": args.no_loss_tolerance,
            "qps_gate": "absolute" if args.min_qps is not None else "relative",
            "qps_floor": qps_floor,
            "service_qps_floor": args.service_qps_floor,
            "relative_no_loss_qps_floor": relative_qps_floor,
            "remote_ssd_reads_required": 0,
        },
        "geometry": {
            "value_bytes_per_physical_kv": VALUE_BYTES,
            "current_slots_each": current_slots,
        },
        "baseline": {
            "local_only_artifacts": [run["artifact"] for run in local_runs],
            "pure_memory_artifact": pure_memory["artifact"],
            "local_only_qps": [run["qps"] for run in local_runs],
            "local_only_qps_mean": average_field(local_runs, "qps"),
            "pure_memory_qps": pure_memory["qps"],
            "qps_floor": qps_floor,
            "no_loss_qps_floor": qps_floor,
            "current_payload_bytes_each": current_payload_bytes,
            "current_payload_gib_each": current_payload_bytes / GIB,
            "gpu_physical_dram_gib_each": local_runs[0]["gpu_dram_bytes_each"]
            / GIB,
            "cpu_remote_active_gib": local_runs[0]["cpu_active_capacity_bytes"]
            / GIB,
            "local_probe_remote_items_mean": observed_remote_items,
            "size_evictions_mean": observed_size_evictions,
            "write_candidate_items_mean": observed_candidates,
            "write_admitted_items_mean": observed_admitted,
            "load_successes_mean": observed_loads,
            "observed_selection_load_yield_percent": observed_load_yield * 100.0,
            "safe_persist_items_per_round": args.safe_persist_items,
            "runs": local_runs,
            "pure_memory_run": pure_memory,
        },
        "trace": {
            "artifact": str(args.trace_artifact),
            "successful_terminal_only": True,
            "nodes": {
                node: {
                    "accesses": trace.accesses,
                    "cold_misses": trace.cold_misses,
                    "unique_items": trace.unique_items,
                    "unique_wss_gib": trace.unique_items * VALUE_BYTES / GIB,
                    "reuse_observations": len(trace.reuse_distances),
                    "source_counts": trace.source_counts,
                    "current_lru_misses": trace.miss_count(current_slots),
                    "current_lru_evictions": trace.eviction_count(current_slots),
                }
                for node, trace in traces.items()
            },
            "current_lru_misses": current_lru_misses,
            "current_lru_evictions": current_lru_evictions,
        },
        "capacity_candidates": rows,
        "observed_capacity_curve": observed_capacity_curve,
        "control_capacity_curve": control_capacity_curve,
        "capacity_gate_curves": capacity_gate_curves,
        "capacity_gate_comparison": capacity_gate_comparison,
        "paired_capacity_comparison": paired_capacity_comparison,
        "next_anchor": next_anchor,
        "limits": [
            "LRU supplies the capacity-curve shape; production uses Moka TinyLFU",
            "pinning and concurrent batch order require cluster calibration",
            "current persisted-key selection has too few local SSD reads to fit a read-benefit coefficient",
            "fixed remote248 first slice may shift saved local DRAM demand to remote DRAM",
            "a second phase must vary CPU remote capacity to minimize total DRAM",
        ],
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    args.output_md.write_text(render_markdown(result), encoding="utf-8")


if __name__ == "__main__":
    main()
