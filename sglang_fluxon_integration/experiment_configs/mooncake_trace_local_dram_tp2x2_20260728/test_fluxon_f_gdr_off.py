#!/usr/bin/env python3
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
import unittest


HERE = Path(__file__).resolve().parent
EXPECTED_RUNTIME_SHA256 = (
    "ba9bea7c8e9b1d645069e56eaff6c7ea0c326bb3956b2bfe06365dccef3cbb07"
)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GdrOffTransformTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.kernel = load_module(
            "fluxon_f_kernel_patch_test", HERE / "patch_fluxon_f_kernel_loader.py"
        )
        cls.gdr = load_module(
            "fluxon_f_gdr_patch_test", HERE / "patch_fluxon_f_gdr_off.py"
        )

    def test_sealed_radix_transforms_to_pinned_gdr_off_runtime(self) -> None:
        source = HERE / "patches/unified_radix_cache_e44_r61_tp_execute_commit.py"
        if not source.is_file():
            self.skipTest("sealed r61 source is supplied by the deployment payload")
        kernel_loaded = self.kernel.transform(source.read_bytes())
        output = self.gdr.transform(kernel_loaded)
        self.assertEqual(self.gdr.sha256_bytes(output), EXPECTED_RUNTIME_SHA256)
        text = output.decode("utf-8")
        self.assertEqual(text.count("_FLUXON_GPU_DIRECT_STAGING_ENABLED = False"), 1)
        self.assertEqual(
            text.count("Fluxon GPU-direct staging disabled: mode=cpu_h2d_only"), 1
        )

    def test_gdr_transform_rejects_unpinned_input(self) -> None:
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            self.gdr.transform(b"not the sealed radix runtime\n")


class HostSmokeStaticTests(unittest.TestCase):
    def test_reader_uses_cpu_plan_and_never_registers_gpu_memory(self) -> None:
        path = HERE / "fluxon_f_remote_host_smoke.py"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        run_reader = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "run_reader"
        )
        calls = {
            node.func.attr
            for node in ast.walk(run_reader)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertIn("execute_get_plan_cpu", calls)
        self.assertIn("get_transfer", calls)
        self.assertNotIn("execute_get_plan_gpu", calls)
        self.assertNotIn("register_gpu_buffer", calls)
        self.assertNotIn("unregister_gpu_buffer", calls)
        self.assertNotIn("torch", source)

    def test_launcher_fails_closed_on_pinned_gdr_off_runtime(self) -> None:
        launcher = (HERE / "launch_fluxon_f_gpu.sh").read_text(encoding="utf-8")
        self.assertIn(EXPECTED_RUNTIME_SHA256, launcher)
        self.assertIn("FLUXON_F_GDR_MODE=disabled", launcher)
        self.assertIn("_FLUXON_GPU_DIRECT_STAGING_ENABLED = False", launcher)


if __name__ == "__main__":
    unittest.main()
