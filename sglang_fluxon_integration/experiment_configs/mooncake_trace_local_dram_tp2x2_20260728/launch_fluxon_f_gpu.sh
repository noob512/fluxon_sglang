#!/usr/bin/env bash
set -euo pipefail

action="${1:-status}"
run_id="${FLUXON_F_RUN_ID:?missing FLUXON_F_RUN_ID}"
case "$run_id" in
  *[!A-Za-z0-9_]*) echo "FLUXON_F_RUN_ID must contain only letters, digits, and underscores" >&2; exit 2 ;;
esac

runtime_root="${FLUXON_F_RUNTIME_ROOT:-/tmp/fluxon_mooncake_f_${run_id}}"
case "$runtime_root" in
  /tmp/fluxon_mooncake_f_*) ;;
  *) echo "invalid FLUXON_F_RUNTIME_ROOT: $runtime_root" >&2; exit 2 ;;
esac

gpu_ip="${FLUXON_F_GPU_IP:-10.233.90.51}"
cpu_ip="${FLUXON_F_CPU_IP:-10.233.114.150}"
expected_hostname="${FLUXON_F_GPU_HOSTNAME:-lgsl-a4-5f02-m9-3-h100gpu145}"
cluster_name="${FLUXON_F_CLUSTER_NAME:-fluxon-mooncake-f-${run_id}}"
master_id="${FLUXON_F_MASTER_ID:-fluxon_mooncake_f_master}"
owner_id="${FLUXON_F_LOCAL_OWNER_ID:-fluxon_mooncake_f_local_owner}"
root="$runtime_root/fluxon_f1"
venv="$runtime_root/venv"
base_venv="${FLUXON_F_BASE_VENV:-/public/mjq/.venv_sglang_fluxon}"
release="${FLUXON_F_GPU_RELEASE:-/public/mjq/sglang_fluxon/releases/fluxon_e44_r111_l3_retry_gpu_cuda_20260802}"
cuda_home="$runtime_root/cuda"
launcher="$root/start_gpu_stack_owner_tp2x2_f.sh"
model="${FLUXON_F_MODEL_PATH:-/public/mjq/models/Qwen3-VL-8B-Instruct}"
gdr_mode="${FLUXON_F_GDR_MODE:-disabled}"
layer_batch_dma="${FLUXON_F_LAYER_BATCH_DMA:-1}"
background_dma_submit="${FLUXON_F_BACKGROUND_DMA_SUBMIT:-1}"
expected_radix_sha256=8e04dbea3b16d8e098792a40431e7dd458f8b283e439de5676917e2413c7fb79
owner_session="fluxon_f_${run_id}_owner"
session0="fluxon_f_${run_id}_sglang0"
session1="fluxon_f_${run_id}_sglang1"

case "${layer_batch_dma}:${background_dma_submit}" in
  0:0|1:0|1:1) ;;
  *)
    echo "invalid Fluxon H2D mode: layer_batch_dma=$layer_batch_dma background_dma_submit=$background_dma_submit; expected 0:0, 1:0, or 1:1" >&2
    exit 2
    ;;
esac

identity_gate() {
  test "$(hostname)" = "$expected_hostname"
  tr ' ' '\n' <<<"$(hostname -I)" | grep -Fx "$gpu_ip" >/dev/null
  test "$(findmnt -T /tmp -o FSTYPE -n)" = xfs
  test -x "$launcher"
  test -x "$venv/bin/python"
  test -x "$base_venv/bin/ninja"
  test -x "$release/ext_images/etcd/etcdctl"
  test -x "$cuda_home/bin/nvcc"
  test -x "$cuda_home/nvvm/bin/cicc"
  test -f "$model/config.json"
  test "$gdr_mode" = disabled
  local radix="$venv/lib/python3.10/site-packages/sglang/srt/mem_cache/unified_radix_cache.py"
  test "$(sha256sum "$radix" | awk '{print $1}')" = "$expected_radix_sha256"
  grep -F '_FLUXON_GPU_DIRECT_STAGING_ENABLED = False' "$radix" >/dev/null
  grep -F 'Fluxon GPU-direct staging disabled: mode=cpu_h2d_only' "$radix" >/dev/null
  local hca
  for hca in mlx5_0 mlx5_1 mlx5_2 mlx5_3; do
    grep -F ACTIVE "/sys/class/infiniband/$hca/ports/1/state" >/dev/null
  done
}

selected_gpu_empty() {
  local gpu="$1" pids
  pids="$(nvidia-smi -i "$gpu" --query-compute-apps=pid --format=csv,noheader,nounits | sed '/^[[:space:]]*$/d')"
  if [[ -n "$pids" ]]; then
    echo "GPU $gpu is not empty: $pids" >&2
    return 1
  fi
}

common_env=(
  ROOT_DIR="$root"
  FLUXON_NODE0_IP="$gpu_ip"
  FLUXON_NODE1_IP="$gpu_ip"
  FLUXON_NODE2_IP="$cpu_ip"
  FLUXON_EXTERNAL_CLUSTER_NAME="$cluster_name"
  FLUXON_EXTERNAL_MASTER_ID="$master_id"
  FLUXON_EXTERNAL_NODE_LABEL=local0
  FLUXON_EXTERNAL_NODE_IP="$gpu_ip"
  FLUXON_EXTERNAL_OWNER_ID="$owner_id"
  FLUXON_EXTERNAL_OWNER_SUB_CLUSTER=sglang_owner
  FLUXON_EXTERNAL_VENV_DIR="$venv"
  SGLANG_EXTERNAL_BASE_VENV_DIR="$base_venv"
  SGLANG_EXTERNAL_CUDA_HOME="$cuda_home"
  SGLANG_EXTERNAL_MODEL_PATH="$model"
  ETCDCTL="$release/ext_images/etcd/etcdctl"
  FLUXON_EXTERNAL_OWNER_DRAM_BYTES=274877906944
  FLUXON_EXTERNAL_REPLICA_WRITEBACK_HOT_CAPACITY_RATIO=0.90
  FLUXON_EXTERNAL_OWNER_LOCAL_RESERVE_VALUE_LEN=4718592
  FLUXON_EXTERNAL_OWNER_LOCAL_RESERVE_PAYLOAD_CAPACITY_BYTES=247390116249
  FLUXON_EXTERNAL_RDMA_DEVICE_0=mlx5_0
  FLUXON_EXTERNAL_RDMA_DEVICE_1=mlx5_1
  FLUXON_EXTERNAL_RDMA_DEVICE_2=mlx5_2
  FLUXON_EXTERNAL_RDMA_DEVICE_3=mlx5_3
  FLUXON_EXTERNAL_CLEAN_START=1
  FLUXON_EXTERNAL_OWNER_SESSION="$owner_session"
  FLUXON_EXTERNAL_DISABLE_OBSERVABILITY=true
  FLUXON_EXTERNAL_ICEORYX_EXTERNAL_BUSY_POLL=true
  FLUXON_EXTERNAL_ICEORYX_OWNER_CLIENT_BUSY_POLL=true
  FLUXON_EXTERNAL_EXPECTED_PYO3_SHA256=beb2eff37e4efe2ca41ac07aa2dc0478db3ca7157ab6437119c16532f02b7d91
  FLUXON_EXTERNAL_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
  FLUXON_EXTERNAL_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
  FLUXON_EXTERNAL_REPLICA_TASK_MAX_INFLIGHT=64
  FLUXON_EXTERNAL_OWNER_REMOTE_PUT_MAX_INFLIGHT_BYTES=17179869184
  FLUXON_EXTERNAL_OWNER_REMOTE_PUT_MAX_INFLIGHT_ITEMS=4096
  FLUXON_EXTERNAL_USER_RPC_SYNC_HANDLER_THREAD_COUNT=8
  SGLANG_EXTERNAL_HICACHE_KEY_PREFIX="fluxon_mooncake_f_${run_id}"
  SGLANG_EXTERNAL_HICACHE_SIZE_GB=32
  SGLANG_EXTERNAL_HICACHE_WRITE_POLICY=write_back
  SGLANG_EXTERNAL_HICACHE_PREFETCH_THRESHOLD=256
  SGLANG_EXTERNAL_HICACHE_BATCH_CONCURRENCY=32
  SGLANG_EXTERNAL_BATCH_EXISTS_PIN_TTL_MS=1200
  SGLANG_EXTERNAL_MAX_TOTAL_TOKENS=200000
  SGLANG_EXTERNAL_PAGE_SIZE=64
  SGLANG_EXTERNAL_MEM_FRACTION_STATIC=0.50
  SGLANG_EXTERNAL_DISABLE_OVERLAP_SCHEDULE=0
  SGLANG_EXTERNAL_DISABLE_CUDA_GRAPH=0
  'SGLANG_EXTERNAL_REPLICA_TASK_CONFIG_JSON={"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
  SGLANG_FLUXON_HOSTLESS_PAGE_INDEX_VALIDATE_EVERY_N=0
  SGLANG_FLUXON_HOSTLESS_EVICTION_WRITE_STREAM=1
  SGLANG_FLUXON_HOSTLESS_LAYER_BATCH_DMA="$layer_batch_dma"
  SGLANG_FLUXON_HOSTLESS_BACKGROUND_DMA_SUBMIT="$background_dma_submit"
  FLUXON_F_GDR_MODE=disabled
  PYTHONDONTWRITEBYTECODE=1
  RUST_LOG=info
)

owner_start() {
  identity_gate
  for gpu in 0 1 2 3 4 5 6 7; do selected_gpu_empty "$gpu"; done
  for name in "$owner_session" "$session0" "$session1"; do
    if tmux has-session -t "$name" 2>/dev/null; then
      echo "session already exists: $name" >&2
      exit 1
    fi
  done
  if [[ -n "${FLUXON_EXTERNAL_OWNER_SSD_CAPACITY_BYTES:-}" ]]; then
    echo "SSD capacity must remain unset for F" >&2
    exit 2
  fi
  env "${common_env[@]}" FLUXON_EXTERNAL_OWNER_ONLY=1 \
    SGLANG_EXTERNAL_PORT=31001 FLUXON_EXTERNAL_GPU_A=0 FLUXON_EXTERNAL_GPU_B=1 \
    "$launcher"
}

instance_start() {
  local instance="$1" port gpu_a gpu_b session suffix
  case "$instance" in
    0) port=31001; gpu_a=0; gpu_b=1; session="$session0"; suffix=instance0 ;;
    1) port=31002; gpu_a=2; gpu_b=3; session="$session1"; suffix=instance1 ;;
    *) exit 2 ;;
  esac
  identity_gate
  tmux has-session -t "$owner_session" 2>/dev/null
  selected_gpu_empty "$gpu_a"
  selected_gpu_empty "$gpu_b"
  if tmux has-session -t "$session" 2>/dev/null; then
    echo "session already exists: $session" >&2
    exit 1
  fi
  if ss -ltn | grep -Eq ":${port} "; then
    echo "port already in use: $port" >&2
    exit 1
  fi
  env "${common_env[@]}" FLUXON_EXTERNAL_SGLANG_ONLY=1 \
    SGLANG_EXTERNAL_PORT="$port" FLUXON_EXTERNAL_GPU_A="$gpu_a" FLUXON_EXTERNAL_GPU_B="$gpu_b" \
    SGLANG_EXTERNAL_SESSION="$session" SGLANG_EXTERNAL_LOG_SUFFIX="_${run_id}_${suffix}" \
    "$launcher"
}

stop_session() {
  local session="$1"
  if tmux has-session -t "$session" 2>/dev/null; then
    tmux send-keys -t "$session" C-c 2>/dev/null || true
    for _ in $(seq 1 30); do
      tmux has-session -t "$session" 2>/dev/null || return 0
      sleep 1
    done
    tmux kill-session -t "$session" 2>/dev/null || true
  fi
}

stop() {
  stop_session "$session1"
  stop_session "$session0"
  stop_session "$owner_session"
}

status() {
  local name
  for name in "$owner_session" "$session0" "$session1"; do
    if tmux has-session -t "$name" 2>/dev/null; then echo "running $name"; else echo "stopped $name"; fi
  done
  echo "h2d_mode layer_batch_dma=$layer_batch_dma background_dma_submit=$background_dma_submit"
  ss -ltnp | grep -E ':(31001|31002) ' || true
  nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv,noheader
}

case "$action" in
  owner-start) owner_start ;;
  instance0-start) instance_start 0 ;;
  instance1-start) instance_start 1 ;;
  stop) stop ;;
  status) status ;;
  *) echo "usage: $0 <owner-start|instance0-start|instance1-start|stop|status>" >&2; exit 2 ;;
esac
