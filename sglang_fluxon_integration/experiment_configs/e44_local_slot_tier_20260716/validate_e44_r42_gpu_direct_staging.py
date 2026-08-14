#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import threading
import time
from pathlib import Path
from types import SimpleNamespace


RUNTIME_MARKERS = (
    "_FLUXON_GPU_DIRECT_STAGING_SLOT_COUNT = 288",
    "backend.get_plan(",
    "backend.try_reserve_gpu_direct_staging(",
    "backend.execute_get_plan_gpu(",
    "backend.execute_get_plan_cpu(",
    "operation.backend.get_transfer_gpu(",
    "operation.kv_plan_ptr = operation.backend.get_transfer_gpu(",
    "operation.gpu_staging_lease.trim_after_transfer(",
    "local_gpu_remote_pages",
    "gpu_remote_indices",
    '"gpu_direct_d2d_kernel"',
    "and not has_gpu_staging",
    "Fluxon layer-batched H2D DMA cannot consume GPU staging sources",
    "self._fluxon_hostless_cuda_device_id = self._cuda_device_index()",
    "gpu_direct_admission_reason",
    '"tp_reservation_inconsistent"',
    '"no_gpu_transferable_prefix"',
    '"no_remote_sources"',
    '"sync_restore_finalizer"',
)

ADAPTER_MARKERS = (
    "class _FluxonGpuStagingLease:",
    "class _FluxonGpuStagingPool:",
    "fluxon_pyo3_mod.FixedSlabAllocator",
    "self._allocator = allocator_type(self.slot_count)",
    "store.register_gpu_buffer(",
    "self.store.get_plan(",
    "self.store.execute_get_plan_gpu(",
    "self.store.execute_get_plan_cpu(",
    "self.store.get_start_gpu(",
    "self.store.get_transfer_gpu(",
    "remote_count = sum(",
    "return int(plan_ptr)",
    "self.store.cancel_get_transfer_gpu(",
    "staging_pool.close()",
    "request_exceeds_capacity",
    "insufficient_free_slots",
    "Fluxon GPU staging lease released:",
    "Fluxon GPU staging pool Snapshot:",
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
    init = method_node(tree, "UnifiedRadixCache", "__init__")
    cuda_device_index = method_node(
        tree,
        "UnifiedRadixCache",
        "_cuda_device_index",
    )
    layerwise_init = method_node(
        tree,
        "_FluxonHostlessLayerwiseLoad",
        "__init__",
    )
    layerwise_release = method_node(
        tree,
        "_FluxonHostlessLayerwiseLoad",
        "release_views",
    )

    if len(named_calls(prefetch, "get_plan")) != 1:
        raise AssertionError("prefetch must create exactly one target-free Get plan")
    if len(named_calls(prefetch, "try_reserve_gpu_direct_staging")) != 1:
        raise AssertionError("prefetch must attempt exactly one GPU staging reservation")
    reserve_call = named_calls(prefetch, "try_reserve_gpu_direct_staging")[0]
    if not reserve_call.args or ast.unparse(reserve_call.args[0]) != "local_gpu_remote_pages":
        raise AssertionError("GPU staging must reserve only remote source pages")
    if len(named_calls(prefetch, "execute_get_plan_gpu")) != 1:
        raise AssertionError("prefetch must expose exactly one GPU plan execution branch")
    if len(named_calls(prefetch, "execute_get_plan_cpu")) != 1:
        raise AssertionError("prefetch must expose exactly one CPU plan execution branch")
    if named_calls(prefetch, "get_start_gpu"):
        raise AssertionError("KV prefetch must not restart GPU lookup after planning")
    prefetch_source = ast.unparse(prefetch)
    if not (
        prefetch_source.index("backend.get_plan")
        < prefetch_source.index("backend.try_reserve_gpu_direct_staging")
        < prefetch_source.index("backend.execute_get_plan_gpu")
    ):
        raise AssertionError("prefetch must plan, reserve exact GPU slots, then execute")
    if len(named_calls(progress, "get_transfer_gpu")) != 1:
        raise AssertionError("progress must have exactly one GPU Get terminal wait")
    if "operation.kv_plan_ptr = operation.backend.get_transfer_gpu" not in ast.unparse(
        progress
    ):
        raise AssertionError("GPU terminal must publish one ordered mixed-source plan")
    if len(named_calls(progress, "trim_after_transfer")) != 1:
        raise AssertionError("progress must trim unused staging only after transfer terminal")
    layerwise_init_source = ast.unparse(layerwise_init)
    if "plan_ptr is None" not in layerwise_init_source:
        raise AssertionError("every CPU/GPU mix must carry one ordered source plan")
    if "exactly one CPU plan or GPU staging lease" in layerwise_init_source:
        raise AssertionError("mixed CPU/GPU source ownership must not be rejected")
    layerwise_release_source = ast.unparse(layerwise_release)
    if "backend.release_views" not in layerwise_release_source or "staging_lease.release" not in layerwise_release_source:
        raise AssertionError("mixed restore must release both source plan and GPU lease")

    start_source = ast.unparse(start_loads)
    if "not has_gpu_staging" not in start_source:
        raise AssertionError("GPU staging must bypass the host-only DMA path")
    if "gpu_direct_d2d_kernel" not in start_source:
        raise AssertionError("GPU staging must select the explicit D2D kernel transport")

    init_source = ast.unparse(init)
    capture = "self._fluxon_hostless_cuda_device_id = self._cuda_device_index()"
    worker_start = "self._fluxon_hostless_dma_submit_executor.submit"
    if capture not in init_source or worker_start not in init_source:
        raise AssertionError("background DMA must capture the scheduler CUDA device")
    if init_source.index(capture) > init_source.index(worker_start):
        raise AssertionError("scheduler CUDA device must be captured before worker start")
    device_source = ast.unparse(cuda_device_index)
    if "_fluxon_hostless_cuda_device_id" not in device_source:
        raise AssertionError("background DMA device resolver must reuse the captured id")


def validate_adapter_ast(tree: ast.Module) -> None:
    configure = method_node(tree, "HiCacheFluxon", "configure_gpu_direct_staging")
    get_plan = method_node(tree, "HiCacheFluxon", "get_plan")
    execute_cpu = method_node(tree, "HiCacheFluxon", "execute_get_plan_cpu")
    execute_gpu = method_node(tree, "HiCacheFluxon", "execute_get_plan_gpu")
    get_start = method_node(tree, "HiCacheFluxon", "get_start_gpu")
    get_transfer = method_node(tree, "HiCacheFluxon", "get_transfer_gpu")
    cancel = method_node(tree, "HiCacheFluxon", "cancel_get_transfer_gpu")
    reserve = method_node(tree, "_FluxonGpuStagingPool", "try_reserve")
    snapshot = method_node(tree, "_FluxonGpuStagingPool", "_snapshot_locked")
    release_slots = method_node(tree, "_FluxonGpuStagingPool", "_release_slots")
    release_lease = method_node(tree, "_FluxonGpuStagingPool", "_release_lease")
    close_pool = method_node(tree, "_FluxonGpuStagingPool", "close")

    if len(named_calls(configure, "register_gpu_buffer")) != 0:
        raise AssertionError("registration must remain owned by the staging pool")
    if len(named_calls(get_plan, "get_plan")) != 1:
        raise AssertionError("adapter must forward target-free Get planning exactly once")
    if len(named_calls(execute_cpu, "execute_get_plan_cpu")) != 1:
        raise AssertionError("adapter must forward CPU plan execution exactly once")
    if len(named_calls(execute_gpu, "execute_get_plan_gpu")) != 1:
        raise AssertionError("adapter must forward GPU plan execution exactly once")
    execute_gpu_source = ast.unparse(execute_gpu)
    if "remote_count" not in execute_gpu_source or "gpu_remote_indices" not in execute_gpu_source:
        raise AssertionError("adapter must size GPU destinations from remote positions")
    if len(named_calls(get_start, "get_start_gpu")) != 1:
        raise AssertionError("adapter must forward GPU Get Start exactly once")
    if len(named_calls(get_transfer, "get_transfer_gpu")) != 1:
        raise AssertionError("adapter must forward GPU Get terminal wait exactly once")
    if "return int(plan_ptr)" not in ast.unparse(get_transfer):
        raise AssertionError("adapter GPU terminal must return the ordered source plan")
    if len(named_calls(cancel, "cancel_get_transfer_gpu")) != 1:
        raise AssertionError("adapter must forward GPU Get cancellation exactly once")
    reserve_source = ast.unparse(reserve)
    for reason in (
        "selected",
        "request_exceeds_capacity",
        "insufficient_free_slots",
        "pool_closed",
        "not_eligible",
    ):
        if reason not in reserve_source:
            raise AssertionError(f"GPU admission is missing reason {reason}")
    pool_node = class_node(tree, "_FluxonGpuStagingPool")
    if any(
        isinstance(node, ast.Attribute) and node.attr == "_free_slots"
        for node in ast.walk(pool_node)
    ):
        raise AssertionError("Python freelist must be replaced by FixedSlabAllocator")
    if "self._allocator.free_count" not in ast.unparse(snapshot):
        raise AssertionError("pool snapshots must read the Rust allocator")
    if len(named_calls(reserve, "try_reserve")) != 1:
        raise AssertionError("GPU admission must reserve through one Rust allocator call")
    if len(named_calls(release_slots, "release")) != 1:
        raise AssertionError("trimmed slots must return through the Rust allocator")
    if len(named_calls(release_lease, "release")) != 1:
        raise AssertionError("lease release must return through the Rust allocator")
    if "held_ms" not in ast.unparse(release_lease):
        raise AssertionError("lease release must retain hold duration observation")
    if "admission_reasons" not in ast.unparse(close_pool):
        raise AssertionError("pool close must emit its accumulated Snapshot")


def validate_lease_lifecycle(tree: ast.Module) -> None:
    lease_class = class_node(tree, "_FluxonGpuStagingLease")
    pool_class = class_node(tree, "_FluxonGpuStagingPool")
    module = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__",
                names=[ast.alias(name="annotations")],
                level=0,
            ),
            lease_class,
            pool_class,
        ],
        type_ignores=[],
    )
    ast.fix_missing_locations(module)

    class FakeLogger:
        def info(self, *args, **kwargs) -> None:
            pass

    class FakeTensor:
        def __init__(self, size: int) -> None:
            self._size = size

        def data_ptr(self) -> int:
            return 0x100000

        def numel(self) -> int:
            return self._size

    class DeviceContext:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            pass

    class FakeCuda:
        @staticmethod
        def device(device_id: int) -> DeviceContext:
            return DeviceContext()

    class FakeTorch:
        uint8 = object()
        cuda = FakeCuda()

        @staticmethod
        def device(kind: str, device_id: int) -> tuple[str, int]:
            return kind, device_id

        @staticmethod
        def empty(size: int, dtype, device) -> FakeTensor:
            return FakeTensor(size)

    class FakeFixedSlabAllocator:
        def __init__(self, slot_count: int) -> None:
            self.capacity = slot_count
            self._free = list(range(slot_count - 1, -1, -1))
            self._allocated = [False] * slot_count

        @property
        def free_count(self) -> int:
            return len(self._free)

        @property
        def live_count(self) -> int:
            return self.capacity - len(self._free)

        def try_reserve(self, count: int) -> list[int] | None:
            if count > len(self._free):
                return None
            slots = [self._free.pop() for _ in range(count)]
            for slot in slots:
                if self._allocated[slot]:
                    raise AssertionError("fake allocator freelist corruption")
                self._allocated[slot] = True
            return slots

        def release(self, slots: list[int]) -> None:
            if len(slots) != len(set(slots)):
                raise ValueError("duplicate slot")
            if any(slot < 0 or slot >= self.capacity for slot in slots):
                raise ValueError("slot out of bounds")
            if any(not self._allocated[slot] for slot in slots):
                raise ValueError("slot is not allocated")
            for slot in slots:
                self._allocated[slot] = False
                self._free.append(slot)

        def is_empty(self) -> bool:
            return self.live_count == 0

    namespace: dict[str, object] = {
        "logger": FakeLogger(),
        "threading": threading,
        "time": time,
        "torch": FakeTorch(),
    }
    exec(compile(module, "<gpu-staging-lease>", "exec"), namespace)
    lease_type = namespace["_FluxonGpuStagingLease"]
    pool_type = namespace["_FluxonGpuStagingPool"]

    class Registration:
        registration_id = 1

        def destination(self, ptr: int, capacity: int) -> SimpleNamespace:
            return SimpleNamespace(ptr=ptr, capacity=capacity)

    class Result:
        def __init__(self, value) -> None:
            self._value = value

        def is_ok(self) -> bool:
            return True

        def unwrap(self):
            return self._value

    class Store:
        def __init__(self) -> None:
            self.unregister_count = 0

        def register_gpu_buffer(self, ptr: int, size: int, device_id: int) -> Result:
            return Result(Registration())

        def unregister_gpu_buffer(self, registration: Registration) -> Result:
            self.unregister_count += 1
            return Result(None)

    store = Store()
    pool = pool_type(store, 4096, 4, 0, FakeFixedSlabAllocator)
    lease, selected = pool.try_reserve(3)
    if not isinstance(lease, lease_type):
        raise AssertionError("selected admission did not return a lease")
    if selected != {
        "reason": "selected",
        "requested_pages": 3,
        "capacity_slots": 4,
        "free_slots_before": 4,
        "live_slots_before": 0,
        "active_leases_before": 0,
        "free_slots_after": 1,
        "live_slots_after": 3,
        "active_leases_after": 1,
        "high_watermark_slots": 3,
    }:
        raise AssertionError(f"unexpected selected admission snapshot: {selected}")

    too_large_lease, too_large = pool.try_reserve(5)
    if too_large_lease is not None or too_large["reason"] != "request_exceeds_capacity":
        raise AssertionError("request larger than pool did not get a stable reason")
    busy_lease, busy = pool.try_reserve(2)
    if busy_lease is not None or busy["reason"] != "insufficient_free_slots":
        raise AssertionError("temporarily busy pool did not get a stable reason")

    lease.trim_after_transfer(2)
    if lease.page_count != 2 or pool._allocator.free_count != 2:
        raise AssertionError("staging trim did not release only the unused tail")
    lease.release("validator_complete")
    lease.release("must_be_idempotent")
    if (
        pool._allocator.free_count != 4
        or not lease.released
        or pool._active_leases != 0
        or pool._lease_releases != 1
        or pool._release_reasons != {"validator_complete": 1}
    ):
        raise AssertionError("staging release is not complete and idempotent")

    blocked_lease, blocked = pool.try_reserve(1, "mamba_required")
    if blocked_lease is not None or blocked["reason"] != "mamba_required":
        raise AssertionError("explicit runtime admission block was not preserved")
    pool.close()
    if store.unregister_count != 1:
        raise AssertionError("pool close did not unregister exactly once")
    closed_lease, closed = pool.try_reserve(1)
    if closed_lease is not None or closed["reason"] != "pool_closed":
        raise AssertionError("closed pool admission reason was not preserved")


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
