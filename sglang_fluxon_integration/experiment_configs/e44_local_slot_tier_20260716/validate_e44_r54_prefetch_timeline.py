#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
from pathlib import Path


TIMELINE_FIELDS = (
    "scheduler_enqueue_queue_position",
    "scheduler_consume_queue_position",
    "plan_ready_age_ms",
    "gpu_reserve_age_ms",
    "gpu_backend_handle",
    "transfer_consume_start_age_ms",
    "rdma_start_age_ms",
    "rdma_terminal_age_ms",
    "rdma_transfer_wall_ms",
    "rdma_terminal_before_consume",
    "rdma_terminal_to_consume_ms",
    "rdma_finish_wait_ms",
    "load_back_consume_start_age_ms",
    "restore_queued_age_ms",
    "restore_complete_age_ms",
    "staging_release_age_ms",
)


def class_node(tree: ast.Module, name: str) -> ast.ClassDef:
    return next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == name
    )


def method_node(tree: ast.Module, class_name: str, name: str) -> ast.FunctionDef:
    return next(
        node
        for node in class_node(tree, class_name).body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def named_calls(node: ast.AST, name: str) -> list[ast.Call]:
    return [
        child
        for child in ast.walk(node)
        if isinstance(child, ast.Call)
        and isinstance(child.func, ast.Attribute)
        and child.func.attr == name
    ]


def validate_runtime(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    observe = method_node(
        tree, "UnifiedRadixCache", "observe_fluxon_prefetch_scheduler_state"
    )
    prefetch = method_node(tree, "UnifiedRadixCache", "prefetch_from_storage")
    progress = method_node(tree, "UnifiedRadixCache", "check_prefetch_progress")
    load_back = method_node(tree, "UnifiedRadixCache", "load_back")
    loading_check = method_node(tree, "UnifiedRadixCache", "loading_check")
    finish = method_node(
        tree, "UnifiedRadixCache", "_finish_fluxon_hostless_request_observation"
    )

    observe_source = ast.unparse(observe)
    for phase in ("phase == 'enqueue'", "phase != 'consume'"):
        if phase not in observe_source:
            raise AssertionError(f"scheduler observation is missing bounded phase {phase}")
    for field in TIMELINE_FIELDS:
        if field not in source:
            raise AssertionError(f"runtime is missing timeline field {field}")
    if len(named_calls(prefetch, "try_reserve_gpu_direct_staging")) != 1:
        raise AssertionError("observation version must keep one staging reservation")
    if len(named_calls(prefetch, "execute_get_plan_gpu")) != 1:
        raise AssertionError("observation version must keep one GPU plan execution")
    if len(named_calls(progress, "get_transfer_gpu")) != 1:
        raise AssertionError("observation version must keep one GPU terminal consume")
    progress_source = ast.unparse(progress)
    for marker in (
        "gpu_handle.transfer_wall_us",
        "gpu_handle.finish_wait_us",
        "gpu_handle.terminal_before_consume",
        "gpu_handle.terminal_to_consume_us",
    ):
        if marker not in progress_source:
            raise AssertionError(f"progress is missing exact GPU timing {marker}")
    if "load_back_consume_start_age_ms" not in ast.unparse(load_back):
        raise AssertionError("load-back consume start is not observed")
    loading_source = ast.unparse(loading_check)
    if loading_source.index("operation.release_views()") > loading_source.index(
        "staging_release_age_ms"
    ):
        raise AssertionError("staging release must happen before its timestamp is published")
    if "Fluxon prefetch timeline:" not in ast.unparse(finish):
        raise AssertionError("request terminal must emit one joined timeline")
    if "_FLUXON_GPU_DIRECT_STAGING_SLOT_COUNT = 288" not in source:
        raise AssertionError("r54 must keep the 288-slot baseline")


def validate_adapter(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    transfer = method_node(tree, "HiCacheFluxon", "get_transfer_gpu")
    transfer_source = ast.unparse(transfer)
    if len(named_calls(transfer, "get_transfer_gpu")) != 1:
        raise AssertionError("adapter must call the GPU terminal exactly once")
    for marker in (
        "backend_handle",
        "transfer_wall_us",
        "terminal_before_consume",
        "terminal_to_consume_us",
        "finish_wait_us",
    ):
        if marker not in transfer_source:
            raise AssertionError(f"adapter log is missing {marker}")
    if "return int(plan_ptr)" not in transfer_source:
        raise AssertionError("timing observation must not change the adapter return contract")


def validate_scheduler(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    enqueue = method_node(tree, "Scheduler", "_prefetch_kvcache")
    consume = method_node(tree, "Scheduler", "_get_new_batch_prefill_raw")
    enqueue_source = ast.unparse(enqueue)
    consume_source = ast.unparse(consume)
    if enqueue_source.count("observe_fluxon_prefetch_scheduler_state") != 1:
        raise AssertionError("enqueue must publish one scheduler snapshot")
    if enqueue_source.index("phase='enqueue'") > enqueue_source.index(
        "prefetch_from_storage"
    ):
        raise AssertionError("enqueue state must be captured before reserve/execute")
    if consume_source.count("observe_fluxon_prefetch_scheduler_state") != 1:
        raise AssertionError("scheduler scan must publish one consume snapshot")
    if consume_source.index("phase='consume'") > consume_source.index(
        "check_prefetch_progress"
    ):
        raise AssertionError("consume state must be captured before terminal wait")
    if named_calls(enqueue, "get_num_waiting_uncached_tokens") or named_calls(
        consume, "get_num_waiting_uncached_tokens"
    ):
        raise AssertionError(
            "scheduler observation must not call an API absent from the installed load inquirer"
        )
    if source.count(
        "waiting_req.seqlen - len(waiting_req.prefix_indices)"
    ) != 2:
        raise AssertionError(
            "enqueue and consume must derive uncached tokens from the installed request fields"
        )
    if "for queue_position, req in enumerate(self.waiting_queue)" not in source:
        raise AssertionError("scheduler must report the actual post-policy queue position")


def validate_fluxon_sources(root: Path) -> None:
    external = (
        root
        / "fluxon_rs/fluxon_kv/src/external_client_api/mod.rs"
    ).read_text(encoding="utf-8")
    pyo3 = (root / "fluxon_rs/fluxon_pyo3/src/lib.rs").read_text(encoding="utf-8")
    python_api = (root / "fluxon_py/kvclient/fluxon.py").read_text(encoding="utf-8")
    for marker in (
        "struct ExternalGpuGetTerminalEvent",
        "observe_external_gpu_get_consume_timing",
        "transfer_started_at: Instant",
        "external GPU Get consume lifecycle:",
    ):
        if marker not in external:
            raise AssertionError(f"Fluxon GPU terminal source is missing {marker}")
    for marker in (
        '"transfer_wall_us"',
        '"finish_wait_us"',
        '"terminal_before_consume"',
        '"terminal_to_consume_us"',
    ):
        if marker not in pyo3:
            raise AssertionError(f"PyO3 terminal payload is missing {marker}")
    for marker in (
        "transfer_wall_us: Optional[int]",
        "terminal_before_consume: Optional[bool]",
        'payload["terminal_to_consume_us"]',
    ):
        if marker not in python_api:
            raise AssertionError(f"Python GPU handle is missing {marker}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("runtime", type=Path)
    parser.add_argument("adapter", type=Path)
    parser.add_argument("scheduler", type=Path)
    parser.add_argument("fluxon_root", type=Path, nargs="?")
    args = parser.parse_args()
    validate_runtime(args.runtime)
    validate_adapter(args.adapter)
    validate_scheduler(args.scheduler)
    if args.fluxon_root is not None:
        validate_fluxon_sources(args.fluxon_root)
    print("e44 r54 prefetch timeline observation validation: passed")


if __name__ == "__main__":
    main()
