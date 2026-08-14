#!/usr/bin/env bash
set -euo pipefail

root="${1:?missing fluxon root}"
node="${2:?missing node label}"
variant="${3:?missing E44 performance variant}"
case "$node" in node0|node1) ;; *) exit 2 ;; esac

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$script_dir/e44_v5_perf_variant_20260718.sh" "$variant"
replica_task_config_json="${E44_HOST_REPLICA_TASK_CONFIG_JSON:-$E44_PERF_REPLICA_TASK_JSON}"
if [ -z "$replica_task_config_json" ]; then
  echo "replica task config JSON must not be empty" >&2
  exit 2
fi

site=/storage/zth/sglang_l13_fluxon_v2/venv-zth/lib/python3.10/site-packages
test "$(sha256sum "$site/sglang/srt/mem_cache/storage/fluxon/hicache_fluxon.py" | awk '{print $1}')" = "$E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256"
test "$(sha256sum "$site/sglang/srt/mem_cache/unified_radix_cache.py" | awk '{print $1}')" = "$E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256"
if [ -n "${E44_PERF_EXPECTED_SCHEDULER_SHA256:-}" ]; then
  test "$(sha256sum "$site/sglang/srt/managers/scheduler.py" | awk '{print $1}')" = \
    "$E44_PERF_EXPECTED_SCHEDULER_SHA256"
fi
if [ -n "${E44_PERF_EXPECTED_SCHEDULE_BATCH_SHA256:-}" ]; then
  test "$(sha256sum "$site/sglang/srt/managers/schedule_batch.py" | awk '{print $1}')" = \
    "$E44_PERF_EXPECTED_SCHEDULE_BATCH_SHA256"
fi
test "$(sha256sum "$site/sglang/srt/mem_cache/unified_cache_components/full_component.py" | awk '{print $1}')" = 6775c5b926a7c3329a9f7f8d1d8182de5e0d3d628d5503a2b702b5b9931b3f8e
test "$(sha256sum "$site/sglang/srt/mem_cache/memory_pool_host.py" | awk '{print $1}')" = "$E44_PERF_EXPECTED_MEMORY_POOL_HOST_SHA256"

export ROOT_DIR="$root"
export FLUXON_NODE0_IP="${FLUXON_NODE0_IP:-10.233.114.139}"
export FLUXON_NODE1_IP="${FLUXON_NODE1_IP:-10.233.114.138}"
export FLUXON_NODE2_IP="${FLUXON_NODE2_IP:-10.233.91.204}"
export FLUXON_EXTERNAL_VENV_DIR="$E44_PERF_VENV_GPU"
export FLUXON_EXTERNAL_CUDA_HOME="$E44_PERF_CUDA_HOME"
export FLUXON_EXTERNAL_CUDA_WHEEL_ROOT="$E44_PERF_CUDA_WHEEL_ROOT"
export FLUXON_EXTERNAL_OWNER_DRAM_BYTES="${E44_HOST_GPU_OWNER_DRAM_BYTES:-137438953472}"
export FLUXON_EXTERNAL_GPU_A="${E44_HOST_GPU_A:-0}"
export FLUXON_EXTERNAL_GPU_B="${E44_HOST_GPU_B:-1}"
export SGLANG_EXTERNAL_PORT="${E44_HOST_SGLANG_PORT:-31001}"
export SGLANG_EXTERNAL_PORT_B="${E44_HOST_SGLANG_PORT_B:-31002}"
export SGLANG_EXTERNAL_LAYOUT="${E44_HOST_SGLANG_LAYOUT:-tp2}"
case "$SGLANG_EXTERNAL_LAYOUT" in
  tp2) expected_owner_local_reserve_value_len=4718592 ;;
  tp1x2) expected_owner_local_reserve_value_len=9437184 ;;
  *) echo "unsupported SGLANG layout for owner reserve geometry: $SGLANG_EXTERNAL_LAYOUT" >&2; exit 2 ;;
esac
owner_local_reserve_value_len="${E44_HOST_OWNER_LOCAL_RESERVE_VALUE_LEN:-$expected_owner_local_reserve_value_len}"
if [ "$owner_local_reserve_value_len" != "$expected_owner_local_reserve_value_len" ]; then
  echo "owner reserve value_len mismatch: layout=$SGLANG_EXTERNAL_LAYOUT expected=$expected_owner_local_reserve_value_len got=$owner_local_reserve_value_len" >&2
  exit 2
fi
export FLUXON_EXTERNAL_RDMA_DEVICE_0="${E44_HOST_RDMA_DEVICE_0:-mlx5_4}"
export FLUXON_EXTERNAL_RDMA_DEVICE_1="${E44_HOST_RDMA_DEVICE_1:-mlx5_6}"
export FLUXON_EXTERNAL_OWNER_CPUSET="${E44_HOST_OWNER_CPUSET:-48-95,144-191}"
export FLUXON_EXTERNAL_REPLICA_WRITEBACK_HOT_CAPACITY_RATIO=0.90
unset FLUXON_EXTERNAL_OMIT_OWNER_HOT_CAPACITY_RATIO
export FLUXON_EXTERNAL_OWNER_LOCAL_RESERVE_VALUE_LEN="$owner_local_reserve_value_len"
export FLUXON_EXTERNAL_OWNER_LOCAL_RESERVE_PAYLOAD_CAPACITY_BYTES="${E44_HOST_GPU_OWNER_LOCAL_PAYLOAD_BYTES:-123695058124}"
export FLUXON_EXTERNAL_CLEAN_START=1
export FLUXON_EXTERNAL_OWNER_SESSION="zth_fluxon_owner_${E44_PERF_RUN_ID}_${node}"
export SGLANG_EXTERNAL_SESSION="zth_sglang_${E44_PERF_RUN_ID}_${node}_tp2"
export SGLANG_EXTERNAL_SESSION_A="zth_sglang_${E44_PERF_RUN_ID}_${node}_gpu${FLUXON_EXTERNAL_GPU_A}_tp1"
export SGLANG_EXTERNAL_SESSION_B="zth_sglang_${E44_PERF_RUN_ID}_${node}_gpu${FLUXON_EXTERNAL_GPU_B}_tp1"
export SGLANG_EXTERNAL_LOG_SUFFIX="_${E44_PERF_RUN_ID}_20260719"
export SGLANG_EXTERNAL_HICACHE_KEY_PREFIX="fluxon_external_${E44_PERF_RUN_ID}_20260719"
export SGLANG_EXTERNAL_HICACHE_SIZE_GB=32 SGLANG_EXTERNAL_HICACHE_WRITE_POLICY=write_back
export SGLANG_EXTERNAL_HICACHE_PREFETCH_THRESHOLD="${E44_PERF_HICACHE_PREFETCH_THRESHOLD:-256}" SGLANG_EXTERNAL_HICACHE_BATCH_CONCURRENCY="$E44_PERF_HICACHE_BATCH_CONCURRENCY"
export SGLANG_EXTERNAL_BATCH_EXISTS_PIN_TTL_MS=1200 SGLANG_EXTERNAL_MAX_TOTAL_TOKENS=200000
export SGLANG_EXTERNAL_PAGE_SIZE=64 SGLANG_EXTERNAL_MEM_FRACTION_STATIC=0.50
export SGLANG_EXTERNAL_DISABLE_OVERLAP_SCHEDULE=0 SGLANG_EXTERNAL_DISABLE_CUDA_GRAPH=0
export FLUXON_EXTERNAL_DISABLE_OBSERVABILITY=false FLUXON_EXTERNAL_ICEORYX_EXTERNAL_BUSY_POLL=true FLUXON_EXTERNAL_ICEORYX_OWNER_CLIENT_BUSY_POLL=true
export FLUXON_EXTERNAL_EXPECTED_PYO3_SHA256="$E44_PERF_EXPECTED_PYO3_SHA256"
export FLUXON_EXTERNAL_EXPECTED_COMMU_CORE_SHA256="$E44_PERF_EXPECTED_COMMU_CORE_SHA256"
export FLUXON_EXTERNAL_EXPECTED_RDMA_PROBE_SHA256="$E44_PERF_EXPECTED_RDMA_PROBE_SHA256"
export FLUXON_EXTERNAL_REPLICA_TASK_MAX_INFLIGHT=64
export FLUXON_EXTERNAL_USER_RPC_SYNC_HANDLER_THREAD_COUNT=8
export FLUXON_EXTERNAL_TCP_THREAD_CONTROL_LANE_COUNT="${E44_PERF_TCP_CONTROL_LANE_COUNT:-}"
export FLUXON_EXTERNAL_OWNER_REMOTE_PUT_MAX_INFLIGHT_BYTES="${E44_PERF_OWNER_REMOTE_PUT_MAX_INFLIGHT_BYTES:-}"
export FLUXON_EXTERNAL_OWNER_REMOTE_PUT_MAX_INFLIGHT_ITEMS="${E44_PERF_OWNER_REMOTE_PUT_MAX_INFLIGHT_ITEMS:-}"
export SGLANG_EXTERNAL_REPLICA_TASK_CONFIG_JSON="$replica_task_config_json"
export SGLANG_FLUXON_HOSTLESS_PAGE_INDEX_VALIDATE_EVERY_N=0
export SGLANG_FLUXON_HOSTLESS_EVICTION_WRITE_STREAM=1 SGLANG_FLUXON_HOSTLESS_LAYER_BATCH_DMA=1 SGLANG_FLUXON_HOSTLESS_BACKGROUND_DMA_SUBMIT=1
export SGLANG_FLUXON_HOSTLESS_DMA_MAX_DESCRIPTORS_PER_CALL="$E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL"
export RUST_LOG=info

tmux set-environment -g SGLANG_FLUXON_HOSTLESS_EVICTION_WRITE_STREAM 1 2>/dev/null || true
tmux set-environment -g SGLANG_FLUXON_HOSTLESS_LAYER_BATCH_DMA 1 2>/dev/null || true
tmux set-environment -g SGLANG_FLUXON_HOSTLESS_BACKGROUND_DMA_SUBMIT 1 2>/dev/null || true
tmux set-environment -g SGLANG_FLUXON_HOSTLESS_DMA_MAX_DESCRIPTORS_PER_CALL "$E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL" 2>/dev/null || true
gpu_stack_script="${E44_HOST_GPU_STACK_SCRIPT:-$script_dir/e16bb_rdma_numa1_20260714/start_gpu_stack_owner_numa1.sh}"
test -f "$gpu_stack_script"
exec bash "$gpu_stack_script"
