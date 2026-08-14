#!/usr/bin/env python3
"""Quantify request placement and conservative load->evict->load churn.

The SGLang hostless read log names every radix node restored in a batch.  A
second read of the same ``(TP rank, radix node id, token count)`` can only
happen after that exact device value was evicted again.  This gives a
conservative, content-level lower bound without changing eviction behavior.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


READ_MARKER = "Fluxon hostless read keys:"
LIFECYCLE_MARKER = "Fluxon hostless request lifecycle:"
PREFIX = re.compile(r"^\[(?P<time>[^]]+) TP(?P<rank>\d+)]")
READ = re.compile(
    r"best_match_node=(?P<anchor>\d+) nodes=(?P<nodes>\d+) "
    r"tokens=(?P<tokens>\d+).*? pages=(?P<pages>\d+) "
    r"groups=(?P<groups>\[[^]]*]) first_key=(?P<first>\S+) "
    r"last_key=(?P<last>\S+) key_sig=(?P<sig>\S+) "
    r"trigger=(?P<trigger>.*?) scheduler_reason="
)
TRIGGER_NODE = re.compile(
    r"full_storage_backed_match\(node=(?P<node>\d+),tokens=(?P<tokens>\d+)\)"
)
SESSION_TURN = re.compile(r":session:(?P<session>\d+):turn:(?P<turn>\d+)]")
NUMBER = re.compile(r"^-?(?:\d+|\d+\.\d+)$")


def parse_number(value: str) -> int | float | str:
    if not NUMBER.fullmatch(value):
        return value
    return float(value) if "." in value else int(value)


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def stats(values: Iterable[int | float]) -> dict[str, Any]:
    samples = [float(value) for value in values]
    if not samples:
        return {"count": 0}
    return {
        "count": len(samples),
        "sum": sum(samples),
        "mean": sum(samples) / len(samples),
        "p50": percentile(samples, 0.50),
        "p90": percentile(samples, 0.90),
        "p99": percentile(samples, 0.99),
        "max": max(samples),
    }


def timestamp_epoch(value: str) -> float:
    timestamp = value.split(" TP", 1)[0]
    return datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S").replace(
        tzinfo=timezone.utc
    ).timestamp()


def discover_one(root: Path, pattern: str) -> Path:
    matches = sorted(root.glob(pattern))
    if len(matches) != 1:
        raise ValueError(f"expected one {pattern} below {root}, found {matches}")
    return matches[0]


def parse_request_metrics(path: Path, node: str) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            record = json.loads(line)
            raw_parameters = record.get("request_parameters")
            if not isinstance(raw_parameters, str):
                continue
            parameters = json.loads(raw_parameters)
            text = str(parameters.get("text", ""))
            markers = list(SESSION_TURN.finditer(text))
            if not markers:
                continue
            # A later turn contains the complete conversation history, so the
            # request text also contains all earlier session/turn markers.
            # The final marker is the current user turn.
            marker = markers[-1]
            request_id = str(record.get("id") or parameters.get("rid") or "")
            if not request_id:
                raise ValueError(f"{path}:{line_number}: missing request id")
            if request_id in records:
                raise ValueError(f"{path}:{line_number}: duplicate request {request_id}")
            records[request_id] = {
                "request_id": request_id,
                "node": node,
                "session": int(marker.group("session")),
                "turn": int(marker.group("turn")),
                "prompt_tokens": int(record.get("prompt_tokens") or 0),
                "cached_tokens": int(record.get("cached_tokens") or 0),
                "cached_tokens_details": record.get("cached_tokens_details") or {},
                "received_at": float(record.get("request_received_ts") or 0),
                "finished_at": float(record.get("request_finished_ts") or 0),
                "e2e_latency_s": float(record.get("e2e_latency") or 0),
            }
    return records


def parse_lifecycle_fields(line: str) -> dict[str, Any]:
    fields = line.split(LIFECYCLE_MARKER, 1)[1].strip()
    result: dict[str, Any] = {}
    for item in fields.split():
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        result[key] = parse_number(value)
    return result


def parse_sglang_log(path: Path, node: str) -> dict[str, Any]:
    reads: list[dict[str, Any]] = []
    lifecycle: list[dict[str, Any]] = []
    malformed_reads: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for line_number, line in enumerate(stream, 1):
            prefix = PREFIX.match(line)
            if prefix is None:
                continue
            rank = int(prefix.group("rank"))
            event_time = timestamp_epoch(prefix.group("time"))
            if READ_MARKER in line:
                match = READ.search(line)
                if match is None:
                    malformed_reads.append({"line": line_number, "text": line.rstrip()})
                    continue
                all_trigger_components = [
                    (int(item.group("node")), int(item.group("tokens")))
                    for item in TRIGGER_NODE.finditer(match.group("trigger"))
                ]
                declared_nodes = int(match.group("nodes"))
                # TP common-prefix convergence can shorten the actual read
                # after the scheduler recorded a longer host-hit trigger.  In
                # that case the log retains the leading trigger-only nodes;
                # the actual read is the deepest-to-root suffix described by
                # ``nodes`` and ``groups``.
                components = all_trigger_components[-declared_nodes:]
                reads.append(
                    {
                        "node": node,
                        "rank": rank,
                        "line": line_number,
                        "log_epoch_s": event_time,
                        "anchor_node": int(match.group("anchor")),
                        "nodes": declared_nodes,
                        "tokens": int(match.group("tokens")),
                        "pages": int(match.group("pages")),
                        "groups": json.loads(match.group("groups")),
                        "first_key": match.group("first"),
                        "last_key": match.group("last"),
                        "key_sig": match.group("sig"),
                        "components": components,
                    }
                )
            if LIFECYCLE_MARKER in line:
                fields = parse_lifecycle_fields(line)
                fields.update(
                    {
                        "node": node,
                        "rank": rank,
                        "line": line_number,
                        "log_epoch_s": event_time,
                    }
                )
                lifecycle.append(fields)

    # Match each consumed terminal to the newest still-unmatched read for the
    # same rank/anchor.  r35 proved that a later untracked tail can overwrite a
    # consumed terminal.  Using the newest pending read keeps one such missing
    # terminal from shifting every later request on the same radix node.
    pending_reads: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    consumed_terminals = [
        record
        for record in lifecycle
        if record.get("terminal") == "load_back_consumed"
        and record.get("decision") != "untracked"
    ]
    timeline: list[tuple[int, int, dict[str, Any]]] = []
    timeline.extend((record["line"], 0, record) for record in reads)
    timeline.extend((record["line"], 1, record) for record in consumed_terminals)
    terminal_without_read: list[dict[str, Any]] = []
    joined = 0
    for _, kind, record in sorted(timeline, key=lambda item: (item[0], item[1])):
        if kind == 0:
            pending_reads[(record["rank"], record["anchor_node"])].append(record)
            continue
        key = (record["rank"], int(record["anchor_node"]))
        if not pending_reads[key]:
            terminal_without_read.append(
                {
                    "rank": key[0],
                    "anchor_node": key[1],
                    "line": record["line"],
                    "request_id": str(record.get("req", "")),
                }
            )
            continue
        read = pending_reads[key].pop()
        read["request_id"] = str(record["req"])
        read["evict_actual_tokens"] = int(record.get("evict_actual_tokens", 0))
        read["evict_candidate_tokens"] = int(
            record.get("evict_candidate_tokens", 0)
        )
        joined += 1

    unmatched_reads = [
        {
            "rank": key[0],
            "anchor_node": key[1],
            "count": len(items),
            "lines": [item["line"] for item in items[:20]],
        }
        for key, items in sorted(pending_reads.items())
        if items
    ]

    component_shape_errors = [
        {
            "rank": record["rank"],
            "line": record["line"],
            "declared_nodes": record["nodes"],
            "parsed_nodes": len(record["components"]),
            "declared_tokens": record["tokens"],
            "component_tokens": sum(tokens for _, tokens in record["components"]),
        }
        for record in reads
        if len(record["components"]) != record["nodes"]
        or sum(tokens for _, tokens in record["components"]) != record["tokens"]
    ]
    return {
        "reads": reads,
        "lifecycle": lifecycle,
        "guards": {
            "malformed_reads": malformed_reads,
            "component_shape_errors": component_shape_errors,
            "lifecycle_present": bool(lifecycle),
            "read_lifecycle_joined": joined,
            "unmatched_reads": unmatched_reads,
            "terminal_without_read": terminal_without_read,
        },
    }


def aggregate_cached_details(records: Iterable[dict[str, Any]]) -> dict[str, float]:
    totals: Counter[str] = Counter()
    for record in records:
        details = record.get("cached_tokens_details") or {}
        if isinstance(details, dict):
            for key, value in details.items():
                if isinstance(value, (int, float)):
                    totals[str(key)] += float(value)
    return dict(sorted(totals.items()))


def summarize_placement(requests: dict[str, dict[str, Any]]) -> dict[str, Any]:
    by_node: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_session: dict[int, list[dict[str, Any]]] = defaultdict(list)
    seen_pairs: set[tuple[int, int]] = set()
    duplicate_pairs: list[tuple[int, int]] = []
    for record in requests.values():
        pair = (record["session"], record["turn"])
        if pair in seen_pairs:
            duplicate_pairs.append(pair)
        seen_pairs.add(pair)
        by_node[record["node"]].append(record)
        by_session[record["session"]].append(record)

    switches = 0
    sessions_with_switch = 0
    switch_by_turn: Counter[int] = Counter()
    session_summaries: list[dict[str, Any]] = []
    missing_turns: dict[int, list[int]] = {}
    for session, records in sorted(by_session.items()):
        ordered = sorted(records, key=lambda item: item["turn"])
        present = {item["turn"] for item in ordered}
        missing = [turn for turn in range(24) if turn not in present]
        if missing:
            missing_turns[session] = missing
        local_switches = 0
        for previous, current in zip(ordered, ordered[1:]):
            if previous["node"] != current["node"]:
                switches += 1
                local_switches += 1
                switch_by_turn[current["turn"]] += 1
        if local_switches:
            sessions_with_switch += 1
        session_summaries.append(
            {
                "session": session,
                "requests": len(ordered),
                "switches": local_switches,
                "nodes": dict(Counter(item["node"] for item in ordered)),
            }
        )

    return {
        "requests": len(requests),
        "session_turn_pairs": len(seen_pairs),
        "duplicate_session_turn_pairs": duplicate_pairs,
        "sessions": len(by_session),
        "missing_turns": missing_turns,
        "by_node": {
            node: {
                "requests": len(records),
                "sessions": len({item["session"] for item in records}),
                "prompt_tokens": sum(item["prompt_tokens"] for item in records),
                "cached_tokens": sum(item["cached_tokens"] for item in records),
                "cached_tokens_details": aggregate_cached_details(records),
                "e2e_latency_s": stats(item["e2e_latency_s"] for item in records),
                "requests_by_turn": dict(
                    sorted(Counter(item["turn"] for item in records).items())
                ),
            }
            for node, records in sorted(by_node.items())
        },
        "node_switches": switches,
        "sessions_with_switch": sessions_with_switch,
        "switches_by_destination_turn": dict(sorted(switch_by_turn.items())),
        "session_summaries": session_summaries,
    }


def summarize_churn(
    events: list[dict[str, Any]], requests: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    ordered = sorted(events, key=lambda item: item["line"])
    component_seen: dict[tuple[int, int], dict[str, Any]] = {}
    batch_seen: dict[tuple[str, int, int], dict[str, Any]] = {}
    component_occurrences: Counter[tuple[int, int]] = Counter()
    batch_occurrences: Counter[tuple[str, int, int]] = Counter()
    repeat_intervals: list[float] = []
    repeated_component_tokens = 0
    repeated_exact_batch_tokens = 0
    same_session_repeat_tokens = 0
    cross_session_repeat_tokens = 0
    repeat_by_turn: Counter[int] = Counter()
    restore_by_turn: Counter[int] = Counter()
    evict_by_turn: Counter[int] = Counter()
    joined_requests = 0

    for event in ordered:
        metadata = requests.get(str(event.get("request_id", "")))
        event_epoch = event["log_epoch_s"]
        if metadata is not None:
            joined_requests += 1
            event_epoch = metadata["received_at"] or event_epoch
            restore_by_turn[metadata["turn"]] += event["tokens"]
            evict_by_turn[metadata["turn"]] += event.get("evict_actual_tokens", 0)

        batch_key = (event["key_sig"], event["tokens"], event["pages"])
        batch_occurrences[batch_key] += 1
        if batch_key in batch_seen:
            repeated_exact_batch_tokens += event["tokens"]
        batch_seen[batch_key] = {"epoch": event_epoch, "metadata": metadata}

        event_repeat_tokens = 0
        for component_node, component_tokens in event["components"]:
            component_key = (component_node, component_tokens)
            component_occurrences[component_key] += 1
            previous = component_seen.get(component_key)
            if previous is not None:
                repeated_component_tokens += component_tokens
                event_repeat_tokens += component_tokens
                interval = event_epoch - previous["epoch"]
                if interval >= 0:
                    repeat_intervals.append(interval)
                previous_metadata = previous["metadata"]
                if metadata is not None and previous_metadata is not None:
                    if metadata["session"] == previous_metadata["session"]:
                        same_session_repeat_tokens += component_tokens
                    else:
                        cross_session_repeat_tokens += component_tokens
            component_seen[component_key] = {
                "epoch": event_epoch,
                "metadata": metadata,
            }
        if metadata is not None and event_repeat_tokens:
            repeat_by_turn[metadata["turn"]] += event_repeat_tokens

    total_tokens = sum(event["tokens"] for event in ordered)
    unique_component_tokens = sum(key[1] for key in component_seen)
    repeated_components = [
        {
            "component_node": key[0],
            "tokens": key[1],
            "loads": count,
            "repeated_tokens": (count - 1) * key[1],
        }
        for key, count in component_occurrences.items()
        if count > 1
    ]
    repeated_components.sort(
        key=lambda item: (item["repeated_tokens"], item["loads"]), reverse=True
    )
    return {
        "read_events": len(ordered),
        "request_joined_events": joined_requests,
        "restore_tokens": total_tokens,
        "restore_pages": sum(event["pages"] for event in ordered),
        "evict_actual_tokens": sum(event.get("evict_actual_tokens", 0) for event in ordered),
        "component_loads": sum(len(event["components"]) for event in ordered),
        "unique_components": len(component_seen),
        "unique_component_tokens": unique_component_tokens,
        "repeated_component_loads": sum(
            count - 1 for count in component_occurrences.values() if count > 1
        ),
        "repeated_component_tokens": repeated_component_tokens,
        "repeated_component_token_ratio": (
            repeated_component_tokens / total_tokens if total_tokens else 0.0
        ),
        "exact_batch_signatures": len(batch_seen),
        "repeated_exact_batch_loads": sum(
            count - 1 for count in batch_occurrences.values() if count > 1
        ),
        "repeated_exact_batch_tokens": repeated_exact_batch_tokens,
        "repeated_exact_batch_token_ratio": (
            repeated_exact_batch_tokens / total_tokens if total_tokens else 0.0
        ),
        "repeat_interval_seconds": stats(repeat_intervals),
        "same_session_repeat_tokens": same_session_repeat_tokens,
        "cross_session_repeat_tokens": cross_session_repeat_tokens,
        "restore_tokens_by_turn": dict(sorted(restore_by_turn.items())),
        "repeated_component_tokens_by_turn": dict(sorted(repeat_by_turn.items())),
        "evict_actual_tokens_by_turn": dict(sorted(evict_by_turn.items())),
        "top_repeated_components": repeated_components[:30],
    }


def summarize_run(name: str, artifact: Path) -> dict[str, Any]:
    requests: dict[str, dict[str, Any]] = {}
    parsed_nodes: dict[str, dict[str, Any]] = {}
    inputs: dict[str, str] = {}
    for node, directory in (("node0", "gpu0"), ("node1", "gpu1")):
        log = discover_one(artifact, f"logs/{directory}/*sglang*.log")
        request_log = discover_one(artifact, f"request_metrics/{directory}/*.log")
        inputs[f"{node}_sglang"] = str(log)
        inputs[f"{node}_request_metrics"] = str(request_log)
        node_requests = parse_request_metrics(request_log, node)
        overlap = requests.keys() & node_requests.keys()
        if overlap:
            raise ValueError(f"request ids appear on both nodes: {sorted(overlap)[:5]}")
        requests.update(node_requests)
        parsed_nodes[node] = parse_sglang_log(log, node)

    by_node: dict[str, Any] = {}
    for node, parsed in parsed_nodes.items():
        ranks = sorted({record["rank"] for record in parsed["reads"]})
        by_rank = {
            str(rank): summarize_churn(
                [record for record in parsed["reads"] if record["rank"] == rank],
                requests,
            )
            for rank in ranks
        }
        logical_rank = "0" if "0" in by_rank else str(ranks[0])
        by_node[node] = {
            "guards": parsed["guards"],
            "by_rank": by_rank,
            "logical_tp0": by_rank[logical_rank],
            "rank_symmetry": {
                "read_events": {
                    rank: summary["read_events"] for rank, summary in by_rank.items()
                },
                "restore_tokens": {
                    rank: summary["restore_tokens"] for rank, summary in by_rank.items()
                },
                "repeated_component_tokens": {
                    rank: summary["repeated_component_tokens"]
                    for rank, summary in by_rank.items()
                },
            },
        }

    logical_tokens = sum(
        node["logical_tp0"]["restore_tokens"] for node in by_node.values()
    )
    logical_repeated = sum(
        node["logical_tp0"]["repeated_component_tokens"] for node in by_node.values()
    )
    physical_tokens = sum(
        rank["restore_tokens"]
        for node in by_node.values()
        for rank in node["by_rank"].values()
    )
    physical_repeated = sum(
        rank["repeated_component_tokens"]
        for node in by_node.values()
        for rank in node["by_rank"].values()
    )
    return {
        "name": name,
        "artifact": str(artifact),
        "inputs": inputs,
        "placement": summarize_placement(requests),
        "by_node": by_node,
        "cluster": {
            "logical_tp0_restore_tokens": logical_tokens,
            "logical_tp0_repeated_component_tokens": logical_repeated,
            "logical_tp0_repeated_component_token_ratio": (
                logical_repeated / logical_tokens if logical_tokens else 0.0
            ),
            "physical_tp_restore_tokens": physical_tokens,
            "physical_tp_repeated_component_tokens": physical_repeated,
            "physical_tp_repeated_component_token_ratio": (
                physical_repeated / physical_tokens if physical_tokens else 0.0
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run",
        action="append",
        required=True,
        help="NAME=ARTIFACT_DIR; may be repeated",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    runs: list[dict[str, Any]] = []
    for raw in args.run:
        if "=" not in raw:
            raise SystemExit(f"--run must be NAME=ARTIFACT_DIR: {raw}")
        name, path = raw.split("=", 1)
        runs.append(summarize_run(name, Path(path)))
    output = {
        "schema": "e44_r37_restore_churn_v1",
        "interpretation_guards": [
            "A repeated component is the same (TP rank, runtime radix node id, token count) read more than once; a second read implies an intervening device eviction.",
            "Node splitting can change runtime ids or token counts, so component repetition is a conservative lower bound, not an upper bound.",
            "TP0 is used for logical-token totals; both ranks are summed for physical TP restore work.",
            "Request/session/turn attribution requires r35 lifecycle observation fields; runs without them still have content-level churn and placement totals.",
        ],
        "runs": runs,
    }
    rendered = json.dumps(output, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
