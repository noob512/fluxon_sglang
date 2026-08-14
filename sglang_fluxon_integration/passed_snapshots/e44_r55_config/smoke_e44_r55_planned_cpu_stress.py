#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
from pathlib import Path

from fluxon_py import new_store
from fluxon_py.kvclient.kvclient_interface import PutOptionalArgs

from smoke_e44_r42_gpu_get import (
    PLAN_BLOB_MAGIC,
    build_config,
    consume_ok,
    payload_bytes,
    wait_ret_codes,
)


def keys_for(prefix: str, count: int) -> list[str]:
    return [f"{prefix}_{index:04d}" for index in range(count)]


def plan_value_ptrs(plan_ptr: int, expected_count: int) -> tuple[int, ...]:
    if plan_ptr <= 0 or expected_count <= 0:
        raise ValueError(
            f"invalid source plan request: ptr={plan_ptr} count={expected_count}"
        )
    header = (ctypes.c_uint64 * 2).from_address(plan_ptr)
    if int(header[0]) != PLAN_BLOB_MAGIC or int(header[1]) != expected_count:
        raise RuntimeError(
            "invalid source plan: "
            f"magic={int(header[0]):#x} count={int(header[1])} "
            f"expected={expected_count}"
        )
    values = (ctypes.c_uint64 * expected_count).from_address(plan_ptr + 16)
    pointers = tuple(int(value) for value in values)
    if any(pointer <= 0 for pointer in pointers):
        raise RuntimeError("source plan contains a null pointer")
    return pointers


def run_writer(args: argparse.Namespace) -> None:
    keys = keys_for(args.key_prefix, args.count)
    payload = payload_bytes(args.size, args.seed)
    payload_sha256 = hashlib.sha256(payload).hexdigest()
    store = consume_ok(
        new_store(build_config(args.config, args.instance_key)),
        "stress writer new_store",
    )
    plan_ptr = None
    try:
        plan_ptr = store.local_fast_put_start(
            keys,
            args.size,
            opts=PutOptionalArgs(
                reject_if_inflight_same_key=True,
                reject_if_exist_same_key=True,
                write_through=True,
                make_replica_task=False,
                make_replica_task_mask=[False] * args.count,
                atomic_group_lens=[1] * args.count,
            ),
        )
        for pointer in plan_value_ptrs(plan_ptr, args.count):
            ctypes.memmove(pointer, payload, len(payload))
        future = store.local_fast_put_commit(plan_ptr)
        plan_ptr = None
        wait_ret_codes(future, [0] * args.count, "stress writer commit")
        print(
            json.dumps(
                {
                    "status": "written",
                    "count": args.count,
                    "item_size": args.size,
                    "total_bytes": args.count * args.size,
                    "payload_sha256": payload_sha256,
                    "first_key": keys[0],
                    "last_key": keys[-1],
                },
                sort_keys=True,
            ),
            flush=True,
        )
    finally:
        if plan_ptr is not None:
            store.put_abort(plan_ptr)
        consume_ok(store.close(), "stress writer close")


def run_reader(args: argparse.Namespace) -> None:
    keys = keys_for(args.key_prefix, args.count)
    payload = payload_bytes(args.size, args.seed)
    payload_sha256 = hashlib.sha256(payload).hexdigest()
    store = consume_ok(
        new_store(build_config(args.config, args.instance_key)),
        "stress reader new_store",
    )
    handle = None
    handle_kind = None
    plan_ptr = None
    try:
        handle = store.get_plan(
            keys,
            prefix_best_effort=False,
            atomic_group_lens=[1] * args.count,
        )
        handle_kind = "plan"
        if not handle.result.all_hit or handle.result.transferable_len != args.count:
            raise RuntimeError(
                "planned CPU stress did not select every key: "
                f"result={handle.result} expected={args.count}"
            )
        handle = store.execute_get_plan_cpu(
            handle,
            consume_prefix_len=args.count,
            concurrency=args.concurrency,
        )
        handle_kind = "cpu"
        plan_ptr = store.get_transfer(handle, consume_prefix_len=args.count)
        handle = None
        handle_kind = None
        for index, pointer in enumerate(plan_value_ptrs(plan_ptr, args.count)):
            actual_sha256 = hashlib.sha256(
                ctypes.string_at(pointer, args.size)
            ).hexdigest()
            if actual_sha256 != payload_sha256:
                raise AssertionError(
                    "planned CPU stress payload mismatch: "
                    f"index={index} key={keys[index]} actual={actual_sha256} "
                    f"expected={payload_sha256}"
                )
        store.release_views(plan_ptr)
        plan_ptr = None
        print(
            json.dumps(
                {
                    "status": "passed",
                    "path": "planned_cpu_stress",
                    "count": args.count,
                    "item_size": args.size,
                    "total_bytes": args.count * args.size,
                    "concurrency": args.concurrency,
                    "payload_sha256": payload_sha256,
                    "first_key": keys[0],
                    "last_key": keys[-1],
                },
                sort_keys=True,
            ),
            flush=True,
        )
    finally:
        if plan_ptr is not None:
            store.release_views(plan_ptr)
        if handle is not None:
            if handle_kind == "plan":
                store.cancel_get_plan(handle)
            else:
                store.cancel_get_transfer(handle)
        consume_ok(store.close(), "stress reader close")


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="mode", required=True)
    for mode in ("writer", "reader"):
        subparser = subparsers.add_parser(mode)
        subparser.add_argument("--config", type=Path, required=True)
        subparser.add_argument("--instance-key", required=True)
        subparser.add_argument("--key-prefix", required=True)
        subparser.add_argument("--count", type=int, default=228)
        subparser.add_argument("--size", type=int, default=4_718_592)
        subparser.add_argument("--seed", type=int, default=73)
        if mode == "reader":
            subparser.add_argument("--concurrency", type=int, default=32)
    args = parser.parse_args()
    if args.count <= 0 or args.size <= 0:
        raise ValueError("--count and --size must be positive")
    if args.mode == "reader" and args.concurrency <= 0:
        raise ValueError("--concurrency must be positive")
    if args.mode == "writer":
        run_writer(args)
    else:
        run_reader(args)


if __name__ == "__main__":
    main()
