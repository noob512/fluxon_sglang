#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import torch

from fluxon_py import FluxonKvClientConfig, new_store


def consume_ok(result: object, operation: str) -> object:
    if not result.is_ok():
        raise RuntimeError(f"{operation} failed: {result.unwrap_error()}")
    return result.unwrap()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Register and unregister one caller-owned Torch CUDA staging range."
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--size-mib", type=int, default=64)
    parser.add_argument("--instance-key", required=True)
    args = parser.parse_args()

    if args.size_mib <= 0:
        raise ValueError("--size-mib must be positive")

    config_dict = FluxonKvClientConfig.from_file(str(args.config)).to_dict()
    config_dict["instance_key"] = args.instance_key
    config_dict["contribute_to_cluster_pool_size"] = {"dram": 0, "vram": {}}
    config = FluxonKvClientConfig(config_dict)

    torch.cuda.set_device(args.device)
    size = args.size_mib * 1024 * 1024
    staging = torch.empty(size, dtype=torch.uint8, device=f"cuda:{args.device}")
    torch.cuda.synchronize(args.device)

    store = consume_ok(new_store(config), "new_store")
    registration = None
    started = time.perf_counter()
    try:
        registration = consume_ok(
            store.register_gpu_buffer(staging.data_ptr(), staging.numel(), args.device),
            "register_gpu_buffer",
        )
        destination = registration.destination(
            staging.data_ptr() + 4096,
            staging.numel() - 8192,
        )
        consume_ok(
            store.validate_gpu_destination(destination),
            "validate_gpu_destination",
        )
        print(
            json.dumps(
                {
                    "status": "registered",
                    "registration_id": registration.registration_id,
                    "ptr": registration.ptr,
                    "size": registration.size,
                    "device_id": registration.device_id,
                    "destination_ptr": destination.ptr,
                    "destination_capacity": destination.capacity,
                    "elapsed_ms": (time.perf_counter() - started) * 1000.0,
                },
                sort_keys=True,
            ),
            flush=True,
        )
    finally:
        if registration is not None:
            consume_ok(
                store.unregister_gpu_buffer(registration),
                "unregister_gpu_buffer",
            )
        consume_ok(store.close(), "close")


if __name__ == "__main__":
    main()
