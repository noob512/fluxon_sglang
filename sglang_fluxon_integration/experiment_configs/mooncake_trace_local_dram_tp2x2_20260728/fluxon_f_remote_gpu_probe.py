#!/usr/bin/env python3
"""Controlled remote-owner write and GPU-read probe for Fluxon F.

The writer attaches to the CPU remote owner's *live shared bundle* and
publishes one key without replication.  The reader attaches to the live local
GPU owner through one port-scoped external config, proves the planned item is
remote, transfers it into registered CUDA memory, and compares every byte.
The shared.json bytes and the runtime mapping returned by Fluxon must agree on
the owner generation; command-line identity fields alone are never source
proof.  Each mode writes an atomic JSON evidence file before an optional hard
exit used to isolate the known r96 close-lifecycle hang.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import socket
import subprocess
from pathlib import Path
from typing import Any, NoReturn

from fluxon_py import FluxonKvClientConfig, new_store
from fluxon_py.kvclient.kvclient_interface import PutOptionalArgs


SCHEMA = "fluxon_f_remote_gpu_probe_record_v2"
PLAN_BLOB_MAGIC = 0x4658504C414E5631


def fail(message: str) -> NoReturn:
    raise RuntimeError(message)


def consume_ok(result: object, operation: str) -> object:
    if not result.is_ok():
        fail(f"{operation} failed: {result.unwrap_error()}")
    return result.unwrap()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def write_json_atomic(path: Path, value: Any) -> None:
    payload = canonical_json(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def payload_bytes(size: int, seed: int) -> bytes:
    unit = bytes((seed + index * 17) % 251 for index in range(4096))
    repeats, tail = divmod(size, len(unit))
    return unit * repeats + unit[:tail]


def load_config(path: Path) -> tuple[FluxonKvClientConfig, dict[str, Any]]:
    config = FluxonKvClientConfig.from_file(str(path))
    raw = config.to_dict()
    if not isinstance(raw, dict):
        fail(f"config did not normalize to a mapping: {path}")
    return config, raw


def nested_dict(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail(f"{context} must be a mapping")
    return value


def normalized_rdma_devices(config: dict[str, Any]) -> list[str]:
    test_spec = nested_dict(config.get("test_spec_config"), "test_spec_config")
    raw = test_spec.get("rdma_device_names")
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        fail("test_spec_config.rdma_device_names must be an explicit string list")
    devices = sorted({item.strip() for item in raw if item.strip()})
    if not devices:
        fail("test_spec_config.rdma_device_names must not be empty")
    return devices


def validate_readiness_audit_declaration(
    config: dict[str, Any], timeout_seconds: int
) -> None:
    """Validate the config declaration without treating it as a readiness gate."""

    test_spec = nested_dict(config.get("test_spec_config"), "test_spec_config")
    if test_spec.get("transport_mode") != "transfer_with_rpc":
        fail("probe config must use transport_mode=transfer_with_rpc")
    actual = test_spec.get("require_transfer_rpc_fast_path_ready_timeout_seconds")
    if actual != timeout_seconds:
        fail(
            "probe config readiness declaration mismatch: "
            f"expected={timeout_seconds} actual={actual!r}"
        )


def validate_cluster(config: dict[str, Any], expected_cluster: str) -> dict[str, Any]:
    spec = nested_dict(config.get("fluxonkv_spec"), "fluxonkv_spec")
    if spec.get("cluster_name") != expected_cluster:
        fail(
            "probe config cluster mismatch: "
            f"expected={expected_cluster} actual={spec.get('cluster_name')!r}"
        )
    return spec


def build_probe_config(config: dict[str, Any], probe_instance_key: str) -> FluxonKvClientConfig:
    """Derive a minimal zero-contribution config from an owner or external config.

    An owner config cannot be converted by changing only its contribution: owner-only
    fields such as ``sub_cluster``, ``large_file_paths`` and the local-reserve contract
    are forbidden in zero-contribution mode.  Keep only fields needed to attach to the
    owner's published shared bundle and to use the same transport declaration.
    """

    spec = nested_dict(config.get("fluxonkv_spec"), "fluxonkv_spec")
    test_spec = nested_dict(config.get("test_spec_config"), "test_spec_config")
    runtime_test_spec: dict[str, Any] = {}
    for key in (
        "disable_observability",
        "disable_local_ipc",
        "disable_crossowner_ipc",
        "enable_iceoryx_logs",
        "iceoryx_external_busy_poll",
        "iceoryx_owner_client_busy_poll",
        "short_circuit_put_payload_path",
        "transport_mode",
        "tcp_thread_reactor_shard_count",
        "tcp_thread_bulk_lane_count",
        "tcp_thread_control_lane_count",
        "user_rpc_sync_handler_thread_count",
        "require_transfer_rpc_fast_path_ready_timeout_seconds",
        "rdma_device_names",
    ):
        if key in test_spec:
            runtime_test_spec[key] = test_spec[key]
    runtime: dict[str, Any] = {
        "instance_key": probe_instance_key,
        "contribute_to_cluster_pool_size": {"dram": 0, "vram": {}},
        "fluxonkv_spec": {
            "cluster_name": spec.get("cluster_name"),
            "share_mem_path": spec.get("share_mem_path"),
        },
        "protocol": dict(nested_dict(config.get("protocol"), "protocol")),
        "test_spec_config": runtime_test_spec,
    }
    return FluxonKvClientConfig(runtime)


def positive_int(value: Any, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        fail(f"{context} must be a positive integer: {value!r}")
    return value


def read_shared_json(path: Path) -> tuple[dict[str, Any], str]:
    try:
        payload = path.read_bytes()
        value = json.loads(payload)
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read live owner shared.json {path}: {exc}")
    if not isinstance(value, dict):
        fail(f"live owner shared.json must contain an object: {path}")
    return value, hashlib.sha256(payload).hexdigest()


def process_start_time_ticks(pid: int) -> int:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
        after_comm = raw.rsplit(")", 1)[1].split()
        return positive_int(int(after_comm[19]), f"process {pid} start_time_ticks")
    except (OSError, ValueError, IndexError) as exc:
        fail(f"cannot read process identity for pid {pid}: {exc}")


def capture_execution_host(
    *, expected_hostname: str, expected_ip: str
) -> dict[str, Any]:
    actual_hostname = socket.gethostname()
    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(actual_hostname, None, socket.AF_INET)
        }
    except socket.gaierror:
        addresses = set()
    try:
        hostname_i = subprocess.run(
            ["hostname", "-I"],
            check=True,
            text=True,
            capture_output=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        fail(f"cannot capture execution-host addresses: {exc}")
    addresses.update(hostname_i.stdout.split())
    if actual_hostname != expected_hostname:
        fail(
            "probe execution hostname mismatch: "
            f"expected={expected_hostname} actual={actual_hostname}"
        )
    if expected_ip not in addresses:
        fail(
            f"probe execution IP mismatch: expected={expected_ip} "
            f"actual={sorted(addresses)}"
        )
    try:
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(
            encoding="ascii"
        ).strip()
    except OSError as exc:
        fail(f"cannot read execution-host boot_id: {exc}")
    if len(boot_id) != 36:
        fail(f"invalid execution-host boot_id: {boot_id!r}")
    return {
        "hostname": actual_hostname,
        "expected_hostname": expected_hostname,
        "ips": sorted(addresses),
        "expected_ip": expected_ip,
        "boot_id": boot_id,
        "pid1_start_time_ticks": process_start_time_ticks(1),
        "pid": os.getpid(),
        "process_start_time_ticks": process_start_time_ticks(os.getpid()),
    }


def validate_external_owner_binding(
    *,
    store: object,
    spec: dict[str, Any],
    expected_owner_id: str,
    expected_owner_node_start_time: int,
    expected_cluster_name: str,
    expected_sub_cluster: str,
    expected_segment_len: int | None,
    context: str,
) -> dict[str, Any]:
    """Bind a probe to owner-published bytes and Fluxon's live mapped owner."""

    raw_share_mem_path = spec.get("share_mem_path")
    if not isinstance(raw_share_mem_path, str) or not raw_share_mem_path.strip():
        fail(f"{context} fluxonkv_spec.share_mem_path must be explicit")
    share_mem_root = Path(raw_share_mem_path)
    if not share_mem_root.is_absolute():
        fail(f"{context} share_mem_path must be absolute: {share_mem_root}")
    # Rust's verified config always appends cluster_name to the configured root.
    # Binding to the raw root would inspect the wrong directory and could not prove
    # which live mmap the probe actually attached to.
    share_mem_path = share_mem_root / expected_cluster_name
    try:
        canonical_share_mem_path = share_mem_path.resolve(strict=True)
    except OSError as exc:
        fail(f"{context} share_mem_path is not live: {share_mem_path}: {exc}")

    segments = store.wait_local_segments_ready()
    if not isinstance(segments, list) or len(segments) != 1:
        fail(
            f"{context} runtime binding must expose exactly one owner segment: "
            f"{segments!r}"
        )
    runtime = segments[0]
    if not isinstance(runtime, dict):
        fail(f"{context} runtime owner segment must be a mapping")
    if runtime.get("segment_label") != "external_owner:0":
        fail(
            f"{context} runtime segment is not an external-owner binding: "
            f"{runtime.get('segment_label')!r}"
        )
    if runtime.get("node_id") != expected_owner_id:
        fail(
            f"{context} runtime owner mismatch: expected={expected_owner_id} "
            f"actual={runtime.get('node_id')!r}"
        )
    runtime_generation = positive_int(runtime.get("generation"), f"{context} generation")
    if runtime_generation != expected_owner_node_start_time:
        fail(
            f"{context} runtime owner generation mismatch: "
            f"expected={expected_owner_node_start_time} actual={runtime_generation}"
        )
    runtime_len = positive_int(runtime.get("len"), f"{context} runtime segment len")
    positive_int(runtime.get("write_ptr"), f"{context} runtime write_ptr")
    positive_int(runtime.get("read_ptr"), f"{context} runtime read_ptr")
    if expected_segment_len is not None and runtime_len != expected_segment_len:
        fail(
            f"{context} runtime segment length mismatch: "
            f"expected={expected_segment_len} actual={runtime_len}"
        )

    shared_json_path = canonical_share_mem_path / "shared.json"
    shared, shared_sha256 = read_shared_json(shared_json_path)
    if shared.get("owner_id") != expected_owner_id:
        fail(
            f"{context} shared.json owner mismatch: expected={expected_owner_id} "
            f"actual={shared.get('owner_id')!r}"
        )
    shared_generation = positive_int(
        shared.get("node_start_time"), f"{context} shared.json node_start_time"
    )
    if shared_generation != runtime_generation:
        fail(
            f"{context} shared.json/runtime generation mismatch: "
            f"shared={shared_generation} runtime={runtime_generation}"
        )
    shared_len = positive_int(shared.get("segment_len"), f"{context} shared.json segment_len")
    if shared_len != runtime_len:
        fail(
            f"{context} shared.json/runtime segment length mismatch: "
            f"shared={shared_len} runtime={runtime_len}"
        )
    if shared.get("segment_label") != "cpu:0":
        fail(f"{context} shared.json segment_label is not cpu:0")
    if shared.get("cluster_name") != expected_cluster_name:
        fail(f"{context} shared.json cluster mismatch")
    if shared.get("sub_cluster") != expected_sub_cluster:
        fail(
            f"{context} shared.json sub_cluster mismatch: "
            f"expected={expected_sub_cluster} actual={shared.get('sub_cluster')!r}"
        )
    raw_published_path = shared.get("share_mem_path")
    if not isinstance(raw_published_path, str) or not raw_published_path:
        fail(f"{context} shared.json share_mem_path is missing")
    try:
        published_path = Path(raw_published_path).resolve(strict=True)
    except OSError as exc:
        fail(f"{context} shared.json share_mem_path is not live: {exc}")
    if published_path != canonical_share_mem_path:
        fail(
            f"{context} shared.json/config share_mem_path mismatch: "
            f"shared={published_path} config={canonical_share_mem_path}"
        )
    mmap_path = canonical_share_mem_path / "mmap.file"
    try:
        mmap_len = mmap_path.stat().st_size
    except OSError as exc:
        fail(f"{context} cannot stat live owner mmap.file {mmap_path}: {exc}")
    if mmap_len != runtime_len:
        fail(
            f"{context} mmap.file/runtime length mismatch: "
            f"mmap={mmap_len} runtime={runtime_len}"
        )
    return {
        "proof_kind": "runtime_external_owner_shared_binding_v1",
        "node_id": expected_owner_id,
        "node_start_time": runtime_generation,
        "runtime_segment_label": "external_owner:0",
        "published_segment_label": "cpu:0",
        "segment_len": runtime_len,
        "configured_share_mem_root": str(share_mem_root),
        "share_mem_path": str(canonical_share_mem_path),
        "shared_json_path": str(shared_json_path),
        "shared_json_sha256": shared_sha256,
        "mmap_path": str(mmap_path),
        "mmap_size": mmap_len,
        "runtime_write_mapping_present": True,
        "runtime_read_mapping_present": True,
    }


def wait_ret_codes(future: object, expected: list[int], operation: str) -> None:
    codes = consume_ok(future.wait(), operation)
    if list(codes) != expected:
        fail(f"{operation} returned unexpected codes: expected={expected} got={codes}")


def plan_value_ptr(plan_ptr: int, expected_count: int) -> int:
    header = (ctypes.c_uint64 * 2).from_address(plan_ptr)
    if int(header[0]) != PLAN_BLOB_MAGIC or int(header[1]) != expected_count:
        fail(
            "invalid local-fast Put plan: "
            f"magic={int(header[0]):#x} count={int(header[1])}"
        )
    value_ptr = int((ctypes.c_uint64 * expected_count).from_address(plan_ptr + 16)[0])
    if value_ptr == 0:
        fail("local-fast Put plan returned a null value pointer")
    return value_ptr


def finish_success(args: argparse.Namespace, record: dict[str, Any]) -> None:
    write_json_atomic(args.evidence, record)
    print(json.dumps(record, sort_keys=True), flush=True)
    if args.hard_exit_after_success:
        os._exit(0)


def run_writer(args: argparse.Namespace) -> None:
    config_sha256 = sha256_file(args.config)
    _, raw = load_config(args.config)
    if sha256_file(args.config) != config_sha256:
        fail("writer config changed while it was being loaded")
    original_instance = raw.get("instance_key")
    if original_instance != args.source_owner_id:
        fail(
            "writer config is not the expected remote owner config: "
            f"expected={args.source_owner_id} actual={original_instance!r}"
        )
    contribution = nested_dict(
        raw.get("contribute_to_cluster_pool_size"), "contribute_to_cluster_pool_size"
    )
    dram = contribution.get("dram")
    if isinstance(dram, bool) or not isinstance(dram, int) or dram <= 0:
        fail("writer source config must be a contributing owner")
    spec = validate_cluster(raw, args.cluster_name)
    if spec.get("sub_cluster") != "remote_cache":
        fail(f"writer config is not remote_cache: {spec.get('sub_cluster')!r}")
    test_spec = nested_dict(raw.get("test_spec_config"), "test_spec_config")
    if test_spec.get("prefer_local_placement") is not True:
        fail("writer owner config must set prefer_local_placement=true")
    validate_readiness_audit_declaration(raw, args.readiness_timeout_seconds)
    devices = normalized_rdma_devices(raw)
    if devices != sorted(args.expected_rdma_device):
        fail(
            "writer RDMA device set mismatch: "
            f"expected={sorted(args.expected_rdma_device)} actual={devices}"
        )

    payload = payload_bytes(args.size, args.seed)
    payload_sha256 = hashlib.sha256(payload).hexdigest()
    execution_host = capture_execution_host(
        expected_hostname=args.expected_hostname,
        expected_ip=args.expected_ip,
    )
    store = consume_ok(
        new_store(build_probe_config(raw, args.probe_instance_key)),
        "writer new_store",
    )
    plan_ptr = None
    try:
        source_binding = validate_external_owner_binding(
            store=store,
            spec=spec,
            expected_owner_id=args.source_owner_id,
            expected_owner_node_start_time=args.source_owner_node_start_time,
            expected_cluster_name=args.cluster_name,
            expected_sub_cluster="remote_cache",
            expected_segment_len=dram,
            context="writer CPU remote owner",
        )
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
        source_binding_after_io = validate_external_owner_binding(
            store=store,
            spec=spec,
            expected_owner_id=args.source_owner_id,
            expected_owner_node_start_time=args.source_owner_node_start_time,
            expected_cluster_name=args.cluster_name,
            expected_sub_cluster="remote_cache",
            expected_segment_len=dram,
            context="writer CPU remote owner after Put",
        )
        if source_binding_after_io != source_binding:
            fail("writer CPU remote owner binding changed across Put")
        if sha256_file(args.config) != config_sha256:
            fail("writer config changed during Put")
        record = {
            "schema": SCHEMA,
            "mode": "writer",
            "status": "written",
            "cluster_name": args.cluster_name,
            "target_client_config_id": args.target_client_config_id,
            "probe_instance_key": args.probe_instance_key,
            "config_path": str(args.config),
            "config_sha256": config_sha256,
            "source_owner_id": args.source_owner_id,
            "source_owner_node_start_time": args.source_owner_node_start_time,
            "source_owner_sub_cluster": "remote_cache",
            "source_owner_configured_dram": dram,
            "source_binding": source_binding,
            "source_binding_revalidated_after_io": True,
            "execution_host": execution_host,
            "rdma_devices": devices,
            "key": args.key,
            "size": args.size,
            "seed": args.seed,
            "sha256": payload_sha256,
            "remote_only": True,
            "write_through": True,
            "make_replica_task": False,
            "make_replica_task_mask": [False],
            "atomic_group_lens": [1],
            "readiness_declaration_scope": "audit_only_not_enforcement",
        }
        finish_success(args, record)
    finally:
        if plan_ptr is not None:
            store.put_abort(plan_ptr)
        consume_ok(store.close(), "writer close")


def validate_terminal_timing(handle: object) -> dict[str, Any]:
    timing = {
        "transfer_wall_us": getattr(handle, "transfer_wall_us", None),
        "finish_wait_us": getattr(handle, "finish_wait_us", None),
        "terminal_before_consume": getattr(handle, "terminal_before_consume", None),
        "terminal_to_consume_us": getattr(handle, "terminal_to_consume_us", None),
    }
    for field in ("transfer_wall_us", "finish_wait_us", "terminal_to_consume_us"):
        value = timing[field]
        if type(value) is not int or value < 0:
            fail(f"GPU Get terminal timing is invalid: {field}={value!r}")
    if type(timing["terminal_before_consume"]) is not bool:
        fail(
            "GPU Get terminal_before_consume is invalid: "
            f"{timing['terminal_before_consume']!r}"
        )
    return timing


def run_reader(args: argparse.Namespace) -> None:
    import torch

    config_sha256 = sha256_file(args.config)
    _, raw = load_config(args.config)
    if sha256_file(args.config) != config_sha256:
        fail("reader config changed while it was being loaded")
    original_instance = raw.get("instance_key")
    if original_instance != args.client_config_id:
        fail(
            "reader config identity mismatch: "
            f"expected={args.client_config_id} actual={original_instance!r}"
        )
    contribution = nested_dict(
        raw.get("contribute_to_cluster_pool_size"), "contribute_to_cluster_pool_size"
    )
    if contribution.get("dram") != 0 or contribution.get("vram") not in ({}, None):
        fail("reader config must have zero contribution")
    spec = validate_cluster(raw, args.cluster_name)
    validate_readiness_audit_declaration(raw, args.readiness_timeout_seconds)
    devices = normalized_rdma_devices(raw)
    if devices != sorted(args.expected_rdma_device):
        fail(
            "reader RDMA device set mismatch: "
            f"expected={sorted(args.expected_rdma_device)} actual={devices}"
        )

    expected = payload_bytes(args.size, args.seed)
    expected_sha256 = hashlib.sha256(expected).hexdigest()
    execution_host = capture_execution_host(
        expected_hostname=args.expected_hostname,
        expected_ip=args.expected_ip,
    )
    torch.cuda.set_device(args.cuda_device)
    staging = torch.full(
        (args.size,),
        0xA5,
        dtype=torch.uint8,
        device=torch.device("cuda", args.cuda_device),
    )
    torch.cuda.synchronize(args.cuda_device)

    store = consume_ok(
        new_store(build_probe_config(raw, args.probe_instance_key)),
        "reader new_store",
    )
    registration = None
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
            context="reader GPU local owner",
        )
        registration = consume_ok(
            store.register_gpu_buffer(
                staging.data_ptr(), int(staging.numel()), args.cuda_device
            ),
            "reader register_gpu_buffer",
        )
        registration_id = int(registration.registration_id)
        destination = registration.destination(
            staging.data_ptr(), int(staging.numel())
        )
        handle = store.get_plan(
            [args.key], prefix_best_effort=False, atomic_group_lens=[1]
        )
        handle_kind = "plan"
        if not handle.gpu_result.all_hit or handle.gpu_result.transferable_len != 1:
            fail(f"GPU Get plan did not select the requested key: {handle.gpu_result}")
        remote_indices = [int(index) for index in handle.gpu_remote_indices]
        if remote_indices != [0]:
            fail(
                "GPU Get plan is not a one-item remote source: "
                f"gpu_remote_indices={remote_indices}"
            )
        handle = store.execute_get_plan_gpu(
            handle, [destination], consume_prefix_len=1
        )
        handle_kind = "gpu"
        gpu_handle = handle
        plan_ptr = store.get_transfer_gpu(gpu_handle, consume_prefix_len=1)
        timing = validate_terminal_timing(gpu_handle)
        handle = None
        handle_kind = None
        torch.cuda.synchronize(args.cuda_device)
        actual = staging.cpu().numpy().tobytes()
        actual_sha256 = hashlib.sha256(actual).hexdigest()
        if actual != expected:
            mismatch = next(
                index
                for index, (actual_byte, expected_byte) in enumerate(zip(actual, expected))
                if actual_byte != expected_byte
            )
            fail(
                "GPU Get payload mismatch: "
                f"offset={mismatch} actual={actual[mismatch]} expected={expected[mismatch]} "
                f"actual_sha256={actual_sha256} expected_sha256={expected_sha256}"
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
            context="reader GPU local owner after Get",
        )
        if local_owner_binding_after_io != local_owner_binding:
            fail("reader GPU local owner binding changed across Get")
        if sha256_file(args.config) != config_sha256:
            fail("reader config changed during Get")
        if args.hard_exit_after_success and registration is not None:
            consume_ok(
                store.unregister_gpu_buffer(registration),
                "reader unregister_gpu_buffer",
            )
            registration = None
        record = {
            "schema": SCHEMA,
            "mode": "reader",
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
            "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
            "cuda_device": args.cuda_device,
            "gpu_device": args.physical_gpu_device,
            "gpu_remote_indices": remote_indices,
            "registration_id": registration_id,
            "terminal_timing": timing,
            "terminal_timing_observed_after_get_transfer_gpu": True,
            "readiness_declaration_scope": "audit_only_not_enforcement",
        }
        finish_success(args, record)
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


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--cluster-name", required=True)
    parser.add_argument("--probe-instance-key", required=True)
    parser.add_argument("--expected-hostname", required=True)
    parser.add_argument("--expected-ip", required=True)
    parser.add_argument("--expected-rdma-device", action="append", required=True)
    parser.add_argument("--readiness-timeout-seconds", type=int, default=300)
    parser.add_argument("--key", required=True)
    parser.add_argument("--size", type=int, default=4_718_592)
    parser.add_argument("--seed", type=int, default=73)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--hard-exit-after-success", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="mode", required=True)
    writer = subparsers.add_parser("writer")
    add_common(writer)
    writer.add_argument("--target-client-config-id", required=True)
    writer.add_argument("--source-owner-id", required=True)
    writer.add_argument("--source-owner-node-start-time", type=int, required=True)
    reader = subparsers.add_parser("reader")
    add_common(reader)
    reader.add_argument("--client-config-id", required=True)
    reader.add_argument("--client-node-start-time", type=int, required=True)
    reader.add_argument("--local-owner-id", required=True)
    reader.add_argument("--local-owner-node-start-time", type=int, required=True)
    reader.add_argument("--local-owner-segment-len", type=int, required=True)
    reader.add_argument("--cuda-device", type=int, default=0)
    reader.add_argument("--physical-gpu-device", type=int, required=True)
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
    if args.mode == "writer":
        if args.source_owner_node_start_time <= 0:
            fail("--source-owner-node-start-time must be positive")
        run_writer(args)
    else:
        if args.client_node_start_time <= 0:
            fail("--client-node-start-time must be positive")
        if args.local_owner_node_start_time <= 0:
            fail("--local-owner-node-start-time must be positive")
        if args.local_owner_segment_len <= 0:
            fail("--local-owner-segment-len must be positive")
        if args.cuda_device < 0 or args.physical_gpu_device < 0:
            fail("GPU device indices must be non-negative")
        run_reader(args)


if __name__ == "__main__":
    main()
