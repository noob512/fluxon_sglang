#!/usr/bin/env python3
from __future__ import annotations

import copy
import argparse
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import fluxon_f_rdma_gate as gate


LOCAL_OWNER = "fluxon_mooncake_f_local_owner"
REMOTE_OWNER = "fluxon_mooncake_f_remote_owner"
CLIENT0 = "fluxon_fluxon_f1_external_sglang_tp2_port31001"
CLIENT1 = "fluxon_fluxon_f1_external_sglang_tp2_port31002"
GPU_HOST = "gpu-host"
CPU_HOST = "cpu-host"
GPU_IP = "10.233.90.51"
CPU_IP = "10.233.114.150"
GPU_BOOT = "11111111-1111-1111-1111-111111111111"
CPU_BOOT = "22222222-2222-2222-2222-222222222222"


def hca(device: str, lid: str) -> dict[str, object]:
    return {
        "device": device,
        "port": 1,
        "state": "ACTIVE",
        "physical_state": "LinkUp",
        "link_layer": "InfiniBand",
        "rate": "400 Gb/sec (4X HDR)",
        "rate_gbps": 400,
        "lid": lid,
        "sm_lid": "0x418",
        "gid0": "fe80:0000:0000:0000:0000:0000:0000:0001",
    }


def member(
    member_id: str,
    generation: int,
    revision: int,
    sub_cluster: str,
    metadata: dict[str, str],
    address: str,
) -> dict[str, object]:
    return {
        "key": f"/fluxon_commu_member_base/cluster/members/{member_id}",
        "missing": False,
        "lease": 99,
        "mod_revision": revision,
        "value": {
            "id": member_id,
            "addresses": [address],
            "port": 12345,
            "node_start_time": generation,
            "metadata": metadata,
            "sub_cluster": sub_cluster,
        },
    }


def ready(member_id: str, generation: int, revision: int) -> dict[str, object]:
    return {
        "key": f"/fluxon_commu_member_ext/cluster/members/{member_id}/transfer_ready",
        "missing": False,
        "lease": 99,
        "mod_revision": revision,
        "value": {
            "node_start_time": generation,
            "backend_epoch": 1,
            "ready_ts_micros": 1_900_000_000_000_000,
        },
    }


def edge(source: str, revision: int, value: str = "closed") -> dict[str, object]:
    return {
        "key": f"/cluster/transfer_link/te/{source}/{REMOTE_OWNER}",
        "missing": False,
        "lease": 0,
        "mod_revision": revision,
        "value_text": value,
    }


def probe(
    client_id: str,
    client_generation: int,
    gpu_device: int,
    suffix: str,
) -> dict[str, object]:
    digest = ("a" if suffix == "0" else "b") * 64
    key = f"fluxon_f_rdma_gate_client{suffix}"
    source_binding = {
        "proof_kind": "runtime_external_owner_shared_binding_v1",
        "node_id": REMOTE_OWNER,
        "node_start_time": 200,
        "runtime_segment_label": "external_owner:0",
        "published_segment_label": "cpu:0",
        "segment_len": 274_877_906_944,
        "configured_share_mem_root": "/run/remote",
        "share_mem_path": "/run/remote/cluster",
        "shared_json_path": "/run/remote/cluster/shared.json",
        "shared_json_sha256": "d" * 64,
        "mmap_path": "/run/remote/cluster/mmap.file",
        "mmap_size": 274_877_906_944,
        "runtime_write_mapping_present": True,
        "runtime_read_mapping_present": True,
    }
    local_binding = {
        **source_binding,
        "node_id": LOCAL_OWNER,
        "node_start_time": 100,
        "shared_json_sha256": "e" * 64,
        "configured_share_mem_root": "/run/local",
        "share_mem_path": "/run/local/cluster",
        "shared_json_path": "/run/local/cluster/shared.json",
        "mmap_path": "/run/local/cluster/mmap.file",
    }
    writer_host = {
        "hostname": CPU_HOST,
        "expected_hostname": CPU_HOST,
        "ips": [CPU_IP],
        "expected_ip": CPU_IP,
        "boot_id": CPU_BOOT,
        "pid1_start_time_ticks": 20,
        "pid": 2000 + int(suffix),
        "process_start_time_ticks": 200,
    }
    reader_host = {
        "hostname": GPU_HOST,
        "expected_hostname": GPU_HOST,
        "ips": [GPU_IP],
        "expected_ip": GPU_IP,
        "boot_id": GPU_BOOT,
        "pid1_start_time_ticks": 10,
        "pid": 3000 + int(suffix),
        "process_start_time_ticks": 300,
    }
    return {
        "schema": "fluxon_f_remote_gpu_probe_bundle_v1",
        "client_config_id": client_id,
        "client_node_start_time": client_generation,
        "writer": {
            "schema": "fluxon_f_remote_gpu_probe_record_v2",
            "mode": "writer",
            "status": "written",
            "cluster_name": "cluster",
            "target_client_config_id": client_id,
            "probe_instance_key": f"{client_id}_writer_probe",
            "key": key,
            "size": 4_718_592,
            "seed": 73 + int(suffix),
            "sha256": digest,
            "remote_only": True,
            "make_replica_task": False,
            "make_replica_task_mask": [False],
            "atomic_group_lens": [1],
            "write_through": True,
            "source_owner_id": REMOTE_OWNER,
            "source_owner_node_start_time": 200,
            "source_owner_configured_dram": 274_877_906_944,
            "source_binding": source_binding,
            "source_binding_revalidated_after_io": True,
            "execution_host": writer_host,
            "config_sha256": "9" * 64,
            "rdma_devices": ["mlx5_0", "mlx5_1"],
            "readiness_declaration_scope": "audit_only_not_enforcement",
        },
        "reader": {
            "schema": "fluxon_f_remote_gpu_probe_record_v2",
            "mode": "reader",
            "status": "passed",
            "cluster_name": "cluster",
            "client_config_id": client_id,
            "client_node_start_time": client_generation,
            "probe_instance_key": f"{client_id}_rdma_probe",
            "key": key,
            "size": 4_718_592,
            "seed": 73 + int(suffix),
            "expected_sha256": digest,
            "actual_sha256": digest,
            "gpu_device": gpu_device,
            "gpu_remote_indices": [0],
            "registration_id": 7,
            "terminal_timing": {
                "transfer_wall_us": 10,
                "finish_wait_us": 2,
                "terminal_before_consume": True,
                "terminal_to_consume_us": 1,
            },
            "terminal_timing_observed_after_get_transfer_gpu": True,
            "bound_local_owner": local_binding,
            "local_owner_binding_revalidated_after_io": True,
            "execution_host": reader_host,
            "config_sha256": ("7" if suffix == "0" else "8") * 64,
            "rdma_devices": ["mlx5_0", "mlx5_1", "mlx5_2", "mlx5_3"],
            "planned_source_scope": "remote_from_bound_local_owner",
            "readiness_declaration_scope": "audit_only_not_enforcement",
        },
    }


def valid_evidence() -> dict[str, object]:
    local_meta = {"client": "true", "p2p_relay": "true"}
    remote_meta = {"client": "true", "p2p_relay": "true"}
    ext_meta = {
        "external_client": "true",
        "shared_storage_node_id": LOCAL_OWNER,
        "shared_storage_node_start_time": "100",
    }
    members = {
        LOCAL_OWNER: member(LOCAL_OWNER, 100, 10, "sglang_owner", local_meta, GPU_IP),
        REMOTE_OWNER: member(REMOTE_OWNER, 200, 11, "remote_cache", remote_meta, CPU_IP),
        CLIENT0: member(CLIENT0, 300, 12, "sglang_owner", ext_meta, GPU_IP),
        CLIENT1: member(CLIENT1, 301, 13, "sglang_owner", ext_meta, GPU_IP),
    }
    transfer_ready = {
        LOCAL_OWNER: ready(LOCAL_OWNER, 100, 20),
        REMOTE_OWNER: ready(REMOTE_OWNER, 200, 21),
        CLIENT0: ready(CLIENT0, 300, 22),
        CLIENT1: ready(CLIENT1, 301, 23),
    }
    return {
        "schema": gate.SCHEMA,
        "cluster_name": "cluster",
        "expected": {
            "gpu_hostname": GPU_HOST,
            "gpu_ip": GPU_IP,
            "gpu_hcas": ["mlx5_0", "mlx5_1", "mlx5_2", "mlx5_3"],
            "cpu_hostname": CPU_HOST,
            "cpu_ip": CPU_IP,
            "cpu_hcas": ["mlx5_0", "mlx5_1"],
            "local_owner_id": LOCAL_OWNER,
            "remote_owner_id": REMOTE_OWNER,
            "clients": [
                {"id": CLIENT0, "port": 31001, "gpu_device": 0},
                {"id": CLIENT1, "port": 31002, "gpu_device": 2},
            ],
        },
        "fabric": {
            "gpu": {
                "role": "gpu",
                "hostname": GPU_HOST,
                "expected_hostname": GPU_HOST,
                "ips": [GPU_IP],
                "expected_ip": GPU_IP,
                "boot_id": GPU_BOOT,
                "pid1_start_time_ticks": 10,
                "hcas": [
                    hca("mlx5_0", "0x23"),
                    hca("mlx5_1", "0x24"),
                    hca("mlx5_2", "0x25"),
                    hca("mlx5_3", "0x26"),
                ],
            },
            "cpu": {
                "role": "cpu",
                "hostname": CPU_HOST,
                "expected_hostname": CPU_HOST,
                "ips": [CPU_IP],
                "expected_ip": CPU_IP,
                "boot_id": CPU_BOOT,
                "pid1_start_time_ticks": 20,
                "hcas": [hca("mlx5_0", "0x8"), hca("mlx5_1", "0x18a")],
            },
        },
        "etcd": {
            "cluster_name": "cluster",
            "members": members,
            "transfer_ready": transfer_ready,
            "te_edges": {
                f"{CLIENT0}->{REMOTE_OWNER}": edge(CLIENT0, 30),
                f"{CLIENT1}->{REMOTE_OWNER}": edge(CLIENT1, 31),
            },
        },
        "probes": [probe(CLIENT0, 300, 0, "0"), probe(CLIENT1, 301, 2, "1")],
    }


class FluxonFRdmaGateTests(unittest.TestCase):
    def assert_rejected(self, evidence: dict[str, object], needle: str) -> None:
        with self.assertRaisesRegex(gate.GateError, needle):
            gate.validate_evidence(evidence)

    def test_valid_two_client_remote_gpu_gate(self) -> None:
        summary = gate.validate_evidence(valid_evidence())
        self.assertEqual(summary["status"], "passed")
        self.assertEqual(summary["sm_lid"], 0x418)
        self.assertEqual(len(summary["te_edges"]), 2)
        self.assertEqual(len(summary["probes"]), 2)

    def test_hca_missing_or_down_fails_closed(self) -> None:
        for mutation, needle in (
            (lambda value: value["fabric"]["gpu"]["hcas"].pop(), "HCA set mismatch"),
            (
                lambda value: value["fabric"]["cpu"]["hcas"][0].update(state="DOWN"),
                "not ACTIVE",
            ),
        ):
            with self.subTest(needle=needle):
                evidence = valid_evidence()
                mutation(evidence)
                self.assert_rejected(evidence, needle)

    def test_different_sm_lid_fails_closed(self) -> None:
        evidence = valid_evidence()
        evidence["fabric"]["cpu"]["hcas"][1]["sm_lid"] = "0x419"
        self.assert_rejected(evidence, "do not share one SM LID")

    def test_external_edge_missing_or_non_closed_fails_closed(self) -> None:
        edge_name = f"{CLIENT0}->{REMOTE_OWNER}"
        for replacement, needle in (
            ({"missing": True}, "external TE edge is missing"),
            (edge(CLIENT0, 30, "closed+fallback"), "not direct closed"),
            (edge(CLIENT0, 30, "p2p_mode"), "not direct closed"),
        ):
            with self.subTest(value=replacement):
                evidence = valid_evidence()
                evidence["etcd"]["te_edges"][edge_name] = replacement
                self.assert_rejected(evidence, needle)

    def test_stale_edge_revision_fails_closed(self) -> None:
        evidence = valid_evidence()
        evidence["etcd"]["te_edges"][f"{CLIENT0}->{REMOTE_OWNER}"]["mod_revision"] = 21
        self.assert_rejected(evidence, "predates the current endpoint generations")

    def test_stale_member_generation_fails_closed(self) -> None:
        evidence = valid_evidence()
        evidence["etcd"]["transfer_ready"][CLIENT0]["value"]["node_start_time"] = 299
        self.assert_rejected(evidence, "stale node_start_time")

    def test_only_owner_owner_ready_does_not_pass(self) -> None:
        evidence = valid_evidence()
        evidence["etcd"]["te_edges"] = {
            f"{LOCAL_OWNER}->{REMOTE_OWNER}": edge(LOCAL_OWNER, 40)
        }
        self.assert_rejected(evidence, "external TE edge is missing")

    def test_non_remote_probe_source_fails_closed(self) -> None:
        evidence = valid_evidence()
        evidence["probes"][0]["writer"]["source_binding"]["node_id"] = LOCAL_OWNER
        self.assert_rejected(evidence, "runtime source owner mismatch")

    def test_payload_mismatch_fails_closed(self) -> None:
        evidence = valid_evidence()
        evidence["probes"][1]["reader"]["actual_sha256"] = "c" * 64
        self.assert_rejected(evidence, "payload hash mismatch")

    def test_cli_source_claim_without_runtime_binding_fails_closed(self) -> None:
        evidence = valid_evidence()
        evidence["probes"][0]["writer"].pop("source_binding")
        self.assert_rejected(evidence, "writer.source_binding must be an object")

    def test_stale_reader_local_owner_binding_fails_closed(self) -> None:
        evidence = valid_evidence()
        evidence["probes"][1]["reader"]["bound_local_owner"]["node_start_time"] = 99
        self.assert_rejected(evidence, "local-owner generation mismatch")

    def test_probe_host_and_identity_are_bound(self) -> None:
        for mutation, needle in (
            (
                lambda value: value["probes"][0]["writer"]["execution_host"].update(
                    boot_id=GPU_BOOT
                ),
                "boot identity mismatch",
            ),
            (
                lambda value: value["probes"][0]["reader"].update(
                    probe_instance_key=REMOTE_OWNER
                ),
                "reused a live owner/client identity",
            ),
            (
                lambda value: value["probes"][1]["reader"].update(
                    config_sha256="7" * 64
                ),
                "different port-scoped client configs",
            ),
        ):
            with self.subTest(needle=needle):
                evidence = valid_evidence()
                mutation(evidence)
                self.assert_rejected(evidence, needle)

    def test_control_plane_host_and_two_gpu_independence_are_bound(self) -> None:
        evidence = valid_evidence()
        evidence["etcd"]["members"][REMOTE_OWNER]["value"]["addresses"] = [GPU_IP]
        self.assert_rejected(evidence, "not advertised by expected IP")

        evidence = valid_evidence()
        evidence["expected"]["clients"][1]["gpu_device"] = 0
        self.assert_rejected(evidence, "different physical GPUs")

    def test_continuous_monitor_rejects_generation_or_epoch_drift(self) -> None:
        evidence = valid_evidence()
        baseline = gate.validate_control_plane_snapshot(
            evidence["etcd"],
            cluster_name="cluster",
            local_owner_id=LOCAL_OWNER,
            remote_owner_id=REMOTE_OWNER,
            local_ip=GPU_IP,
            remote_ip=CPU_IP,
            client_ids=[CLIENT0, CLIENT1],
        )
        for mutation, needle in (
            (
                lambda value: value["members"][CLIENT0]["value"].update(node_start_time=302),
                "generation changed",
            ),
            (
                lambda value: value["transfer_ready"][CLIENT1]["value"].update(backend_epoch=2),
                "backend epoch changed",
            ),
        ):
            with self.subTest(needle=needle):
                current = copy.deepcopy(evidence["etcd"])
                mutation(current)
                if "generation" in needle:
                    current["transfer_ready"][CLIENT0]["value"]["node_start_time"] = 302
                with self.assertRaisesRegex(gate.GateError, needle):
                    gate.validate_control_plane_snapshot(
                        current,
                        cluster_name="cluster",
                        local_owner_id=LOCAL_OWNER,
                        remote_owner_id=REMOTE_OWNER,
                        local_ip=GPU_IP,
                        remote_ip=CPU_IP,
                        client_ids=[CLIENT0, CLIENT1],
                        baseline=baseline,
                    )


class FluxonFRdmaMonitorTests(unittest.TestCase):
    def monitor_args(self, root: Path) -> argparse.Namespace:
        baseline = root / "baseline.json"
        baseline.write_text(
            json.dumps(valid_evidence()["etcd"], sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return argparse.Namespace(
            log=root / "monitor.jsonl",
            pid_file=root / "monitor.pid.json",
            ready_file=root / "monitor.ready.json",
            invalid_marker=root / "monitor.invalid.json",
            stop_file=root / "monitor.stop",
            summary_output=root / "monitor.summary.json",
            baseline_etcd=baseline,
            cluster_name="cluster",
            local_owner_id=LOCAL_OWNER,
            remote_owner_id=REMOTE_OWNER,
            local_ip=GPU_IP,
            remote_ip=CPU_IP,
            client_id=[CLIENT0, CLIENT1],
            etcdctl=Path("/nonexistent/etcdctl"),
            endpoint="http://127.0.0.1:2379",
            poll_seconds=0.001,
            heartbeat_seconds=0.001,
            minimum_runtime_seconds=0.0,
        )

    def test_monitor_first_sample_ready_and_clean_final_are_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = self.monitor_args(Path(directory))

            def capture(**_kwargs: object) -> dict[str, object]:
                args.stop_file.touch()
                return copy.deepcopy(valid_evidence()["etcd"])

            with mock.patch.object(gate, "capture_etcd_snapshot", side_effect=capture):
                summary = gate.monitor_etcd(args)
            self.assertEqual(summary["status"], "stopped_cleanly")
            self.assertTrue(args.ready_file.is_file())
            status = gate.validate_monitor_artifacts(
                pid_file=args.pid_file,
                ready_file=args.ready_file,
                invalid_marker=args.invalid_marker,
                summary_output=args.summary_output,
                expect="final",
            )
            self.assertEqual(status["status"], "final")
            self.assertFalse(args.invalid_marker.exists())
            shortened = json.loads(args.summary_output.read_text(encoding="utf-8"))
            shortened["elapsed_seconds"] = 0.0
            shortened["minimum_runtime_seconds"] = 1.0
            args.summary_output.write_text(json.dumps(shortened), encoding="utf-8")
            with self.assertRaisesRegex(gate.GateError, "shorter than required"):
                gate.validate_monitor_artifacts(
                    pid_file=args.pid_file,
                    ready_file=args.ready_file,
                    invalid_marker=args.invalid_marker,
                    summary_output=args.summary_output,
                    expect="final",
                )

    def test_monitor_drift_writes_invalid_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = self.monitor_args(Path(directory))
            drifted = copy.deepcopy(valid_evidence()["etcd"])
            drifted["te_edges"][f"{CLIENT0}->{REMOTE_OWNER}"]["value_text"] = "unknown"
            with mock.patch.object(gate, "capture_etcd_snapshot", return_value=drifted):
                with self.assertRaisesRegex(gate.GateError, "not direct closed"):
                    gate.monitor_etcd(args)
            invalid = json.loads(args.invalid_marker.read_text(encoding="utf-8"))
            self.assertEqual(invalid["status"], "invalid")
            self.assertFalse(args.ready_file.exists())

    def test_live_monitor_check_rejects_invalid_or_pid_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pid_record = {
                "schema": "fluxon_f_direct_rdma_monitor_pid_v1",
                "pid": os.getpid(),
                "start_time_ticks": gate.proc_start_time_ticks(os.getpid()),
                "boot_id": gate.boot_id(),
                "started_time_ns": 1,
                "baseline_etcd_path": "/evidence/baseline.json",
                "baseline_etcd_sha256": "a" * 64,
            }
            ready = {
                "schema": "fluxon_f_direct_rdma_monitor_ready_v1",
                "status": "ready",
                "time_ns": 2,
                "pid": pid_record["pid"],
                "start_time_ticks": pid_record["start_time_ticks"],
                "boot_id": pid_record["boot_id"],
                "baseline_etcd_sha256": pid_record["baseline_etcd_sha256"],
                "first_live_control_plane": {},
            }
            pid_path = root / "pid.json"
            ready_path = root / "ready.json"
            invalid_path = root / "invalid.json"
            summary_path = root / "summary.json"
            pid_path.write_text(json.dumps(pid_record), encoding="utf-8")
            ready_path.write_text(json.dumps(ready), encoding="utf-8")
            status = gate.validate_monitor_artifacts(
                pid_file=pid_path,
                ready_file=ready_path,
                invalid_marker=invalid_path,
                summary_output=summary_path,
                expect="live",
            )
            self.assertEqual(status["status"], "live")

            invalid_path.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(gate.GateError, "invalid marker exists"):
                gate.validate_monitor_artifacts(
                    pid_file=pid_path,
                    ready_file=ready_path,
                    invalid_marker=invalid_path,
                    summary_output=summary_path,
                    expect="live",
                )
            invalid_path.unlink()
            pid_record["start_time_ticks"] += 1
            ready["start_time_ticks"] += 1
            pid_path.write_text(json.dumps(pid_record), encoding="utf-8")
            ready_path.write_text(json.dumps(ready), encoding="utf-8")
            with self.assertRaisesRegex(gate.GateError, "dead or has been reused"):
                gate.validate_monitor_artifacts(
                    pid_file=pid_path,
                    ready_file=ready_path,
                    invalid_marker=invalid_path,
                    summary_output=summary_path,
                    expect="live",
                )


if __name__ == "__main__":
    unittest.main()
