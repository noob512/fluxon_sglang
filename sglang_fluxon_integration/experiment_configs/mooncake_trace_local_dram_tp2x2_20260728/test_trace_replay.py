#!/usr/bin/env python3

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import io
import json
import os
import shlex
import subprocess
import tempfile
import types
import unittest
from unittest import mock
from collections import defaultdict
from pathlib import Path

import mooncake_trace_replay as replay
import finalize_capacity_manifest as capacity
import finalize_fluxon_f_capacity as fcapacity
import finalize_lmcache_capacity_manifest as lmcapacity
import fluxon_f_resource_observer as fobserver
import fluxon_sgl_kernel_loader as kernel_loader
import interference_observer as observer
import interactive_conversation_replay as interactive
import patch_fluxon_f_kernel_loader as kernel_patcher
import vllm_sglang_adapter as vadapter


TRACE = Path(
    "/mnt/ceph/mjq/mooncake_test/mooncake/FAST25-release/traces/"
    "conversation_trace.jsonl"
)
INTERACTIVE_TRACE = Path(
    os.environ.get(
        "INTERACTIVE_CONVERSATION_PART2_TRACE",
        "/mnt/nvme0/mjq_build/interactive_conversation_workload_6f3281b/"
        "total_workload/total_traces_part2.txt",
    )
)


class FakeContent:
    def __init__(self, lines: list[bytes]) -> None:
        self.lines = lines

    def __aiter__(self):
        self.iterator = iter(self.lines)
        return self

    async def __anext__(self) -> bytes:
        try:
            return next(self.iterator)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class FakeResponse:
    def __init__(self, status: int, body: object) -> None:
        self.status = status
        self.body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def text(self) -> str:
        if isinstance(self.body, str):
            return self.body
        return json.dumps(self.body)


class FakeSession:
    def __init__(self, responses: dict[str, FakeResponse]) -> None:
        self.responses = responses

    def get(self, url: str) -> FakeResponse:
        endpoint = url.split("/", 3)[-1]
        return self.responses[endpoint]


class TraceReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.trace = replay.load_trace(TRACE)
        replay.validate_official_trace(cls.trace)
        cls.token_map = replay.build_trie_token_map(cls.trace.records)

    def test_official_trace_invariants(self) -> None:
        self.assertEqual(len(self.trace.records), replay.TRACE_REQUESTS)
        self.assertEqual(self.trace.input_tokens, replay.TRACE_INPUT_TOKENS)
        self.assertEqual(self.trace.output_tokens, replay.TRACE_OUTPUT_TOKENS)
        self.assertEqual(self.trace.max_context, replay.TRACE_MAX_CONTEXT)
        self.assertEqual(self.trace.longest_index, replay.TRACE_LONGEST_INDEX)
        self.assertEqual(self.token_map.node_count, 182_790)
        self.assertLessEqual(self.token_map.max_fanout, replay.TOKEN_SPAN)

    def test_shared_and_diverging_prefixes(self) -> None:
        first = replay.build_input_ids(self.trace.records[0], self.token_map)
        second = replay.build_input_ids(self.trace.records[1], self.token_map)
        self.assertEqual(first[: replay.BLOCK_TOKENS], second[: replay.BLOCK_TOKENS])
        self.assertNotEqual(first[replay.BLOCK_TOKENS], second[replay.BLOCK_TOKENS])

    def test_sibling_first_tokens_are_unique(self) -> None:
        tokens_by_parent: dict[int, set[int]] = defaultdict(set)
        counts_by_parent: dict[int, int] = defaultdict(int)
        for node, parent in self.token_map.parent_by_node.items():
            tokens_by_parent[parent].add(self.token_map.first_token_by_node[node])
            counts_by_parent[parent] += 1
        for parent, count in counts_by_parent.items():
            self.assertEqual(len(tokens_by_parent[parent]), count)

    def test_partial_block_and_token_range(self) -> None:
        record = self.trace.records[85]
        self.assertEqual(record.input_length % replay.BLOCK_TOKENS, 1)
        input_ids = replay.build_input_ids(record, self.token_map)
        self.assertEqual(len(input_ids), record.input_length)
        self.assertGreaterEqual(min(input_ids), replay.TOKEN_BASE)
        self.assertLess(max(input_ids), replay.TOKEN_MAX_EXCLUSIVE)

    def test_payload_is_deterministic(self) -> None:
        record = self.trace.records[3]
        first = replay.build_payload_bytes(record, self.token_map)
        second = replay.build_payload_bytes(record, self.token_map)
        self.assertEqual(first, second)
        self.assertIn(b'"ignore_eos":true', first)
        self.assertIn(b'"rid":"mc-conversation-00003"', first)

    def test_openai_payload_preserves_native_token_ids(self) -> None:
        record = self.trace.records[3]
        model = "/public/mjq/models/Qwen3-VL-8B-Instruct"
        encoded = replay.build_payload_bytes(
            record, self.token_map, api_kind="openai", expected_model=model
        )
        payload = json.loads(encoded)
        self.assertEqual(payload["model"], model)
        self.assertEqual(payload["request_id"], "mc-conversation-00003")
        self.assertEqual(payload["prompt"], replay.build_input_ids(record, self.token_map))
        self.assertEqual(len(payload["prompt"]), record.input_length)
        self.assertFalse(payload["add_special_tokens"])
        self.assertTrue(payload["return_token_ids"])
        self.assertTrue(payload["stream_options"]["include_usage"])
        self.assertTrue(payload["stream_options"]["continuous_usage_stats"])
        self.assertEqual(payload["max_tokens"], record.output_length)

    def test_smoke_selection_contains_longest(self) -> None:
        selected = replay.select_records(self.trace, "smoke")
        self.assertEqual(len(selected), 32)
        self.assertEqual(selected[-1].record.index, replay.TRACE_LONGEST_INDEX)
        self.assertEqual(
            [
                right.schedule_timestamp_ms - left.schedule_timestamp_ms
                for left, right in zip(selected, selected[1:])
            ],
            [replay.SMOKE_INTERVAL_MS] * 31,
        )
        self.assertLess(
            selected[-1].schedule_timestamp_ms,
            self.trace.records[replay.TRACE_LONGEST_INDEX].timestamp_ms,
        )

    def test_smoke_dispatch_is_strictly_serial(self) -> None:
        base = replay.select_records(self.trace, "smoke")[0]
        selected = tuple(
            replay.ScheduledRecord(
                record=self.trace.records[index],
                schedule_timestamp_ms=base.schedule_timestamp_ms,
            )
            for index in range(3)
        )
        active = maximum = 0
        order: list[int] = []

        async def fake_send_one(**kwargs):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            index = kwargs["scheduled"].record.index
            order.append(index)
            await asyncio.sleep(0.001)
            active -= 1
            return {"request_index": index}

        async def run():
            loop = asyncio.get_running_loop()
            with mock.patch.object(replay, "send_one", new=fake_send_one):
                return await replay.dispatch_selected_records(
                    selected=selected,
                    mode="smoke",
                    time_scale=1.0,
                    prepare_lead_s=0.0,
                    run_start=loop.time(),
                    session=object(),
                    generate_url="http://unused/generate",
                    token_map=self.token_map,
                    executor=object(),
                    writer=object(),
                    api_kind="sglang",
                    expected_model="model",
                )

        results = asyncio.run(run())
        self.assertEqual(maximum, 1)
        self.assertEqual(order, [0, 1, 2])
        self.assertEqual([item["request_index"] for item in results], order)

    def test_sse_parser(self) -> None:
        async def collect():
            content = FakeContent(
                [
                    b'data: {"text":"a","meta_info":{"completion_tokens":1}}\n',
                    b"\n",
                    b'data: {"text":"ab","meta_info":{"completion_tokens":2}}\n\n',
                    b"data: [DONE]\n",
                    b"\n",
                ]
            )
            return [item async for item in replay.iter_sse_json(content)]

        events = asyncio.run(collect())
        self.assertEqual([event["meta_info"]["completion_tokens"] for event in events], [1, 2])

    def test_tcp_connector_disables_keepalive_reuse(self) -> None:
        class FakeAiohttp:
            @staticmethod
            def TCPConnector(**kwargs):
                return kwargs

        connector = replay.make_tcp_connector(FakeAiohttp)
        self.assertEqual(connector, replay.TCP_CONNECTOR_CONFIG)
        self.assertTrue(connector["force_close"])
        self.assertEqual(connector["limit"], 0)

    def test_group_e_replay_preserves_sglang_token_ids_for_adapter(self) -> None:
        record = self.trace.records[3]
        native = replay.build_payload_bytes(record, self.token_map, api_kind="sglang")
        adapted = replay.build_payload_bytes(
            record,
            self.token_map,
            api_kind="vllm_adapter",
            expected_model="unused-by-adapter-payload",
        )
        self.assertEqual(adapted, native)
        payload = json.loads(adapted)
        self.assertEqual(payload["input_ids"], replay.build_input_ids(record, self.token_map))
        arguments = [
            "--trace",
            "trace.jsonl",
            "replay",
            "--mode",
            "smoke",
            "--group",
            "E",
            "--api-kind",
            "vllm_adapter",
            "--base-url",
            "http://router",
            "--expected-model",
            "model",
            "--vocab-size",
            "32000",
            "--run-id",
            "e_adapter_test",
            "--output-dir",
            "output",
        ]
        parsed = replay.parse_args(arguments)
        self.assertEqual(parsed.api_kind, "vllm_adapter")
        wrong = list(arguments)
        wrong[wrong.index("vllm_adapter")] = "openai"
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                replay.parse_args(wrong)

    def test_fast25_four_gpu_load_profile_is_exactly_four_x(self) -> None:
        arguments = [
            "--trace",
            "trace.jsonl",
            "replay",
            "--mode",
            "formal",
            "--group",
            "B",
            "--base-url",
            "http://router",
            "--expected-model",
            "model",
            "--vocab-size",
            "32000",
            "--capacity-manifest",
            "capacity.json",
            "--run-id",
            "four_gpu_test",
            "--output-dir",
            "output",
        ]
        default = replay.parse_args(arguments)
        self.assertEqual(default.load_profile, replay.DEFAULT_LOAD_PROFILE)
        self.assertEqual(default.time_scale, 1.0)
        self.assertEqual(default.arrival_rate_multiplier, 1.0)

        four_x = replay.parse_args(
            arguments + ["--load-profile", "four-gpu-4x"]
        )
        self.assertEqual(four_x.load_profile, "four-gpu-4x")
        self.assertEqual(four_x.time_scale, 0.25)
        self.assertEqual(four_x.arrival_rate_multiplier, 4.0)

        explicit_match = replay.parse_args(
            arguments
            + [
                "--load-profile",
                "four-gpu-4x",
                "--time-scale",
                "0.25",
            ]
        )
        self.assertEqual(explicit_match.time_scale, 0.25)

        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                replay.parse_args(arguments + ["--time-scale", "0.25"])
            with self.assertRaises(SystemExit):
                replay.parse_args(
                    arguments
                    + [
                        "--load-profile",
                        "four-gpu-4x",
                        "--time-scale",
                        "0.5",
                    ]
                )

    def test_four_gpu_summary_uses_scaled_schedule_span(self) -> None:
        selected = replay.select_records(self.trace, "formal")
        summary = replay.summarize_results(
            [],
            selected,
            900.0,
            load_profile="four-gpu-4x",
            time_scale=0.25,
            arrival_rate_multiplier=4.0,
        )
        self.assertEqual(summary["source_schedule_span_s"], 3_536.999)
        self.assertEqual(summary["schedule_span_s"], 884.24975)
        self.assertAlmostEqual(
            summary["offered_qps"], replay.TRACE_REQUESTS / 884.24975
        )
        self.assertAlmostEqual(summary["offered_qps"], 13.605884537)
        self.assertEqual(summary["arrival_rate_multiplier"], 4.0)

        descriptor = replay.load_profile_descriptor(
            self.trace, "four-gpu-4x"
        )
        self.assertEqual(descriptor["requests"], replay.TRACE_REQUESTS)
        self.assertEqual(descriptor["source_schedule_span_s"], 3_536.999)
        self.assertEqual(descriptor["schedule_span_s"], 884.24975)
        self.assertAlmostEqual(descriptor["offered_qps"], 13.605884537)
        self.assertAlmostEqual(
            descriptor["offered_prompt_tokens_per_s"], 163_747.655, places=3
        )

        parsed = replay.parse_args(
            [
                "--trace",
                "trace.jsonl",
                "validate",
                "--load-profile",
                "four-gpu-4x",
            ]
        )
        self.assertEqual(parsed.load_profile, "four-gpu-4x")

    def test_vllm_adapter_closes_token_and_usage_accounting(self) -> None:
        native = {
            "rid": "mc-conversation-00003",
            "input_ids": [1000, 1001, 1002],
            "sampling_params": {
                "temperature": 0.0,
                "max_new_tokens": 2,
                "ignore_eos": True,
            },
            "stream": True,
            "return_logprob": False,
            "log_metrics": True,
        }
        upstream, context = vadapter.build_upstream_payload(
            native,
            expected_model=vadapter.MODEL_PATH,
            vocab_size=vadapter.VOCAB_SIZE,
        )
        self.assertEqual(upstream["prompt"], native["input_ids"])
        self.assertFalse(upstream["add_special_tokens"])
        self.assertTrue(upstream["return_token_ids"])
        state = vadapter.TranslationState(
            **context,
            expected_model=vadapter.MODEL_PATH,
        )
        first = state.consume(
            {
                "id": f"cmpl-{native['rid']}",
                "model": vadapter.MODEL_PATH,
                "choices": [{"token_ids": [2000], "finish_reason": None}],
            }
        )
        final = state.consume(
            {
                "id": f"cmpl-{native['rid']}",
                "model": vadapter.MODEL_PATH,
                "choices": [{"token_ids": [2001], "finish_reason": "length"}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2},
            }
        )
        state.validate()
        self.assertEqual(first["meta_info"]["completion_tokens"], 1)
        self.assertEqual(final["meta_info"]["completion_tokens"], 2)
        self.assertEqual(state.adapter_error, "")
        self.assertEqual(state.upstream_request_id, f"cmpl-{native['rid']}")
        self.assertEqual(state.sglang_event()["meta_info"]["adapter_usage_prompt_tokens"], 3)

        bad = vadapter.TranslationState(
            **context,
            expected_model=vadapter.MODEL_PATH,
        )
        with self.assertRaisesRegex(vadapter.AdapterError, "request id mismatch"):
            bad.consume(
                {
                    "id": native["rid"],
                    "model": vadapter.MODEL_PATH,
                    "choices": [{"token_ids": [2000], "finish_reason": None}],
                }
            )

    def test_vllm_adapter_sse_parser_accepts_long_prompt_echo(self) -> None:
        class ChunkedContent:
            def __init__(self, chunks: list[bytes]) -> None:
                self.chunks = chunks

            async def iter_any(self):
                for chunk in self.chunks:
                    yield chunk

        large = b"x" * 200_000

        async def collect():
            content = ChunkedContent(
                [b"data: " + large[:70_000], large[70_000:] + b"\n\n", b"data: [DONE]\n\n"]
            )
            return [item async for item in vadapter.iter_sse_data(content)]

        self.assertEqual(asyncio.run(collect()), [large, b"[DONE]"])

    def test_formal_tp2x2_capacity_manifest(self) -> None:
        value = {
            "schema": "mooncake_local_dram_capacity_v2",
            "status": "final_measured",
            "group": "B",
            "hicache_rank_bytes": [32_001_490_944] * 4,
            "mooncake_local_instance_segment_bytes": [73_435_971_584] * 2,
            "mooncake_local_segment_bytes": 146_871_943_168,
            "mooncake_remote_segment_bytes": 274_877_906_944,
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "capacity.json"
            path.write_text(json.dumps(value) + "\n")
            loaded = replay.load_capacity_manifest(path, "B", formal=True)
        self.assertEqual(
            loaded["mooncake_local_instance_segment_bytes"],
            [73_435_971_584, 73_435_971_584],
        )

    def test_formal_rejects_doubled_instance_segments(self) -> None:
        value = {
            "schema": "mooncake_local_dram_capacity_v2",
            "status": "final_measured",
            "group": "B",
            "hicache_rank_bytes": [32_001_490_944] * 4,
            "mooncake_local_instance_segment_bytes": [146_871_943_168] * 2,
            "mooncake_local_segment_bytes": 146_871_943_168,
            "mooncake_remote_segment_bytes": 274_877_906_944,
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "capacity.json"
            path.write_text(json.dumps(value) + "\n")
            with self.assertRaises(replay.ValidationError):
                replay.load_capacity_manifest(path, "B", formal=True)

    def test_formal_group_d_zero_local_mooncake(self) -> None:
        value = {
            "schema": "mooncake_local_dram_capacity_v2",
            "status": "final_measured",
            "group": "D",
            "hicache_rank_bytes": [68_716_855_296] * 4,
            "mooncake_local_instance_segment_bytes": [0, 0],
            "mooncake_local_segment_bytes": 0,
            "local_payload_bytes": 274_867_421_184,
            "page_alignment_slack_bytes": 10_485_760,
            "local_total_bytes": 274_877_906_944,
            "mooncake_remote_segment_bytes": 274_877_906_944,
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "capacity-d.json"
            path.write_text(json.dumps(value) + "\n")
            loaded = replay.load_capacity_manifest(path, "D", formal=True)
        self.assertEqual(loaded["mooncake_local_instance_segment_bytes"], [0, 0])
        self.assertEqual(loaded["page_alignment_slack_bytes"], 10_485_760)

    def test_formal_group_d_rejects_missing_alignment_slack(self) -> None:
        value = {
            "schema": "mooncake_local_dram_capacity_v2",
            "status": "final_measured",
            "group": "D",
            "hicache_rank_bytes": [68_716_855_296] * 4,
            "mooncake_local_instance_segment_bytes": [0, 0],
            "mooncake_local_segment_bytes": 0,
            "mooncake_remote_segment_bytes": 274_877_906_944,
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "capacity-d-bad.json"
            path.write_text(json.dumps(value) + "\n")
            with self.assertRaises(replay.ValidationError):
                replay.load_capacity_manifest(path, "D", formal=True)

    def test_formal_group_e_lmcache_capacity(self) -> None:
        value = {
            "schema": "lmcache_mooncake_capacity_v2",
            "status": "final_measured",
            "group": "E",
            "lmcache_chunk_tokens": 512,
            "lmcache_chunk_bytes_per_rank": 37_748_736,
            "lmcache_rank_configured_bytes": [68_702_698_496] * 4,
            "lmcache_rank_usable_bytes": [68_664_950_784] * 4,
            "lmcache_rank_alignment_slack_bytes": [37_747_712] * 4,
            "mooncake_local_rank_segment_bytes": [16_777_216] * 4,
            "mooncake_local_segment_bytes": 67_108_864,
            "mooncake_local_rank_buffer_bytes": [1_024] * 4,
            "mooncake_local_buffer_bytes": 4_096,
            "mooncake_local_kv_usable_bytes": 0,
            "local_total_bytes": 274_877_906_944,
            "mooncake_remote_segment_bytes": 274_877_906_944,
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "capacity-e.json"
            path.write_text(json.dumps(value) + "\n")
            loaded = replay.load_capacity_manifest(path, "E", formal=True)
        self.assertEqual(
            sum(loaded["lmcache_rank_configured_bytes"])
            + sum(loaded["mooncake_local_rank_segment_bytes"]),
            256 * 1024**3 - 4_096,
        )
        self.assertEqual(
            sum(loaded["lmcache_rank_configured_bytes"])
            + sum(loaded["mooncake_local_rank_segment_bytes"])
            + sum(loaded["mooncake_local_rank_buffer_bytes"]),
            256 * 1024**3,
        )

    def test_formal_group_e_rejects_wrong_protocol_segment(self) -> None:
        value = {
            "schema": "lmcache_mooncake_capacity_v2",
            "status": "final_measured",
            "group": "E",
            "lmcache_chunk_tokens": 512,
            "lmcache_chunk_bytes_per_rank": 37_748_736,
            "lmcache_rank_configured_bytes": [68_702_698_496] * 4,
            "lmcache_rank_usable_bytes": [68_664_950_784] * 4,
            "lmcache_rank_alignment_slack_bytes": [37_747_712] * 4,
            "mooncake_local_rank_segment_bytes": [16_777_216, 16_777_216, 16_777_216, 0],
            "mooncake_local_segment_bytes": 50_331_648,
            "mooncake_local_rank_buffer_bytes": [1_024] * 4,
            "mooncake_local_buffer_bytes": 4_096,
            "mooncake_local_kv_usable_bytes": 0,
            "mooncake_remote_segment_bytes": 274_877_906_944,
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "capacity-e-bad.json"
            path.write_text(json.dumps(value) + "\n")
            with self.assertRaises(replay.ValidationError):
                replay.load_capacity_manifest(path, "E", formal=True)

    def test_formal_group_f_fluxon_capacity(self) -> None:
        manifest = {
            "schema": "fluxon_dram_capacity_v1",
            "schema_version": 1,
            "group": "F",
            "status": "final_measured",
            "cluster_name": "fluxon-mooncake-f-test",
            "ssd_enabled": False,
            "local": {
                "owner_id": "local",
                "physical_dram_bytes": 274_877_906_944,
                "configured_payload_bytes": 247_390_116_249,
                "mmap_bytes": 274_877_906_944,
                "observed_capacity_bytes": [247_390_116_249],
                "hot_capacity_ratio": 0.90,
                "rdma_hcas": ["mlx5_0", "mlx5_1", "mlx5_2", "mlx5_3"],
            },
            "remote": {
                "owner_id": "remote",
                "physical_dram_bytes": 274_877_906_944,
                "mmap_bytes": 274_877_906_944,
                "observed_capacity_bytes": [],
                "rdma_hcas": ["mlx5_0", "mlx5_1"],
            },
            "external_clients": ["client-31001", "client-31002"],
            "evidence": {"local.yaml": "a" * 64},
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "capacity-f.json"
            path.write_text(json.dumps(manifest) + "\n")
            loaded = replay.load_capacity_manifest(path, "F", formal=True)
            self.assertEqual(loaded["local"]["configured_payload_bytes"], 247_390_116_249)
            manifest["rdma_profile"] = "pplx_common_two_rail"
            manifest["local"]["rdma_hcas"] = ["mlx5_0", "mlx5_1"]
            path.write_text(json.dumps(manifest) + "\n")
            loaded = replay.load_capacity_manifest(path, "F", formal=True)
            self.assertEqual(loaded["rdma_profile"], "pplx_common_two_rail")
            manifest.pop("rdma_profile")
            path.write_text(json.dumps(manifest) + "\n")
            with self.assertRaises(replay.ValidationError):
                replay.load_capacity_manifest(path, "F", formal=True)
            manifest["rdma_profile"] = "pplx_common_two_rail"
            manifest["external_clients"] = ["duplicate", "duplicate"]
            path.write_text(json.dumps(manifest) + "\n")
            with self.assertRaises(replay.ValidationError):
                replay.load_capacity_manifest(path, "F", formal=True)

    def test_fluxon_capacity_local_hca_profiles(self) -> None:
        self.assertEqual(
            fcapacity.local_hcas_for_profile("legacy_four_rail"),
            ["mlx5_0", "mlx5_1", "mlx5_2", "mlx5_3"],
        )
        self.assertEqual(
            fcapacity.local_hcas_for_profile("pplx_common_two_rail"),
            ["mlx5_0", "mlx5_1"],
        )
        with self.assertRaisesRegex(SystemExit, "unsupported local RDMA profile"):
            fcapacity.local_hcas_for_profile("unknown")

    def test_fluxon_capacity_log_parser_strips_ansi_csi(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "owner.log"
            path.write_bytes(
                b"plain capacity_bytes=261134011596\n"
                b"\x1b[2mcapacity_bytes\x1b[0m\x1b[2m=\x1b[0m247390116249\n"
            )
            self.assertEqual(
                fcapacity.capacity_values(path),
                [247_390_116_249, 261_134_011_596],
            )

    def test_fluxon_router_waits_for_registered_models(self) -> None:
        launcher = (
            Path(__file__).resolve().parent / "launch_fluxon_f_router.sh"
        ).read_text()
        self.assertIn('local models_tmp="${models_path}.tmp.$$"', launcher)
        self.assertIn(
            "until curl -fsS --max-time 10 "
            "http://127.0.0.1:32000/v1/models -o \"$models_tmp\"",
            launcher,
        )
        self.assertIn('mv "$models_tmp" "$models_path"', launcher)

    def test_fluxon_runtime_preparer_installs_focused_kernel(self) -> None:
        preparer = (
            Path(__file__).resolve().parent / "prepare_fluxon_f_gpu_runtime.sh"
        ).read_text()
        self.assertIn(kernel_loader.EXPECTED_LIBRARY_SHA256, preparer)
        self.assertIn(
            'install -m 0555 "$deployment_dir/fluxon_sgl_kernel_ops_cuda13.so"',
            preparer,
        )
        self.assertIn('"$deployment_dir/patch_fluxon_f_kernel_loader.py"', preparer)
        self.assertIn(
            '--output "$mem_cache/unified_radix_cache.py"',
            preparer,
        )
        self.assertIn("kernel_library = load_fluxon_sgl_kernel_ops()", preparer)

    def test_group_e_measured_capacity_generator(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            configs = [root / "instance0.yaml", root / "instance1.yaml"]
            commands = [root / "instance0.argv", root / "instance1.argv"]
            logs = [root / "instance0.log", root / "instance1.log"]
            metrics = [root / "instance0.metrics", root / "instance1.metrics"]
            master_metrics = root / "master.metrics"
            gpu_ip = "10.0.0.1"
            for index in range(2):
                devices = "mlx5_0,mlx5_1" if index == 0 else "mlx5_2,mlx5_3"
                config = lmcapacity.expected_config(gpu_ip, devices)
                top_level = [
                    key for key in config if not key.startswith("extra_config.")
                ]
                config_lines = [
                    f"{key}: {json.dumps(config[key]).lower() if isinstance(config[key], bool) else json.dumps(config[key])}"
                    for key in top_level
                ]
                config_lines.append("extra_config:")
                for key, value in config.items():
                    if not key.startswith("extra_config."):
                        continue
                    nested = key.split(".", 1)[1]
                    rendered = json.dumps(value).lower() if isinstance(value, bool) else json.dumps(value)
                    config_lines.append(f"  {nested}: {rendered}")
                configs[index].write_text("\n".join(config_lines) + "\n")
                commands[index].write_text(
                    shlex.join(lmcapacity.expected_command(31001 + index)) + "\n"
                )
                geometry = (
                    "num_layer: 36, chunk_size: 512, num_kv_head (per gpu): 4, "
                    "head_size: 128, hidden_dim (D) for KV (per gpu): 512, "
                    "use mla: False, kv shape: (36, 2, 512, 4, 128)"
                )
                setup = {
                    "global_segment_size": "16777216",
                    "local_buffer_size": "1024",
                    "local_hostname": gpu_ip,
                    "metadata_server": "***REDACTED***",
                    "device_name": devices,
                    "rdma_devices": devices,
                    "master_server_address": "***REDACTED***",
                    "master_server_addr": "127.0.0.1:51081",
                }
                log_lines = ["Application startup complete."]
                for rank in range(2):
                    log_lines.extend(
                        [
                            geometry,
                            "LMCache initialized for role KVConnectorRole.WORKER with version 0.5.2, "
                            "vllm version 0.24.0, lmcache cache_engine metadata: "
                            f"LMCacheMetadata(world_size=2, worker_id={rank}, "
                            "kv_shape=(36, 2, 512, 4, 128), role='worker')",
                            f"Setting up Mooncake store with setup_config: {setup!r} "
                            "\x1b[3m(mooncakestore_connector.py:370)\x1b[0m",
                            "Successfully created client on port 12626 after 1 attempt(s)",
                            "Mounting segment: 16777216 bytes, 16777216 of 16777216",
                            "Registered: 0x1234, 68702698496 bytes",
                            "Mooncake store setup completed successfully",
                        ]
                    )
                logs[index].write_text("\n".join(log_lines) + "\n")
                metrics[index].write_text(
                    'lmcache:local_cache_usage{model_name="m",worker_id="0",role="worker",served_model_name="m"} 0.0\n'
                    'lmcache:local_cache_usage{model_name="m",worker_id="1",role="worker",served_model_name="m"} 0.0\n'
                )
            master_metrics.write_text(
                "master_total_capacity_bytes 274945015808\n"
                "master_active_clients 5\n"
                "master_mount_segment_failures_total 0\n"
                'segment_total_capacity_bytes{segment="remote"} 274877906944\n'
                'segment_total_capacity_bytes{segment="gpu0"} 16777216\n'
                'segment_total_capacity_bytes{segment="gpu1"} 16777216\n'
                'segment_total_capacity_bytes{segment="gpu2"} 16777216\n'
                'segment_total_capacity_bytes{segment="gpu3"} 16777216\n'
            )

            overlay = root / "OVERLAY_MANIFEST.json"
            overlay_value = {
                "schema": "vllm_lmcache_overlay_v1",
                "tree_sha256": "a" * 64,
                "wheel_manifest_sha256": "b" * 64,
                "installed_distributions": {"vllm": "0.24.0", "lmcache": "0.5.2"},
                "import_smoke": {
                    "vllm": "0.24.0",
                    "lmcache": "0.5.2",
                    "mooncake": "0.3.11.post1",
                    "cuda_available": True,
                    "gpu_count": 8,
                },
            }
            overlay.write_text(json.dumps(overlay_value) + "\n")
            overlay_sha = hashlib.sha256(overlay.read_bytes()).hexdigest()
            output = root / "capacity-e.json"
            rc = lmcapacity.main(
                [
                    "--lmcache-config",
                    *map(str, configs),
                    "--command-argv",
                    *map(str, commands),
                    "--vllm-log",
                    *map(str, logs),
                    "--metrics-file",
                    *map(str, metrics),
                    "--master-metrics-file",
                    str(master_metrics),
                    "--overlay-manifest",
                    str(overlay),
                    "--overlay-manifest-sha256",
                    overlay_sha,
                    "--namespace",
                    "e_test",
                    "--gpu-private-ip",
                    gpu_ip,
                    "--remote-hostname",
                    "cpu-only",
                    "--remote-private-ip",
                    "10.0.0.2",
                    "--output",
                    str(output),
                ]
            )
            value = json.loads(output.read_text())
            logs[0].write_text(
                logs[0].read_text() + "Buffer registration failed: error=-600\n"
            )
            with self.assertRaises(SystemExit):
                lmcapacity.validate_instance(
                    0,
                    configs[0],
                    commands[0],
                    logs[0],
                    metrics[0],
                    gpu_ip,
                )
        self.assertEqual(rc, 0)
        self.assertEqual(value["lmcache_chunk_bytes_per_rank"], 37_748_736)
        self.assertEqual(value["lmcache_chunks_per_rank"], 1819)
        self.assertEqual(value["lmcache_rank_configured_bytes"], [68_702_698_496] * 4)
        self.assertEqual(value["mooncake_local_rank_segment_bytes"], [16_777_216] * 4)
        self.assertEqual(value["mooncake_local_rank_buffer_bytes"], [1_024] * 4)
        self.assertEqual(value["mooncake_local_kv_usable_bytes"], 0)
        self.assertEqual(value["local_total_bytes"], 256 * 1024**3)

    def test_interference_observer_distinguishes_vllm(self) -> None:
        model = "/public/mjq/models/Qwen3-VL-8B-Instruct"
        argv = [
            "/public/mjq/.venv_sglang_fluxon/bin/python",
            "-m",
            "vllm.entrypoints.cli.main",
            "serve",
            model,
            "--port",
            "31001",
            "--tensor-parallel-size",
            "2",
        ]
        self.assertIsNone(
            observer.classify(argv, "gpu", model, [31001, 31002], engine="vllm")
        )
        self.assertEqual(
            observer.classify(argv, "gpu", model, [31001, 31002], engine="sglang"),
            "external_vllm",
        )
        self.assertEqual(
            observer.classify(argv, "cpu", model, [31001, 31002], engine="vllm"),
            "external_vllm",
        )

    def test_fluxon_observer_tracks_renamed_worker_parent(self) -> None:
        parents = {40: 30, 30: 1, 50: 1}
        commands = {
            40: ["sglang::scheduler_TP0"],
            30: ["/tmp/fluxon_run/venv/bin/python", "-m", "sglang.launch_server"],
            50: ["sglang::scheduler_TP0"],
        }
        with (
            mock.patch.object(
                fobserver, "pid_parent", side_effect=lambda pid: parents.get(pid, 0)
            ),
            mock.patch.object(
                fobserver, "pid_cmdline", side_effect=lambda pid: commands.get(pid, [])
            ),
            mock.patch.object(fobserver, "pid_exe", return_value="/usr/bin/python3.10"),
        ):
            self.assertTrue(
                fobserver.pid_belongs_to_runtime(
                    40, "/tmp/fluxon_run/", "/tmp/fluxon_run"
                )
            )
            self.assertFalse(
                fobserver.pid_belongs_to_runtime(
                    50, "/tmp/fluxon_run/", "/tmp/fluxon_run"
                )
            )

    def test_fluxon_observer_skips_ss_without_required_ports(self) -> None:
        with mock.patch.object(
            fobserver,
            "listening_ports",
            side_effect=AssertionError("ss must not run for an empty port gate"),
        ):
            self.assertEqual(fobserver.missing_listening_ports([]), [])
        with mock.patch.object(fobserver, "listening_ports", return_value={31001}):
            self.assertEqual(
                fobserver.missing_listening_ports([31001, 31002]), [31002]
            )

    def test_fluxon_observer_probe_starts_new_session(self) -> None:
        completed = subprocess.CompletedProcess(
            ["probe"], 0, stdout="probe-output", stderr=""
        )
        with mock.patch.object(
            fobserver.subprocess, "run", return_value=completed
        ) as mocked:
            result = fobserver.run_checked(["probe", "--flag"])
        self.assertIs(result, completed)
        mocked.assert_called_once_with(
            ["probe", "--flag"],
            check=True,
            text=True,
            capture_output=True,
            start_new_session=True,
        )

    def test_fluxon_kernel_loader_is_exact_and_idempotent(self) -> None:
        fake_torch = types.SimpleNamespace(
            __version__="2.11.0+cu130",
            version=types.SimpleNamespace(cuda="13.0"),
            ops=types.SimpleNamespace(load_library=mock.Mock()),
            _C=types.SimpleNamespace(
                _dispatch_has_kernel_for_dispatch_key=mock.Mock(return_value=True)
            ),
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            library = Path(tmpdir) / "fluxon_sgl_kernel_ops_cuda13.so"
            library.write_bytes(b"focused-library")
            kernel_loader._LOADED_PATH = None
            with (
                mock.patch.object(
                    kernel_loader,
                    "sha256",
                    return_value=kernel_loader.EXPECTED_LIBRARY_SHA256,
                ),
                mock.patch.object(
                    kernel_loader.importlib,
                    "import_module",
                    return_value=fake_torch,
                ),
            ):
                first = kernel_loader.load_fluxon_sgl_kernel_ops(library)
                second = kernel_loader.load_fluxon_sgl_kernel_ops(library)
            kernel_loader._LOADED_PATH = None
        self.assertEqual(first, second)
        fake_torch.ops.load_library.assert_called_once_with(str(first))
        self.assertEqual(
            fake_torch._C._dispatch_has_kernel_for_dispatch_key.call_count,
            len(kernel_loader.CUDA_OPS),
        )

    def test_fluxon_kernel_patcher_is_exact_and_reversible(self) -> None:
        root = Path(__file__).resolve().parents[1]
        source = (
            root
            / "e44_local_slot_tier_20260716"
            / "unified_radix_cache_e44_r61_tp_execute_commit.py"
        ).read_bytes()
        output = kernel_patcher.transform(source)
        self.assertEqual(output.count(b"load_fluxon_sgl_kernel_ops()"), 1)
        self.assertLess(
            output.index(b"load_fluxon_sgl_kernel_ops()"),
            output.index(b"from sglang.jit_kernel"),
        )
        self.assertEqual(
            output.replace(
                kernel_patcher.REPLACEMENT.encode("utf-8"),
                kernel_patcher.ANCHOR.encode("utf-8"),
                1,
            ),
            source,
        )

    def test_group_d_measured_capacity_generator(self) -> None:
        allocation = "Allocating 68.72 GB host memory for hierarchical KV cache."
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            logs = [root / "instance0.log", root / "instance1.log"]
            metrics = [root / "instance0.metrics", root / "instance1.metrics"]
            for log in logs:
                log.write_text(
                    f"tp_size=2\n[2026-07-29 TP0] {allocation}\n"
                    f"[2026-07-29 TP1] {allocation}\n"
                )
            for metric in metrics:
                metric.write_text(
                    'sglang:hicache_host_total_tokens{tp_rank="0"} 932032\n'
                )
            output = root / "capacity-d.json"
            rc = capacity.main(
                [
                    "--group",
                    "D",
                    "--hicache-size-gb",
                    "0",
                    "--hicache-ratio",
                    "4.65984",
                    "--mooncake-local-instance-segment-bytes",
                    "0",
                    "0",
                    "--sglang-log",
                    str(logs[0]),
                    str(logs[1]),
                    "--metrics-file",
                    str(metrics[0]),
                    str(metrics[1]),
                    "--namespace",
                    "d_test",
                    "--gpu-private-ip",
                    "10.0.0.1",
                    "--instance0-gpus",
                    "4",
                    "5",
                    "--instance1-gpus",
                    "6",
                    "7",
                    "--remote-hostname",
                    "cpu-only",
                    "--remote-private-ip",
                    "10.0.0.2",
                    "--output",
                    str(output),
                ]
            )
            value = json.loads(output.read_text())
        self.assertEqual(rc, 0)
        self.assertEqual(value["hicache_rank_bytes"], [68_716_855_296] * 4)
        self.assertEqual(value["mooncake_local_segment_bytes"], 0)
        self.assertEqual(value["page_alignment_slack_bytes"], 10_485_760)
        self.assertEqual(value["topology"]["instance0"]["gpus"], [4, 5])
        self.assertEqual(value["topology"]["instance1"]["gpus"], [6, 7])

    def test_interactive_formal_high_window_identity_and_mapping_basis(self) -> None:
        trace = interactive.load_raw_trace(
            INTERACTIVE_TRACE,
            interactive.TRACE_SHA256,
            interactive.FORMAL_HIGH_10M_PROFILE,
        )
        self.assertEqual(trace.window_profile, "formal-high-10m")
        self.assertEqual((trace.window_start_s, trace.window_end_s), (10_020, 10_620))
        self.assertEqual(trace.window_duration_s, 600)
        self.assertEqual(len(trace.records), 22_631)
        self.assertEqual(trace.users, 2_760)
        self.assertEqual(trace.query_tokens, 788_880)
        self.assertEqual(trace.prompt_tokens, 29_576_894)
        self.assertEqual(trace.output_tokens, 1_015_642)
        self.assertEqual((trace.max_input, trace.max_context, trace.max_round), (5_546, 5_592, 116))
        self.assertEqual(
            trace.selected_raw_sha256,
            "f2f437c622c016c4bf9cb9abb6a38947d1ed593fb535b494bf809ae875bfa7c8",
        )
        self.assertEqual(
            trace.selected_canonical_sha256,
            "5ad8a1c120884f754e9b072a07e6ccd1e113375c586fdf5977bde952f640e161",
        )
        self.assertEqual(len(trace.mapping_records), 101_111)
        self.assertEqual((trace.records[0].index, trace.records[-1].index), (71_899, 94_529))
        self.assertIs(trace.records[0], trace.mapping_records[71_899])
        token_map = replay.build_trie_token_map(trace.mapping_records)
        descriptor = interactive.trace_descriptor(trace, token_map)
        self.assertEqual(descriptor["selection"]["profile"], "formal-high-10m")
        self.assertEqual(descriptor["token_mapping"]["basis_records"], 101_111)
        self.assertEqual(descriptor["token_mapping"]["basis_start_s"], 7_200)
        self.assertEqual(descriptor["token_mapping"]["basis_end_s"], 10_800)

    def test_interactive_high_window_is_unique_global_and_basis_max(self) -> None:
        trace = interactive.load_raw_trace(
            INTERACTIVE_TRACE,
            interactive.TRACE_SHA256,
            interactive.FORMAL_HIGH_10M_PROFILE,
        )
        self.assertEqual(
            trace.high_pressure_proof,
            {
                "alignment": "integer_seconds",
                "duration_s": 600,
                "full_trace": {
                    "domain_start_s": 7_200,
                    "domain_end_s": 25_054,
                    "max_records": 22_631,
                    "max_starts_s": [10_020],
                },
                "token_mapping_basis": {
                    "domain_start_s": 7_200,
                    "domain_end_s": 10_800,
                    "max_records": 22_631,
                    "max_starts_s": [10_020],
                },
            },
        )

    def test_interactive_legacy_windows_remain_exact_and_arbitrary_crop_is_rejected(self) -> None:
        low = interactive.load_raw_trace(
            INTERACTIVE_TRACE,
            interactive.TRACE_SHA256,
            interactive.EVIDENCE_LOW_10M_PROFILE,
        )
        self.assertEqual((low.window_start_s, low.window_end_s), (7_200, 7_800))
        self.assertEqual(len(low.records), 5_594)
        self.assertEqual(
            low.selected_raw_sha256,
            "da6d2b5b1f3be9e39b2ef8e60015a0edaac55142deb58bb69d3fe2a88a164f86",
        )
        self.assertEqual(
            low.selected_canonical_sha256,
            "866f5c2b9b2d9c8826efdc53edfc7fd837a5bf04be2e47f5b48e0749a4e5f272",
        )
        self.assertEqual(low.records, low.mapping_records[:5_594])
        legacy = interactive.load_raw_trace(
            INTERACTIVE_TRACE,
            interactive.TRACE_SHA256,
            interactive.LEGACY_ONE_HOUR_PROFILE,
        )
        self.assertEqual((legacy.window_start_s, legacy.window_end_s), (7_200, 10_800))
        self.assertEqual(len(legacy.records), 101_111)
        self.assertEqual(
            legacy.selected_raw_sha256,
            "878ba2cf89f92f7573ce9f0f305091d96565ddbe492527bbe0670f7cd8e5b58d",
        )
        self.assertEqual(
            legacy.selected_canonical_sha256,
            "a1d09bd16eeabd9288bb39b45a4475114fe2a4c2bd76f20549505ef9f99ae2ad",
        )
        self.assertEqual(legacy.records, legacy.mapping_records)
        with self.assertRaisesRegex(interactive.ValidationError, "unsupported window profile"):
            interactive.load_raw_trace(
                INTERACTIVE_TRACE,
                interactive.TRACE_SHA256,
                "10021-to-10621",
            )

    def test_interactive_replay_profiles_and_d_e_f_api_contract(self) -> None:
        common = [
            "--trace",
            "/trace",
            "--base-replayer",
            "/base",
            "replay",
            "--base-url",
            "http://router",
            "--expected-model",
            "/model",
            "--vocab-size",
            "151936",
            "--capacity-manifest",
            "/capacity",
            "--run-id",
            "run_1",
            "--output-dir",
            "/output",
        ]
        self.assertEqual(interactive.parse_args(common).group, "D")
        self.assertEqual(
            interactive.parse_args(common).window_profile,
            interactive.FORMAL_HIGH_10M_PROFILE,
        )
        explicit_e = common[:5] + ["--group", "E"] + common[5:]
        self.assertEqual(interactive.parse_args(explicit_e).group, "E")
        explicit_f = common[:5] + ["--group", "F"] + common[5:]
        self.assertEqual(interactive.parse_args(explicit_f).group, "F")
        legacy = common[:4] + [
            "--window-profile",
            interactive.LEGACY_ONE_HOUR_PROFILE,
        ] + common[4:]
        self.assertEqual(
            interactive.parse_args(legacy).window_profile,
            interactive.LEGACY_ONE_HOUR_PROFILE,
        )
        self.assertEqual(interactive.highpressure_group("D"), "D-highpressure")
        self.assertEqual(interactive.highpressure_group("E"), "E-highpressure")
        self.assertEqual(interactive.highpressure_group("F"), "F-highpressure")
        self.assertEqual(interactive.api_kind_for_group("D"), "sglang")
        self.assertEqual(interactive.api_kind_for_group("E"), "vllm_adapter")
        self.assertEqual(interactive.api_kind_for_group("F"), "sglang")
        with self.assertRaises(interactive.ValidationError):
            interactive.highpressure_group("G")
        with self.assertRaises(interactive.ValidationError):
            interactive.api_kind_for_group("G")
        for illegal in (
            common[:4] + ["--window-profile", "custom-600s"] + common[4:],
            common[:4] + ["--window-duration-s", "600"] + common[4:],
        ):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    interactive.parse_args(illegal)

    def test_router_model_identity_uses_v1_models(self) -> None:
        expected = "/public/mjq/models/Qwen3-VL-8B-Instruct"
        session = FakeSession(
            {
                "health": FakeResponse(200, "OK"),
                "model_info": FakeResponse(404, ""),
                "get_server_info": FakeResponse(404, ""),
                "v1/models": FakeResponse(
                    200, {"data": [{"id": expected, "object": "model"}]}
                ),
            }
        )
        checks = asyncio.run(
            replay.endpoint_preflight(session, "http://router", expected, formal=True)
        )
        self.assertEqual(checks["model_identity"]["source"], "v1/models")
        self.assertEqual(checks["model_identity"]["actual_models"], [expected])

    def test_router_model_identity_rejects_wrong_model(self) -> None:
        session = FakeSession(
            {
                "health": FakeResponse(200, "OK"),
                "model_info": FakeResponse(404, ""),
                "get_server_info": FakeResponse(404, ""),
                "v1/models": FakeResponse(200, {"data": [{"id": "wrong"}]}),
            }
        )
        with self.assertRaises(replay.ValidationError):
            asyncio.run(
                replay.endpoint_preflight(
                    session,
                    "http://router",
                    "/public/mjq/models/Qwen3-VL-8B-Instruct",
                    formal=True,
                )
            )

    def test_group_e_router_targets_sglang_compatible_adapters(self) -> None:
        root = Path(__file__).resolve().parent
        wrapper = (root / "launch_tp2x2_trace.sh").read_text()
        base = (root / "base_launcher_tp2x2.sh").read_text()
        self.assertIn('if [[ "$group" == E ]]; then', wrapper)
        self.assertIn("expected_router_worker0_port=31101", wrapper)
        self.assertIn("expected_router_worker1_port=31102", wrapper)
        self.assertIn("expected_router_worker0_port=31001", wrapper)
        self.assertIn("expected_router_worker1_port=31002", wrapper)
        self.assertIn('export GPU0_ROUTER_WORKER_PORT="$expected_router_worker0_port"', wrapper)
        self.assertIn('export GPU1_ROUTER_WORKER_PORT="$expected_router_worker1_port"', wrapper)
        self.assertIn(
            'GPU0_ROUTER_WORKER_PORT="${GPU0_ROUTER_WORKER_PORT:-$GPU0_SGLANG_PORT}"',
            base,
        )
        self.assertIn(
            'GPU1_ROUTER_WORKER_PORT="${GPU1_ROUTER_WORKER_PORT:-$GPU1_SGLANG_PORT}"',
            base,
        )
        self.assertIn('http://$GPU0_ROUTER_WORKER_HOST:$GPU0_ROUTER_WORKER_PORT', base)
        self.assertIn('http://$GPU1_ROUTER_WORKER_HOST:$GPU1_ROUTER_WORKER_PORT', base)
        self.assertNotIn('--backend "$ROUTER_BACKEND"', base)
        adapter_launcher = (root / "launch_vllm_sglang_adapters.sh").read_text()
        self.assertIn("node0) listen_port=31101; upstream_port=31001", adapter_launcher)
        self.assertIn("node1) listen_port=31102; upstream_port=31002", adapter_launcher)
        self.assertIn("PYTHONDONTWRITEBYTECODE=1", adapter_launcher)
        self.assertIn("tmux display-message -p", adapter_launcher)
        self.assertIn("#{pane_pid}", adapter_launcher)
        self.assertNotIn("setsid bash -c", adapter_launcher)

    def test_vllm_launcher_pins_ninja_runtime_and_path(self) -> None:
        launcher = (
            Path(__file__).resolve().parent / "launch_vllm_lmcache_tp2x2.sh"
        ).read_text()
        self.assertIn(
            "expected_ninja_sha256="
            "696f9628a79d9ce50314cf9556d7cd1a1d1ec52b8fd52828f6f9db1719565b67",
            launcher,
        )
        self.assertIn(
            "expected_ninja_version=1.13.0.git.kitware.jobserver-pipe-1",
            launcher,
        )
        self.assertIn('ninja_bin="$shared_mjq/.venv_sglang_fluxon/bin/ninja"', launcher)
        self.assertIn('PATH=$(printf %q "$runtime_path")', launcher)
        self.assertIn('"ninja_sha256=$ninja_sha256"', launcher)
        self.assertIn("lmcache_rank_bytes=68702698496", launcher)
        self.assertIn("mooncake_rank_segment_bytes=16777216", launcher)
        self.assertIn("mooncake_rank_local_buffer_bytes=1024", launcher)
        self.assertIn('mooncake_rdma_devices: \\"$device_names\\"', launcher)
        self.assertIn('mooncake_master_server_addr: "127.0.0.1:51081"', launcher)
        self.assertIn("PYTHONDONTWRITEBYTECODE=1", launcher)

    def test_30448_remote_requires_exact_explicit_override(self) -> None:
        root = Path(__file__).resolve().parent
        common = {
            "MOONCAKE_EXPERIMENT_RUN_ID": "remote_gate_test",
            "MOONCAKE_GPU_IP": "10.233.90.51",
            "MOONCAKE_GPU_HOSTNAME": "lgsl-a4-5f02-m9-3-h100gpu145",
            "MOONCAKE_CPU_IP": "10.233.114.150",
            "MOONCAKE_CPU_HOSTNAME": (
                "job-f8df1d36c3a6-20260728034352-6f5fb9dd4d-hl89q"
            ),
            "MOONCAKE_CPU_SSH_PORT": "30448",
            "MOONCAKE_CPU_DEVICE_NAMES": "mlx5_0,mlx5_1",
            "BASE_LAUNCHER": "/bin/true",
        }
        launchers = [
            (root / "launch_tp2x2_trace.sh", ["cpu", "status"], "D"),
            (root / "launch_vllm_lmcache_tp2x2.sh", ["status", "node0"], "E"),
        ]
        for launcher, arguments, group in launchers:
            with self.subTest(launcher=launcher.name, case="missing_override"):
                env = os.environ.copy()
                env.update(common)
                env["MOONCAKE_EXPERIMENT_GROUP"] = group
                result = subprocess.run(
                    ["bash", str(launcher), *arguments],
                    env=env,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                self.assertEqual(result.returncode, 2)
                self.assertIn("without explicit", result.stderr)
            with self.subTest(launcher=launcher.name, case="exact_override"):
                env["MOONCAKE_ALLOW_GPU_CAPABLE_REMOTE_CPU"] = "1"
                result = subprocess.run(
                    ["bash", str(launcher), *arguments],
                    env=env,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                self.assertNotIn("refusing GPU-capable 30448", result.stderr)
                self.assertNotIn("requires exact 30448 identity", result.stderr)
            with self.subTest(launcher=launcher.name, case="wrong_identity"):
                env["MOONCAKE_CPU_IP"] = "10.233.114.151"
                result = subprocess.run(
                    ["bash", str(launcher), *arguments],
                    env=env,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                self.assertEqual(result.returncode, 2)
                self.assertIn("requires exact 30448 identity", result.stderr)


if __name__ == "__main__":
    unittest.main()
