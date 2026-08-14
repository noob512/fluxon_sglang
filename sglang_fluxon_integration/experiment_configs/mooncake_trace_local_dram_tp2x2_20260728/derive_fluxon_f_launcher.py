#!/usr/bin/env python3
"""Derive the TP2x2 Fluxon launcher from the sealed r96 launcher.

The transformation is deliberately exact-count based.  A changed r96 input
must fail closed instead of silently producing a launcher with mixed old/new
semantics.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


EXPECTED_SOURCE_SHA256 = "a3f949e8cc2fcf3efa668941813874f3e6d3e572f106f38d58f5256f20e7f5e5"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def replace_exact(text: str, old: str, new: str, expected_count: int = 1) -> str:
    actual_count = text.count(old)
    if actual_count != expected_count:
        raise SystemExit(
            f"refusing launcher derivation: expected {expected_count} occurrence(s), "
            f"found {actual_count}: {old!r}"
        )
    return text.replace(old, new)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()

    source_hash = sha256(args.source)
    if source_hash != EXPECTED_SOURCE_SHA256:
        raise SystemExit(
            "sealed r96 GPU launcher identity mismatch: "
            f"got={source_hash} expected={EXPECTED_SOURCE_SHA256}"
        )

    text = args.source.read_text(encoding="utf-8")
    text = replace_exact(
        text,
        'SGLANG_BASE_VENV_DIR="/storage/zth/sglang_l13_fluxon_v2/venv-zth"',
        'SGLANG_BASE_VENV_DIR="${SGLANG_EXTERNAL_BASE_VENV_DIR:?missing SGLANG_EXTERNAL_BASE_VENV_DIR}"\n'
        'SGLANG_CUDA_HOME="${SGLANG_EXTERNAL_CUDA_HOME:?missing SGLANG_EXTERNAL_CUDA_HOME}"',
    )
    text = replace_exact(
        text,
        'SGLANG_PORT="31001"',
        'SGLANG_PORT="${SGLANG_EXTERNAL_PORT:-31001}"',
    )
    text = replace_exact(
        text,
        'REPLICA_TASK_MAX_INFLIGHT="${FLUXON_EXTERNAL_REPLICA_TASK_MAX_INFLIGHT:-}"',
        'REPLICA_TASK_MAX_INFLIGHT="${FLUXON_EXTERNAL_REPLICA_TASK_MAX_INFLIGHT:-}"\n'
        'OWNER_REMOTE_PUT_MAX_INFLIGHT_BYTES="${FLUXON_EXTERNAL_OWNER_REMOTE_PUT_MAX_INFLIGHT_BYTES:-}"\n'
        'OWNER_REMOTE_PUT_MAX_INFLIGHT_ITEMS="${FLUXON_EXTERNAL_OWNER_REMOTE_PUT_MAX_INFLIGHT_ITEMS:-}"',
    )
    text = replace_exact(
        text,
        'RDMA_DEVICE_1="${FLUXON_EXTERNAL_RDMA_DEVICE_1:-mlx5_1}"',
        'RDMA_DEVICE_1="${FLUXON_EXTERNAL_RDMA_DEVICE_1:-mlx5_1}"\n'
        'RDMA_DEVICE_2="${FLUXON_EXTERNAL_RDMA_DEVICE_2:?missing FLUXON_EXTERNAL_RDMA_DEVICE_2}"\n'
        'RDMA_DEVICE_3="${FLUXON_EXTERNAL_RDMA_DEVICE_3:?missing FLUXON_EXTERNAL_RDMA_DEVICE_3}"',
    )
    text = replace_exact(
        text,
        'CLIENT_CONFIG="$CONFIG_DIR/fluxon_client_current_cpu_remote_tp2.yaml"',
        'CLIENT_CONFIG="$CONFIG_DIR/fluxon_client_current_cpu_remote_tp2_port${SGLANG_PORT}.yaml"',
    )
    text = replace_exact(
        text,
        '  - "${RDMA_DEVICE_0}"\n  - "${RDMA_DEVICE_1}"',
        '  - "${RDMA_DEVICE_0}"\n'
        '  - "${RDMA_DEVICE_1}"\n'
        '  - "${RDMA_DEVICE_2}"\n'
        '  - "${RDMA_DEVICE_3}"',
        expected_count=2,
    )
    # This declaration is intentionally audit-only for external clients in r96:
    # the core owner startup gate excludes external_client members.  The formal
    # pre-trace gate performs the actual generation/edge/data-path validation.
    text = replace_exact(
        text,
        '  - "${RDMA_DEVICE_3}"\nYAML\n\n'
        '  append_user_rpc_sync_handler_thread_count "$path"',
        '  - "${RDMA_DEVICE_3}"\n'
        '  require_transfer_rpc_fast_path_ready_timeout_seconds: ${RDMA_READY_TIMEOUT}\n'
        'YAML\n\n'
        '  append_user_rpc_sync_handler_thread_count "$path"',
    )
    text = replace_exact(
        text,
        '  write_client_config "$CLIENT_CONFIG" "fluxon_${ROOT_DIR##*/}_external_sglang_tp2"',
        '  write_client_config "$CLIENT_CONFIG" "fluxon_${ROOT_DIR##*/}_external_sglang_tp2_port${SGLANG_PORT}"',
    )
    remote_admission_block = '''  if [ -n "$OWNER_REMOTE_PUT_MAX_INFLIGHT_BYTES" ] || [ -n "$OWNER_REMOTE_PUT_MAX_INFLIGHT_ITEMS" ]; then
    if [[ ! "$OWNER_REMOTE_PUT_MAX_INFLIGHT_BYTES" =~ ^[1-9][0-9]*$ ]] ||
       [[ ! "$OWNER_REMOTE_PUT_MAX_INFLIGHT_ITEMS" =~ ^[1-9][0-9]*$ ]]; then
      echo "owner remote Put admission requires paired positive byte/item limits" >&2
      exit 2
    fi
    cat >> "$OWNER_CONFIG" <<YAML
  owner_remote_put_max_inflight_bytes: ${OWNER_REMOTE_PUT_MAX_INFLIGHT_BYTES}
  owner_remote_put_max_inflight_items: ${OWNER_REMOTE_PUT_MAX_INFLIGHT_ITEMS}
YAML
  fi

'''
    text = replace_exact(
        text,
        '  if [ -n "$OWNER_LOCAL_RESERVE_VALUE_LEN" ] || [ -n "$OWNER_LOCAL_RESERVE_PAYLOAD_CAPACITY_BYTES" ]; then',
        remote_admission_block
        + '  if [ -n "$OWNER_LOCAL_RESERVE_VALUE_LEN" ] || [ -n "$OWNER_LOCAL_RESERVE_PAYLOAD_CAPACITY_BYTES" ]; then',
    )
    text = replace_exact(
        text,
        'expected = "/storage/zth/sglang_l13_fluxon_v2/venv-zth/"',
        'expected = str(Path(sys.argv[3]).resolve()) + "/"',
    )
    text = replace_exact(
        text,
        "until grep -Eq 'owner local reserve refill batch completed:.*expected_grants=[1-9][0-9]*' \"$OWNER_LOG\"; do",
        "until grep -Eq 'owner local reserve (refill batch completed:.*expected_grants=[1-9][0-9]*|offset-pool refill completed)' \"$OWNER_LOG\"; do",
    )
    text = replace_exact(
        text,
        'export PATH="$VENV_DIR/bin:$SGLANG_BASE_VENV_DIR/bin:\\$PATH"\n'
        'export LD_LIBRARY_PATH="$FLUXON_RUNTIME_LD_LIBRARY_PATH:\\${LD_LIBRARY_PATH:-}"',
        'export CUDA_HOME="$SGLANG_CUDA_HOME"\n'
        'export PATH="\\$CUDA_HOME/bin:$VENV_DIR/bin:$SGLANG_BASE_VENV_DIR/bin:\\$PATH"\n'
        'export LD_LIBRARY_PATH="\\$CUDA_HOME/lib64:$FLUXON_RUNTIME_LD_LIBRARY_PATH:\\${LD_LIBRARY_PATH:-}"',
    )
    child_cuda_path = (
        'export PATH="\\$CUDA_HOME/bin:$VENV_DIR/bin:'
        '$SGLANG_BASE_VENV_DIR/bin:\\$PATH"'
    )
    child_cuda_ld_path = (
        'export LD_LIBRARY_PATH="\\$CUDA_HOME/lib64:'
        '$FLUXON_RUNTIME_LD_LIBRARY_PATH:\\${LD_LIBRARY_PATH:-}"'
    )
    if text.count(child_cuda_path) != 1 or text.count(child_cuda_ld_path) != 1:
        raise SystemExit(
            "derived launcher must defer CUDA_HOME expansion to the generated "
            "SGLang child launcher"
        )
    text = replace_exact(
        text,
        'RUST_LOG="${RUST_LOG:-info}"',
        'RUST_LOG="${RUST_LOG:-info}"\n'
        'HOSTLESS_LAYER_BATCH_DMA="${SGLANG_FLUXON_HOSTLESS_LAYER_BATCH_DMA:-0}"\n'
        'HOSTLESS_BACKGROUND_DMA_SUBMIT="${SGLANG_FLUXON_HOSTLESS_BACKGROUND_DMA_SUBMIT:-0}"',
    )
    text = replace_exact(
        text,
        'export SGLANG_ENABLE_HEALTH_ENDPOINT_GENERATION="$HEALTH_ENDPOINT_GENERATION"\n\n'
        'HICACHE_STORAGE_EXTRA_CONFIG=',
        'export SGLANG_ENABLE_HEALTH_ENDPOINT_GENERATION="$HEALTH_ENDPOINT_GENERATION"\n'
        'export SGLANG_FLUXON_HOSTLESS_LAYER_BATCH_DMA="$HOSTLESS_LAYER_BATCH_DMA"\n'
        'export SGLANG_FLUXON_HOSTLESS_BACKGROUND_DMA_SUBMIT="$HOSTLESS_BACKGROUND_DMA_SUBMIT"\n\n'
        'HICACHE_STORAGE_EXTRA_CONFIG=',
    )
    text = replace_exact(
        text,
        '  require_cmd tmux\n  require_cmd curl\n'
        '  command -v ss >/dev/null 2>&1 || require_cmd netstat\n\n',
        '  require_cmd tmux\n  require_cmd curl\n'
        '  command -v ss >/dev/null 2>&1 || require_cmd netstat\n\n'
        '  case "${HOSTLESS_LAYER_BATCH_DMA}:${HOSTLESS_BACKGROUND_DMA_SUBMIT}" in\n'
        '    0:0|1:0|1:1) ;;\n'
        '    *)\n'
        '      echo "invalid Fluxon H2D mode: layer_batch_dma=${HOSTLESS_LAYER_BATCH_DMA} '
        'background_dma_submit=${HOSTLESS_BACKGROUND_DMA_SUBMIT}; expected 0:0, 1:0, or 1:1" >&2\n'
        '      exit 2\n'
        '      ;;\n'
        '  esac\n\n',
    )
    text = replace_exact(
        text,
        '    assert_port_free "$SGLANG_PORT"\n    check_runtime\n'
        '    start_sglang "$SGLANG_SESSION" "$SGLANG_PORT" "$CLIENT_CONFIG" "$SGLANG_LOG"',
        '    assert_port_free "$SGLANG_PORT"\n'
        '    write_client_config "$CLIENT_CONFIG" '
        '"fluxon_${ROOT_DIR##*/}_external_sglang_tp2_port${SGLANG_PORT}"\n'
        '    check_runtime\n'
        '    start_sglang "$SGLANG_SESSION" "$SGLANG_PORT" "$CLIENT_CONFIG" "$SGLANG_LOG"',
    )

    banner = (
        "# Derived for Mooncake Conversation F: one 256-GiB owner, two TP2 "
        "external clients, four HCAs.\n"
    )
    text = text.replace("#!/usr/bin/env bash\n", "#!/usr/bin/env bash\n" + banner, 1)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    os.chmod(args.output, 0o755)
    output_hash = sha256(args.output)
    manifest = {
        "schema_version": 1,
        "source": str(args.source),
        "source_sha256": source_hash,
        "derived": str(args.output),
        "derived_sha256": output_hash,
        "changes": [
            "explicit SGLang base venv",
            "runtime-selected SGLang port",
            "four RDMA HCAs for the shared local owner and clients",
            "one unique external-client identity/config per SGLang port",
            "paired no-queue remote Put byte/item admission on the local owner only",
            "owner reserve readiness accepts both legacy fixed-slot and offset-pool completion logs",
            "audit-only external readiness timeout declaration; formal enforcement is the independent direct-RDMA gate",
            "isolated venv import identity check",
            "run-scoped CUDA_HOME for FlashInfer JIT and CUDA graphs",
            "run-scoped layer-batch and background H2D mode exported by the generated SGLang child launcher",
            "fail-closed validation for H2D modes 0/0, 1/0, and 1/1",
        ],
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, sort_keys=True))


if __name__ == "__main__":
    main()
