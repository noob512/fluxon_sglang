#!/usr/bin/env python3
from __future__ import annotations

import ast
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
MODULE_PATH = HERE / "patch_fluxon_f_storage_metrics_compat.py"
DEPLOYED_SOURCE = HERE / "patches/hicache_fluxon_e44_r54_prefetch_timeline_observe.py"
WORKSPACE_SOURCE = (
    HERE.parent
    / "e44_local_slot_tier_20260716/artifacts/"
    "e44_r55_planned_get_cancel_safe_enddepth288_netobs_passed_20260723/config/"
    "hicache_fluxon_e44_r54_prefetch_timeline_observe.py"
)
SOURCE = DEPLOYED_SOURCE if DEPLOYED_SOURCE.is_file() else WORKSPACE_SOURCE
NVME_TMP = Path(os.environ.get("FLUXON_F_TEST_TMPDIR", "/mnt/nvme0/mjq_build"))

spec = importlib.util.spec_from_file_location("fluxon_f_metrics_compat", MODULE_PATH)
assert spec is not None and spec.loader is not None
compat = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compat)


class FluxonFStorageMetricsCompatTest(unittest.TestCase):
    def test_exact_transform_keeps_kv_code_and_adds_observation_gate(self) -> None:
        source = SOURCE.read_text(encoding="utf-8")
        output = compat.transform(source)
        ast.parse(output)
        self.assertEqual(output.count("add_l2_hit_sample"), 3)
        self.assertEqual(output.count("add_io_sample"), 2)
        self.assertIn("if not callable(getattr(stats", output)
        self.assertEqual(output.replace(compat.NEW, compat.OLD, 1), source)

    def test_transform_is_fail_closed_for_changed_source(self) -> None:
        with self.assertRaisesRegex(ValueError, "expected one r54 observability hook"):
            compat.transform("def unrelated():\n    pass\n")

    def test_cli_pins_source_hash_and_writes_manifest(self) -> None:
        NVME_TMP.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=NVME_TMP) as tmp:
            root = Path(tmp)
            output = root / "hicache_fluxon.py"
            manifest = root / "compat.json"
            subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(MODULE_PATH),
                    "--source",
                    str(SOURCE),
                    "--output",
                    str(output),
                    "--manifest",
                    str(manifest),
                ],
                check=True,
                text=True,
                capture_output=True,
            )
            self.assertTrue(output.is_file())
            self.assertTrue(manifest.is_file())
            self.assertIn('"kv_data_path_changed": false', manifest.read_text())


if __name__ == "__main__":
    unittest.main()
