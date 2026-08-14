#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
from pathlib import Path


R55_ADAPTER_SHA256 = "eb1e0848c2717e7f59e82f9051ba6dbae1c06793694dd11aaa3d6e93c6c98ccd"
R55_SCHEDULER_SHA256 = "5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef"


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def class_method(tree: ast.Module, class_name: str, method_name: str) -> ast.FunctionDef:
    klass = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    return next(
        node
        for node in klass.body
        if isinstance(node, ast.FunctionDef) and node.name == method_name
    )


def attribute_call_count(node: ast.AST, name: str) -> int:
    return sum(
        isinstance(child, ast.Call)
        and isinstance(child.func, ast.Attribute)
        and child.func.attr == name
        for child in ast.walk(node)
    )


def validate_runtime(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    prefetch = class_method(tree, "UnifiedRadixCache", "prefetch_from_storage")
    execute_commit = class_method(
        tree,
        "UnifiedRadixCache",
        "_fluxon_hostless_tp_plan_execute_commit",
    )
    finish = class_method(
        tree, "UnifiedRadixCache", "_finish_fluxon_hostless_request_observation"
    )
    emitter = class_method(tree, "UnifiedRadixCache", "_emit_fluxon_kv_lineage")
    key_id = class_method(tree, "UnifiedRadixCache", "_fluxon_kv_lineage_key_id")

    if "import json" not in source:
        raise AssertionError("r61 runtime must retain machine-readable lineage JSON")
    for marker in (
        '"schema": "e44_r60_kv_lineage_v1"',
        '"materialization": str(',
        '"key_ids": key_ids',
        '"sources": sources',
        '"start_depth_pages": int(',
        '"plan_unix_ns": int(',
        '"terminal_unix_ns": time.time_ns()',
        'lineage_keys = hash_values[:transferable_pages]',
        '"R"',
        '"L"',
        '"U"',
        '"gdr_h2d" if kv_handle_mode == "gpu" else "cpu_h2d"',
    ):
        if marker not in source:
            raise AssertionError(f"r61 runtime is missing lineage marker {marker}")
    if "two_stage_mixed_materialization" in source or "prefetch_to_host" in source:
        raise AssertionError("r61 must derive from r60/r55 and not contain r56-r59 early warm")
    if "fluxon-r60" not in ast.unparse(key_id):
        raise AssertionError("lineage key IDs must use the stable r60 BLAKE2 namespace")
    if "json.dumps" not in ast.unparse(emitter):
        raise AssertionError("lineage emitter must serialize one compact JSON payload")
    if ast.unparse(finish).count("self._emit_fluxon_kv_lineage") != 1:
        raise AssertionError("each terminal observation must emit lineage exactly once")
    for method_name, expected in (
        ("get_plan", 1),
        ("try_reserve_gpu_direct_staging", 1),
        ("execute_get_plan_cpu", 1),
        ("execute_get_plan_gpu", 1),
    ):
        actual = attribute_call_count(prefetch, method_name)
        if actual != expected:
            raise AssertionError(
                f"r61 must retain one r55 {method_name} call, got {actual}"
            )
    helper_source = ast.unparse(execute_commit)
    prefetch_source = ast.unparse(prefetch)
    if attribute_call_count(execute_commit, "all_reduce") != 1:
        raise AssertionError("r61 execute commit must use exactly one TP collective")
    for marker in (
        "torch.distributed.ReduceOp.SUM",
        "succeeded_rank_count == self.tp_world_size",
        "gpu_direct_rank_count in (0, self.tp_world_size)",
    ):
        if marker not in helper_source:
            raise AssertionError(f"r61 execute commit is missing {marker}")
    for marker in (
        "planned_execute_pages = transferable_pages",
        "planned_execute_gpu_direct = kv_gpu_direct",
        "planned_execute_pages > 0 and self.tp_world_size > 1",
        "self._fluxon_hostless_tp_plan_execute_commit",
        "prefetch_tp_plan_execute_commit_rejected",
        "tp_plan_execute_commit_rejected",
    ):
        if marker not in prefetch_source:
            raise AssertionError(f"r61 prefetch is missing execute commit marker {marker}")
    execute_pos = prefetch_source.index("execute_get_plan_gpu")
    commit_pos = prefetch_source.index(
        "self._fluxon_hostless_tp_plan_execute_commit"
    )
    publish_pos = prefetch_source.index(
        "operation = _FluxonHostlessPrefetchOperation"
    )
    if not execute_pos < commit_pos < publish_pos:
        raise AssertionError(
            "r61 TP commit must run after Plan execute and before operation publish"
        )
    if "_FLUXON_GPU_DIRECT_STAGING_SLOT_COUNT = 288" not in source:
        raise AssertionError("r61 must keep the r55 288-slot staging baseline")


def validate_frozen_file(path: Path, expected_sha256: str, label: str) -> None:
    actual = file_sha256(path)
    if actual != expected_sha256:
        raise AssertionError(
            f"r61 {label} must be the exact archived r55 file: "
            f"expected={expected_sha256} actual={actual}"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("runtime", type=Path)
    parser.add_argument("adapter", type=Path)
    parser.add_argument("scheduler", type=Path)
    args = parser.parse_args()
    validate_runtime(args.runtime)
    validate_frozen_file(args.adapter, R55_ADAPTER_SHA256, "adapter")
    validate_frozen_file(args.scheduler, R55_SCHEDULER_SHA256, "scheduler")
    print("e44 r61 TP Plan execute commit validation: passed")


if __name__ == "__main__":
    main()
