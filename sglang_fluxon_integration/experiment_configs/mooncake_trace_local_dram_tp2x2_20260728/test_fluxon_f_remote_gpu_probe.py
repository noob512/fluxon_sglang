#!/usr/bin/env python3
from __future__ import annotations

import ast
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

import fluxon_f_remote_gpu_probe_coordinator as coordinator


HERE = Path(__file__).resolve().parent
CLIENT0 = "fluxon_external_port31001"
CLIENT1 = "fluxon_external_port31002"
REMOTE = "fluxon_remote_owner"
LOCAL = "fluxon_local_owner"
CPU_BOOT = "22222222-2222-2222-2222-222222222222"
GPU_BOOT = "11111111-1111-1111-1111-111111111111"


def binding(owner: str, generation: int, digest: str) -> dict[str, object]:
    root = "/run/remote" if owner == REMOTE else "/run/local"
    return {
        "proof_kind": "runtime_external_owner_shared_binding_v1",
        "node_id": owner,
        "node_start_time": generation,
        "runtime_segment_label": "external_owner:0",
        "published_segment_label": "cpu:0",
        "segment_len": 274_877_906_944,
        "configured_share_mem_root": root,
        "share_mem_path": f"{root}/cluster",
        "shared_json_path": f"{root}/cluster/shared.json",
        "shared_json_sha256": digest * 64,
        "mmap_path": f"{root}/cluster/mmap.file",
        "mmap_size": 274_877_906_944,
        "runtime_write_mapping_present": True,
        "runtime_read_mapping_present": True,
    }


def execution_host(*, writer: bool, suffix: str) -> dict[str, object]:
    hostname = "cpu-host" if writer else "gpu-host"
    ip = "10.233.114.150" if writer else "10.233.90.51"
    return {
        "hostname": hostname,
        "expected_hostname": hostname,
        "ips": [ip],
        "expected_ip": ip,
        "boot_id": CPU_BOOT if writer else GPU_BOOT,
        "pid1_start_time_ticks": 20 if writer else 10,
        "pid": (2000 if writer else 3000) + int(suffix),
        "process_start_time_ticks": 200 if writer else 300,
    }


def records(client: str, generation: int, suffix: str) -> tuple[dict[str, object], dict[str, object]]:
    digest = suffix * 64
    key = f"remote-only-{suffix}"
    writer = {
        "schema": coordinator.RECORD_SCHEMA,
        "mode": "writer",
        "status": "written",
        "cluster_name": "cluster",
        "target_client_config_id": client,
        "probe_instance_key": f"writer-{suffix}",
        "source_owner_id": REMOTE,
        "source_owner_node_start_time": 200,
        "source_owner_configured_dram": 274_877_906_944,
        "source_binding": binding(REMOTE, 200, "d"),
        "source_binding_revalidated_after_io": True,
        "execution_host": execution_host(writer=True, suffix=suffix),
        "config_sha256": "9" * 64,
        "rdma_devices": ["mlx5_0", "mlx5_1"],
        "key": key,
        "size": 4_718_592,
        "seed": 73 + int(suffix),
        "sha256": digest,
        "remote_only": True,
        "write_through": True,
        "make_replica_task": False,
        "make_replica_task_mask": [False],
        "atomic_group_lens": [1],
        "readiness_declaration_scope": "audit_only_not_enforcement",
    }
    reader = {
        "schema": coordinator.RECORD_SCHEMA,
        "mode": "reader",
        "status": "passed",
        "cluster_name": "cluster",
        "client_config_id": client,
        "client_node_start_time": generation,
        "probe_instance_key": f"reader-{suffix}",
        "bound_local_owner": binding(LOCAL, 100, "e"),
        "local_owner_binding_revalidated_after_io": True,
        "execution_host": execution_host(writer=False, suffix=suffix),
        "config_sha256": ("7" if suffix == "0" else "8") * 64,
        "rdma_devices": ["mlx5_0", "mlx5_1", "mlx5_2", "mlx5_3"],
        "planned_source_scope": "remote_from_bound_local_owner",
        "key": key,
        "size": 4_718_592,
        "seed": 73 + int(suffix),
        "expected_sha256": digest,
        "actual_sha256": digest,
        "gpu_remote_indices": [0],
        "gpu_device": 0 if suffix == "0" else 2,
        "terminal_timing": {
            "transfer_wall_us": 10,
            "finish_wait_us": 2,
            "terminal_before_consume": True,
            "terminal_to_consume_us": 1,
        },
        "terminal_timing_observed_after_get_transfer_gpu": True,
        "readiness_declaration_scope": "audit_only_not_enforcement",
    }
    return writer, reader


class ProbeCoordinatorTests(unittest.TestCase):
    def test_build_bundle_requires_runtime_source_binding(self) -> None:
        writer, reader = records(CLIENT0, 300, "0")
        bundle = coordinator.build_bundle(
            client_config_id=CLIENT0,
            client_node_start_time=300,
            writer_raw=writer,
            reader_raw=reader,
        )
        self.assertEqual(bundle["schema"], coordinator.BUNDLE_SCHEMA)
        writer.pop("source_binding")
        with self.assertRaisesRegex(coordinator.CoordinatorError, "source_binding must be an object"):
            coordinator.build_bundle(
                client_config_id=CLIENT0,
                client_node_start_time=300,
                writer_raw=writer,
                reader_raw=reader,
            )

    def test_build_bundle_rejects_payload_or_local_binding_mismatch(self) -> None:
        for mutation, needle in (
            (
                lambda _writer, reader: reader.update(actual_sha256="f" * 64),
                "payload hash mismatch",
            ),
            (
                lambda _writer, reader: reader["bound_local_owner"].update(mmap_size=1),
                "mmap size mismatch",
            ),
        ):
            with self.subTest(needle=needle):
                writer, reader = records(CLIENT0, 300, "0")
                mutation(writer, reader)
                with self.assertRaisesRegex(coordinator.CoordinatorError, needle):
                    coordinator.build_bundle(
                        client_config_id=CLIENT0,
                        client_node_start_time=300,
                        writer_raw=writer,
                        reader_raw=reader,
                    )

    def test_build_bundle_rejects_same_execution_host_or_live_identity(self) -> None:
        writer, reader = records(CLIENT0, 300, "0")
        reader["execution_host"] = copy.deepcopy(writer["execution_host"])
        with self.assertRaisesRegex(coordinator.CoordinatorError, "different hosts"):
            coordinator.build_bundle(
                client_config_id=CLIENT0,
                client_node_start_time=300,
                writer_raw=writer,
                reader_raw=reader,
            )

        writer, reader = records(CLIENT0, 300, "0")
        reader["probe_instance_key"] = CLIENT0
        with self.assertRaisesRegex(coordinator.CoordinatorError, "reused the live client"):
            coordinator.build_bundle(
                client_config_id=CLIENT0,
                client_node_start_time=300,
                writer_raw=writer,
                reader_raw=reader,
            )

    def test_execute_plan_runs_both_writers_before_readers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            clients = []
            payloads = {}
            for index, (client, generation, suffix) in enumerate(
                ((CLIENT0, 300, "0"), (CLIENT1, 301, "1"))
            ):
                writer, reader = records(client, generation, suffix)
                writer_path = root / f"writer{index}.json"
                reader_path = root / f"reader{index}.json"
                payloads[("writer", client)] = (writer_path, writer)
                payloads[("reader", client)] = (reader_path, reader)
                clients.append(
                    {
                        "client_config_id": client,
                        "client_node_start_time": generation,
                        "writer": {"argv": ["writer", client], "evidence": writer_path},
                        "reader": {"argv": ["reader", client], "evidence": reader_path},
                        "bundle_output": root / f"bundle{index}.json",
                    }
                )
            normalized = {
                "clients": clients,
                "command_timeout_seconds": 10,
                "summary_output": root / "summary.json",
                "invalid_marker": root / "invalid.json",
            }
            order = []

            def fake_run(command: dict[str, object], *, timeout: int, phase: str, client_id: str) -> dict[str, object]:
                order.append((phase, client_id))
                path, payload = payloads[(phase, client_id)]
                coordinator.write_json_atomic(path, payload)
                return {"phase": phase, "client_config_id": client_id}

            with mock.patch.object(coordinator, "run_command", side_effect=fake_run):
                summary = coordinator.execute_plan(normalized)
            self.assertEqual(
                order,
                [
                    ("writer", CLIENT0),
                    ("writer", CLIENT1),
                    ("reader", CLIENT0),
                    ("reader", CLIENT1),
                ],
            )
            self.assertEqual(summary["status"], "passed")
            self.assertFalse(normalized["invalid_marker"].exists())

    def test_execute_plan_rejects_duplicate_gpu_probe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            clients = []
            payloads = {}
            for index, (client, generation, suffix) in enumerate(
                ((CLIENT0, 300, "0"), (CLIENT1, 301, "1"))
            ):
                writer, reader = records(client, generation, suffix)
                reader["gpu_device"] = 0
                writer_path = root / f"writer{index}.json"
                reader_path = root / f"reader{index}.json"
                payloads[("writer", client)] = (writer_path, writer)
                payloads[("reader", client)] = (reader_path, reader)
                clients.append(
                    {
                        "client_config_id": client,
                        "client_node_start_time": generation,
                        "writer": {"argv": ["writer", client], "evidence": writer_path},
                        "reader": {"argv": ["reader", client], "evidence": reader_path},
                        "bundle_output": root / f"bundle{index}.json",
                    }
                )
            normalized = {
                "clients": clients,
                "command_timeout_seconds": 10,
                "summary_output": root / "summary.json",
                "invalid_marker": root / "invalid.json",
            }

            def fake_run(command: dict[str, object], *, timeout: int, phase: str, client_id: str) -> dict[str, object]:
                path, payload = payloads[(phase, client_id)]
                coordinator.write_json_atomic(path, payload)
                return {"phase": phase, "client_config_id": client_id}

            with mock.patch.object(coordinator, "run_command", side_effect=fake_run):
                with self.assertRaisesRegex(coordinator.CoordinatorError, "different physical GPUs"):
                    coordinator.execute_plan(normalized)

    def test_plan_rejects_shell_strings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = {
                "schema": coordinator.PLAN_SCHEMA,
                "command_timeout_seconds": 10,
                "summary_output": str(root / "summary.json"),
                "invalid_marker": str(root / "invalid.json"),
                "clients": [],
            }
            for index, client in enumerate((CLIENT0, CLIENT1)):
                raw["clients"].append(
                    {
                        "client_config_id": client,
                        "client_node_start_time": 300 + index,
                        "writer": {
                            "argv": "ssh host python probe.py",
                            "evidence": str(root / f"w{index}.json"),
                        },
                        "reader": {
                            "argv": ["python", "probe.py"],
                            "evidence": str(root / f"r{index}.json"),
                        },
                        "bundle_output": str(root / f"b{index}.json"),
                    }
                )
            with self.assertRaisesRegex(coordinator.CoordinatorError, "argv must be an array"):
                coordinator.validate_plan(raw)


class ProbeRuntimeBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        class FakeConfig:
            def __init__(self, raw: dict[str, object]) -> None:
                self.raw = raw

        fluxon = types.ModuleType("fluxon_py")
        fluxon.FluxonKvClientConfig = FakeConfig
        fluxon.new_store = lambda *_args, **_kwargs: None
        kvclient = types.ModuleType("fluxon_py.kvclient")
        interface = types.ModuleType("fluxon_py.kvclient.kvclient_interface")
        interface.PutOptionalArgs = object
        spec = importlib.util.spec_from_file_location(
            "fluxon_f_remote_gpu_probe_test_module", HERE / "fluxon_f_remote_gpu_probe.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        with mock.patch.dict(
            sys.modules,
            {
                "fluxon_py": fluxon,
                "fluxon_py.kvclient": kvclient,
                "fluxon_py.kvclient.kvclient_interface": interface,
            },
        ):
            spec.loader.exec_module(module)
        cls.probe = module

    def test_owner_config_is_sanitized_before_zero_contribution_attach(self) -> None:
        owner = {
            "instance_key": REMOTE,
            "contribute_to_cluster_pool_size": {"dram": 274_877_906_944, "vram": {}},
            "replica_writeback_hot_capacity_ratio": 0.9,
            "fluxonkv_spec": {
                "cluster_name": "cluster",
                "share_mem_path": "/run/remote",
                "sub_cluster": "remote_cache",
                "etcd_addresses": ["127.0.0.1:2379"],
                "large_file_paths": ["/run/large"],
            },
            "protocol": {"protocol_type": "rdma"},
            "test_spec_config": {
                "transport_mode": "transfer_with_rpc",
                "rdma_device_names": ["mlx5_0", "mlx5_1"],
                "prefer_local_placement": True,
                "owner_local_reserve_expected_capacity": {
                    "value_len": 4_718_592,
                    "payload_capacity_bytes": 1,
                },
            },
        }
        derived = self.probe.build_probe_config(owner, "writer-probe").raw
        self.assertEqual(
            derived["contribute_to_cluster_pool_size"], {"dram": 0, "vram": {}}
        )
        self.assertEqual(
            derived["fluxonkv_spec"],
            {"cluster_name": "cluster", "share_mem_path": "/run/remote"},
        )
        self.assertNotIn("replica_writeback_hot_capacity_ratio", derived)
        self.assertNotIn("prefer_local_placement", derived["test_spec_config"])
        self.assertNotIn(
            "owner_local_reserve_expected_capacity", derived["test_spec_config"]
        )

    def test_runtime_binding_uses_cluster_scoped_owner_generation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "owner-root"
            scoped = root / "cluster"
            scoped.mkdir(parents=True)
            (scoped / "mmap.file").write_bytes(b"x" * 64)
            shared = {
                "owner_id": REMOTE,
                "node_start_time": 200,
                "segment_len": 64,
                "segment_label": "cpu:0",
                "sub_cluster": "remote_cache",
                "cluster_name": "cluster",
                "share_mem_path": str(scoped.resolve()),
            }
            (scoped / "shared.json").write_text(
                json.dumps(shared), encoding="utf-8"
            )

            class Store:
                @staticmethod
                def wait_local_segments_ready() -> list[dict[str, object]]:
                    return [
                        {
                            "segment_label": "external_owner:0",
                            "node_id": REMOTE,
                            "generation": 200,
                            "len": 64,
                            "write_ptr": 1,
                            "read_ptr": 2,
                        }
                    ]

            evidence = self.probe.validate_external_owner_binding(
                store=Store(),
                spec={"share_mem_path": str(root)},
                expected_owner_id=REMOTE,
                expected_owner_node_start_time=200,
                expected_cluster_name="cluster",
                expected_sub_cluster="remote_cache",
                expected_segment_len=64,
                context="writer CPU remote owner",
            )
            self.assertEqual(evidence["share_mem_path"], str(scoped.resolve()))
            self.assertEqual(evidence["node_start_time"], 200)

            shared["node_start_time"] = 201
            (scoped / "shared.json").write_text(
                json.dumps(shared), encoding="utf-8"
            )
            with self.assertRaisesRegex(RuntimeError, "shared.json/runtime generation mismatch"):
                self.probe.validate_external_owner_binding(
                    store=Store(),
                    spec={"share_mem_path": str(root)},
                    expected_owner_id=REMOTE,
                    expected_owner_node_start_time=200,
                    expected_cluster_name="cluster",
                    expected_sub_cluster="remote_cache",
                    expected_segment_len=64,
                    context="writer CPU remote owner",
                )


class ProbeStaticContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.probe_path = HERE / "fluxon_f_remote_gpu_probe.py"
        cls.probe_text = cls.probe_path.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.probe_text)

    def function(self, name: str) -> ast.FunctionDef:
        for node in self.tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return node
        raise AssertionError(f"missing function {name}")

    def test_writer_and_reader_bind_live_owner_before_io(self) -> None:
        for function_name, io_call in (
            ("run_writer", "local_fast_put_start"),
            ("run_reader", "get_plan"),
        ):
            function = self.function(function_name)
            binding_lines = [
                node.lineno
                for node in ast.walk(function)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "validate_external_owner_binding"
            ]
            io_lines = [
                node.lineno
                for node in ast.walk(function)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == io_call
            ]
            self.assertEqual(len(binding_lines), 2)
            self.assertEqual(len(io_lines), 1)
            self.assertLess(min(binding_lines), io_lines[0])
            self.assertGreater(max(binding_lines), io_lines[0])

    def test_binding_uses_runtime_mapping_and_owner_published_files(self) -> None:
        source = ast.get_source_segment(
            self.probe_text, self.function("validate_external_owner_binding")
        )
        self.assertIn("wait_local_segments_ready", source)
        self.assertIn('"shared.json"', source)
        self.assertIn('"mmap.file"', source)
        self.assertIn("runtime_external_owner_shared_binding_v1", source)

    def test_launcher_calls_readiness_declaration_audit_only(self) -> None:
        launcher = (HERE / "derive_fluxon_f_launcher.py").read_text(encoding="utf-8")
        self.assertIn("intentionally audit-only", launcher)
        self.assertIn("formal enforcement is the independent direct-RDMA gate", launcher)


if __name__ == "__main__":
    unittest.main()
