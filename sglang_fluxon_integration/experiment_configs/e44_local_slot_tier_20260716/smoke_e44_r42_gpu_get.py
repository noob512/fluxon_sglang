#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path

import torch

from fluxon_py import FluxonKvClientConfig, new_store
from fluxon_py.kvclient.kvclient_interface import PutOptionalArgs


PLAN_BLOB_MAGIC = 0x4658504C414E5631


def consume_ok(result: object, operation: str) -> object:
    if not result.is_ok():
        raise RuntimeError(f"{operation} failed: {result.unwrap_error()}")
    return result.unwrap()


def build_config(config_path: Path, instance_key: str) -> FluxonKvClientConfig:
    config_dict = FluxonKvClientConfig.from_file(str(config_path)).to_dict()
    config_dict["instance_key"] = instance_key
    config_dict["contribute_to_cluster_pool_size"] = {"dram": 0, "vram": {}}
    test_spec = config_dict.setdefault("test_spec_config", {})
    if not isinstance(test_spec, dict):
        raise TypeError("test_spec_config must be a mapping")
    # These clients exist only for a bounded Put/Get/Delete smoke. Starting an
    # OTLP exporter adds no evidence and can leave close() waiting after the
    # data-path checks have already completed.
    test_spec["disable_observability"] = True
    return FluxonKvClientConfig(config_dict)


def payload_bytes(size: int, seed: int) -> bytes:
    unit = bytes((seed + index * 17) % 251 for index in range(4096))
    repeats, tail = divmod(size, len(unit))
    return unit * repeats + unit[:tail]


def wait_ret_codes(future: object, expected: list[int], operation: str) -> None:
    result = future.wait()
    codes = consume_ok(result, operation)
    if list(codes) != expected:
        raise RuntimeError(
            f"{operation} returned unexpected codes: expected={expected} got={codes}"
        )


def plan_value_ptr(plan_ptr: int, expected_count: int) -> int:
    header = (ctypes.c_uint64 * 2).from_address(plan_ptr)
    if int(header[0]) != PLAN_BLOB_MAGIC or int(header[1]) != expected_count:
        raise RuntimeError(
            "invalid local-fast Put plan: "
            f"magic={int(header[0]):#x} count={int(header[1])}"
        )
    value_ptr = int((ctypes.c_uint64 * expected_count).from_address(plan_ptr + 16)[0])
    if value_ptr == 0:
        raise RuntimeError("local-fast Put plan returned a null value pointer")
    return value_ptr


def run_writer(args: argparse.Namespace) -> None:
    payload = payload_bytes(args.size, args.seed)
    store = consume_ok(
        new_store(build_config(args.config, args.instance_key)),
        "writer new_store",
    )
    plan_ptr = None
    try:
        plan_ptr = store.local_fast_put_start(
            [args.key],
            args.size,
            opts=PutOptionalArgs(
                reject_if_inflight_same_key=True,
                reject_if_exist_same_key=True,
                write_through=True,
                make_replica_task=False,
                make_replica_task_mask=[False],
                atomic_group_lens=[1],
            ),
        )
        ctypes.memmove(plan_value_ptr(plan_ptr, 1), payload, len(payload))
        future = store.local_fast_put_commit(plan_ptr)
        plan_ptr = None
        wait_ret_codes(future, [0], "writer local_fast_put_commit")
        print(
            json.dumps(
                {
                    "status": "written",
                    "key": args.key,
                    "size": args.size,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                },
                sort_keys=True,
            ),
            flush=True,
        )
        if args.hard_exit_after_success:
            os._exit(0)
    finally:
        if plan_ptr is not None:
            store.put_abort(plan_ptr)
        consume_ok(store.close(), "writer close")


def run_reader(args: argparse.Namespace) -> None:
    expected = payload_bytes(args.size, args.seed)
    expected_sha256 = hashlib.sha256(expected).hexdigest()
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
        "reader new_store",
    )
    registration = None
    handle = None
    handle_kind = None
    plan_ptr = None
    try:
        registration = consume_ok(
            store.register_gpu_buffer(
                staging.data_ptr(),
                int(staging.numel()),
                args.device,
            ),
            "reader register_gpu_buffer",
        )
        registration_id = registration.registration_id
        destination = registration.destination(
            staging.data_ptr(),
            int(staging.numel()),
        )
        handle = store.get_plan(
            [args.key],
            prefix_best_effort=False,
            atomic_group_lens=[1],
        )
        handle_kind = "plan"
        if not handle.gpu_result.all_hit or handle.gpu_result.transferable_len != 1:
            raise RuntimeError(
                f"GPU Get plan did not select the requested key: {handle.gpu_result}"
            )
        handle = store.execute_get_plan_gpu(
            handle,
            [destination],
            consume_prefix_len=1,
        )
        handle_kind = "gpu"
        gpu_handle = handle
        plan_ptr = store.get_transfer_gpu(gpu_handle, consume_prefix_len=1)
        terminal_timing = {
            "transfer_wall_us": getattr(gpu_handle, "transfer_wall_us", None),
            "finish_wait_us": getattr(gpu_handle, "finish_wait_us", None),
            "terminal_before_consume": getattr(
                gpu_handle, "terminal_before_consume", None
            ),
            "terminal_to_consume_us": getattr(
                gpu_handle, "terminal_to_consume_us", None
            ),
        }
        if args.require_terminal_timing:
            for field in (
                "transfer_wall_us",
                "finish_wait_us",
                "terminal_to_consume_us",
            ):
                value = terminal_timing[field]
                if type(value) is not int or value < 0:
                    raise AssertionError(
                        f"GPU Get terminal timing is invalid: {field}={value!r}"
                    )
            if type(terminal_timing["terminal_before_consume"]) is not bool:
                raise AssertionError(
                    "GPU Get terminal_before_consume is invalid: "
                    f"{terminal_timing['terminal_before_consume']!r}"
                )
        handle = None
        handle_kind = None
        torch.cuda.synchronize(args.device)
        actual = staging.cpu().numpy().tobytes()
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
                "GPU Get payload mismatch: "
                f"offset={mismatch} actual={actual[mismatch]} expected={expected[mismatch]} "
                f"actual_sha256={actual_sha256} expected_sha256={expected_sha256}"
            )
        store.release_views(plan_ptr)
        plan_ptr = None
        if args.hard_exit_after_success and registration is not None:
            consume_ok(
                store.unregister_gpu_buffer(registration),
                "reader unregister_gpu_buffer",
            )
            registration = None
        print(
            json.dumps(
                {
                    "status": "passed",
                    "key": args.key,
                    "size": args.size,
                    "registration_id": registration_id,
                    "sha256": actual_sha256,
                    "terminal_timing": terminal_timing,
                },
                sort_keys=True,
            ),
            flush=True,
        )
        if args.hard_exit_after_success:
            os._exit(0)
    finally:
        if plan_ptr is not None:
            store.release_views(plan_ptr)
        if handle is not None:
            if handle_kind == "plan":
                store.cancel_get_plan(handle)
            else:
                store.cancel_get_transfer_gpu(handle)
        if registration is not None:
            consume_ok(
                store.unregister_gpu_buffer(registration),
                "reader unregister_gpu_buffer",
            )
        consume_ok(store.close(), "reader close")


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="mode", required=True)
    for mode in ("writer", "reader"):
        subparser = subparsers.add_parser(mode)
        subparser.add_argument("--config", type=Path, required=True)
        subparser.add_argument("--instance-key", required=True)
        subparser.add_argument("--key", required=True)
        subparser.add_argument("--size", type=int, default=4 * 1024 * 1024)
        subparser.add_argument("--seed", type=int, default=73)
        subparser.add_argument("--hard-exit-after-success", action="store_true")
        if mode == "reader":
            subparser.add_argument("--device", type=int, default=0)
            subparser.add_argument(
                "--require-terminal-timing",
                action="store_true",
            )
    args = parser.parse_args()
    if args.size <= 0:
        raise ValueError("--size must be positive")
    if args.mode == "writer":
        run_writer(args)
    else:
        run_reader(args)


if __name__ == "__main__":
    main()
