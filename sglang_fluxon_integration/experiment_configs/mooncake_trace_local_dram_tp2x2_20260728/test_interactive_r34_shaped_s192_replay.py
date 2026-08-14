#!/usr/bin/env python3
"""Focused invariants for the nested S192 r34-shaped workload."""

from __future__ import annotations

import hashlib
import importlib.util
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


s96 = load_module(
    "interactive_r34_shaped_s96_for_s192_test",
    HERE / "interactive_r34_shaped_replay.py",
)
s192 = load_module(
    "interactive_r34_shaped_s192_tested",
    HERE / "interactive_r34_shaped_s192_replay.py",
)


class PureInvariantTests(unittest.TestCase):
    def test_only_working_set_dimensions_change(self) -> None:
        self.assertEqual(s192.SESSIONS, 192)
        self.assertEqual(s192.TURNS, s96.TURNS)
        self.assertEqual(s192.CONCURRENCY, 24)
        self.assertEqual(s192.OUTPUT_TOKENS, s96.OUTPUT_TOKENS)
        self.assertEqual(s192.SHARED_PREFIX_TOKENS, s96.SHARED_PREFIX_TOKENS)
        self.assertEqual(s192.SELECTION_KEY_PROFILE, s96.PROFILE)
        self.assertEqual(s192.PREFIX_ASSET_PROFILE, s96.PROFILE)
        self.assertEqual(
            s192.R34_TURN_PROMPT_TOTALS,
            tuple(value * 2 for value in s96.R34_TURN_PROMPT_TOTALS),
        )

    def test_s96_prefix_asset_is_explicitly_reused(self) -> None:
        value = {
            "schema": s192.PREFIX_ASSET_SCHEMA,
            "profile": s192.PREFIX_ASSET_PROFILE,
            "vocab_size": 128,
            "tokenizer_files_sha256": {"tokenizer.json": "a" * 64},
            "decoded_prefix_sha256": "b" * 64,
            "token_ids": [7] * s192.SHARED_PREFIX_TOKENS,
        }
        value["token_ids_sha256"] = hashlib.sha256(
            s192.canonical_json_bytes(value["token_ids"])
        ).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prefix.json"
            path.write_bytes(s192.canonical_json_bytes(value) + b"\n")
            loaded = s192.load_prefix_asset(path, s192.sha256_file(path), 128)
            self.assertEqual(len(loaded.token_ids), 4096)


class FullTraceInvariantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        trace_raw = os.environ.get("INTERACTIVE_R34_TRACE")
        if not trace_raw:
            raise unittest.SkipTest("set INTERACTIVE_R34_TRACE")
        cls.s96_trace = s96.build_shaped_trace(Path(trace_raw))
        cls.s192_trace = s192.build_shaped_trace(Path(trace_raw))

    def test_nested_selection_length_and_wss_identity(self) -> None:
        trace = self.s192_trace
        self.assertEqual(trace.candidate_count, 444)
        self.assertEqual(len(trace.selected_users), 192)
        self.assertEqual(trace.selected_users[:96], self.s96_trace.selected_users)
        self.assertEqual(len(trace.records), 4_608)
        self.assertEqual(trace.selected_users_sha256, s192.SELECTED_USERS_SHA256)
        self.assertEqual(
            trace.selection_coordinates_sha256, s192.SELECTION_COORDINATES_SHA256
        )
        self.assertEqual(trace.shaped_records_sha256, s192.SHAPED_RECORDS_SHA256)
        self.assertEqual(trace.prompt_tokens, 102_714_976)
        self.assertEqual(trace.output_tokens, 36_864)
        self.assertEqual((trace.min_input, trace.max_input), (12_746, 42_863))
        self.assertEqual(trace.unique_exact_tokens, 4_310_590)
        self.assertEqual(trace.unique_pages, 67_454)
        self.assertEqual(trace.unique_page_bytes, 636_575_809_536)
        for turn_slot, target in enumerate(s192.R34_TURN_PROMPT_TOTALS):
            self.assertEqual(
                sum(session[turn_slot].input_length for session in trace.sessions),
                target,
            )


if __name__ == "__main__":
    unittest.main()
