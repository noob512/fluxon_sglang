#!/usr/bin/env python3
"""Replay CacheSack-style admission policies on an E44 Fluxon KV trace.

The replay deliberately uses the SSD-off lineage as its primary demand trace.
Each physical ``(requester, TP rank, KV key)`` is modeled independently, as
required by CacheSack's TTL approximation.  The SSD is below owner-local DRAM,
so only lineage sources ``R`` and ``U`` are SSD lookup opportunities; ``L`` is
an owner-local DRAM hit and does not refresh SSD recency.

The script reproduces the following CacheSack mechanisms:

* AdmitOnWrite, AdmitOnMiss, AdmitOnSecondMiss and NeverAdmit;
* TTL as an approximation to LRU retention;
* traffic categories and per-category metric estimates;
* a lower-convex-hull, fractional-greedy optimizer.

Google does not publish the cost coefficient for flash writes.  Fluxon has an
explicit per-owner write-rate boundary, so the optimizer constrains written
bytes directly and minimizes downstream KV misses.  This is a declared
Fluxon adaptation of CacheSack's optimizer, not a reproduction of Google's
confidential total-cost function.

The current lineage has no independent normal-Put key/timestamp stream.
Consequently, the identifiable AdmitOnWrite lower bound is equal to
AdmitOnMiss.  An additional optimistic upper bound assumes every object was
written immediately before its first observed SSD lookup.  Neither bound is
reported as an exact normal-Put result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from analyze_e44_r60_kv_lineage import load_events, parse_input_spec
from model_e44_resource_load_scaling import (
    RequestMeta,
    build_session_chains,
    load_request_metrics,
    logical_lineage,
)


MIB = 1 << 20
GIB = 1 << 30
TIB = 1 << 40
POLICIES = (
    "never_admit",
    "admit_on_second_miss",
    "admit_on_miss",
    "admit_on_write_observed_lower",
)
BOUND_POLICY = "admit_on_write_optimistic_upper"


@dataclass(frozen=True)
class PhysicalAccess:
    request_id: str
    node: str
    tp_rank: int
    key_id: str
    depth: int
    source: str
    plan_s: float
    terminal_s: float

    @property
    def identity(self) -> tuple[str, int, str]:
        return self.node, self.tp_rank, self.key_id


@dataclass(frozen=True)
class PolicyPoint:
    policy: str
    writes: float
    writes_bytes: float
    misses: float
    hits: float
    cache_byte_seconds: float
    reads: float


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = quantile * (len(ordered) - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return float(ordered[lower])
    fraction = rank - lower
    return float(ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction)


def distribution(values: Iterable[float]) -> dict[str, float | int | None]:
    materialized = list(values)
    return {
        "count": len(materialized),
        "mean": sum(materialized) / len(materialized) if materialized else None,
        "p50": percentile(materialized, 0.50),
        "p90": percentile(materialized, 0.90),
        "p99": percentile(materialized, 0.99),
        "max": max(materialized) if materialized else None,
    }


def ttl_label(ttl_s: float) -> str:
    if math.isinf(ttl_s):
        return "inf"
    return f"{ttl_s:g}"


def parse_ttl(raw: str) -> float:
    if raw.lower() in {"inf", "infinity", "+inf"}:
        return math.inf
    try:
        value = float(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid TTL: {raw}") from exc
    if value <= 0:
        raise argparse.ArgumentTypeError("TTL must be positive")
    return value


def parse_node_budget(raw: str) -> tuple[str, int]:
    node, separator, value = raw.partition("=")
    if not separator or not node or not value:
        raise argparse.ArgumentTypeError("node budget must be NODE=BYTES")
    try:
        budget = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid byte budget: {value}") from exc
    if budget < 0:
        raise argparse.ArgumentTypeError("node budget must be non-negative")
    return node, budget


def depth_bucket(depth: int, width: int) -> str:
    start = max(0, depth // width * width)
    return f"{start:04d}-{start + width - 1:04d}"


def lineage_files(specs: Iterable[str]) -> list[Path]:
    paths: list[Path] = []
    for spec in specs:
        _node, path = parse_input_spec(spec)
        if path.is_dir():
            paths.extend(sorted(candidate for candidate in path.rglob("*.log")))
        else:
            paths.append(path)
    return paths


def build_physical_accesses(
    events: list[dict[str, Any]],
    requests: dict[str, RequestMeta],
) -> tuple[list[PhysicalAccess], dict[str, Any]]:
    """Collapse retries without collapsing TP ranks or physical KV blocks."""

    selected: dict[tuple[str, str, int, str], PhysicalAccess] = {}
    terminals: dict[tuple[str, str, int, str], set[str]] = defaultdict(set)
    counters: Counter[str] = Counter()
    for event in events:
        request_id = str(event.get("req", ""))
        if request_id not in requests:
            raise ValueError(f"unmapped lineage request id: {request_id!r}")
        node = str(event["node"])
        rank = int(event["tp_rank"])
        keys = [str(key) for key in event["key_ids"]]
        sources = str(event["sources"])
        start_depth = int(event["start_depth_pages"])
        plan_s = int(event["plan_unix_ns"]) / 1e9
        terminal_s = int(event["terminal_unix_ns"]) / 1e9
        terminal = str(event.get("terminal", "unknown"))
        counters["raw_physical_events"] += 1
        counters[f"raw_terminal.{terminal}"] += 1
        for offset, (key_id, source) in enumerate(zip(keys, sources)):
            if source not in "LRU":
                raise ValueError(f"invalid lineage source: {source!r}")
            access = PhysicalAccess(
                request_id=request_id,
                node=node,
                tp_rank=rank,
                key_id=key_id,
                depth=start_depth + offset,
                source=source,
                plan_s=plan_s,
                terminal_s=terminal_s,
            )
            identity = (request_id, node, rank, key_id)
            terminals[identity].add(terminal)
            previous = selected.get(identity)
            if previous is None:
                selected[identity] = access
                continue
            counters["retry_or_duplicate_block_observations"] += 1
            if previous.depth != access.depth:
                raise ValueError(
                    "same external request observes one physical key at different depths: "
                    f"identity={identity} depths={previous.depth}/{access.depth}"
                )
            if access.plan_s < previous.plan_s:
                selected[identity] = access

    accesses = sorted(
        selected.values(),
        key=lambda item: (
            item.plan_s,
            item.request_id,
            item.node,
            item.tp_rank,
            item.depth,
            item.key_id,
        ),
    )
    counters["deduplicated_physical_block_accesses"] = len(accesses)
    counters["deduplicated_external_requests"] = len(
        {access.request_id for access in accesses}
    )
    counters["deduplicated_retry_keys"] = sum(
        len(values) > 1 for values in terminals.values()
    )
    counters["source_L"] = sum(access.source == "L" for access in accesses)
    counters["source_R"] = sum(access.source == "R" for access in accesses)
    counters["source_U"] = sum(access.source == "U" for access in accesses)
    return accesses, dict(counters)


def build_categories(
    accesses: list[PhysicalAccess],
    *,
    bucket_width: int,
) -> tuple[dict[str, dict[tuple[str, int, str], list[PhysicalAccess]]], dict[str, Any]]:
    """Build requester-local SSD demand categories from owner-DRAM misses."""

    category_by_identity: dict[tuple[str, int, str], str] = {}
    categories: dict[str, dict[tuple[str, int, str], list[PhysicalAccess]]] = {}
    depth_mismatches = 0
    for access in accesses:
        if access.source == "L":
            continue
        identity = access.identity
        category = f"{access.node}/depth_{depth_bucket(access.depth, bucket_width)}"
        previous = category_by_identity.setdefault(identity, category)
        if previous != category:
            depth_mismatches += 1
            continue
        categories.setdefault(category, {}).setdefault(identity, []).append(access)
    if depth_mismatches:
        raise ValueError(
            f"{depth_mismatches} physical identities crossed depth categories"
        )
    for objects in categories.values():
        for object_accesses in objects.values():
            object_accesses.sort(key=lambda item: item.plan_s)
    return categories, {
        "category_count": len(categories),
        "physical_objects": len(category_by_identity),
        "local_ssd_lookup_opportunities": sum(
            len(item) for objects in categories.values() for item in objects.values()
        ),
        "identity_depth_category_mismatches": depth_mismatches,
        "categories_by_node": dict(
            sorted(Counter(category.split("/", 1)[0] for category in categories).items())
        ),
    }


def close_interval(
    interval_start: float | None,
    expiry: float,
    end_s: float,
) -> float:
    if interval_start is None:
        return 0.0
    return max(0.0, min(expiry, end_s) - interval_start)


def simulate_object(
    times: list[float],
    *,
    policy: str,
    ttl_s: float,
    window_start_s: float,
    window_end_s: float,
    value_bytes: int,
) -> dict[str, float]:
    if not times:
        return {
            "reads": 0.0,
            "misses": 0.0,
            "hits": 0.0,
            "writes": 0.0,
            "writes_bytes": 0.0,
            "cache_byte_seconds": 0.0,
        }

    resident = False
    interval_start: float | None = None
    expiry = -math.inf
    last_read: float | None = None
    hits = 0
    misses = 0
    writes = 0
    resident_seconds = 0.0

    if policy == BOUND_POLICY:
        write_s = max(window_start_s, times[0] - 1e-6)
        resident = True
        interval_start = write_s
        expiry = window_end_s if math.isinf(ttl_s) else write_s + ttl_s
        writes += 1

    for timestamp_s in times:
        if resident and timestamp_s > expiry:
            resident_seconds += close_interval(interval_start, expiry, window_end_s)
            resident = False
            interval_start = None

        if resident:
            hits += 1
            expiry = window_end_s if math.isinf(ttl_s) else timestamp_s + ttl_s
        else:
            misses += 1
            admit = False
            if policy in {"admit_on_miss", "admit_on_write_observed_lower", BOUND_POLICY}:
                admit = True
            elif policy == "admit_on_second_miss":
                admit = (
                    last_read is not None
                    and (math.isinf(ttl_s) or timestamp_s - last_read <= ttl_s)
                )
            elif policy != "never_admit":
                raise ValueError(f"unsupported policy: {policy}")
            if admit:
                resident = True
                interval_start = timestamp_s
                expiry = window_end_s if math.isinf(ttl_s) else timestamp_s + ttl_s
                writes += 1
        last_read = timestamp_s

    if resident:
        resident_seconds += close_interval(interval_start, expiry, window_end_s)
    return {
        "reads": float(len(times)),
        "misses": float(misses),
        "hits": float(hits),
        "writes": float(writes),
        "writes_bytes": float(writes * value_bytes),
        "cache_byte_seconds": float(resident_seconds * value_bytes),
    }


def finalize_metrics(metrics: dict[str, float], duration_s: float) -> dict[str, Any]:
    reads = metrics["reads"]
    writes_bytes = metrics["writes_bytes"]
    hits = metrics["hits"]
    result: dict[str, Any] = dict(metrics)
    for name in ("reads", "misses", "hits", "writes"):
        rounded = round(result[name])
        result[name] = int(rounded) if abs(result[name] - rounded) < 1e-9 else result[name]
    result.update(
        miss_ratio=(metrics["misses"] / reads if reads else 0.0),
        hit_ratio=(hits / reads if reads else 0.0),
        average_occupancy_gib=(
            metrics["cache_byte_seconds"] / duration_s / GIB if duration_s else 0.0
        ),
        writes_gib=writes_bytes / GIB,
        useful_reuse_density=(hits * 1.0 / metrics["writes"] if metrics["writes"] else None),
    )
    return result


def simulate_categories(
    categories: dict[str, dict[tuple[str, int, str], list[PhysicalAccess]]],
    *,
    ttl_s: float,
    window_start_s: float,
    window_end_s: float,
    value_bytes: int,
) -> dict[str, dict[str, dict[str, Any]]]:
    duration_s = window_end_s - window_start_s
    output: dict[str, dict[str, dict[str, Any]]] = {}
    for category, objects in sorted(categories.items()):
        policy_metrics: dict[str, dict[str, Any]] = {}
        for policy in (*POLICIES, BOUND_POLICY):
            totals: defaultdict[str, float] = defaultdict(float)
            for object_accesses in objects.values():
                object_metrics = simulate_object(
                    [access.plan_s for access in object_accesses],
                    policy=policy,
                    ttl_s=ttl_s,
                    window_start_s=window_start_s,
                    window_end_s=window_end_s,
                    value_bytes=value_bytes,
                )
                for name, value in object_metrics.items():
                    totals[name] += value
            policy_metrics[policy] = finalize_metrics(dict(totals), duration_s)
        output[category] = policy_metrics
    return output


def aggregate_policy(
    categories: dict[str, dict[str, dict[str, Any]]],
    policy: str,
    duration_s: float,
) -> dict[str, Any]:
    totals: defaultdict[str, float] = defaultdict(float)
    for policy_metrics in categories.values():
        metrics = policy_metrics[policy]
        for name in (
            "reads",
            "misses",
            "hits",
            "writes",
            "writes_bytes",
            "cache_byte_seconds",
        ):
            totals[name] += float(metrics[name])
    return finalize_metrics(dict(totals), duration_s)


def lower_convex_hull(points: list[PolicyPoint]) -> list[PolicyPoint]:
    """Return the non-dominated lower hull in (write bytes, misses)."""

    by_x: dict[float, PolicyPoint] = {}
    for point in points:
        previous = by_x.get(point.writes_bytes)
        if previous is None or (
            point.misses,
            point.cache_byte_seconds,
            point.policy,
        ) < (
            previous.misses,
            previous.cache_byte_seconds,
            previous.policy,
        ):
            by_x[point.writes_bytes] = point

    non_dominated: list[PolicyPoint] = []
    best_misses = math.inf
    for point in sorted(by_x.values(), key=lambda item: item.writes_bytes):
        if point.misses < best_misses - 1e-12:
            non_dominated.append(point)
            best_misses = point.misses

    hull: list[PolicyPoint] = []
    for point in non_dominated:
        while len(hull) >= 2:
            first, second = hull[-2], hull[-1]
            cross = (
                (second.writes_bytes - first.writes_bytes)
                * (point.misses - second.misses)
                - (second.misses - first.misses)
                * (point.writes_bytes - second.writes_bytes)
            )
            if cross > 1e-12:
                break
            hull.pop()
        hull.append(point)
    return hull


def point_from_metrics(policy: str, metrics: dict[str, Any]) -> PolicyPoint:
    return PolicyPoint(
        policy=policy,
        writes=float(metrics["writes"]),
        writes_bytes=float(metrics["writes_bytes"]),
        misses=float(metrics["misses"]),
        hits=float(metrics["hits"]),
        cache_byte_seconds=float(metrics["cache_byte_seconds"]),
        reads=float(metrics["reads"]),
    )


def optimize_one_node(
    category_metrics: dict[str, dict[str, dict[str, Any]]],
    *,
    node: str,
    budget_bytes: float,
    duration_s: float,
) -> dict[str, Any]:
    hulls: dict[str, list[PolicyPoint]] = {}
    selections: dict[str, dict[str, float]] = {}
    totals: defaultdict[str, float] = defaultdict(float)
    segments: list[tuple[float, str, int, PolicyPoint, PolicyPoint]] = []

    for category, policy_metrics in sorted(category_metrics.items()):
        if not category.startswith(f"{node}/"):
            continue
        points = [
            point_from_metrics(policy, policy_metrics[policy])
            for policy in POLICIES
        ]
        hull = lower_convex_hull(points)
        if not hull:
            continue
        hulls[category] = hull
        base = hull[0]
        selections[category] = {base.policy: 1.0}
        totals["writes"] += base.writes
        totals["writes_bytes"] += base.writes_bytes
        totals["misses"] += base.misses
        totals["hits"] += base.hits
        totals["cache_byte_seconds"] += base.cache_byte_seconds
        totals["reads"] += base.reads
        for index, (left, right) in enumerate(zip(hull, hull[1:])):
            delta_bytes = right.writes_bytes - left.writes_bytes
            miss_reduction = left.misses - right.misses
            if delta_bytes <= 0 or miss_reduction <= 0:
                continue
            benefit = miss_reduction / delta_bytes
            segments.append((benefit, category, index, left, right))

    remaining = max(0.0, budget_bytes - totals["writes_bytes"])
    chosen_segments: list[dict[str, Any]] = []
    for benefit, category, index, left, right in sorted(
        segments, key=lambda item: (-item[0], item[1], item[2])
    ):
        delta_bytes = right.writes_bytes - left.writes_bytes
        if remaining <= 1e-9:
            break
        fraction = min(1.0, remaining / delta_bytes)
        for name in (
            "writes",
            "writes_bytes",
            "misses",
            "hits",
            "cache_byte_seconds",
            "reads",
        ):
            left_value = getattr(left, name)
            right_value = getattr(right, name)
            totals[name] += fraction * (right_value - left_value)
        selections[category] = (
            {right.policy: 1.0}
            if fraction >= 1.0 - 1e-12
            else {left.policy: 1.0 - fraction, right.policy: fraction}
        )
        chosen_segments.append(
            {
                "category": category,
                "from": left.policy,
                "to": right.policy,
                "fraction": fraction,
                "misses_saved_per_gib_written": benefit * GIB,
            }
        )
        remaining -= fraction * delta_bytes
        if fraction < 1.0 - 1e-12:
            break

    traffic_mix: defaultdict[str, float] = defaultdict(float)
    for category, mix in selections.items():
        reads = float(next(iter(category_metrics[category].values()))["reads"])
        for policy, fraction in mix.items():
            traffic_mix[policy] += reads * fraction
    total_reads = totals["reads"]
    return {
        **finalize_metrics(dict(totals), duration_s),
        "node": node,
        "budget_bytes": budget_bytes,
        "budget_gib": budget_bytes / GIB,
        "unused_budget_gib": max(0.0, remaining) / GIB,
        "category_hulls": {
            category: [asdict(point) for point in hull]
            for category, hull in hulls.items()
        },
        "category_policy_mix": selections,
        "traffic_policy_fraction": {
            policy: value / total_reads if total_reads else 0.0
            for policy, value in sorted(traffic_mix.items())
        },
        "chosen_segments": chosen_segments,
    }


def optimize_budgets(
    category_metrics: dict[str, dict[str, dict[str, Any]]],
    *,
    nodes: list[str],
    budgets_by_node: dict[str, float],
    duration_s: float,
    capacity_gib_per_owner: float,
) -> dict[str, Any]:
    if set(budgets_by_node) != set(nodes):
        raise ValueError(
            f"budget nodes mismatch: budgets={sorted(budgets_by_node)} nodes={nodes}"
        )
    node_results = [
        optimize_one_node(
            category_metrics,
            node=node,
            budget_bytes=budgets_by_node[node],
            duration_s=duration_s,
        )
        for node in nodes
    ]
    totals: defaultdict[str, float] = defaultdict(float)
    for result in node_results:
        for name in (
            "reads",
            "misses",
            "hits",
            "writes",
            "writes_bytes",
            "cache_byte_seconds",
        ):
            totals[name] += float(result[name])
    aggregate = finalize_metrics(dict(totals), duration_s)
    aggregate.update(
        budget_gib_by_node={
            node: budgets_by_node[node] / GIB for node in nodes
        },
        theoretical_budget_gib_total=sum(budgets_by_node.values()) / GIB,
        ssd_capacity_gib_per_owner=capacity_gib_per_owner,
        average_capacity_safe=all(
            result["average_occupancy_gib"] <= capacity_gib_per_owner
            for result in node_results
        ),
        nodes=node_results,
    )
    return aggregate


def optimize_rate(
    category_metrics: dict[str, dict[str, dict[str, Any]]],
    *,
    nodes: list[str],
    rate_mib_s: float,
    burst_bytes: int,
    duration_s: float,
    capacity_gib_per_owner: float,
) -> dict[str, Any]:
    budget_each = rate_mib_s * MIB * duration_s + burst_bytes
    aggregate = optimize_budgets(
        category_metrics,
        nodes=nodes,
        budgets_by_node={node: budget_each for node in nodes},
        duration_s=duration_s,
        capacity_gib_per_owner=capacity_gib_per_owner,
    )
    aggregate["configured_rate_mib_s_per_owner"] = rate_mib_s
    return aggregate


def reuse_audit(
    categories: dict[str, dict[tuple[str, int, str], list[PhysicalAccess]]]
) -> dict[str, Any]:
    counts: list[int] = []
    intervals: list[float] = []
    source_counts: Counter[str] = Counter()
    for objects in categories.values():
        for accesses in objects.values():
            counts.append(len(accesses))
            source_counts.update(access.source for access in accesses)
            intervals.extend(
                current.plan_s - previous.plan_s
                for previous, current in zip(accesses, accesses[1:])
            )
    object_count = len(counts)
    repeated = [count for count in counts if count >= 2]
    return {
        "objects": object_count,
        "lookup_opportunities": sum(counts),
        "objects_accessed_once": sum(count == 1 for count in counts),
        "objects_accessed_once_ratio": (
            sum(count == 1 for count in counts) / object_count if object_count else 0.0
        ),
        "repeated_objects": len(repeated),
        "repeated_objects_with_exactly_two_accesses": sum(count == 2 for count in repeated),
        "exactly_two_ratio_among_repeated": (
            sum(count == 2 for count in repeated) / len(repeated) if repeated else 0.0
        ),
        "accesses_per_object": distribution(float(count) for count in counts),
        "reuse_interval_s": distribution(intervals),
        "lookup_sources": dict(sorted(source_counts.items())),
    }


def markdown_report(result: dict[str, Any]) -> str:
    audit = result["audit"]
    reuse = result["reuse"]
    lines = [
        f"# {result['trace_name']} CacheSack-style replay",
        "",
        f"Generated: {result['generated_at']}",
        "",
        "## Trace gate",
        "",
        "| Check | Value |",
        "|---|---:|",
        f"| mapped requests | {audit['request_metrics']['mapped_requests']} |",
        f"| physical lineage events | {audit['lineage']['physical_events']} |",
        f"| TP key/depth mismatches | {audit['lineage']['tp_key_depth_mismatches']} |",
        f"| TP source mismatches (kept per rank) | {audit['lineage']['tp_source_mismatches']} |",
        f"| unmapped request ids | {audit['lineage']['unmapped_request_ids']} |",
        f"| deduplicated SSD lookup opportunities | {reuse['lookup_opportunities']} |",
        "",
        "## Reuse shape below owner-local DRAM",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| physical objects | {reuse['objects']} |",
        f"| one-lookup objects | {reuse['objects_accessed_once']} ({reuse['objects_accessed_once_ratio']:.2%}) |",
        f"| repeated objects | {reuse['repeated_objects']} |",
        f"| exactly-two among repeated | {reuse['repeated_objects_with_exactly_two_accesses']} ({reuse['exactly_two_ratio_among_repeated']:.2%}) |",
        f"| reuse interval p50 / p90 / p99 | {reuse['reuse_interval_s']['p50']:.3f} / {reuse['reuse_interval_s']['p90']:.3f} / {reuse['reuse_interval_s']['p99']:.3f} s |",
        "",
        "## Static policy surface",
        "",
        "| TTL (s) | Policy | Misses | Hit ratio | Writes GiB | Avg occupancy GiB |",
        "|---:|---|---:|---:|---:|---:|",
    ]
    for ttl, policies in result["static_policy_surface"].items():
        for policy, metrics in policies.items():
            if policy == BOUND_POLICY:
                continue
            lines.append(
                f"| {ttl} | {policy} | {metrics['misses']} | "
                f"{metrics['hit_ratio']:.2%} | {metrics['writes_gib']:.3f} | "
                f"{metrics['average_occupancy_gib']:.3f} |"
            )
    lines.extend(
        [
            "",
            "`admit_on_write_observed_lower`与`admit_on_miss`相同，是当前日志可辨识性的结果；不能解释为两种策略真实等价。",
            "",
            "## Fractional greedy result",
            "",
            "| Rate MiB/s/owner | Best TTL (s) | Misses | Hit ratio | Writes GiB | Avg occupancy GiB |",
            "|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for rate, best in result["best_by_rate"].items():
        lines.append(
            f"| {rate} | {best['ttl_s']} | {best['misses']:.3f} | "
            f"{best['hit_ratio']:.2%} | {best['writes_gib']:.3f} | "
            f"{best['average_occupancy_gib']:.3f} |"
        )
    observed = result.get("best_observed_budget")
    if observed is not None:
        lines.extend(
            [
                "",
                "按实测每个 owner 的落盘字节预算重放：",
                "",
                "| Budget | Best TTL (s) | Misses | Hit ratio | Writes GiB | Useful hits/write |",
                "|---|---:|---:|---:|---:|---:|",
                f"| observed per-owner | {observed['ttl_s']} | {observed['misses']:.3f} | "
                f"{observed['hit_ratio']:.2%} | {observed['writes_gib']:.3f} | "
                f"{observed['useful_reuse_density']:.3f} |",
            ]
        )
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "- Miss means one physical KV lookup that would fall through requester-local SSD; it is not a QPS prediction.",
            "- SSD-off lineage is the primary demand trace. `L` is excluded because owner-local DRAM serves it before SSD.",
            "- Retry attempts are collapsed by external request, requester, TP rank and KV key.",
            "- The optimizer uses known per-owner write budgets. Google's flash-write cost coefficient is confidential.",
            "- Exact AdmitOnWrite and the original content mask require a new normal-Put shadow trace before behavior can be enabled.",
            "",
        ]
    )
    return "\n".join(lines)


def self_test() -> None:
    size = 100
    common = dict(
        ttl_s=2.0,
        window_start_s=0.0,
        window_end_s=12.0,
        value_bytes=size,
    )
    never = simulate_object([0.0, 1.0, 10.0], policy="never_admit", **common)
    on_miss = simulate_object([0.0, 1.0, 10.0], policy="admit_on_miss", **common)
    second = simulate_object(
        [0.0, 1.0, 10.0], policy="admit_on_second_miss", **common
    )
    assert never["misses"] == 3 and never["writes"] == 0
    assert on_miss["misses"] == 2 and on_miss["hits"] == 1
    assert on_miss["writes"] == 2
    assert second["misses"] == 3 and second["writes"] == 1
    points = [
        PolicyPoint("never", 0.0, 0.0, 10.0, 0.0, 0.0, 10.0),
        PolicyPoint("bad_middle", 1.0, 1.0, 9.0, 1.0, 1.0, 10.0),
        PolicyPoint("best", 2.0, 2.0, 0.0, 10.0, 2.0, 10.0),
    ]
    assert [point.policy for point in lower_convex_hull(points)] == ["never", "best"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-name", default="e44_trace")
    parser.add_argument("--lineage", action="append", default=[])
    parser.add_argument("--request-metrics", type=Path, action="append", default=[])
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--output-md", type=Path)
    parser.add_argument("--generated-at", default="2026-07-31 HKT")
    parser.add_argument("--expected-requests", type=int, default=2304)
    parser.add_argument("--tp-size", type=int, default=2)
    parser.add_argument("--value-bytes", type=int, default=4_718_592)
    parser.add_argument("--depth-bucket-pages", type=int, default=32)
    parser.add_argument("--ttl-s", type=parse_ttl, action="append")
    parser.add_argument("--rate-mib-s", type=float, action="append")
    parser.add_argument(
        "--observed-budget-bytes", type=parse_node_budget, action="append", default=[]
    )
    parser.add_argument("--burst-bytes", type=int, default=61_341_696)
    parser.add_argument("--ssd-capacity-gib-per-owner", type=float, default=1536.0)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        print("self-test passed")
        if not args.lineage:
            return 0
    required = {
        "--lineage": args.lineage,
        "--request-metrics": args.request_metrics,
        "--output-json": args.output_json,
        "--output-md": args.output_md,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        parser.error(f"missing required arguments: {', '.join(missing)}")
    if args.depth_bucket_pages <= 0 or args.value_bytes <= 0:
        parser.error("depth bucket and value bytes must be positive")

    ttl_grid = sorted(
        set(
            args.ttl_s
            or [0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 64.0, 128.0, 256.0, math.inf]
        )
    )
    rate_grid = sorted(set(args.rate_mib_s or [24.0, 64.0, 128.0]))
    if any(rate <= 0 for rate in rate_grid):
        parser.error("write rates must be positive")

    requests, request_audit = load_request_metrics(args.request_metrics)
    if len(requests) != args.expected_requests:
        raise ValueError(
            f"request count mismatch: got={len(requests)} expected={args.expected_requests}"
        )
    events = load_events(args.lineage)
    logical, lineage_audit = logical_lineage(events, requests, args.tp_size)
    _chains, session_audit = build_session_chains(logical, requests)
    if session_audit["missing_lineage_groups"]:
        raise ValueError(
            f"request groups without lineage: {session_audit['missing_lineage_groups']}"
        )
    physical, physical_audit = build_physical_accesses(events, requests)
    categories, category_audit = build_categories(
        physical, bucket_width=args.depth_bucket_pages
    )

    window_start_s = min(meta.received_s for meta in requests.values())
    window_end_s = max(meta.finished_s for meta in requests.values())
    duration_s = window_end_s - window_start_s
    if duration_s <= 0:
        raise ValueError(f"invalid request window duration: {duration_s}")
    nodes = sorted({access.node for access in physical})
    if len(nodes) != 2:
        raise ValueError(f"expected two requester owners, got {nodes}")
    observed_budgets = dict(args.observed_budget_bytes)
    if len(observed_budgets) != len(args.observed_budget_bytes):
        raise ValueError("duplicate --observed-budget-bytes node")
    if observed_budgets and set(observed_budgets) != set(nodes):
        raise ValueError(
            f"observed budget nodes mismatch: budgets={sorted(observed_budgets)} nodes={nodes}"
        )

    static_surface: dict[str, dict[str, dict[str, Any]]] = {}
    optimized_surface: dict[str, dict[str, dict[str, Any]]] = {}
    observed_budget_surface: dict[str, dict[str, Any]] = {}
    detailed_categories: dict[str, dict[str, dict[str, dict[str, Any]]]] = {}
    for ttl_s in ttl_grid:
        label = ttl_label(ttl_s)
        category_metrics = simulate_categories(
            categories,
            ttl_s=ttl_s,
            window_start_s=window_start_s,
            window_end_s=window_end_s,
            value_bytes=args.value_bytes,
        )
        detailed_categories[label] = category_metrics
        static_surface[label] = {
            policy: aggregate_policy(category_metrics, policy, duration_s)
            for policy in (*POLICIES, BOUND_POLICY)
        }
        optimized_surface[label] = {
            f"{rate:g}": optimize_rate(
                category_metrics,
                nodes=nodes,
                rate_mib_s=rate,
                burst_bytes=args.burst_bytes,
                duration_s=duration_s,
                capacity_gib_per_owner=args.ssd_capacity_gib_per_owner,
            )
            for rate in rate_grid
        }
        if observed_budgets:
            observed_budget_surface[label] = optimize_budgets(
                category_metrics,
                nodes=nodes,
                budgets_by_node=observed_budgets,
                duration_s=duration_s,
                capacity_gib_per_owner=args.ssd_capacity_gib_per_owner,
            )

    best_by_rate: dict[str, dict[str, Any]] = {}
    for rate in rate_grid:
        rate_label = f"{rate:g}"
        ttl, metrics = min(
            (
                (ttl, optimized_surface[ttl][rate_label])
                for ttl in optimized_surface
            ),
            key=lambda item: (
                float(item[1]["misses"]),
                float(item[1]["writes_bytes"]),
                float(item[1]["cache_byte_seconds"]),
            ),
        )
        best_by_rate[rate_label] = {"ttl_s": ttl, **metrics}

    best_observed_budget: dict[str, Any] | None = None
    if observed_budget_surface:
        ttl, metrics = min(
            observed_budget_surface.items(),
            key=lambda item: (
                float(item[1]["misses"]),
                float(item[1]["writes_bytes"]),
                float(item[1]["cache_byte_seconds"]),
            ),
        )
        best_observed_budget = {"ttl_s": ttl, **metrics}

    inputs = []
    for path in [*lineage_files(args.lineage), *args.request_metrics]:
        inputs.append(
            {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)}
        )
    result = {
        "schema": "e44_cachesack_admission_replay_v1",
        "trace_name": args.trace_name,
        "generated_at": args.generated_at,
        "inputs": inputs,
        "configuration": {
            "tp_size": args.tp_size,
            "value_bytes_per_tp_rank": args.value_bytes,
            "depth_bucket_pages": args.depth_bucket_pages,
            "ttl_grid_s": [ttl_label(ttl) for ttl in ttl_grid],
            "rate_grid_mib_s_per_owner": rate_grid,
            "observed_budget_bytes_by_node": observed_budgets,
            "burst_bytes_per_owner": args.burst_bytes,
            "ssd_capacity_gib_per_owner": args.ssd_capacity_gib_per_owner,
            "request_window_start_s": window_start_s,
            "request_window_end_s": window_end_s,
            "request_window_duration_s": duration_s,
            "nodes": nodes,
        },
        "audit": {
            "request_metrics": request_audit,
            "lineage": lineage_audit,
            "sessions": session_audit,
            "physical_dedup": physical_audit,
            "categories": category_audit,
        },
        "reuse": reuse_audit(categories),
        "static_policy_surface": static_surface,
        "optimized_surface": optimized_surface,
        "best_by_rate": best_by_rate,
        "observed_budget_surface": observed_budget_surface,
        "best_observed_budget": best_observed_budget,
        "category_metrics": detailed_categories,
        "limitations": [
            "normal Put key/timestamp identity is absent, so exact AdmitOnWrite is not identifiable",
            "the original make_replica_task_mask is absent from lineage",
            "the replay models physical fallback lookups and does not predict QPS",
            "TTL assumes immediate admission and does not model persist gate queueing or I/O latency",
            "the optimizer constrains known Fluxon write bytes instead of Google's confidential write-cost coefficient",
        ],
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    args.output_md.write_text(markdown_report(result), encoding="utf-8")
    print(json.dumps({
        "trace": args.trace_name,
        "requests": len(requests),
        "lookup_opportunities": result["reuse"]["lookup_opportunities"],
        "best_by_rate": {
            rate: {
                "ttl_s": metrics["ttl_s"],
                "misses": metrics["misses"],
                "writes_gib": metrics["writes_gib"],
                "hit_ratio": metrics["hit_ratio"],
            }
            for rate, metrics in best_by_rate.items()
        },
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
