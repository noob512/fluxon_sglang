#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import io
import logging
import time
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def emit(
    cache: Any,
    req: str,
    raw_keys: list[str],
    sources: str,
    materialization: str,
) -> None:
    if len(raw_keys) != len(sources):
        raise AssertionError("smoke key/source shape mismatch")
    key_ids = tuple(cache._fluxon_kv_lineage_key_id(key) for key in raw_keys)
    cache._observe_fluxon_hostless_request(
        req,
        anchor_node_id=7,
        requested_pages=len(raw_keys),
        final_transferable_pages=len(raw_keys),
        gpu_direct_selected=int(materialization == "gdr_h2d"),
        lineage_plan_unix_ns=time.time_ns(),
        lineage_plan_handle=101,
        lineage_start_depth_pages=64,
        lineage_cpu_plan_pages=len(raw_keys),
        lineage_gpu_plan_pages=len(raw_keys),
        lineage_materialization=materialization,
        lineage_key_ids=key_ids,
        lineage_sources=sources,
    )
    cache._finish_fluxon_hostless_request_observation(
        req,
        "load_back_consumed",
        consumed_pages=len(raw_keys),
        consumed_tokens=len(raw_keys) * 64,
    )


def verify_tp_execute_commit(runtime: Any) -> None:
    cache = object.__new__(runtime.UnifiedRadixCache)
    cache.tp_world_size = 2
    cache.tp_group = object()
    original_all_reduce = runtime.torch.distributed.all_reduce

    def run_case(
        *,
        local_succeeded: bool,
        local_gpu_direct: bool,
        peer_succeeded: bool,
        peer_gpu_direct: bool,
    ) -> tuple[bool, int, int]:
        def fake_all_reduce(tensor: Any, *, op: Any, group: Any) -> None:
            if op != runtime.torch.distributed.ReduceOp.SUM:
                raise AssertionError(f"unexpected execute commit reduction: {op}")
            if group is not cache.tp_group:
                raise AssertionError("execute commit used the wrong TP group")
            tensor[0] += int(peer_succeeded)
            tensor[1] += int(peer_succeeded and peer_gpu_direct)

        runtime.torch.distributed.all_reduce = fake_all_reduce
        return cache._fluxon_hostless_tp_plan_execute_commit(
            local_succeeded=local_succeeded,
            gpu_direct=local_gpu_direct,
        )

    try:
        cases = (
            (
                dict(
                    local_succeeded=True,
                    local_gpu_direct=False,
                    peer_succeeded=True,
                    peer_gpu_direct=False,
                ),
                (True, 2, 0),
            ),
            (
                dict(
                    local_succeeded=True,
                    local_gpu_direct=True,
                    peer_succeeded=True,
                    peer_gpu_direct=True,
                ),
                (True, 2, 2),
            ),
            (
                dict(
                    local_succeeded=False,
                    local_gpu_direct=True,
                    peer_succeeded=True,
                    peer_gpu_direct=True,
                ),
                (False, 1, 1),
            ),
            (
                dict(
                    local_succeeded=True,
                    local_gpu_direct=True,
                    peer_succeeded=True,
                    peer_gpu_direct=False,
                ),
                (False, 2, 1),
            ),
            (
                dict(
                    local_succeeded=True,
                    local_gpu_direct=False,
                    peer_succeeded=False,
                    peer_gpu_direct=False,
                ),
                (False, 1, 0),
            ),
        )
        for inputs, expected in cases:
            actual = run_case(**inputs)
            if actual != expected:
                raise AssertionError(
                    f"execute commit case mismatch: inputs={inputs} "
                    f"expected={expected} actual={actual}"
                )
    finally:
        runtime.torch.distributed.all_reduce = original_all_reduce


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("runtime", type=Path)
    parser.add_argument("analyzer", type=Path)
    args = parser.parse_args()

    runtime = load_module("e44_r61_runtime_smoke", args.runtime)
    analyzer = load_module("e44_r61_analyzer_smoke", args.analyzer)
    verify_tp_execute_commit(runtime)
    cache = object.__new__(runtime.UnifiedRadixCache)
    cache.cache_controller = SimpleNamespace(tp_rank=0)
    cache._fluxon_hostless_request_observations = {}
    cache._fluxon_hostless_observation_counters = defaultdict(int)

    capture = io.StringIO()
    handler = logging.StreamHandler(capture)
    old_level = runtime.logger.level
    runtime.logger.setLevel(logging.INFO)
    runtime.logger.addHandler(handler)
    raw_a = "raw-storage-key-a-must-not-appear"
    raw_b = "raw-storage-key-b-must-not-appear"
    try:
        emit(cache, "cpu-materialize", [raw_a, raw_b], "RR", "cpu_h2d")
        emit(cache, "local-reuse", [raw_a], "L", "cpu_h2d")
        emit(cache, "gdr-after-loss", [raw_a], "R", "gdr_h2d")
    finally:
        runtime.logger.removeHandler(handler)
        runtime.logger.setLevel(old_level)

    log_text = capture.getvalue()
    if raw_a in log_text or raw_b in log_text:
        raise AssertionError("lineage log leaked a full raw storage key")
    events = []
    for line_number, line in enumerate(log_text.splitlines(), 1):
        event = analyzer.parse_line(
            line,
            "dynamic-smoke",
            Path("dynamic-smoke.log"),
            line_number,
        )
        if event is not None:
            events.append(event)
    if len(events) != 3:
        raise AssertionError(f"expected three lineage events, got {len(events)}")
    result = analyzer.analyze(events)
    counters = result["counters"]
    expected = {
        "remote_cpu_materializations": 2,
        "remote_cpu_generations_reused": 1,
        "remote_cpu_lost_after_reuse": 1,
        "remote_cpu_unresolved_without_reuse_at_end": 1,
        "gdr_remote_terminal_pages": 1,
    }
    for key, value in expected.items():
        if counters.get(key) != value:
            raise AssertionError(
                f"dynamic smoke {key}: expected={value} got={counters.get(key)}"
            )
    if cache._fluxon_hostless_request_observations:
        raise AssertionError("terminal observation did not clear live request state")
    print(
        "e44 r61 TP execute commit and lineage smoke: passed "
        f"commit_cases=5 events={len(events)} "
        f"generations={len(result['remote_cpu_generations'])}"
    )


if __name__ == "__main__":
    main()
