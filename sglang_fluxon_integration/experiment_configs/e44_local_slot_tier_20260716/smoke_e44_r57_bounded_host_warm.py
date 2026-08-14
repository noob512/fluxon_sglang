#!/usr/bin/env python3
from __future__ import annotations

import gc
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from fluxon_py.api_error import Result
from sglang.srt.mem_cache.storage.fluxon.hicache_fluxon import HiCacheFluxon
from sglang.srt.mem_cache.unified_radix_cache import (
    UnifiedRadixCache,
    _FluxonHostlessPrefetchOperation,
)


class Counters:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.created = 0
        self.released = 0
        self.unwrapped = 0

    def holder_created(self) -> None:
        with self.lock:
            self.created += 1

    def holder_released(self) -> None:
        with self.lock:
            self.released += 1

    def result_unwrapped(self) -> None:
        with self.lock:
            self.unwrapped += 1


class Holder:
    def __init__(self, key: str, counters: Counters) -> None:
        self.key = key
        self.counters = counters
        counters.holder_created()

    def __del__(self) -> None:
        self.counters.holder_released()


class Ok:
    def __init__(self, value: object, counters: Counters) -> None:
        self.result = Result.new_ok(value)
        self.counters = counters
        self.consumed = False

    def is_ok(self) -> bool:
        return self.result.is_ok()

    def unwrap(self) -> object:
        assert not self.consumed
        self.consumed = True
        self.counters.result_unwrapped()
        return self.result.unwrap()


class FakeStore:
    def __init__(self, counters: Counters, release: threading.Event) -> None:
        self.counters = counters
        self.release = release
        self.started = threading.Event()
        self.calls: list[tuple[str, ...]] = []

    def batch_get_blocking(self, keys: list[str], concurrency: int) -> list[Ok]:
        self.calls.append(tuple(keys))
        self.started.set()
        if not self.release.wait(timeout=10):
            raise TimeoutError("fake host warm was not released")
        return [Ok(Holder(key, self.counters), self.counters) for key in keys]


def make_backend(store: FakeStore, limit: int) -> HiCacheFluxon:
    backend = HiCacheFluxon.__new__(HiCacheFluxon)
    backend.store = store
    backend._enable_warm_get = True
    backend._warm_futures = {}
    backend._warm_inflight = set()
    backend._warm_lock = threading.Lock()
    backend._warm_condition = threading.Condition(backend._warm_lock)
    backend._warm_limit = limit
    backend._warm_submit_limit = limit
    backend._warm_drain_budget = limit
    backend._warm_peak_pending = 0
    backend._warm_auto_drained = 0
    backend._warm_auto_drain_failed = 0
    backend._batch_concurrency = 32
    backend._warm_batch_executor = ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix="r57-smoke",
    )
    backend._store_key = lambda key, component_name=None: str(key)
    return backend


def wait_until(predicate, description: str, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for {description}")


def test_auto_drain_and_hard_limit() -> None:
    counters = Counters()
    release = threading.Event()
    store = FakeStore(counters, release)
    backend = make_backend(store, limit=192)
    try:
        keys = [f"auto-{index}" for index in range(300)]
        tracked = backend.prefetch_to_host(
            keys,
            max_keys=len(keys),
            release_on_complete=True,
        )
        assert len(tracked) == 192
        assert len(backend._warm_futures) + len(backend._warm_inflight) == 192
        assert backend._warm_peak_pending == 192
        assert store.started.wait(timeout=5)

        rejected = backend.prefetch_to_host(
            [f"overflow-{index}" for index in range(32)],
            max_keys=32,
            release_on_complete=True,
        )
        assert rejected == ()
        assert len(store.calls) == 1

        release.set()
        wait_until(
            lambda: backend._warm_auto_drained == 192,
            "all terminal holders to auto-drain",
        )
        gc.collect()
        assert counters.created == 192
        assert counters.unwrapped == 192
        assert counters.released == 192
        assert backend._warm_futures == {}
        assert backend._warm_inflight == set()

        keepalives, stats = backend.finish_prefetch_to_host(tracked)
        assert keepalives == []
        assert stats["terminal_drained"] == 192
        assert stats["failed"] == 0
    finally:
        backend._warm_batch_executor.shutdown(wait=True, cancel_futures=True)


def test_foreground_retain_wins_once() -> None:
    counters = Counters()
    release = threading.Event()
    store = FakeStore(counters, release)
    backend = make_backend(store, limit=8)
    tracked = backend.prefetch_to_host(
        ["retain-0", "retain-1"],
        max_keys=2,
        release_on_complete=True,
    )
    assert len(tracked) == 2
    assert store.started.wait(timeout=5)

    result_box: list[tuple[list[object], dict[str, object]]] = []
    waiter = threading.Thread(
        target=lambda: result_box.append(backend.finish_prefetch_to_host(tracked)),
        daemon=True,
    )
    waiter.start()
    wait_until(
        lambda: len(backend._warm_futures) == 1,
        "foreground claim of the first shared-batch future",
    )
    release.set()
    waiter.join(timeout=10)
    assert not waiter.is_alive()
    keepalives, stats = result_box[0]
    # The foreground claims the first per-key wrapper before terminal. The
    # shared-batch callback may then drain the still-unclaimed second wrapper;
    # both outcomes are terminal and together must cover every tracked key.
    assert len(keepalives) == 1
    assert stats["ready"] == 1
    assert stats["terminal_drained"] == 1
    assert backend._warm_auto_drained == 1
    assert len(store.calls) == 1
    assert counters.unwrapped == 2
    assert counters.released == 1

    keepalives.clear()
    result_box.clear()
    gc.collect()
    wait_until(lambda: counters.released == 2, "foreground keepalive release")
    backend._warm_batch_executor.shutdown(wait=True, cancel_futures=True)


def test_correction_retains_until_finish() -> None:
    counters = Counters()
    release = threading.Event()
    release.set()
    store = FakeStore(counters, release)
    backend = make_backend(store, limit=8)
    try:
        tracked = backend.prefetch_to_host(
            ["correction-0", "correction-1"],
            max_keys=2,
            release_on_complete=False,
        )
        wait_until(
            lambda: all(not future.is_waiting() for future in backend._warm_futures.values()),
            "retained correction terminal",
        )
        gc.collect()
        assert counters.created == 2
        assert counters.unwrapped == 0
        assert counters.released == 0

        keepalives, stats = backend.finish_prefetch_to_host(tracked)
        assert len(keepalives) == 2
        assert stats["ready"] == 2
        assert counters.unwrapped == 2
        assert backend._warm_futures == {}
        assert counters.released == 0
        keepalives.clear()
        gc.collect()
        wait_until(lambda: counters.released == 2, "correction keepalive release")
    finally:
        backend._warm_batch_executor.shutdown(wait=True, cancel_futures=True)


class GateBackend:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def prefetch_to_host(
        self,
        keys: list[str],
        component_name: object,
        max_keys: int,
        release_on_complete: bool,
    ) -> tuple[str, ...]:
        self.calls.append(
            {
                "keys": tuple(keys),
                "component_name": component_name,
                "max_keys": max_keys,
                "release_on_complete": release_on_complete,
            }
        )
        return tuple(keys[:max_keys])


def test_two_queue_head_gates() -> None:
    backend = GateBackend()
    cache = UnifiedRadixCache.__new__(UnifiedRadixCache)
    cache._fluxon_host_prefetch_queue_head_k = 4
    cache._fluxon_materialize_queue_head_k = 3
    cache.ongoing_prefetch = {}
    cache._observe_fluxon_hostless_request = lambda req_id, **fields: fields
    cache._fluxon_hostless_observation_age_ms = lambda req_id: 1.0
    materialized: list[str] = []

    def record_materialize(req_id: str, operation: object) -> None:
        materialized.append(req_id)

    cache._materialize_fluxon_hostless_prefetch = record_materialize
    cache.can_terminate_prefetch = lambda operation: False
    operation = _FluxonHostlessPrefetchOperation(
        backend=backend,
        hash_value=[f"gate-{index}" for index in range(300)],
        kv_handle=None,
        mamba_handle=None,
        mamba_key=None,
        completed_tokens=0,
        total_tokens=300 * 64,
        anchor_node_id=1,
        has_ready_transfer=False,
        host_prefetch_target_pages=96,
        deferred_materialization=True,
        gdr_budget_pages=96,
    )
    cache.ongoing_prefetch["gate-request"] = (
        None,
        None,
        None,
        operation,
        None,
        {},
    )

    assert cache.check_prefetch_progress("gate-request", queue_position=7) is False
    assert backend.calls == []
    assert cache.check_prefetch_progress("gate-request", queue_position=5) is False
    assert backend.calls == []
    assert cache.check_prefetch_progress("gate-request", queue_position=3) is False
    assert len(backend.calls) == 1
    assert backend.calls[0]["max_keys"] == 96
    assert backend.calls[0]["release_on_complete"] is True
    assert operation.host_prefetch_started is True
    assert operation.host_prefetch_start_position == 3
    assert cache.check_prefetch_progress("gate-request", queue_position=3) is False
    assert len(backend.calls) == 1
    assert materialized == []
    assert cache.check_prefetch_progress("gate-request", queue_position=2) is False
    assert materialized == ["gate-request"]


def main() -> None:
    test_auto_drain_and_hard_limit()
    test_foreground_retain_wins_once()
    test_correction_retains_until_finish()
    test_two_queue_head_gates()
    print("e44 r57 bounded host warm smoke: passed")


if __name__ == "__main__":
    main()
