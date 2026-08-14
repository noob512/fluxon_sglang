#!/usr/bin/env python3
from __future__ import annotations

from types import SimpleNamespace

from sglang.srt.mem_cache.unified_radix_cache import UnifiedRadixCache


def make_cache():
    snapshots: list[str] = []
    cache = SimpleNamespace(
        cache_controller=SimpleNamespace(prefetch_tokens_occupied=0),
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
    return cache, snapshots


def main() -> None:
    acquire = UnifiedRadixCache._try_acquire_fluxon_hostless_prefetch_admission
    release = UnifiedRadixCache._release_fluxon_hostless_prefetch_admission
    cache, snapshots = make_cache()

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

    cache.cache_controller.prefetch_tokens_occupied = 1
    mismatch = acquire(cache, "state-mismatch", 64, 0)
    assert mismatch["admitted"] is False
    assert mismatch["reason"] == "tp_state_mismatch"
    assert cache._fluxon_hostless_admission_state_rejected == 1
    print("e44 r119 source-aware admission smoke: passed")


if __name__ == "__main__":
    main()
