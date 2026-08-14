#!/usr/bin/env python3
"""Fail-closed capacity manifest for Fluxon/SGLang group F."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import yaml


PHYSICAL_BYTES = 274_877_906_944
LOCAL_PAYLOAD_BYTES = 247_390_116_249
VALUE_LEN_BYTES = 4_718_592
LEGACY_FOUR_RAIL_LOCAL_HCAS = ["mlx5_0", "mlx5_1", "mlx5_2", "mlx5_3"]
COMMON_TWO_RAIL_LOCAL_HCAS = ["mlx5_0", "mlx5_1"]
LOCAL_HCAS = LEGACY_FOUR_RAIL_LOCAL_HCAS
REMOTE_HCAS = ["mlx5_0", "mlx5_1"]
ANSI_CSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit(f"expected YAML mapping: {path}")
    return value


def require_equal(label: str, actual: Any, expected: Any) -> None:
    if actual != expected:
        raise SystemExit(f"{label} mismatch: actual={actual!r} expected={expected!r}")


def local_hcas_for_profile(profile: str) -> list[str]:
    if profile == "legacy_four_rail":
        return list(LEGACY_FOUR_RAIL_LOCAL_HCAS)
    if profile == "pplx_common_two_rail":
        return list(COMMON_TWO_RAIL_LOCAL_HCAS)
    raise SystemExit(f"unsupported local RDMA profile: {profile}")


def assert_ssd_disabled(label: str, config: dict[str, Any]) -> None:
    spec = config.get("fluxonkv_spec")
    if not isinstance(spec, dict):
        raise SystemExit(f"{label} missing fluxonkv_spec")
    forbidden = {
        "large_limit_size",
        "ssd_write_rate_limit_bytes_per_sec",
        "ssd_write_burst_bytes",
        "ssd_capacity_writeback_enabled",
    }
    present = sorted(forbidden.intersection(spec))
    if present:
        raise SystemExit(f"{label} unexpectedly enables SSD fields: {present}")


def capacity_values(path: Path) -> list[int]:
    text = path.read_text(encoding="utf-8", errors="replace")
    text = ANSI_CSI_RE.sub("", text)
    values = {
        int(match)
        for match in re.findall(r"\bcapacity_bytes=(\d+)\b", text)
    }
    return sorted(values)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-owner-config", type=Path, required=True)
    parser.add_argument("--remote-owner-config", type=Path, required=True)
    parser.add_argument("--client-config", type=Path, action="append", required=True)
    parser.add_argument("--local-owner-log", type=Path, required=True)
    parser.add_argument("--remote-owner-log", type=Path, required=True)
    parser.add_argument("--local-mmap-size", type=int, required=True)
    parser.add_argument("--remote-mmap-size", type=int, required=True)
    parser.add_argument(
        "--local-rdma-profile",
        choices=("legacy_four_rail", "pplx_common_two_rail"),
        default="legacy_four_rail",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    local_hcas = local_hcas_for_profile(args.local_rdma_profile)

    if len(args.client_config) != 2:
        raise SystemExit("exactly two --client-config arguments are required")
    paths = [
        args.local_owner_config,
        args.remote_owner_config,
        args.local_owner_log,
        args.remote_owner_log,
        *args.client_config,
    ]
    for path in paths:
        if not path.is_file():
            raise SystemExit(f"missing evidence file: {path}")
    if args.output.exists():
        raise SystemExit(f"refusing to overwrite capacity manifest: {args.output}")

    local = load_yaml(args.local_owner_config)
    remote = load_yaml(args.remote_owner_config)
    clients = [load_yaml(path) for path in args.client_config]

    require_equal("local physical config", local.get("contribute_to_cluster_pool_size", {}).get("dram"), PHYSICAL_BYTES)
    require_equal("remote physical config", remote.get("contribute_to_cluster_pool_size", {}).get("dram"), PHYSICAL_BYTES)
    require_equal("local mmap", args.local_mmap_size, PHYSICAL_BYTES)
    require_equal("remote mmap", args.remote_mmap_size, PHYSICAL_BYTES)
    require_equal("local hot ratio", local.get("replica_writeback_hot_capacity_ratio"), 0.90)
    reserve = local.get("test_spec_config", {}).get("owner_local_reserve_expected_capacity", {})
    require_equal("local reserve value_len", reserve.get("value_len"), VALUE_LEN_BYTES)
    require_equal("local reserve payload", reserve.get("payload_capacity_bytes"), LOCAL_PAYLOAD_BYTES)
    require_equal("local HCA list", local.get("test_spec_config", {}).get("rdma_device_names"), local_hcas)
    require_equal("remote HCA list", remote.get("test_spec_config", {}).get("rdma_device_names"), REMOTE_HCAS)
    require_equal("remote role", remote.get("fluxonkv_spec", {}).get("sub_cluster"), "remote_cache")
    assert_ssd_disabled("local owner", local)
    assert_ssd_disabled("remote owner", remote)

    cluster = local.get("fluxonkv_spec", {}).get("cluster_name")
    require_equal("remote cluster", remote.get("fluxonkv_spec", {}).get("cluster_name"), cluster)
    local_share = local.get("fluxonkv_spec", {}).get("share_mem_path")
    client_ids: list[str] = []
    for index, client in enumerate(clients):
        require_equal(f"client{index} DRAM contribution", client.get("contribute_to_cluster_pool_size", {}).get("dram"), 0)
        require_equal(f"client{index} cluster", client.get("fluxonkv_spec", {}).get("cluster_name"), cluster)
        require_equal(f"client{index} shared owner path", client.get("fluxonkv_spec", {}).get("share_mem_path"), local_share)
        require_equal(f"client{index} HCA list", client.get("test_spec_config", {}).get("rdma_device_names"), local_hcas)
        client_id = client.get("instance_key")
        if not isinstance(client_id, str) or not client_id:
            raise SystemExit(f"client{index} has invalid instance_key")
        client_ids.append(client_id)
        assert_ssd_disabled(f"client{index}", client)
    if len(set(client_ids)) != 2:
        raise SystemExit(f"external-client identities are not unique: {client_ids}")

    local_capacities = capacity_values(args.local_owner_log)
    remote_capacities = capacity_values(args.remote_owner_log)
    if LOCAL_PAYLOAD_BYTES not in local_capacities:
        raise SystemExit(
            "local owner did not report the target Moka boundary: "
            f"target={LOCAL_PAYLOAD_BYTES} observed={local_capacities}"
        )

    output = {
        "schema": "fluxon_dram_capacity_v1",
        "schema_version": 1,
        "group": "F",
        "status": "final_measured",
        "cluster_name": cluster,
        "ssd_enabled": False,
        "rdma_profile": args.local_rdma_profile,
        "local": {
            "owner_id": local.get("instance_key"),
            "physical_dram_bytes": PHYSICAL_BYTES,
            "configured_payload_bytes": LOCAL_PAYLOAD_BYTES,
            "mmap_bytes": args.local_mmap_size,
            "observed_capacity_bytes": local_capacities,
            "hot_capacity_ratio": 0.90,
            "rdma_hcas": local_hcas,
        },
        "remote": {
            "owner_id": remote.get("instance_key"),
            "physical_dram_bytes": PHYSICAL_BYTES,
            "mmap_bytes": args.remote_mmap_size,
            "observed_capacity_bytes": remote_capacities,
            "rdma_hcas": REMOTE_HCAS,
        },
        "external_clients": sorted(client_ids),
        "evidence": {
            str(path): sha256(path)
            for path in paths
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(output, sort_keys=True))


if __name__ == "__main__":
    main()
