#!/usr/bin/env python3
"""Fit a DRAM/SSD sizing model and backtest it against existing E44 runs.

The model keeps four questions separate:

* workload and per-worker local capacity determine a local-miss stream;
* a shared remote reuse-distance curve determines required remote DRAM;
* SSD write rate and the useful reuse-retention window determine SSD bytes;
* SSD may reduce remote DRAM only after a positive same-release knee shift is
  measured. Provisioned SSD bytes alone never receive substitution credit.

The output is a trace-calibrated sizing surface and an explicit validation
matrix. It is not an online controller and it does not mutate the cluster.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import OrderedDict
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean
from typing import Any

from analyze_e44_r60_kv_lineage import load_events
from model_e44_local_ssd_knee import load_run, parse_env
from model_e44_resource_load_scaling import (
    build_session_chains,
    load_request_metrics,
    logical_lineage,
    selected_groups,
)
from simulate_e44_joint_cache_surface import iter_physical_accesses


GIB = 1 << 30
MIB = 1 << 20


@dataclass(frozen=True)
class PolicyAnchor:
    name: str
    artifact: str
    qps: float
    wall_s: float
    write_rate_bytes_per_s_each: int
    write_burst_bytes_each: int
    configured_ssd_bytes_each: int
    persist_bytes: int
    load_bytes: int
    persist_items: int
    load_items: int
    used_bytes_by_node: dict[str, int]
    persist_bytes_by_node: dict[str, int]
    load_bytes_by_node: dict[str, int]

    @property
    def owners(self) -> int:
        return len(self.used_bytes_by_node)

    @property
    def configured_rate_bound_bytes(self) -> float:
        return self.owners * (
            self.write_rate_bytes_per_s_each * self.wall_s
            + self.write_burst_bytes_each
        )

    @property
    def rate_bound_utilization(self) -> float | None:
        if self.configured_rate_bound_bytes <= 0:
            return None
        return self.persist_bytes / self.configured_rate_bound_bytes

    @property
    def observed_write_mib_per_s_total(self) -> float:
        return self.persist_bytes / self.wall_s / MIB

    @property
    def observed_read_mib_per_s_total(self) -> float:
        return self.load_bytes / self.wall_s / MIB


def parse_named_path(raw: str) -> tuple[str, Path]:
    name, separator, path = raw.partition("=")
    if not separator or not name or not path:
        raise argparse.ArgumentTypeError("anchor must be NAME=ARTIFACT")
    return name, Path(path)


def validate_lineage_workers(
    events: list[dict[str, Any]], expected_workers: int
) -> list[str]:
    workers = sorted({str(event["node"]) for event in events})
    if len(workers) != expected_workers:
        raise ValueError(
            "lineage worker identity mismatch: "
            f"expected={expected_workers} observed={len(workers)} "
            f"workers={workers}; label each input as NODE=PATH when source "
            "basenames are not unique"
        )
    return workers


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
    return float(
        ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction
    )


def distribution(values: list[float]) -> dict[str, float | int | None]:
    return {
        "count": len(values),
        "mean": mean(values) if values else None,
        "p50": percentile(values, 0.50),
        "p90": percentile(values, 0.90),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
        "max": max(values) if values else None,
    }


def load_policy_anchor(name: str, artifact: Path) -> PolicyAnchor:
    run = load_run(artifact, expect_ssd=True)
    env = parse_env(artifact / "capacity.env")
    used = {
        node: int(row["ssd"].get("used_bytes", 0))
        for node, row in run["node_rows"].items()
    }
    persisted = {
        node: int(row["ssd"].get("persist_bytes", 0))
        for node, row in run["node_rows"].items()
    }
    loaded = {
        node: int(row["ssd"].get("load_bytes", 0))
        for node, row in run["node_rows"].items()
    }
    return PolicyAnchor(
        name=name,
        artifact=str(artifact),
        qps=float(run["qps"]),
        wall_s=float(run["wall_s"]),
        write_rate_bytes_per_s_each=int(
            env["gpu_ssd_write_rate_bytes_per_sec"]
        ),
        write_burst_bytes_each=int(env["gpu_ssd_write_burst_bytes"]),
        configured_ssd_bytes_each=int(env["gpu_ssd_capacity_bytes_each"]),
        persist_bytes=int(run["persist_bytes"]),
        load_bytes=int(run["load_bytes"]),
        persist_items=int(run["persist_successes"]),
        load_items=int(run["load_successes"]),
        used_bytes_by_node=used,
        persist_bytes_by_node=persisted,
        load_bytes_by_node=loaded,
    )


def local_miss_reuse_intervals(
    logical: list[dict[str, Any]],
    groups: set[int],
    *,
    slots_each: int,
    tp_size: int,
    worker_assignment: str = "trace",
) -> tuple[list[float], dict[str, Any]]:
    caches: dict[str, OrderedDict[tuple[int, str], None]] = {}
    last_miss_s: dict[tuple[str, int, str], float] = {}
    intervals: list[float] = []
    accesses = 0
    misses = 0
    first_timestamp_s: float | None = None
    last_timestamp_s: float | None = None

    for worker, timestamp_s, identity in iter_physical_accesses(
        logical,
        groups,
        tp_size=tp_size,
        worker_assignment=worker_assignment,
    ):
        accesses += 1
        first_timestamp_s = (
            timestamp_s
            if first_timestamp_s is None
            else min(first_timestamp_s, timestamp_s)
        )
        last_timestamp_s = (
            timestamp_s
            if last_timestamp_s is None
            else max(last_timestamp_s, timestamp_s)
        )
        cache = caches.setdefault(worker, OrderedDict())
        if identity in cache:
            cache.move_to_end(identity)
            continue
        misses += 1
        event_identity = (worker, identity[0], identity[1])
        previous = last_miss_s.get(event_identity)
        if previous is not None:
            intervals.append(timestamp_s - previous)
        last_miss_s[event_identity] = timestamp_s
        cache[identity] = None
        if len(cache) > slots_each:
            cache.popitem(last=False)

    duration_s = (
        0.0
        if first_timestamp_s is None or last_timestamp_s is None
        else last_timestamp_s - first_timestamp_s
    )
    return intervals, {
        "accesses": accesses,
        "local_misses": misses,
        "reuse_intervals": len(intervals),
        "duration_s": duration_s,
        "slots_each": slots_each,
    }


def retention_capacity(
    *,
    rate_bytes_per_s_each: int,
    burst_bytes_each: int,
    retention_s: float,
    headroom_ratio: float,
) -> dict[str, float]:
    raw_bytes = rate_bytes_per_s_each * retention_s + burst_bytes_each
    provisioned_bytes = raw_bytes * headroom_ratio
    return {
        "retention_s": retention_s,
        "raw_bytes_each": raw_bytes,
        "raw_gib_each": raw_bytes / GIB,
        "with_headroom_bytes_each": provisioned_bytes,
        "with_headroom_gib_each": provisioned_bytes / GIB,
        "rounded_candidate_gib_each": float(
            max(1, math.ceil(provisioned_bytes / GIB))
        ),
    }


def fit_rate_limited_write_model(
    anchors: list[PolicyAnchor],
) -> dict[str, Any]:
    if len(anchors) < 2:
        raise ValueError("at least two rate-limited anchors are required")
    utilizations = [
        float(anchor.rate_bound_utilization)
        for anchor in anchors
        if anchor.rate_bound_utilization is not None
    ]
    fitted = mean(utilizations)
    rows: list[dict[str, Any]] = []
    heldout_errors: list[float] = []
    for index, anchor in enumerate(anchors):
        training = [
            value for other, value in enumerate(utilizations) if other != index
        ]
        loo_utilization = mean(training)
        predicted = loo_utilization * anchor.configured_rate_bound_bytes
        error_percent = (
            100.0 * (predicted - anchor.persist_bytes) / anchor.persist_bytes
        )
        heldout_errors.append(abs(error_percent))
        rows.append(
            {
                "name": anchor.name,
                "actual_persist_bytes": anchor.persist_bytes,
                "rate_bound_bytes": anchor.configured_rate_bound_bytes,
                "observed_utilization": anchor.rate_bound_utilization,
                "loo_utilization": loo_utilization,
                "loo_predicted_persist_bytes": predicted,
                "loo_error_percent": error_percent,
            }
        )
    return {
        "model": "persist_bytes = utilization * owners * (Bw * wall + burst)",
        "fitted_utilization": fitted,
        "anchor_utilizations": utilizations,
        "max_leave_one_out_error_percent": max(heldout_errors),
        "rows": rows,
    }


def interpolate_local_knee(
    holdout: dict[str, Any], target_remote_gib: float
) -> dict[str, Any]:
    rows = sorted(
        (
            row
            for row in holdout["surface"]
            if int(row["sessions"]) == 96
        ),
        key=lambda row: float(row["gpu_payload_gib_each"]),
    )
    crossing: float | None = None
    crossing_pair: list[dict[str, float]] = []
    for left, right in zip(rows, rows[1:]):
        left_remote = float(left["predicted_remote_active_gib"])
        right_remote = float(right["predicted_remote_active_gib"])
        if left_remote > target_remote_gib >= right_remote:
            fraction = (left_remote - target_remote_gib) / (
                left_remote - right_remote
            )
            crossing = float(left["gpu_payload_gib_each"]) + fraction * (
                float(right["gpu_payload_gib_each"])
                - float(left["gpu_payload_gib_each"])
            )
            crossing_pair = [
                {
                    "payload_gib_each": float(left["gpu_payload_gib_each"]),
                    "predicted_remote_gib": left_remote,
                },
                {
                    "payload_gib_each": float(right["gpu_payload_gib_each"]),
                    "predicted_remote_gib": right_remote,
                },
            ]
            break
    if crossing is None:
        raise ValueError("local holdout surface does not cross target remote")
    return {
        "target_remote_active_gib": target_remote_gib,
        "predicted_local_payload_knee_gib_each": crossing,
        "crossing_pair": crossing_pair,
    }


def observed_local_bracket(local_model: dict[str, Any]) -> list[float]:
    bracket = local_model["observed_capacity_curve"]["observed_bracket"]
    failed = bracket.get(
        "failed_payload_gib_each", bracket.get("failed_axis_gib")
    )
    passed = bracket.get(
        "passed_payload_gib_each", bracket.get("passed_axis_gib")
    )
    if failed is None or passed is None:
        raise ValueError("local model has no closed observed bracket")
    return [float(failed), float(passed)]


def capacity_curve_bracket(curve: dict[str, Any]) -> list[float]:
    bracket = curve["observed_bracket"]
    failed = bracket.get(
        "failed_payload_gib_each", bracket.get("failed_axis_gib")
    )
    passed = bracket.get(
        "passed_payload_gib_each", bracket.get("passed_axis_gib")
    )
    if failed is None or passed is None:
        raise ValueError("capacity curve has no closed observed bracket")
    return [float(failed), float(passed)]


def make_policy_surface(
    joint: dict[str, Any],
    logical: list[dict[str, Any]],
    chains: dict[int, tuple[str, ...]],
    *,
    tp_size: int,
    value_bytes: int,
    rate_bytes_per_s_each: int,
    burst_bytes_each: int,
    read_budget_mib_per_s_each: float,
    retention_quantile: float,
    headroom_ratio: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for joint_row in joint["surface"]:
        sessions = int(joint_row["sessions"])
        payload_gib = float(joint_row["gpu_payload_gib_each"])
        remote_gib = joint_row["predicted_remote_active_gib"]
        groups = set(selected_groups(chains, sessions))
        slots = math.floor(payload_gib * GIB / value_bytes)
        intervals, replay = local_miss_reuse_intervals(
            logical,
            groups,
            slots_each=slots,
            tp_size=tp_size,
        )
        interval_summary = distribution(intervals)
        local_fit = (
            joint_row["remote_performance_knee_status"]
            == "local_fit_remote_floor_not_identified"
        )
        retention_s = (
            None
            if local_fit
            else percentile(intervals, retention_quantile)
        )
        capacity = (
            None
            if retention_s is None
            else retention_capacity(
                rate_bytes_per_s_each=rate_bytes_per_s_each,
                burst_bytes_each=burst_bytes_each,
                retention_s=retention_s,
                headroom_ratio=headroom_ratio,
            )
        )
        rows.append(
            {
                "sessions": sessions,
                "concurrency": int(joint_row["concurrency"]),
                "gpu_payload_gib_each": payload_gib,
                "max_worker_wss_gib": float(
                    joint_row["max_worker_host_visible_wss_gib"]
                ),
                "pressure_ratio": float(
                    joint_row["max_worker_host_visible_wss_gib"]
                )
                / payload_gib,
                "predicted_remote_active_gib": remote_gib,
                "remote_evidence_band_gib": [
                    joint_row["evidence_band_lower_open_gib"],
                    joint_row["evidence_band_upper_gib"],
                ],
                "policy_regime": (
                    "local_fit_last_backing_only"
                    if local_fit
                    else "pressure_selective_early_write"
                ),
                "early_write_rate_mib_per_s_each": (
                    0.0 if local_fit else rate_bytes_per_s_each / MIB
                ),
                "ssd_read_budget_mib_per_s_each": (
                    0.0 if local_fit else read_budget_mib_per_s_each
                ),
                "reuse_interval_s": interval_summary,
                "ssd_retention": capacity,
                "local_replay": replay,
                "ssd_performance_floor_identified": not local_fit,
            }
        )
    return rows


def render_markdown(result: dict[str, Any]) -> str:
    current = result["current_base_sizing"]
    no_eviction_candidate_gib = current["one_round_no_eviction"][
        "rounded_candidate_gib_each"
    ]
    p99_candidate_gib = current["p99_retention"][
        "rounded_candidate_gib_each"
    ]
    checks = result["backtest"]["checks"]
    local = result["backtest"]["local_capacity_holdout"]
    load = result["backtest"]["load_scaling_holdout"]
    write = result["backtest"]["ssd_write_volume"]
    lines = [
        "# Fluxon 负载/GPU资源 → DRAM/SSD 联合数学模型",
        "",
        f"生成时间：{result['generated_at']}",
        "",
        "## 结论",
        "",
        f"现有结果一致性检查=`{'通过' if result['backtest']['existing_results_consistent'] else '未通过'}`。"
        "当前模型先回答“现有SSD策略需要多少介质”，不提前给SSD容量记remote DRAM替代credit。",
        "",
        f"当前S96/c24、每owner local payload 115.2 GiB：remote active点估计"
        f"`{current['remote_active_point_gib']:.3f} GiB`，证据区间"
        f"`({current['remote_active_band_gib'][0]:.0f},"
        f"{current['remote_active_band_gib'][1]:.0f}] GiB`；",
        f"24 MiB/s/owner、13-KV burst下，local-miss reuse p95/p99="
        f"`{current['reuse_interval_s']['p95']:.2f}/"
        f"{current['reuse_interval_s']['p99']:.2f}s`。p99滚动窗口需要"
        f"`{current['p99_retention']['with_headroom_gib_each']:.3f} GiB/owner`，"
        f"首个容量候选向上取整为`{current['p99_retention']['rounded_candidate_gib_each']:.0f} GiB/owner`；",
        f"读写预算独立：写入上限`24 MiB/s/owner`，当前读流量加20%余量为"
        f"`{current['read_budget_with_headroom_mib_per_s_each']:.2f} MiB/s/owner`；",
        f"若完全不允许一轮内SSD驱逐，需要"
        f"`{current['one_round_no_eviction']['with_headroom_gib_each']:.3f} GiB/owner`，"
        f"首个保守验证点取`{current['one_round_no_eviction']['rounded_candidate_gib_each']:.0f} GiB/owner`。",
        "",
        "这两个SSD数都是数据容量，不包含文件系统预留；2-GiB点还没有真实容量实验，不能替换当前1.5-TiB配置直接上线。",
        "",
        "## 数学定义",
        "",
        "对worker i的KV访问流Ai，local容量G可容纳Ng=floor(G/v)个KV。local miss组成共享remote流D：",
        "",
        "```text",
        "D(L,G) = concat_i LRU_misses(Ai(L), floor(G/v))",
        "mR(C) = count(remote_reuse_distance(D) >= floor(0.95*C/v))",
        "CR*(L,G,π) = min { C | mR(D minus SSD_hits(π), C) / requests <= b* }",
        "CS*(π,q) = headroom * (Bw(π) * reuse_interval_q + burst)",
        "```",
        "",
        "联合优化目标为：",
        "",
        "```text",
        "minimize      CR + alpha * CS",
        "subject to    QPS >= 10",
        "              SSD_write_rate <= Bw",
        "              SSD_read_rate  <= Br",
        "              SSD p95 load latency <= prefetch lead",
        "              correctness/reclaim gates pass",
        "```",
        "",
        "当前策略没有测出正的SSD knee shift，因此模型强制"
        "`SSD_substitution_credit=0`。只有同release实验得到"
        "`Cmin,SSD-on < Cmin,SSD-off`后，SSD hit才允许从remote流中扣除。",
        "",
        "## 已有结果回测",
        "",
        "| 检查 | 预测 | 已有结果 | 结论 |",
        "|---|---:|---:|:---:|",
        f"| 48 sessions / 1 worker remote knee | "
        f"{load['predicted_remote_active_gib']:.3f} GiB | "
        f"({load['observed_bracket_gib'][0]:.0f},"
        f"{load['observed_bracket_gib'][1]:.0f}] GiB | "
        f"{'pass' if checks['load_scaling_holdout'] else 'fail'} |",
        f"| remote248反求local knee | "
        f"{local['predicted_local_payload_knee_gib_each']:.3f} GiB | "
        f"({local['observed_bracket_gib_each'][0]:.1f},"
        f"{local['observed_bracket_gib_each'][1]:.1f}] GiB | "
        f"{'pass' if checks['local_capacity_holdout'] else 'fail'} |",
        f"| 24-MiB/s写量LOO最大误差 | "
        f"{write['max_leave_one_out_error_percent']:.2f}% | <=5% | "
        f"{'pass' if checks['ssd_write_volume_holdout'] else 'fail'} |",
        f"| 当前SSD可归因knee shift | 0 GiB | r90=0，r95未证明为正 | "
        f"{'pass' if checks['zero_unproven_ssd_credit'] else 'fail'} |",
        "",
        "r94 full-rate与r94/r95 24-MiB/s不能混成一条性能线：full-rate实际写约"
        f"`{result['policy_anchors']['full_rate']['observed_write_mib_per_s_total']:.1f} MiB/s`"
        "且QPS<10；r95 pre-admission在约44 MiB/s总写入下通过。"
        "动态策略第一版因此把24 MiB/s/owner作为已验证上限，不在线探索更高rate。",
        "",
        "## 动态策略",
        "",
        "动态的是准入阈值、写rate和保留窗口，不是在线扩缩物理SSD：",
        "",
        "```text",
        "rho = max_worker_WSS / local_payload",
        "rho <= 1: early write = 0，只保留last-backing",
        "rho >  1: selective early write，Bw <= 24 MiB/s/owner，保留p99窗口",
        "```",
        "",
        "读写token继续分开；no-queue admission与try_lock不变。控制器先使用离线表和滞回，"
        "不引入actor、I/O backlog或在线强化学习。",
        "",
        "## 当前曲面",
        "",
        "| sessions/c | local/owner | pressure | remote点估计 | SSD候选/owner | 策略 |",
        "|---:|---:|---:|---:|---:|:---|",
    ]
    for row in result["policy_surface"]:
        remote = row["predicted_remote_active_gib"]
        remote_text = "local-fit" if remote == 0.0 else f"{remote:.1f} GiB"
        retention = row["ssd_retention"]
        ssd_text = (
            "性能下限未识别"
            if retention is None
            else f"{retention['rounded_candidate_gib_each']:.0f} GiB"
        )
        lines.append(
            f"| {row['sessions']}/{row['concurrency']} | "
            f"{row['gpu_payload_gib_each']:.1f} GiB | "
            f"{row['pressure_ratio']:.3f} | {remote_text} | {ssd_text} | "
            f"{row['policy_regime']} |"
        )
    lines.extend(
        [
            "",
            "## 最小验证矩阵",
            "",
            f"1. 保持remote248、SSD-on、24 MiB/s和所有负载配置不变，把每owner SSD从1.5 TiB降到"
            f"{no_eviction_candidate_gib:.0f} GiB；"
            "该点不应发生一轮内容量驱逐，用于验证容量公式不改变行为。",
            f"2. 第1步重复通过后，降到{p99_candidate_gib:.0f} GiB/owner；"
            "该点会启用p99滚动保留，用persist/load/eviction和QPS验证reuse窗口。",
            "3. SSD容量轴通过后，才测试remote容量中心及上侧安全点；不能把SSD缩容和remote缩容放在同一首轮。",
            "4. 动态rate/threshold最后开启，并先与静态24 MiB/s做同容量A/B；任一阶段QPS<10或错误链非0即停止。",
            "",
            "## 尚未识别",
            "",
            "- lineage输入必须保留两个独立worker identity；文件basename不唯一时使用`NODE=PATH`。模型会在worker数不等于2时fail-closed；",
            "- 当前GPU资源轴是TP2 worker数量与GPU-owner host-KV payload；HBM KV slot没有独立实验，不能外推；",
            "- SSD persisted-key identity不在r61 trace，2-GiB候选依赖全体local-miss reuse分布，必须真实验证；",
            "- local-fit只消除remote性能knee，不消除持久backing、故障恢复和remote owner最小容量；",
            f"- 现有SSD容量从未成为瓶颈，物理容量收益只能由"
            f"{no_eviction_candidate_gib:.0f}→{p99_candidate_gib:.0f} GiB实验封口。",
            "",
        ]
    )
    return "\n".join(lines)


def self_test() -> None:
    values = [1.0, 2.0, 3.0, 4.0]
    assert percentile(values, 0.5) == 2.5
    capacity = retention_capacity(
        rate_bytes_per_s_each=24 * MIB,
        burst_bytes_each=13 * 4_718_592,
        retention_s=60.0,
        headroom_ratio=1.2,
    )
    assert capacity["rounded_candidate_gib_each"] == 2.0
    assert validate_lineage_workers(
        [{"node": "node0"}, {"node": "node1"}], 2
    ) == ["node0", "node1"]
    try:
        validate_lineage_workers([{"node": "same"}, {"node": "same"}], 2)
    except ValueError as exc:
        assert "NODE=PATH" in str(exc)
    else:
        raise AssertionError("collapsed lineage workers were not rejected")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lineage", action="append", default=[])
    parser.add_argument(
        "--request-metrics", type=Path, action="append", default=[]
    )
    parser.add_argument("--joint-model", type=Path)
    parser.add_argument("--local-holdout-surface", type=Path)
    parser.add_argument("--r90-local-model", type=Path)
    parser.add_argument(
        "--rate24-anchor", type=parse_named_path, action="append", default=[]
    )
    parser.add_argument("--full-rate-anchor", type=parse_named_path)
    parser.add_argument("--one-kv-anchor", type=parse_named_path)
    parser.add_argument("--current-anchor-name", default="r95_remote248")
    parser.add_argument("--expected-workers", type=int, default=2)
    parser.add_argument("--tp-size", type=int, default=2)
    parser.add_argument("--value-bytes", type=int, default=4_718_592)
    parser.add_argument(
        "--safe-write-rate-bytes-per-s-each",
        type=int,
        default=25_165_824,
    )
    parser.add_argument(
        "--safe-write-burst-bytes-each", type=int, default=61_341_696
    )
    parser.add_argument("--retention-quantile", type=float, default=0.99)
    parser.add_argument("--ssd-headroom-ratio", type=float, default=1.20)
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
        "--joint-model": args.joint_model,
        "--local-holdout-surface": args.local_holdout_surface,
        "--r90-local-model": args.r90_local_model,
        "--rate24-anchor": args.rate24_anchor,
        "--full-rate-anchor": args.full_rate_anchor,
        "--one-kv-anchor": args.one_kv_anchor,
        "--output-json": args.output_json,
        "--output-md": args.output_md,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        parser.error(f"missing required arguments: {', '.join(missing)}")
    if not 0.0 < args.retention_quantile < 1.0:
        parser.error("--retention-quantile must be in (0,1)")
    if args.ssd_headroom_ratio < 1.0:
        parser.error("--ssd-headroom-ratio must be >= 1")
    if args.expected_workers <= 0:
        parser.error("--expected-workers must be positive")

    all_events = load_events(args.lineage)
    validate_lineage_workers(all_events, args.expected_workers)
    successful_events = [
        event
        for event in all_events
        if event.get("terminal") == "load_back_consumed"
    ]
    requests, request_audit = load_request_metrics(args.request_metrics)
    all_logical, lineage_audit = logical_lineage(
        all_events, requests, args.tp_size
    )
    logical, replay_lineage_audit = logical_lineage(
        successful_events, requests, args.tp_size
    )
    chains, session_audit = build_session_chains(all_logical, requests)

    assert args.joint_model is not None
    assert args.local_holdout_surface is not None
    assert args.r90_local_model is not None
    joint = json.loads(args.joint_model.read_text(encoding="utf-8"))
    local_holdout = json.loads(
        args.local_holdout_surface.read_text(encoding="utf-8")
    )
    r90_local = json.loads(
        args.r90_local_model.read_text(encoding="utf-8")
    )

    rate24_anchors = [
        load_policy_anchor(name, path) for name, path in args.rate24_anchor
    ]
    if args.full_rate_anchor is None or args.one_kv_anchor is None:
        raise AssertionError("argparse required checks failed")
    full_rate = load_policy_anchor(*args.full_rate_anchor)
    one_kv = load_policy_anchor(*args.one_kv_anchor)
    current_by_name = {
        anchor.name: anchor
        for anchor in [*rate24_anchors, full_rate, one_kv]
    }
    if args.current_anchor_name not in current_by_name:
        raise ValueError(
            f"current anchor {args.current_anchor_name!r} is unavailable"
        )
    current_anchor = current_by_name[args.current_anchor_name]

    base_groups = set(selected_groups(chains, 96))
    base_slots = math.floor(115.2 * GIB / args.value_bytes)
    base_intervals, base_replay = local_miss_reuse_intervals(
        logical,
        base_groups,
        slots_each=base_slots,
        tp_size=args.tp_size,
    )
    base_interval_summary = distribution(base_intervals)
    p95_s = float(base_interval_summary["p95"])
    p99_s = float(base_interval_summary["p99"])
    p95_capacity = retention_capacity(
        rate_bytes_per_s_each=args.safe_write_rate_bytes_per_s_each,
        burst_bytes_each=args.safe_write_burst_bytes_each,
        retention_s=p95_s,
        headroom_ratio=args.ssd_headroom_ratio,
    )
    p99_capacity = retention_capacity(
        rate_bytes_per_s_each=args.safe_write_rate_bytes_per_s_each,
        burst_bytes_each=args.safe_write_burst_bytes_each,
        retention_s=p99_s,
        headroom_ratio=args.ssd_headroom_ratio,
    )
    one_round_capacity = retention_capacity(
        rate_bytes_per_s_each=args.safe_write_rate_bytes_per_s_each,
        burst_bytes_each=args.safe_write_burst_bytes_each,
        retention_s=current_anchor.wall_s,
        headroom_ratio=args.ssd_headroom_ratio,
    )

    write_model = fit_rate_limited_write_model(rate24_anchors)
    local_prediction = interpolate_local_knee(local_holdout, 248.0)
    local_bracket = observed_local_bracket(r90_local)
    control_local_bracket = capacity_curve_bracket(
        r90_local["control_capacity_curve"]
    )
    r90_ssd_knee_shift = (
        control_local_bracket[1] - local_bracket[1]
    )
    r95_ssd_status = str(
        joint["objective"]["ssd_attributable_savings_status"]
    )
    zero_ssd_credit_supported = math.isclose(
        r90_ssd_knee_shift, 0.0, abs_tol=1e-9
    ) and not r95_ssd_status.startswith("proven_positive")
    local_prediction["observed_bracket_gib_each"] = local_bracket
    local_prediction["inside_observed_bracket"] = (
        local_bracket[0]
        < local_prediction["predicted_local_payload_knee_gib_each"]
        <= local_bracket[1]
    )
    load_validation = joint["legacy_shape_validation"]

    base_joint_row = next(
        row
        for row in joint["surface"]
        if int(row["sessions"]) == 96
        and math.isclose(float(row["gpu_payload_gib_each"]), 115.2)
    )
    policy_surface = make_policy_surface(
        joint,
        logical,
        chains,
        tp_size=args.tp_size,
        value_bytes=args.value_bytes,
        rate_bytes_per_s_each=args.safe_write_rate_bytes_per_s_each,
        burst_bytes_each=args.safe_write_burst_bytes_each,
        read_budget_mib_per_s_each=(
            max(
                value / current_anchor.wall_s / MIB
                for value in current_anchor.load_bytes_by_node.values()
            )
            * args.ssd_headroom_ratio
        ),
        retention_quantile=args.retention_quantile,
        headroom_ratio=args.ssd_headroom_ratio,
    )

    fitted_current_persist = (
        write_model["fitted_utilization"]
        * current_anchor.configured_rate_bound_bytes
    )
    current_persist_error_percent = (
        100.0
        * (fitted_current_persist - current_anchor.persist_bytes)
        / current_anchor.persist_bytes
    )
    current_read_mib_per_s_by_node = {
        node: value / current_anchor.wall_s / MIB
        for node, value in current_anchor.load_bytes_by_node.items()
    }
    read_budget_with_headroom = (
        max(current_read_mib_per_s_by_node.values())
        * args.ssd_headroom_ratio
    )
    checks = {
        "load_scaling_holdout": bool(
            load_validation["inside_observed_bracket"]
        ),
        "local_capacity_holdout": bool(
            local_prediction["inside_observed_bracket"]
        ),
        "ssd_write_volume_holdout": (
            write_model["max_leave_one_out_error_percent"] <= 5.0
        ),
        "base_remote_anchor_closes": math.isclose(
            float(base_joint_row["predicted_remote_active_gib"]),
            float(joint["calibration"]["point_active_gib"]),
            abs_tol=1e-9,
        ),
        "zero_unproven_ssd_credit": zero_ssd_credit_supported,
    }
    result = {
        "schema": "e44_dram_ssd_autosizing_model_v1",
        "generated_at": args.generated_at,
        "objective": {
            "inputs": [
                "sessions/turns/concurrency",
                "active TP2 workers",
                "gpu_owner_host_kv_payload",
            ],
            "outputs": [
                "remote_active_dram",
                "local_ssd_data_capacity_each",
                "ssd_write_rate_each",
                "ssd_retention_window",
                "policy_regime",
            ],
            "qps_floor": 10.0,
            "ssd_substitution_credit_gib": 0.0,
            "reason": (
                "r90 SSD-on/off local knees are equal and r95 does not "
                "demonstrate a positive SSD-on remote knee shift"
            ),
        },
        "geometry": {
            "tp_size": args.tp_size,
            "value_bytes_per_physical_kv": args.value_bytes,
            "remote_payload_ratio": 0.95,
            "ssd_headroom_ratio": args.ssd_headroom_ratio,
        },
        "trace_audit": {
            "request_metrics": request_audit,
            "lineage": lineage_audit,
            "successful_replay_lineage": replay_lineage_audit,
            "sessions": session_audit,
        },
        "current_base_sizing": {
            "sessions": 96,
            "concurrency": 24,
            "gpu_owner_payload_gib_each": 115.2,
            "remote_active_point_gib": float(
                base_joint_row["predicted_remote_active_gib"]
            ),
            "remote_active_band_gib": [
                float(base_joint_row["evidence_band_lower_open_gib"]),
                float(base_joint_row["evidence_band_upper_gib"]),
            ],
            "safe_write_rate_mib_per_s_each": (
                args.safe_write_rate_bytes_per_s_each / MIB
            ),
            "safe_write_burst_gib_each": (
                args.safe_write_burst_bytes_each / GIB
            ),
            "reuse_interval_s": base_interval_summary,
            "p95_retention": p95_capacity,
            "p99_retention": p99_capacity,
            "one_round_no_eviction": one_round_capacity,
            "current_configured_ssd_gib_each": (
                current_anchor.configured_ssd_bytes_each / GIB
            ),
            "current_used_ssd_gib_by_node": {
                node: value / GIB
                for node, value in current_anchor.used_bytes_by_node.items()
            },
            "current_observed_write_mib_per_s_total": (
                current_anchor.observed_write_mib_per_s_total
            ),
            "current_observed_read_mib_per_s_total": (
                current_anchor.observed_read_mib_per_s_total
            ),
            "current_observed_read_mib_per_s_by_node": (
                current_read_mib_per_s_by_node
            ),
            "read_budget_with_headroom_mib_per_s_each": (
                read_budget_with_headroom
            ),
            "base_local_replay": base_replay,
        },
        "policy_anchors": {
            "rate_limited": [asdict(anchor) for anchor in rate24_anchors],
            "full_rate": {
                **asdict(full_rate),
                "observed_write_mib_per_s_total": (
                    full_rate.observed_write_mib_per_s_total
                ),
                "observed_read_mib_per_s_total": (
                    full_rate.observed_read_mib_per_s_total
                ),
            },
            "one_kv": {
                **asdict(one_kv),
                "observed_write_mib_per_s_total": (
                    one_kv.observed_write_mib_per_s_total
                ),
                "observed_read_mib_per_s_total": (
                    one_kv.observed_read_mib_per_s_total
                ),
            },
        },
        "policy_surface": policy_surface,
        "backtest": {
            "checks": checks,
            "existing_results_consistent": all(checks.values()),
            "load_scaling_holdout": load_validation,
            "local_capacity_holdout": local_prediction,
            "ssd_write_volume": {
                **write_model,
                "current_fitted_persist_bytes": fitted_current_persist,
                "current_fit_error_percent": current_persist_error_percent,
            },
            "ssd_capacity_observation": {
                "configured_capacity_never_bound": True,
                "current_actual_used_bytes_total": sum(
                    current_anchor.used_bytes_by_node.values()
                ),
                "current_actual_persist_bytes": current_anchor.persist_bytes,
                "one_round_raw_rate_bound_bytes_total": (
                    2 * one_round_capacity["raw_bytes_each"]
                ),
            },
            "ssd_knee_shift": {
                "r90_ssd_on_bracket_gib_each": local_bracket,
                "r90_ssd_off_bracket_gib_each": control_local_bracket,
                "r90_local_payload_shift_gib_each": r90_ssd_knee_shift,
                "r95_remote_shift_status": r95_ssd_status,
                "model_credit_gib": 0.0,
            },
        },
        "validation_plan": [
            {
                "step": 1,
                "remote_active_gib": 248.0,
                "ssd_capacity_gib_each": one_round_capacity[
                    "rounded_candidate_gib_each"
                ],
                "purpose": "no-eviction SSD capacity anchor",
                "expected": "same behavior as current 1.5 TiB within run noise",
            },
            {
                "step": 2,
                "remote_active_gib": 248.0,
                "ssd_capacity_gib_each": p99_capacity[
                    "rounded_candidate_gib_each"
                ],
                "purpose": "p99 rolling-retention validation",
                "expected": "QPS >= 10 and bounded SSD eviction/load-miss",
            },
            {
                "step": 3,
                "remote_active_gib": (
                    round(
                        float(base_joint_row["predicted_remote_active_gib"])
                        / 4.0
                    )
                    * 4.0
                ),
                "ssd_capacity_gib_each": p99_capacity[
                    "rounded_candidate_gib_each"
                ],
                "purpose": "joint remote/SSD point after SSD axis passes",
                "expected": "requires two complete repeats; not yet authorized",
            },
        ],
        "limits": [
            "HBM KV capacity is fixed in all anchors and is not identified",
            "SSD persisted-key identity is absent from the lineage trace",
            "p99 SSD capacity is a candidate derived from all local-miss reuse intervals",
            "local-fit does not remove durability or failure-recovery floors",
            "dynamic rate above 24 MiB/s/owner has no passing performance anchor",
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
                "existing_results_consistent": result["backtest"][
                    "existing_results_consistent"
                ],
                "checks": checks,
                "current_base_sizing": result["current_base_sizing"],
                "validation_plan": result["validation_plan"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
