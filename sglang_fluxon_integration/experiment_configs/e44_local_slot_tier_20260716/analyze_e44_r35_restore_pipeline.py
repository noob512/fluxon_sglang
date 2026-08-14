#!/usr/bin/env python3
"""Analyze r35 Fluxon hostless restore submission and completion scaling.

The SGLang log has one scheduler stream and one background DMA executor per TP
rank, but it does not print a shared batch id on all three records.  This tool
therefore joins submitted/background records by their per-rank FIFO order, then
joins operation completions to the rounded background_submit_cpu_ms carried by
the operation.  It fails closed when counts, pages, tokens, layers, or operation
completions do not reconcile.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


SUBMITTED_MARKER = "Fluxon layerwise restore submitted:"
BACKGROUND_MARKER = "Fluxon background layer DMA submit complete:"
COMPLETE_MARKER = "Fluxon layerwise restore complete:"
RANK_PATTERN = re.compile(r"\[([^]]+)\s+TP(\d+)]")
FIELD_PATTERN = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)=([^\s]+)")
INTEGER_PATTERN = re.compile(r"^-?\d+$")
FLOAT_PATTERN = re.compile(r"^-?(?:\d+\.\d+|\d+\.?)(?:[eE][+-]?\d+)?$")
BACKGROUND_TIME_TOLERANCE_MS = 0.00051


def parse_value(raw: str) -> Any:
    if raw == "None":
        return None
    if raw == "True":
        return True
    if raw == "False":
        return False
    if INTEGER_PATTERN.fullmatch(raw):
        return int(raw)
    if FLOAT_PATTERN.fullmatch(raw):
        return float(raw)
    return raw.rstrip(",")


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
        "min": min(samples),
        "max": max(samples),
    }


def pearson(xs: Iterable[int | float], ys: Iterable[int | float]) -> float | None:
    x_values = [float(value) for value in xs]
    y_values = [float(value) for value in ys]
    if len(x_values) != len(y_values) or len(x_values) < 2:
        return None
    x_mean = sum(x_values) / len(x_values)
    y_mean = sum(y_values) / len(y_values)
    numerator = sum(
        (x_value - x_mean) * (y_value - y_mean)
        for x_value, y_value in zip(x_values, y_values)
    )
    x_square = sum((value - x_mean) ** 2 for value in x_values)
    y_square = sum((value - y_mean) ** 2 for value in y_values)
    if x_square == 0 or y_square == 0:
        return None
    return numerator / math.sqrt(x_square * y_square)


def linear_fit(xs: Iterable[int | float], ys: Iterable[int | float]) -> dict[str, Any]:
    x_values = [float(value) for value in xs]
    y_values = [float(value) for value in ys]
    if len(x_values) != len(y_values) or len(x_values) < 2:
        return {"count": len(x_values)}
    x_mean = sum(x_values) / len(x_values)
    y_mean = sum(y_values) / len(y_values)
    denominator = sum((value - x_mean) ** 2 for value in x_values)
    if denominator == 0:
        return {"count": len(x_values), "constant_x": True}
    slope = sum(
        (x_value - x_mean) * (y_value - y_mean)
        for x_value, y_value in zip(x_values, y_values)
    ) / denominator
    intercept = y_mean - slope * x_mean
    predicted = [intercept + slope * value for value in x_values]
    residual_square = sum(
        (actual - estimate) ** 2
        for actual, estimate in zip(y_values, predicted)
    )
    total_square = sum((value - y_mean) ** 2 for value in y_values)
    return {
        "count": len(x_values),
        "intercept": intercept,
        "slope": slope,
        "r_squared": None if total_square == 0 else 1.0 - residual_square / total_square,
    }


def parse_record(
    node: str,
    path: Path,
    line_number: int,
    line: str,
    marker: str,
) -> dict[str, Any]:
    rank_match = RANK_PATTERN.search(line)
    if rank_match is None:
        raise ValueError(f"{path}:{line_number}: missing TP rank for {marker}")
    fields = {
        key: parse_value(value)
        for key, value in FIELD_PATTERN.findall(line.split(marker, 1)[1])
    }
    return {
        "node": node,
        "path": str(path),
        "line": line_number,
        "timestamp": rank_match.group(1),
        "tp_rank": int(rank_match.group(2)),
        **fields,
    }


def require_fields(
    record: dict[str, Any],
    fields: set[str],
    record_kind: str,
) -> None:
    missing = fields - record.keys()
    if missing:
        raise ValueError(
            f"{record['path']}:{record['line']}: {record_kind} missing fields "
            f"{sorted(missing)}"
        )


def load_log(node: str, path: Path) -> dict[int, dict[str, list[dict[str, Any]]]]:
    by_rank: dict[int, dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: {"submitted": [], "background": [], "complete": []}
    )
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for line_number, line in enumerate(stream, 1):
            if SUBMITTED_MARKER in line:
                record = parse_record(node, path, line_number, line, SUBMITTED_MARKER)
                require_fields(
                    record,
                    {
                        "producer",
                        "operations",
                        "tokens",
                        "layers",
                        "pages",
                        "descriptor_cpu_ms",
                        "dispatch_cpu_ms",
                        "background",
                    },
                    "submitted",
                )
                by_rank[record["tp_rank"]]["submitted"].append(record)
            elif BACKGROUND_MARKER in line:
                record = parse_record(node, path, line_number, line, BACKGROUND_MARKER)
                require_fields(
                    record,
                    {
                        "operations",
                        "tokens",
                        "layers",
                        "pages",
                        "submitted_layers",
                        "submit_cpu_ms",
                        "error",
                    },
                    "background",
                )
                by_rank[record["tp_rank"]]["background"].append(record)
            elif COMPLETE_MARKER in line:
                record = parse_record(node, path, line_number, line, COMPLETE_MARKER)
                require_fields(
                    record,
                    {"node", "tokens", "duration_ms", "background_submit_cpu_ms"},
                    "complete",
                )
                # The operation's numeric node id shadows the cluster node label.
                record["radix_node"] = record.pop("node")
                record["cluster_node"] = node
                by_rank[record["tp_rank"]]["complete"].append(record)
    return by_rank


def join_rank_records(
    node: str,
    rank: int,
    records: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    submitted = records["submitted"]
    background = records["background"]
    completions = records["complete"]
    if len(submitted) != len(background):
        raise ValueError(
            f"{node}/TP{rank}: submitted/background mismatch "
            f"{len(submitted)} != {len(background)}"
        )

    batches: list[dict[str, Any]] = []
    fields_to_match = ("operations", "tokens", "layers", "pages")
    for sequence, (submit, finish) in enumerate(zip(submitted, background), 1):
        mismatches = {
            field: (submit[field], finish[field])
            for field in fields_to_match
            if submit[field] != finish[field]
        }
        if mismatches:
            raise ValueError(
                f"{node}/TP{rank}/batch{sequence}: FIFO join mismatch {mismatches}"
            )
        if submit["background"] is not True:
            raise ValueError(f"{node}/TP{rank}/batch{sequence}: not background DMA")
        if finish["error"] is not None:
            raise ValueError(
                f"{node}/TP{rank}/batch{sequence}: background error={finish['error']}"
            )
        if finish["submitted_layers"] != finish["layers"]:
            raise ValueError(
                f"{node}/TP{rank}/batch{sequence}: incomplete layer submission "
                f"{finish['submitted_layers']}/{finish['layers']}"
            )
        chunk_fields = {
            "descriptors_per_layer",
            "dma_calls",
            "max_descriptors_per_call",
        }
        present_chunk_fields = chunk_fields & finish.keys()
        if present_chunk_fields and present_chunk_fields != chunk_fields:
            raise ValueError(
                f"{node}/TP{rank}/batch{sequence}: partial chunk metrics "
                f"{sorted(present_chunk_fields)}"
            )
        if present_chunk_fields:
            descriptors_per_layer = int(finish["descriptors_per_layer"])
            descriptor_cap = int(finish["max_descriptors_per_call"])
            calls_per_layer = (
                1
                if descriptor_cap <= 0 or descriptors_per_layer <= descriptor_cap
                else math.ceil(descriptors_per_layer / descriptor_cap)
            )
            expected_dma_calls = int(finish["layers"]) * calls_per_layer
            if int(finish["dma_calls"]) != expected_dma_calls:
                raise ValueError(
                    f"{node}/TP{rank}/batch{sequence}: dma_calls "
                    f"{finish['dma_calls']} != expected {expected_dma_calls}"
                )
        batches.append(
            {
                "node": node,
                "tp_rank": rank,
                "sequence": sequence,
                "submit_line": submit["line"],
                "background_line": finish["line"],
                "producer": submit["producer"],
                "operations": submit["operations"],
                "tokens": submit["tokens"],
                "layers": submit["layers"],
                "pages": submit["pages"],
                "descriptor_cpu_ms": submit["descriptor_cpu_ms"],
                "dispatch_cpu_ms": submit["dispatch_cpu_ms"],
                "background_submit_cpu_ms": finish["submit_cpu_ms"],
                "descriptors_per_layer": finish.get("descriptors_per_layer"),
                "dma_calls": finish.get("dma_calls"),
                "max_descriptors_per_call": finish.get(
                    "max_descriptors_per_call"
                ),
                "operation_completions": [],
            }
        )

    for completion in completions:
        candidates = [
            batch
            for batch in batches
            if batch["background_line"] < completion["line"]
            and len(batch["operation_completions"]) < batch["operations"]
            and abs(
                float(batch["background_submit_cpu_ms"])
                - float(completion["background_submit_cpu_ms"])
            )
            < BACKGROUND_TIME_TOLERANCE_MS
        ]
        if not candidates:
            raise ValueError(
                f"{completion['path']}:{completion['line']}: no batch for "
                f"TP{rank} background_submit_cpu_ms="
                f"{completion['background_submit_cpu_ms']}"
            )
        # Rounded submit times can collide. FIFO is the only stable identity in
        # that case because each TP rank owns a single background executor.
        batch = min(candidates, key=lambda item: item["sequence"])
        batch["operation_completions"].append(
            {
                "line": completion["line"],
                "radix_node": completion["radix_node"],
                "tokens": completion["tokens"],
                "duration_ms": completion["duration_ms"],
            }
        )

    for batch in batches:
        operation_completions = batch["operation_completions"]
        if len(operation_completions) != batch["operations"]:
            raise ValueError(
                f"{node}/TP{rank}/batch{batch['sequence']}: completion count "
                f"{len(operation_completions)} != {batch['operations']}"
            )
        completed_tokens = sum(item["tokens"] for item in operation_completions)
        if completed_tokens != batch["tokens"]:
            raise ValueError(
                f"{node}/TP{rank}/batch{batch['sequence']}: completion tokens "
                f"{completed_tokens} != {batch['tokens']}"
            )
        batch["operation_complete_mean_ms"] = sum(
            item["duration_ms"] for item in operation_completions
        ) / len(operation_completions)
        batch["operation_complete_max_ms"] = max(
            item["duration_ms"] for item in operation_completions
        )
        batch["submit_cpu_ms_per_page"] = (
            batch["background_submit_cpu_ms"] / batch["pages"]
        )
        batch["submit_cpu_ms_per_operation"] = (
            batch["background_submit_cpu_ms"] / batch["operations"]
        )
        batch["pages_per_operation"] = batch["pages"] / batch["operations"]
    return batches


def summarize_batches(batches: list[dict[str, Any]]) -> dict[str, Any]:
    operation_completions = [
        operation
        for batch in batches
        for operation in batch["operation_completions"]
    ]
    chunk_batches = [
        batch for batch in batches if batch["descriptors_per_layer"] is not None
    ]
    return {
        "batches": len(batches),
        "operations": sum(batch["operations"] for batch in batches),
        "pages": sum(batch["pages"] for batch in batches),
        "tokens": sum(batch["tokens"] for batch in batches),
        "layer_api_calls": sum(batch["layers"] for batch in batches),
        "page_descriptors_across_layers": sum(
            batch["pages"] * batch["layers"] for batch in batches
        ),
        "chunk_metrics": {
            "batches": len(chunk_batches),
            "descriptors_per_layer": stats(
                batch["descriptors_per_layer"] for batch in chunk_batches
            ),
            "dma_calls": stats(batch["dma_calls"] for batch in chunk_batches),
            "dma_calls_total": sum(batch["dma_calls"] for batch in chunk_batches),
            "max_descriptors_per_call_distribution": {
                str(key): value
                for key, value in sorted(
                    Counter(
                        batch["max_descriptors_per_call"] for batch in chunk_batches
                    ).items()
                )
            },
        },
        "operation_count_distribution": {
            str(key): value
            for key, value in sorted(Counter(batch["operations"] for batch in batches).items())
        },
        "pages_per_batch": stats(batch["pages"] for batch in batches),
        "pages_per_operation": stats(batch["pages_per_operation"] for batch in batches),
        "descriptor_cpu_ms": stats(batch["descriptor_cpu_ms"] for batch in batches),
        "dispatch_cpu_ms": stats(batch["dispatch_cpu_ms"] for batch in batches),
        "background_submit_cpu_ms": stats(
            batch["background_submit_cpu_ms"] for batch in batches
        ),
        "background_submit_cpu_ms_per_page": stats(
            batch["submit_cpu_ms_per_page"] for batch in batches
        ),
        "background_submit_cpu_ms_per_operation": stats(
            batch["submit_cpu_ms_per_operation"] for batch in batches
        ),
        "operation_complete_duration_ms": stats(
            operation["duration_ms"] for operation in operation_completions
        ),
        "batch_max_operation_complete_ms": stats(
            batch["operation_complete_max_ms"] for batch in batches
        ),
    }


def summarize_operation_group(batches: list[dict[str, Any]]) -> dict[str, Any]:
    summary = summarize_batches(batches)
    summary["observed_submit_vs_single_linear_ratio"] = None
    return summary


def page_bucket(page_count: int) -> str:
    if page_count <= 128:
        return "0001-0128"
    if page_count <= 288:
        return "0129-0288"
    if page_count <= 576:
        return "0289-0576"
    if page_count <= 864:
        return "0577-0864"
    return "0865+"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "inputs",
        nargs="+",
        help="NODE=PATH pairs, for example node0=/path/to/sglang.log",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    all_batches: list[dict[str, Any]] = []
    input_files: list[dict[str, Any]] = []
    seen_nodes: set[str] = set()
    for raw in args.inputs:
        if "=" not in raw:
            raise SystemExit(f"input must be NODE=PATH: {raw}")
        node, path_text = raw.split("=", 1)
        if node in seen_nodes:
            raise SystemExit(f"duplicate node label: {node}")
        seen_nodes.add(node)
        path = Path(path_text)
        by_rank = load_log(node, path)
        if not by_rank:
            raise ValueError(f"{path}: no restore pipeline records")
        node_batches: list[dict[str, Any]] = []
        for rank, records in sorted(by_rank.items()):
            node_batches.extend(join_rank_records(node, rank, records))
        all_batches.extend(node_batches)
        input_files.append(
            {
                "node": node,
                "path": str(path),
                "tp_ranks": sorted(by_rank),
                **summarize_batches(node_batches),
            }
        )

    by_node_rank: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    by_operation_count: dict[int, list[dict[str, Any]]] = defaultdict(list)
    by_page_bucket: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for batch in all_batches:
        by_node_rank[(batch["node"], batch["tp_rank"])].append(batch)
        by_operation_count[batch["operations"]].append(batch)
        by_page_bucket[page_bucket(batch["pages"])].append(batch)

    operation_groups = {
        str(operation_count): summarize_operation_group(batches)
        for operation_count, batches in sorted(by_operation_count.items())
    }
    single_submit_mean = operation_groups.get("1", {}).get(
        "background_submit_cpu_ms", {}
    ).get("mean")
    if single_submit_mean:
        for operation_count_text, group in operation_groups.items():
            operation_count = int(operation_count_text)
            observed_mean = group["background_submit_cpu_ms"]["mean"]
            group["observed_submit_vs_single_linear_ratio"] = (
                observed_mean / (single_submit_mean * operation_count)
            )

    background_times = [batch["background_submit_cpu_ms"] for batch in all_batches]
    result = {
        "schema": "e44_r35_restore_pipeline_summary_v1",
        "join_guards": {
            "per_rank_submitted_background_fifo_match": True,
            "submitted_background_fields_matched": [
                "operations",
                "tokens",
                "layers",
                "pages",
            ],
            "all_background_errors_none": True,
            "all_layers_submitted": True,
            "chunk_metrics_valid_when_present": True,
            "operation_completion_counts_and_tokens_matched": True,
            "background_time_join_tolerance_ms": BACKGROUND_TIME_TOLERANCE_MS,
        },
        "inputs": input_files,
        "overall": summarize_batches(all_batches),
        "by_node_rank": {
            f"{node}/TP{rank}": summarize_batches(batches)
            for (node, rank), batches in sorted(by_node_rank.items())
        },
        "by_operation_count": operation_groups,
        "by_page_bucket": {
            bucket: summarize_batches(batches)
            for bucket, batches in sorted(by_page_bucket.items())
        },
        "correlations": {
            "operations_vs_background_submit_cpu_ms": pearson(
                (batch["operations"] for batch in all_batches), background_times
            ),
            "pages_vs_background_submit_cpu_ms": pearson(
                (batch["pages"] for batch in all_batches), background_times
            ),
            "tokens_vs_background_submit_cpu_ms": pearson(
                (batch["tokens"] for batch in all_batches), background_times
            ),
            "descriptor_cpu_ms_vs_background_submit_cpu_ms": pearson(
                (batch["descriptor_cpu_ms"] for batch in all_batches),
                background_times,
            ),
            "dispatch_cpu_ms_vs_background_submit_cpu_ms": pearson(
                (batch["dispatch_cpu_ms"] for batch in all_batches),
                background_times,
            ),
            "background_submit_cpu_ms_vs_batch_max_operation_complete_ms": pearson(
                background_times,
                (batch["operation_complete_max_ms"] for batch in all_batches),
            ),
            "operations_vs_pages": pearson(
                (batch["operations"] for batch in all_batches),
                (batch["pages"] for batch in all_batches),
            ),
        },
        "linear_fits": {
            "background_submit_cpu_ms_by_operations": linear_fit(
                (batch["operations"] for batch in all_batches), background_times
            ),
            "background_submit_cpu_ms_by_pages": linear_fit(
                (batch["pages"] for batch in all_batches), background_times
            ),
        },
        "interpretation_guards": {
            "operations_and_pages_are_nearly_collinear": True,
            "correlation_does_not_identify_cuda_api_vs_physical_copy_time": True,
            "operation_duration_includes_queue_time_from_operation_creation": True,
            "r35_is_observation_only_and_not_a_formal_performance_baseline": True,
        },
    }

    rendered = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
