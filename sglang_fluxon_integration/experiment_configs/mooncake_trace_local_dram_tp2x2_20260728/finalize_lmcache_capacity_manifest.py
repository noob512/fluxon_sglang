#!/usr/bin/env python3
"""Create the fail-closed measured capacity manifest for formal group E."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import shlex
import socket
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Sequence


SCHEMA = "lmcache_mooncake_capacity_v2"
MODEL_PATH = "/public/mjq/models/Qwen3-VL-8B-Instruct"
LOCAL_TOTAL_BYTES = 274_877_906_944
REMOTE_SEGMENT_BYTES = 274_877_906_944
MOONCAKE_RANK_SEGMENT_BYTES = 16_777_216
MOONCAKE_RANK_LOCAL_BUFFER_BYTES = 1_024
RANK_CONFIGURED_BYTES = 68_702_698_496
RANK_CONFIGURED_GIB = RANK_CONFIGURED_BYTES / 1024**3
CHUNK_TOKENS = 512
NUM_LAYERS = 36
KV_SIZE = 2
KV_HEADS_PER_RANK = 4
HEAD_SIZE = 128
DTYPE_BYTES = 2
CHUNK_BYTES_PER_RANK = (
    NUM_LAYERS
    * KV_SIZE
    * CHUNK_TOKENS
    * KV_HEADS_PER_RANK
    * HEAD_SIZE
    * DTYPE_BYTES
)
RANK_CHUNKS = RANK_CONFIGURED_BYTES // CHUNK_BYTES_PER_RANK
RANK_USABLE_BYTES = RANK_CHUNKS * CHUNK_BYTES_PER_RANK
RANK_ALIGNMENT_SLACK_BYTES = RANK_CONFIGURED_BYTES - RANK_USABLE_BYTES
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_evidence(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--lmcache-config",
        type=Path,
        nargs=2,
        required=True,
        metavar=("INSTANCE0", "INSTANCE1"),
    )
    parser.add_argument(
        "--command-argv",
        type=Path,
        nargs=2,
        required=True,
        metavar=("INSTANCE0", "INSTANCE1"),
    )
    parser.add_argument(
        "--vllm-log",
        type=Path,
        nargs=2,
        required=True,
        metavar=("INSTANCE0", "INSTANCE1"),
    )
    parser.add_argument(
        "--metrics-file",
        type=Path,
        nargs=2,
        required=True,
        metavar=("INSTANCE0", "INSTANCE1"),
    )
    parser.add_argument("--master-metrics-file", type=Path, required=True)
    parser.add_argument("--overlay-manifest", type=Path, required=True)
    parser.add_argument("--overlay-manifest-sha256", required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--gpu-hostname", default=socket.gethostname())
    parser.add_argument("--gpu-private-ip", required=True)
    parser.add_argument("--remote-hostname", required=True)
    parser.add_argument("--remote-private-ip", required=True)
    parser.add_argument(
        "--mooncake-remote-segment-bytes",
        type=int,
        default=REMOTE_SEGMENT_BYTES,
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def scalar(value: str) -> Any:
    value = value.strip()
    if value.startswith(('"', "'")):
        return ast.literal_eval(value)
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    if re.fullmatch(r"-?[0-9]+", value):
        return int(value)
    if re.fullmatch(r"-?[0-9]+[.][0-9]+", value):
        return float(value)
    return value


def parse_simple_yaml(path: Path) -> dict[str, Any]:
    values: dict[str, Any] = {}
    parent: str | None = None
    for line_number, raw in enumerate(path.read_text().splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        match = re.fullmatch(r"(  )?([a-zA-Z0-9_]+):(?:[ ]*(.*))?", raw)
        if match is None:
            raise SystemExit(f"unsupported YAML line {path}:{line_number}: {raw!r}")
        indent, key, raw_value = match.groups()
        raw_value = raw_value or ""
        if indent:
            if parent is None:
                raise SystemExit(f"orphan nested YAML key {path}:{line_number}")
            full_key = f"{parent}.{key}"
        else:
            parent = key if not raw_value else None
            if not raw_value:
                continue
            full_key = key
        if full_key in values:
            raise SystemExit(f"duplicate YAML key {full_key} in {path}")
        values[full_key] = scalar(raw_value)
    return values


def expected_config(gpu_ip: str, devices: str) -> dict[str, Any]:
    return {
        "chunk_size": CHUNK_TOKENS,
        "local_cpu": True,
        "max_local_cpu_size": RANK_CONFIGURED_GIB,
        "local_cpu_use_hugepages": False,
        "remote_serde": "naive",
        "remote_url": "mooncakestore://127.0.0.1:51081/",
        "numa_mode": "auto",
        "pre_caching_hash_algorithm": "sha256_cbor_64bit",
        "extra_config.save_chunk_meta": False,
        "extra_config.use_exists_sync": True,
        "extra_config.local_hostname": gpu_ip,
        "extra_config.metadata_server": "http://127.0.0.1:8183/metadata",
        "extra_config.protocol": "rdma",
        "extra_config.device_name": devices,
        "extra_config.mooncake_rdma_devices": devices,
        "extra_config.global_segment_size": MOONCAKE_RANK_SEGMENT_BYTES,
        "extra_config.local_buffer_size": MOONCAKE_RANK_LOCAL_BUFFER_BYTES,
        "extra_config.master_server_address": "127.0.0.1:51081",
        "extra_config.mooncake_master_server_addr": "127.0.0.1:51081",
        "extra_config.mooncake_prefer_local_alloc": False,
        "extra_config.transfer_timeout": 10,
    }


def expected_command(port: int) -> list[str]:
    return [
        str(Path("/public/mjq/.venv_sglang_fluxon/bin/python")),
        "-m",
        "vllm.entrypoints.cli.main",
        "serve",
        MODEL_PATH,
        "--served-model-name",
        MODEL_PATH,
        "--host",
        "0.0.0.0",
        "--port",
        str(port),
        "--tensor-parallel-size",
        "2",
        "--distributed-executor-backend",
        "mp",
        "--max-model-len",
        "200000",
        "--max-num-batched-tokens",
        "8192",
        "--max-num-seqs",
        "1024",
        "--gpu-memory-utilization",
        "0.90",
        "--cpu-offload-gb",
        "0",
        "--enable-chunked-prefill",
        "--enable-prefix-caching",
        "--enable-prompt-tokens-details",
        "--generation-config",
        "vllm",
        "--kv-transfer-config",
        '{"kv_connector":"LMCacheConnectorV1","kv_role":"kv_both"}',
    ]


def parse_setup_dicts(log_text: str) -> list[dict[str, Any]]:
    marker = "Setting up Mooncake store with setup_config: "
    values: list[dict[str, Any]] = []
    for line in log_text.splitlines():
        if marker not in line:
            continue
        raw = line.split(marker, 1)[1].strip()
        dict_end = raw.rfind("}")
        if not raw.startswith("{") or dict_end < 0:
            raise SystemExit(f"cannot find Mooncake setup mapping: {raw!r}")
        raw = raw[: dict_end + 1]
        try:
            value = ast.literal_eval(raw)
        except (SyntaxError, ValueError) as exc:
            raise SystemExit(f"cannot parse Mooncake setup evidence: {raw!r}") from exc
        if not isinstance(value, dict):
            raise SystemExit("Mooncake setup evidence is not a mapping")
        values.append(value)
    return values


def parse_worker_metrics(text: str) -> dict[int, float]:
    samples: dict[int, float] = {}
    pattern = re.compile(
        r'^lmcache[:_]local_cache_usage\{(?P<labels>[^}]*)\}[ ]+(?P<value>[0-9.eE+-]+)$'
    )
    for line in text.splitlines():
        match = pattern.fullmatch(line.strip())
        if match is None:
            continue
        labels = dict(re.findall(r'([a-zA-Z_]+)="([^"]*)"', match.group("labels")))
        if labels.get("role", "").lower() != "worker":
            continue
        worker_raw = labels.get("worker_id")
        if worker_raw not in {"0", "1"}:
            continue
        worker = int(worker_raw)
        if worker in samples:
            raise SystemExit(f"duplicate LMCache usage sample for worker {worker}")
        value = float(match.group("value"))
        if value < 0 or value > RANK_CONFIGURED_BYTES:
            raise SystemExit(f"invalid LMCache usage for worker {worker}: {value}")
        samples[worker] = value
    if set(samples) != {0, 1}:
        raise SystemExit(f"metrics lack LMCache worker 0/1 usage samples: {samples}")
    return samples


def prometheus_integer(text: str, metric: str) -> int:
    matches = re.findall(
        rf"^{re.escape(metric)}[ ]+([0-9.eE+-]+)$", text, flags=re.MULTILINE
    )
    if len(matches) != 1:
        raise SystemExit(f"expected one {metric} sample, found {matches}")
    try:
        value = Decimal(matches[0])
    except InvalidOperation as exc:
        raise SystemExit(f"invalid {metric} value: {matches[0]}") from exc
    if value != value.to_integral_value() or value < 0:
        raise SystemExit(f"non-integer {metric} value: {matches[0]}")
    return int(value)


def validate_master_metrics(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SystemExit(f"missing master metrics evidence: {path}")
    text = path.read_text()
    expected_total = REMOTE_SEGMENT_BYTES + 4 * MOONCAKE_RANK_SEGMENT_BYTES
    total = prometheus_integer(text, "master_total_capacity_bytes")
    clients = prometheus_integer(text, "master_active_clients")
    mount_failures = prometheus_integer(
        text, "master_mount_segment_failures_total"
    )
    segment_values = []
    for raw in re.findall(
        r'^segment_total_capacity_bytes\{[^}]+\}[ ]+([0-9.eE+-]+)$',
        text,
        flags=re.MULTILINE,
    ):
        try:
            value = Decimal(raw)
        except InvalidOperation as exc:
            raise SystemExit(f"invalid segment capacity: {raw}") from exc
        if value != value.to_integral_value() or value < 0:
            raise SystemExit(f"non-integer segment capacity: {raw}")
        segment_values.append(int(value))
    expected_segments = sorted(
        [REMOTE_SEGMENT_BYTES] + [MOONCAKE_RANK_SEGMENT_BYTES] * 4
    )
    if total != expected_total:
        raise SystemExit(
            f"master capacity mismatch: expected={expected_total} actual={total}"
        )
    if clients != 5 or mount_failures != 0:
        raise SystemExit(
            f"master client/mount gate failed: clients={clients} "
            f"mount_failures={mount_failures}"
        )
    if sorted(segment_values) != expected_segments:
        raise SystemExit(
            f"master segment capacities mismatch: expected={expected_segments} "
            f"actual={sorted(segment_values)}"
        )
    return {
        **file_evidence(path),
        "total_capacity_bytes": total,
        "active_clients": clients,
        "mount_segment_failures": mount_failures,
        "segment_capacity_bytes": sorted(segment_values),
    }


def validate_overlay(path: Path, expected_sha256: str) -> dict[str, Any]:
    if not SHA256_RE.fullmatch(expected_sha256):
        raise SystemExit("invalid overlay manifest SHA256")
    actual_sha256 = sha256_file(path)
    if actual_sha256 != expected_sha256:
        raise SystemExit("overlay manifest SHA256 mismatch")
    value = json.loads(path.read_text())
    if value.get("schema") != "vllm_lmcache_overlay_v1":
        raise SystemExit("wrong overlay manifest schema")
    smoke = value.get("import_smoke", {})
    expected_versions = {
        "vllm": "0.24.0",
        "lmcache": "0.5.2",
        "mooncake": "0.3.11.post1",
    }
    if any(smoke.get(key) != version for key, version in expected_versions.items()):
        raise SystemExit(f"overlay version mismatch: {smoke}")
    if not smoke.get("cuda_available") or smoke.get("gpu_count", 0) < 4:
        raise SystemExit("overlay GPU import smoke is not valid")
    distributions = value.get("installed_distributions", {})
    if distributions.get("vllm") != "0.24.0" or distributions.get("lmcache") != "0.5.2":
        raise SystemExit("overlay distribution versions do not match")
    return value


def validate_instance(
    index: int,
    config_path: Path,
    command_path: Path,
    log_path: Path,
    metrics_path: Path,
    gpu_ip: str,
) -> dict[str, Any]:
    for path in (config_path, command_path, log_path, metrics_path):
        if not path.is_file():
            raise SystemExit(f"missing instance{index} evidence: {path}")

    devices = "mlx5_0,mlx5_1" if index == 0 else "mlx5_2,mlx5_3"
    config = parse_simple_yaml(config_path)
    expected = expected_config(gpu_ip, devices)
    if config != expected:
        raise SystemExit(
            f"instance{index} LMCache config mismatch: expected={expected} actual={config}"
        )

    command = shlex.split(command_path.read_text())
    expected_argv = expected_command(31001 + index)
    if command != expected_argv:
        raise SystemExit(
            f"instance{index} vLLM argv mismatch: expected={expected_argv} actual={command}"
        )

    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    if "Application startup complete." not in log_text:
        raise SystemExit(f"instance{index} vLLM log does not prove API readiness")
    geometry_marker = (
        "num_layer: 36, chunk_size: 512, num_kv_head (per gpu): 4, "
        "head_size: 128, hidden_dim (D) for KV (per gpu): 512, use mla: False, "
        "kv shape: (36, 2, 512, 4, 128)"
    )
    if log_text.count(geometry_marker) < 2:
        raise SystemExit(f"instance{index} lacks two-rank LMCache geometry evidence")
    worker_ranks = {
        int(match.group(1))
        for line in log_text.splitlines()
        if "LMCache initialized for role KVConnectorRole.WORKER" in line
        and "world_size=2" in line
        and "kv_shape=(36, 2, 512, 4, 128)" in line
        and (match := re.search(r"worker_id=([01])", line)) is not None
    }
    if worker_ranks != {0, 1}:
        raise SystemExit(
            f"instance{index} lacks initialized LMCache worker ranks 0/1: {worker_ranks}"
        )
    forbidden_runtime_markers = (
        "Invalid global_segment_size",
        "Invalid local_buffer_size",
        "Client is not initialized",
        "Buffer registration failed",
        "Mooncake store setup failed",
    )
    present_forbidden = [
        marker for marker in forbidden_runtime_markers if marker in log_text
    ]
    if present_forbidden:
        raise SystemExit(
            f"instance{index} contains Mooncake runtime failures: {present_forbidden}"
        )
    registered = re.findall(r"Registered: 0x[0-9a-fA-F]+, ([0-9]+) bytes", log_text)
    if registered != [str(RANK_CONFIGURED_BYTES)] * 2:
        raise SystemExit(
            f"instance{index} registered buffers do not prove two configured ranks: {registered}"
        )
    setup_dicts = parse_setup_dicts(log_text)
    valid_setups = [
        item
        for item in setup_dicts
        if int(item.get("global_segment_size", -1))
        == MOONCAKE_RANK_SEGMENT_BYTES
        and int(item.get("local_buffer_size", -1))
        == MOONCAKE_RANK_LOCAL_BUFFER_BYTES
        and item.get("local_hostname") == gpu_ip
        and item.get("metadata_server") == "***REDACTED***"
        and item.get("device_name") == devices
        and item.get("rdma_devices") == devices
        and item.get("master_server_address") == "***REDACTED***"
        and item.get("master_server_addr") == "127.0.0.1:51081"
    ]
    if len(valid_setups) != 2:
        raise SystemExit(
            f"instance{index} does not prove two allocator-minimum Mooncake clients"
        )
    if log_text.count("Mooncake store setup completed successfully") != 2:
        raise SystemExit(f"instance{index} Mooncake setup success count is not two")
    if log_text.count("Successfully created client on port") != 2:
        raise SystemExit(f"instance{index} Mooncake client success count is not two")
    if log_text.count(
        f"Mounting segment: {MOONCAKE_RANK_SEGMENT_BYTES} bytes"
    ) != 2:
        raise SystemExit(
            f"instance{index} does not prove two allocator-minimum Mooncake segments"
        )

    metric_samples = parse_worker_metrics(metrics_path.read_text())
    return {
        "instance": f"instance{index}",
        "port": 31001 + index,
        "gpus": [2 * index, 2 * index + 1],
        "device_names": devices,
        "lmcache_config": file_evidence(config_path),
        "command_argv": file_evidence(command_path),
        "vllm_log": file_evidence(log_path),
        "metrics": {
            **file_evidence(metrics_path),
            "local_cache_usage_bytes_by_worker": {
                str(rank): value for rank, value in sorted(metric_samples.items())
            },
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.gpu_hostname != socket.gethostname():
        raise SystemExit(
            f"GPU hostname mismatch: expected={args.gpu_hostname} actual={socket.gethostname()}"
        )
    if args.mooncake_remote_segment_bytes != REMOTE_SEGMENT_BYTES:
        raise SystemExit("remote Mooncake capacity is not exactly 256 GiB")
    if args.output.exists():
        raise SystemExit(f"output already exists: {args.output}")
    if CHUNK_BYTES_PER_RANK != 37_748_736:
        raise SystemExit("internal LMCache chunk geometry mismatch")
    if (
        RANK_USABLE_BYTES != 68_664_950_784
        or RANK_ALIGNMENT_SLACK_BYTES != 37_747_712
    ):
        raise SystemExit("internal LMCache allocator geometry mismatch")

    overlay = validate_overlay(args.overlay_manifest, args.overlay_manifest_sha256)
    instances = [
        validate_instance(
            index,
            args.lmcache_config[index],
            args.command_argv[index],
            args.vllm_log[index],
            args.metrics_file[index],
            args.gpu_private_ip,
        )
        for index in range(2)
    ]
    master_metrics = validate_master_metrics(args.master_metrics_file)

    configured = [RANK_CONFIGURED_BYTES] * 4
    usable = [RANK_USABLE_BYTES] * 4
    slack = [RANK_ALIGNMENT_SLACK_BYTES] * 4
    local_mooncake = [MOONCAKE_RANK_SEGMENT_BYTES] * 4
    local_mooncake_buffers = [MOONCAKE_RANK_LOCAL_BUFFER_BYTES] * 4
    value = {
        "schema": SCHEMA,
        "status": "final_measured",
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        "group": "E",
        "namespace": args.namespace,
        "engine": "vllm-0.24.0+lmcache-0.5.2+mooncake-0.3.11.post1",
        "lmcache_chunk_tokens": CHUNK_TOKENS,
        "lmcache_chunk_bytes_per_rank": CHUNK_BYTES_PER_RANK,
        "lmcache_chunks_per_rank": RANK_CHUNKS,
        "lmcache_rank_configured_bytes": configured,
        "lmcache_rank_usable_bytes": usable,
        "lmcache_rank_alignment_slack_bytes": slack,
        "lmcache_total_configured_bytes": sum(configured),
        "lmcache_total_usable_bytes": sum(usable),
        "lmcache_total_alignment_slack_bytes": sum(slack),
        "mooncake_local_rank_segment_bytes": local_mooncake,
        "mooncake_local_segment_bytes": sum(local_mooncake),
        "mooncake_local_rank_buffer_bytes": local_mooncake_buffers,
        "mooncake_local_buffer_bytes": sum(local_mooncake_buffers),
        "mooncake_local_kv_usable_bytes": 0,
        "mooncake_local_protocol_only": True,
        "local_total_bytes": (
            sum(configured) + sum(local_mooncake) + sum(local_mooncake_buffers)
        ),
        "mooncake_remote_segment_bytes": args.mooncake_remote_segment_bytes,
        "topology": {
            "instance0": {"tp_size": 2, "gpus": [0, 1], "port": 31001},
            "instance1": {"tp_size": 2, "gpus": [2, 3], "port": 31002},
            "router_port": 32000,
            "router_worker_hosts": ["127.0.0.1", "127.0.0.1"],
        },
        "gpu": {"hostname": args.gpu_hostname, "private_ip": args.gpu_private_ip},
        "remote_cpu": {
            "hostname": args.remote_hostname,
            "private_ip": args.remote_private_ip,
        },
        "capacity_evidence": {
            "instances": instances,
            "master_metrics": master_metrics,
        },
        "overlay": {
            **file_evidence(args.overlay_manifest),
            "tree_sha256": overlay.get("tree_sha256"),
            "wheel_manifest_sha256": overlay.get("wheel_manifest_sha256"),
            "import_smoke": overlay.get("import_smoke"),
        },
        "generator": {
            "path": str(Path(__file__).resolve()),
            "sha256": sha256_file(Path(__file__).resolve()),
            "pid": os.getpid(),
        },
    }
    if value["local_total_bytes"] != LOCAL_TOTAL_BYTES:
        raise SystemExit("local LMCache plus Mooncake capacity is not exactly 256 GiB")

    encoded = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    print(hashlib.sha256(encoded).hexdigest(), args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
