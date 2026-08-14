#!/usr/bin/env python3
from __future__ import annotations

from types import SimpleNamespace

from sglang.srt.mem_cache.unified_radix_cache import UnifiedRadixCache


def node(node_id: int, parent, pages: int, hashes: list[str]):
    return SimpleNamespace(
        id=node_id,
        parent=parent,
        key=[0] * (pages * 64),
        hashes=hashes,
    )


def operation(hashes: list[str], completed_pages: int, anchor_node_id: int = 9):
    return SimpleNamespace(
        kv_plan_ptr=1,
        hash_value=hashes,
        completed_tokens=completed_pages * 64,
        anchor_node_id=anchor_node_id,
    )


def main() -> None:
    root = node(0, None, 0, [])
    device = node(1, root, 2, ["d0", "d1"])
    first = node(2, device, 10, [f"p{i}" for i in range(10)])
    fake_cache = SimpleNamespace(
        root_node=root,
        page_size=64,
        _node_hash_values=lambda current: current.hashes,
    )
    helper = UnifiedRadixCache._fluxon_hostless_longest_ready_restore_node

    shape: dict[str, object] = {}
    result = helper(
        fake_cache,
        operation([f"p{i}" for i in range(4)], 4),
        first,
        device,
        failure_shape=shape,
    )
    assert result is None
    assert shape == {
        "reason": "node_exceeds_ready_prefix",
        "ready_pages": 4,
        "path_nodes": 1,
        "path_pages": 10,
        "failure_node_index": 0,
        "failure_node_pages": 10,
        "consumed_pages": 0,
        "matched_pages": 0,
        "remaining_ready_pages": 4,
    }

    shape = {}
    result = helper(
        fake_cache,
        operation(["p0", "p1", "wrong", *[f"p{i}" for i in range(3, 10)]], 10),
        first,
        device,
        failure_shape=shape,
    )
    assert result is None
    assert shape["reason"] == "node_hash_mismatch"
    assert shape["matched_pages"] == 2

    other_device = node(3, root, 1, ["other"])
    shape = {}
    result = helper(
        fake_cache,
        operation(["p0"], 1),
        first,
        other_device,
        failure_shape=shape,
    )
    assert result is None
    assert shape["reason"] == "device_anchor_not_ancestor"

    rid = "r115-holder-release"
    ready_operation = operation(["p0"], 1)
    released: list[tuple[object, str]] = []
    empty_indices = object()

    def no_match(*_, failure_shape=None, **__) -> None:
        failure_shape.update(
            reason="node_exceeds_ready_prefix",
            ready_pages=1,
            path_nodes=1,
            path_pages=2,
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
        best_match_node=first,
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
    print("e44 r115 ready-prefix failure-shape smoke: passed")


if __name__ == "__main__":
    main()
