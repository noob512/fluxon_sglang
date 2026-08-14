#!/usr/bin/env python3
from __future__ import annotations

from types import SimpleNamespace

from sglang.srt.mem_cache.unified_radix_cache import UnifiedRadixCache


PAGE_SIZE = 64


def node(node_id: int, parent, hashes: list[str]):
    return SimpleNamespace(
        id=node_id,
        parent=parent,
        key=[0] * (len(hashes) * PAGE_SIZE),
        hashes=hashes,
    )


def operation(hashes: list[str]):
    return SimpleNamespace(
        kv_plan_ptr=0x1234,
        kv_plan_offset_pages=0,
        hash_value=hashes,
        completed_tokens=len(hashes) * PAGE_SIZE,
        anchor_node_id=9,
    )


def main() -> None:
    root = node(0, None, [])
    device = node(1, root, ["d0", "d1"])
    first = node(2, device, ["p8", "p9"])
    best = node(3, first, ["p10", "p11"])
    fake_cache = SimpleNamespace(
        root_node=root,
        page_size=PAGE_SIZE,
        _node_hash_values=lambda current: current.hashes,
    )
    longest = UnifiedRadixCache._fluxon_hostless_longest_ready_restore_node
    covers = UnifiedRadixCache._fluxon_hostless_ready_operation_covers_kv
    view_ptrs = UnifiedRadixCache._fluxon_hostless_ready_value_ptrs

    shifted = operation([f"p{i}" for i in range(12)])
    shape: dict[str, object] = {}
    result = longest(
        fake_cache,
        shifted,
        best,
        device,
        failure_shape=shape,
    )
    assert result is best
    assert shifted.kv_plan_offset_pages == 8
    assert covers(fake_cache, shifted, [f"p{i}" for i in range(8, 12)])
    backend = SimpleNamespace(
        view_value_ptrs=lambda plan_ptr, count: tuple(
            0x1000 + index for index in range(count)
        )
    )
    assert view_ptrs(fake_cache, backend, 0x1234, shifted, 4) == tuple(
        0x1000 + index for index in range(8, 12)
    )

    partial = operation([f"p{i}" for i in range(11)])
    shape = {}
    result = longest(
        fake_cache,
        partial,
        best,
        device,
        failure_shape=shape,
    )
    assert result is first
    assert partial.kv_plan_offset_pages == 8
    assert shape["reason"] == "node_exceeds_ready_prefix"
    assert covers(fake_cache, partial, ["p8", "p9"])
    assert not covers(fake_cache, partial, ["p8", "p9", "p10", "p11"])

    regressed_first = node(4, device, ["before0", "before1"])
    regressed_best = node(5, regressed_first, ["p0", "p1"])
    regressed = operation([f"p{i}" for i in range(12)])
    shape = {}
    result = longest(
        fake_cache,
        regressed,
        regressed_best,
        device,
        failure_shape=shape,
    )
    assert result is None
    assert regressed.kv_plan_offset_pages == 0
    assert shape["reason"] == "node_hash_mismatch"

    ambiguous_first = node(6, device, ["same", "tail"])
    ambiguous = operation(["old", "same", "tail", "same", "tail"])
    shape = {}
    result = longest(
        fake_cache,
        ambiguous,
        ambiguous_first,
        device,
        failure_shape=shape,
    )
    assert result is None
    assert shape["reason"] == "ambiguous_plan_suffix_alignment"

    try:
        view_ptrs(fake_cache, backend, 0x1234, shifted, 5)
    except RuntimeError as exc:
        assert "out of bounds" in str(exc)
    else:
        raise AssertionError("out-of-bounds plan slice was accepted")

    rid = "r116-holder-release"
    ready_operation = operation(["p0"])
    released: list[tuple[object, str]] = []
    empty_indices = object()

    def no_match(*_, failure_shape=None, **__) -> None:
        failure_shape.update(
            reason="node_hash_mismatch",
            ready_pages=1,
            path_nodes=1,
            path_pages=2,
            plan_offset_pages=0,
            alignment_candidates=0,
        )
        return None

    fake_init_cache = SimpleNamespace(
        fluxon_hostless_ready_prefetch={rid: ready_operation},
        _fluxon_hostless_request_observations={},
        _empty_match_result=SimpleNamespace(device_indices=empty_indices),
        _is_fluxon_hostless_full_mode=lambda: True,
        _fluxon_hostless_longest_ready_restore_node=no_match,
        _cancel_fluxon_hostless_prefetch_operation=lambda op, reason: released.append(
            (op, reason)
        ),
    )
    params = SimpleNamespace(
        best_match_node=best,
        mem_quota=None,
        req=SimpleNamespace(rid=rid, last_node=device),
        host_hit_length=64,
    )
    device_indices, matched_node = UnifiedRadixCache.init_load_back(
        fake_init_cache, params
    )
    assert device_indices is empty_indices
    assert matched_node is device
    assert fake_init_cache.fluxon_hostless_ready_prefetch == {}
    assert released == [(ready_operation, "ready_no_whole_node_prefix")]
    anchor = node(7, root, ["anchor"])
    lock_params = object()
    acquired: list[object] = []
    released: list[tuple[object, object]] = []

    class LockResult:
        def to_dec_params(self):
            return lock_params

    lock_cache = SimpleNamespace(
        root_node=root,
        _fluxon_hostless_anchor_locks_active=0,
        _fluxon_hostless_anchor_locks_acquired=0,
        _fluxon_hostless_anchor_locks_released=0,
        _fluxon_hostless_anchor_locks_high_watermark=0,
        inc_lock_ref=lambda current: acquired.append(current) or LockResult(),
        dec_lock_ref=lambda current, params: released.append((current, params)),
    )
    acquire_anchor = UnifiedRadixCache._acquire_fluxon_hostless_anchor_lock
    release_anchor = UnifiedRadixCache._release_fluxon_hostless_anchor_lock
    locked_operation = SimpleNamespace(
        kv_anchor_node=None,
        kv_anchor_lock_params=None,
        kv_plan_ptr=None,
        mamba_plan_ptr=None,
        kv_handle=None,
        mamba_handle=None,
        gpu_staging_lease=None,
        gpu_direct=False,
        backend=SimpleNamespace(),
    )
    acquire_anchor(lock_cache, locked_operation, anchor)
    assert acquired == [anchor]
    assert locked_operation.kv_anchor_node is anchor
    assert locked_operation.kv_anchor_lock_params is lock_params
    assert lock_cache._fluxon_hostless_anchor_locks_active == 1
    assert lock_cache._fluxon_hostless_anchor_locks_acquired == 1
    assert lock_cache._fluxon_hostless_anchor_locks_high_watermark == 1

    lock_cache._release_fluxon_hostless_anchor_lock = lambda current: release_anchor(
        lock_cache, current
    )
    lock_cache._cancel_fluxon_hostless_get_start_handle = lambda *args, **kwargs: None
    lock_cache._release_fluxon_gpu_staging_lease = lambda *args, **kwargs: None
    cancel_operation = UnifiedRadixCache._cancel_fluxon_hostless_prefetch_operation
    cancel_operation(lock_cache, locked_operation, "smoke_first_cancel")
    assert released == [(anchor, lock_params)]
    assert locked_operation.kv_anchor_node is None
    assert locked_operation.kv_anchor_lock_params is None
    assert lock_cache._fluxon_hostless_anchor_locks_active == 0
    assert lock_cache._fluxon_hostless_anchor_locks_released == 1

    # Unified cancellation is intentionally idempotent: several error paths can
    # converge on the same operation, but the anchor must be released once.
    cancel_operation(lock_cache, locked_operation, "smoke_second_cancel")
    assert released == [(anchor, lock_params)]
    assert lock_cache._fluxon_hostless_anchor_locks_active == 0
    assert lock_cache._fluxon_hostless_anchor_locks_released == 1

    root_operation = SimpleNamespace(
        kv_anchor_node=None,
        kv_anchor_lock_params=None,
    )
    acquire_anchor(lock_cache, root_operation, root)
    assert acquired == [anchor]
    assert lock_cache._fluxon_hostless_anchor_locks_active == 0
    print("e44 r118 ready-anchor lock smoke: passed")


if __name__ == "__main__":
    main()
