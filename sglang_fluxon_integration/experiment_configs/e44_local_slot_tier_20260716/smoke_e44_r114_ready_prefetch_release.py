#!/usr/bin/env python3
from __future__ import annotations

from types import SimpleNamespace

from sglang.srt.mem_cache.unified_radix_cache import UnifiedRadixCache


def main() -> None:
    rid = "r114-holder-release"
    ready_operation = SimpleNamespace(hash_value=["page"])
    released: list[tuple[object, str]] = []
    last_device_node = object()
    empty_indices = object()
    fake_cache = SimpleNamespace(
        fluxon_hostless_ready_prefetch={rid: ready_operation},
        _fluxon_hostless_request_observations={},
        _empty_match_result=SimpleNamespace(device_indices=empty_indices),
        _is_fluxon_hostless_full_mode=lambda: True,
        _fluxon_hostless_longest_ready_restore_node=lambda *_: None,
        _cancel_fluxon_hostless_prefetch_operation=lambda operation, reason: released.append(
            (operation, reason)
        ),
    )
    params = SimpleNamespace(
        best_match_node=SimpleNamespace(id=7),
        mem_quota=None,
        req=SimpleNamespace(rid=rid, last_node=last_device_node),
        host_hit_length=64,
    )

    device_indices, matched_node = UnifiedRadixCache.init_load_back(fake_cache, params)
    assert device_indices is empty_indices
    assert matched_node is last_device_node
    assert fake_cache.fluxon_hostless_ready_prefetch == {}
    assert released == [(ready_operation, "ready_no_whole_node_prefix")]
    print("e44 r114 ready-prefetch holder lifecycle smoke: passed")


if __name__ == "__main__":
    main()
