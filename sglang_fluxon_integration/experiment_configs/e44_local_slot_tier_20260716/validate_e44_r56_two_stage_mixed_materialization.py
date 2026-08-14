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


def validate_runtime(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    prefetch = ast.unparse(
        method_node(tree, "UnifiedRadixCache", "prefetch_from_storage")
    )
    materialize = ast.unparse(
        method_node(
            tree,
            "UnifiedRadixCache",
            "_materialize_fluxon_hostless_prefetch",
        )
    )
    progress = ast.unparse(
        method_node(tree, "UnifiedRadixCache", "check_prefetch_progress")
    )

    for marker in (
        "two_stage_mixed_materialization",
        "materialize_queue_head_k",
        "materialize_gdr_budget_pages",
        "Fluxon mixed materialization lifecycle:",
    ):
        if marker not in source:
            raise AssertionError(f"runtime is missing {marker}")
    for marker in (
        "backend.prefetch_to_host",
        "deferred_materialization=True",
        "gdr_budget_pages=self._fluxon_materialize_gdr_budget_pages",
    ):
        if marker not in prefetch:
            raise AssertionError(f"early host stage is missing {marker}")
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
    correction = materialize.index("correction_keys =")
    cancel = materialize.index("backend.cancel_get_plan", correction)
    warm = materialize.index("backend.prefetch_to_host", correction)
    if cancel > warm:
        raise AssertionError(
            "metadata plan must be revoked before a correction host transfer starts"
        )
    if "position >= self._fluxon_materialize_queue_head_k" not in progress:
        raise AssertionError("late materialization is not gated by queue-head K")
    if "self._materialize_fluxon_hostless_prefetch(req_id, operation)" not in progress:
        raise AssertionError("scheduler progress does not invoke late materialization")


def validate_adapter(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    submit = ast.unparse(method_node(tree, "HiCacheFluxon", "prefetch_to_host"))
    finish = ast.unparse(
        method_node(tree, "HiCacheFluxon", "finish_prefetch_to_host")
    )
    for marker in (
        "self._submit_warm_get_batch(storage_keys)",
        "tracked_storage_keys",
    ):
        if marker not in submit:
            raise AssertionError(f"host submit API is missing {marker}")
    for marker in (
        "future = self._take_warm_future(storage_key)",
        "result = future.wait()",
        "keepalives.append(result.unwrap())",
    ):
        if marker not in finish:
            raise AssertionError(f"host finish API is missing {marker}")
    if finish.index("result = future.wait()") > finish.index(
        "keepalives.append(result.unwrap())"
    ):
        raise AssertionError("host holders must only be retained after terminal success")


def validate_scheduler(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    schedule = ast.unparse(
        method_node(tree, "Scheduler", "_get_new_batch_prefill_raw")
    )
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
    print("e44 r56 two-stage mixed materialization validation: passed")


if __name__ == "__main__":
    main()
