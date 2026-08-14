#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
from pathlib import Path


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


def rendered_method(tree: ast.Module, class_name: str, name: str) -> str:
    return ast.unparse(method_node(tree, class_name, name))


def validate_runtime(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    prefetch = rendered_method(tree, "UnifiedRadixCache", "prefetch_from_storage")
    start_host = rendered_method(
        tree,
        "UnifiedRadixCache",
        "_start_fluxon_host_prefetch",
    )
    materialize = rendered_method(
        tree,
        "UnifiedRadixCache",
        "_materialize_fluxon_hostless_prefetch",
    )
    progress = rendered_method(
        tree,
        "UnifiedRadixCache",
        "check_prefetch_progress",
    )

    for marker in (
        "host_prefetch_queue_head_k",
        "host_prefetch_budget_pages",
        "host_correction_enabled",
        "materialize_queue_head_k",
        "materialize_gdr_budget_pages",
        "host_prefetch_terminal_drained_pages",
    ):
        if marker not in source:
            raise AssertionError(f"runtime is missing {marker}")

    if "backend.prefetch_to_host" in prefetch:
        raise AssertionError("host warm must not start for every enqueued request")
    for marker in (
        "host_prefetch_target_pages=host_prefetch_target",
        "deferred_materialization=True",
        "host_prefetch_deferred",
    ):
        if marker not in prefetch:
            raise AssertionError(f"deferred host stage is missing {marker}")

    for marker in (
        "operation.backend.prefetch_to_host",
        "max_keys=operation.host_prefetch_target_pages",
        "release_on_complete=True",
        "operation.host_prefetch_started = True",
    ):
        if marker not in start_host:
            raise AssertionError(f"bounded host starter is missing {marker}")

    host_gate = "position < self._fluxon_host_prefetch_queue_head_k"
    materialize_gate = "position >= self._fluxon_materialize_queue_head_k"
    if host_gate not in progress or materialize_gate not in progress:
        raise AssertionError("the two queue-head gates are incomplete")
    if progress.index(host_gate) > progress.index(materialize_gate):
        raise AssertionError("host warm gate must run before materialize gate")
    if "self._start_fluxon_host_prefetch" not in progress:
        raise AssertionError("scheduler progress never starts the host stage")

    for marker in (
        "backend.finish_prefetch_to_host",
        "backend.get_plan",
        "backend.try_reserve_gpu_direct_staging",
        "backend.execute_get_plan_gpu",
        "backend.execute_get_plan_cpu",
        "materialize_h2d_source_pages",
        "materialize_gdr_source_pages",
    ):
        if marker not in materialize:
            raise AssertionError(f"late materializer is missing {marker}")
    if materialize.index("backend.finish_prefetch_to_host") > materialize.index(
        "backend.get_plan"
    ):
        raise AssertionError("host lane must be terminal before late route planning")
    correction = materialize.index("correction_keys:")
    if "self._fluxon_host_correction_enabled" not in materialize[correction:]:
        raise AssertionError("late correction is not guarded by explicit admission")
    cancel = materialize.index("backend.cancel_get_plan", correction)
    warm = materialize.index("backend.prefetch_to_host", correction)
    retain = materialize.index("release_on_complete=False", correction)
    if not cancel < warm < retain:
        raise AssertionError(
            "correction must revoke Plan before a retained host transfer"
        )


def validate_adapter(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    submit_batch = rendered_method(
        tree,
        "HiCacheFluxon",
        "_submit_warm_get_batch",
    )
    drain = rendered_method(
        tree,
        "HiCacheFluxon",
        "_drain_completed_warm_entries",
    )
    prefetch = rendered_method(tree, "HiCacheFluxon", "prefetch_to_host")
    finish = rendered_method(tree, "HiCacheFluxon", "finish_prefetch_to_host")

    for marker in (
        "len(self._warm_futures) + len(self._warm_inflight)",
        "release_on_complete",
        "batch_future.add_done_callback",
        "tracked_entries",
    ):
        if marker not in submit_batch:
            raise AssertionError(f"bounded batch submit is missing {marker}")
    for marker in (
        "current_future is not expected_future",
        "self._warm_futures.pop(storage_key, None)",
        "wait_result = future.wait()",
        "holder = wait_result.unwrap()",
        "del holder",
        "error = wait_result.unwrap_error()",
        "self._warm_auto_drained += drained",
    ):
        if marker not in drain:
            raise AssertionError(f"terminal holder drain is missing {marker}")
    if drain.index("self._warm_futures.pop") > drain.index(
        "wait_result = future.wait()"
    ):
        raise AssertionError("terminal drain must claim each future before consuming it")

    for marker in (
        "release_on_complete=release_on_complete",
        "tracked_storage_keys.update(submitted_storage_keys)",
        "pending_limit=%d",
    ):
        if marker not in prefetch:
            raise AssertionError(f"host submit API is missing {marker}")
    for marker in (
        "future = self._take_warm_future(storage_key)",
        "result = future.wait()",
        "terminal_drained",
    ):
        if marker not in finish:
            raise AssertionError(f"host finish API is missing {marker}")


def validate_scheduler(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    schedule = rendered_method(tree, "Scheduler", "_get_new_batch_prefill_raw")
    call = "self.tree_cache.check_prefetch_progress(req.rid, queue_position=queue_position)"
    if call not in schedule:
        raise AssertionError("scheduler must pass the post-policy queue position")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("runtime", type=Path)
    parser.add_argument("adapter", type=Path)
    parser.add_argument("scheduler", type=Path)
    args = parser.parse_args()
    validate_runtime(args.runtime)
    validate_adapter(args.adapter)
    validate_scheduler(args.scheduler)
    print("e44 r57 bounded two-stage materialization validation: passed")


if __name__ == "__main__":
    main()
