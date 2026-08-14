#!/usr/bin/env python3
from __future__ import annotations

import inspect
from types import SimpleNamespace

from sglang.srt.mem_cache.storage.fluxon.hicache_fluxon import HiCacheFluxon


class RecordingStore:
    def __init__(self) -> None:
        self.calls: list[tuple[object, int | None, int | None]] = []

    def get_transfer(
        self,
        handle: object,
        concurrency: int | None = None,
        *,
        consume_prefix_len: int | None = None,
    ) -> int:
        self.calls.append((handle, concurrency, consume_prefix_len))
        return 0x1234


def main() -> None:
    signature = inspect.signature(HiCacheFluxon.get_transfer)
    consume = signature.parameters.get("consume_prefix_len")
    if consume is None or consume.kind is not inspect.Parameter.KEYWORD_ONLY:
        raise AssertionError(f"unexpected adapter signature: {signature}")
    if consume.default is not None:
        raise AssertionError(f"consume_prefix_len must default to None: {signature}")

    store = RecordingStore()
    adapter = SimpleNamespace(store=store, _batch_concurrency=32)
    first_handle = SimpleNamespace(closed=False)
    result = HiCacheFluxon.get_transfer(
        adapter,
        first_handle,
        consume_prefix_len=7,
    )
    if result != 0x1234 or store.calls != [(first_handle, 32, 7)]:
        raise AssertionError(
            f"explicit prefix was not forwarded exactly: result={result} "
            f"calls={store.calls}"
        )

    second_handle = SimpleNamespace(closed=False)
    result = HiCacheFluxon.get_transfer(adapter, second_handle)
    if result != 0x1234 or store.calls[-1] != (second_handle, 32, None):
        raise AssertionError(
            f"default full-prefix behavior changed: result={result} calls={store.calls}"
        )

    try:
        HiCacheFluxon.get_transfer(adapter, second_handle, 7)
    except TypeError:
        pass
    else:
        raise AssertionError("consume_prefix_len must reject positional callers")

    print("e44 r38 installed HiCacheFluxon adapter real-call smoke: passed")


if __name__ == "__main__":
    main()
