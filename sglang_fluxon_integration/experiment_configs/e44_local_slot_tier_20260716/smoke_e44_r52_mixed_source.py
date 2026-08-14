#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import traceback
from pathlib import Path

import torch

from fluxon_py import new_store

from smoke_e44_r42_gpu_get import (
    PLAN_BLOB_MAGIC,
    build_config,
    consume_ok,
    payload_bytes,
)


def plan_value_ptrs(plan_ptr: int, expected_count: int) -> tuple[int, ...]:
    if plan_ptr <= 0 or expected_count <= 0:
        raise ValueError(
            f"invalid source plan request: ptr={plan_ptr} count={expected_count}"
        )
    header = (ctypes.c_uint64 * 2).from_address(plan_ptr)
    if int(header[0]) != PLAN_BLOB_MAGIC or int(header[1]) != expected_count:
        raise RuntimeError(
            "invalid mixed source plan: "
            f"magic={int(header[0]):#x} count={int(header[1])} "
            f"expected={expected_count}"
        )
    values = (ctypes.c_uint64 * expected_count).from_address(plan_ptr + 16)
    pointers = tuple(int(value) for value in values)
    if any(pointer <= 0 for pointer in pointers):
        raise RuntimeError(f"mixed source plan contains a null pointer: {pointers}")
    return pointers


def assert_payload(actual: bytes, expected: bytes, label: str) -> str:
    actual_sha256 = hashlib.sha256(actual).hexdigest()
    expected_sha256 = hashlib.sha256(expected).hexdigest()
    if actual != expected:
        mismatch = next(
            index
            for index, (actual_byte, expected_byte) in enumerate(zip(actual, expected))
            if actual_byte != expected_byte
        )
        raise AssertionError(
            f"{label} payload mismatch: offset={mismatch} "
            f"actual={actual[mismatch]} expected={expected[mismatch]} "
            f"actual_sha256={actual_sha256} expected_sha256={expected_sha256}"
        )
    return actual_sha256


def run(args: argparse.Namespace) -> None:
    local_expected = payload_bytes(args.size, args.local_seed)
    remote_expected = payload_bytes(args.size, args.remote_seed)
    torch.cuda.set_device(args.device)
    staging = torch.full(
        (args.size,),
        0xA5,
        dtype=torch.uint8,
        device=torch.device("cuda", args.device),
    )
    torch.cuda.synchronize(args.device)

    store = consume_ok(
        new_store(build_config(args.config, args.instance_key)),
        "mixed reader new_store",
    )
    registration = None
    handle = None
    handle_kind = None
    plan_ptr = None
    try:
        # A local-only request must finish without asking for any remote GPU
        # destination. Execute it through the CPU source-plan API and verify
        # the owner-local pointer byte for byte.
        handle = store.get_plan(
            [args.local_key],
            prefix_best_effort=False,
            atomic_group_lens=[1],
        )
        handle_kind = "plan"
        if (
            not handle.result.all_hit
            or handle.result.transferable_len != 1
            or tuple(handle.gpu_remote_indices) != ()
        ):
            raise RuntimeError(
                "local-only plan escaped into the remote subset: "
                f"result={handle.result} remote={handle.gpu_remote_indices}"
            )
        handle = store.execute_get_plan_cpu(handle, consume_prefix_len=1)
        handle_kind = "cpu"
        plan_ptr = store.get_transfer(handle, consume_prefix_len=1)
        handle = None
        handle_kind = None
        local_only_pointer = plan_value_ptrs(plan_ptr, 1)[0]
        local_only_sha256 = assert_payload(
            ctypes.string_at(local_only_pointer, args.size),
            local_expected,
            "local-only",
        )
        store.release_views(plan_ptr)
        plan_ptr = None

        # Mixed order is intentional: the first source must stay owner-local
        # CPU memory, while only the second (remote) source consumes a GPU
        # destination. The returned plan must preserve that original order.
        registration = consume_ok(
            store.register_gpu_buffer(
                staging.data_ptr(),
                int(staging.numel()),
                args.device,
            ),
            "mixed reader register_gpu_buffer",
        )
        destination = registration.destination(
            staging.data_ptr(),
            int(staging.numel()),
        )
        handle = store.get_plan(
            [args.local_key, args.remote_key],
            prefix_best_effort=False,
            atomic_group_lens=[1, 1],
        )
        handle_kind = "plan"
        if (
            not handle.result.all_hit
            or not handle.gpu_result.all_hit
            or handle.result.transferable_len != 2
            or handle.gpu_result.transferable_len != 2
            or tuple(handle.gpu_remote_indices) != (1,)
        ):
            raise RuntimeError(
                "mixed plan did not separate local and remote positions: "
                f"cpu={handle.result} gpu={handle.gpu_result} "
                f"remote={handle.gpu_remote_indices}"
            )
        handle = store.execute_get_plan_gpu(
            handle,
            [destination],
            consume_prefix_len=2,
        )
        handle_kind = "gpu"
        if tuple(handle.remote_indices) != (1,):
            raise RuntimeError(
                f"mixed execute changed remote positions: {handle.remote_indices}"
            )
        plan_ptr = store.get_transfer_gpu(handle, consume_prefix_len=2)
        handle = None
        handle_kind = None
        source_ptrs = plan_value_ptrs(plan_ptr, 2)
        if source_ptrs[1] != staging.data_ptr():
            raise RuntimeError(
                "remote source did not use the reserved GPU destination: "
                f"plan={source_ptrs[1]:#x} staging={staging.data_ptr():#x}"
            )
        if source_ptrs[0] == staging.data_ptr():
            raise RuntimeError("local source incorrectly consumed the remote GPU slot")
        mixed_local_sha256 = assert_payload(
            ctypes.string_at(source_ptrs[0], args.size),
            local_expected,
            "mixed-local",
        )
        torch.cuda.synchronize(args.device)
        mixed_remote_sha256 = assert_payload(
            staging.cpu().numpy().tobytes(),
            remote_expected,
            "mixed-remote",
        )
        store.release_views(plan_ptr)
        plan_ptr = None
        consume_ok(
            store.unregister_gpu_buffer(registration),
            "mixed reader unregister_gpu_buffer",
        )
        registration = None
        print(
            json.dumps(
                {
                    "status": "passed",
                    "path": "local_first_remote_only_gpu_decision",
                    "local_key": args.local_key,
                    "remote_key": args.remote_key,
                    "remote_indices": [1],
                    "gpu_destinations": 1,
                    "local_only_sha256": local_only_sha256,
                    "mixed_local_sha256": mixed_local_sha256,
                    "mixed_remote_sha256": mixed_remote_sha256,
                },
                sort_keys=True,
            ),
            flush=True,
        )
        if args.hard_exit_after_success:
            os._exit(0)
    except BaseException as error:
        print(f"mixed source smoke failed before cleanup: {error!r}", flush=True)
        traceback.print_exc()
        raise
    finally:
        if plan_ptr is not None:
            store.release_views(plan_ptr)
        if handle is not None:
            if handle_kind == "plan":
                store.cancel_get_plan(handle)
            elif handle_kind == "gpu":
                store.cancel_get_transfer_gpu(handle)
            else:
                store.cancel_get_transfer(handle)
        if registration is not None:
            consume_ok(
                store.unregister_gpu_buffer(registration),
                "mixed reader unregister_gpu_buffer",
            )
        consume_ok(store.close(), "mixed reader close")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--instance-key", required=True)
    parser.add_argument("--local-key", required=True)
    parser.add_argument("--remote-key", required=True)
    parser.add_argument("--size", type=int, default=4_718_592)
    parser.add_argument("--local-seed", type=int, default=41)
    parser.add_argument("--remote-seed", type=int, default=73)
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--hard-exit-after-success", action="store_true")
    args = parser.parse_args()
    if args.size <= 0:
        raise ValueError("--size must be positive")
    if args.local_key == args.remote_key:
        raise ValueError("local and remote keys must differ")
    run(args)


if __name__ == "__main__":
    main()
