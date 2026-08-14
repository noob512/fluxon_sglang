#!/usr/bin/env python3
"""Focused invariants for the frozen Interactive r34-shaped workload."""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


replay = load_module("interactive_r34_shaped_replay_tested", HERE / "interactive_r34_shaped_replay.py")
prefix_builder = load_module(
    "build_interactive_r34_shared_prefix_tested",
    HERE / "build_interactive_r34_shared_prefix.py",
)


class PureInvariantTests(unittest.TestCase):
    def test_cached_token_metrics_and_hit_summary(self) -> None:
        metrics = """
sglang:cached_tokens_total{cache_source="device",model="a"} 100
sglang:cached_tokens_total{model="b",cache_source="device"} 20
sglang:cached_tokens_total{cache_source="host",model="a"} 200
sglang:cached_tokens_total{cache_source="storage_MooncakeStore",model="a"} 300
ignored_metric{cache_source="device"} 999
"""
        parsed = replay.parse_cached_token_metrics(metrics)
        self.assertEqual(
            parsed,
            {"device": 120.0, "host": 200.0, "storage_MooncakeStore": 300.0},
        )
        summary = replay.hit_summary(
            {"device": 10, "host": 20, "storage_MooncakeStore": 30},
            {"device": 110, "host": 220, "storage_MooncakeStore": 330},
            1_000,
        )
        self.assertEqual(summary["l1_device_tokens"], 100)
        self.assertEqual(summary["l2_host_tokens"], 200)
        self.assertEqual(summary["l3_mooncake_tokens"], 300)
        self.assertAlmostEqual(summary["total_hit_share"], 0.6)
        self.assertAlmostEqual(summary["miss_share"], 0.4)

    def test_runtime_boundary_is_exactly_ten_minutes(self) -> None:
        common = [
            "--trace",
            "trace",
            "--base-replayer",
            "base",
            "--prefix-asset",
            "prefix",
            "--expected-prefix-sha256",
            "0" * 64,
            "replay",
            "--base-url",
            "http://router",
            "--worker-metrics-url",
            "http://worker0/metrics",
            "--worker-metrics-url",
            "http://worker1/metrics",
            "--expected-model",
            "model",
            "--capacity-manifest",
            "capacity",
            "--run-id",
            "unit_test",
            "--output-dir",
            "output",
        ]
        accepted = replay.parse_args(common + ["--max-runtime-s", "600"])
        self.assertEqual(accepted.max_runtime_s, 600.0)
        self.assertEqual(accepted.capacity_group, "D")
        balanced = replay.parse_args(
            common + ["--capacity-group", "B", "--max-runtime-s", "600"]
        )
        self.assertEqual(balanced.capacity_group, "B")
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                replay.parse_args(common + ["--max-runtime-s", "599.999"])
            with self.assertRaises(SystemExit):
                replay.parse_args(common + ["--capacity-group", "E"])

        four_workers = common[:-8]
        four_workers.extend(
            [
                "--worker-metrics-url",
                "http://worker2/metrics",
                "--worker-metrics-url",
                "http://worker3/metrics",
                *common[-8:],
            ]
        )
        accepted_four = replay.parse_args(four_workers + ["--max-runtime-s", "600"])
        self.assertEqual(len(accepted_four.worker_metrics_url), 4)

        three_workers = common[:-8]
        three_workers.extend(
            ["--worker-metrics-url", "http://worker2/metrics", *common[-8:]]
        )
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                replay.parse_args(three_workers + ["--max-runtime-s", "600"])

    def test_prefix_asset_identity_and_token_range_gate(self) -> None:
        value = {
            "schema": replay.PREFIX_ASSET_SCHEMA,
            "profile": replay.PROFILE,
            "vocab_size": 128,
            "tokenizer_files_sha256": {"tokenizer.json": "a" * 64},
            "decoded_prefix_sha256": "b" * 64,
            "token_ids": [7] * replay.SHARED_PREFIX_TOKENS,
        }
        value["token_ids_sha256"] = hashlib.sha256(
            replay.canonical_json_bytes(value["token_ids"])
        ).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prefix.json"
            path.write_bytes(replay.canonical_json_bytes(value) + b"\n")
            file_sha = replay.sha256_file(path)
            loaded = replay.load_prefix_asset(path, file_sha, 128)
            self.assertEqual(len(loaded.token_ids), replay.SHARED_PREFIX_TOKENS)
            value["token_ids"][-1] = 128
            value["token_ids_sha256"] = hashlib.sha256(
                replay.canonical_json_bytes(value["token_ids"])
            ).hexdigest()
            path.write_bytes(replay.canonical_json_bytes(value) + b"\n")
            with self.assertRaises(replay.ValidationError):
                replay.load_prefix_asset(path, replay.sha256_file(path), 128)

    def test_prefix_builder_rejects_non_frozen_length(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                prefix_builder.parse_args(
                    ["--tokenizer", "tokenizer", "--output", "out", "--target-tokens", "4095"]
                )


class FullTraceInvariantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        trace_raw = os.environ.get("INTERACTIVE_R34_TRACE")
        base_raw = os.environ.get("INTERACTIVE_R34_BASE_REPLAYER")
        if not trace_raw or not base_raw:
            raise unittest.SkipTest(
                "set INTERACTIVE_R34_TRACE and INTERACTIVE_R34_BASE_REPLAYER"
            )
        cls.base = replay.load_base_replayer(
            Path(base_raw), replay.BASE_REPLAYER_SHA256
        )
        cls.trace = replay.build_shaped_trace(Path(trace_raw))
        cls.token_map = cls.base.build_trie_token_map(cls.trace.records)

    def test_selection_length_and_wss_identity(self) -> None:
        trace = self.trace
        self.assertEqual(trace.candidate_count, 444)
        self.assertEqual(len(trace.selected_users), 96)
        self.assertEqual(len(trace.records), 2_304)
        self.assertEqual(trace.selected_users_sha256, replay.SELECTED_USERS_SHA256)
        self.assertEqual(
            trace.selection_coordinates_sha256, replay.SELECTION_COORDINATES_SHA256
        )
        self.assertEqual(trace.shaped_records_sha256, replay.SHAPED_RECORDS_SHA256)
        self.assertEqual(trace.prompt_tokens, 51_357_488)
        self.assertEqual(trace.output_tokens, 18_432)
        self.assertEqual((trace.min_input, trace.max_input), (11_950, 42_157))
        self.assertEqual(trace.unique_exact_tokens, 2_157_343)
        self.assertEqual(trace.unique_pages, 33_759)
        self.assertEqual(trace.unique_page_bytes, 318_589_894_656)
        for turn_slot, target in enumerate(replay.R34_TURN_PROMPT_TOTALS):
            self.assertEqual(
                sum(session[turn_slot].input_length for session in trace.sessions),
                target,
            )

    def test_session_extension_and_cross_session_prefix(self) -> None:
        trace = self.trace
        for session in trace.sessions:
            self.assertEqual(len(session), 24)
            self.assertTrue(
                all(
                    right.input_length > left.input_length
                    for left, right in zip(session, session[1:])
                )
            )
        prefix = replay.PrefixAsset(
            path="unit",
            file_sha256="unit",
            token_ids_sha256="unit",
            decoded_prefix_sha256="unit",
            tokenizer_files_sha256={},
            vocab_size=151_936,
            token_ids=tuple([42] * replay.SHARED_PREFIX_TOKENS),
        )
        first = replay.build_input_ids(
            trace.sessions[0][0], self.token_map, prefix, self.base
        )
        sibling = replay.build_input_ids(
            trace.sessions[1][0], self.token_map, prefix, self.base
        )
        followup = replay.build_input_ids(
            trace.sessions[0][1], self.token_map, prefix, self.base
        )
        self.assertEqual(
            first[: replay.SHARED_PREFIX_TOKENS],
            sibling[: replay.SHARED_PREFIX_TOKENS],
        )
        self.assertNotEqual(first, sibling)
        self.assertEqual(first, followup[: len(first)])


if __name__ == "__main__":
    unittest.main()
