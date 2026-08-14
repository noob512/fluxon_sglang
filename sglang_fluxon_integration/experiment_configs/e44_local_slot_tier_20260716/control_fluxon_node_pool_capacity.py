#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import threading
import time
from typing import Any

from fluxon_py import FluxonKvClientConfig, new_store


RPC_PATH = "fluxon_kv/node_pool_capacity"
RPC_TIMEOUT_MS = 10_000


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
    # A short-lived capacity controller must not start metrics/OTLP exporters. Apart from being
    # unnecessary, their shutdown join can outlive an otherwise completed control operation.
    test_spec["disable_observability"] = True
    return FluxonKvClientConfig(config_dict)


def get_payload(owner_node_id: str) -> dict[str, Any]:
    return {"operation": "get", "owner_node_id": owner_node_id}


def set_payload(
    owner_node_id: str,
    owner_node_start_time: int,
    capacity_epoch: int,
    active_capacity_bytes: int,
) -> dict[str, Any]:
    if active_capacity_bytes <= 0:
        raise ValueError("active capacity must be positive")
    return {
        "operation": "set_active",
        "owner_node_id": owner_node_id,
        "expected_owner_node_start_time": owner_node_start_time,
        "expected_capacity_epoch": capacity_epoch,
        "active_capacity_bytes": active_capacity_bytes,
    }


REQUIRED_RESPONSE_FIELDS = {
    "owner_node_id",
    "owner_node_start_time",
    "physical_capacity_bytes",
    "active_capacity_bytes",
    "used_capacity_bytes",
    "parked_capacity_bytes",
    "draining_capacity_bytes",
    "available_capacity_bytes",
    "capacity_epoch",
    "ring_b_effective_capacity_bytes",
    "ring_b_pending_reclaim_bytes",
    "settled",
}


def rpc_call(store: object, master_node_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    future = consume_ok(
        store.rpc_call_bytes(
            master_node_id,
            RPC_PATH,
            encoded,
            timeout_ms=RPC_TIMEOUT_MS,
        ),
        "capacity controller rpc_call_bytes",
    )
    raw_response = consume_ok(future.wait(), "capacity controller RPC wait")
    response = json.loads(bytes(raw_response).decode("utf-8"))
    missing = sorted(REQUIRED_RESPONSE_FIELDS.difference(response))
    if missing:
        raise RuntimeError(f"capacity response is missing fields: {missing}")
    if response["owner_node_id"] != payload["owner_node_id"]:
        raise RuntimeError(
            "capacity response owner mismatch: "
            f"expected={payload['owner_node_id']} got={response['owner_node_id']}"
        )
    return response


def set_and_wait(store: object, args: argparse.Namespace) -> dict[str, Any]:
    before = rpc_call(store, args.master_node_id, get_payload(args.owner_node_id))
    initiated = rpc_call(
        store,
        args.master_node_id,
        set_payload(
            args.owner_node_id,
            int(before["owner_node_start_time"]),
            int(before["capacity_epoch"]),
            args.active_capacity_bytes,
        ),
    )
    expected_start_time = int(initiated["owner_node_start_time"])
    expected_epoch = int(initiated["capacity_epoch"])
    deadline = time.monotonic() + args.settle_timeout_seconds
    polls = 0
    final = initiated
    while not bool(final["settled"]):
        if time.monotonic() >= deadline:
            raise TimeoutError(
                "node pool capacity did not settle before timeout: "
                f"owner={args.owner_node_id} final={json.dumps(final, sort_keys=True)}"
            )
        time.sleep(args.poll_interval_seconds)
        final = rpc_call(store, args.master_node_id, get_payload(args.owner_node_id))
        polls += 1
        if int(final["owner_node_start_time"]) != expected_start_time:
            raise RuntimeError("owner generation changed while waiting for capacity settle")
        if int(final["capacity_epoch"]) != expected_epoch:
            raise RuntimeError("capacity epoch changed while waiting for capacity settle")
        if int(final["active_capacity_bytes"]) != args.active_capacity_bytes:
            raise RuntimeError("active capacity changed while waiting for capacity settle")
    return {
        "operation": "set_wait",
        "before": before,
        "initiated": initiated,
        "final": final,
        "polls": polls,
    }


def close_store_bounded(store: object, timeout_seconds: float, success: bool) -> None:
    errors: list[BaseException] = []

    def close_worker() -> None:
        try:
            consume_ok(store.close(), "capacity controller close")
        except BaseException as error:  # Preserve the original Python/Rust close failure.
            errors.append(error)

    worker = threading.Thread(
        target=close_worker,
        name="capacity-controller-close",
        daemon=True,
    )
    worker.start()
    worker.join(timeout_seconds)
    if worker.is_alive():
        print(
            "capacity controller close exceeded "
            f"{timeout_seconds:.3f}s; forcing process exit after response publication",
            file=sys.stderr,
            flush=True,
        )
        os._exit(0 if success else 1)
    if errors:
        raise errors[0]


def publish_response(response: dict[str, Any], response_file: Path | None) -> None:
    encoded = json.dumps(response, sort_keys=True)
    if response_file is not None:
        response_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = response_file.with_name(f".{response_file.name}.{os.getpid()}.tmp")
        temporary.write_text(encoded + "\n", encoding="utf-8")
        temporary.replace(response_file)
    print(encoded, flush=True)


def run(args: argparse.Namespace) -> None:
    store = consume_ok(
        new_store(build_config(args.config, args.instance_key)),
        "capacity controller new_store",
    )
    response_published = False
    try:
        if args.operation == "get":
            response: dict[str, Any] = rpc_call(
                store, args.master_node_id, get_payload(args.owner_node_id)
            )
        elif args.operation == "set":
            response = rpc_call(
                store,
                args.master_node_id,
                set_payload(
                    args.owner_node_id,
                    args.expected_owner_node_start_time,
                    args.expected_capacity_epoch,
                    args.active_capacity_bytes,
                ),
            )
        else:
            response = set_and_wait(store, args)
        publish_response(response, args.response_file)
        response_published = True
    finally:
        close_store_bounded(store, args.close_timeout_seconds, response_published)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--instance-key", required=True)
    parser.add_argument("--master-node-id", required=True)
    parser.add_argument("--owner-node-id", required=True)
    parser.add_argument("--response-file", type=Path)
    parser.add_argument("--close-timeout-seconds", type=float, default=20.0)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    subparsers.add_parser("get")
    set_parser = subparsers.add_parser("set")
    set_parser.add_argument("--expected-owner-node-start-time", type=int, required=True)
    set_parser.add_argument("--expected-capacity-epoch", type=int, required=True)
    set_parser.add_argument("--active-capacity-bytes", type=int, required=True)
    wait_parser = subparsers.add_parser("set-wait")
    wait_parser.add_argument("--active-capacity-bytes", type=int, required=True)
    wait_parser.add_argument("--settle-timeout-seconds", type=float, default=900.0)
    wait_parser.add_argument("--poll-interval-seconds", type=float, default=1.0)
    args = parser.parse_args()
    if getattr(args, "settle_timeout_seconds", 1.0) <= 0:
        parser.error("--settle-timeout-seconds must be positive")
    if getattr(args, "poll_interval_seconds", 1.0) <= 0:
        parser.error("--poll-interval-seconds must be positive")
    if args.close_timeout_seconds <= 0:
        parser.error("--close-timeout-seconds must be positive")
    run(args)


if __name__ == "__main__":
    main()
