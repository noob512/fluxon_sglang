#!/usr/bin/env python3
"""Replay the E44 KV trace into a load/local-cache/remote-DRAM surface.

This model answers one deliberately narrow question: with requester-local SSD
kept enabled, how much *active remote DRAM* is required as the number of
sessions and the GPU-owner local KV payload change?

The trace supplies the shape of the answer.  A per-worker LRU replay emits the
references that miss owner-local DRAM; a shared LRU stack-distance curve then
maps active remote capacity to downstream misses.  The acceptable downstream
misses/request budget is calibrated at the same-release r95 SSD-on 10-QPS
crossing.  The observed fail/pass bracket is propagated as an evidence band.

The production caches use Moka TinyLFU, pins and concurrent atomic batches, so
the replay is not presented as an exact cache implementation.  In particular,
the current SSD policy's individual persisted keys are absent from the lineage
trace.  SSD therefore remains fixed and is folded into the empirical anchor;
the script refuses to attribute the predicted reduction to SSD alone.
"""

from __future__ import annotations

import argparse
import bisect
import json
import math
from collections import Counter, OrderedDict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from analyze_e44_r60_kv_lineage import load_events
from model_e44_resource_load_scaling import (
    build_session_chains,
    load_request_metrics,
    logical_lineage,
    selected_groups,
)


GIB = 1 << 30


@dataclass(frozen=True)
class ReuseCurve:
    accesses: int
    cold_misses: int
    reuse_distances: tuple[int, ...]

    def miss_count(self, slots: int) -> int:
        if slots < 0:
            raise ValueError("cache slots cannot be negative")
        first_hit = bisect.bisect_left(self.reuse_distances, slots)
        return self.cold_misses + len(self.reuse_distances) - first_hit

    def capacity_miss_count(self, slots: int) -> int:
        """Misses caused by finite retention, excluding first introduction."""
        return self.miss_count(slots) - self.cold_misses

    def minimum_slots(self, max_misses: float) -> int | None:
        if max_misses < self.cold_misses:
            return None
        if self.accesses <= max_misses:
            return 0
        low = 0
        high = max(self.reuse_distances, default=0) + 1
        while low < high:
            middle = (low + high) // 2
            if self.miss_count(middle) <= max_misses:
                high = middle
            else:
                low = middle + 1
        return low


@dataclass(frozen=True)
class ReplayProfile:
    sessions: int
    turns: int
    concurrency: int
    workers: int
    gpu_payload_gib_each: float
    worker_assignment: str = "trace"


class Fenwick:
    def __init__(self, size: int) -> None:
        self.tree = [0] * (size + 1)

    def add(self, index: int, delta: int) -> None:
        while index < len(self.tree):
            self.tree[index] += delta
            index += index & -index

    def prefix_sum(self, index: int) -> int:
        total = 0
        while index > 0:
            total += self.tree[index]
            index -= index & -index
        return total


def build_reuse_curve(accesses: Iterable[tuple[int, str]]) -> ReuseCurve:
    materialized = list(accesses)
    fenwick = Fenwick(len(materialized))
    last_position: dict[tuple[int, str], int] = {}
    distances: list[int] = []
    active = 0
    for position, identity in enumerate(materialized, 1):
        previous = last_position.get(identity)
        if previous is None:
            active += 1
        else:
            distances.append(active - fenwick.prefix_sum(previous))
            fenwick.add(previous, -1)
        fenwick.add(position, 1)
        last_position[identity] = position
    distances.sort()
    return ReuseCurve(
        accesses=len(materialized),
        cold_misses=len(last_position),
        reuse_distances=tuple(distances),
    )


def attach_and_audit_worker_assignments(
    logical: list[dict[str, Any]],
) -> tuple[dict[int, str], dict[str, Any]]:
    assignments: dict[int, str] = {}
    operations_by_node: Counter[str] = Counter()
    for operation in logical:
        group = int(operation["group"])
        node = str(operation["node"])
        previous = assignments.setdefault(group, node)
        if previous != node:
            raise ValueError(
                f"session/group {group} moved between workers: {previous}/{node}"
            )
        operations_by_node[node] += 1
    return assignments, {
        "sessions_with_assignment": len(assignments),
        "operations_by_node": dict(sorted(operations_by_node.items())),
        "sessions_by_node": dict(sorted(Counter(assignments.values()).items())),
        "moved_sessions": 0,
    }


def iter_physical_accesses(
    logical: Iterable[dict[str, Any]],
    groups: set[int],
    *,
    tp_size: int,
    worker_assignment: str,
) -> Iterable[tuple[str, float, tuple[int, str]]]:
    if worker_assignment not in {"trace", "collapse"}:
        raise ValueError(f"unsupported worker assignment: {worker_assignment}")
    for operation in logical:
        if int(operation["group"]) not in groups:
            continue
        worker = (
            "worker0"
            if worker_assignment == "collapse"
            else str(operation["node"])
        )
        timestamp_s = int(operation["plan_unix_ns"]) / 1e9
        for key in operation["keys"]:
            for rank in range(tp_size):
                yield worker, timestamp_s, (rank, str(key))


def local_miss_replay(
    logical: list[dict[str, Any]],
    groups: set[int],
    *,
    slots_each: int,
    tp_size: int,
    worker_assignment: str,
) -> tuple[ReuseCurve, dict[str, Any]]:
    caches: dict[str, OrderedDict[tuple[int, str], None]] = {}
    counters: Counter[str] = Counter()
    per_worker: dict[str, Counter[str]] = {}
    downstream: list[tuple[int, str]] = []

    for worker, _timestamp_s, identity in iter_physical_accesses(
        logical,
        groups,
        tp_size=tp_size,
        worker_assignment=worker_assignment,
    ):
        cache = caches.setdefault(worker, OrderedDict())
        worker_counts = per_worker.setdefault(worker, Counter())
        counters["accesses"] += 1
        worker_counts["accesses"] += 1
        if identity in cache:
            counters["hits"] += 1
            worker_counts["hits"] += 1
            cache.move_to_end(identity)
            continue
        counters["misses"] += 1
        worker_counts["misses"] += 1
        downstream.append(identity)
        cache[identity] = None
        if len(cache) > slots_each:
            cache.popitem(last=False)
            counters["evictions"] += 1
            worker_counts["evictions"] += 1

    curve = build_reuse_curve(downstream)
    return curve, {
        **dict(counters),
        "slots_each": slots_each,
        "workers": {
            worker: dict(counts) for worker, counts in sorted(per_worker.items())
        },
        "remote_stream_accesses": curve.accesses,
        "remote_stream_unique_items": curve.cold_misses,
    }


def active_gib_to_slots(
    active_gib: float, *, value_bytes: int, remote_payload_ratio: float
) -> int:
    return math.floor(active_gib * GIB * remote_payload_ratio / value_bytes)


def slots_to_active_gib(
    slots: int, *, value_bytes: int, remote_payload_ratio: float
) -> float:
    return slots * value_bytes / (GIB * remote_payload_ratio)


def misses_per_request(
    curve: ReuseCurve,
    active_gib: float,
    requests: int,
    *,
    value_bytes: int,
    remote_payload_ratio: float,
) -> float:
    slots = active_gib_to_slots(
        active_gib,
        value_bytes=value_bytes,
        remote_payload_ratio=remote_payload_ratio,
    )
    return curve.capacity_miss_count(slots) / requests


def capacity_for_budget(
    curve: ReuseCurve,
    budget_per_request: float,
    requests: int,
    *,
    value_bytes: int,
    remote_payload_ratio: float,
) -> float | None:
    slots = curve.minimum_slots(
        budget_per_request * requests + curve.cold_misses
    )
    if slots is None:
        return None
    return slots_to_active_gib(
        slots,
        value_bytes=value_bytes,
        remote_payload_ratio=remote_payload_ratio,
    )


def service_calibration(model: dict[str, Any]) -> dict[str, float]:
    gate = model["capacity_gate_curves"]["service_floor"]["ssd_on"]
    crossing = gate.get("isotonic_crossing_axis_gib")
    bracket = gate["observed_bracket"]
    failed = bracket.get("failed_axis_gib")
    passed = bracket.get("passed_axis_gib")
    if crossing is None or failed is None or passed is None:
        raise ValueError("SSD-on service-floor calibration is not bracketed")
    if not float(failed) < float(crossing) <= float(passed):
        raise ValueError("SSD-on crossing lies outside its observed bracket")
    return {
        "qps_floor": float(gate["qps_floor"]),
        "point_active_gib": float(crossing),
        "failed_active_gib": float(failed),
        "passed_active_gib": float(passed),
    }


def session_wss(
    chains: dict[int, tuple[str, ...]],
    groups: list[int],
    *,
    tp_size: int,
    value_bytes: int,
) -> float:
    return (
        sum(len(chains[group]) for group in groups)
        * tp_size
        * value_bytes
        / GIB
    )


def worker_session_wss(
    chains: dict[int, tuple[str, ...]],
    groups: list[int],
    assignments: dict[int, str],
    *,
    tp_size: int,
    value_bytes: int,
) -> dict[str, float]:
    pages: Counter[str] = Counter()
    for group in groups:
        pages[assignments[group]] += len(chains[group])
    return {
        worker: count * tp_size * value_bytes / GIB
        for worker, count in sorted(pages.items())
    }


def make_surface_row(
    profile: ReplayProfile,
    curve: ReuseCurve,
    local_stats: dict[str, Any],
    *,
    global_wss_gib: float,
    worker_wss_gib: dict[str, float],
    budgets: dict[str, float],
    capacity_offsets_gib: dict[str, float],
    value_bytes: int,
    remote_payload_ratio: float,
    reference_remote_gib: float,
) -> dict[str, Any]:
    requests = profile.sessions * profile.turns
    raw_capacities = {
        name: capacity_for_budget(
            curve,
            budget,
            requests,
            value_bytes=value_bytes,
            remote_payload_ratio=remote_payload_ratio,
        )
        for name, budget in budgets.items()
    }
    capacities = {
        name: (
            None
            if capacity is None
            else 0.0
            if capacity == 0.0
            else max(0.0, capacity + capacity_offsets_gib[name])
        )
        for name, capacity in raw_capacities.items()
    }
    point = capacities["point"]
    lenient = capacities["failed_side"]
    strict = capacities["passed_side"]
    return {
        **asdict(profile),
        "requests": requests,
        "global_host_visible_wss_gib": global_wss_gib,
        "worker_host_visible_wss_gib": worker_wss_gib,
        "max_worker_host_visible_wss_gib": max(worker_wss_gib.values()),
        "local_slots_each": local_stats["slots_each"],
        "local_access_items": local_stats.get("accesses", 0),
        "local_miss_items": local_stats.get("misses", 0),
        "local_misses_per_request": local_stats.get("misses", 0) / requests,
        "remote_stream_unique_items": curve.cold_misses,
        "remote_stream_unique_gib": curve.cold_misses * value_bytes / GIB,
        "predicted_remote_active_gib": point,
        "raw_predicted_remote_active_gib": raw_capacities["point"],
        "evidence_band_lower_open_gib": lenient,
        "evidence_band_upper_gib": strict,
        "saved_vs_reference_gib": (
            reference_remote_gib - point if point is not None else None
        ),
        "remote_performance_knee_status": (
            "unreachable"
            if point is None
            else "local_fit_remote_floor_not_identified"
            if point == 0.0
            else "trace_calibrated_prediction"
        ),
        "local_replay": local_stats,
    }


def render_markdown(result: dict[str, Any]) -> str:
    calibration = result["calibration"]
    trace = result["trace_audit"]
    base = result["base_replay"]
    legacy = result["legacy_shape_validation"]
    surface_by_shape = {
        (row["sessions"], row["gpu_payload_gib_each"]): row
        for row in result["surface"]
    }
    base_96 = surface_by_shape.get((96, 115.2))
    local_96 = surface_by_shape.get((96, 96.0))
    base_72 = surface_by_shape.get((72, 115.2))
    if base_96 is not None and local_96 is not None and base_72 is not None:
        cliff_note = (
            "这张表最重要的形状是 local-fit cliff，不是平滑线性换算。"
            f"96 sessions 时最大 worker WSS 为 `{base_96['max_worker_host_visible_wss_gib']:.1f} GiB`；"
            f"payload 从 `115.2` 降到 `96 GiB`，remote 点估计从 "
            f"`{base_96['predicted_remote_active_gib']:.1f}` 跳到 "
            f"`{local_96['predicted_remote_active_gib']:.1f} GiB`。"
            f"72 sessions 时最大 worker WSS 为 `{base_72['max_worker_host_visible_wss_gib']:.1f} GiB`，"
            "115.2-GiB local 已覆盖这份工作集，remote 性能 knee 才消失。"
        )
    else:
        cliff_note = (
            "容量曲线的主要非线性来自每个worker的working set是否跨过local payload；"
            "自定义网格应在local-fit边界两侧各保留至少一个点。"
        )
    lines = [
        "# Fluxon 负载 × GPU-owner KV 容量 → remote DRAM 仿真模型",
        "",
        f"生成时间：{result['generated_at']}",
        "",
        "## 先说结论",
        "",
        "这版先给出可计算的容量曲面，不再继续补集群点。SSD 固定开启，scope 固定为 "
        "`gpu_local_only`，读取顺序固定为 `local DRAM → local SSD → remote DRAM`。",
        "",
        f"当前 96 sessions、每个 GPU owner 有效 payload `115.2 GiB` 时，r95 SSD-on "
        f"的 10-QPS isotonic crossing 是 `{calibration['point_active_gib']:.3f} GiB`；"
        f"实测只把它夹在 `({calibration['failed_active_gib']:.0f}, "
        f"{calibration['passed_active_gib']:.0f}] GiB`，所以表中的点估计不能当成已验收配置。",
        "",
        "表里的“相对 256 GiB 可减”表示在 SSD-on 固定条件下的总容量余量。它不等于 SSD "
        "独自替代的内存：同容量 SSD-off 当前并不更差，SSD 可归因替代量仍未被实验证明为正。",
        "",
        "## 模型",
        "",
        "每个请求先回放 owner-local LRU；local miss 形成共享 remote 的访问流。对 remote "
        "访问流计算精确 LRU stack distance。当前实测 crossing 对应的下层 "
        "reuse/capacity miss/request "
        "被定义为可接受预算 `b*`：",
        "",
        "```text",
        "b* = remote_capacity_misses(S=96, C_local=115.2, C_remote=226.852) / 2304",
        "C_remote*(S, C_local) = min { C | remote_capacity_misses(S, C_local, C) / requests ≤ b* }",
        "saved(S, C_local) = 256 GiB - C_remote*(S, C_local)",
        "```",
        "",
        f"中心预算为 `{base['budgets_misses_per_request']['point']:.3f}` 个物理 KV/request。"
        f"失败侧/通过侧分别给出 `{base['budgets_misses_per_request']['failed_side']:.3f}` / "
        f"`{base['budgets_misses_per_request']['passed_side']:.3f}`，用于传播当前稀疏锚点的不确定性。",
        "",
        "## 容量曲面",
        "",
        "固定两个 TP2 worker、每 session 24 turns；concurrency 随 sessions 按基线 1:4 缩放。"
        "payload 是每个 GPU owner 的有效 host-KV payload，不是物理 DRAM，也不是 HBM allocator 容量。",
        "",
        "| sessions / c | payload/owner | max worker WSS | global WSS | remote点估计 | 实测锚点传播区间 | 相对256可减 |",
        "|---:|---:|---:|---:|---:|:---:|---:|",
    ]
    for row in result["surface"]:
        point = row["predicted_remote_active_gib"]
        lower = row["evidence_band_lower_open_gib"]
        upper = row["evidence_band_upper_gib"]
        saved = row["saved_vs_reference_gib"]
        point_text = (
            "不可达"
            if point is None
            else "0（local-fit）"
            if point == 0.0
            else f"{point:.1f} GiB"
        )
        band_text = (
            "不可达"
            if lower is None or upper is None
            else "下限未识别"
            if lower == 0.0 and upper == 0.0
            else f"({lower:.1f}, {upper:.1f}] GiB"
        )
        saved_text = (
            "不可达"
            if saved is None
            else "≤256（部署下限未建模）"
            if point == 0.0
            else f"{saved:+.1f} GiB"
        )
        lines.append(
            f"| {row['sessions']} / {row['concurrency']} | "
            f"{row['gpu_payload_gib_each']:.1f} GiB | "
            f"{row['max_worker_host_visible_wss_gib']:.1f} GiB | "
            f"{row['global_host_visible_wss_gib']:.1f} GiB | {point_text} | "
            f"{band_text} | {saved_text} |"
        )

    lines.extend(
        [
            "",
            "表中的 `0（local-fit）` 只表示当前 trace 下 local cache 已把 capacity miss 压到预算内，"
            "remote 的性能 knee 无法继续识别。它不是可直接部署的 0-GiB 配置；持久 backing、"
            "故障恢复和 remote owner 最小运行容量仍需另设下限。",
            "",
            cliff_note,
        ]
    )

    lines.extend(
        [
            "",
            "## 校验",
            "",
            f"- request metrics=`{trace['request_metrics']['mapped_requests']}`，成功逻辑 lineage="
            f"`{trace['successful_replay_lineage']['logical_operations']}`，TP key/depth mismatch="
            f"`{trace['lineage']['tp_key_depth_mismatches']}`，session prefix violation="
            f"`{trace['sessions']['prefix_violations']}`；",
            f"- 96-session host-visible WSS=`{base['global_host_visible_wss_gib']:.3f} GiB`，"
            "与既有工作集模型一致；",
            f"- 用旧 r61 285.8-GiB anchor 只校准 96-session 预算，再预测 48 sessions / "
            f"1 worker，得到 `{legacy['predicted_remote_active_gib']:.3f} GiB`；独立实测括号为 "
            f"`({legacy['observed_bracket_gib'][0]:.0f}, {legacy['observed_bracket_gib'][1]:.0f}] GiB`，"
            f"判定=`{'通过' if legacy['inside_observed_bracket'] else '未通过'}`。",
            "",
            "## 这版不能回答的部分",
            "",
            "- r61 trace 只提供容量曲线形状，r95 SSD-on 实验提供服务预算；跨 release 校准已经显式保留，"
            "不能把仿真点写成新代码验收结果；",
            "- lineage 没记录 r95 每个 SSD persisted key。当前 SSD load 只占 remote probe 的千分之几，"
            "模型把固定 SSD 策略折进 anchor，不外推写带宽、读延迟或 SSD-specific hit rate；",
            "- concurrency 改变 batching、pin、queue 和瞬时 slot 压力。表中只允许 sessions 与 "
            "concurrency 按同一比例缩放；任意并发仍需要新锚点；",
            "- 生产使用 Moka TinyLFU，不是 LRU。区间只传播当前容量锚点，尚未包含替换策略误差；"
            "正式缩容仍需在预测 knee 两侧各跑完整重复轮。",
            "",
        ]
    )
    return "\n".join(lines)


def self_test() -> None:
    curve = build_reuse_curve([(0, "a"), (0, "b"), (0, "a"), (0, "b")])
    assert curve.cold_misses == 2
    assert curve.miss_count(0) == 4
    assert curve.miss_count(1) == 4
    assert curve.miss_count(2) == 2
    assert curve.capacity_miss_count(0) == 2
    assert curve.capacity_miss_count(2) == 0
    assert curve.minimum_slots(2) == 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lineage", action="append", default=[])
    parser.add_argument("--request-metrics", type=Path, action="append", default=[])
    parser.add_argument("--observed-ssd-model", type=Path)
    parser.add_argument("--sessions", type=int, action="append")
    parser.add_argument("--gpu-payload-gib", type=float, action="append")
    parser.add_argument("--turns", type=int, default=24)
    parser.add_argument("--base-sessions", type=int, default=96)
    parser.add_argument("--base-gpu-payload-gib", type=float, default=115.2)
    parser.add_argument("--tp-size", type=int, default=2)
    parser.add_argument("--value-bytes", type=int, default=4_718_592)
    parser.add_argument("--remote-payload-ratio", type=float, default=0.95)
    parser.add_argument("--reference-remote-gib", type=float, default=256.0)
    parser.add_argument("--legacy-base-knee-gib", type=float, default=285.8)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--output-md", type=Path)
    parser.add_argument("--generated-at", default="2026-07-28 HKT")
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
        "--observed-ssd-model": args.observed_ssd_model,
        "--output-json": args.output_json,
        "--output-md": args.output_md,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        parser.error(f"missing required arguments: {', '.join(missing)}")
    if not 0.0 < args.remote_payload_ratio <= 1.0:
        parser.error("--remote-payload-ratio must be in (0,1]")

    requests, request_audit = load_request_metrics(args.request_metrics)
    all_events = load_events(args.lineage)
    successful_events = [
        event
        for event in all_events
        if event.get("terminal") == "load_back_consumed"
    ]
    all_logical, lineage_audit = logical_lineage(
        all_events, requests, args.tp_size
    )
    logical, replay_lineage_audit = logical_lineage(
        successful_events, requests, args.tp_size
    )
    chains, session_audit = build_session_chains(all_logical, requests)
    assignments, assignment_audit = attach_and_audit_worker_assignments(logical)
    if session_audit["missing_lineage_groups"]:
        raise ValueError("some request groups have no successful lineage")

    observed = json.loads(args.observed_ssd_model.read_text(encoding="utf-8"))
    calibration = service_calibration(observed)
    sessions_grid = sorted(set(args.sessions or [24, 48, 72, 96]))
    payload_grid = sorted(set(args.gpu_payload_gib or [64.0, 80.0, 96.0, 115.2]))
    if args.base_sessions not in sessions_grid:
        sessions_grid.append(args.base_sessions)
        sessions_grid.sort()
    if args.base_gpu_payload_gib not in payload_grid:
        payload_grid.append(args.base_gpu_payload_gib)
        payload_grid.sort()

    base_groups = selected_groups(chains, args.base_sessions)
    base_slots = math.floor(args.base_gpu_payload_gib * GIB / args.value_bytes)
    base_curve, base_local = local_miss_replay(
        logical,
        set(base_groups),
        slots_each=base_slots,
        tp_size=args.tp_size,
        worker_assignment="trace",
    )
    base_requests = args.base_sessions * args.turns
    budgets = {
        "point": misses_per_request(
            base_curve,
            calibration["point_active_gib"],
            base_requests,
            value_bytes=args.value_bytes,
            remote_payload_ratio=args.remote_payload_ratio,
        ),
        "failed_side": misses_per_request(
            base_curve,
            calibration["failed_active_gib"],
            base_requests,
            value_bytes=args.value_bytes,
            remote_payload_ratio=args.remote_payload_ratio,
        ),
        "passed_side": misses_per_request(
            base_curve,
            calibration["passed_active_gib"],
            base_requests,
            value_bytes=args.value_bytes,
            remote_payload_ratio=args.remote_payload_ratio,
        ),
    }
    calibration_targets = {
        "point": calibration["point_active_gib"],
        "failed_side": calibration["failed_active_gib"],
        "passed_side": calibration["passed_active_gib"],
    }
    raw_base_inverse = {
        name: capacity_for_budget(
            base_curve,
            budget,
            base_requests,
            value_bytes=args.value_bytes,
            remote_payload_ratio=args.remote_payload_ratio,
        )
        for name, budget in budgets.items()
    }
    if any(value is None for value in raw_base_inverse.values()):
        raise ValueError("base calibration has no finite inverse capacity")
    capacity_offsets_gib = {
        name: calibration_targets[name] - float(raw_base_inverse[name])
        for name in budgets
    }

    surface: list[dict[str, Any]] = []
    replay_cache: dict[tuple[int, float], tuple[ReuseCurve, dict[str, Any]]] = {}
    for sessions in sessions_grid:
        groups = selected_groups(chains, sessions)
        global_wss_gib = session_wss(
            chains,
            groups,
            tp_size=args.tp_size,
            value_bytes=args.value_bytes,
        )
        worker_wss_gib = worker_session_wss(
            chains,
            groups,
            assignments,
            tp_size=args.tp_size,
            value_bytes=args.value_bytes,
        )
        for payload_gib in payload_grid:
            slots = math.floor(payload_gib * GIB / args.value_bytes)
            curve, local_stats = local_miss_replay(
                logical,
                set(groups),
                slots_each=slots,
                tp_size=args.tp_size,
                worker_assignment="trace",
            )
            replay_cache[(sessions, payload_gib)] = (curve, local_stats)
            surface.append(
                make_surface_row(
                    ReplayProfile(
                        sessions=sessions,
                        turns=args.turns,
                        concurrency=max(1, sessions // 4),
                        workers=2,
                        gpu_payload_gib_each=payload_gib,
                    ),
                    curve,
                    local_stats,
                    global_wss_gib=global_wss_gib,
                    worker_wss_gib=worker_wss_gib,
                    budgets=budgets,
                    capacity_offsets_gib=capacity_offsets_gib,
                    value_bytes=args.value_bytes,
                    remote_payload_ratio=args.remote_payload_ratio,
                    reference_remote_gib=args.reference_remote_gib,
                )
            )

    legacy_budget = misses_per_request(
        base_curve,
        args.legacy_base_knee_gib,
        base_requests,
        value_bytes=args.value_bytes,
        remote_payload_ratio=args.remote_payload_ratio,
    )
    legacy_groups = selected_groups(chains, 48)
    legacy_curve, legacy_local = local_miss_replay(
        logical,
        set(legacy_groups),
        slots_each=base_slots,
        tp_size=args.tp_size,
        worker_assignment="collapse",
    )
    legacy_prediction = capacity_for_budget(
        legacy_curve,
        legacy_budget,
        48 * args.turns,
        value_bytes=args.value_bytes,
        remote_payload_ratio=args.remote_payload_ratio,
    )
    if legacy_prediction is None:
        raise ValueError("legacy shape validation has no finite capacity")
    legacy_bracket = [128.0, 145.0]

    r95_baseline = observed.get("baseline", {})
    ssd_load_fraction = (
        float(r95_baseline.get("load_successes_mean", 0.0))
        / float(r95_baseline.get("local_probe_remote_items_mean", 1.0))
    )
    result = {
        "schema": "e44_joint_cache_surface_simulation_v1",
        "generated_at": args.generated_at,
        "objective": {
            "ssd_fixed_enabled": True,
            "ssd_scope": "gpu_local_only",
            "read_order": ["local_dram", "local_ssd", "remote_dram"],
            "qps_floor": calibration["qps_floor"],
            "reference_remote_active_gib": args.reference_remote_gib,
            "ssd_attributable_savings_status": "unproven_non_positive_in_current_pairs",
        },
        "geometry": {
            "tp_size": args.tp_size,
            "value_bytes_per_physical_kv": args.value_bytes,
            "remote_payload_ratio": args.remote_payload_ratio,
            "base_gpu_owner_payload_gib_each": args.base_gpu_payload_gib,
        },
        "trace_audit": {
            "request_metrics": request_audit,
            "lineage": lineage_audit,
            "successful_replay_lineage": replay_lineage_audit,
            "sessions": session_audit,
            "assignments": assignment_audit,
        },
        "calibration": {
            **calibration,
            "source_model": str(args.observed_ssd_model),
            "budgets_misses_per_request": budgets,
            "inverse_capacity_closure_offsets_gib": capacity_offsets_gib,
            "r95_observed_ssd_load_fraction_of_remote_probe": ssd_load_fraction,
            "ssd_key_identity_available_in_trace": False,
        },
        "base_replay": {
            "sessions": args.base_sessions,
            "requests": base_requests,
            "global_host_visible_wss_gib": session_wss(
                chains,
                base_groups,
                tp_size=args.tp_size,
                value_bytes=args.value_bytes,
            ),
            "local": base_local,
            "remote_curve": {
                "accesses": base_curve.accesses,
                "cold_misses": base_curve.cold_misses,
                "reuse_observations": len(base_curve.reuse_distances),
            },
            "budgets_misses_per_request": budgets,
            "raw_inverse_capacity_gib": raw_base_inverse,
            "calibrated_inverse_capacity_gib": calibration_targets,
        },
        "surface": surface,
        "legacy_shape_validation": {
            "calibration_release": "r61 capacity model",
            "base_sessions": 96,
            "base_knee_gib": args.legacy_base_knee_gib,
            "target_sessions": 48,
            "target_workers": 1,
            "target_local_payload_gib": args.base_gpu_payload_gib,
            "predicted_remote_active_gib": legacy_prediction,
            "observed_bracket_gib": legacy_bracket,
            "inside_observed_bracket": legacy_bracket[0]
            < legacy_prediction
            <= legacy_bracket[1],
            "target_local_replay": legacy_local,
        },
        "limits": [
            "r61 lineage supplies curve shape while r95 SSD-on supplies the service anchor",
            "SSD persisted-key identities are not present; fixed SSD behavior is folded into the anchor",
            "the evidence band propagates the observed fail/pass bracket, not all model error",
            "sessions and concurrency are only scaled together at the baseline 4:1 ratio",
            "production Moka TinyLFU, pins and batch order require cluster validation",
        ],
    }

    assert args.output_json is not None
    assert args.output_md is not None
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    args.output_md.write_text(render_markdown(result), encoding="utf-8")
    print(
        json.dumps(
            {
                "calibration": result["calibration"],
                "base_replay": result["base_replay"],
                "legacy_shape_validation": result["legacy_shape_validation"],
                "surface_rows": len(surface),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
