#!/usr/bin/env python3
"""Replay the frozen Interactive-derived S96xT24 workload in session-stream mode."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import math
import os
import re
import socket
import statistics
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Sequence


SCHEMA = "interactive_r34_shaped_s96t24_replay_v1"
PROFILE = "interactive-r34-shaped-s96t24-shared-system-v1"
# Derived profiles may reuse the frozen cohort ordering and the exact same
# tokenizer-generated shared prefix while changing only the number of active
# sessions.  Keep those identities explicit instead of implicitly coupling
# them to the derived workload name.
SELECTION_KEY_PROFILE = PROFILE
PREFIX_ASSET_PROFILE = PROFILE
TRACE_SHA256 = "3bdddbf607d7da977311f2e8c8abfeaf8e93d61fb22ba43ead0ff12f6d0b16e4"
BASE_REPLAYER_SHA256 = "98a797ad20f1b5b6cb078e87cf7e1e9a24773963b9d3ba3a8b67594d96d6153b"
PREFIX_ASSET_SCHEMA = "interactive_r34_shared_system_prefix_v1"
HEADER = "user_id time_stamp(seconds) query_length response_length round_index"
ANCHOR_TIMESTAMP_S = 10_020
SESSIONS = 96
TURNS = 24
CONCURRENCY = 24
OUTPUT_TOKENS = 8
SHARED_PREFIX_TOKENS = 4096
BLOCK_TOKENS = 512
PAGE_TOKENS = 64
TP2_PAGE_BYTES = 9_437_184
ACTIVE_CANDIDATES = 444
FULL_RECORDS = 263_810
FULL_FIRST_TIMESTAMP_S = 7_200
FULL_LAST_TIMESTAMP_S = 25_053
LENGTH_VARIATION_SCALE = Fraction(9, 2)
SELECTED_USERS_SHA256 = "5eae31fe06c34de4f9f300f803ae68bac5e4a870c4950dbe761ac41b69f6ff0a"
SELECTION_COORDINATES_SHA256 = "4573ce6699d3c03eb66fd04ae616c8d030092518e1133a7594bd33c4bb68d625"
SHAPED_RECORDS_SHA256 = "be5f1a6b7ba70cb374f9add43ae78fdd71d78d0179fd8f1a5f14a94c3ba5140b"
EXPECTED_UNIQUE_PAGES = 33_759
EXPECTED_UNIQUE_EXACT_TOKENS = 2_157_343
SHARED_NODE_BASE = 0x1000_0000_0000
PRIVATE_NODE_BASE = 0x2000_0000_0000
PRIVATE_NODE_SESSION_STRIDE = 1 << 16

# Exact per-turn prompt-token totals from the frozen r34 request stream.
R34_TURN_PROMPT_TOTALS = (
    1_734_204,
    1_769_418,
    1_804_601,
    1_839_841,
    1_875_114,
    1_910_393,
    1_945_571,
    1_980_728,
    2_015_911,
    2_051_069,
    2_086_359,
    2_121_710,
    2_157_152,
    2_192_618,
    2_228_055,
    2_263_407,
    2_298_777,
    2_334_222,
    2_369_614,
    2_404_993,
    2_440_387,
    2_475_758,
    2_511_123,
    2_546_463,
)


class ValidationError(ValueError):
    pass


@dataclass(frozen=True)
class RawRecord:
    source_index: int
    source_line: int
    user_id: int
    timestamp_s: int
    query_length: int
    response_length: int
    round_index: int
    input_length: int


@dataclass(frozen=True)
class ShapedRecord:
    index: int
    session_slot: int
    turn_slot: int
    user_id: int
    raw_round_index: int
    source_index: int
    source_line: int
    raw_timestamp_s: int
    raw_input_length: int
    input_length: int
    output_length: int
    timestamp_ms: int
    hash_ids: tuple[int, ...]

    def identity(self) -> dict[str, Any]:
        return {
            "session_slot": self.session_slot,
            "turn_slot": self.turn_slot,
            "user_id": self.user_id,
            "raw_round_index": self.raw_round_index,
            "source_index": self.source_index,
            "raw_timestamp_s": self.raw_timestamp_s,
            "raw_input_length": self.raw_input_length,
            "target_input_length": self.input_length,
            "output_length": self.output_length,
        }


@dataclass(frozen=True)
class ShapedTrace:
    path: str
    sha256: str
    selected_users: tuple[int, ...]
    selected_users_sha256: str
    selection_coordinates_sha256: str
    shaped_records_sha256: str
    records: tuple[ShapedRecord, ...]
    sessions: tuple[tuple[ShapedRecord, ...], ...]
    candidate_count: int
    prompt_tokens: int
    output_tokens: int
    min_input: int
    max_input: int
    unique_exact_tokens: int
    unique_pages: int
    unique_page_bytes: int


@dataclass(frozen=True)
class PrefixAsset:
    path: str
    file_sha256: str
    token_ids_sha256: str
    decoded_prefix_sha256: str
    tokenizer_files_sha256: dict[str, str]
    vocab_size: int
    token_ids: tuple[int, ...]


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


def load_base_replayer(path: Path, expected_sha256: str) -> Any:
    actual = sha256_file(path)
    if actual != expected_sha256:
        raise ValidationError(
            f"base replayer SHA256 mismatch: expected={expected_sha256} actual={actual}"
        )
    spec = importlib.util.spec_from_file_location("r34_shaped_base_replayer", path)
    if spec is None or spec.loader is None:
        raise ValidationError(f"cannot import base replayer: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _parse_nonnegative(raw: bytes, name: str, source_line: int) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValidationError(f"line {source_line}: {name} is not an integer") from exc
    if value < 0:
        raise ValidationError(f"line {source_line}: {name} must be non-negative")
    return value


def load_raw_records(path: Path, expected_sha256: str) -> dict[int, list[RawRecord]]:
    actual = sha256_file(path)
    if actual != expected_sha256:
        raise ValidationError(
            f"trace SHA256 mismatch: expected={expected_sha256} actual={actual}"
        )
    by_user: dict[int, list[RawRecord]] = defaultdict(list)
    history_tokens: dict[int, int] = {}
    next_round: dict[int, int] = {}
    previous_timestamp = -1
    records = 0
    first_timestamp = -1
    last_timestamp = -1
    with path.open("rb") as handle:
        header = handle.readline().rstrip(b"\r\n").decode("ascii", errors="strict")
        if header != HEADER:
            raise ValidationError(f"raw trace header mismatch: {header!r}")
        for source_line, raw_line in enumerate(handle, 2):
            fields = raw_line.split()
            if len(fields) != 5:
                raise ValidationError(f"line {source_line}: expected five fields")
            user_id = _parse_nonnegative(fields[0], "user_id", source_line)
            timestamp_s = _parse_nonnegative(fields[1], "timestamp", source_line)
            query_length = _parse_nonnegative(fields[2], "query_length", source_line)
            response_length = _parse_nonnegative(fields[3], "response_length", source_line)
            round_index = _parse_nonnegative(fields[4], "round_index", source_line)
            if query_length <= 0 or response_length <= 0:
                raise ValidationError(f"line {source_line}: token lengths must be positive")
            if timestamp_s < previous_timestamp:
                raise ValidationError(f"line {source_line}: timestamps are not monotonic")
            previous_timestamp = timestamp_s
            expected_round = next_round.get(user_id, 0)
            if round_index != expected_round:
                raise ValidationError(
                    f"line {source_line}: user {user_id} round={round_index}, expected={expected_round}"
                )
            next_round[user_id] = expected_round + 1
            input_length = history_tokens.get(user_id, 0) + query_length
            history_tokens[user_id] = input_length + response_length
            if records == 0:
                first_timestamp = timestamp_s
            last_timestamp = timestamp_s
            record = RawRecord(
                source_index=records,
                source_line=source_line,
                user_id=user_id,
                timestamp_s=timestamp_s,
                query_length=query_length,
                response_length=response_length,
                round_index=round_index,
                input_length=input_length,
            )
            by_user[user_id].append(record)
            records += 1
    actual_full = (records, first_timestamp, last_timestamp)
    expected_full = (FULL_RECORDS, FULL_FIRST_TIMESTAMP_S, FULL_LAST_TIMESTAMP_S)
    if actual_full != expected_full:
        raise ValidationError(f"full trace invariants differ: {actual_full} != {expected_full}")
    return by_user


def selection_key(user_id: int) -> bytes:
    material = (
        f"{TRACE_SHA256}\0{SELECTION_KEY_PROFILE}\0anchor={ANCHOR_TIMESTAMP_S}\0user={user_id}"
    ).encode("utf-8")
    return hashlib.sha256(material).digest()


def select_active_sessions(
    by_user: dict[int, list[RawRecord]],
) -> list[tuple[int, list[RawRecord]]]:
    candidates: list[tuple[int, list[RawRecord]]] = []
    for user_id, records in by_user.items():
        future = [item for item in records if item.timestamp_s >= ANCHOR_TIMESTAMP_S]
        if (
            records[0].timestamp_s <= ANCHOR_TIMESTAMP_S <= records[-1].timestamp_s
            and len(future) >= TURNS
        ):
            candidates.append((user_id, future[:TURNS]))
    if len(candidates) != ACTIVE_CANDIDATES:
        raise ValidationError(
            f"active candidate count differs: {len(candidates)} != {ACTIVE_CANDIDATES}"
        )
    selected = sorted(candidates, key=lambda item: (selection_key(item[0]), item[0]))[
        :SESSIONS
    ]
    users = [user_id for user_id, _ in selected]
    users_sha = sha256_bytes(canonical_json_bytes(users))
    if users_sha != SELECTED_USERS_SHA256:
        raise ValidationError(
            f"selected user identity differs: {users_sha} != {SELECTED_USERS_SHA256}"
        )
    coordinates_digest = hashlib.sha256()
    for session_slot, (user_id, records) in enumerate(selected):
        if len(records) != TURNS:
            raise AssertionError("selected session does not contain exactly 24 turns")
        for turn_slot, record in enumerate(records):
            coordinate = {
                "session_slot": session_slot,
                "turn_slot": turn_slot,
                "user_id": user_id,
                "raw_round_index": record.round_index,
                "source_index": record.source_index,
            }
            coordinates_digest.update(canonical_json_bytes(coordinate))
            coordinates_digest.update(b"\n")
    coordinate_sha = coordinates_digest.hexdigest()
    if coordinate_sha != SELECTION_COORDINATES_SHA256:
        raise ValidationError(
            "selection coordinates differ: "
            f"{coordinate_sha} != {SELECTION_COORDINATES_SHA256}"
        )
    return selected


def allocate_target_lengths(
    selected: Sequence[tuple[int, Sequence[RawRecord]]],
) -> list[list[int]]:
    if len(selected) != SESSIONS:
        raise ValidationError(f"expected {SESSIONS} selected sessions")
    lengths = [[0] * TURNS for _ in range(SESSIONS)]
    for turn_slot, target_total in enumerate(R34_TURN_PROMPT_TOTALS):
        raw_lengths = [records[turn_slot].input_length for _, records in selected]
        raw_total = sum(raw_lengths)
        ideals: list[tuple[int, int, Fraction]] = []
        for session_slot, raw_length in enumerate(raw_lengths):
            ideal = Fraction(target_total, SESSIONS) + LENGTH_VARIATION_SCALE * (
                Fraction(raw_length) - Fraction(raw_total, SESSIONS)
            )
            floor_value = ideal.numerator // ideal.denominator
            ideals.append((session_slot, floor_value, ideal - floor_value))
        remainder = target_total - sum(item[1] for item in ideals)
        if not 0 <= remainder < SESSIONS:
            raise AssertionError(f"invalid integer remainder for turn {turn_slot}: {remainder}")
        increment = {
            item[0]
            for item in sorted(ideals, key=lambda item: (-item[2], item[0]))[:remainder]
        }
        for session_slot, floor_value, _ in ideals:
            lengths[session_slot][turn_slot] = floor_value + int(
                session_slot in increment
            )
        if sum(row[turn_slot] for row in lengths) != target_total:
            raise AssertionError(f"turn {turn_slot} prompt total did not close")

    for session_slot, row in enumerate(lengths):
        if min(row) <= SHARED_PREFIX_TOKENS:
            raise ValidationError(
                f"session {session_slot} is shorter than the shared prefix"
            )
        if any(right <= left for left, right in zip(row, row[1:])):
            raise ValidationError(f"session {session_slot} target lengths are not increasing")
    return lengths


def build_hash_ids(session_slot: int, input_length: int) -> tuple[int, ...]:
    block_count = math.ceil(input_length / BLOCK_TOKENS)
    shared_blocks = SHARED_PREFIX_TOKENS // BLOCK_TOKENS
    if block_count <= shared_blocks:
        raise ValidationError("record does not extend beyond the shared prefix")
    shared = tuple(SHARED_NODE_BASE + depth for depth in range(shared_blocks))
    private = tuple(
        PRIVATE_NODE_BASE + session_slot * PRIVATE_NODE_SESSION_STRIDE + depth
        for depth in range(shared_blocks, block_count)
    )
    return shared + private


def build_shaped_trace(path: Path, expected_sha256: str = TRACE_SHA256) -> ShapedTrace:
    by_user = load_raw_records(path, expected_sha256)
    selected = select_active_sessions(by_user)
    target_lengths = allocate_target_lengths(selected)
    sessions: list[tuple[ShapedRecord, ...]] = []
    records: list[ShapedRecord] = []
    identity_digest = hashlib.sha256()
    for session_slot, (user_id, raw_records) in enumerate(selected):
        session_records: list[ShapedRecord] = []
        for turn_slot, raw in enumerate(raw_records):
            input_length = target_lengths[session_slot][turn_slot]
            record = ShapedRecord(
                index=session_slot * TURNS + turn_slot,
                session_slot=session_slot,
                turn_slot=turn_slot,
                user_id=user_id,
                raw_round_index=raw.round_index,
                source_index=raw.source_index,
                source_line=raw.source_line,
                raw_timestamp_s=raw.timestamp_s,
                raw_input_length=raw.input_length,
                input_length=input_length,
                output_length=OUTPUT_TOKENS,
                timestamp_ms=raw.timestamp_s * 1000,
                hash_ids=build_hash_ids(session_slot, input_length),
            )
            identity_digest.update(canonical_json_bytes(record.identity()))
            identity_digest.update(b"\n")
            session_records.append(record)
            records.append(record)
        sessions.append(tuple(session_records))
    shaped_sha = identity_digest.hexdigest()
    if shaped_sha != SHAPED_RECORDS_SHA256:
        raise ValidationError(
            f"shaped record identity differs: {shaped_sha} != {SHAPED_RECORDS_SHA256}"
        )

    final_lengths = [session[-1].input_length for session in sessions]
    unique_exact_tokens = SHARED_PREFIX_TOKENS + sum(
        length - SHARED_PREFIX_TOKENS for length in final_lengths
    )
    unique_pages = SHARED_PREFIX_TOKENS // PAGE_TOKENS + sum(
        math.ceil((length - SHARED_PREFIX_TOKENS) / PAGE_TOKENS)
        for length in final_lengths
    )
    if unique_exact_tokens != EXPECTED_UNIQUE_EXACT_TOKENS:
        raise ValidationError("unique exact-token WSS differs")
    if unique_pages != EXPECTED_UNIQUE_PAGES:
        raise ValidationError("page-rounded WSS differs")
    prompt_tokens = sum(item.input_length for item in records)
    if prompt_tokens != sum(R34_TURN_PROMPT_TOTALS):
        raise ValidationError("prompt total does not match frozen r34")
    return ShapedTrace(
        path=str(path.resolve()),
        sha256=expected_sha256,
        selected_users=tuple(user_id for user_id, _ in selected),
        selected_users_sha256=SELECTED_USERS_SHA256,
        selection_coordinates_sha256=SELECTION_COORDINATES_SHA256,
        shaped_records_sha256=shaped_sha,
        records=tuple(records),
        sessions=tuple(sessions),
        candidate_count=ACTIVE_CANDIDATES,
        prompt_tokens=prompt_tokens,
        output_tokens=len(records) * OUTPUT_TOKENS,
        min_input=min(item.input_length for item in records),
        max_input=max(item.input_length for item in records),
        unique_exact_tokens=unique_exact_tokens,
        unique_pages=unique_pages,
        unique_page_bytes=unique_pages * TP2_PAGE_BYTES,
    )


def load_prefix_asset(path: Path, expected_sha256: str, vocab_size: int) -> PrefixAsset:
    raw = path.read_bytes()
    actual = sha256_bytes(raw)
    if expected_sha256 and actual != expected_sha256:
        raise ValidationError(
            f"prefix asset SHA256 mismatch: expected={expected_sha256} actual={actual}"
        )
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get("schema") != PREFIX_ASSET_SCHEMA:
        raise ValidationError("invalid shared-prefix asset schema")
    if value.get("profile") != PREFIX_ASSET_PROFILE:
        raise ValidationError("shared-prefix profile mismatch")
    token_ids = value.get("token_ids")
    if (
        not isinstance(token_ids, list)
        or len(token_ids) != SHARED_PREFIX_TOKENS
        or any(isinstance(item, bool) or not isinstance(item, int) for item in token_ids)
    ):
        raise ValidationError("shared-prefix token ids are invalid")
    if any(item < 0 or item >= vocab_size for item in token_ids):
        raise ValidationError("shared-prefix token id exceeds runtime vocabulary")
    token_sha = sha256_bytes(canonical_json_bytes(token_ids))
    if token_sha != value.get("token_ids_sha256"):
        raise ValidationError("shared-prefix token digest mismatch")
    tokenizer_hashes = value.get("tokenizer_files_sha256")
    if not isinstance(tokenizer_hashes, dict) or not tokenizer_hashes:
        raise ValidationError("shared-prefix tokenizer identity is missing")
    return PrefixAsset(
        path=str(path.resolve()),
        file_sha256=actual,
        token_ids_sha256=token_sha,
        decoded_prefix_sha256=str(value.get("decoded_prefix_sha256", "")),
        tokenizer_files_sha256={str(k): str(v) for k, v in tokenizer_hashes.items()},
        vocab_size=int(value.get("vocab_size", 0)),
        token_ids=tuple(token_ids),
    )


def build_input_ids(
    record: ShapedRecord, token_map: Any, prefix: PrefixAsset, base: Any
) -> list[int]:
    output: list[int] = []
    remaining = record.input_length
    for depth, node in enumerate(record.hash_ids):
        visible = min(BLOCK_TOKENS, remaining)
        if depth * BLOCK_TOKENS < SHARED_PREFIX_TOKENS:
            start = depth * BLOCK_TOKENS
            output.extend(prefix.token_ids[start : start + visible])
        else:
            output.extend(
                base.token_for_offset(node, depth, offset, token_map)
                for offset in range(visible)
            )
        remaining -= visible
    if remaining != 0 or len(output) != record.input_length:
        raise AssertionError(
            f"input generation mismatch: record={record.index} remaining={remaining}"
        )
    return output


def request_id(record: ShapedRecord) -> str:
    return f"ir34-s{record.session_slot:03d}-t{record.turn_slot:02d}"


def build_payload_bytes(
    record: ShapedRecord, token_map: Any, prefix: PrefixAsset, base: Any
) -> bytes:
    payload = {
        "rid": request_id(record),
        "input_ids": build_input_ids(record, token_map, prefix, base),
        "sampling_params": {
            "temperature": 0.0,
            "max_new_tokens": record.output_length,
            "ignore_eos": True,
        },
        "stream": True,
        "return_logprob": False,
        "log_metrics": True,
    }
    return canonical_json_bytes(payload)


def trace_descriptor(trace: ShapedTrace, token_map: Any) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "profile": PROFILE,
        "raw_trace": {
            "path": trace.path,
            "sha256": trace.sha256,
            "anchor_timestamp_s": ANCHOR_TIMESTAMP_S,
            "active_definition": "first_ts <= anchor <= last_ts and at least 24 records with timestamp >= anchor",
            "active_candidates": trace.candidate_count,
        },
        "selection": {
            "sessions": SESSIONS,
            "turns": TURNS,
            "ranking_profile": SELECTION_KEY_PROFILE,
            "selected_users": list(trace.selected_users),
            "selected_users_sha256": trace.selected_users_sha256,
            "coordinates_sha256": trace.selection_coordinates_sha256,
            "shaped_records_sha256": trace.shaped_records_sha256,
        },
        "schedule": {
            "mode": "session_stream",
            "active_sessions": SESSIONS,
            "concurrency": CONCURRENCY,
            "think_time_s": 0,
            "max_runtime_s": 600,
        },
        "length_shape": {
            "variation_scale": "9/2",
            "r34_turn_prompt_totals": list(R34_TURN_PROMPT_TOTALS),
            "prompt_tokens": trace.prompt_tokens,
            "output_tokens": trace.output_tokens,
            "min_input": trace.min_input,
            "max_input": trace.max_input,
            "output_per_request": OUTPUT_TOKENS,
        },
        "prefix_layout": {
            "variant": "shared-system",
            "asset_profile": PREFIX_ASSET_PROFILE,
            "shared_prefix_tokens": SHARED_PREFIX_TOKENS,
            "shared_prefix_blocks": SHARED_PREFIX_TOKENS // BLOCK_TOKENS,
            "private_after_shared_prefix": True,
        },
        "wss_model": {
            "unique_exact_tokens": trace.unique_exact_tokens,
            "page_tokens": PAGE_TOKENS,
            "unique_pages": trace.unique_pages,
            "tp2_page_bytes": TP2_PAGE_BYTES,
            "unique_page_bytes": trace.unique_page_bytes,
            "unique_page_gib": trace.unique_page_bytes / 2**30,
        },
        "trie": {
            "nodes": token_map.node_count,
            "parents": token_map.parent_count,
            "max_fanout": token_map.max_fanout,
        },
    }


METRIC_RE = re.compile(r'^sglang:cached_tokens_total\{([^}]*)\}\s+([^\s]+)$')


def parse_cached_token_metrics(text: str) -> dict[str, float]:
    values: dict[str, float] = {}
    for line in text.splitlines():
        match = METRIC_RE.match(line.strip())
        if match is None:
            continue
        labels: dict[str, str] = {}
        for part in match.group(1).split(","):
            key, raw_value = part.split("=", 1)
            labels[key] = raw_value.strip('"')
        source = labels.get("cache_source")
        if source:
            values[source] = values.get(source, 0.0) + float(match.group(2))
    return values


async def fetch_text(session: Any, url: str) -> str:
    async with session.get(url) as response:
        body = await response.text()
        if response.status != 200:
            raise ValidationError(f"metrics GET failed: url={url} status={response.status}")
        return body


async def snapshot_metrics(
    session: Any, urls: Sequence[str], output_dir: Path, label: str
) -> dict[str, float]:
    total: dict[str, float] = {}
    for index, url in enumerate(urls):
        text = await fetch_text(session, url)
        (output_dir / f"{label}.instance{index}.prom").write_text(text, encoding="utf-8")
        for source, value in parse_cached_token_metrics(text).items():
            total[source] = total.get(source, 0.0) + value
    return total


def percentile(values: Sequence[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


async def send_record(
    *,
    session: Any,
    url: str,
    record: ShapedRecord,
    token_map: Any,
    prefix: PrefixAsset,
    base: Any,
    executor: ThreadPoolExecutor,
    writer: Any,
    run_start: float,
) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    result: dict[str, Any] = {
        "schema": SCHEMA,
        **record.identity(),
        "request_index": record.index,
        "rid": request_id(record),
        "success": False,
        "http_status": None,
        "completion_tokens": 0,
        "ttft_s": None,
        "e2e_s": None,
        "send_offset_s": None,
        "finished_offset_s": None,
        "cached_tokens": None,
        "cached_tokens_details": None,
        "error": "",
    }
    send_started: float | None = None
    try:
        body = await loop.run_in_executor(
            executor, build_payload_bytes, record, token_map, prefix, base
        )
        result["payload_bytes"] = len(body)
        result["payload_sha256"] = sha256_bytes(body)
        send_started = loop.time()
        result["send_offset_s"] = send_started - run_start
        last_completion = 0
        last_meta: dict[str, Any] = {}
        async with session.post(
            url, data=body, headers={"Content-Type": "application/json"}
        ) as response:
            result["http_status"] = response.status
            if response.status != 200:
                result["error"] = (await response.text())[:16_384]
            else:
                async for event in base.iter_sse_json(response.content):
                    now = loop.time()
                    meta = event.get("meta_info") or {}
                    if not isinstance(meta, dict):
                        continue
                    last_meta = meta
                    completion = meta.get("completion_tokens", last_completion)
                    if isinstance(completion, int) and completion > last_completion:
                        if result["ttft_s"] is None:
                            result["ttft_s"] = now - send_started
                        last_completion = completion
                    if "cached_tokens" in meta:
                        result["cached_tokens"] = meta.get("cached_tokens")
                    if meta.get("cached_tokens_details") is not None:
                        result["cached_tokens_details"] = meta.get(
                            "cached_tokens_details"
                        )
                result["completion_tokens"] = last_completion
                result["final_meta_info"] = last_meta
                if last_completion != record.output_length:
                    result["error"] = (
                        f"completion mismatch: {last_completion} != {record.output_length}"
                    )
                elif result["ttft_s"] is None:
                    result["error"] = "no output-token event observed"
                else:
                    result["success"] = True
    except asyncio.CancelledError:
        result["error"] = "cancelled by 600-second runtime boundary"
        raise
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        finished = loop.time()
        if send_started is not None:
            result["e2e_s"] = finished - send_started
        result["finished_offset_s"] = finished - run_start
        await writer.write(result)
    return result


def hit_summary(
    before: dict[str, float], after: dict[str, float], prompt_tokens: int
) -> dict[str, Any]:
    deltas = {
        source: after.get(source, 0.0) - before.get(source, 0.0)
        for source in set(before) | set(after)
    }
    if any(value < 0 for value in deltas.values()):
        raise ValidationError(f"cached-token counter decreased: {deltas}")
    l1 = deltas.get("device", 0.0)
    l2 = deltas.get("host", 0.0)
    l3 = deltas.get("storage_MooncakeStore", 0.0)
    total = l1 + l2 + l3
    return {
        "counter_before": before,
        "counter_after": after,
        "counter_delta": deltas,
        "prompt_tokens": prompt_tokens,
        "l1_device_tokens": l1,
        "l2_host_tokens": l2,
        "l3_mooncake_tokens": l3,
        "l1_share": l1 / prompt_tokens if prompt_tokens else None,
        "l2_share": l2 / prompt_tokens if prompt_tokens else None,
        "l3_share": l3 / prompt_tokens if prompt_tokens else None,
        "total_hit_tokens": total,
        "total_hit_share": total / prompt_tokens if prompt_tokens else None,
        "miss_tokens": prompt_tokens - total,
        "miss_share": (prompt_tokens - total) / prompt_tokens if prompt_tokens else None,
    }


async def replay(args: argparse.Namespace, trace: ShapedTrace, prefix: PrefixAsset, base: Any) -> int:
    try:
        import aiohttp
    except ImportError as exc:
        raise ValidationError("aiohttp is required for replay") from exc

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    capacity = base.load_capacity_manifest(
        Path(args.capacity_manifest), args.capacity_group, formal=True
    )
    token_map = base.build_trie_token_map(trace.records)
    writer = base.JsonlWriter(output_dir / "requests.jsonl")
    executor = ThreadPoolExecutor(
        max_workers=args.prepare_workers, thread_name_prefix="r34-shaped-payload"
    )
    timeout = aiohttp.ClientTimeout(
        total=args.request_timeout_s,
        connect=60,
        sock_connect=60,
        sock_read=args.request_timeout_s,
    )
    connector = base.make_tcp_connector(aiohttp)
    results: list[dict[str, Any]] = []
    results_lock = asyncio.Lock()
    task_errors: list[str] = []
    invalid_marker = Path(args.invalid_marker) if args.invalid_marker else None
    base_url = args.base_url.rstrip("/")
    script_path = Path(__file__).resolve()

    try:
        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as http:
            preflight = await base.endpoint_preflight(
                http, base_url, args.expected_model, formal=True
            )
            metrics_before = await snapshot_metrics(
                http, args.worker_metrics_url, output_dir, "before"
            )
            manifest = {
                "schema": SCHEMA,
                "profile": PROFILE,
                "created_at_utc": base.utc_now(),
                "run_id": args.run_id,
                "group": f"{args.capacity_group}-r34-shaped",
                "base_url": base_url,
                "generate_url": f"{base_url}/generate",
                "expected_model": args.expected_model,
                "vocab_size": args.vocab_size,
                "request_timeout_s": args.request_timeout_s,
                "max_runtime_s": args.max_runtime_s,
                "prepare_workers": args.prepare_workers,
                "worker_metrics_url": list(args.worker_metrics_url),
                "client_hostname": socket.gethostname(),
                "client_pid": os.getpid(),
                "python": sys.version,
                "script_path": str(script_path),
                "script_sha256": sha256_file(script_path),
                "base_replayer_path": str(Path(args.base_replayer).resolve()),
                "base_replayer_sha256": sha256_file(Path(args.base_replayer)),
                "trace": trace_descriptor(trace, token_map),
                "prefix_asset": {
                    "path": prefix.path,
                    "file_sha256": prefix.file_sha256,
                    "token_ids_sha256": prefix.token_ids_sha256,
                    "decoded_prefix_sha256": prefix.decoded_prefix_sha256,
                    "tokenizer_files_sha256": prefix.tokenizer_files_sha256,
                    "tokens": len(prefix.token_ids),
                },
                "capacity": capacity,
                "endpoint_preflight": preflight,
                "metrics_before": metrics_before,
                "invalid_marker": str(invalid_marker) if invalid_marker else None,
            }
            (output_dir / "run_manifest.json").write_bytes(
                canonical_json_bytes(manifest) + b"\n"
            )
            loop = asyncio.get_running_loop()
            run_start = loop.time()
            deadline = run_start + args.max_runtime_s
            semaphore = asyncio.Semaphore(CONCURRENCY)

            async def run_session(session_records: Sequence[ShapedRecord]) -> None:
                for record in session_records:
                    if invalid_marker is not None and invalid_marker.exists():
                        raise ValidationError(
                            f"interference marker appeared: {invalid_marker}"
                        )
                    remaining = deadline - loop.time()
                    if remaining <= 0:
                        return
                    async with semaphore:
                        remaining = deadline - loop.time()
                        if remaining <= 0:
                            return
                        result = await asyncio.wait_for(
                            send_record(
                                session=http,
                                url=f"{base_url}/generate",
                                record=record,
                                token_map=token_map,
                                prefix=prefix,
                                base=base,
                                executor=executor,
                                writer=writer,
                                run_start=run_start,
                            ),
                            timeout=min(args.request_timeout_s, remaining),
                        )
                    async with results_lock:
                        results.append(result)

            tasks = [
                asyncio.create_task(run_session(session_records))
                for session_records in trace.sessions
            ]
            done, pending = await asyncio.wait(
                tasks, timeout=args.max_runtime_s, return_when=asyncio.ALL_COMPLETED
            )
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                try:
                    task.result()
                except Exception as exc:
                    task_errors.append(f"{type(exc).__name__}: {exc}")
            wall_s = loop.time() - run_start
            metrics_after = await snapshot_metrics(
                http, args.worker_metrics_url, output_dir, "after"
            )
            successes = [item for item in results if item.get("success")]
            prompt_success = sum(int(item["target_input_length"]) for item in successes)
            ttfts = [float(item["ttft_s"]) for item in successes]
            e2es = [float(item["e2e_s"]) for item in successes]
            hit = hit_summary(metrics_before, metrics_after, prompt_success)
            summary = {
                "schema": SCHEMA,
                "profile": PROFILE,
                "completed_at_utc": base.utc_now(),
                "run_id": args.run_id,
                "requests_expected": len(trace.records),
                "requests_observed": len(results),
                "requests_success": len(successes),
                "requests_error": len(results) - len(successes),
                "requests_missing_at_runtime_boundary": len(trace.records) - len(results),
                "task_errors": task_errors,
                "wall_s": wall_s,
                "achieved_qps": len(successes) / wall_s if wall_s else None,
                "prompt_tokens_success": prompt_success,
                "output_tokens_success": sum(
                    int(item["completion_tokens"]) for item in successes
                ),
                "prompt_tokens_per_s": prompt_success / wall_s if wall_s else None,
                "ttft_mean_s": statistics.fmean(ttfts) if ttfts else None,
                "ttft_p50_s": percentile(ttfts, 0.50),
                "ttft_p90_s": percentile(ttfts, 0.90),
                "ttft_p99_s": percentile(ttfts, 0.99),
                "e2e_mean_s": statistics.fmean(e2es) if e2es else None,
                "e2e_p50_s": percentile(e2es, 0.50),
                "e2e_p90_s": percentile(e2es, 0.90),
                "e2e_p99_s": percentile(e2es, 0.99),
                "cache_hits": hit,
                "complete": (
                    len(successes) == len(trace.records)
                    and len(results) == len(trace.records)
                    and not task_errors
                    and not pending
                ),
            }
            (output_dir / "summary.json").write_bytes(
                canonical_json_bytes(summary) + b"\n"
            )
            return 0 if summary["complete"] else 2
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
        writer.close()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--expected-trace-sha256", default=TRACE_SHA256)
    parser.add_argument("--base-replayer", type=Path, required=True)
    parser.add_argument("--expected-base-sha256", default=BASE_REPLAYER_SHA256)
    parser.add_argument("--prefix-asset", type=Path, required=True)
    parser.add_argument("--expected-prefix-sha256", required=True)
    parser.add_argument("--vocab-size", type=int, default=151_936)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate")
    run = subparsers.add_parser("replay")
    run.add_argument("--base-url", required=True)
    run.add_argument("--worker-metrics-url", action="append", required=True)
    run.add_argument("--expected-model", required=True)
    run.add_argument("--capacity-manifest", required=True)
    run.add_argument(
        "--capacity-group", choices=("A", "B", "C", "D"), default="D"
    )
    run.add_argument("--run-id", required=True)
    run.add_argument("--output-dir", required=True)
    run.add_argument("--invalid-marker")
    run.add_argument("--prepare-workers", type=int, default=16)
    run.add_argument("--request-timeout-s", type=float, default=300.0)
    run.add_argument("--max-runtime-s", type=float, default=600.0)
    args = parser.parse_args(argv)
    if args.vocab_size <= 0:
        parser.error("vocab-size must be positive")
    if args.command == "replay":
        if not re.fullmatch(r"[A-Za-z0-9_]+", args.run_id):
            parser.error("run-id must contain only letters, digits, and underscores")
        if len(args.worker_metrics_url) not in (2, 4):
            parser.error("exactly two or four --worker-metrics-url values are required")
        if args.prepare_workers <= 0 or args.request_timeout_s <= 0:
            parser.error("worker and timeout values must be positive")
        if args.max_runtime_s != 600.0:
            parser.error("this profile requires an exact 600-second runtime boundary")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        base = load_base_replayer(args.base_replayer, args.expected_base_sha256)
        trace = build_shaped_trace(args.trace, args.expected_trace_sha256)
        prefix = load_prefix_asset(
            args.prefix_asset, args.expected_prefix_sha256, args.vocab_size
        )
        token_map = base.build_trie_token_map(trace.records)
        # Materialize representative requests to prove exact prefix equality and
        # within-session extension before either validate or replay succeeds.
        first = build_input_ids(trace.sessions[0][0], token_map, prefix, base)
        sibling = build_input_ids(trace.sessions[1][0], token_map, prefix, base)
        followup = build_input_ids(trace.sessions[0][1], token_map, prefix, base)
        if first[:SHARED_PREFIX_TOKENS] != sibling[:SHARED_PREFIX_TOKENS]:
            raise ValidationError("cross-session shared prefix is not identical")
        if first == sibling or first != followup[: len(first)]:
            raise ValidationError("private divergence or session extension is invalid")
        if args.command == "validate":
            descriptor = trace_descriptor(trace, token_map)
            descriptor["prefix_asset"] = {
                "path": prefix.path,
                "file_sha256": prefix.file_sha256,
                "token_ids_sha256": prefix.token_ids_sha256,
                "tokens": len(prefix.token_ids),
            }
            print(json.dumps(descriptor, indent=2, sort_keys=True))
            return 0
        return asyncio.run(replay(args, trace, prefix, base))
    except (OSError, ValidationError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
