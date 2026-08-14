#!/usr/bin/env python3
"""Deterministic open-loop replay for the Mooncake FAST'25 traces.

The upstream trace contains lengths and a trie path of 512-token hash blocks,
but not the original tokens.  This client assigns a deterministic token block
to every trie node and sends either native SGLang ``input_ids`` requests or
OpenAI-compatible vLLM completion requests with the same token IDs.  Children
of the same trie node always receive different first tokens, including when
the last trace block contains only one visible token.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import socket
import statistics
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Iterable, Sequence


SCHEMA = "mooncake_fast25_sglang_native_replay_v1"
TRACE_SHA256 = "b8cbb061a85206d729d91cdc2981f43c9e0d99209dce588d3af5f7934408b9df"
TRACE_REQUESTS = 12_031
TRACE_WINDOW_MS = 3_536_999
TRACE_INPUT_TOKENS = 144_793_823
TRACE_OUTPUT_TOKENS = 4_122_048
TRACE_MAX_CONTEXT = 126_527
TRACE_LONGEST_INDEX = 11_192
SMOKE_INTERVAL_MS = 10_000
BLOCK_TOKENS = 512
TOKEN_BASE = 1_000
TOKEN_SPAN = 30_000
TOKEN_MAX_EXCLUSIVE = TOKEN_BASE + TOKEN_SPAN
MASK64 = (1 << 64) - 1
FILLER_SEED = 0x6A09E667F3BCC909
REMOTE_SEGMENT_BYTES = 274_877_906_944
LOCAL_TOTAL_BYTES = 274_877_906_944
FLUXON_F_FOUR_RAIL_HCAS = ["mlx5_0", "mlx5_1", "mlx5_2", "mlx5_3"]
FLUXON_F_COMMON_TWO_RAIL_HCAS = ["mlx5_0", "mlx5_1"]
TCP_CONNECTOR_CONFIG = {
    "limit": 0,
    "ttl_dns_cache": 300,
    "force_close": True,
}
DEFAULT_LOAD_PROFILE = "official-1x"
FORMAL_LOAD_PROFILES = {
    DEFAULT_LOAD_PROFILE: {
        "arrival_rate_multiplier": 1.0,
        "time_scale": 1.0,
    },
    "four-gpu-4x": {
        "arrival_rate_multiplier": 4.0,
        "time_scale": 0.25,
    },
}


class ValidationError(ValueError):
    pass


@dataclass(frozen=True)
class TraceRecord:
    index: int
    timestamp_ms: int
    input_length: int
    output_length: int
    hash_ids: tuple[int, ...]

    def canonical(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "timestamp": self.timestamp_ms,
            "input_length": self.input_length,
            "output_length": self.output_length,
            "hash_ids": list(self.hash_ids),
        }


@dataclass(frozen=True)
class TraceData:
    path: str
    sha256: str
    records: tuple[TraceRecord, ...]
    input_tokens: int
    output_tokens: int
    first_timestamp_ms: int
    last_timestamp_ms: int
    max_context: int
    longest_index: int


@dataclass(frozen=True)
class TrieTokenMap:
    first_token_by_node: dict[int, int]
    parent_by_node: dict[int, int]
    depth_by_node: dict[int, int]
    node_count: int
    parent_count: int
    max_fanout: int


@dataclass(frozen=True)
class ScheduledRecord:
    record: TraceRecord
    schedule_timestamp_ms: int


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def make_tcp_connector(aiohttp_module: Any) -> Any:
    # Uvicorn closes idle keep-alive connections sooner than aiohttp's default
    # connector timeout.  POST is not safe for an automatic replay after a
    # stale socket is selected, so use a fresh TCP connection for every logical
    # trace request instead of retrying an ambiguously delivered request.
    return aiohttp_module.TCPConnector(**TCP_CONNECTOR_CONFIG)


def _require_int(record: dict[str, Any], name: str, line_number: int) -> int:
    value = record.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"line {line_number}: {name} must be an integer")
    return value


def load_trace(path: Path, expected_sha256: str = TRACE_SHA256) -> TraceData:
    actual_sha256 = sha256_file(path)
    if expected_sha256 and actual_sha256 != expected_sha256:
        raise ValidationError(
            f"trace SHA256 mismatch: expected={expected_sha256} actual={actual_sha256}"
        )

    records: list[TraceRecord] = []
    previous_timestamp = -1
    input_tokens = 0
    output_tokens = 0
    max_context = -1
    longest_index = -1

    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValidationError(f"line {line_number}: invalid JSON: {exc}") from exc
            if not isinstance(raw, dict):
                raise ValidationError(f"line {line_number}: record must be an object")

            timestamp = _require_int(raw, "timestamp", line_number)
            input_length = _require_int(raw, "input_length", line_number)
            output_length = _require_int(raw, "output_length", line_number)
            hash_ids_raw = raw.get("hash_ids")

            if timestamp < previous_timestamp:
                raise ValidationError(f"line {line_number}: timestamps are not monotonic")
            if input_length <= 0 or output_length <= 0:
                raise ValidationError(
                    f"line {line_number}: input/output lengths must be positive"
                )
            if not isinstance(hash_ids_raw, list) or not hash_ids_raw:
                raise ValidationError(f"line {line_number}: hash_ids must be non-empty")
            if any(
                isinstance(item, bool) or not isinstance(item, int) or item < 0
                for item in hash_ids_raw
            ):
                raise ValidationError(
                    f"line {line_number}: hash_ids must contain non-negative integers"
                )

            expected_blocks = math.ceil(input_length / BLOCK_TOKENS)
            if len(hash_ids_raw) != expected_blocks:
                raise ValidationError(
                    f"line {line_number}: hash blocks={len(hash_ids_raw)} "
                    f"expected={expected_blocks}"
                )

            index = len(records)
            context = input_length + output_length
            if context > max_context:
                max_context = context
                longest_index = index
            records.append(
                TraceRecord(
                    index=index,
                    timestamp_ms=timestamp,
                    input_length=input_length,
                    output_length=output_length,
                    hash_ids=tuple(hash_ids_raw),
                )
            )
            previous_timestamp = timestamp
            input_tokens += input_length
            output_tokens += output_length

    if not records:
        raise ValidationError("trace is empty")

    return TraceData(
        path=str(path.resolve()),
        sha256=actual_sha256,
        records=tuple(records),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        first_timestamp_ms=records[0].timestamp_ms,
        last_timestamp_ms=records[-1].timestamp_ms,
        max_context=max_context,
        longest_index=longest_index,
    )


def validate_official_trace(trace: TraceData) -> None:
    expected = {
        "requests": TRACE_REQUESTS,
        "window_ms": TRACE_WINDOW_MS,
        "input_tokens": TRACE_INPUT_TOKENS,
        "output_tokens": TRACE_OUTPUT_TOKENS,
        "max_context": TRACE_MAX_CONTEXT,
        "longest_index": TRACE_LONGEST_INDEX,
    }
    actual = {
        "requests": len(trace.records),
        "window_ms": trace.last_timestamp_ms - trace.first_timestamp_ms,
        "input_tokens": trace.input_tokens,
        "output_tokens": trace.output_tokens,
        "max_context": trace.max_context,
        "longest_index": trace.longest_index,
    }
    if actual != expected:
        raise ValidationError(f"official trace invariants differ: {actual} != {expected}")


def build_trie_token_map(records: Sequence[TraceRecord]) -> TrieTokenMap:
    parent_by_node: dict[int, int] = {}
    depth_by_node: dict[int, int] = {}
    children: dict[int, set[int]] = defaultdict(set)

    for record in records:
        parent = -1
        for depth, node in enumerate(record.hash_ids):
            previous_parent = parent_by_node.get(node)
            if previous_parent is not None and previous_parent != parent:
                raise ValidationError(
                    f"trace node {node} has multiple parents: "
                    f"{previous_parent} and {parent}"
                )
            previous_depth = depth_by_node.get(node)
            if previous_depth is not None and previous_depth != depth:
                raise ValidationError(
                    f"trace node {node} has multiple depths: {previous_depth} and {depth}"
                )
            parent_by_node[node] = parent
            depth_by_node[node] = depth
            children[parent].add(node)
            parent = node

    max_fanout = max(len(items) for items in children.values())
    if max_fanout > TOKEN_SPAN:
        raise ValidationError(
            f"max trie fanout {max_fanout} exceeds token span {TOKEN_SPAN}"
        )

    first_token_by_node: dict[int, int] = {}
    for child_nodes in children.values():
        for ordinal, node in enumerate(sorted(child_nodes)):
            first_token_by_node[node] = TOKEN_BASE + ordinal

    if len(first_token_by_node) != len(parent_by_node):
        raise AssertionError("incomplete trie token assignment")
    return TrieTokenMap(
        first_token_by_node=first_token_by_node,
        parent_by_node=parent_by_node,
        depth_by_node=depth_by_node,
        node_count=len(parent_by_node),
        parent_count=len(children),
        max_fanout=max_fanout,
    )


def splitmix64(value: int) -> int:
    value = (value + 0x9E3779B97F4A7C15) & MASK64
    value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
    value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & MASK64
    return value ^ (value >> 31)


def token_for_offset(node: int, depth: int, offset: int, token_map: TrieTokenMap) -> int:
    if offset == 0:
        return token_map.first_token_by_node[node]
    mixed = (
        FILLER_SEED
        ^ ((node * 0xD6E8FEB86659FD93) & MASK64)
        ^ ((depth * 0xA5A3564E27F8862D) & MASK64)
        ^ ((offset * 0x9E3779B185EBCA87) & MASK64)
    )
    return TOKEN_BASE + splitmix64(mixed) % TOKEN_SPAN


def build_input_ids(record: TraceRecord, token_map: TrieTokenMap) -> list[int]:
    output: list[int] = []
    remaining = record.input_length
    for depth, node in enumerate(record.hash_ids):
        visible = min(BLOCK_TOKENS, remaining)
        output.extend(
            token_for_offset(node, depth, offset, token_map)
            for offset in range(visible)
        )
        remaining -= visible
    if remaining != 0 or len(output) != record.input_length:
        raise AssertionError(
            f"input generation mismatch for request {record.index}: "
            f"remaining={remaining} generated={len(output)}"
        )
    return output


def request_id(index: int) -> str:
    # Deliberately group-independent so A/B/C/D/E request bodies are byte-identical.
    return f"mc-conversation-{index:05d}"


def build_payload_bytes(
    record: TraceRecord,
    token_map: TrieTokenMap,
    api_kind: str = "sglang",
    expected_model: str | None = None,
) -> bytes:
    input_ids = build_input_ids(record, token_map)
    if api_kind in {"sglang", "vllm_adapter"}:
        payload = {
            "rid": request_id(record.index),
            "input_ids": input_ids,
            "sampling_params": {
                "temperature": 0.0,
                "max_new_tokens": record.output_length,
                "ignore_eos": True,
            },
            "stream": True,
            "return_logprob": False,
            "log_metrics": True,
        }
    elif api_kind == "openai":
        if not expected_model:
            raise ValidationError("OpenAI payload requires expected_model")
        payload = {
            "model": expected_model,
            "prompt": input_ids,
            "request_id": request_id(record.index),
            "add_special_tokens": False,
            "temperature": 0.0,
            "max_tokens": record.output_length,
            "ignore_eos": True,
            "stream": True,
            "stream_options": {
                "include_usage": True,
                "continuous_usage_stats": True,
            },
            "return_token_ids": True,
        }
    else:
        raise ValidationError(f"unsupported api_kind: {api_kind}")
    return canonical_json_bytes(payload)


def selected_trace_sha256(records: Sequence[ScheduledRecord]) -> str:
    digest = hashlib.sha256()
    for item in records:
        digest.update(canonical_json_bytes(item.record.canonical()))
        digest.update(b"\n")
    return digest.hexdigest()


def select_records(trace: TraceData, mode: str) -> tuple[ScheduledRecord, ...]:
    if mode == "formal":
        return tuple(
            ScheduledRecord(record=item, schedule_timestamp_ms=item.timestamp_ms)
            for item in trace.records
        )
    if mode == "smoke":
        indices = list(range(31)) + [trace.longest_index]
        first_schedule = trace.records[indices[0]].timestamp_ms
        return tuple(
            ScheduledRecord(
                record=trace.records[index],
                schedule_timestamp_ms=first_schedule + ordinal * SMOKE_INTERVAL_MS,
            )
            for ordinal, index in enumerate(indices)
        )
    raise ValidationError(f"unsupported replay mode: {mode}")


def percentile(values: Sequence[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


async def iter_sse_json(content: Any) -> AsyncIterator[dict[str, Any]]:
    data_lines: list[str] = []
    buffer = ""

    def decode_event() -> dict[str, Any] | None:
        if not data_lines:
            return None
        payload = "\n".join(data_lines).strip()
        data_lines.clear()
        if not payload or payload == "[DONE]":
            return None
        value = json.loads(payload)
        if not isinstance(value, dict):
            raise ValidationError("SSE data must decode to a JSON object")
        return value

    def consume_line(line: str) -> dict[str, Any] | None:
        line = line.rstrip("\r")
        if not line:
            return decode_event()
        if line.startswith(":"):
            return None
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
        elif line.startswith("{"):
            # Defensive fallback for JSON-lines streaming proxies.
            data_lines.append(line)
        return None

    async for raw_chunk in content:
        buffer += raw_chunk.decode("utf-8")
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            event = consume_line(line)
            if event is not None:
                yield event

    if buffer:
        event = consume_line(buffer)
        if event is not None:
            yield event
    event = decode_event()
    if event is not None:
        yield event


class JsonlWriter:
    def __init__(self, path: Path) -> None:
        self._handle = path.open("x", encoding="utf-8", buffering=1)
        self._lock = asyncio.Lock()

    async def write(self, value: dict[str, Any]) -> None:
        line = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        async with self._lock:
            self._handle.write(line + "\n")

    def close(self) -> None:
        self._handle.flush()
        os.fsync(self._handle.fileno())
        self._handle.close()


def load_capacity_manifest(path: Path, group: str, formal: bool) -> dict[str, Any]:
    raw_bytes = path.read_bytes()
    value = json.loads(raw_bytes)
    if not isinstance(value, dict):
        raise ValidationError("capacity manifest must be a JSON object")
    if value.get("group") != group:
        raise ValidationError(
            f"capacity group mismatch: {value.get('group')} != {group}"
        )
    if formal and value.get("status") != "final_measured":
        raise ValidationError("formal replay requires status=final_measured")
    if group == "F":
        if formal and value.get("schema") != "fluxon_dram_capacity_v1":
            raise ValidationError("formal group F replay requires Fluxon DRAM capacity v1")
        if value.get("ssd_enabled") is not False:
            raise ValidationError("group F requires SSD to be disabled")
        local = value.get("local")
        remote = value.get("remote")
        if not isinstance(local, dict) or not isinstance(remote, dict):
            raise ValidationError("group F capacity requires local and remote objects")
        if local.get("physical_dram_bytes") != LOCAL_TOTAL_BYTES:
            raise ValidationError("group F local physical DRAM is not exactly 256 GiB")
        if local.get("mmap_bytes") != LOCAL_TOTAL_BYTES:
            raise ValidationError("group F local mmap is not exactly 256 GiB")
        if local.get("configured_payload_bytes") != 247_390_116_249:
            raise ValidationError("group F local Moka payload boundary mismatch")
        if local.get("hot_capacity_ratio") != 0.90:
            raise ValidationError("group F local hot-capacity ratio is not 0.90")
        rdma_profile = value.get("rdma_profile", "legacy_four_rail")
        if rdma_profile == "legacy_four_rail":
            expected_local_hcas = FLUXON_F_FOUR_RAIL_HCAS
        elif rdma_profile == "pplx_common_two_rail":
            expected_local_hcas = FLUXON_F_COMMON_TWO_RAIL_HCAS
        else:
            raise ValidationError("group F RDMA profile is unsupported")
        if local.get("rdma_hcas") != expected_local_hcas:
            raise ValidationError("group F local HCA list/profile mismatch")
        local_observed = local.get("observed_capacity_bytes")
        if not isinstance(local_observed, list) or 247_390_116_249 not in local_observed:
            raise ValidationError("group F local owner did not report its Moka boundary")
        if remote.get("physical_dram_bytes") != REMOTE_SEGMENT_BYTES:
            raise ValidationError("group F remote physical DRAM is not exactly 256 GiB")
        if remote.get("mmap_bytes") != REMOTE_SEGMENT_BYTES:
            raise ValidationError("group F remote mmap is not exactly 256 GiB")
        if remote.get("rdma_hcas") != ["mlx5_0", "mlx5_1"]:
            raise ValidationError("group F remote HCA list mismatch")
        remote_observed = remote.get("observed_capacity_bytes")
        if not isinstance(remote_observed, list) or any(
            isinstance(item, bool) or not isinstance(item, int) or item <= 0
            for item in remote_observed
        ):
            raise ValidationError("group F remote observed capacities are invalid")
        clients = value.get("external_clients")
        if (
            not isinstance(clients, list)
            or len(clients) != 2
            or len(set(clients)) != 2
            or any(not isinstance(item, str) or not item for item in clients)
        ):
            raise ValidationError("group F requires two unique external-client identities")
        evidence = value.get("evidence")
        if not isinstance(evidence, dict) or not evidence:
            raise ValidationError("group F capacity evidence is missing")
        value["manifest_sha256"] = sha256_bytes(raw_bytes)
        value["manifest_path"] = str(path.resolve())
        return value
    if group == "E":
        if formal and value.get("schema") != "lmcache_mooncake_capacity_v2":
            raise ValidationError("formal group E replay requires LMCache capacity v2")
        configured = value.get("lmcache_rank_configured_bytes")
        usable = value.get("lmcache_rank_usable_bytes")
        slack = value.get("lmcache_rank_alignment_slack_bytes")
        local_mooncake = value.get("mooncake_local_rank_segment_bytes")
        local_mooncake_buffers = value.get("mooncake_local_rank_buffer_bytes")
        expected_configured = [68_702_698_496] * 4
        expected_usable = [68_664_950_784] * 4
        expected_slack = [37_747_712] * 4
        if configured != expected_configured:
            raise ValidationError(
                f"group E LMCache configured rank bytes mismatch: {configured}"
            )
        if usable != expected_usable or slack != expected_slack:
            raise ValidationError("group E LMCache usable bytes/alignment slack mismatch")
        if local_mooncake != [16_777_216] * 4:
            raise ValidationError(
                "group E requires one allocator-minimum 16-MiB Mooncake segment per rank"
            )
        if value.get("mooncake_local_segment_bytes") != 67_108_864:
            raise ValidationError("group E Mooncake protocol segment total is not 64 MiB")
        if local_mooncake_buffers != [1_024, 1_024, 1_024, 1_024]:
            raise ValidationError(
                "group E requires one minimum 1024-byte Mooncake local buffer per rank"
            )
        if value.get("mooncake_local_buffer_bytes") != 4_096:
            raise ValidationError("group E Mooncake local buffer total is not 4096 B")
        if value.get("mooncake_local_kv_usable_bytes") != 0:
            raise ValidationError("group E protocol-only Mooncake segments must not store KV chunks")
        if (
            sum(configured)
            + sum(local_mooncake)
            + sum(local_mooncake_buffers)
            != LOCAL_TOTAL_BYTES
        ):
            raise ValidationError(
                "group E configured LMCache plus Mooncake bytes do not equal 256 GiB"
            )
        if any(u + s != c for u, s, c in zip(usable, slack, configured, strict=True)):
            raise ValidationError("group E per-rank usable + slack does not equal configured")
        if value.get("lmcache_chunk_tokens") != 512:
            raise ValidationError("group E requires 512-token LMCache chunks")
        if value.get("lmcache_chunk_bytes_per_rank") != 37_748_736:
            raise ValidationError("group E LMCache chunk geometry mismatch")
        if any(item >= 37_748_736 for item in local_mooncake):
            raise ValidationError("group E local Mooncake segment can hold a KV chunk")
        remote_segment = value.get("mooncake_remote_segment_bytes")
        if remote_segment != REMOTE_SEGMENT_BYTES:
            raise ValidationError("remote Mooncake segment is not exactly 256 GiB")
        if value.get("local_total_bytes", LOCAL_TOTAL_BYTES) != LOCAL_TOTAL_BYTES:
            raise ValidationError("group E local total is not exactly 256 GiB")
        value["manifest_sha256"] = sha256_bytes(raw_bytes)
        value["manifest_path"] = str(path.resolve())
        return value
    if formal and value.get("schema") != "mooncake_local_dram_capacity_v2":
        raise ValidationError("formal SGLang TP2x2 replay requires capacity schema v2")
    rank_bytes = value.get("hicache_rank_bytes")
    if not isinstance(rank_bytes, list) or len(rank_bytes) != 4:
        raise ValidationError("capacity manifest requires four hicache_rank_bytes")
    if any(isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in rank_bytes):
        raise ValidationError("hicache_rank_bytes must be positive integers")
    local_segment = value.get("mooncake_local_segment_bytes")
    instance_segments = value.get("mooncake_local_instance_segment_bytes")
    remote_segment = value.get("mooncake_remote_segment_bytes")
    if (
        isinstance(local_segment, bool)
        or not isinstance(local_segment, int)
        or local_segment < 0
    ):
        raise ValidationError("mooncake_local_segment_bytes must be a non-negative integer")
    if (
        not isinstance(instance_segments, list)
        or len(instance_segments) != 2
        or any(
            isinstance(item, bool) or not isinstance(item, int) or item < 0
            for item in instance_segments
        )
    ):
        raise ValidationError(
            "capacity manifest requires two non-negative local instance segments"
        )
    if instance_segments[0] != instance_segments[1]:
        raise ValidationError("the two TP2 local instance segments must be equal")
    if sum(instance_segments) != local_segment:
        raise ValidationError("local instance segments do not match local segment total")
    alignment_slack = value.get("page_alignment_slack_bytes", 0)
    if (
        isinstance(alignment_slack, bool)
        or not isinstance(alignment_slack, int)
        or alignment_slack < 0
    ):
        raise ValidationError("page_alignment_slack_bytes must be a non-negative integer")
    if group == "D":
        if instance_segments != [0, 0] or local_segment != 0:
            raise ValidationError("group D requires zero local Mooncake segments")
        if alignment_slack != 10_485_760:
            raise ValidationError("group D requires the measured 10 MiB page-alignment slack")
    elif any(item == 0 for item in instance_segments) or alignment_slack != 0:
        raise ValidationError(
            f"group {group} requires positive local Mooncake segments and zero alignment slack"
        )
    if isinstance(remote_segment, bool) or not isinstance(remote_segment, int):
        raise ValidationError("mooncake_remote_segment_bytes must be an integer")
    local_payload = sum(rank_bytes) + local_segment
    if value.get("local_payload_bytes", local_payload) != local_payload:
        raise ValidationError("local_payload_bytes does not match HiCache + Mooncake bytes")
    if local_payload + alignment_slack != LOCAL_TOTAL_BYTES:
        raise ValidationError(
            "local HiCache + Mooncake payload + alignment slack do not equal 256 GiB"
        )
    if value.get("local_total_bytes", LOCAL_TOTAL_BYTES) != LOCAL_TOTAL_BYTES:
        raise ValidationError("local_total_bytes is not exactly 256 GiB")
    if remote_segment != REMOTE_SEGMENT_BYTES:
        raise ValidationError("remote Mooncake segment is not exactly 256 GiB")
    value["manifest_sha256"] = sha256_bytes(raw_bytes)
    value["manifest_path"] = str(path.resolve())
    return value


async def fetch_json_or_text(session: Any, url: str) -> dict[str, Any]:
    try:
        async with session.get(url) as response:
            text = await response.text()
            try:
                body: Any = json.loads(text) if text else None
            except json.JSONDecodeError:
                body = text[:16_384]
            return {"url": url, "status": response.status, "body": body}
    except Exception as exc:  # recorded and checked by caller
        return {"url": url, "status": None, "error": f"{type(exc).__name__}: {exc}"}


async def endpoint_preflight(
    session: Any, base_url: str, expected_model: str, formal: bool
) -> dict[str, Any]:
    checks = {}
    for endpoint in ("health", "model_info", "get_server_info", "v1/models"):
        checks[endpoint] = await fetch_json_or_text(
            session, f"{base_url.rstrip('/')}/{endpoint}"
        )
    if checks["health"].get("status") != 200:
        raise ValidationError(f"health preflight failed: {checks['health']}")
    if formal:
        model_check = checks["model_info"]
        if model_check.get("status") == 200:
            if not isinstance(model_check.get("body"), dict):
                raise ValidationError(f"model_info preflight failed: {model_check}")
            actual_model = model_check["body"].get("model_path")
            if actual_model != expected_model:
                raise ValidationError(
                    f"model mismatch: expected={expected_model!r} actual={actual_model!r}"
                )
            checks["model_identity"] = {
                "source": "model_info",
                "expected_model": expected_model,
                "actual_models": [actual_model],
            }
        elif model_check.get("status") in (404, 405):
            models_check = checks["v1/models"]
            body = models_check.get("body")
            if models_check.get("status") != 200 or not isinstance(body, dict):
                raise ValidationError(
                    f"router model identity preflight failed: {models_check}"
                )
            data = body.get("data")
            if not isinstance(data, list):
                raise ValidationError(f"invalid /v1/models body: {body}")
            actual_models = [
                item.get("id") for item in data if isinstance(item, dict)
            ]
            if expected_model not in actual_models:
                raise ValidationError(
                    f"router model mismatch: expected={expected_model!r} "
                    f"actual={actual_models!r}"
                )
            checks["model_identity"] = {
                "source": "v1/models",
                "expected_model": expected_model,
                "actual_models": actual_models,
            }
        else:
            raise ValidationError(f"model_info preflight failed: {model_check}")
    return checks


async def send_one(
    *,
    session: Any,
    generate_url: str,
    scheduled: ScheduledRecord,
    token_map: TrieTokenMap,
    run_start: float,
    scheduled_monotonic: float,
    executor: ThreadPoolExecutor,
    writer: JsonlWriter,
    api_kind: str,
    expected_model: str,
) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    record = scheduled.record
    prepare_started = loop.time()
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "request_index": record.index,
        "rid": request_id(record.index),
        "trace_timestamp_ms": record.timestamp_ms,
        "schedule_timestamp_ms": scheduled.schedule_timestamp_ms,
        "scheduled_offset_s": scheduled_monotonic - run_start,
        "input_length": record.input_length,
        "output_length_expected": record.output_length,
        "success": False,
        "http_status": None,
        "completion_tokens": 0,
        "ttft_s": None,
        "e2e_s": None,
        "dispatch_lag_s": None,
        "finish_reason": None,
        "cached_tokens": None,
        "cached_tokens_details": None,
        "api_kind": api_kind,
        "usage_prompt_tokens": None,
        "usage_completion_tokens": None,
        "chunk_events": [],
        "error": "",
    }
    compact: dict[str, Any] = {
        "request_index": record.index,
        "input_length": record.input_length,
        "output_length_expected": record.output_length,
        "success": False,
        "ttft_s": None,
        "e2e_s": None,
        "dispatch_lag_s": None,
        "finished_offset_s": None,
    }

    try:
        body = await loop.run_in_executor(
            executor,
            build_payload_bytes,
            record,
            token_map,
            api_kind,
            expected_model,
        )
        payload_ready = loop.time()
        result["payload_prepare_s"] = payload_ready - prepare_started
        result["payload_bytes"] = len(body)
        result["payload_sha256"] = sha256_bytes(body)
        result["payload_ready_offset_s"] = payload_ready - run_start

        delay = scheduled_monotonic - loop.time()
        if delay > 0:
            await asyncio.sleep(delay)
        send_started = loop.time()
        dispatch_lag = send_started - scheduled_monotonic
        result["send_offset_s"] = send_started - run_start
        result["dispatch_lag_s"] = dispatch_lag
        compact["dispatch_lag_s"] = dispatch_lag

        last_completion = 0
        last_meta: dict[str, Any] = {}
        headers = {"Content-Type": "application/json"}
        async with session.post(generate_url, data=body, headers=headers) as response:
            result["http_status"] = response.status
            if response.status != 200:
                result["error"] = (await response.text())[:16_384]
            else:
                async for event in iter_sse_json(response.content):
                    now = loop.time()
                    if api_kind in {"sglang", "vllm_adapter"}:
                        meta = event.get("meta_info") or {}
                        if isinstance(meta, dict):
                            last_meta = meta
                        completion = meta.get("completion_tokens", last_completion)
                        if isinstance(completion, int) and completion > last_completion:
                            elapsed = now - send_started
                            result["chunk_events"].append([completion, elapsed])
                            if result["ttft_s"] is None:
                                result["ttft_s"] = elapsed
                            last_completion = completion
                        if isinstance(meta, dict):
                            if "cached_tokens" in meta:
                                result["cached_tokens"] = meta.get("cached_tokens")
                            if meta.get("cached_tokens_details") is not None:
                                result["cached_tokens_details"] = meta.get(
                                    "cached_tokens_details"
                                )
                            if meta.get("finish_reason") is not None:
                                result["finish_reason"] = meta.get("finish_reason")
                            if api_kind == "vllm_adapter":
                                prompt_tokens = meta.get("adapter_usage_prompt_tokens")
                                completion_tokens = meta.get(
                                    "adapter_usage_completion_tokens"
                                )
                                if isinstance(prompt_tokens, int):
                                    result["usage_prompt_tokens"] = prompt_tokens
                                if isinstance(completion_tokens, int):
                                    result["usage_completion_tokens"] = completion_tokens
                                result["adapter_upstream_model"] = meta.get(
                                    "adapter_upstream_model"
                                )
                                result["adapter_upstream_request_id"] = meta.get(
                                    "adapter_upstream_request_id"
                                )
                    else:
                        if event.get("error") is not None:
                            raise ValidationError(f"vLLM streaming error: {event['error']}")
                        event_id = event.get("id")
                        if event_id is not None and event_id != request_id(record.index):
                            raise ValidationError(
                                f"vLLM request id mismatch: {event_id!r}"
                            )
                        choices = event.get("choices", [])
                        if not isinstance(choices, list):
                            raise ValidationError("vLLM choices must be a list")
                        for choice in choices:
                            if not isinstance(choice, dict):
                                raise ValidationError("vLLM choice must be an object")
                            token_ids = choice.get("token_ids") or []
                            if not isinstance(token_ids, list) or any(
                                isinstance(token, bool) or not isinstance(token, int)
                                for token in token_ids
                            ):
                                raise ValidationError("vLLM token_ids must be integers")
                            if token_ids:
                                last_completion += len(token_ids)
                                elapsed = now - send_started
                                result["chunk_events"].append(
                                    [last_completion, elapsed]
                                )
                                if result["ttft_s"] is None:
                                    result["ttft_s"] = elapsed
                            if choice.get("finish_reason") is not None:
                                result["finish_reason"] = choice.get("finish_reason")
                        usage = event.get("usage")
                        if usage is not None:
                            if not isinstance(usage, dict):
                                raise ValidationError("vLLM usage must be an object")
                            prompt_tokens = usage.get("prompt_tokens")
                            completion_tokens = usage.get("completion_tokens")
                            if isinstance(prompt_tokens, int):
                                result["usage_prompt_tokens"] = prompt_tokens
                            if isinstance(completion_tokens, int):
                                result["usage_completion_tokens"] = completion_tokens
                            details = usage.get("prompt_tokens_details")
                            if isinstance(details, dict):
                                result["cached_tokens_details"] = details
                                if isinstance(details.get("cached_tokens"), int):
                                    result["cached_tokens"] = details["cached_tokens"]

                result["completion_tokens"] = last_completion
                result["final_meta_info"] = last_meta
                adapter_error = last_meta.get("adapter_error")
                if api_kind == "vllm_adapter" and adapter_error:
                    result["error"] = f"adapter error: {adapter_error}"
                elif (
                    api_kind in {"openai", "vllm_adapter"}
                    and result["usage_prompt_tokens"] != record.input_length
                ):
                    result["error"] = (
                        f"prompt token mismatch: expected={record.input_length} "
                        f"actual={result['usage_prompt_tokens']}"
                    )
                elif (
                    api_kind in {"openai", "vllm_adapter"}
                    and result["usage_completion_tokens"] != last_completion
                ):
                    result["error"] = (
                        "stream/usage completion mismatch: "
                        f"stream={last_completion} usage={result['usage_completion_tokens']}"
                    )
                elif (
                    api_kind == "vllm_adapter"
                    and result.get("adapter_upstream_model") != expected_model
                ):
                    result["error"] = (
                        "adapter upstream model mismatch: "
                        f"expected={expected_model!r} "
                        f"actual={result.get('adapter_upstream_model')!r}"
                    )
                elif (
                    api_kind == "vllm_adapter"
                    and result.get("adapter_upstream_request_id")
                    != f"cmpl-{request_id(record.index)}"
                ):
                    result["error"] = (
                        "adapter upstream request id mismatch: "
                        f"expected={'cmpl-' + request_id(record.index)!r} "
                        f"actual={result.get('adapter_upstream_request_id')!r}"
                    )
                elif last_completion != record.output_length:
                    result["error"] = (
                        f"completion token mismatch: expected={record.output_length} "
                        f"actual={last_completion}"
                    )
                elif result["ttft_s"] is None:
                    result["error"] = "no output-token event observed"
                else:
                    result["success"] = True
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        finished = loop.time()
        send_offset = result.get("send_offset_s")
        if isinstance(send_offset, (int, float)):
            result["e2e_s"] = finished - (run_start + send_offset)
        result["finished_offset_s"] = finished - run_start
        compact.update(
            success=result["success"],
            ttft_s=result["ttft_s"],
            e2e_s=result["e2e_s"],
            finished_offset_s=result["finished_offset_s"],
        )
        await writer.write(result)
    return compact


def summarize_results(
    compact_results: Sequence[dict[str, Any]],
    selected: Sequence[ScheduledRecord],
    wall_s: float,
    *,
    load_profile: str,
    time_scale: float,
    arrival_rate_multiplier: float,
) -> dict[str, Any]:
    successes = [item for item in compact_results if item["success"]]
    ttfts = [float(item["ttft_s"]) for item in successes]
    e2es = [float(item["e2e_s"]) for item in successes]
    dispatch_lags = [float(item["dispatch_lag_s"]) for item in compact_results]
    successful_input = sum(int(item["input_length"]) for item in successes)
    successful_output = sum(
        int(item["output_length_expected"]) for item in successes
    )
    source_schedule_span_s = (
        selected[-1].schedule_timestamp_ms - selected[0].schedule_timestamp_ms
    ) / 1000.0
    schedule_span_s = source_schedule_span_s * time_scale
    return {
        "schema": SCHEMA,
        "completed_at_utc": utc_now(),
        "load_profile": load_profile,
        "time_scale": time_scale,
        "arrival_rate_multiplier": arrival_rate_multiplier,
        "requests_expected": len(selected),
        "requests_success": len(successes),
        "requests_error": len(selected) - len(successes),
        "wall_s": wall_s,
        "source_schedule_span_s": source_schedule_span_s,
        "schedule_span_s": schedule_span_s,
        "offered_qps": len(selected) / schedule_span_s if schedule_span_s > 0 else None,
        "achieved_qps": len(successes) / wall_s if wall_s > 0 else None,
        "successful_input_tokens": successful_input,
        "successful_output_tokens": successful_output,
        "prompt_tokens_per_s": successful_input / wall_s if wall_s > 0 else None,
        "output_tokens_per_s": successful_output / wall_s if wall_s > 0 else None,
        "ttft_s": {
            "mean": statistics.fmean(ttfts) if ttfts else None,
            "p50": percentile(ttfts, 0.50),
            "p90": percentile(ttfts, 0.90),
            "p99": percentile(ttfts, 0.99),
        },
        "e2e_s": {
            "mean": statistics.fmean(e2es) if e2es else None,
            "p50": percentile(e2es, 0.50),
            "p90": percentile(e2es, 0.90),
            "p99": percentile(e2es, 0.99),
        },
        "dispatch_lag_s": {
            "mean": statistics.fmean(dispatch_lags) if dispatch_lags else None,
            "p50": percentile(dispatch_lags, 0.50),
            "p90": percentile(dispatch_lags, 0.90),
            "p99": percentile(dispatch_lags, 0.99),
            "max": max(dispatch_lags) if dispatch_lags else None,
        },
    }


def trace_descriptor(trace: TraceData, token_map: TrieTokenMap) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "trace_path": trace.path,
        "trace_sha256": trace.sha256,
        "requests": len(trace.records),
        "first_timestamp_ms": trace.first_timestamp_ms,
        "last_timestamp_ms": trace.last_timestamp_ms,
        "window_s": (trace.last_timestamp_ms - trace.first_timestamp_ms) / 1000.0,
        "input_tokens": trace.input_tokens,
        "output_tokens": trace.output_tokens,
        "max_context": trace.max_context,
        "longest_index": trace.longest_index,
        "block_tokens": BLOCK_TOKENS,
        "token_base": TOKEN_BASE,
        "token_max_exclusive": TOKEN_MAX_EXCLUSIVE,
        "trie_nodes": token_map.node_count,
        "trie_parents": token_map.parent_count,
        "max_fanout": token_map.max_fanout,
        "mapping": "sibling-unique-first-token + splitmix64(depth,node,offset)",
    }


def load_profile_descriptor(trace: TraceData, load_profile: str) -> dict[str, Any]:
    profile = FORMAL_LOAD_PROFILES.get(load_profile)
    if profile is None:
        raise ValidationError(f"unsupported load profile: {load_profile}")
    source_schedule_span_s = (
        trace.last_timestamp_ms - trace.first_timestamp_ms
    ) / 1000.0
    time_scale = float(profile["time_scale"])
    schedule_span_s = source_schedule_span_s * time_scale
    return {
        "name": load_profile,
        "arrival_rate_multiplier": float(profile["arrival_rate_multiplier"]),
        "time_scale": time_scale,
        "requests": len(trace.records),
        "source_schedule_span_s": source_schedule_span_s,
        "schedule_span_s": schedule_span_s,
        "offered_qps": len(trace.records) / schedule_span_s,
        "offered_prompt_tokens_per_s": trace.input_tokens / schedule_span_s,
        "offered_output_tokens_per_s": trace.output_tokens / schedule_span_s,
    }


async def dispatch_selected_records(
    *,
    selected: Sequence[ScheduledRecord],
    mode: str,
    time_scale: float,
    prepare_lead_s: float,
    run_start: float,
    session: Any,
    generate_url: str,
    token_map: TrieTokenMap,
    executor: ThreadPoolExecutor,
    writer: JsonlWriter,
    api_kind: str,
    expected_model: str,
) -> list[dict[str, Any]]:
    """Dispatch formal requests open-loop and smoke requests strictly serially."""
    loop = asyncio.get_running_loop()
    first_schedule = selected[0].schedule_timestamp_ms
    tasks: list[asyncio.Task[dict[str, Any]]] = []
    serial_results: list[dict[str, Any]] = []

    for item in selected:
        scheduled_offset = (
            (item.schedule_timestamp_ms - first_schedule) / 1000.0 * time_scale
        )
        scheduled_monotonic = run_start + scheduled_offset
        prepare_at = scheduled_monotonic - prepare_lead_s
        delay = prepare_at - loop.time()
        if delay > 0:
            await asyncio.sleep(delay)
        request = send_one(
            session=session,
            generate_url=generate_url,
            scheduled=item,
            token_map=token_map,
            run_start=run_start,
            scheduled_monotonic=scheduled_monotonic,
            executor=executor,
            writer=writer,
            api_kind=api_kind,
            expected_model=expected_model,
        )
        if mode == "smoke":
            # Never expose the next request to the router until this response
            # has fully closed.  If it finishes early, the nominal 10-second
            # schedule is still honored; if it runs late, the next item starts
            # immediately afterward and records the dispatch lag.
            serial_results.append(await request)
        else:
            tasks.append(asyncio.create_task(request))

    if mode == "smoke":
        return serial_results
    return list(await asyncio.gather(*tasks))


async def replay(args: argparse.Namespace, trace: TraceData, token_map: TrieTokenMap) -> int:
    try:
        import aiohttp
    except ImportError as exc:
        raise ValidationError("aiohttp is required for replay mode") from exc

    formal = args.mode == "formal"
    selected = select_records(trace, args.mode)
    load_profile = FORMAL_LOAD_PROFILES.get(args.load_profile)
    if load_profile is None:
        raise ValidationError(f"unsupported load profile: {args.load_profile}")
    if args.time_scale != load_profile["time_scale"]:
        raise ValidationError(
            "load profile/time-scale mismatch: "
            f"profile={args.load_profile} expected={load_profile['time_scale']} "
            f"actual={args.time_scale}"
        )
    if formal:
        validate_official_trace(trace)
        if len(selected) != TRACE_REQUESTS:
            raise ValidationError("formal replay must select the complete trace")
        if not args.capacity_manifest:
            raise ValidationError("formal replay requires --capacity-manifest")
    elif args.load_profile != DEFAULT_LOAD_PROFILE:
        raise ValidationError(
            f"smoke replay requires --load-profile={DEFAULT_LOAD_PROFILE}"
        )
    if TOKEN_MAX_EXCLUSIVE > args.vocab_size:
        raise ValidationError(
            f"generated token id upper bound {TOKEN_MAX_EXCLUSIVE} exceeds "
            f"vocab size {args.vocab_size}"
        )

    capacity = None
    if args.capacity_manifest:
        capacity = load_capacity_manifest(
            Path(args.capacity_manifest), args.group, formal=formal
        )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    writer = JsonlWriter(output_dir / "requests.jsonl")
    script_path = Path(__file__).resolve()
    base_url = args.base_url.rstrip("/")
    generate_url = (
        f"{base_url}/v1/completions"
        if args.api_kind == "openai"
        else f"{base_url}/generate"
    )

    timeout = aiohttp.ClientTimeout(
        total=args.request_timeout_s,
        connect=60,
        sock_connect=60,
        sock_read=args.request_timeout_s,
    )
    connector = make_tcp_connector(aiohttp)
    compact_results: list[dict[str, Any]] = []
    executor = ThreadPoolExecutor(
        max_workers=args.prepare_workers, thread_name_prefix="trace-payload"
    )

    try:
        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            preflight = await endpoint_preflight(
                session, base_url, args.expected_model, formal=formal
            )
            loop = asyncio.get_running_loop()
            run_start = loop.time() + args.prepare_lead_s
            first_schedule = selected[0].schedule_timestamp_ms
            run_manifest = {
                "schema": SCHEMA,
                "created_at_utc": utc_now(),
                "run_id": args.run_id,
                "group": args.group,
                "mode": args.mode,
                "base_url": base_url,
                "generate_url": generate_url,
                "api_kind": args.api_kind,
                "expected_model": args.expected_model,
                "vocab_size": args.vocab_size,
                "load_profile": args.load_profile,
                "time_scale": args.time_scale,
                "arrival_rate_multiplier": args.arrival_rate_multiplier,
                "dispatch_mode": "open_loop" if formal else "strict_serial",
                "smoke_interval_s": None if formal else SMOKE_INTERVAL_MS / 1000.0,
                "prepare_lead_s": args.prepare_lead_s,
                "prepare_workers": args.prepare_workers,
                "request_timeout_s": args.request_timeout_s,
                "tcp_connector": dict(TCP_CONNECTOR_CONFIG),
                "client_hostname": socket.gethostname(),
                "client_pid": os.getpid(),
                "python": sys.version,
                "script_path": str(script_path),
                "script_sha256": sha256_file(script_path),
                "trace": trace_descriptor(trace, token_map),
                "selection": {
                    "count": len(selected),
                    "indices": (
                        "all" if formal else [item.record.index for item in selected]
                    ),
                    "selected_trace_sha256": selected_trace_sha256(selected),
                    "schedule_first_ms": first_schedule,
                    "schedule_last_ms": selected[-1].schedule_timestamp_ms,
                },
                "capacity": capacity,
                "endpoint_preflight": preflight,
            }
            (output_dir / "run_manifest.json").write_bytes(
                canonical_json_bytes(run_manifest) + b"\n"
            )

            compact_results = await dispatch_selected_records(
                selected=selected,
                mode=args.mode,
                time_scale=args.time_scale,
                prepare_lead_s=args.prepare_lead_s,
                run_start=run_start,
                session=session,
                generate_url=generate_url,
                token_map=token_map,
                executor=executor,
                writer=writer,
                api_kind=args.api_kind,
                expected_model=args.expected_model,
            )
            wall_s = max(
                (float(item["finished_offset_s"]) for item in compact_results),
                default=0.0,
            )
            summary = summarize_results(
                compact_results,
                selected,
                wall_s,
                load_profile=args.load_profile,
                time_scale=args.time_scale,
                arrival_rate_multiplier=args.arrival_rate_multiplier,
            )
            summary["run_id"] = args.run_id
            summary["group"] = args.group
            summary["mode"] = args.mode
            (output_dir / "summary.json").write_bytes(
                canonical_json_bytes(summary) + b"\n"
            )
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
        writer.close()

    return 0 if compact_results and all(item["success"] for item in compact_results) else 2


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--expected-trace-sha256", default=TRACE_SHA256)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser(
        "validate", help="validate trace and print its descriptor"
    )
    validate_parser.add_argument(
        "--load-profile",
        choices=tuple(FORMAL_LOAD_PROFILES),
        default=DEFAULT_LOAD_PROFILE,
    )

    replay_parser = subparsers.add_parser("replay", help="send an open-loop replay")
    replay_parser.add_argument("--mode", choices=("smoke", "formal"), required=True)
    replay_parser.add_argument(
        "--group", choices=("A", "B", "C", "D", "E", "F"), required=True
    )
    replay_parser.add_argument(
        "--api-kind",
        choices=("sglang", "openai", "vllm_adapter"),
        default="sglang",
    )
    replay_parser.add_argument("--base-url", required=True)
    replay_parser.add_argument("--expected-model", required=True)
    replay_parser.add_argument("--vocab-size", type=int, required=True)
    replay_parser.add_argument("--capacity-manifest")
    replay_parser.add_argument("--run-id", required=True)
    replay_parser.add_argument("--output-dir", required=True)
    replay_parser.add_argument(
        "--load-profile",
        choices=tuple(FORMAL_LOAD_PROFILES),
        default=DEFAULT_LOAD_PROFILE,
    )
    replay_parser.add_argument(
        "--time-scale",
        type=float,
        default=None,
        help=(
            "compatibility assertion only; the selected load profile owns the "
            "formal time scale"
        ),
    )
    replay_parser.add_argument("--prepare-lead-s", type=float, default=5.0)
    replay_parser.add_argument("--prepare-workers", type=int, default=8)
    replay_parser.add_argument("--request-timeout-s", type=float, default=21_600.0)
    args = parser.parse_args(argv)

    if args.command == "replay":
        expected_api_kind = "vllm_adapter" if args.group == "E" else "sglang"
        if args.api_kind != expected_api_kind:
            parser.error(
                f"group {args.group} requires --api-kind={expected_api_kind}"
            )
        profile = FORMAL_LOAD_PROFILES[args.load_profile]
        profile_time_scale = float(profile["time_scale"])
        if args.time_scale is not None and (
            not math.isfinite(args.time_scale)
            or args.time_scale != profile_time_scale
        ):
            parser.error(
                "--time-scale must exactly match --load-profile "
                f"{args.load_profile} ({profile_time_scale})"
            )
        args.time_scale = profile_time_scale
        args.arrival_rate_multiplier = float(profile["arrival_rate_multiplier"])
        if not math.isfinite(args.prepare_lead_s) or args.prepare_lead_s < 0:
            parser.error("--prepare-lead-s must be finite and non-negative")
        if args.prepare_workers <= 0:
            parser.error("--prepare-workers must be positive")
        if args.vocab_size <= 0:
            parser.error("--vocab-size must be positive")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        trace = load_trace(args.trace, args.expected_trace_sha256)
        validate_official_trace(trace)
        token_map = build_trie_token_map(trace.records)
        if args.command == "validate":
            descriptor = trace_descriptor(trace, token_map)
            descriptor["load_profile"] = load_profile_descriptor(
                trace, args.load_profile
            )
            print(json.dumps(descriptor, indent=2, sort_keys=True))
            return 0
        return asyncio.run(replay(args, trace, token_map))
    except (OSError, ValidationError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
