#!/usr/bin/env python3
"""Verify a remote-only Fluxon key through planned CPU fallback.

This reader intentionally never registers GPU memory.  It attaches to the
same live local owner used by one SGLang instance, pulls a key whose only
backing is the remote CPU owner into local host DRAM, and compares every byte.
The normal SGLang path performs the subsequent local H2D copy.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import os
from pathlib import Path
from typing import Any

from fluxon_f_remote_gpu_probe import (
    build_probe_config,
    capture_execution_host,
    fail,
    finish_success,
    load_config,
    nested_dict,
    normalized_rdma_devices,
    payload_bytes,
    plan_value_ptr,
    sha256_file,
    validate_cluster,
    validate_external_owner_binding,
    validate_readiness_audit_declaration,
)
from fluxon_py import new_store


SCHEMA = "fluxon_f_remote_host_smoke_record_v1"


def consume_store_result(result: object, operation: str) -> Any:
    if not result.is_ok():
        fail(f"{operation} failed: {result.unwrap_error()}")
    return result.unwrap()


def run_reader(args: argparse.Namespace) -> None:
    config_sha256 = sha256_file(args.config)
    _, raw = load_config(args.config)
    if sha256_file(args.config) != config_sha256:
        fail("host reader config changed while it was being loaded")
    if raw.get("instance_key") != args.client_config_id:
        fail(
            "host reader config identity mismatch: "
            f"expected={args.client_config_id} actual={raw.get('instance_key')!r}"
        )
    contribution = nested_dict(
        raw.get("contribute_to_cluster_pool_size"),
        "contribute_to_cluster_pool_size",
    )
    if contribution.get("dram") != 0 or contribution.get("vram") not in ({}, None):
        fail("host reader config must have zero contribution")
    spec = validate_cluster(raw, args.cluster_name)
    validate_readiness_audit_declaration(raw, args.readiness_timeout_seconds)
    devices = normalized_rdma_devices(raw)
    if devices != sorted(args.expected_rdma_device):
        fail(
            "host reader RDMA device set mismatch: "
            f"expected={sorted(args.expected_rdma_device)} actual={devices}"
        )

    expected = payload_bytes(args.size, args.seed)
    expected_sha256 = hashlib.sha256(expected).hexdigest()
    execution_host = capture_execution_host(
        expected_hostname=args.expected_hostname,
        expected_ip=args.expected_ip,
    )
    store = consume_store_result(
        new_store(build_probe_config(raw, args.probe_instance_key)),
        "host reader new_store",
    )
    handle = None
    handle_kind = None
    plan_ptr = None
    try:
        local_owner_binding = validate_external_owner_binding(
            store=store,
            spec=spec,
            expected_owner_id=args.local_owner_id,
            expected_owner_node_start_time=args.local_owner_node_start_time,
            expected_cluster_name=args.cluster_name,
            expected_sub_cluster="sglang_owner",
            expected_segment_len=args.local_owner_segment_len,
            context="host reader GPU-node local owner",
        )
        handle = store.get_plan(
            [args.key], prefix_best_effort=False, atomic_group_lens=[1]
        )
        handle_kind = "plan"
        if not handle.result.all_hit or handle.result.transferable_len != 1:
            fail(f"host Get plan did not select the requested key: {handle.result}")
        remote_indices = [int(index) for index in handle.gpu_remote_indices]
        if remote_indices != [0]:
            fail(
                "host Get plan is not a one-item remote source: "
                f"remote_indices={remote_indices}"
            )
        handle = store.execute_get_plan_cpu(handle, consume_prefix_len=1)
        handle_kind = "host"
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
            fail(
                "planned CPU fallback payload mismatch: "
                f"offset={mismatch} actual={actual[mismatch]} "
                f"expected={expected[mismatch]} actual_sha256={actual_sha256} "
                f"expected_sha256={expected_sha256}"
            )
        store.release_views(plan_ptr)
        plan_ptr = None
        local_owner_binding_after_io = validate_external_owner_binding(
            store=store,
            spec=spec,
            expected_owner_id=args.local_owner_id,
            expected_owner_node_start_time=args.local_owner_node_start_time,
            expected_cluster_name=args.cluster_name,
            expected_sub_cluster="sglang_owner",
            expected_segment_len=args.local_owner_segment_len,
            context="host reader GPU-node local owner after Get",
        )
        if local_owner_binding_after_io != local_owner_binding:
            fail("host reader local-owner binding changed across Get")
        if sha256_file(args.config) != config_sha256:
            fail("host reader config changed during Get")
        finish_success(
            args,
            {
                "schema": SCHEMA,
                "mode": "reader_host",
                "status": "passed",
                "cluster_name": args.cluster_name,
                "probe_instance_key": args.probe_instance_key,
                "client_config_id": args.client_config_id,
                "client_node_start_time": args.client_node_start_time,
                "config_path": str(args.config),
                "config_sha256": config_sha256,
                "bound_local_owner": local_owner_binding,
                "local_owner_binding_revalidated_after_io": True,
                "execution_host": execution_host,
                "planned_source_scope": "remote_from_bound_local_owner",
                "rdma_devices": devices,
                "key": args.key,
                "size": args.size,
                "seed": args.seed,
                "expected_sha256": expected_sha256,
                "actual_sha256": actual_sha256,
                "remote_indices": remote_indices,
                "transfer_path": "planned_cpu_fallback",
                "gpu_buffer_registered": False,
                "gdr_enabled": False,
                "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
                "readiness_declaration_scope": "audit_only_not_enforcement",
            },
        )
    finally:
        if plan_ptr is not None:
            store.release_views(plan_ptr)
        if handle is not None:
            if handle_kind == "plan":
                store.cancel_get_plan(handle)
            else:
                store.cancel_get_transfer(handle)
        consume_store_result(store.close(), "host reader close")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--cluster-name", required=True)
    parser.add_argument("--probe-instance-key", required=True)
    parser.add_argument("--expected-hostname", required=True)
    parser.add_argument("--expected-ip", required=True)
    parser.add_argument("--expected-rdma-device", action="append", required=True)
    parser.add_argument("--readiness-timeout-seconds", type=int, default=300)
    parser.add_argument("--key", required=True)
    parser.add_argument("--size", type=int, default=4_718_592)
    parser.add_argument("--seed", type=int, default=73)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--hard-exit-after-success", action="store_true")
    parser.add_argument("--client-config-id", required=True)
    parser.add_argument("--client-node-start-time", type=int, required=True)
    parser.add_argument("--local-owner-id", required=True)
    parser.add_argument("--local-owner-node-start-time", type=int, required=True)
    parser.add_argument("--local-owner-segment-len", type=int, required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.size <= 0:
        fail("--size must be positive")
    if not 0 <= args.seed <= 250:
        fail("--seed must be in [0, 250]")
    if args.readiness_timeout_seconds <= 0:
        fail("--readiness-timeout-seconds must be positive")
    if len(set(args.expected_rdma_device)) != len(args.expected_rdma_device):
        fail("--expected-rdma-device entries must be unique")
    for name in (
        "client_node_start_time",
        "local_owner_node_start_time",
        "local_owner_segment_len",
    ):
        if getattr(args, name) <= 0:
            fail(f"--{name.replace('_', '-')} must be positive")
    run_reader(args)


if __name__ == "__main__":
    main()
