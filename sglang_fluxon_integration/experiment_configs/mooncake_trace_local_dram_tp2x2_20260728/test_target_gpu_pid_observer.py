from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("target_gpu_pid_observer.py")
SPEC = importlib.util.spec_from_file_location("target_gpu_pid_observer", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class TargetGpuPidObserverTest(unittest.TestCase):
    def test_parsers(self) -> None:
        self.assertEqual(
            MODULE.parse_gpu_inventory("0, GPU-a\n3, GPU-d\n"),
            {0: "GPU-a", 3: "GPU-d"},
        )
        self.assertEqual(
            MODULE.parse_compute_apps("GPU-d, 42, 123 MiB\n"),
            [{"gpu_uuid": "GPU-d", "pid": 42, "used_memory": "123 MiB"}],
        )

    def test_only_target_foreign_process_is_rejected(self) -> None:
        observations = [
            {"gpu_uuid": "GPU-target", "pid": 10, "used_memory": "1 MiB"},
            {"gpu_uuid": "GPU-target", "pid": 20, "used_memory": "2 MiB"},
            {"gpu_uuid": "GPU-other", "pid": 30, "used_memory": "3 MiB"},
        ]

        def chains(pid: int) -> list[dict[str, object]]:
            if pid == 10:
                return [
                    {"pid": 10, "argv": ["sglang::scheduler_TP0"]},
                    {"pid": 9, "argv": ["bash", "run_series_attempt_7"]},
                ]
            return [{"pid": pid, "argv": ["python", "decoder_app.py"]}]

        violations = MODULE.foreign_processes(
            observations,
            {"GPU-target"},
            "series_attempt_7",
            chain_reader=chains,
        )
        self.assertEqual([item["pid"] for item in violations], [20])
        self.assertEqual(violations[0]["process_chain"][0]["pid"], 20)

    def test_chain_stops_on_cycle(self) -> None:
        parents = {7: 8, 8: 7}
        chain = MODULE.process_chain(
            7,
            cmdline_reader=lambda pid: (f"pid-{pid}",),
            ppid_reader=parents.get,
        )
        self.assertEqual([item["pid"] for item in chain], [7, 8])

    def test_known_generation_survives_empty_cmdline_exit_race(self) -> None:
        observation = [{"gpu_uuid": "GPU-target", "pid": 10, "used_memory": "1 MiB"}]
        identities: dict[int, int | None] = {}
        allowed_chain = lambda _pid: [
            {"pid": 10, "argv": ["sglang::scheduler_TP0"]},
            {"pid": 9, "argv": ["bash", "series_attempt_7"]},
        ]
        self.assertEqual(
            MODULE.foreign_processes(
                observation,
                {"GPU-target"},
                "series_attempt_7",
                chain_reader=allowed_chain,
                starttime_reader=lambda _pid: 100,
                allowed_identities=identities,
            ),
            [],
        )
        self.assertEqual(identities, {10: 100})
        empty_chain = lambda _pid: [{"pid": 10, "argv": []}]
        self.assertEqual(
            MODULE.foreign_processes(
                observation,
                {"GPU-target"},
                "series_attempt_7",
                chain_reader=empty_chain,
                starttime_reader=lambda _pid: None,
                allowed_identities=identities,
            ),
            [],
        )
        reused = MODULE.foreign_processes(
            observation,
            {"GPU-target"},
            "series_attempt_7",
            chain_reader=empty_chain,
            starttime_reader=lambda _pid: 200,
            allowed_identities=identities,
        )
        self.assertEqual([item["pid"] for item in reused], [10])
        self.assertEqual(reused[0]["previously_allowed_starttime"], 100)


if __name__ == "__main__":
    unittest.main()
