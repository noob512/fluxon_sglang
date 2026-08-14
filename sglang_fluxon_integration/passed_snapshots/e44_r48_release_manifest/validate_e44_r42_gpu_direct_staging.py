#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
from pathlib import Path
from types import SimpleNamespace


RUNTIME_MARKERS = (
    "_FLUXON_GPU_DIRECT_STAGING_SLOT_COUNT = 288",
    "backend.try_reserve_gpu_direct_staging(",
    "backend.get_start_gpu(",
    "operation.backend.get_transfer_gpu(",
    "operation.gpu_staging_lease.trim_after_transfer(",
    '"gpu_direct_d2d_kernel"',
    "and not has_gpu_staging",
    "Fluxon layer-batched H2D DMA cannot consume GPU staging sources",
)

ADAPTER_MARKERS = (
    "class _FluxonGpuStagingLease:",
    "class _FluxonGpuStagingPool:",
    "store.register_gpu_buffer(",
    "self.store.get_start_gpu(",
    "self.store.get_transfer_gpu(",
    "self.store.cancel_get_transfer_gpu(",
    "staging_pool.close()",
)


def class_node(tree: ast.Module, name: str) -> ast.ClassDef:
    return next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == name
    )


def method_node(tree: ast.Module, class_name: str, method_name: str) -> ast.FunctionDef:
    target_class = class_node(tree, class_name)
    return next(
        node
        for node in target_class.body
        if isinstance(node, ast.FunctionDef) and node.name == method_name
    )


def named_calls(method: ast.FunctionDef, name: str) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(method)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == name
    ]


def validate_runtime_ast(tree: ast.Module) -> None:
    prefetch = method_node(tree, "UnifiedRadixCache", "prefetch_from_storage")
    progress = method_node(tree, "UnifiedRadixCache", "check_prefetch_progress")
    start_loads = method_node(
        tree,
        "UnifiedRadixCache",
        "_start_fluxon_hostless_layerwise_loads",
    )

    if len(named_calls(prefetch, "try_reserve_gpu_direct_staging")) != 1:
        raise AssertionError("prefetch must attempt exactly one GPU staging reservation")
    if len(named_calls(prefetch, "get_start_gpu")) != 1:
        raise AssertionError("prefetch must have exactly one GPU Get Start call")
    if len(named_calls(progress, "get_transfer_gpu")) != 1:
        raise AssertionError("progress must have exactly one GPU Get terminal wait")
    if len(named_calls(progress, "trim_after_transfer")) != 1:
        raise AssertionError("progress must trim unused staging only after transfer terminal")

    start_source = ast.unparse(start_loads)
    if "not has_gpu_staging" not in start_source:
        raise AssertionError("GPU staging must bypass the host-only DMA path")
    if "gpu_direct_d2d_kernel" not in start_source:
        raise AssertionError("GPU staging must select the explicit D2D kernel transport")


def validate_adapter_ast(tree: ast.Module) -> None:
    configure = method_node(tree, "HiCacheFluxon", "configure_gpu_direct_staging")
    get_start = method_node(tree, "HiCacheFluxon", "get_start_gpu")
    get_transfer = method_node(tree, "HiCacheFluxon", "get_transfer_gpu")
    cancel = method_node(tree, "HiCacheFluxon", "cancel_get_transfer_gpu")

    if len(named_calls(configure, "register_gpu_buffer")) != 0:
        raise AssertionError("registration must remain owned by the staging pool")
    if len(named_calls(get_start, "get_start_gpu")) != 1:
        raise AssertionError("adapter must forward GPU Get Start exactly once")
    if len(named_calls(get_transfer, "get_transfer_gpu")) != 1:
        raise AssertionError("adapter must forward GPU Get terminal wait exactly once")
    if len(named_calls(cancel, "cancel_get_transfer_gpu")) != 1:
        raise AssertionError("adapter must forward GPU Get cancellation exactly once")


def validate_lease_lifecycle(tree: ast.Module) -> None:
    lease_class = class_node(tree, "_FluxonGpuStagingLease")
    module = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__",
                names=[ast.alias(name="annotations")],
                level=0,
            ),
            lease_class,
        ],
        type_ignores=[],
    )
    ast.fix_missing_locations(module)
    namespace: dict[str, object] = {}
    exec(compile(module, "<gpu-staging-lease>", "exec"), namespace)
    lease_type = namespace["_FluxonGpuStagingLease"]

    class Registration:
        def destination(self, ptr: int, capacity: int) -> SimpleNamespace:
            return SimpleNamespace(ptr=ptr, capacity=capacity)

    class Pool:
        registration = Registration()
        base_ptr = 0x100000
        slot_size = 4096

        def __init__(self) -> None:
            self.released: list[int] = []

        def _release_slots(self, slots: list[int]) -> None:
            self.released.extend(slots)

    pool = Pool()
    lease = lease_type(pool, [2, 4, 6])
    lease.trim_after_transfer(2)
    if pool.released != [6] or lease.page_count != 2:
        raise AssertionError("staging trim did not release only the unused tail")
    lease.release()
    lease.release()
    if pool.released != [6, 2, 4] or not lease.released:
        raise AssertionError("staging release is not complete and idempotent")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("runtime", type=Path)
    parser.add_argument("adapter", type=Path)
    args = parser.parse_args()

    runtime_text = args.runtime.read_text(encoding="utf-8")
    adapter_text = args.adapter.read_text(encoding="utf-8")
    for marker in RUNTIME_MARKERS:
        if marker not in runtime_text:
            raise AssertionError(f"runtime is missing r42 marker: {marker}")
    for marker in ADAPTER_MARKERS:
        if marker not in adapter_text:
            raise AssertionError(f"adapter is missing r42 marker: {marker}")

    runtime_tree = ast.parse(runtime_text, filename=str(args.runtime))
    adapter_tree = ast.parse(adapter_text, filename=str(args.adapter))
    compile(runtime_tree, str(args.runtime), "exec")
    compile(adapter_tree, str(args.adapter), "exec")
    validate_runtime_ast(runtime_tree)
    validate_adapter_ast(adapter_tree)
    validate_lease_lifecycle(adapter_tree)
    print("e44 r42 GPU-direct staging lifecycle validation: passed")


if __name__ == "__main__":
    main()
