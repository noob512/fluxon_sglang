#!/usr/bin/env python3
"""Run and bind two CPU-writer -> external-client GPU Get probes.

The plan contains argv arrays, never shell strings.  Both CPU-owner writes must
finish before either GPU reader starts.  Every command writes a run-scoped JSON
record; this coordinator validates the pair and emits the two bundles consumed
by ``fluxon_f_rdma_gate.py``.  Any failure creates an exclusive invalid marker.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, NoReturn


PLAN_SCHEMA = "fluxon_f_remote_gpu_probe_plan_v1"
RECORD_SCHEMA = "fluxon_f_remote_gpu_probe_record_v2"
BUNDLE_SCHEMA = "fluxon_f_remote_gpu_probe_bundle_v1"
SUMMARY_SCHEMA = "fluxon_f_remote_gpu_probe_coordinator_summary_v1"


class CoordinatorError(RuntimeError):
    pass


def fail(message: str) -> NoReturn:
    raise CoordinatorError(message)


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


def require_int(value: Any, context: str, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        fail(f"{context} must be an integer >= {minimum}")
    return value


def canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CoordinatorError(f"cannot read JSON {path}: {exc}") from exc


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("xb") as stream:
        stream.write(canonical_json(value))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def write_invalid_once(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(canonical_json(value))
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        return


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_command(raw: Any, context: str) -> dict[str, Any]:
    command = require_dict(raw, context)
    argv = require_list(command.get("argv"), f"{context}.argv")
    require(argv and all(isinstance(item, str) and item for item in argv), f"{context}.argv must contain non-empty strings")
    evidence = Path(require_text(command.get("evidence"), f"{context}.evidence"))
    require(evidence.is_absolute(), f"{context}.evidence must be absolute")
    return {"argv": list(argv), "evidence": evidence}


def validate_plan(raw: Any) -> dict[str, Any]:
    plan = require_dict(raw, "plan")
    require(plan.get("schema") == PLAN_SCHEMA, "unsupported coordinator plan schema")
    clients = require_list(plan.get("clients"), "plan.clients")
    require(len(clients) == 2, "plan must contain exactly two clients")
    normalized = []
    for index, raw_client in enumerate(clients):
        client = require_dict(raw_client, f"plan.clients[{index}]")
        client_id = require_text(client.get("client_config_id"), f"plan.clients[{index}].client_config_id")
        generation = require_int(client.get("client_node_start_time"), f"plan.clients[{index}].client_node_start_time")
        bundle_output = Path(require_text(client.get("bundle_output"), f"plan.clients[{index}].bundle_output"))
        require(bundle_output.is_absolute(), f"plan.clients[{index}].bundle_output must be absolute")
        normalized.append(
            {
                "client_config_id": client_id,
                "client_node_start_time": generation,
                "writer": validate_command(client.get("writer"), f"plan.clients[{index}].writer"),
                "reader": validate_command(client.get("reader"), f"plan.clients[{index}].reader"),
                "bundle_output": bundle_output,
            }
        )
    require(len({item["client_config_id"] for item in normalized}) == 2, "client ids must be unique")
    paths = [
        path
        for item in normalized
        for path in (item["writer"]["evidence"], item["reader"]["evidence"], item["bundle_output"])
    ]
    require(len(set(paths)) == len(paths), "all evidence and bundle paths must be unique")
    timeout = require_int(plan.get("command_timeout_seconds", 180), "plan.command_timeout_seconds")
    require(timeout <= 600, "plan.command_timeout_seconds must be <= 600")
    summary_output = Path(require_text(plan.get("summary_output"), "plan.summary_output"))
    invalid_marker = Path(require_text(plan.get("invalid_marker"), "plan.invalid_marker"))
    require(summary_output.is_absolute(), "plan.summary_output must be absolute")
    require(invalid_marker.is_absolute(), "plan.invalid_marker must be absolute")
    require(
        summary_output not in paths
        and invalid_marker not in paths
        and summary_output != invalid_marker,
        "summary/invalid paths must be unique",
    )
    return {
        "clients": normalized,
        "command_timeout_seconds": timeout,
        "summary_output": summary_output,
        "invalid_marker": invalid_marker,
    }


def validate_binding(raw: Any, *, context: str) -> dict[str, Any]:
    binding = require_dict(raw, context)
    require(binding.get("proof_kind") == "runtime_external_owner_shared_binding_v1", f"{context} proof kind mismatch")
    require_text(binding.get("node_id"), f"{context}.node_id")
    require_int(binding.get("node_start_time"), f"{context}.node_start_time")
    require_int(binding.get("segment_len"), f"{context}.segment_len")
    require(binding.get("runtime_segment_label") == "external_owner:0", f"{context} runtime segment label mismatch")
    require(binding.get("published_segment_label") == "cpu:0", f"{context} published segment label mismatch")
    require(binding.get("mmap_size") == binding.get("segment_len"), f"{context} mmap size mismatch")
    require(binding.get("runtime_write_mapping_present") is True, f"{context} lacks write mapping")
    require(binding.get("runtime_read_mapping_present") is True, f"{context} lacks read mapping")
    digest = require_text(binding.get("shared_json_sha256"), f"{context}.shared_json_sha256")
    require(len(digest) == 64, f"{context} shared.json SHA256 length is invalid")
    configured_root = Path(
        require_text(binding.get("configured_share_mem_root"), f"{context}.configured_share_mem_root")
    )
    scoped_path = Path(require_text(binding.get("share_mem_path"), f"{context}.share_mem_path"))
    require(configured_root.is_absolute() and scoped_path.is_absolute(), f"{context} paths must be absolute")
    require(
        Path(require_text(binding.get("shared_json_path"), f"{context}.shared_json_path"))
        == scoped_path / "shared.json",
        f"{context} shared.json path mismatch",
    )
    require(
        Path(require_text(binding.get("mmap_path"), f"{context}.mmap_path"))
        == scoped_path / "mmap.file",
        f"{context} mmap path mismatch",
    )
    return binding


def validate_execution_host(raw: Any, context: str) -> dict[str, Any]:
    host = require_dict(raw, context)
    hostname = require_text(host.get("hostname"), f"{context}.hostname")
    require(host.get("expected_hostname") == hostname, f"{context} hostname assertion mismatch")
    ips = require_list(host.get("ips"), f"{context}.ips")
    require(
        host.get("expected_ip") in ips and isinstance(host.get("expected_ip"), str),
        f"{context} IP assertion mismatch",
    )
    boot_id = require_text(host.get("boot_id"), f"{context}.boot_id")
    require(len(boot_id) == 36, f"{context} boot_id is invalid")
    require_int(host.get("pid1_start_time_ticks"), f"{context}.pid1_start_time_ticks")
    require_int(host.get("pid"), f"{context}.pid")
    require_int(host.get("process_start_time_ticks"), f"{context}.process_start_time_ticks")
    return host


def build_bundle(
    *, client_config_id: str, client_node_start_time: int, writer_raw: Any, reader_raw: Any
) -> dict[str, Any]:
    writer = require_dict(writer_raw, f"writer {client_config_id}")
    reader = require_dict(reader_raw, f"reader {client_config_id}")
    for record, mode in ((writer, "writer"), (reader, "reader")):
        require(record.get("schema") == RECORD_SCHEMA, f"{mode} record schema mismatch")
        require(record.get("mode") == mode, f"{mode} record mode mismatch")
    require(writer.get("status") == "written", "writer did not finish")
    require(reader.get("status") == "passed", "reader did not pass")
    require(writer.get("target_client_config_id") == client_config_id, "writer target client mismatch")
    require(reader.get("client_config_id") == client_config_id, "reader client config mismatch")
    require(reader.get("client_node_start_time") == client_node_start_time, "reader live-client generation assertion mismatch")
    require(writer.get("cluster_name") == reader.get("cluster_name"), "writer/reader cluster mismatch")
    writer_host = validate_execution_host(writer.get("execution_host"), "writer.execution_host")
    reader_host = validate_execution_host(reader.get("execution_host"), "reader.execution_host")
    require(writer_host.get("hostname") != reader_host.get("hostname"), "writer and reader must execute on different hosts")
    for record, mode in ((writer, "writer"), (reader, "reader")):
        config_sha = require_text(record.get("config_sha256"), f"{mode}.config_sha256")
        require(len(config_sha) == 64, f"{mode} config SHA256 length is invalid")
        devices = require_list(record.get("rdma_devices"), f"{mode}.rdma_devices")
        require(devices and len(devices) == len(set(devices)), f"{mode} RDMA devices must be unique")
    source_binding = validate_binding(writer.get("source_binding"), context="writer.source_binding")
    local_binding = validate_binding(reader.get("bound_local_owner"), context="reader.bound_local_owner")
    require(writer.get("source_binding_revalidated_after_io") is True, "writer source binding was not revalidated after Put")
    require(reader.get("local_owner_binding_revalidated_after_io") is True, "reader local-owner binding was not revalidated after Get")
    require(writer.get("source_owner_id") == source_binding.get("node_id"), "writer source owner is not runtime-bound")
    require(writer.get("source_owner_node_start_time") == source_binding.get("node_start_time"), "writer source generation is not runtime-bound")
    require(writer.get("remote_only") is True, "writer is not remote-only")
    require(writer.get("write_through") is True, "writer is not write-through")
    require(writer.get("make_replica_task") is False, "writer enabled replication")
    require(writer.get("make_replica_task_mask") == [False], "writer replica mask is not disabled")
    require(writer.get("atomic_group_lens") == [1], "writer atomic geometry mismatch")
    require(reader.get("planned_source_scope") == "remote_from_bound_local_owner", "reader did not plan a remote source")
    require(reader.get("gpu_remote_indices") == [0], "reader did not select one remote GPU source")
    require(reader.get("terminal_timing_observed_after_get_transfer_gpu") is True, "reader terminal timing is not terminal")
    timing = require_dict(reader.get("terminal_timing"), "reader.terminal_timing")
    for field in ("transfer_wall_us", "finish_wait_us", "terminal_to_consume_us"):
        require_int(timing.get(field), f"reader.terminal_timing.{field}", minimum=0)
    require(
        isinstance(timing.get("terminal_before_consume"), bool),
        "reader.terminal_timing.terminal_before_consume must be boolean",
    )
    require(writer.get("readiness_declaration_scope") == "audit_only_not_enforcement", "writer misstates readiness declaration")
    require(reader.get("readiness_declaration_scope") == "audit_only_not_enforcement", "reader misstates readiness declaration")
    for field in ("key", "size", "seed"):
        require(writer.get(field) == reader.get(field), f"writer/reader {field} mismatch")
    require_int(writer.get("size"), "writer.size")
    require_int(writer.get("seed"), "writer.seed", minimum=0)
    writer_sha = require_text(writer.get("sha256"), "writer.sha256")
    require(writer_sha == reader.get("expected_sha256") == reader.get("actual_sha256"), "writer/reader payload hash mismatch")
    require(len(writer_sha) == 64, "payload SHA256 length is invalid")
    require(writer.get("probe_instance_key") != reader.get("probe_instance_key"), "writer and reader probe identities must differ")
    require(writer.get("probe_instance_key") != client_config_id, "writer reused the live client identity")
    require(reader.get("probe_instance_key") != client_config_id, "reader reused the live client identity")
    return {
        "schema": BUNDLE_SCHEMA,
        "client_config_id": client_config_id,
        "client_node_start_time": client_node_start_time,
        "writer": writer,
        "reader": reader,
    }


def run_command(command: dict[str, Any], *, timeout: int, phase: str, client_id: str) -> dict[str, Any]:
    started = time.monotonic_ns()
    result = subprocess.run(
        command["argv"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    elapsed_us = (time.monotonic_ns() - started) // 1_000
    audit = {
        "phase": phase,
        "client_config_id": client_id,
        "argv_sha256": hashlib.sha256(canonical_json(command["argv"])).hexdigest(),
        "returncode": result.returncode,
        "elapsed_us": elapsed_us,
        "stdout_sha256": hashlib.sha256(result.stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(result.stderr).hexdigest(),
    }
    if result.returncode != 0:
        tail = result.stderr[-2048:].decode("utf-8", errors="replace")
        fail(f"{phase} command failed for {client_id}: rc={result.returncode} stderr_tail={tail!r}")
    require(command["evidence"].is_file(), f"{phase} evidence is missing for {client_id}: {command['evidence']}")
    audit["evidence_sha256"] = sha256_file(command["evidence"])
    return audit


def execute_plan(plan: dict[str, Any]) -> dict[str, Any]:
    require(not plan["invalid_marker"].exists(), "invalid marker already exists")
    pending_outputs = [plan["summary_output"]]
    for client in plan["clients"]:
        pending_outputs.extend(
            (
                client["writer"]["evidence"],
                client["reader"]["evidence"],
                client["bundle_output"],
            )
        )
    for path in pending_outputs:
        require(not path.exists(), f"refusing stale probe output path: {path}")
    audits = []
    # Remote-only keys must exist before either reader is allowed to plan a Get.
    for client in plan["clients"]:
        audits.append(run_command(client["writer"], timeout=plan["command_timeout_seconds"], phase="writer", client_id=client["client_config_id"]))
    for client in plan["clients"]:
        audits.append(run_command(client["reader"], timeout=plan["command_timeout_seconds"], phase="reader", client_id=client["client_config_id"]))
    bundles = []
    probe_ids: set[str] = set()
    keys: set[str] = set()
    gpu_devices: set[int] = set()
    reader_config_hashes: set[str] = set()
    live_client_ids = {item["client_config_id"] for item in plan["clients"]}
    writer_host_identities: set[tuple[str, str, int]] = set()
    reader_host_identities: set[tuple[str, str, int]] = set()
    for client in plan["clients"]:
        bundle = build_bundle(
            client_config_id=client["client_config_id"],
            client_node_start_time=client["client_node_start_time"],
            writer_raw=read_json(client["writer"]["evidence"]),
            reader_raw=read_json(client["reader"]["evidence"]),
        )
        for record in (bundle["writer"], bundle["reader"]):
            probe_id = require_text(record.get("probe_instance_key"), "probe_instance_key")
            require(probe_id not in probe_ids, "all four probe identities must be unique")
            require(probe_id not in live_client_ids, "probe identity reused a live SGLang client id")
            probe_ids.add(probe_id)
        key = require_text(bundle["writer"].get("key"), "writer.key")
        require(key not in keys, "the two clients must use different remote-only keys")
        keys.add(key)
        gpu_device = require_int(bundle["reader"].get("gpu_device"), "reader.gpu_device", minimum=0)
        require(gpu_device not in gpu_devices, "the two readers must use different physical GPUs")
        gpu_devices.add(gpu_device)
        reader_config_hash = require_text(bundle["reader"].get("config_sha256"), "reader.config_sha256")
        require(reader_config_hash not in reader_config_hashes, "the two readers must use different port-scoped configs")
        reader_config_hashes.add(reader_config_hash)
        for record, identities in (
            (bundle["writer"], writer_host_identities),
            (bundle["reader"], reader_host_identities),
        ):
            host = require_dict(record.get("execution_host"), "execution_host")
            identities.add(
                (
                    require_text(host.get("hostname"), "execution_host.hostname"),
                    require_text(host.get("boot_id"), "execution_host.boot_id"),
                    require_int(host.get("pid1_start_time_ticks"), "execution_host.pid1_start_time_ticks"),
                )
            )
        write_json_atomic(client["bundle_output"], bundle)
        bundles.append(
            {
                "client_config_id": client["client_config_id"],
                "bundle_path": str(client["bundle_output"]),
                "bundle_sha256": sha256_file(client["bundle_output"]),
                "key": key,
                "payload_sha256": bundle["writer"]["sha256"],
            }
        )
    require(len(writer_host_identities) == 1, "the two writers did not execute on one CPU host generation")
    require(len(reader_host_identities) == 1, "the two readers did not execute on one GPU host generation")
    summary = {
        "schema": SUMMARY_SCHEMA,
        "status": "passed",
        "ordering": "all_remote_writers_then_all_gpu_readers",
        "identity_boundary": {
            "data_plane": "four independent ephemeral probe identities",
            "control_plane": "live SGLang identities are validated separately by fluxon_f_rdma_gate.py",
            "data_probe_does_not_substitute_for_live_identity_monitor": True,
        },
        "commands": audits,
        "bundles": bundles,
    }
    write_json_atomic(plan["summary_output"], summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    raw_plan: Any = None
    normalized: dict[str, Any] | None = None
    try:
        raw_plan = read_json(args.plan)
        normalized = validate_plan(raw_plan)
        if args.validate_only:
            print(json.dumps({"schema": PLAN_SCHEMA, "status": "valid"}, sort_keys=True))
            return
        summary = execute_plan(normalized)
        print(json.dumps(summary, sort_keys=True))
    except (CoordinatorError, subprocess.TimeoutExpired, OSError) as exc:
        invalid_path = normalized.get("invalid_marker") if normalized is not None else None
        if isinstance(invalid_path, Path):
            write_invalid_once(
                invalid_path,
                {
                    "schema": "fluxon_f_remote_gpu_probe_invalid_v1",
                    "status": "invalid",
                    "error": str(exc),
                },
            )
        print(f"Fluxon F remote GPU probe coordinator failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
