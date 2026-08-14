#!/usr/bin/env python3
"""Fail-closed pre-trace gate for Fluxon F external GPU reads.

The owner startup gate in sealed r96 deliberately excludes external clients.
This tool therefore validates the live external generations and their direct
TE edges, then binds those control-plane facts to two real remote-only GPU Get
data probes.  It never starts a service or sends inference traffic.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, NoReturn


SCHEMA = "fluxon_f_direct_rdma_gate_v2"
SUMMARY_SCHEMA = "fluxon_f_direct_rdma_gate_summary_v2"


class GateError(RuntimeError):
    pass


def fail(message: str) -> NoReturn:
    raise GateError(message)


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def require_dict(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail(f"{context} must be an object")
    return value


def require_list(value: Any, context: str) -> list[Any]:
    if not isinstance(value, list):
        fail(f"{context} must be an array")
    return value


def require_text(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        fail(f"{context} must be a non-empty string")
    return value.strip()


def require_int(value: Any, context: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        fail(f"{context} must be an integer >= {minimum}")
    return value


def require_bool(value: Any, context: str) -> bool:
    if not isinstance(value, bool):
        fail(f"{context} must be a boolean")
    return value


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GateError(f"cannot read JSON {path}: {exc}") from exc


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


def write_json_exclusive(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(canonical_json(value))
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        return


def write_json_strict_exclusive(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(canonical_json(value))
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise GateError(f"refusing existing evidence path: {path}") from exc


def append_jsonl(path: Path, value: Any) -> None:
    payload = canonical_json(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab", buffering=0) as stream:
        stream.write(payload)
        os.fsync(stream.fileno())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sysfs_text(path: Path) -> str:
    try:
        return path.read_text(encoding="ascii").strip()
    except OSError as exc:
        raise GateError(f"cannot read required sysfs path {path}: {exc}") from exc


def proc_start_time_ticks(pid: int) -> int:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
        after_comm = raw.rsplit(")", 1)[1].split()
        return require_int(
            int(after_comm[19]), f"process {pid} start_time_ticks", minimum=1
        )
    except (OSError, ValueError, IndexError) as exc:
        raise GateError(f"cannot read process identity for pid {pid}: {exc}") from exc


def boot_id() -> str:
    try:
        value = Path("/proc/sys/kernel/random/boot_id").read_text(
            encoding="ascii"
        ).strip()
    except OSError as exc:
        raise GateError(f"cannot read boot_id: {exc}") from exc
    require(len(value) == 36, f"invalid boot_id: {value!r}")
    return value


def state_suffix(raw: str) -> str:
    return raw.split(":", 1)[-1].strip()


def parse_rate_gbps(raw: str) -> int:
    first = raw.split()[0] if raw.split() else ""
    try:
        return int(first)
    except ValueError as exc:
        raise GateError(f"cannot parse HCA rate {raw!r}") from exc


def capture_hca_snapshot(
    *, role: str, expected_hostname: str, expected_ip: str, devices: list[str]
) -> dict[str, Any]:
    require(role in {"gpu", "cpu"}, "HCA role must be gpu or cpu")
    require(len(devices) == len(set(devices)) and devices, "HCA devices must be unique")
    actual_hostname = socket.gethostname()
    try:
        addresses = sorted(
            {
                item[4][0]
                for item in socket.getaddrinfo(actual_hostname, None, socket.AF_INET)
            }
        )
    except socket.gaierror:
        addresses = []
    # hostname -I sees pod/container addresses that getaddrinfo may omit.
    result = subprocess.run(
        ["hostname", "-I"], check=True, text=True, capture_output=True
    )
    addresses = sorted(set(addresses).union(result.stdout.split()))
    hcas: list[dict[str, Any]] = []
    for device in devices:
        port = Path("/sys/class/infiniband") / device / "ports/1"
        lid = sysfs_text(port / "lid")
        sm_lid = sysfs_text(port / "sm_lid")
        gid0 = sysfs_text(port / "gids/0")
        rate = sysfs_text(port / "rate")
        hcas.append(
            {
                "device": device,
                "port": 1,
                "state": state_suffix(sysfs_text(port / "state")),
                "physical_state": state_suffix(sysfs_text(port / "phys_state")),
                "link_layer": sysfs_text(port / "link_layer"),
                "rate": rate,
                "rate_gbps": parse_rate_gbps(rate),
                "lid": lid,
                "sm_lid": sm_lid,
                "gid0": gid0,
            }
        )
    return {
        "role": role,
        "hostname": actual_hostname,
        "expected_hostname": expected_hostname,
        "ips": addresses,
        "expected_ip": expected_ip,
        "boot_id": boot_id(),
        "pid1_start_time_ticks": proc_start_time_ticks(1),
        "hcas": hcas,
    }


def decode_etcd_payload(raw: str, key: str) -> dict[str, Any]:
    try:
        response = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GateError(f"etcdctl returned invalid JSON for {key}: {exc}") from exc
    kvs = response.get("kvs", [])
    if not kvs:
        return {
            "key": key,
            "missing": True,
            "header_revision": int(response.get("header", {}).get("revision", 0)),
        }
    if len(kvs) != 1:
        fail(f"etcd key {key} returned {len(kvs)} values")
    kv = kvs[0]
    try:
        decoded_key = base64.b64decode(kv["key"], validate=True).decode("utf-8")
        value_text = base64.b64decode(kv["value"], validate=True).decode("utf-8")
    except (KeyError, ValueError, UnicodeDecodeError) as exc:
        raise GateError(f"cannot decode etcd key/value for {key}: {exc}") from exc
    require(decoded_key == key, f"etcd response key mismatch: expected={key} got={decoded_key}")
    return {
        "key": key,
        "missing": False,
        "create_revision": int(kv.get("create_revision", 0)),
        "mod_revision": int(kv.get("mod_revision", 0)),
        "version": int(kv.get("version", 0)),
        "lease": int(kv.get("lease", 0)),
        "value_text": value_text,
        "header_revision": int(response.get("header", {}).get("revision", 0)),
    }


def etcd_get(etcdctl: Path, endpoint: str, key: str) -> dict[str, Any]:
    command = [
        str(etcdctl),
        f"--endpoints={endpoint}",
        "get",
        key,
        "-w",
        "json",
    ]
    env = dict(os.environ)
    env["ETCDCTL_API"] = "3"
    try:
        result = subprocess.run(
            command,
            env=env,
            text=True,
            capture_output=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired as exc:
        raise GateError(f"etcdctl get timed out for {key}") from exc
    if result.returncode != 0:
        fail(
            f"etcdctl get failed for {key}: rc={result.returncode} "
            f"stderr={result.stderr.strip()}"
        )
    return decode_etcd_payload(result.stdout, key)


def json_value(entry: dict[str, Any], context: str) -> dict[str, Any]:
    require(not entry.get("missing", False), f"{context} is missing")
    try:
        value = json.loads(require_text(entry.get("value_text"), f"{context}.value_text"))
    except json.JSONDecodeError as exc:
        raise GateError(f"{context} value is not JSON: {exc}") from exc
    return require_dict(value, f"{context}.value")


def capture_etcd_snapshot(
    *,
    etcdctl: Path,
    endpoint: str,
    cluster_name: str,
    local_owner_id: str,
    remote_owner_id: str,
    client_ids: list[str],
) -> dict[str, Any]:
    require(len(client_ids) == 2 and len(set(client_ids)) == 2, "exactly two clients required")
    member_ids = [local_owner_id, remote_owner_id, *client_ids]
    members: dict[str, Any] = {}
    transfer_ready: dict[str, Any] = {}
    for member_id in member_ids:
        member_key = f"/fluxon_commu_member_base/{cluster_name}/members/{member_id}"
        ready_key = f"/fluxon_commu_member_ext/{cluster_name}/members/{member_id}/transfer_ready"
        member_entry = etcd_get(etcdctl, endpoint, member_key)
        ready_entry = etcd_get(etcdctl, endpoint, ready_key)
        if not member_entry.get("missing", False):
            member_entry["value"] = json_value(member_entry, f"member {member_id}")
        if not ready_entry.get("missing", False):
            ready_entry["value"] = json_value(ready_entry, f"transfer_ready {member_id}")
        members[member_id] = member_entry
        transfer_ready[member_id] = ready_entry
    te_edges: dict[str, Any] = {}
    for client_id in client_ids:
        edge_name = f"{client_id}->{remote_owner_id}"
        edge_key = f"/{cluster_name}/transfer_link/te/{client_id}/{remote_owner_id}"
        te_edges[edge_name] = etcd_get(etcdctl, endpoint, edge_key)
    return {
        "endpoint": endpoint,
        "cluster_name": cluster_name,
        "members": members,
        "transfer_ready": transfer_ready,
        "te_edges": te_edges,
    }


def parse_hex_nonzero(value: Any, context: str) -> int:
    raw = require_text(value, context)
    try:
        parsed = int(raw, 0)
    except ValueError as exc:
        raise GateError(f"{context} must be an integer/hex string: {raw!r}") from exc
    require(parsed > 0, f"{context} must be non-zero")
    return parsed


def validate_fabric_node(
    node: Any,
    *,
    role: str,
    expected_hostname: str,
    expected_ip: str,
    expected_devices: list[str],
) -> dict[str, Any]:
    value = require_dict(node, f"fabric.{role}")
    require(value.get("role") == role, f"fabric.{role}.role mismatch")
    require(value.get("hostname") == expected_hostname, f"fabric.{role} hostname mismatch")
    require(
        value.get("expected_hostname") == expected_hostname,
        f"fabric.{role} captured expected_hostname mismatch",
    )
    ips = require_list(value.get("ips"), f"fabric.{role}.ips")
    require(expected_ip in ips, f"fabric.{role} expected IP {expected_ip} is absent")
    require(
        value.get("expected_ip") == expected_ip,
        f"fabric.{role} captured expected_ip mismatch",
    )
    node_boot_id = require_text(value.get("boot_id"), f"fabric.{role}.boot_id")
    require(len(node_boot_id) == 36, f"fabric.{role}.boot_id is invalid")
    pid1_start = require_int(
        value.get("pid1_start_time_ticks"),
        f"fabric.{role}.pid1_start_time_ticks",
        minimum=1,
    )
    hcas = require_list(value.get("hcas"), f"fabric.{role}.hcas")
    by_device: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(hcas):
        hca = require_dict(raw, f"fabric.{role}.hcas[{index}]")
        device = require_text(hca.get("device"), f"fabric.{role}.hcas[{index}].device")
        require(device not in by_device, f"fabric.{role} duplicate HCA {device}")
        by_device[device] = hca
    require(
        set(by_device) == set(expected_devices),
        f"fabric.{role} HCA set mismatch: expected={expected_devices} got={sorted(by_device)}",
    )
    sm_lids: list[int] = []
    for device in expected_devices:
        hca = by_device[device]
        require(hca.get("state") == "ACTIVE", f"fabric.{role}.{device} is not ACTIVE")
        require(
            hca.get("physical_state") == "LinkUp",
            f"fabric.{role}.{device} is not LinkUp",
        )
        require(
            hca.get("link_layer") == "InfiniBand",
            f"fabric.{role}.{device} is not InfiniBand",
        )
        require_int(hca.get("rate_gbps"), f"fabric.{role}.{device}.rate_gbps", minimum=400)
        parse_hex_nonzero(hca.get("lid"), f"fabric.{role}.{device}.lid")
        sm_lids.append(parse_hex_nonzero(hca.get("sm_lid"), f"fabric.{role}.{device}.sm_lid"))
        gid = require_text(hca.get("gid0"), f"fabric.{role}.{device}.gid0").lower()
        compact_gid = gid.replace(":", "").replace("0x", "")
        require(any(char != "0" for char in compact_gid), f"fabric.{role}.{device}.gid0 is zero")
    return {
        "role": role,
        "hostname": expected_hostname,
        "ip": expected_ip,
        "boot_id": node_boot_id,
        "pid1_start_time_ticks": pid1_start,
        "devices": list(expected_devices),
        "sm_lids": sm_lids,
    }


def validate_member_entry(
    entry: Any,
    *,
    member_id: str,
    expected_sub_cluster: str,
    expected_ip: str,
    external: bool,
) -> tuple[dict[str, Any], int, int]:
    record = require_dict(entry, f"member {member_id}")
    require(not record.get("missing", False), f"member {member_id} is missing")
    require_int(record.get("lease"), f"member {member_id}.lease", minimum=1)
    revision = require_int(record.get("mod_revision"), f"member {member_id}.mod_revision", minimum=1)
    value = require_dict(record.get("value"), f"member {member_id}.value")
    require(value.get("id") == member_id, f"member {member_id} embedded id mismatch")
    addresses = require_list(value.get("addresses"), f"member {member_id}.addresses")
    require(
        expected_ip in addresses,
        f"member {member_id} is not advertised by expected IP {expected_ip}",
    )
    generation = require_int(
        value.get("node_start_time"), f"member {member_id}.node_start_time", minimum=1
    )
    metadata = require_dict(value.get("metadata"), f"member {member_id}.metadata")
    require(value.get("sub_cluster") == expected_sub_cluster, f"member {member_id} sub_cluster mismatch")
    if external:
        require(metadata.get("external_client") == "true", f"member {member_id} is not external")
        require(metadata.get("client") != "true", f"member {member_id} is also marked owner client")
    else:
        require(metadata.get("client") == "true", f"member {member_id} is not an owner client")
        require(metadata.get("external_client") != "true", f"owner {member_id} is external")
    return value, generation, revision


def validate_transfer_ready(
    entry: Any, *, member_id: str, generation: int, member_revision: int
) -> tuple[int, int]:
    record = require_dict(entry, f"transfer_ready {member_id}")
    require(not record.get("missing", False), f"transfer_ready {member_id} is missing")
    revision = require_int(
        record.get("mod_revision"), f"transfer_ready {member_id}.mod_revision", minimum=1
    )
    require(revision >= member_revision, f"transfer_ready {member_id} predates member generation")
    value = require_dict(record.get("value"), f"transfer_ready {member_id}.value")
    require(
        value.get("node_start_time") == generation,
        f"transfer_ready {member_id} has stale node_start_time",
    )
    backend_epoch = require_int(
        value.get("backend_epoch"), f"transfer_ready {member_id}.backend_epoch", minimum=1
    )
    require_int(value.get("ready_ts_micros"), f"transfer_ready {member_id}.ready_ts_micros", minimum=1)
    return revision, backend_epoch


def validate_control_plane_snapshot(
    raw: Any,
    *,
    cluster_name: str,
    local_owner_id: str,
    remote_owner_id: str,
    local_ip: str,
    remote_ip: str,
    client_ids: list[str],
    baseline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate current-generation live clients and their direct TE edges."""

    require(
        len(client_ids) == 2 and len(set(client_ids)) == 2,
        "control-plane validation requires exactly two unique clients",
    )
    etcd = require_dict(raw, "etcd")
    require(etcd.get("cluster_name") == cluster_name, "etcd cluster_name mismatch")
    members = require_dict(etcd.get("members"), "etcd.members")
    ready = require_dict(etcd.get("transfer_ready"), "etcd.transfer_ready")
    edges = require_dict(etcd.get("te_edges"), "etcd.te_edges")

    _, local_generation, local_member_revision = validate_member_entry(
        members.get(local_owner_id),
        member_id=local_owner_id,
        expected_sub_cluster="sglang_owner",
        expected_ip=local_ip,
        external=False,
    )
    _, remote_generation, remote_member_revision = validate_member_entry(
        members.get(remote_owner_id),
        member_id=remote_owner_id,
        expected_sub_cluster="remote_cache",
        expected_ip=remote_ip,
        external=False,
    )
    local_ready_revision, local_backend_epoch = validate_transfer_ready(
        ready.get(local_owner_id),
        member_id=local_owner_id,
        generation=local_generation,
        member_revision=local_member_revision,
    )
    remote_ready_revision, remote_backend_epoch = validate_transfer_ready(
        ready.get(remote_owner_id),
        member_id=remote_owner_id,
        generation=remote_generation,
        member_revision=remote_member_revision,
    )

    clients: list[dict[str, Any]] = []
    edge_summaries: list[dict[str, Any]] = []
    for client_id in client_ids:
        member_value, generation, member_revision = validate_member_entry(
            members.get(client_id),
            member_id=client_id,
            expected_sub_cluster="sglang_owner",
            expected_ip=local_ip,
            external=True,
        )
        metadata = require_dict(member_value.get("metadata"), f"member {client_id}.metadata")
        require(
            metadata.get("shared_storage_node_id") == local_owner_id,
            f"external {client_id} is not bound to local owner",
        )
        require(
            metadata.get("shared_storage_node_start_time") == str(local_generation),
            f"external {client_id} is bound to stale local-owner generation",
        )
        ready_revision, backend_epoch = validate_transfer_ready(
            ready.get(client_id),
            member_id=client_id,
            generation=generation,
            member_revision=member_revision,
        )
        edge_name = f"{client_id}->{remote_owner_id}"
        require(edge_name in edges, f"external TE edge is missing: {edge_name}")
        edge = require_dict(edges[edge_name], f"TE edge {edge_name}")
        require(not edge.get("missing", False), f"external TE edge is missing: {edge_name}")
        edge_revision = require_int(
            edge.get("mod_revision"), f"TE edge {edge_name}.mod_revision", minimum=1
        )
        require(
            edge_revision >= max(ready_revision, remote_ready_revision),
            f"TE edge {edge_name} predates the current endpoint generations",
        )
        raw_edge_value = require_text(edge.get("value_text"), f"TE edge {edge_name}.value")
        require(
            raw_edge_value.strip() == "closed",
            f"TE edge {edge_name} is not direct closed: {raw_edge_value!r}",
        )
        clients.append(
            {
                "id": client_id,
                "node_start_time": generation,
                "member_revision": member_revision,
                "transfer_ready_revision": ready_revision,
                "backend_epoch": backend_epoch,
                "shared_storage_node_id": local_owner_id,
                "shared_storage_node_start_time": local_generation,
            }
        )
        edge_summaries.append(
            {
                "from": client_id,
                "from_node_start_time": generation,
                "from_backend_epoch": backend_epoch,
                "to": remote_owner_id,
                "to_node_start_time": remote_generation,
                "to_backend_epoch": remote_backend_epoch,
                "mod_revision": edge_revision,
                "value": raw_edge_value,
            }
        )

    summary = {
        "cluster_name": cluster_name,
        "local_owner": {
            "id": local_owner_id,
            "node_start_time": local_generation,
            "member_revision": local_member_revision,
            "transfer_ready_revision": local_ready_revision,
            "backend_epoch": local_backend_epoch,
        },
        "remote_owner": {
            "id": remote_owner_id,
            "node_start_time": remote_generation,
            "member_revision": remote_member_revision,
            "transfer_ready_revision": remote_ready_revision,
            "backend_epoch": remote_backend_epoch,
        },
        "clients": clients,
        "te_edges": edge_summaries,
    }
    if baseline is not None:
        baseline_clients = {
            require_text(item.get("id"), "baseline.clients[].id"): item
            for item in require_list(baseline.get("clients"), "baseline.clients")
        }
        current_clients = {item["id"]: item for item in clients}
        require(set(current_clients) == set(baseline_clients), "monitored client set changed")
        for role in ("local_owner", "remote_owner"):
            current = require_dict(summary.get(role), role)
            expected = require_dict(baseline.get(role), f"baseline.{role}")
            require(
                current.get("node_start_time") == expected.get("node_start_time"),
                f"{role} generation changed during formal window",
            )
            require(
                current.get("backend_epoch") == expected.get("backend_epoch"),
                f"{role} transfer backend epoch changed during formal window",
            )
            for field in ("member_revision", "transfer_ready_revision"):
                require(
                    require_int(current.get(field), f"{role}.{field}", minimum=1)
                    == require_int(expected.get(field), f"baseline.{role}.{field}", minimum=1),
                    f"{role} {field} changed during formal window",
                )
        for client_id, current in current_clients.items():
            expected = require_dict(baseline_clients[client_id], f"baseline client {client_id}")
            require(
                current.get("node_start_time") == expected.get("node_start_time"),
                f"external {client_id} generation changed during formal window",
            )
            require(
                current.get("backend_epoch") == expected.get("backend_epoch"),
                f"external {client_id} transfer backend epoch changed during formal window",
            )
            for field in ("member_revision", "transfer_ready_revision"):
                require(
                    require_int(current.get(field), f"external {client_id}.{field}", minimum=1)
                    == require_int(
                        expected.get(field),
                        f"baseline external {client_id}.{field}",
                        minimum=1,
                    ),
                    f"external {client_id} {field} changed during formal window",
                )
        baseline_edges = {
            require_text(item.get("from"), "baseline.te_edges[].from"): item
            for item in require_list(baseline.get("te_edges"), "baseline.te_edges")
        }
        for edge in edge_summaries:
            expected = require_dict(
                baseline_edges.get(edge["from"]), f"baseline edge {edge['from']}"
            )
            require(
                edge["mod_revision"]
                == require_int(expected.get("mod_revision"), "baseline edge revision", minimum=1),
                f"external TE edge revision changed during formal window: {edge['from']}",
            )
    return summary


def validate_probe(
    raw: Any,
    *,
    client: dict[str, Any],
    client_generation: int,
    cluster_name: str,
    local_owner_id: str,
    local_generation: int,
    remote_owner_id: str,
    remote_generation: int,
    gpu_fabric: dict[str, Any],
    cpu_fabric: dict[str, Any],
    forbidden_live_identities: set[str],
) -> dict[str, Any]:
    client_id = require_text(client.get("id"), "expected client id")
    probe = require_dict(raw, f"probe {client_id}")
    require(
        probe.get("schema") == "fluxon_f_remote_gpu_probe_bundle_v1",
        f"probe {client_id} bundle schema mismatch",
    )
    require(probe.get("client_config_id") == client_id, f"probe {client_id} config id mismatch")
    require(
        probe.get("client_node_start_time") == client_generation,
        f"probe {client_id} targets a stale client generation",
    )
    writer = require_dict(probe.get("writer"), f"probe {client_id}.writer")
    reader = require_dict(probe.get("reader"), f"probe {client_id}.reader")
    for side_name, side in (("writer", writer), ("reader", reader)):
        require(
            side.get("schema") == "fluxon_f_remote_gpu_probe_record_v2",
            f"probe {client_id} {side_name} record schema mismatch",
        )
        require(side.get("mode") == side_name, f"probe {client_id} {side_name} mode mismatch")
        require(
            side.get("cluster_name") == cluster_name,
            f"probe {client_id} {side_name} cluster mismatch",
        )
        require(
            side.get("readiness_declaration_scope") == "audit_only_not_enforcement",
            f"probe {client_id} {side_name} misstates readiness declaration",
        )
    require(writer.get("status") == "written", f"probe {client_id} writer did not finish")
    require(reader.get("status") == "passed", f"probe {client_id} reader did not pass")
    require(
        writer.get("target_client_config_id") == client_id,
        f"probe {client_id} writer target mismatch",
    )
    for side_name, side, host in (
        ("writer", writer, cpu_fabric),
        ("reader", reader, gpu_fabric),
    ):
        execution = require_dict(
            side.get("execution_host"), f"probe {client_id}.{side_name}.execution_host"
        )
        require(
            execution.get("hostname") == host["hostname"],
            f"probe {client_id} {side_name} executed on the wrong hostname",
        )
        require(
            execution.get("expected_hostname") == host["hostname"],
            f"probe {client_id} {side_name} expected_hostname mismatch",
        )
        execution_ips = require_list(
            execution.get("ips"), f"probe {client_id}.{side_name}.execution_host.ips"
        )
        require(
            host["ip"] in execution_ips
            and execution.get("expected_ip") == host["ip"],
            f"probe {client_id} {side_name} executed on the wrong IP",
        )
        require(
            execution.get("boot_id") == host["boot_id"],
            f"probe {client_id} {side_name} boot identity mismatch",
        )
        require(
            execution.get("pid1_start_time_ticks")
            == host["pid1_start_time_ticks"],
            f"probe {client_id} {side_name} PID1 identity mismatch",
        )
        require_int(
            execution.get("pid"),
            f"probe {client_id}.{side_name}.execution_host.pid",
            minimum=1,
        )
        require_int(
            execution.get("process_start_time_ticks"),
            f"probe {client_id}.{side_name}.execution_host.process_start_time_ticks",
            minimum=1,
        )
        config_sha = require_text(
            side.get("config_sha256"), f"probe {client_id}.{side_name}.config_sha256"
        )
        require(len(config_sha) == 64, f"probe {client_id} {side_name} config SHA256 invalid")
        devices = require_list(
            side.get("rdma_devices"), f"probe {client_id}.{side_name}.rdma_devices"
        )
        require(
            sorted(devices) == sorted(host["devices"]),
            f"probe {client_id} {side_name} RDMA device set mismatch",
        )
    source_binding = require_dict(
        writer.get("source_binding"), f"probe {client_id}.writer.source_binding"
    )
    require(
        writer.get("source_binding_revalidated_after_io") is True,
        f"probe {client_id} writer did not revalidate source binding after Put",
    )
    require(
        source_binding.get("proof_kind") == "runtime_external_owner_shared_binding_v1",
        f"probe {client_id} writer lacks runtime source proof",
    )
    require(
        source_binding.get("node_id") == remote_owner_id,
        f"probe {client_id} writer runtime source owner mismatch",
    )
    require(
        source_binding.get("node_start_time") == remote_generation,
        f"probe {client_id} writer runtime source generation mismatch",
    )
    require(
        writer.get("source_owner_id") == source_binding.get("node_id"),
        f"probe {client_id} writer source assertion is not runtime-bound",
    )
    require(
        writer.get("source_owner_node_start_time")
        == source_binding.get("node_start_time"),
        f"probe {client_id} writer source generation assertion is not runtime-bound",
    )
    source_len = require_int(
        source_binding.get("segment_len"),
        f"probe {client_id}.writer.source_binding.segment_len",
        minimum=1,
    )
    require(
        source_binding.get("mmap_size") == source_len,
        f"probe {client_id} writer source mmap length mismatch",
    )
    require(
        writer.get("source_owner_configured_dram") == source_len,
        f"probe {client_id} writer source configured/runtime length mismatch",
    )
    require(
        source_binding.get("runtime_segment_label") == "external_owner:0"
        and source_binding.get("published_segment_label") == "cpu:0",
        f"probe {client_id} writer source labels mismatch",
    )
    source_shared_sha = require_text(
        source_binding.get("shared_json_sha256"),
        f"probe {client_id}.writer.source_binding.shared_json_sha256",
    )
    require(len(source_shared_sha) == 64, f"probe {client_id} source shared.json hash invalid")
    local_binding = require_dict(
        reader.get("bound_local_owner"), f"probe {client_id}.reader.bound_local_owner"
    )
    require(
        reader.get("local_owner_binding_revalidated_after_io") is True,
        f"probe {client_id} reader did not revalidate local-owner binding after Get",
    )
    require(
        local_binding.get("proof_kind") == "runtime_external_owner_shared_binding_v1",
        f"probe {client_id} reader lacks runtime local-owner binding",
    )
    require(
        local_binding.get("node_id") == local_owner_id,
        f"probe {client_id} reader local-owner binding mismatch",
    )
    require(
        local_binding.get("node_start_time") == local_generation,
        f"probe {client_id} reader local-owner generation mismatch",
    )
    local_len = require_int(
        local_binding.get("segment_len"),
        f"probe {client_id}.reader.bound_local_owner.segment_len",
        minimum=1,
    )
    require(
        local_binding.get("mmap_size") == local_len,
        f"probe {client_id} reader local-owner mmap length mismatch",
    )
    require(
        local_binding.get("runtime_segment_label") == "external_owner:0"
        and local_binding.get("published_segment_label") == "cpu:0",
        f"probe {client_id} reader local-owner labels mismatch",
    )
    local_shared_sha = require_text(
        local_binding.get("shared_json_sha256"),
        f"probe {client_id}.reader.bound_local_owner.shared_json_sha256",
    )
    require(len(local_shared_sha) == 64, f"probe {client_id} local shared.json hash invalid")
    for binding_name, binding in (("source", source_binding), ("local", local_binding)):
        configured_root = Path(
            require_text(
                binding.get("configured_share_mem_root"),
                f"probe {client_id}.{binding_name}.configured_share_mem_root",
            )
        )
        scoped_path = Path(
            require_text(
                binding.get("share_mem_path"),
                f"probe {client_id}.{binding_name}.share_mem_path",
            )
        )
        require(
            configured_root.is_absolute() and scoped_path.is_absolute(),
            f"probe {client_id} {binding_name} owner paths are not absolute",
        )
        require(
            scoped_path.name == cluster_name,
            f"probe {client_id} {binding_name} owner path is not cluster-scoped",
        )
        require(
            Path(require_text(binding.get("shared_json_path"), "shared_json_path"))
            == scoped_path / "shared.json"
            and Path(require_text(binding.get("mmap_path"), "mmap_path"))
            == scoped_path / "mmap.file",
            f"probe {client_id} {binding_name} owner evidence paths mismatch",
        )
        require(
            binding.get("runtime_write_mapping_present") is True
            and binding.get("runtime_read_mapping_present") is True,
            f"probe {client_id} {binding_name} owner mapping is incomplete",
        )
    require(
        reader.get("planned_source_scope") == "remote_from_bound_local_owner",
        f"probe {client_id} reader source scope is not remote",
    )
    require_bool(writer.get("remote_only"), f"probe {client_id}.writer.remote_only")
    require(writer.get("remote_only") is True, f"probe {client_id} writer is not remote-only")
    require(writer.get("make_replica_task") is False, f"probe {client_id} writer enabled replication")
    require(
        writer.get("make_replica_task_mask") == [False],
        f"probe {client_id} writer replica mask is not disabled",
    )
    require(
        writer.get("atomic_group_lens") == [1],
        f"probe {client_id} writer atomic geometry mismatch",
    )
    require(writer.get("write_through") is True, f"probe {client_id} writer is not write-through")
    require(reader.get("client_config_id") == client_id, f"probe {client_id} reader config mismatch")
    require(
        reader.get("client_node_start_time") == client_generation,
        f"probe {client_id} reader generation mismatch",
    )
    require(
        reader.get("gpu_device") == client.get("gpu_device"),
        f"probe {client_id} used the wrong GPU",
    )
    require(reader.get("gpu_remote_indices") == [0], f"probe {client_id} did not select one remote GPU source")
    require_int(reader.get("registration_id"), f"probe {client_id}.registration_id", minimum=1)
    key = require_text(writer.get("key"), f"probe {client_id}.writer.key")
    require(reader.get("key") == key, f"probe {client_id} key mismatch")
    size = require_int(writer.get("size"), f"probe {client_id}.writer.size", minimum=1)
    require(reader.get("size") == size, f"probe {client_id} size mismatch")
    writer_sha = require_text(writer.get("sha256"), f"probe {client_id}.writer.sha256")
    expected_sha = require_text(reader.get("expected_sha256"), f"probe {client_id}.reader.expected_sha256")
    actual_sha = require_text(reader.get("actual_sha256"), f"probe {client_id}.reader.actual_sha256")
    require(len(writer_sha) == 64, f"probe {client_id} writer SHA256 length is invalid")
    require(writer_sha == expected_sha == actual_sha, f"probe {client_id} payload hash mismatch")
    timings = require_dict(reader.get("terminal_timing"), f"probe {client_id}.terminal_timing")
    for field in ("transfer_wall_us", "finish_wait_us", "terminal_to_consume_us"):
        require_int(timings.get(field), f"probe {client_id}.terminal_timing.{field}")
    require_bool(
        timings.get("terminal_before_consume"),
        f"probe {client_id}.terminal_timing.terminal_before_consume",
    )
    require(
        reader.get("terminal_timing_observed_after_get_transfer_gpu") is True,
        f"probe {client_id} terminal timing was not captured at terminal",
    )
    reader_probe_instance_key = require_text(
        reader.get("probe_instance_key"), f"probe {client_id}.reader.probe_instance_key"
    )
    writer_probe_instance_key = require_text(
        writer.get("probe_instance_key"), f"probe {client_id}.writer.probe_instance_key"
    )
    require(
        reader_probe_instance_key != client_id and writer_probe_instance_key != client_id,
        f"probe {client_id} illegally reused live identity",
    )
    require(
        reader_probe_instance_key not in forbidden_live_identities
        and writer_probe_instance_key not in forbidden_live_identities,
        f"probe {client_id} reused a live owner/client identity",
    )
    require(
        reader_probe_instance_key != writer_probe_instance_key,
        f"probe {client_id} writer/reader identities are not unique",
    )
    return {
        "client_config_id": client_id,
        "client_node_start_time": client_generation,
        "writer_probe_instance_key": writer_probe_instance_key,
        "reader_probe_instance_key": reader_probe_instance_key,
        "key": key,
        "size": size,
        "sha256": actual_sha,
        "gpu_device": reader["gpu_device"],
        "writer_config_sha256": writer["config_sha256"],
        "reader_config_sha256": reader["config_sha256"],
        "source_owner_id": remote_owner_id,
        "source_owner_node_start_time": remote_generation,
        "source_proof_kind": source_binding["proof_kind"],
        "bound_local_owner_id": local_owner_id,
        "bound_local_owner_node_start_time": local_generation,
        "identity_scope": "independent_ephemeral_probe_derived_from_live_client_config",
    }


def validate_evidence(evidence: Any) -> dict[str, Any]:
    root = require_dict(evidence, "evidence")
    require(root.get("schema") == SCHEMA, f"unsupported evidence schema: {root.get('schema')!r}")
    cluster_name = require_text(root.get("cluster_name"), "cluster_name")
    expected = require_dict(root.get("expected"), "expected")
    local_owner_id = require_text(expected.get("local_owner_id"), "expected.local_owner_id")
    remote_owner_id = require_text(expected.get("remote_owner_id"), "expected.remote_owner_id")
    clients = require_list(expected.get("clients"), "expected.clients")
    require(len(clients) == 2, "expected.clients must contain exactly two clients")
    normalized_clients: list[dict[str, Any]] = []
    for index, raw in enumerate(clients):
        client = require_dict(raw, f"expected.clients[{index}]")
        client_id = require_text(client.get("id"), f"expected.clients[{index}].id")
        port = require_int(client.get("port"), f"expected.clients[{index}].port", minimum=1)
        gpu_device = require_int(
            client.get("gpu_device"), f"expected.clients[{index}].gpu_device", minimum=0
        )
        normalized_clients.append({"id": client_id, "port": port, "gpu_device": gpu_device})
    require(
        len({item["id"] for item in normalized_clients}) == 2,
        "external client ids must be unique",
    )
    require(
        len({item["port"] for item in normalized_clients}) == 2,
        "external client ports must be unique",
    )
    require(
        len({item["gpu_device"] for item in normalized_clients}) == 2,
        "the two external clients must use different physical GPUs",
    )

    fabric = require_dict(root.get("fabric"), "fabric")
    gpu_fabric = validate_fabric_node(
        fabric.get("gpu"),
        role="gpu",
        expected_hostname=require_text(expected.get("gpu_hostname"), "expected.gpu_hostname"),
        expected_ip=require_text(expected.get("gpu_ip"), "expected.gpu_ip"),
        expected_devices=[
            require_text(item, "expected.gpu_hcas[]")
            for item in require_list(expected.get("gpu_hcas"), "expected.gpu_hcas")
        ],
    )
    cpu_fabric = validate_fabric_node(
        fabric.get("cpu"),
        role="cpu",
        expected_hostname=require_text(expected.get("cpu_hostname"), "expected.cpu_hostname"),
        expected_ip=require_text(expected.get("cpu_ip"), "expected.cpu_ip"),
        expected_devices=[
            require_text(item, "expected.cpu_hcas[]")
            for item in require_list(expected.get("cpu_hcas"), "expected.cpu_hcas")
        ],
    )
    all_sm_lids = gpu_fabric["sm_lids"] + cpu_fabric["sm_lids"]
    require(len(set(all_sm_lids)) == 1, f"selected HCAs do not share one SM LID: {all_sm_lids}")

    control_plane = validate_control_plane_snapshot(
        root.get("etcd"),
        cluster_name=cluster_name,
        local_owner_id=local_owner_id,
        remote_owner_id=remote_owner_id,
        local_ip=require_text(expected.get("gpu_ip"), "expected.gpu_ip"),
        remote_ip=require_text(expected.get("cpu_ip"), "expected.cpu_ip"),
        client_ids=[item["id"] for item in normalized_clients],
    )
    local_generation = control_plane["local_owner"]["node_start_time"]
    remote_generation = control_plane["remote_owner"]["node_start_time"]
    client_generations = {
        item["id"]: item["node_start_time"] for item in control_plane["clients"]
    }
    forbidden_live_identities = {
        local_owner_id,
        remote_owner_id,
        *client_generations.keys(),
    }

    probes = require_list(root.get("probes"), "probes")
    require(len(probes) == 2, "exactly two data probes are required")
    probe_by_client: dict[str, Any] = {}
    for raw in probes:
        record = require_dict(raw, "probes[]")
        client_id = require_text(record.get("client_config_id"), "probes[].client_config_id")
        require(client_id not in probe_by_client, f"duplicate probe for client {client_id}")
        probe_by_client[client_id] = record
    probe_summaries = [
        validate_probe(
            probe_by_client.get(client["id"]),
            client=client,
            client_generation=client_generations[client["id"]],
            cluster_name=cluster_name,
            local_owner_id=local_owner_id,
            local_generation=local_generation,
            remote_owner_id=remote_owner_id,
            remote_generation=remote_generation,
            gpu_fabric=gpu_fabric,
            cpu_fabric=cpu_fabric,
            forbidden_live_identities=forbidden_live_identities,
        )
        for client in normalized_clients
    ]
    require(
        len({item["key"] for item in probe_summaries}) == 2,
        "the two clients must use different remote-only probe keys",
    )
    require(
        len(
            {
                instance
                for item in probe_summaries
                for instance in (
                    item["writer_probe_instance_key"],
                    item["reader_probe_instance_key"],
                )
            }
        )
        == 4,
        "all four data-probe identities must be unique",
    )
    require(
        len({item["reader_config_sha256"] for item in probe_summaries}) == 2,
        "the two GPU probes must derive from different port-scoped client configs",
    )
    return {
        "schema": SUMMARY_SCHEMA,
        "status": "passed",
        "cluster_name": cluster_name,
        "sm_lid": all_sm_lids[0],
        "control_plane_scope": {
            "identity": "live_sglang_external_clients",
            "preflight": "current_generation_transfer_ready_and_exact_closed_te_edge",
            "formal_window_requirement": "monitor_ready_and_pid_alive_on_every_replay_dispatch_then_clean_final_summary",
        },
        "data_plane_scope": {
            "identity": "independent_ephemeral_probes_derived_from_each_live_client_config",
            "proof": "30448_remote_owner_generation_runtime_binding_to_31772_registered_gpu_get_payload_hash_and_terminal_timing",
            "does_not_replace_live_identity_monitor": True,
            "does_not_claim_live_sglang_identity_executed_probe": True,
        },
        "local_owner": {
            "id": local_owner_id,
            "node_start_time": local_generation,
            "transfer_ready_revision": control_plane["local_owner"]["transfer_ready_revision"],
        },
        "remote_owner": {
            "id": remote_owner_id,
            "node_start_time": remote_generation,
            "backend_epoch": control_plane["remote_owner"]["backend_epoch"],
        },
        "te_edges": control_plane["te_edges"],
        "probes": probe_summaries,
    }


def assemble_evidence(args: argparse.Namespace) -> dict[str, Any]:
    clients = [
        {"id": args.client_id[0], "port": args.client_port[0], "gpu_device": args.gpu_device[0]},
        {"id": args.client_id[1], "port": args.client_port[1], "gpu_device": args.gpu_device[1]},
    ]
    evidence = {
        "schema": SCHEMA,
        "cluster_name": args.cluster_name,
        "expected": {
            "gpu_hostname": args.gpu_hostname,
            "gpu_ip": args.gpu_ip,
            "gpu_hcas": args.gpu_hca,
            "cpu_hostname": args.cpu_hostname,
            "cpu_ip": args.cpu_ip,
            "cpu_hcas": args.cpu_hca,
            "local_owner_id": args.local_owner_id,
            "remote_owner_id": args.remote_owner_id,
            "clients": clients,
        },
        "fabric": {
            "gpu": read_json(args.gpu_fabric),
            "cpu": read_json(args.cpu_fabric),
        },
        "etcd": read_json(args.etcd_snapshot),
        "probes": [read_json(path) for path in args.probe],
    }
    summary = validate_evidence(evidence)
    write_json_atomic(args.output, evidence)
    if args.summary_output is not None:
        write_json_atomic(args.summary_output, summary)
    return summary


def monitor_etcd(args: argparse.Namespace) -> dict[str, Any]:
    """Continuously invalidate a formal window if live client edges drift."""

    for path, label in (
        (args.log, "monitor log"),
        (args.pid_file, "monitor pid file"),
        (args.ready_file, "monitor ready file"),
        (args.invalid_marker, "invalid marker"),
        (args.stop_file, "stop file"),
        (args.summary_output, "monitor summary"),
    ):
        require(not path.exists(), f"{label} already exists: {path}")
    baseline_sha256_before = sha256_file(args.baseline_etcd)
    baseline_snapshot = read_json(args.baseline_etcd)
    baseline_sha256_after = sha256_file(args.baseline_etcd)
    require(
        baseline_sha256_before == baseline_sha256_after,
        "baseline etcd snapshot changed while monitor was binding it",
    )
    baseline = validate_control_plane_snapshot(
        baseline_snapshot,
        cluster_name=args.cluster_name,
        local_owner_id=args.local_owner_id,
        remote_owner_id=args.remote_owner_id,
        local_ip=args.local_ip,
        remote_ip=args.remote_ip,
        client_ids=args.client_id,
    )
    started_ns = time.time_ns()
    started_monotonic = time.monotonic()
    pid_record = {
        "schema": "fluxon_f_direct_rdma_monitor_pid_v1",
        "pid": os.getpid(),
        "start_time_ticks": proc_start_time_ticks(os.getpid()),
        "boot_id": boot_id(),
        "started_time_ns": started_ns,
        "baseline_etcd_path": str(args.baseline_etcd),
        "baseline_etcd_sha256": baseline_sha256_before,
    }
    write_json_strict_exclusive(args.pid_file, pid_record)
    append_jsonl(
        args.log,
        {
            "schema": "fluxon_f_direct_rdma_monitor_event_v1",
            "event": "started",
            "time_ns": started_ns,
            "pid": os.getpid(),
            "poll_seconds": args.poll_seconds,
            "heartbeat_seconds": args.heartbeat_seconds,
            "minimum_runtime_seconds": args.minimum_runtime_seconds,
            "baseline": baseline,
        },
    )
    samples = 0
    next_heartbeat = time.monotonic()
    latest = baseline
    old_signal_handlers: dict[int, Any] = {}

    def invalidate_on_signal(signum: int, _frame: Any) -> None:
        raise GateError(
            f"direct-RDMA monitor received termination signal {signal.Signals(signum).name}"
        )

    try:
        for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            old_signal_handlers[signum] = signal.signal(signum, invalidate_on_signal)
        while not args.stop_file.exists():
            require(
                not args.invalid_marker.exists(),
                "invalid marker appeared while direct-RDMA monitor was running",
            )
            snapshot = capture_etcd_snapshot(
                etcdctl=args.etcdctl,
                endpoint=args.endpoint,
                cluster_name=args.cluster_name,
                local_owner_id=args.local_owner_id,
                remote_owner_id=args.remote_owner_id,
                client_ids=args.client_id,
            )
            latest = validate_control_plane_snapshot(
                snapshot,
                cluster_name=args.cluster_name,
                local_owner_id=args.local_owner_id,
                remote_owner_id=args.remote_owner_id,
                local_ip=args.local_ip,
                remote_ip=args.remote_ip,
                client_ids=args.client_id,
                baseline=baseline,
            )
            samples += 1
            if samples == 1:
                ready_record = {
                    "schema": "fluxon_f_direct_rdma_monitor_ready_v1",
                    "status": "ready",
                    "time_ns": time.time_ns(),
                    "pid": pid_record["pid"],
                    "start_time_ticks": pid_record["start_time_ticks"],
                    "boot_id": pid_record["boot_id"],
                    "baseline_etcd_sha256": baseline_sha256_before,
                    "first_live_control_plane": latest,
                }
                write_json_strict_exclusive(args.ready_file, ready_record)
            now = time.monotonic()
            if samples == 1 or now >= next_heartbeat:
                append_jsonl(
                    args.log,
                    {
                        "schema": "fluxon_f_direct_rdma_monitor_event_v1",
                        "event": "heartbeat",
                        "time_ns": time.time_ns(),
                        "samples": samples,
                        "control_plane": latest,
                    },
                )
                next_heartbeat = now + args.heartbeat_seconds
            time.sleep(args.poll_seconds)
        require(samples >= 1, "direct-RDMA monitor stopped before its first live sample")
        elapsed_seconds = time.monotonic() - started_monotonic
        require(
            elapsed_seconds >= args.minimum_runtime_seconds,
            "direct-RDMA monitor stopped before the required formal window: "
            f"elapsed={elapsed_seconds:.6f}s "
            f"minimum={args.minimum_runtime_seconds:.6f}s",
        )
    except (GateError, OSError, subprocess.SubprocessError) as exc:
        invalid = {
            "schema": "fluxon_f_direct_rdma_monitor_invalid_v1",
            "status": "invalid",
            "time_ns": time.time_ns(),
            "samples": samples,
            "monitor_identity": pid_record,
            "error": str(exc),
            "baseline": baseline,
            "latest_passed": latest,
        }
        write_json_exclusive(args.invalid_marker, invalid)
        append_jsonl(
            args.log,
            {
                "schema": "fluxon_f_direct_rdma_monitor_event_v1",
                "event": "invalid",
                **invalid,
            },
        )
        raise GateError(str(exc)) from exc
    finally:
        for signum, handler in old_signal_handlers.items():
            signal.signal(signum, handler)
    stopped = {
        "schema": "fluxon_f_direct_rdma_monitor_summary_v1",
        "status": "stopped_cleanly",
        "time_ns": time.time_ns(),
        "samples": samples,
        "elapsed_seconds": elapsed_seconds,
        "minimum_runtime_seconds": args.minimum_runtime_seconds,
        "monitor_identity": pid_record,
        "ready_sha256": sha256_file(args.ready_file),
        "baseline": baseline,
        "latest": latest,
    }
    append_jsonl(
        args.log,
        {
            "schema": "fluxon_f_direct_rdma_monitor_event_v1",
            "event": "stopped_cleanly",
            **stopped,
        },
    )
    write_json_strict_exclusive(args.summary_output, stopped)
    return stopped


def validate_monitor_artifacts(
    *,
    pid_file: Path,
    ready_file: Path,
    invalid_marker: Path,
    summary_output: Path,
    expect: str,
) -> dict[str, Any]:
    """Fail closed on monitor death, stale PID reuse, invalidation, or short final run."""

    require(expect in {"live", "final"}, "monitor artifact expectation must be live or final")
    require(not invalid_marker.exists(), f"direct-RDMA invalid marker exists: {invalid_marker}")
    pid_record = require_dict(read_json(pid_file), "monitor pid record")
    ready = require_dict(read_json(ready_file), "monitor ready record")
    require(
        pid_record.get("schema") == "fluxon_f_direct_rdma_monitor_pid_v1",
        "monitor pid schema mismatch",
    )
    require(
        ready.get("schema") == "fluxon_f_direct_rdma_monitor_ready_v1"
        and ready.get("status") == "ready",
        "monitor ready record is invalid",
    )
    for field in ("pid", "start_time_ticks", "boot_id", "baseline_etcd_sha256"):
        require(
            ready.get(field) == pid_record.get(field),
            f"monitor ready/pid identity mismatch: {field}",
        )
    pid = require_int(pid_record.get("pid"), "monitor pid", minimum=1)
    expected_start = require_int(
        pid_record.get("start_time_ticks"), "monitor start_time_ticks", minimum=1
    )
    if expect == "live":
        require(not summary_output.exists(), "monitor already has a final summary")
        require(
            pid_record.get("boot_id") == boot_id(),
            "monitor host boot identity changed",
        )
        require(
            proc_start_time_ticks(pid) == expected_start,
            "direct-RDMA monitor PID is dead or has been reused",
        )
        return {
            "schema": "fluxon_f_direct_rdma_monitor_check_v1",
            "status": "live",
            "pid": pid,
            "start_time_ticks": expected_start,
        }

    summary = require_dict(read_json(summary_output), "monitor final summary")
    require(
        summary.get("schema") == "fluxon_f_direct_rdma_monitor_summary_v1"
        and summary.get("status") == "stopped_cleanly",
        "monitor final summary is not clean",
    )
    identity = require_dict(summary.get("monitor_identity"), "summary.monitor_identity")
    require(identity == pid_record, "monitor final summary identity mismatch")
    require_int(summary.get("samples"), "monitor final samples", minimum=1)
    elapsed = summary.get("elapsed_seconds")
    minimum = summary.get("minimum_runtime_seconds")
    require(
        isinstance(elapsed, (int, float))
        and not isinstance(elapsed, bool)
        and isinstance(minimum, (int, float))
        and not isinstance(minimum, bool)
        and elapsed >= minimum >= 0,
        "monitor final runtime is shorter than required",
    )
    require(
        summary.get("ready_sha256") == sha256_file(ready_file),
        "monitor final summary does not bind the ready record",
    )
    return {
        "schema": "fluxon_f_direct_rdma_monitor_check_v1",
        "status": "final",
        "pid": pid,
        "samples": summary["samples"],
        "elapsed_seconds": elapsed,
        "minimum_runtime_seconds": minimum,
    }


def add_common_identity_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--cluster-name", required=True)
    parser.add_argument("--local-owner-id", required=True)
    parser.add_argument("--remote-owner-id", required=True)
    parser.add_argument("--client-id", action="append", required=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    hca = subparsers.add_parser("capture-hca")
    hca.add_argument("--role", choices=("gpu", "cpu"), required=True)
    hca.add_argument("--expected-hostname", required=True)
    hca.add_argument("--expected-ip", required=True)
    hca.add_argument("--device", action="append", required=True)
    hca.add_argument("--output", type=Path, required=True)

    etcd = subparsers.add_parser("capture-etcd")
    add_common_identity_args(etcd)
    etcd.add_argument("--etcdctl", type=Path, required=True)
    etcd.add_argument("--endpoint", required=True)
    etcd.add_argument("--output", type=Path, required=True)

    monitor = subparsers.add_parser("monitor-etcd")
    add_common_identity_args(monitor)
    monitor.add_argument("--local-ip", required=True)
    monitor.add_argument("--remote-ip", required=True)
    monitor.add_argument("--etcdctl", type=Path, required=True)
    monitor.add_argument("--endpoint", required=True)
    monitor.add_argument("--baseline-etcd", type=Path, required=True)
    monitor.add_argument("--poll-seconds", type=float, default=0.5)
    monitor.add_argument("--heartbeat-seconds", type=float, default=5.0)
    monitor.add_argument("--stop-file", type=Path, required=True)
    monitor.add_argument("--invalid-marker", type=Path, required=True)
    monitor.add_argument("--log", type=Path, required=True)
    monitor.add_argument("--pid-file", type=Path, required=True)
    monitor.add_argument("--ready-file", type=Path, required=True)
    monitor.add_argument("--summary-output", type=Path, required=True)
    monitor.add_argument("--minimum-runtime-seconds", type=float, required=True)

    check_monitor = subparsers.add_parser("check-monitor")
    check_monitor.add_argument("--pid-file", type=Path, required=True)
    check_monitor.add_argument("--ready-file", type=Path, required=True)
    check_monitor.add_argument("--invalid-marker", type=Path, required=True)
    check_monitor.add_argument("--summary-output", type=Path, required=True)
    check_monitor.add_argument("--expect", choices=("live", "final"), required=True)

    validate = subparsers.add_parser("validate")
    validate.add_argument("--evidence", type=Path, required=True)
    validate.add_argument("--summary-output", type=Path)

    assemble = subparsers.add_parser("assemble")
    add_common_identity_args(assemble)
    assemble.add_argument("--gpu-hostname", required=True)
    assemble.add_argument("--gpu-ip", required=True)
    assemble.add_argument("--gpu-hca", action="append", required=True)
    assemble.add_argument("--cpu-hostname", required=True)
    assemble.add_argument("--cpu-ip", required=True)
    assemble.add_argument("--cpu-hca", action="append", required=True)
    assemble.add_argument("--client-port", type=int, action="append", required=True)
    assemble.add_argument("--gpu-device", type=int, action="append", required=True)
    assemble.add_argument("--gpu-fabric", type=Path, required=True)
    assemble.add_argument("--cpu-fabric", type=Path, required=True)
    assemble.add_argument("--etcd-snapshot", type=Path, required=True)
    assemble.add_argument("--probe", type=Path, action="append", required=True)
    assemble.add_argument("--output", type=Path, required=True)
    assemble.add_argument("--summary-output", type=Path)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.command == "capture-hca":
            snapshot = capture_hca_snapshot(
                role=args.role,
                expected_hostname=args.expected_hostname,
                expected_ip=args.expected_ip,
                devices=args.device,
            )
            write_json_atomic(args.output, snapshot)
            print(json.dumps(snapshot, sort_keys=True))
            return
        if args.command == "capture-etcd":
            require(len(args.client_id) == 2, "capture-etcd requires exactly two --client-id")
            snapshot = capture_etcd_snapshot(
                etcdctl=args.etcdctl,
                endpoint=args.endpoint,
                cluster_name=args.cluster_name,
                local_owner_id=args.local_owner_id,
                remote_owner_id=args.remote_owner_id,
                client_ids=args.client_id,
            )
            write_json_atomic(args.output, snapshot)
            print(json.dumps(snapshot, sort_keys=True))
            return
        if args.command == "monitor-etcd":
            require(len(args.client_id) == 2, "monitor-etcd requires exactly two --client-id")
            require(
                0.1 <= args.poll_seconds <= 5.0,
                "monitor-etcd poll seconds must be in [0.1, 5.0]",
            )
            require(
                args.heartbeat_seconds >= args.poll_seconds,
                "monitor-etcd heartbeat must be at least one poll interval",
            )
            require(
                args.minimum_runtime_seconds > 0,
                "monitor-etcd minimum runtime must be positive",
            )
            summary = monitor_etcd(args)
            print(json.dumps(summary, sort_keys=True))
            return
        if args.command == "check-monitor":
            status = validate_monitor_artifacts(
                pid_file=args.pid_file,
                ready_file=args.ready_file,
                invalid_marker=args.invalid_marker,
                summary_output=args.summary_output,
                expect=args.expect,
            )
            print(json.dumps(status, sort_keys=True))
            return
        if args.command == "validate":
            summary = validate_evidence(read_json(args.evidence))
            if args.summary_output is not None:
                write_json_atomic(args.summary_output, summary)
            print(json.dumps(summary, sort_keys=True))
            return
        if args.command == "assemble":
            for name in ("client_id", "client_port", "gpu_device", "probe"):
                require(len(getattr(args, name)) == 2, f"assemble requires exactly two --{name.replace('_', '-')}")
            summary = assemble_evidence(args)
            print(json.dumps(summary, sort_keys=True))
            return
        fail(f"unsupported command: {args.command}")
    except GateError as exc:
        print(f"Fluxon F direct-RDMA gate failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
