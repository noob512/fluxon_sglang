#!/usr/bin/env python3
from __future__ import annotations

from types import SimpleNamespace

from sglang.srt.mem_cache.unified_radix_cache import UnifiedRadixCache
from sglang.srt.mem_cache.unified_cache_components import BASE_COMPONENT_TYPE


def make_cache():
    snapshots: list[str] = []
    allocator = SimpleNamespace(available=500_000)
    allocator.available_size = lambda: allocator.available
    allocator.full_available_size = lambda: allocator.available
    cache = SimpleNamespace(
        cache_controller=SimpleNamespace(prefetch_tokens_occupied=0),
        token_to_kv_pool_allocator=allocator,
        component_evictable_size_={BASE_COMPONENT_TYPE: 0},
        supports_swa=lambda: False,
        tp_world_size=1,
        tp_group=None,
        _fluxon_hostless_admission_total_tokens_occupied=0,
        _fluxon_hostless_admission_remote_pages_occupied=0,
        _fluxon_hostless_admission_active=0,
        _fluxon_hostless_admission_acquired=0,
        _fluxon_hostless_admission_released=0,
        _fluxon_hostless_admission_total_rejected=0,
        _fluxon_hostless_admission_remote_rejected=0,
        _fluxon_hostless_admission_state_rejected=0,
        _fluxon_hostless_admission_device_headroom_rejected=0,
        _fluxon_hostless_admission_source_mismatches=0,
        _fluxon_hostless_admission_total_tokens_high_watermark=0,
        _fluxon_hostless_admission_remote_pages_high_watermark=0,
        _fluxon_hostless_admission_active_high_watermark=0,
        _fluxon_hostless_tp_rank=lambda: 0,
        _log_fluxon_hostless_admission_snapshot=lambda caller: snapshots.append(
            caller
        ),
    )
    release_values = (
        UnifiedRadixCache._release_fluxon_hostless_prefetch_admission_values
    )
    cache._release_fluxon_hostless_prefetch_admission_values = (
        lambda total_tokens, remote_pages, caller: release_values(
            cache,
            total_tokens,
            remote_pages,
            caller,
        )
    )
    return cache, snapshots, allocator


def main() -> None:
    acquire = UnifiedRadixCache._try_acquire_fluxon_hostless_prefetch_admission
    release = UnifiedRadixCache._release_fluxon_hostless_prefetch_admission
    cache, snapshots, allocator = make_cache()

    first = acquire(cache, "first", 200_000, 480)
    assert first["admitted"] is True
    assert first["remote_pages"] == 480
    assert cache._fluxon_hostless_admission_total_tokens_occupied == 200_000
    assert cache._fluxon_hostless_admission_remote_pages_occupied == 480
    assert cache.cache_controller.prefetch_tokens_occupied == 200_000

    remote_reject = acquire(cache, "remote-reject", 1, 33)
    assert remote_reject["admitted"] is False
    assert remote_reject["reason"] == "remote_source_limit"
    total_reject = acquire(cache, "total-reject", 34_049, 0)
    assert total_reject["admitted"] is False
    assert total_reject["reason"] == "total_holder_limit"

    operation = SimpleNamespace(
        admission_active=True,
        admission_total_tokens=200_000,
        admission_remote_pages=480,
    )
    release(cache, operation, "first-ready")
    assert operation.admission_active is False
    assert cache._fluxon_hostless_admission_total_tokens_occupied == 0
    assert cache._fluxon_hostless_admission_remote_pages_occupied == 0
    assert cache.cache_controller.prefetch_tokens_occupied == 0
    assert cache._fluxon_hostless_admission_acquired == 1
    assert cache._fluxon_hostless_admission_released == 1
    assert snapshots == ["first-ready:drained"]

    # Several lifecycle exits may converge on the same operation.  The debt
    # release is generation-local and idempotent.
    release(cache, operation, "duplicate-release")
    assert cache._fluxon_hostless_admission_released == 1

    exact = acquire(cache, "exact-limit", 234_048, 512)
    assert exact["admitted"] is True
    exact_operation = SimpleNamespace(
        admission_active=True,
        admission_total_tokens=234_048,
        admission_remote_pages=512,
    )
    release(cache, exact_operation, "exact-ready")
    assert cache._fluxon_hostless_admission_total_tokens_high_watermark == 234_048
    assert cache._fluxon_hostless_admission_remote_pages_high_watermark == 512

    allocator.available = 40_000
    cache.component_evictable_size_[BASE_COMPONENT_TYPE] = 20_000
    headroom_first = acquire(cache, "headroom-first", 33_024, 0)
    assert headroom_first["admitted"] is True
    assert headroom_first["device_reclaimable_min"] == 60_000
    assert headroom_first["device_prefetch_budget"] == 51_808
    headroom_reject = acquire(cache, "headroom-reject", 29_952, 0)
    assert headroom_reject["admitted"] is False
    assert headroom_reject["reason"] == "device_headroom"
    assert cache._fluxon_hostless_admission_device_headroom_rejected == 1
    headroom_operation = SimpleNamespace(
        admission_active=True,
        admission_total_tokens=33_024,
        admission_remote_pages=0,
    )
    release(cache, headroom_operation, "headroom-ready")

    allocator.available = 500_000
    cache.component_evictable_size_[BASE_COMPONENT_TYPE] = 0
    cache.cache_controller.prefetch_tokens_occupied = 1
    mismatch = acquire(cache, "state-mismatch", 64, 0)
    assert mismatch["admitted"] is False
    assert mismatch["reason"] == "tp_state_mismatch"
    assert cache._fluxon_hostless_admission_state_rejected == 1
    print("e44 r133 device-headroom admission smoke: passed")


if __name__ == "__main__":
    main()
