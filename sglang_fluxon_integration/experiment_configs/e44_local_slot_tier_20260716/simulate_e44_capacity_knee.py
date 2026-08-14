#!/usr/bin/env python3
"""Fit a trace-calibrated Fluxon CPU-remote capacity knee model.

The simulator intentionally stays aggregate and identifiable.  SGLang uses
continuous batching, so seven completed capacity runs are not enough to
reconstruct a faithful request-level queue.  Instead this tool combines:

* measured QPS and cache hit rate;
* actual SGLang prefill-compute counters and queue histograms;
* Fluxon CPU-source Get bytes, capacity reclaim and owner-local evictions;
* a piecewise throughput breakpoint and a calibrated wall-time response.

It reports fit/leave-one-out error and never treats correlated remote bytes
and local evictions as independently identified causal coefficients.
"""

from __future__ import annotations

import argparse
import ast
import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np


ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
PROM_RE = re.compile(r"^(\S+?)(?:\{(.*)\})?\s+([+\-0-9.eE]+)$")
PROM_LABEL_RE = re.compile(r'(\w+)="([^"]*)"')


@dataclass(frozen=True)
class Run:
    capacity_gib: float
    artifact: str
    qps: float
    wall_s: float
    prompt_tokens_m: float
    total_hit_rate: float
    miss_tokens_m: float
    cpu_effective_gb: float
    cpu_weighted_gb: float
    cpu_occupancy: float
    reclaim_completed: int
    remote_source_tb: float
    local_size_evictions_m: float
    hca_tx_tb: float
    queue_mean_s: float
    prefill_forward_mean_s: float
    prefill_compute_mtokens: float
    prefill_cache_mtokens: float
    timeline_gpu_selected: int
    timeline_terminal_to_consume_ms: float


def parse_run_arg(raw: str) -> tuple[float, Path]:
    capacity, separator, artifact = raw.partition("=")
    if not separator or not capacity or not artifact:
        raise argparse.ArgumentTypeError("run must be CAPACITY_GIB=ARTIFACT_DIR")
    try:
        parsed_capacity = float(capacity)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid capacity: {capacity}") from exc
    return parsed_capacity, Path(artifact)


def clean_lines(path: Path) -> list[str]:
    return [
        ANSI_RE.sub("", line)
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
    ]


def parse_prometheus(path: Path) -> dict[tuple[str, tuple[tuple[str, str], ...]], float]:
    result: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line or line.startswith("#"):
            continue
        match = PROM_RE.match(line)
        if match is None:
            continue
        metric, raw_labels, raw_value = match.groups()
        labels = tuple(sorted(PROM_LABEL_RE.findall(raw_labels or "")))
        result[(metric, labels)] = float(raw_value)
    return result


def metric_delta(
    before: dict[tuple[str, tuple[tuple[str, str], ...]], float],
    after: dict[tuple[str, tuple[tuple[str, str], ...]], float],
    metric: str,
    required_labels: dict[str, str | int],
) -> float:
    matches: list[float] = []
    expected = {key: str(value) for key, value in required_labels.items()}
    for identity, after_value in after.items():
        name, labels_tuple = identity
        if name != metric:
            continue
        labels = dict(labels_tuple)
        if all(labels.get(key) == value for key, value in expected.items()):
            matches.append(after_value - before.get(identity, 0.0))
    if len(matches) != 1:
        raise ValueError(
            f"expected one metric match: metric={metric} labels={expected} got={len(matches)}"
        )
    return matches[0]


def load_prometheus_features(artifact: Path) -> dict[str, float]:
    metrics_dir = artifact / "workload_result" / "metrics"
    queue_sum = 0.0
    queue_count = 0.0
    forward_sum = 0.0
    forward_count = 0.0
    compute_tokens = 0.0
    cache_tokens = 0.0
    for node in ("node0", "node1"):
        before = parse_prometheus(metrics_dir / f"router_agent.before.{node}.sglang.prom")
        after = parse_prometheus(metrics_dir / f"router_agent.after.{node}.sglang.prom")
        rank0 = {"tp_rank": 0}
        queue_sum += metric_delta(
            before, after, "sglang:queue_time_seconds_sum", rank0
        )
        queue_count += metric_delta(
            before, after, "sglang:queue_time_seconds_count", rank0
        )
        forward_labels = {"tp_rank": 0, "stage": "prefill_forward"}
        forward_sum += metric_delta(
            before,
            after,
            "sglang:per_stage_req_latency_seconds_sum",
            forward_labels,
        )
        forward_count += metric_delta(
            before,
            after,
            "sglang:per_stage_req_latency_seconds_count",
            forward_labels,
        )
        compute_tokens += metric_delta(
            before,
            after,
            "sglang:realtime_tokens_total",
            {"tp_rank": 0, "mode": "prefill_compute"},
        )
        cache_tokens += metric_delta(
            before,
            after,
            "sglang:realtime_tokens_total",
            {"tp_rank": 0, "mode": "prefill_cache"},
        )
    return {
        "queue_mean_s": queue_sum / queue_count,
        "prefill_forward_mean_s": forward_sum / forward_count,
        "prefill_compute_mtokens": compute_tokens / 1e6,
        "prefill_cache_mtokens": cache_tokens / 1e6,
    }


def load_run(capacity_gib: float, artifact: Path) -> Run:
    summary_path = artifact / "workload_result" / "summary.json"
    phase = json.loads(summary_path.read_text(encoding="utf-8"))["router_agent"]
    request = phase["request_summary"]
    cache = phase["cache_summary"]

    master_paths = sorted((artifact / "node0").glob("master_*.log"))
    if len(master_paths) != 1:
        raise ValueError(f"expected one master log in {artifact}, got {master_paths}")
    master_lines = clean_lines(master_paths[0])
    runtime = [
        line
        for line in master_lines
        if "replica cache runtime: owner=sglang_l13_owner_remote_cache_cpu0" in line
    ][-1]
    runtime_match = re.search(
        r"owner=sglang_l13_owner_remote_cache_cpu0 entries=(\d+) "
        r"weighted_bytes=(\d+) effective_capacity_bytes=(\d+).*? "
        r"reclaim_completed=(\d+)",
        runtime,
    )
    if runtime_match is None:
        raise ValueError(f"cannot parse CPU runtime snapshot: {master_paths[0]}")
    _entries, weighted_bytes, effective_bytes, reclaim = map(
        int, runtime_match.groups()
    )
    placement = [
        line for line in master_lines if "placement historical distribution" in line
    ][-1]
    raw_source_bytes = placement.split("get_requester_source_bytes=", 1)[1].split(
        " | get_allocation_mode_counts=", 1
    )[0]
    source_bytes = sum(value for _identity, value in ast.literal_eval(raw_source_bytes))

    size_evictions = 0
    for node in ("node0", "node1"):
        snapshots = [
            line
            for line in clean_lines(artifact / node / "owner.log")
            if "owner hot source-eviction policy snapshot" in line
        ]
        match = re.search(r"size_evictions=(\d+)", snapshots[-1])
        if match is None:
            raise ValueError(f"cannot parse owner size evictions: {artifact / node}")
        size_evictions += int(match.group(1))

    hca_path = artifact / "hca_summary_formal.json"
    if not hca_path.exists():
        hca_path = artifact / "hca_cpu_formal.json"
    hca = json.loads(hca_path.read_text(encoding="utf-8"))
    cpu_hca = next(node for node in hca["nodes"] if node["node"] == "cpu")
    hca_tx_bytes = sum(item["tx_bytes"] for item in cpu_hca["per_hca"].values())

    prom = load_prometheus_features(artifact)
    timeline_path = artifact / "prefetch_timeline_summary.json"
    timeline: dict[str, Any] = {}
    if timeline_path.exists():
        timeline = json.loads(timeline_path.read_text(encoding="utf-8"))["summary"]
    timeline_distributions = timeline.get("distributions", {})

    prompt_tokens = float(cache["prompt_tokens_total"])
    hit_rate = float(cache["overall_hit_rate"])
    return Run(
        capacity_gib=capacity_gib,
        artifact=str(artifact),
        qps=float(request["request_qps"]),
        wall_s=float(request["wall_duration_s"]),
        prompt_tokens_m=prompt_tokens / 1e6,
        total_hit_rate=hit_rate,
        miss_tokens_m=prompt_tokens * (1.0 - hit_rate) / 1e6,
        cpu_effective_gb=effective_bytes / 1e9,
        cpu_weighted_gb=weighted_bytes / 1e9,
        cpu_occupancy=weighted_bytes / effective_bytes,
        reclaim_completed=int(reclaim),
        remote_source_tb=source_bytes / 1e12,
        local_size_evictions_m=size_evictions / 1e6,
        hca_tx_tb=hca_tx_bytes / 1e12,
        queue_mean_s=prom["queue_mean_s"],
        prefill_forward_mean_s=prom["prefill_forward_mean_s"],
        prefill_compute_mtokens=prom["prefill_compute_mtokens"],
        prefill_cache_mtokens=prom["prefill_cache_mtokens"],
        timeline_gpu_selected=int(timeline.get("gpu_selected", 0)),
        timeline_terminal_to_consume_ms=float(
            timeline_distributions.get("terminal_to_consume_ms", {}).get("mean", 0.0)
        ),
    )


def ols_with_validation(features: np.ndarray, target: np.ndarray) -> dict[str, Any]:
    design = np.column_stack([np.ones(len(target)), features])
    coefficients = np.linalg.lstsq(design, target, rcond=None)[0]
    predicted = design @ coefficients
    residuals = target - predicted
    total_variance = np.sum((target - target.mean()) ** 2)
    leave_one_out: list[float] = []
    for index in range(len(target)):
        keep = np.arange(len(target)) != index
        held_coefficients = np.linalg.lstsq(
            design[keep], target[keep], rcond=None
        )[0]
        leave_one_out.append(float(design[index] @ held_coefficients))
    return {
        "coefficients": coefficients.tolist(),
        "predicted": predicted.tolist(),
        "residuals": residuals.tolist(),
        "rmse": float(np.sqrt(np.mean(residuals**2))),
        "r2": float(1.0 - np.sum(residuals**2) / total_variance),
        "leave_one_out_rmse": float(
            np.sqrt(np.mean((np.asarray(leave_one_out) - target) ** 2))
        ),
    }


def fit_piecewise_qps(capacity: np.ndarray, qps: np.ndarray) -> dict[str, Any]:
    lower = max(200.0, float(capacity.min()))
    upper = min(330.0, float(capacity.max()) - 1.0)
    best: tuple[float, float, np.ndarray, np.ndarray] | None = None
    for breakpoint in np.linspace(lower, upper, int((upper - lower) * 10) + 1):
        design = np.column_stack(
            [np.ones(len(capacity)), capacity, np.maximum(0.0, capacity - breakpoint)]
        )
        coefficients = np.linalg.lstsq(design, qps, rcond=None)[0]
        predicted = design @ coefficients
        sse = float(np.sum((predicted - qps) ** 2))
        candidate = (sse, float(breakpoint), coefficients, predicted)
        if best is None or candidate[0] < best[0]:
            best = candidate
    assert best is not None
    sse, breakpoint, coefficients, predicted = best

    held_breakpoints: list[float] = []
    anchored_breakpoints: list[float] = []
    for index in range(len(qps)):
        keep = np.arange(len(qps)) != index
        held = fit_piecewise_qps_no_validation(capacity[keep], qps[keep])
        held_breakpoint = float(held["breakpoint_gib"])
        held_breakpoints.append(held_breakpoint)
        # Dropping either of the only two plateau anchors (300/350 GiB) makes
        # the post-break slope structurally weak.  Report that full LOO range,
        # but also expose the conditional range that retains both anchors.
        if capacity[index] < 300.0:
            anchored_breakpoints.append(held_breakpoint)
    return {
        "breakpoint_gib": breakpoint,
        "pre_break_slope_qps_per_gib": float(coefficients[1]),
        "post_break_slope_qps_per_gib": float(coefficients[1] + coefficients[2]),
        "coefficients": coefficients.tolist(),
        "predicted": predicted.tolist(),
        "rmse_qps": float(math.sqrt(sse / len(qps))),
        "leave_one_out_breakpoint_min_gib": min(held_breakpoints),
        "leave_one_out_breakpoint_max_gib": max(held_breakpoints),
        "plateau_anchored_leave_one_out_breakpoint_min_gib": min(
            anchored_breakpoints
        ),
        "plateau_anchored_leave_one_out_breakpoint_max_gib": max(
            anchored_breakpoints
        ),
    }


def fit_piecewise_qps_no_validation(
    capacity: np.ndarray, qps: np.ndarray
) -> dict[str, Any]:
    lower = max(200.0, float(capacity.min()))
    upper = min(330.0, float(capacity.max()) - 1.0)
    best: tuple[float, float, np.ndarray] | None = None
    for breakpoint in np.linspace(lower, upper, int((upper - lower) * 10) + 1):
        design = np.column_stack(
            [np.ones(len(capacity)), capacity, np.maximum(0.0, capacity - breakpoint)]
        )
        coefficients = np.linalg.lstsq(design, qps, rcond=None)[0]
        sse = float(np.sum((design @ coefficients - qps) ** 2))
        candidate = (sse, float(breakpoint), coefficients)
        if best is None or candidate[0] < best[0]:
            best = candidate
    assert best is not None
    return {"breakpoint_gib": best[1], "coefficients": best[2].tolist()}


def piecewise_predict(model: dict[str, Any], capacity: float) -> float:
    intercept, pre_slope, slope_change = model["coefficients"]
    breakpoint = float(model["breakpoint_gib"])
    return float(
        intercept
        + pre_slope * capacity
        + slope_change * max(0.0, capacity - breakpoint)
    )


def fit_reclaim_threshold(runs: list[Run]) -> dict[str, Any]:
    positive = [run for run in runs if run.reclaim_completed > 0]
    zeros = [run for run in runs if run.reclaim_completed == 0]
    capacity = np.asarray([run.capacity_gib for run in positive], dtype=float)
    reclaim = np.asarray([run.reclaim_completed for run in positive], dtype=float)
    upper = min(run.capacity_gib for run in zeros)

    def fit_subset(c_values: np.ndarray, r_values: np.ndarray) -> tuple[float, np.ndarray, float]:
        best: tuple[float, float, np.ndarray] | None = None
        start = float(c_values.max()) + 0.1
        for threshold in np.linspace(start, upper, max(2, int((upper - start) * 10) + 1)):
            design = np.column_stack(
                [np.ones(len(c_values)), np.log(threshold - c_values)]
            )
            coefficients = np.linalg.lstsq(design, np.log(r_values), rcond=None)[0]
            error = design @ coefficients - np.log(r_values)
            rmse = float(np.sqrt(np.mean(error**2)))
            candidate = (rmse, float(threshold), coefficients)
            if best is None or candidate[0] < best[0]:
                best = candidate
        assert best is not None
        return best[1], best[2], best[0]

    threshold, coefficients, log_rmse = fit_subset(capacity, reclaim)
    held_thresholds: list[float] = []
    for index in range(len(capacity)):
        keep = np.arange(len(capacity)) != index
        held_thresholds.append(fit_subset(capacity[keep], reclaim[keep])[0])
    return {
        "threshold_gib": threshold,
        "scale": float(math.exp(coefficients[0])),
        "power": float(coefficients[1]),
        "log_rmse": log_rmse,
        "leave_one_out_threshold_min_gib": min(held_thresholds),
        "leave_one_out_threshold_max_gib": max(held_thresholds),
    }


def reclaim_predict(model: dict[str, Any], capacity: float) -> float:
    distance = max(0.0, float(model["threshold_gib"]) - capacity)
    return float(model["scale"] * distance ** float(model["power"])) if distance else 0.0


def interpolate(runs: list[Run], field: str, capacity: float) -> float:
    x = np.asarray([run.capacity_gib for run in runs], dtype=float)
    y = np.asarray([float(getattr(run, field)) for run in runs], dtype=float)
    if capacity < x.min() or capacity > x.max():
        raise ValueError(f"candidate {capacity} is outside measured range")
    return float(np.interp(capacity, x, y))


def render_markdown(result: dict[str, Any]) -> str:
    pipeline = result["models"]["pipeline_wall"]
    queue = result["models"]["queue_from_compute"]
    breakpoint = result["models"]["piecewise_qps"]
    reclaim = result["models"]["reclaim_threshold"]
    lines = [
        "# Fluxon CPU Remote 容量拐点机制与 Trace 校准仿真",
        "",
        f"生成时间：{result['generated_at']}",
        "",
        "## 结论先行",
        "",
        f"- QPS分段模型的最优拐点为`{breakpoint['breakpoint_gib']:.1f} GiB`；保留300/350两个平台锚点的"
        f"留一范围为`{breakpoint['plateau_anchored_leave_one_out_breakpoint_min_gib']:.1f}–"
        f"{breakpoint['plateau_anchored_leave_one_out_breakpoint_max_gib']:.1f} GiB`。若删掉任一平台锚点，"
        f"完整留一范围扩大到`{breakpoint['leave_one_out_breakpoint_min_gib']:.1f}–"
        f"{breakpoint['leave_one_out_breakpoint_max_gib']:.1f} GiB`；",
        f"- queue与实际prefill compute tokens近似线性，`R²={queue['r2']:.4f}`。300/350 GiB的"
        "prefill compute和queue几乎相同，所以吞吐平台首先是“可节省计算已耗尽”，不是350 GiB网络打满；",
        f"- wall模型为`wall_s = {pipeline['coefficients'][0]:.3f} + "
        f"{pipeline['coefficients'][1]:.3f}×prefill_compute_M + "
        f"{pipeline['coefficients'][2]:.3f}×remote_source_TB`，"
        f"`R²={pipeline['r2']:.4f}`、LOO RMSE=`{pipeline['leave_one_out_rmse']:.3f}s`；",
        "- remote bytes与local eviction的相关系数接近1，现有7轮不能把二者的成本独立识别；"
        "remote系数只能解释为传输、restore和local churn的联合代理。",
        "",
        "## 实测输入",
        "",
        "| CPU GiB | QPS | prefill compute(M) | queue mean(s) | remote(TB) | local eviction(M) | reclaim |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for run in result["runs"]:
        lines.append(
            f"| {run['capacity_gib']:g} | {run['qps']:.6f} | "
            f"{run['prefill_compute_mtokens']:.3f} | {run['queue_mean_s']:.3f} | "
            f"{run['remote_source_tb']:.3f} | {run['local_size_evictions_m']:.3f} | "
            f"{run['reclaim_completed']} |"
        )
    lines.extend(
        [
            "",
            "## 300 → 350 GiB 分解",
            "",
            f"- 实际wall变化：`{result['plateau_decomposition']['actual_wall_delta_s']:+.3f}s`；",
            f"- 模型中的计算量变化贡献：`{result['plateau_decomposition']['compute_component_delta_s']:+.3f}s`；",
            f"- remote/restore/churn联合代理贡献：`{result['plateau_decomposition']['remote_component_delta_s']:+.3f}s`；",
            "- 两轮实测差小于模型单轮误差，因此只能裁决为同一平台，不能把0.06% QPS差解释成真实性能反转。",
            "",
            "## 候选容量仿真",
            "",
            "候选点的compute、remote和hit在相邻实测点之间做线性插值；wall不确定性由7轮拟合残差重采样。",
            "",
            "| CPU GiB | pipeline QPS p10/p50/p90 | 分段QPS | 插值命中 | reclaim点预测 |",
            "|---:|---:|---:|---:|---:|",
        ]
    )
    for candidate in result["candidates"]:
        lines.append(
            f"| {candidate['capacity_gib']:g} | "
            f"{candidate['pipeline_qps_p10']:.3f}/{candidate['pipeline_qps_p50']:.3f}/{candidate['pipeline_qps_p90']:.3f} | "
            f"{candidate['piecewise_qps']:.3f} | {candidate['interpolated_hit_rate']*100:.2f}% | "
            f"{candidate['reclaim_point_prediction']:.0f} |"
        )
    lines.extend(
        [
            "",
            "## 模型边界",
            "",
            "- 这是trace校准的聚合响应模型，不是SGLang continuous batching的请求级离散事件复刻；",
            "- 7个容量点足以识别平台和计算量→queue关系，但不足以独立估计RDMA、H2D、local Moka驱逐各自成本；",
            f"- reclaim阈值点估计为`{reclaim['threshold_gib']:.1f} GiB`，但留一范围"
            f"`{reclaim['leave_one_out_threshold_min_gib']:.1f}–{reclaim['leave_one_out_threshold_max_gib']:.1f} GiB`，"
            "说明该阈值不能只靠现有点精确外推；",
            "- 若只跑一个验证点，优先CPU remote=288 GiB：它接近QPS拐点拟合值，且高于reclaim阈值留一上界。"
            "若288与300持平且reclaim=0，再测275 GiB压缩成本区间。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="append", type=parse_run_arg, default=[])
    parser.add_argument("--candidate", type=float, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--generated-at", default="2026-07-24 HKT")
    parser.add_argument("--bootstrap-samples", type=int, default=50000)
    parser.add_argument("--seed", type=int, default=20260724)
    args = parser.parse_args()
    if len(args.run) < 5:
        parser.error("at least five --run CAPACITY=ARTIFACT inputs are required")

    runs = sorted((load_run(capacity, artifact) for capacity, artifact in args.run), key=lambda run: run.capacity_gib)
    capacity = np.asarray([run.capacity_gib for run in runs], dtype=float)
    qps = np.asarray([run.qps for run in runs], dtype=float)
    wall = np.asarray([run.wall_s for run in runs], dtype=float)
    compute = np.asarray([run.prefill_compute_mtokens for run in runs], dtype=float)
    remote = np.asarray([run.remote_source_tb for run in runs], dtype=float)
    evictions = np.asarray([run.local_size_evictions_m for run in runs], dtype=float)
    queue = np.asarray([run.queue_mean_s for run in runs], dtype=float)

    compute_only = ols_with_validation(compute[:, None], wall)
    pipeline = ols_with_validation(np.column_stack([compute, remote]), wall)
    queue_model = ols_with_validation(compute[:, None], queue)
    piecewise = fit_piecewise_qps(capacity, qps)
    reclaim_model = fit_reclaim_threshold(runs)
    correlation = np.corrcoef(np.column_stack([compute, remote, evictions]).T)

    run_by_capacity = {run.capacity_gib: run for run in runs}
    if 300.0 not in run_by_capacity or 350.0 not in run_by_capacity:
        raise ValueError("300 and 350 GiB runs are required for plateau decomposition")
    run300 = run_by_capacity[300.0]
    run350 = run_by_capacity[350.0]
    pipeline_coefficients = pipeline["coefficients"]
    plateau_decomposition = {
        "actual_wall_delta_s": run350.wall_s - run300.wall_s,
        "compute_component_delta_s": pipeline_coefficients[1]
        * (run350.prefill_compute_mtokens - run300.prefill_compute_mtokens),
        "remote_component_delta_s": pipeline_coefficients[2]
        * (run350.remote_source_tb - run300.remote_source_tb),
        "queue_delta_s": run350.queue_mean_s - run300.queue_mean_s,
        "prefill_compute_delta_mtokens": run350.prefill_compute_mtokens
        - run300.prefill_compute_mtokens,
        "remote_source_delta_tb": run350.remote_source_tb - run300.remote_source_tb,
        "local_eviction_delta_m": run350.local_size_evictions_m
        - run300.local_size_evictions_m,
    }

    rng = np.random.default_rng(args.seed)
    residuals = np.asarray(pipeline["residuals"], dtype=float)
    candidates: list[dict[str, Any]] = []
    for candidate_capacity in args.candidate or [275.0, 288.0]:
        candidate_compute = interpolate(runs, "prefill_compute_mtokens", candidate_capacity)
        candidate_remote = interpolate(runs, "remote_source_tb", candidate_capacity)
        candidate_hit = interpolate(runs, "total_hit_rate", candidate_capacity)
        predicted_wall = (
            pipeline_coefficients[0]
            + pipeline_coefficients[1] * candidate_compute
            + pipeline_coefficients[2] * candidate_remote
        )
        simulated_wall = predicted_wall + rng.choice(
            residuals, size=args.bootstrap_samples, replace=True
        )
        simulated_qps = 2304.0 / simulated_wall
        qps_quantiles = np.quantile(simulated_qps, [0.10, 0.50, 0.90])
        candidates.append(
            {
                "capacity_gib": candidate_capacity,
                "interpolated_prefill_compute_mtokens": candidate_compute,
                "interpolated_remote_source_tb": candidate_remote,
                "interpolated_hit_rate": candidate_hit,
                "pipeline_wall_s": predicted_wall,
                "pipeline_qps_p10": float(qps_quantiles[0]),
                "pipeline_qps_p50": float(qps_quantiles[1]),
                "pipeline_qps_p90": float(qps_quantiles[2]),
                "piecewise_qps": piecewise_predict(piecewise, candidate_capacity),
                "reclaim_point_prediction": reclaim_predict(
                    reclaim_model, candidate_capacity
                ),
            }
        )

    result = {
        "schema": "e44_capacity_knee_model_v1",
        "generated_at": args.generated_at,
        "runs": [asdict(run) for run in runs],
        "models": {
            "piecewise_qps": piecewise,
            "compute_only_wall": compute_only,
            "pipeline_wall": pipeline,
            "queue_from_compute": queue_model,
            "reclaim_threshold": reclaim_model,
            "feature_correlation": {
                "labels": [
                    "prefill_compute_mtokens",
                    "remote_source_tb",
                    "local_size_evictions_m",
                ],
                "matrix": correlation.tolist(),
            },
        },
        "plateau_decomposition": plateau_decomposition,
        "candidates": candidates,
        "interpretation": {
            "remote_and_eviction_separately_identifiable": False,
            "reason": "remote bytes and local evictions are nearly collinear across seven runs",
            "simulator_scope": "trace-calibrated aggregate response, not request-level continuous batching",
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.markdown is not None:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(render_markdown(result), encoding="utf-8")
    print(json.dumps({"models": result["models"], "candidates": candidates, "plateau_decomposition": plateau_decomposition}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
