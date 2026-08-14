#!/usr/bin/env python3
"""Build the frozen 4096-token realistic shared system/tool prefix."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Sequence


SCHEMA = "interactive_r34_shared_system_prefix_v1"
PROFILE = "interactive-r34-shaped-s96t24-shared-system-v1"
TARGET_TOKENS = 4096
TOKENIZER_FILES = (
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.json",
    "merges.txt",
    "chat_template.json",
)


BASE_PROMPT = """You are an engineering agent operating inside a production software workspace.
Follow the user's objective, preserve constraints from earlier turns, and use tools only when they
materially advance the task. Before changing code, inspect the relevant implementation and tests.
Preserve unrelated worktree changes. Prefer reversible operations, record exact evidence, and never
claim an experiment passed before the requested workload and validation gates complete.

For cluster experiments, keep workload identity, model, topology, capacities, and request bytes in
the run manifest. Check host identity, target GPU occupancy, ports, memory limits, and interference
before launch. Do not stop unrelated jobs. When a run ends, collect request-level results, service
metrics, capacity evidence, and cleanup evidence. Distinguish observations from estimates.

The following tool catalog is part of the stable agent contract. Tool calls use JSON objects. Paths
must be absolute, identifiers must be copied exactly, and state-changing actions require the same
scope as the user's request.
"""


TOOL_KINDS = (
    (
        "workspace_search",
        "Search repository paths and text using a read-only indexed query.",
        {"query": "string", "path": "absolute path", "max_results": "integer"},
    ),
    (
        "workspace_read",
        "Read a bounded region of a text file without modifying it.",
        {"path": "absolute path", "start_line": "integer", "line_count": "integer"},
    ),
    (
        "workspace_patch",
        "Apply an auditable unified patch to files already placed in scope.",
        {"patch": "string", "expected_preimage_sha256": "string"},
    ),
    (
        "shell_exec",
        "Run a bounded command in an explicit working directory and return stdout, stderr, and rc.",
        {"command": "string", "working_directory": "absolute path", "timeout_seconds": "number"},
    ),
    (
        "cluster_inspect",
        "Read host identity, process, port, accelerator, memory, and network state.",
        {"node": "string", "checks": "array of strings", "run_id": "string"},
    ),
    (
        "metrics_snapshot",
        "Capture an immutable metrics endpoint snapshot with timestamp and content digest.",
        {"url": "string", "output_path": "absolute path", "labels": "object"},
    ),
    (
        "artifact_verify",
        "Verify a transport or result manifest and report missing, extra, or mismatched files.",
        {"root": "absolute path", "manifest": "absolute path", "fail_closed": "boolean"},
    ),
    (
        "trace_analyze",
        "Compute request, session, token, prefix, and arrival statistics without changing the trace.",
        {"trace_path": "absolute path", "profile": "string", "expected_sha256": "string"},
    ),
    (
        "service_control",
        "Start or stop only run-scoped services after identity and interference gates pass.",
        {"run_id": "string", "role": "string", "action": "start or stop", "manifest": "string"},
    ),
    (
        "result_archive",
        "Seal result files, produce checksums, and verify the published shared-storage view.",
        {"run_id": "string", "source": "absolute path", "destination": "absolute path"},
    ),
)


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


def build_prompt_source() -> str:
    sections = [BASE_PROMPT]
    # Unique namespaces model the large tool schemas commonly present in agent
    # system prompts. The descriptions remain meaningful; this is not random
    # token padding.
    for catalog_index in range(96):
        name, description, properties = TOOL_KINDS[catalog_index % len(TOOL_KINDS)]
        namespace = f"agent_runtime_{catalog_index // len(TOOL_KINDS):02d}"
        schema = {
            "type": "function",
            "function": {
                "name": f"{namespace}__{name}",
                "description": description,
                "parameters": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        key: {"description": meaning, "type": "string"}
                        for key, meaning in properties.items()
                    },
                    "required": list(properties),
                },
            },
        }
        sections.append(
            "\nTool definition "
            f"{catalog_index:03d}:\n"
            + json.dumps(schema, ensure_ascii=False, sort_keys=True, indent=2)
            + "\nOperational rule: validate every required field, keep evidence under the current "
            "run id, and return a structured error instead of silently changing scope.\n"
        )
    sections.append(
        "\nResponse policy: lead with the result, state concrete blockers, and keep measurements "
        "separate from hypotheses. Preserve enough state for the next conversation turn.\n"
    )
    return "".join(sections)


def build_asset(tokenizer_path: Path, target_tokens: int) -> dict[str, Any]:
    try:
        from transformers import AutoTokenizer
    except ImportError as exc:  # pragma: no cover - exercised on the cluster runtime
        raise RuntimeError("transformers is required to build the prefix asset") from exc

    tokenizer = AutoTokenizer.from_pretrained(
        str(tokenizer_path), local_files_only=True, trust_remote_code=True
    )
    source = build_prompt_source()
    source_ids = tokenizer.encode(source, add_special_tokens=False)
    if len(source_ids) < target_tokens:
        raise RuntimeError(
            f"generated prompt is too short: {len(source_ids)} < {target_tokens}"
        )
    token_ids = [int(item) for item in source_ids[:target_tokens]]
    vocab_size = int(getattr(tokenizer, "vocab_size", 0) or len(tokenizer))
    if any(item < 0 or item >= vocab_size for item in token_ids):
        raise RuntimeError("tokenizer produced an out-of-range token id")
    decoded_prefix = tokenizer.decode(token_ids, skip_special_tokens=False)

    tokenizer_hashes: dict[str, str] = {}
    for name in TOKENIZER_FILES:
        path = tokenizer_path / name
        if not path.is_file():
            raise RuntimeError(f"missing tokenizer identity file: {path}")
        tokenizer_hashes[name] = sha256_file(path)

    token_bytes = canonical_json_bytes(token_ids)
    return {
        "schema": SCHEMA,
        "profile": PROFILE,
        "target_tokens": target_tokens,
        "vocab_size": vocab_size,
        "tokenizer_path": str(tokenizer_path.resolve()),
        "tokenizer_files_sha256": tokenizer_hashes,
        "source_prompt_utf8_bytes": len(source.encode("utf-8")),
        "source_prompt_tokens_before_truncate": len(source_ids),
        "source_prompt_sha256": sha256_bytes(source.encode("utf-8")),
        "decoded_prefix_sha256": sha256_bytes(decoded_prefix.encode("utf-8")),
        "token_ids_sha256": sha256_bytes(token_bytes),
        "token_ids": token_ids,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target-tokens", type=int, default=TARGET_TOKENS)
    args = parser.parse_args(argv)
    if args.target_tokens != TARGET_TOKENS:
        parser.error(f"this profile requires exactly {TARGET_TOKENS} tokens")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    asset = build_asset(args.tokenizer, args.target_tokens)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical_json_bytes(asset) + b"\n")
    print(json.dumps({key: value for key, value in asset.items() if key != "token_ids"}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
