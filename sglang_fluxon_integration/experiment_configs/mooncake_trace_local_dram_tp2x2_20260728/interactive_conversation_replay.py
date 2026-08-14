#!/usr/bin/env python3
"""Replay sealed Interactive Conversation part2 windows for D/E/F."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import math
import os
import socket
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


SCHEMA = "interactive_conversation_sglang_replay_v1"
TRACE_SHA256 = "3bdddbf607d7da977311f2e8c8abfeaf8e93d61fb22ba43ead0ff12f6d0b16e4"
BASE_REPLAYER_SHA256 = "98a797ad20f1b5b6cb078e87cf7e1e9a24773963b9d3ba3a8b67594d96d6153b"
HEADER = "user_id time_stamp(seconds) query_length response_length round_index"
TOKEN_MAPPING_BASIS_START_S = 7_200
TOKEN_MAPPING_BASIS_END_S = 10_800
TOKEN_MAPPING_BASIS_DURATION_S = (
    TOKEN_MAPPING_BASIS_END_S - TOKEN_MAPPING_BASIS_START_S
)
FORMAL_HIGH_10M_PROFILE = "formal-high-10m"
EVIDENCE_LOW_10M_PROFILE = "evidence-low-10m"
LEGACY_ONE_HOUR_PROFILE = "legacy-one-hour"
BLOCK_TOKENS = 512
NODE_BLOCK_BITS = 20

FULL_INVARIANTS = {
    "records": 263_810,
    "first_timestamp_s": 7_200,
    "last_timestamp_s": 25_053,
}
TOKEN_MAPPING_BASIS_INVARIANTS = {
    "records": 101_111,
    "users": 5_976,
    "first_timestamp_s": 7_200,
    "last_timestamp_s": 10_799,
    "query_tokens": 3_399_548,
    "prompt_tokens": 106_125_228,
    "output_tokens": 4_621_252,
    "max_input": 5_816,
    "max_context": 5_876,
    "max_round": 122,
}
WINDOW_PROFILES = {
    FORMAL_HIGH_10M_PROFILE: {
        "start_s": 10_020,
        "end_s": 10_620,
        "invariants": {
            "records": 22_631,
            "users": 2_760,
            "first_timestamp_s": 10_020,
            "last_timestamp_s": 10_619,
            "query_tokens": 788_880,
            "prompt_tokens": 29_576_894,
            "output_tokens": 1_015_642,
            "max_input": 5_546,
            "max_context": 5_592,
            "max_round": 116,
            "first_mapping_index": 71_899,
            "last_mapping_index": 94_529,
            "raw_lines_sha256": (
                "f2f437c622c016c4bf9cb9abb6a38947"
                "d1ed593fb535b494bf809ae875bfa7c8"
            ),
            "canonical_sha256": (
                "5ad8a1c120884f754e9b072a07e6ccd"
                "1e113375c586fdf5977bde952f640e161"
            ),
        },
    },
    EVIDENCE_LOW_10M_PROFILE: {
        "start_s": 7_200,
        "end_s": 7_800,
        "invariants": {
            "records": 5_594,
            "users": 915,
            "first_timestamp_s": 7_200,
            "last_timestamp_s": 7_799,
            "query_tokens": 165_582,
            "prompt_tokens": 1_680_916,
            "output_tokens": 249_894,
            "max_input": 1_042,
            "max_context": 1_128,
            "max_round": 18,
            "first_mapping_index": 0,
            "last_mapping_index": 5_593,
            "raw_lines_sha256": (
                "da6d2b5b1f3be9e39b2ef8e60015a0ed"
                "aac55142deb58bb69d3fe2a88a164f86"
            ),
            "canonical_sha256": (
                "866f5c2b9b2d9c8826efdc53edfc7fd8"
                "37a5bf04be2e47f5b48e0749a4e5f272"
            ),
        },
    },
    LEGACY_ONE_HOUR_PROFILE: {
        "start_s": 7_200,
        "end_s": 10_800,
        "invariants": {
            **TOKEN_MAPPING_BASIS_INVARIANTS,
            "first_mapping_index": 0,
            "last_mapping_index": 101_110,
            "raw_lines_sha256": (
                "878ba2cf89f92f7573ce9f0f305091d9"
                "6565ddbe492527bbe0670f7cd8e5b58d"
            ),
            "canonical_sha256": (
                "a1d09bd16eeabd9288bb39b45a447511"
                "4fe2a4c2bd76f20549505ef9f99ae2ad"
            ),
        },
    },
}
HIGH_PRESSURE_PROOF_EXPECTED = {
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
}


class ValidationError(ValueError):
    pass


def highpressure_group(group: str) -> str:
    if group not in {"D", "E", "F"}:
        raise ValidationError(f"unsupported high-pressure group: {group}")
    return f"{group}-highpressure"


def api_kind_for_group(group: str) -> str:
    if group == "E":
        return "vllm_adapter"
    if group in {"D", "F"}:
        return "sglang"
    raise ValidationError(f"unsupported high-pressure group: {group}")


@dataclass(frozen=True)
class InteractiveRecord:
    index: int
    source_index: int
    source_line: int
    user_id: int
    round_index: int
    timestamp_ms: int
    query_length: int
    input_length: int
    output_length: int
    hash_ids: tuple[int, ...]

    def canonical(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "source_index": self.source_index,
            "source_line": self.source_line,
            "user_id": self.user_id,
            "round_index": self.round_index,
            "timestamp_ms": self.timestamp_ms,
            "query_length": self.query_length,
            "input_length": self.input_length,
            "output_length": self.output_length,
            "hash_ids": list(self.hash_ids),
        }


@dataclass(frozen=True)
class InteractiveTrace:
    path: str
    sha256: str
    selected_raw_sha256: str
    selected_canonical_sha256: str
    records: tuple[InteractiveRecord, ...]
    mapping_records: tuple[InteractiveRecord, ...]
    full_records: int
    full_first_timestamp_s: int
    full_last_timestamp_s: int
    users: int
    query_tokens: int
    prompt_tokens: int
    output_tokens: int
    max_input: int
    max_context: int
    max_round: int
    window_profile: str
    window_start_s: int
    window_end_s: int
    window_duration_s: int
    high_pressure_proof: dict[str, Any]


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
    spec = importlib.util.spec_from_file_location("sealed_mooncake_trace_replay", path)
    if spec is None or spec.loader is None:
        raise ValidationError(f"cannot import base replayer: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
def parse_positive(raw: bytes, name: str, source_line: int, *, allow_zero: bool = False) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValidationError(f"line {source_line}: {name} is not an integer") from exc
    if value < 0 or (value == 0 and not allow_zero):
        bound = "non-negative" if allow_zero else "positive"
        raise ValidationError(f"line {source_line}: {name} must be {bound}")
    return value


def resolve_window_profile(window_profile: str) -> dict[str, Any]:
    try:
        return WINDOW_PROFILES[window_profile]
    except (KeyError, TypeError) as exc:
        allowed = ", ".join(WINDOW_PROFILES)
        raise ValidationError(
            f"unsupported window profile: {window_profile!r}; allowed={allowed}"
        ) from exc


def maximum_integer_aligned_window(
    timestamp_counts: dict[int, int],
    *,
    domain_start_s: int,
    domain_end_s: int,
    duration_s: int,
) -> tuple[int, tuple[int, ...]]:
    if duration_s <= 0 or domain_end_s - domain_start_s < duration_s:
        raise ValidationError("invalid maximum-window domain or duration")
    last_start_s = domain_end_s - duration_s
    current = sum(
        timestamp_counts.get(timestamp_s, 0)
        for timestamp_s in range(domain_start_s, domain_start_s + duration_s)
    )
    maximum = current
    starts = [domain_start_s]
    for start_s in range(domain_start_s + 1, last_start_s + 1):
        current -= timestamp_counts.get(start_s - 1, 0)
        current += timestamp_counts.get(start_s + duration_s - 1, 0)
        if current > maximum:
            maximum = current
            starts = [start_s]
        elif current == maximum:
            starts.append(start_s)
    return maximum, tuple(starts)


def validate_high_pressure_proof(
    timestamp_counts: dict[int, int],
) -> dict[str, Any]:
    proof: dict[str, Any] = {
        "alignment": "integer_seconds",
        "duration_s": 600,
    }
    for name, domain_start_s, domain_end_s in (
        (
            "full_trace",
            FULL_INVARIANTS["first_timestamp_s"],
            FULL_INVARIANTS["last_timestamp_s"] + 1,
        ),
        (
            "token_mapping_basis",
            TOKEN_MAPPING_BASIS_START_S,
            TOKEN_MAPPING_BASIS_END_S,
        ),
    ):
        maximum, starts = maximum_integer_aligned_window(
            timestamp_counts,
            domain_start_s=domain_start_s,
            domain_end_s=domain_end_s,
            duration_s=600,
        )
        proof[name] = {
            "domain_start_s": domain_start_s,
            "domain_end_s": domain_end_s,
            "max_records": maximum,
            "max_starts_s": list(starts),
        }
    if proof != HIGH_PRESSURE_PROOF_EXPECTED:
        raise ValidationError(f"high-pressure window proof differs: {proof}")
    return proof


def load_raw_trace(
    path: Path,
    expected_sha256: str,
    window_profile: str = FORMAL_HIGH_10M_PROFILE,
) -> InteractiveTrace:
    profile = resolve_window_profile(window_profile)
    window_start_s = int(profile["start_s"])
    window_end_s = int(profile["end_s"])
    window_duration_s = window_end_s - window_start_s
    actual_sha256 = sha256_file(path)
    if actual_sha256 != expected_sha256:
        raise ValidationError(
            f"raw trace SHA256 mismatch: expected={expected_sha256} actual={actual_sha256}"
        )

    records: list[InteractiveRecord] = []
    mapping_records: list[InteractiveRecord] = []
    history_tokens: dict[int, int] = {}
    next_round: dict[int, int] = {}
    selected_users: set[int] = set()
    selected_raw_digest = hashlib.sha256()
    selected_canonical_digest = hashlib.sha256()
    full_records = 0
    full_first_timestamp_s = -1
    full_last_timestamp_s = -1
    previous_timestamp_s = -1
    timestamp_counts: dict[int, int] = {}
    query_tokens = 0
    prompt_tokens = 0
    output_tokens = 0
    max_input = 0
    max_context = 0
    max_round = 0
    mapping_query_tokens = 0
    mapping_prompt_tokens = 0
    mapping_output_tokens = 0
    mapping_max_input = 0
    mapping_max_context = 0
    mapping_max_round = 0

    with path.open("rb") as handle:
        header = handle.readline().rstrip(b"\r\n").decode("ascii", errors="strict")
        if header != HEADER:
            raise ValidationError(f"raw trace header mismatch: {header!r}")
        for source_line, raw_line in enumerate(handle, 2):
            if not raw_line.strip():
                raise ValidationError(f"line {source_line}: blank lines are not allowed")
            fields = raw_line.split()
            if len(fields) != 5:
                raise ValidationError(
                    f"line {source_line}: expected five whitespace-separated fields"
                )
            user_id = parse_positive(fields[0], "user_id", source_line, allow_zero=True)
            timestamp_s = parse_positive(
                fields[1], "timestamp", source_line, allow_zero=True
            )
            query_length = parse_positive(fields[2], "query_length", source_line)
            response_length = parse_positive(fields[3], "response_length", source_line)
            round_index = parse_positive(
                fields[4], "round_index", source_line, allow_zero=True
            )
            if timestamp_s < previous_timestamp_s:
                raise ValidationError(f"line {source_line}: timestamps are not monotonic")
            previous_timestamp_s = timestamp_s
            timestamp_counts[timestamp_s] = timestamp_counts.get(timestamp_s, 0) + 1
            if full_records == 0:
                full_first_timestamp_s = timestamp_s
            source_index = full_records
            full_records += 1
            full_last_timestamp_s = timestamp_s

            if not (
                TOKEN_MAPPING_BASIS_START_S
                <= timestamp_s
                < TOKEN_MAPPING_BASIS_END_S
            ):
                continue
            expected_round = next_round.get(user_id, 0)
            if round_index != expected_round:
                raise ValidationError(
                    f"line {source_line}: user {user_id} round={round_index}, "
                    f"expected contiguous round={expected_round} in selected window"
                )
            next_round[user_id] = expected_round + 1
            input_length = history_tokens.get(user_id, 0) + query_length
            history_tokens[user_id] = input_length + response_length
            block_count = math.ceil(input_length / BLOCK_TOKENS)
            hash_ids = tuple(
                (user_id << NODE_BLOCK_BITS) | block_index
                for block_index in range(block_count)
            )
            record = InteractiveRecord(
                index=len(mapping_records),
                source_index=source_index,
                source_line=source_line,
                user_id=user_id,
                round_index=round_index,
                timestamp_ms=timestamp_s * 1000,
                query_length=query_length,
                input_length=input_length,
                output_length=response_length,
                hash_ids=hash_ids,
            )
            mapping_records.append(record)
            mapping_query_tokens += query_length
            mapping_prompt_tokens += input_length
            mapping_output_tokens += response_length
            mapping_max_input = max(mapping_max_input, input_length)
            mapping_max_context = max(mapping_max_context, input_length + response_length)
            mapping_max_round = max(mapping_max_round, round_index)
            if not (window_start_s <= timestamp_s < window_end_s):
                continue
            records.append(record)
            selected_users.add(user_id)
            selected_raw_digest.update(raw_line)
            selected_canonical_digest.update(canonical_json_bytes(record.canonical()))
            selected_canonical_digest.update(b"\n")
            query_tokens += query_length
            prompt_tokens += input_length
            output_tokens += response_length
            max_input = max(max_input, input_length)
            max_context = max(max_context, input_length + response_length)
            max_round = max(max_round, round_index)

    full_actual = {
        "records": full_records,
        "first_timestamp_s": full_first_timestamp_s,
        "last_timestamp_s": full_last_timestamp_s,
    }
    if full_actual != FULL_INVARIANTS:
        raise ValidationError(f"full raw trace invariants differ: {full_actual}")
    high_pressure_proof = validate_high_pressure_proof(timestamp_counts)
    mapping_actual = {
        "records": len(mapping_records),
        "users": len(history_tokens),
        "first_timestamp_s": mapping_records[0].timestamp_ms // 1000,
        "last_timestamp_s": mapping_records[-1].timestamp_ms // 1000,
        "query_tokens": mapping_query_tokens,
        "prompt_tokens": mapping_prompt_tokens,
        "output_tokens": mapping_output_tokens,
        "max_input": mapping_max_input,
        "max_context": mapping_max_context,
        "max_round": mapping_max_round,
    }
    if mapping_actual != TOKEN_MAPPING_BASIS_INVARIANTS:
        raise ValidationError(f"mapping basis invariants differ: {mapping_actual}")
    if not records:
        raise ValidationError("selected window is empty")
    window_actual = {
        "records": len(records),
        "users": len(selected_users),
        "first_timestamp_s": records[0].timestamp_ms // 1000,
        "last_timestamp_s": records[-1].timestamp_ms // 1000,
        "query_tokens": query_tokens,
        "prompt_tokens": prompt_tokens,
        "output_tokens": output_tokens,
        "max_input": max_input,
        "max_context": max_context,
        "max_round": max_round,
        "first_mapping_index": records[0].index,
        "last_mapping_index": records[-1].index,
        "raw_lines_sha256": selected_raw_digest.hexdigest(),
        "canonical_sha256": selected_canonical_digest.hexdigest(),
    }
    window_invariants = profile["invariants"]
    if window_actual != window_invariants:
        raise ValidationError(f"selected window invariants differ: {window_actual}")
    return InteractiveTrace(
        path=str(path.resolve()),
        sha256=actual_sha256,
        selected_raw_sha256=selected_raw_digest.hexdigest(),
        selected_canonical_sha256=selected_canonical_digest.hexdigest(),
        records=tuple(records),
        mapping_records=tuple(mapping_records),
        full_records=full_records,
        full_first_timestamp_s=full_first_timestamp_s,
        full_last_timestamp_s=full_last_timestamp_s,
        users=len(selected_users),
        query_tokens=query_tokens,
        prompt_tokens=prompt_tokens,
        output_tokens=output_tokens,
        max_input=max_input,
        max_context=max_context,
        max_round=max_round,
        window_profile=window_profile,
        window_start_s=window_start_s,
        window_end_s=window_end_s,
        window_duration_s=window_duration_s,
        high_pressure_proof=high_pressure_proof,
    )


def trace_descriptor(trace: InteractiveTrace, token_map: Any) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "raw_path": trace.path,
        "raw_sha256": trace.sha256,
        "raw_full_records": trace.full_records,
        "raw_first_timestamp_s": trace.full_first_timestamp_s,
        "raw_last_timestamp_s": trace.full_last_timestamp_s,
        "selection": {
            "profile": trace.window_profile,
            "window_semantics": "half_open",
            "start_s": trace.window_start_s,
            "end_s": trace.window_end_s,
            "duration_s": trace.window_duration_s,
            "records": len(trace.records),
            "first_timestamp_s": trace.records[0].timestamp_ms // 1000,
            "last_timestamp_s": trace.records[-1].timestamp_ms // 1000,
            "raw_lines_sha256": trace.selected_raw_sha256,
            "canonical_sha256": trace.selected_canonical_sha256,
        },
        "high_pressure_proof": trace.high_pressure_proof,
        "users": trace.users,
        "query_tokens": trace.query_tokens,
        "prompt_tokens": trace.prompt_tokens,
        "output_tokens": trace.output_tokens,
        "max_input": trace.max_input,
        "max_context": trace.max_context,
        "max_round": trace.max_round,
        "offered_qps": len(trace.records) / trace.window_duration_s,
        "token_mapping": {
            "history": "cumulative query + synthetic response lengths per user",
            "blocks": "stable (user_id, 512-token block index)",
            "basis_start_s": TOKEN_MAPPING_BASIS_START_S,
            "basis_end_s": TOKEN_MAPPING_BASIS_END_S,
            "basis_records": len(trace.mapping_records),
            "trie_nodes": token_map.node_count,
            "trie_parents": token_map.parent_count,
            "max_fanout": token_map.max_fanout,
        },
    }


async def dispatch_open_loop(
    *,
    base: Any,
    selected: Sequence[Any],
    run_start: float,
    prepare_lead_s: float,
    session: Any,
    generate_url: str,
    token_map: Any,
    executor: ThreadPoolExecutor,
    writer: Any,
    expected_model: str,
    invalid_marker: Path | None,
    window_start_s: int,
    api_kind: str,
) -> list[dict[str, Any]]:
    loop = asyncio.get_running_loop()
    tasks: list[asyncio.Task[dict[str, Any]]] = []
    for item in selected:
        if invalid_marker is not None and invalid_marker.exists():
            raise ValidationError(f"interference marker appeared: {invalid_marker}")
        scheduled_offset_s = item.schedule_timestamp_ms / 1000.0 - window_start_s
        scheduled_monotonic = run_start + scheduled_offset_s
        delay = scheduled_monotonic - prepare_lead_s - loop.time()
        if delay > 0:
            await asyncio.sleep(delay)
        tasks.append(
            asyncio.create_task(
                base.send_one(
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
            )
        )
    return list(await asyncio.gather(*tasks))


async def replay(args: argparse.Namespace, trace: InteractiveTrace, base: Any) -> int:
    try:
        import aiohttp
    except ImportError as exc:
        raise ValidationError("aiohttp is required for replay") from exc

    token_map = base.build_trie_token_map(trace.mapping_records)
    if base.TOKEN_MAX_EXCLUSIVE > args.vocab_size:
        raise ValidationError("base token mapping exceeds model vocabulary")
    capacity = base.load_capacity_manifest(
        Path(args.capacity_manifest), args.group, formal=True
    )
    result_group = highpressure_group(args.group)
    api_kind = api_kind_for_group(args.group)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    writer = base.JsonlWriter(output_dir / "requests.jsonl")
    executor = ThreadPoolExecutor(
        max_workers=args.prepare_workers, thread_name_prefix="interactive-payload"
    )
    selected = tuple(
        base.ScheduledRecord(record=record, schedule_timestamp_ms=record.timestamp_ms)
        for record in trace.records
    )
    compact_results: list[dict[str, Any]] = []
    timeout = aiohttp.ClientTimeout(
        total=args.request_timeout_s,
        connect=60,
        sock_connect=60,
        sock_read=args.request_timeout_s,
    )
    connector = base.make_tcp_connector(aiohttp)
    base_url = args.base_url.rstrip("/")
    script_path = Path(__file__).resolve()
    try:
        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            preflight = await base.endpoint_preflight(
                session, base_url, args.expected_model, formal=True
            )
            loop = asyncio.get_running_loop()
            run_start = loop.time() + args.prepare_lead_s
            manifest = {
                "schema": SCHEMA,
                "created_at_utc": base.utc_now(),
                "run_id": args.run_id,
                "group": result_group,
                "dispatch_mode": "open_loop",
                "base_url": base_url,
                "generate_url": f"{base_url}/generate",
                "api_kind": api_kind,
                "expected_model": args.expected_model,
                "vocab_size": args.vocab_size,
                "prepare_lead_s": args.prepare_lead_s,
                "prepare_workers": args.prepare_workers,
                "request_timeout_s": args.request_timeout_s,
                "tcp_connector": dict(base.TCP_CONNECTOR_CONFIG),
                "client_hostname": socket.gethostname(),
                "client_pid": os.getpid(),
                "python": sys.version,
                "script_path": str(script_path),
                "script_sha256": sha256_file(script_path),
                "base_replayer_path": str(Path(args.base_replayer).resolve()),
                "base_replayer_sha256": sha256_file(Path(args.base_replayer)),
                "trace": trace_descriptor(trace, token_map),
                "capacity": capacity,
                "endpoint_preflight": preflight,
                "invalid_marker": (
                    str(Path(args.invalid_marker).resolve())
                    if args.invalid_marker
                    else None
                ),
            }
            (output_dir / "run_manifest.json").write_bytes(
                canonical_json_bytes(manifest) + b"\n"
            )
            compact_results = await dispatch_open_loop(
                base=base,
                selected=selected,
                run_start=run_start,
                prepare_lead_s=args.prepare_lead_s,
                session=session,
                generate_url=f"{base_url}/generate",
                token_map=token_map,
                executor=executor,
                writer=writer,
                expected_model=args.expected_model,
                invalid_marker=(Path(args.invalid_marker) if args.invalid_marker else None),
                window_start_s=trace.window_start_s,
                api_kind=api_kind,
            )
            wall_s = max(
                (float(item["finished_offset_s"]) for item in compact_results),
                default=0.0,
            )
            summary = base.summarize_results(compact_results, selected, wall_s)
            summary.update(
                schema=SCHEMA,
                run_id=args.run_id,
                group=result_group,
                schedule_span_s=trace.window_duration_s,
                offered_qps=len(selected) / trace.window_duration_s,
                raw_last_arrival_offset_s=(
                    trace.records[-1].timestamp_ms / 1000.0 - trace.window_start_s
                ),
                drain_s=max(
                    0.0,
                    wall_s
                    - (trace.records[-1].timestamp_ms / 1000.0 - trace.window_start_s),
                ),
            )
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
    parser.add_argument("--base-replayer", type=Path, required=True)
    parser.add_argument("--expected-base-sha256", default=BASE_REPLAYER_SHA256)
    parser.add_argument(
        "--window-profile",
        choices=tuple(WINDOW_PROFILES),
        default=FORMAL_HIGH_10M_PROFILE,
        help=(
            "sealed selection identity; arbitrary start/end/duration cropping is not "
            "accepted"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate")
    replay_parser = subparsers.add_parser("replay")
    replay_parser.add_argument("--group", choices=("D", "E", "F"), default="D")
    replay_parser.add_argument("--base-url", required=True)
    replay_parser.add_argument("--expected-model", required=True)
    replay_parser.add_argument("--vocab-size", type=int, required=True)
    replay_parser.add_argument("--capacity-manifest", required=True)
    replay_parser.add_argument("--run-id", required=True)
    replay_parser.add_argument("--output-dir", required=True)
    replay_parser.add_argument("--invalid-marker")
    replay_parser.add_argument("--prepare-lead-s", type=float, default=5.0)
    replay_parser.add_argument("--prepare-workers", type=int, default=16)
    replay_parser.add_argument("--request-timeout-s", type=float, default=21_600.0)
    args = parser.parse_args(argv)
    if args.command == "replay":
        if not args.run_id or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" for ch in args.run_id):
            parser.error("run-id must contain only letters, digits, and underscores")
        if args.vocab_size <= 0 or args.prepare_workers <= 0:
            parser.error("vocab-size and prepare-workers must be positive")
        if not math.isfinite(args.prepare_lead_s) or args.prepare_lead_s < 0:
            parser.error("prepare-lead-s must be finite and non-negative")
        if not math.isfinite(args.request_timeout_s) or args.request_timeout_s <= 0:
            parser.error("request-timeout-s must be finite and positive")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        base = load_base_replayer(args.base_replayer, args.expected_base_sha256)
        trace = load_raw_trace(
            args.trace, args.expected_trace_sha256, args.window_profile
        )
        token_map = base.build_trie_token_map(trace.mapping_records)
        if args.command == "validate":
            print(json.dumps(trace_descriptor(trace, token_map), indent=2, sort_keys=True))
            return 0
        return asyncio.run(replay(args, trace, base))
    except (OSError, ValidationError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
