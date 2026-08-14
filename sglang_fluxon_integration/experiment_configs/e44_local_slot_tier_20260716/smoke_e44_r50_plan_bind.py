#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import traceback
from pathlib import Path

from fluxon_py import new_store

from smoke_e44_r42_gpu_get import (
    build_config,
    consume_ok,
    payload_bytes,
    plan_value_ptr,
)


def run_cpu_reader(args: argparse.Namespace) -> None:
    expected = payload_bytes(args.size, args.seed)
    expected_sha256 = hashlib.sha256(expected).hexdigest()
    store = consume_ok(
        new_store(build_config(args.config, args.instance_key)),
        "CPU reader new_store",
    )
    handle = None
    handle_kind = None
    plan_ptr = None
    try:
        handle = store.get_plan(
            [args.key],
            prefix_best_effort=False,
            atomic_group_lens=[1],
        )
        handle_kind = "plan"
        if not handle.result.all_hit or handle.result.transferable_len != 1:
            raise RuntimeError(
                f"CPU Get plan did not select the requested key: {handle.result}"
            )
        handle = store.execute_get_plan_cpu(
            handle,
            consume_prefix_len=1,
        )
        handle_kind = "cpu"
        plan_ptr = store.get_transfer(handle, consume_prefix_len=1)
        handle = None
        handle_kind = None
        actual = ctypes.string_at(plan_value_ptr(plan_ptr, 1), args.size)
        actual_sha256 = hashlib.sha256(actual).hexdigest()
        if actual != expected:
            mismatch = next(
                index
                for index, (actual_byte, expected_byte) in enumerate(
                    zip(actual, expected)
                )
                if actual_byte != expected_byte
            )
            raise AssertionError(
                "CPU fallback payload mismatch: "
                f"offset={mismatch} actual={actual[mismatch]} "
                f"expected={expected[mismatch]} actual_sha256={actual_sha256} "
                f"expected_sha256={expected_sha256}"
            )
        store.release_views(plan_ptr)
        plan_ptr = None
        print(
            json.dumps(
                {
                "status": "passed",
                "path": "planned_cpu_fallback",
                "key": args.key,
                "size": args.size,
                "sha256": actual_sha256,
                },
                sort_keys=True,
            ),
            flush=True,
        )
        if args.hard_exit_after_success:
            os._exit(0)
    except BaseException as error:
        print(
            f"planned CPU fallback smoke failed before cleanup: {error!r}",
            flush=True,
        )
        traceback.print_exc()
        raise
    finally:
        if plan_ptr is not None:
            store.release_views(plan_ptr)
        if handle is not None:
            if handle_kind == "plan":
                store.cancel_get_plan(handle)
            else:
                store.cancel_get_transfer(handle)
        consume_ok(store.close(), "CPU reader close")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--instance-key", required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--size", type=int, default=4 * 1024 * 1024)
    parser.add_argument("--seed", type=int, default=73)
    parser.add_argument("--hard-exit-after-success", action="store_true")
    args = parser.parse_args()
    if args.size <= 0:
        raise ValueError("--size must be positive")
    run_cpu_reader(args)


if __name__ == "__main__":
    main()
