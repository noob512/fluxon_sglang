#!/usr/bin/env bash
set -euo pipefail

# Run this script on the remote experiment nodes.  It intentionally uses
# distinct tmux sessions and output paths so the older Mooncake launchers are
# left untouched.

BASE_DIR="${BASE_DIR:-/storage/mjq/mooncake_m1/mooncake_3node_aligned_20260712}"
VENV="${VENV:-/storage/mjq/.venv_sglang_fluxon}"
MODEL_PATH="${MODEL_PATH:-/storage/fanyk1/models/Qwen3-VL-8B-Instruct}"
WORKLOAD_DIR="${WORKLOAD_DIR:-/storage/mjq/mooncake_m1/mooncake_perf_workloads}"

GPU0_IP="${GPU0_IP:-10.233.111.117}"
GPU1_IP="${GPU1_IP:-10.233.114.102}"
CPU_IP="${CPU_IP:-10.233.125.121}"
SGLANG_PORT="${SGLANG_PORT:-31001}"
GPU0_SGLANG_PORT="${GPU0_SGLANG_PORT:-$SGLANG_PORT}"
GPU1_SGLANG_PORT="${GPU1_SGLANG_PORT:-$SGLANG_PORT}"
GPU0_SGLANG_PORT_B="${GPU0_SGLANG_PORT_B:-31002}"
GPU1_SGLANG_PORT_B="${GPU1_SGLANG_PORT_B:-31002}"
GPU0_ROUTER_WORKER_HOST="${GPU0_ROUTER_WORKER_HOST:-$GPU0_IP}"
GPU1_ROUTER_WORKER_HOST="${GPU1_ROUTER_WORKER_HOST:-$GPU1_IP}"
GPU0_ROUTER_WORKER_PORT="${GPU0_ROUTER_WORKER_PORT:-$GPU0_SGLANG_PORT}"
GPU1_ROUTER_WORKER_PORT="${GPU1_ROUTER_WORKER_PORT:-$GPU1_SGLANG_PORT}"
GPU0_ROUTER_WORKER_PORT_B="${GPU0_ROUTER_WORKER_PORT_B:-$GPU0_SGLANG_PORT_B}"
GPU1_ROUTER_WORKER_PORT_B="${GPU1_ROUTER_WORKER_PORT_B:-$GPU1_SGLANG_PORT_B}"
ROUTER_PORT="${ROUTER_PORT:-32000}"
ROUTER_METRICS_PORT="${ROUTER_METRICS_PORT:-29100}"
ROUTER_POLICY="${ROUTER_POLICY:-cache_aware}"
METADATA_PORT="${METADATA_PORT:-8183}"
MASTER_PORT="${MASTER_PORT:-51081}"
MASTER_METRICS_PORT="${MASTER_METRICS_PORT:-9143}"
CPU_STORE_PORT="${CPU_STORE_PORT:-50052}"
CPU_STORE_HTTP_PORT="${CPU_STORE_HTTP_PORT:-9300}"
GPU_STORE_PORT="${GPU_STORE_PORT:-50053}"
GPU_STORE_HTTP_PORT="${GPU_STORE_HTTP_PORT:-9301}"
MOONCAKE_CPU_DEVICE_NAMES="${MOONCAKE_CPU_DEVICE_NAMES:-mlx5_0,mlx5_1}"

GPU_SEGMENT_BYTES="${GPU_SEGMENT_BYTES:-137438953472}"
CPU_SEGMENT_BYTES="${CPU_SEGMENT_BYTES:-274877906944}"
FLUXON_STALE_GPU_MMAP_BYTES="${FLUXON_STALE_GPU_MMAP_BYTES:-137438953472}"
FLUXON_STALE_CPU_MMAP_BYTES="${FLUXON_STALE_CPU_MMAP_BYTES:-274877906944}"
HICACHE_SIZE_GIB="${HICACHE_SIZE_GIB:-32}"
HICACHE_RATIO="${HICACHE_RATIO:-2.0}"
HICACHE_WRITE_POLICY="${HICACHE_WRITE_POLICY:-write_back}"
HICACHE_STORAGE_METADATA_CAPACITY="${HICACHE_STORAGE_METADATA_CAPACITY:-0}"
SGLANG_MAX_TOTAL_TOKENS="${SGLANG_MAX_TOTAL_TOKENS:-100000}"
SGLANG_DISABLE_OVERLAP_SCHEDULE="${SGLANG_DISABLE_OVERLAP_SCHEDULE:-1}"
EVICTION_HIGH_WATERMARK_RATIO="${EVICTION_HIGH_WATERMARK_RATIO:-0.95}"
SESSION_PREFIX="${SESSION_PREFIX:-sgmc_align}"
ENABLE_OFFLOAD="${ENABLE_OFFLOAD:-0}"
CLEAN_STALE_FLUXON_SHM="${CLEAN_STALE_FLUXON_SHM:-1}"
MOONCAKE_MEMORY_SAFETY_BYTES="${MOONCAKE_MEMORY_SAFETY_BYTES:-8589934592}"
GPU_HOST_CACHE_TOTAL_BYTES="${GPU_HOST_CACHE_TOTAL_BYTES:-$GPU_SEGMENT_BYTES}"
SGLANG_TP_SIZE="${SGLANG_TP_SIZE:-2}"
SGLANG_LAYOUT="${SGLANG_LAYOUT:-tp2}"
SGLANG_CUDA_VISIBLE_DEVICES="${SGLANG_CUDA_VISIBLE_DEVICES:-0,1}"
GPU_DEVICE_NAMES="${GPU_DEVICE_NAMES:-mlx5_0,mlx5_1}"
GPU_NCCL_SOCKET_IFNAME="${GPU_NCCL_SOCKET_IFNAME:-eth0}"
GPU_GLOO_SOCKET_IFNAME="${GPU_GLOO_SOCKET_IFNAME:-eth0}"
RDMA_RUNTIME_LIB_DIR="${RDMA_RUNTIME_LIB_DIR:-/storage/mjq/rdma_runtime_jammy/lib}"
RDMA_PROVIDER_LIB_DIR="${RDMA_PROVIDER_LIB_DIR:-${RDMA_RUNTIME_LIB_DIR%/lib}/libibverbs}"
RDMA_VERBS_DRIVERS="${RDMA_VERBS_DRIVERS:-}"
PYTHON_OVERLAY_DIR="${PYTHON_OVERLAY_DIR:-}"
CUDA_HOME="${CUDA_HOME:-}"
XDG_CACHE_HOME="${XDG_CACHE_HOME:-}"
TORCH_EXTENSIONS_DIR="${TORCH_EXTENSIONS_DIR:-}"
TVM_FFI_CACHE_DIR="${TVM_FFI_CACHE_DIR:-}"

case "$ROUTER_POLICY" in
  cache_aware|round_robin) ;;
  *) echo "ROUTER_POLICY must be cache_aware or round_robin" >&2; exit 2 ;;
esac
case "$SGLANG_LAYOUT" in
  tp2) ;;
  tp1x2)
    if [[ "$SGLANG_TP_SIZE" != 1 ]]; then
      echo "tp1x2 requires SGLANG_TP_SIZE=1" >&2
      exit 2
    fi
    if [[ "$GPU0_SGLANG_PORT" == "$GPU0_SGLANG_PORT_B" \
      || "$GPU1_SGLANG_PORT" == "$GPU1_SGLANG_PORT_B" ]]; then
      echo "tp1x2 requires two distinct SGLang ports on each node" >&2
      exit 2
    fi
    ;;
  *) echo "SGLANG_LAYOUT must be tp2 or tp1x2" >&2; exit 2 ;;
esac

LOG_DIR="$BASE_DIR/logs"
STATE_FILE="$BASE_DIR/cluster.env"
RUNTIME_LIB_DIR="${RUNTIME_LIB_DIR:-$BASE_DIR/runtime_libs}"
MOONCAKE_PACKAGE="$VENV/lib/python3.10/site-packages/mooncake"
MOONCAKE_AUDITWHEEL_LIBS="$VENV/lib/python3.10/site-packages/mooncake_transfer_engine.libs"

usage() {
  cat <<'EOF'
Usage:
  mooncake_3node_aligned_20260712.sh control <start|stop|status|run_metadata|run_master>
  mooncake_3node_aligned_20260712.sh cpu <start|stop|status|run>
  mooncake_3node_aligned_20260712.sh gpu <start|stop|status|run> <node0|node1>
  mooncake_3node_aligned_20260712.sh router <start|stop|status|run>
  mooncake_3node_aligned_20260712.sh workload <start|stop|status|run> <run_tag>
EOF
}

require_file() {
  if [[ ! -f "$1" ]]; then
    echo "missing file: $1" >&2
    exit 1
  fi
}

require_executable() {
  if [[ ! -x "$1" ]]; then
    echo "missing executable: $1" >&2
    exit 1
  fi
}

session_exists() {
  tmux has-session -t "$1" 2>/dev/null
}

start_session() {
  local session="$1"
  local log_file="$2"
  shift 2
  if session_exists "$session"; then
    echo "session already running: $session" >&2
    exit 1
  fi
  mkdir -p "$LOG_DIR"
  : >"$log_file"
  # A long-lived tmux server does not automatically import arbitrary client
  # environment variables.  Preserve all launcher overrides explicitly so a
  # wrapper can safely create an isolated experiment variant.
  local -a preserved_env=(
    "BASE_DIR=$BASE_DIR"
    "VENV=$VENV"
    "MODEL_PATH=$MODEL_PATH"
    "WORKLOAD_DIR=$WORKLOAD_DIR"
    "GPU0_IP=$GPU0_IP"
    "GPU1_IP=$GPU1_IP"
    "CPU_IP=$CPU_IP"
    "SGLANG_PORT=$SGLANG_PORT"
    "GPU0_SGLANG_PORT=$GPU0_SGLANG_PORT"
    "GPU1_SGLANG_PORT=$GPU1_SGLANG_PORT"
    "GPU0_SGLANG_PORT_B=$GPU0_SGLANG_PORT_B"
    "GPU1_SGLANG_PORT_B=$GPU1_SGLANG_PORT_B"
    "GPU0_ROUTER_WORKER_HOST=$GPU0_ROUTER_WORKER_HOST"
    "GPU1_ROUTER_WORKER_HOST=$GPU1_ROUTER_WORKER_HOST"
    "GPU0_ROUTER_WORKER_PORT=$GPU0_ROUTER_WORKER_PORT"
    "GPU1_ROUTER_WORKER_PORT=$GPU1_ROUTER_WORKER_PORT"
    "GPU0_ROUTER_WORKER_PORT_B=$GPU0_ROUTER_WORKER_PORT_B"
    "GPU1_ROUTER_WORKER_PORT_B=$GPU1_ROUTER_WORKER_PORT_B"
    "ROUTER_PORT=$ROUTER_PORT"
    "ROUTER_METRICS_PORT=$ROUTER_METRICS_PORT"
    "ROUTER_POLICY=$ROUTER_POLICY"
    "METADATA_PORT=$METADATA_PORT"
    "MASTER_PORT=$MASTER_PORT"
    "MASTER_METRICS_PORT=$MASTER_METRICS_PORT"
    "CPU_STORE_PORT=$CPU_STORE_PORT"
    "CPU_STORE_HTTP_PORT=$CPU_STORE_HTTP_PORT"
    "GPU_STORE_PORT=$GPU_STORE_PORT"
    "GPU_STORE_HTTP_PORT=$GPU_STORE_HTTP_PORT"
    "MOONCAKE_CPU_DEVICE_NAMES=$MOONCAKE_CPU_DEVICE_NAMES"
    "GPU_SEGMENT_BYTES=$GPU_SEGMENT_BYTES"
    "CPU_SEGMENT_BYTES=$CPU_SEGMENT_BYTES"
    "FLUXON_STALE_GPU_MMAP_BYTES=$FLUXON_STALE_GPU_MMAP_BYTES"
    "FLUXON_STALE_CPU_MMAP_BYTES=$FLUXON_STALE_CPU_MMAP_BYTES"
    "HICACHE_SIZE_GIB=$HICACHE_SIZE_GIB"
    "HICACHE_RATIO=$HICACHE_RATIO"
    "HICACHE_WRITE_POLICY=$HICACHE_WRITE_POLICY"
    "HICACHE_STORAGE_METADATA_CAPACITY=$HICACHE_STORAGE_METADATA_CAPACITY"
    "SGLANG_MAX_TOTAL_TOKENS=$SGLANG_MAX_TOTAL_TOKENS"
    "SGLANG_DISABLE_OVERLAP_SCHEDULE=$SGLANG_DISABLE_OVERLAP_SCHEDULE"
    "EVICTION_HIGH_WATERMARK_RATIO=$EVICTION_HIGH_WATERMARK_RATIO"
    "SESSION_PREFIX=$SESSION_PREFIX"
    "ENABLE_OFFLOAD=$ENABLE_OFFLOAD"
    "CLEAN_STALE_FLUXON_SHM=$CLEAN_STALE_FLUXON_SHM"
    "MOONCAKE_MEMORY_SAFETY_BYTES=$MOONCAKE_MEMORY_SAFETY_BYTES"
    "GPU_HOST_CACHE_TOTAL_BYTES=$GPU_HOST_CACHE_TOTAL_BYTES"
    "SGLANG_TP_SIZE=$SGLANG_TP_SIZE"
    "SGLANG_LAYOUT=$SGLANG_LAYOUT"
    "SGLANG_CUDA_VISIBLE_DEVICES=$SGLANG_CUDA_VISIBLE_DEVICES"
    "GPU_DEVICE_NAMES=$GPU_DEVICE_NAMES"
    "GPU_NCCL_SOCKET_IFNAME=$GPU_NCCL_SOCKET_IFNAME"
    "GPU_GLOO_SOCKET_IFNAME=$GPU_GLOO_SOCKET_IFNAME"
    "RDMA_RUNTIME_LIB_DIR=$RDMA_RUNTIME_LIB_DIR"
    "RDMA_PROVIDER_LIB_DIR=$RDMA_PROVIDER_LIB_DIR"
    "RDMA_VERBS_DRIVERS=$RDMA_VERBS_DRIVERS"
    "PYTHON_OVERLAY_DIR=$PYTHON_OVERLAY_DIR"
    "CUDA_HOME=$CUDA_HOME"
    "XDG_CACHE_HOME=$XDG_CACHE_HOME"
    "TORCH_EXTENSIONS_DIR=$TORCH_EXTENSIONS_DIR"
    "TVM_FFI_CACHE_DIR=$TVM_FFI_CACHE_DIR"
    "RUNTIME_LIB_DIR=$RUNTIME_LIB_DIR"
    "FLUXON_STALE_NODE0_SHM_PATH=${FLUXON_STALE_NODE0_SHM_PATH:-}"
    "FLUXON_STALE_NODE1_SHM_PATH=${FLUXON_STALE_NODE1_SHM_PATH:-}"
    "FLUXON_STALE_CPU_SHM_PATH=${FLUXON_STALE_CPU_SHM_PATH:-}"
    "MOONCAKE_OFFLOAD_STORAGE_BACKEND_DESCRIPTOR=${MOONCAKE_OFFLOAD_STORAGE_BACKEND_DESCRIPTOR:-}"
    "MOONCAKE_OFFLOAD_FILE_STORAGE_PATH=${MOONCAKE_OFFLOAD_FILE_STORAGE_PATH:-}"
    "MOONCAKE_OFFLOAD_LOCAL_BUFFER_SIZE_BYTES=${MOONCAKE_OFFLOAD_LOCAL_BUFFER_SIZE_BYTES:-}"
    "MOONCAKE_OFFLOAD_TOTAL_SIZE_LIMIT_BYTES=${MOONCAKE_OFFLOAD_TOTAL_SIZE_LIMIT_BYTES:-}"
    "MOONCAKE_OFFLOAD_BUCKET_MAX_TOTAL_SIZE=${MOONCAKE_OFFLOAD_BUCKET_MAX_TOTAL_SIZE:-}"
    "MOONCAKE_OFFLOAD_BUCKET_EVICTION_POLICY=${MOONCAKE_OFFLOAD_BUCKET_EVICTION_POLICY:-}"
    "MOONCAKE_OFFLOAD_USE_URING=${MOONCAKE_OFFLOAD_USE_URING:-}"
  )
  tmux new-session -d -s "$session" "$(printf '%q ' env "${preserved_env[@]}" "$@") >>$(printf '%q' "$log_file") 2>&1"
  echo "started $session; log=$log_file"
}

stop_session() {
  local session="$1"
  tmux kill-session -t "$session" 2>/dev/null || true
}

show_session() {
  local session="$1"
  if session_exists "$session"; then
    echo "running $session"
  else
    echo "stopped $session"
  fi
}

is_true() {
  case "${1,,}" in
    1|true|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}

find_open_fds_under_path() {
  local path="$1"
  local fd target
  for fd in /proc/[0-9]*/fd/*; do
    target="$(readlink "$fd" 2>/dev/null || true)"
    case "$target" in
      "$path"|"$path"/*) printf '%s -> %s\n' "$fd" "$target" ;;
    esac
  done
}

find_deleted_fluxon_shm_holders() {
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP +L1 2>/dev/null \
      | grep -E '/dev/shm/.*(sglang_fluxon_current_cpu_remote|mmap\.file)' \
      || true
    return
  fi
  local fd target
  for fd in /proc/[0-9]*/fd/*; do
    target="$(readlink "$fd" 2>/dev/null || true)"
    if [[ "$target" == /dev/shm/* \
      && "$target" == *" (deleted)" \
      && ( "$target" == *sglang_fluxon_current_cpu_remote* \
        || "$target" == *mmap.file* ) ]]; then
      printf '%s -> %s\n' "$fd" "$target"
    fi
  done
}

cleanup_stale_fluxon_shm() {
  local role="$1"
  local expected_bytes="$2"
  local planned_bytes="$3"
  local path
  case "$role" in
    node0) path="${FLUXON_STALE_NODE0_SHM_PATH:-/dev/shm/sglang_fluxon_current_cpu_remote/fluxon_f1}" ;;
    node1) path="${FLUXON_STALE_NODE1_SHM_PATH:-/dev/shm/sglang_fluxon_current_cpu_remote/fluxon_f2}" ;;
    cpu) path="${FLUXON_STALE_CPU_SHM_PATH:-/dev/shm/sglang_fluxon_current_cpu_remote/fluxon_cpu}" ;;
    *) echo "invalid stale-shm cleanup role: $role" >&2; exit 2 ;;
  esac

  if is_true "$CLEAN_STALE_FLUXON_SHM" && [[ -e "$path" ]]; then
    local mmap_file="$path/fluxon-sglang-l13-single/mmap.file"
    local open_fds
    if command -v lsof >/dev/null 2>&1; then
      open_fds="$(lsof +D "$path" 2>/dev/null || true)"
    else
      open_fds="$(find_open_fds_under_path "$path")"
    fi
    if [[ -n "$open_fds" ]]; then
      echo "refusing to delete active Fluxon shm: $path" >&2
      printf '%s\n' "$open_fds" >&2
      exit 1
    fi
    if [[ ! -f "$mmap_file" ]]; then
      echo "refusing to delete unexpected Fluxon shm layout: $path" >&2
      exit 1
    fi
    local actual_bytes
    actual_bytes="$(stat -c %s "$mmap_file")"
    if [[ "$actual_bytes" != "$expected_bytes" ]]; then
      echo "refusing to delete Fluxon shm with unexpected mmap size: path=$mmap_file expected=$expected_bytes actual=$actual_bytes" >&2
      exit 1
    fi
    rm -rf -- "$path"
    echo "removed stale Fluxon shm before Mooncake start: role=$role bytes=$actual_bytes path=$path"
  fi

  # A Fluxon side worker can outlive its owner, unlink mmap.file, and keep all
  # tmpfs pages charged to the cgroup.  A pathname-only check cannot see that
  # case; starting a same-sized Mooncake segment would briefly require both
  # mappings and can OOM the node.
  local deleted_fluxon_holders
  deleted_fluxon_holders="$(find_deleted_fluxon_shm_holders)"
  if [[ -n "$deleted_fluxon_holders" ]]; then
    echo "refusing Mooncake start while deleted Fluxon shm is still open: role=$role" >&2
    printf '%s\n' "$deleted_fluxon_holders" >&2
    exit 1
  fi

  local memory_max_file=/sys/fs/cgroup/memory.max
  local memory_current_file=/sys/fs/cgroup/memory.current
  local memory_v1_max_file=/sys/fs/cgroup/memory/memory.limit_in_bytes
  local memory_v1_current_file=/sys/fs/cgroup/memory/memory.usage_in_bytes
  local required=$(( planned_bytes + MOONCAKE_MEMORY_SAFETY_BYTES ))
  if [[ -r "$memory_max_file" && -r "$memory_current_file" ]]; then
    local memory_max memory_current
    memory_max="$(cat "$memory_max_file")"
    memory_current="$(cat "$memory_current_file")"
    if [[ "$memory_max" != max ]] && (( memory_current + required > memory_max )); then
      echo "insufficient cgroup headroom for Mooncake segment: role=$role current=$memory_current planned=$planned_bytes safety=$MOONCAKE_MEMORY_SAFETY_BYTES max=$memory_max" >&2
      exit 1
    fi
    echo "Mooncake memory preflight passed: role=$role current=$memory_current planned=$planned_bytes safety=$MOONCAKE_MEMORY_SAFETY_BYTES max=$memory_max"
  elif [[ -r "$memory_v1_max_file" && -r "$memory_v1_current_file" ]]; then
    local memory_max memory_current
    memory_max="$(cat "$memory_v1_max_file")"
    memory_current="$(cat "$memory_v1_current_file")"
    if (( memory_current + required > memory_max )); then
      echo "insufficient cgroup-v1 headroom for Mooncake segment: role=$role current=$memory_current planned=$planned_bytes safety=$MOONCAKE_MEMORY_SAFETY_BYTES max=$memory_max" >&2
      exit 1
    fi
    echo "Mooncake cgroup-v1 memory preflight passed: role=$role current=$memory_current planned=$planned_bytes safety=$MOONCAKE_MEMORY_SAFETY_BYTES max=$memory_max"
  fi

  if [[ -r /proc/meminfo ]]; then
    local mem_available_kib mem_available_bytes
    mem_available_kib="$(awk '$1 == "MemAvailable:" { print $2; exit }' /proc/meminfo)"
    if [[ "$mem_available_kib" =~ ^[0-9]+$ ]]; then
      mem_available_bytes=$(( mem_available_kib * 1024 ))
      if (( mem_available_bytes < required )); then
        echo "insufficient host headroom for Mooncake segment: role=$role available=$mem_available_bytes planned=$planned_bytes safety=$MOONCAKE_MEMORY_SAFETY_BYTES" >&2
        exit 1
      fi
      echo "Mooncake host memory preflight passed: role=$role available=$mem_available_bytes planned=$planned_bytes safety=$MOONCAKE_MEMORY_SAFETY_BYTES"
    fi
  fi
}

common_env() {
  unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
  # Fluxon launchers intentionally persist these in the tmux server's global
  # environment.  A later Mooncake session inherits them unless the child
  # clears them again after tmux has constructed its environment.
  unset SGLANG_FLUXON_HOSTLESS_PAGE_INDEX_VALIDATE_EVERY_N
  unset SGLANG_FLUXON_HOSTLESS_EVICTION_WRITE_STREAM
  unset SGLANG_FLUXON_HOSTLESS_LAYER_BATCH_DMA
  unset SGLANG_FLUXON_HOSTLESS_BACKGROUND_DMA_SUBMIT
  export no_proxy="127.0.0.1,localhost,$GPU0_IP,$GPU1_IP,$CPU_IP,10.0.0.0/8,10.233.0.0/16"
  export NO_PROXY="$no_proxy"
  export PATH="$VENV/bin:$PATH"
  local cuda_ld_path=""
  if [[ -n "$CUDA_HOME" ]]; then
    export PATH="$CUDA_HOME/bin:$PATH"
    cuda_ld_path="$CUDA_HOME/lib64:"
  fi
  export LD_LIBRARY_PATH="${cuda_ld_path}$RUNTIME_LIB_DIR:$MOONCAKE_PACKAGE:$MOONCAKE_AUDITWHEEL_LIBS:$RDMA_PROVIDER_LIB_DIR:$RDMA_RUNTIME_LIB_DIR:/usr/lib/x86_64-linux-gnu:/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
  export IBV_DRIVERS_PATH="$RDMA_PROVIDER_LIB_DIR"
  if [[ -n "$RDMA_VERBS_DRIVERS" ]]; then
    export IBV_DRIVERS="$RDMA_VERBS_DRIVERS"
  fi
  export PYTHONUNBUFFERED=1
  export PYTHONDONTWRITEBYTECODE=1
  unset PYTHONPATH
  if [[ -n "$PYTHON_OVERLAY_DIR" ]]; then
    export PYTHONPATH="$PYTHON_OVERLAY_DIR"
  fi
  if [[ -n "$XDG_CACHE_HOME" ]]; then
    export XDG_CACHE_HOME
  fi
  if [[ -n "$TORCH_EXTENSIONS_DIR" ]]; then
    export TORCH_EXTENSIONS_DIR
  fi
  if [[ -n "$TVM_FFI_CACHE_DIR" ]]; then
    export TVM_FFI_CACHE_DIR
  fi
}

control_role() {
  local action="${1:-status}"
  local metadata_session="${SESSION_PREFIX}_metadata"
  local master_session="${SESSION_PREFIX}_master"
  case "$action" in
    start)
      require_executable "$VENV/bin/python"
      require_executable "$VENV/bin/mooncake_master"
      start_session "$metadata_session" "$LOG_DIR/metadata.log" "$0" control run_metadata
      start_session "$master_session" "$LOG_DIR/master.log" "$0" control run_master
      ;;
    run_metadata)
      common_env
      exec "$VENV/bin/python" -m mooncake.http_metadata_server --port "$METADATA_PORT"
      ;;
    run_master)
      common_env
      local -a offload_args=()
      if is_true "$ENABLE_OFFLOAD"; then
        offload_args+=(--enable_offload=true)
      fi
      exec "$VENV/bin/python" "$VENV/bin/mooncake_master" \
        --rpc_port="$MASTER_PORT" \
        --metrics_port="$MASTER_METRICS_PORT" \
        --eviction_high_watermark_ratio="$EVICTION_HIGH_WATERMARK_RATIO" \
        "${offload_args[@]}" \
        --logtostderr=1
      ;;
    stop)
      stop_session "$master_session"
      stop_session "$metadata_session"
      ;;
    status)
      show_session "$metadata_session"
      show_session "$master_session"
      ;;
    *) usage; exit 2 ;;
  esac
}

cpu_role() {
  local action="${1:-status}"
  local session="${SESSION_PREFIX}_cpu_store"
  case "$action" in
    start)
      require_executable "$MOONCAKE_PACKAGE/mooncake_client"
      require_file "$RUNTIME_LIB_DIR/libcudart.so.12"
      cleanup_stale_fluxon_shm cpu "$FLUXON_STALE_CPU_MMAP_BYTES" "$CPU_SEGMENT_BYTES"
      start_session "$session" "$LOG_DIR/cpu_store.log" "$0" cpu run
      ;;
    run)
      common_env
      export LD_LIBRARY_PATH="$RUNTIME_LIB_DIR:$MOONCAKE_PACKAGE:$MOONCAKE_AUDITWHEEL_LIBS:$LD_LIBRARY_PATH"
      ulimit -l unlimited 2>/dev/null || true
      local -a offload_args=()
      if is_true "$ENABLE_OFFLOAD"; then
        if [[ -z "${MOONCAKE_OFFLOAD_FILE_STORAGE_PATH:-}" ]]; then
          echo "ENABLE_OFFLOAD requires MOONCAKE_OFFLOAD_FILE_STORAGE_PATH" >&2
          exit 2
        fi
        offload_args+=(--enable_offload=true)
      fi
      exec "$MOONCAKE_PACKAGE/mooncake_client" \
        --host="$CPU_IP" \
        --port="$CPU_STORE_PORT" \
        --master_server_address="$GPU0_IP:$MASTER_PORT" \
        --metadata_server="http://$GPU0_IP:$METADATA_PORT/metadata" \
        --protocol=rdma \
        --device_names="$MOONCAKE_CPU_DEVICE_NAMES" \
        --global_segment_size="$CPU_SEGMENT_BYTES" \
        "${offload_args[@]}" \
        --threads=32 \
        --enable_http_server=true \
        --http_port="$CPU_STORE_HTTP_PORT" \
        --logtostderr=1
      ;;
    stop) stop_session "$session" ;;
    status) show_session "$session" ;;
    *) usage; exit 2 ;;
  esac
}

gpu_role() {
  local action="${1:-status}"
  local node="${2:-}"
  local instance="${3:-a}"
  if [[ "$node" != node0 && "$node" != node1 ]]; then
    echo "gpu role requires node0 or node1" >&2
    exit 2
  fi
  local node_ip="$GPU0_IP"
  local session="${SESSION_PREFIX}_node0"
  local session_a="${SESSION_PREFIX}_node0_a"
  local session_b="${SESSION_PREFIX}_node0_b"
  local store_session="${SESSION_PREFIX}_node0_store"
  local port_a="$GPU0_SGLANG_PORT"
  local port_b="$GPU0_SGLANG_PORT_B"
  if [[ "$node" == node1 ]]; then
    node_ip="$GPU1_IP"
    session="${SESSION_PREFIX}_node1"
    session_a="${SESSION_PREFIX}_node1_a"
    session_b="${SESSION_PREFIX}_node1_b"
    store_session="${SESSION_PREFIX}_node1_store"
    port_a="$GPU1_SGLANG_PORT"
    port_b="$GPU1_SGLANG_PORT_B"
  fi
  local -a selected_gpus=()
  IFS=',' read -r -a selected_gpus <<<"$SGLANG_CUDA_VISIBLE_DEVICES"
  case "$action" in
    start)
      require_executable "$VENV/bin/python"
      require_file "$MODEL_PATH/config.json"
      case "$SGLANG_LAYOUT" in
        tp2)
          cleanup_stale_fluxon_shm "$node" "$FLUXON_STALE_GPU_MMAP_BYTES" "$GPU_HOST_CACHE_TOTAL_BYTES"
          start_session "$session" "$LOG_DIR/${node}_sglang.log" "$0" gpu run "$node" a
          ;;
        tp1x2)
          require_executable "$MOONCAKE_PACKAGE/mooncake_client"
          require_file "$RUNTIME_LIB_DIR/libcudart.so.12"
          if [[ "${#selected_gpus[@]}" != 2 || "${selected_gpus[0]}" == "${selected_gpus[1]}" ]]; then
            echo "tp1x2 requires exactly two distinct CUDA devices" >&2
            exit 2
          fi
          cleanup_stale_fluxon_shm "$node" "$FLUXON_STALE_GPU_MMAP_BYTES" \
            "$((GPU_HOST_CACHE_TOTAL_BYTES + GPU_SEGMENT_BYTES))"
          start_session "$store_session" "$LOG_DIR/${node}_store.log" "$0" gpu run_store "$node"
          local store_ready=0
          for _ in $(seq 1 180); do
            if curl -fsS --max-time 2 "http://127.0.0.1:$GPU_STORE_HTTP_PORT/metrics" >/dev/null 2>&1; then
              store_ready=1
              break
            fi
            if ! session_exists "$store_session"; then
              tail -n 120 "$LOG_DIR/${node}_store.log" >&2 || true
              exit 1
            fi
            sleep 1
          done
          if [[ "$store_ready" != 1 ]]; then
            echo "timeout waiting for node-local Mooncake store on $node" >&2
            tail -n 120 "$LOG_DIR/${node}_store.log" >&2 || true
            exit 1
          fi
          start_session "$session_a" "$LOG_DIR/${node}_sglang_a.log" "$0" gpu run "$node" a
          start_session "$session_b" "$LOG_DIR/${node}_sglang_b.log" "$0" gpu run "$node" b
          ;;
      esac
      ;;
    run_store)
      common_env
      ulimit -l unlimited 2>/dev/null || true
      exec "$MOONCAKE_PACKAGE/mooncake_client" \
        --host="$node_ip" \
        --port="$GPU_STORE_PORT" \
        --master_server_address="$GPU0_IP:$MASTER_PORT" \
        --metadata_server="http://$GPU0_IP:$METADATA_PORT/metadata" \
        --protocol=rdma \
        --device_names="$GPU_DEVICE_NAMES" \
        --global_segment_size="$GPU_SEGMENT_BYTES" \
        --threads=32 \
        --enable_http_server=true \
        --http_port="$GPU_STORE_HTTP_PORT" \
        --logtostderr=1
      ;;
    run)
      common_env
      if [[ "$instance" != a && "$instance" != b ]]; then
        echo "gpu run requires instance a or b" >&2
        exit 2
      fi
      if [[ ! "$SGLANG_MAX_TOTAL_TOKENS" =~ ^[1-9][0-9]*$ ]]; then
        echo "SGLANG_MAX_TOTAL_TOKENS must be a positive integer" >&2
        exit 2
      fi
      case "$HICACHE_WRITE_POLICY" in
        write_back|write_through|write_through_selective) ;;
        *) echo "invalid HICACHE_WRITE_POLICY: $HICACHE_WRITE_POLICY" >&2; exit 2 ;;
      esac
      if [[ ! "$HICACHE_STORAGE_METADATA_CAPACITY" =~ ^[0-9]+$ ]]; then
        echo "HICACHE_STORAGE_METADATA_CAPACITY must be a non-negative integer" >&2
        exit 2
      fi
      local -a hicache_capacity_args=()
      if [[ "$HICACHE_SIZE_GIB" =~ ^[1-9][0-9]*$ ]]; then
        hicache_capacity_args+=(--hicache-size "$HICACHE_SIZE_GIB")
      elif [[ "$HICACHE_SIZE_GIB" == 0 ]] \
        && [[ "$HICACHE_RATIO" =~ ^[0-9]+([.][0-9]+)?$ ]] \
        && awk -v value="$HICACHE_RATIO" 'BEGIN { exit !(value > 0) }'; then
        hicache_capacity_args+=(--hicache-size 0 --hicache-ratio "$HICACHE_RATIO")
      else
        echo "HICACHE_SIZE_GIB must be a positive integer, or 0 with a positive HICACHE_RATIO" >&2
        exit 2
      fi
      # SGLang's internal get_open_port() interprets an exported SGLANG_PORT
      # as the first IPC port candidate.  Keep the launcher value for --port,
      # but do not let scheduler IPC reserve the HTTP port before Uvicorn.
      local launch_sglang_port="$port_a"
      local visible_gpus="$SGLANG_CUDA_VISIBLE_DEVICES"
      local hicache_storage_extra_config='{"prefetch_threshold":256}'
      if [[ "$SGLANG_LAYOUT" == tp1x2 ]]; then
        if [[ "${#selected_gpus[@]}" != 2 ]]; then
          echo "tp1x2 requires exactly two CUDA devices" >&2
          exit 2
        fi
        visible_gpus="${selected_gpus[0]}"
        if [[ "$instance" == b ]]; then
          launch_sglang_port="$port_b"
          visible_gpus="${selected_gpus[1]}"
        fi
        hicache_storage_extra_config="{\"prefetch_threshold\":256,\"standalone_storage\":true,\"client_server_address\":\"$node_ip:$GPU_STORE_PORT\"}"
      fi
      unset SGLANG_PORT
      export CUDA_VISIBLE_DEVICES="$visible_gpus"
      export MC_TCP_ENABLE_CONNECTION_POOL=true
      export MC_TE_METRIC=1
      export MC_MS_AUTO_DISC=0
      export NCCL_SOCKET_IFNAME="$GPU_NCCL_SOCKET_IFNAME"
      export GLOO_SOCKET_IFNAME="$GPU_GLOO_SOCKET_IFNAME"
      export NCCL_IB_HCA="$GPU_DEVICE_NAMES"
      export NCCL_COLLNET_ENABLE=0
      export NCCL_SHARP_DISABLE=1
      export MOONCAKE_MASTER="$GPU0_IP:$MASTER_PORT"
      export MOONCAKE_MASTER_METRICS_PORT="$MASTER_METRICS_PORT"
      export MOONCAKE_TE_META_DATA_SERVER="http://$GPU0_IP:$METADATA_PORT/metadata"
      export MOONCAKE_PROTOCOL=rdma
      export MOONCAKE_DEVICE="$GPU_DEVICE_NAMES"
      export MOONCAKE_GLOBAL_SEGMENT_SIZE="$GPU_SEGMENT_BYTES"
      export MOONCAKE_LOCAL_HOSTNAME="$node_ip"
      export MOONCAKE_CHECK_SERVER=0
      if [[ "$SGLANG_LAYOUT" == tp1x2 ]]; then
        export MOONCAKE_GLOBAL_SEGMENT_SIZE=0
        export MOONCAKE_STANDALONE_STORAGE=1
        export MOONCAKE_CLIENT="$node_ip:$GPU_STORE_PORT"
      fi
      export SGLANG_ENABLE_UNIFIED_RADIX_TREE=1
      export SGLANG_SKIP_SGL_KERNEL_VERSION_CHECK=1
      export SGLANG_ENABLE_HEALTH_ENDPOINT_GENERATION=1
      local -a overlap_args=()
      if is_true "$SGLANG_DISABLE_OVERLAP_SCHEDULE"; then
        overlap_args+=(--disable-overlap-schedule)
      fi
      exec "$VENV/bin/python" -m sglang.launch_server \
        --model-path "$MODEL_PATH" \
        --host 0.0.0.0 \
        --port "$launch_sglang_port" \
        --tensor-parallel-size "$SGLANG_TP_SIZE" \
        --mem-fraction-static 0.50 \
        --watchdog-timeout 1200 \
        --trust-remote-code \
        --enable-hierarchical-cache \
        "${hicache_capacity_args[@]}" \
        --hicache-write-policy "$HICACHE_WRITE_POLICY" \
        --hicache-io-backend direct \
        --hicache-mem-layout page_first_direct \
        --hicache-storage-backend mooncake \
        --hicache-storage-metadata-capacity "$HICACHE_STORAGE_METADATA_CAPACITY" \
        --hicache-storage-prefetch-policy timeout \
        --hicache-storage-backend-extra-config "$hicache_storage_extra_config" \
        --enable-metrics \
        --enable-cache-report \
        --page-size 64 \
        --max-total-tokens "$SGLANG_MAX_TOTAL_TOKENS" \
        "${overlap_args[@]}"
      ;;
    stop)
      stop_session "$session_b"
      stop_session "$session_a"
      stop_session "$session"
      stop_session "$store_session"
      ;;
    status)
      if [[ "$SGLANG_LAYOUT" == tp1x2 ]]; then
        show_session "$store_session"
        show_session "$session_a"
        show_session "$session_b"
      else
        show_session "$session"
      fi
      ;;
    *) usage; exit 2 ;;
  esac
}

router_role() {
  local action="${1:-status}"
  local session="${SESSION_PREFIX}_router"
  case "$action" in
    start)
      require_executable "$VENV/bin/python"
      start_session "$session" "$LOG_DIR/router.log" "$0" router run
      ;;
    run)
      common_env
      export CUDA_VISIBLE_DEVICES=
      local -a worker_urls=(
        "http://$GPU0_ROUTER_WORKER_HOST:$GPU0_ROUTER_WORKER_PORT"
        "http://$GPU1_ROUTER_WORKER_HOST:$GPU1_ROUTER_WORKER_PORT"
      )
      if [[ "$SGLANG_LAYOUT" == tp1x2 ]]; then
        worker_urls+=(
          "http://$GPU0_ROUTER_WORKER_HOST:$GPU0_ROUTER_WORKER_PORT_B"
          "http://$GPU1_ROUTER_WORKER_HOST:$GPU1_ROUTER_WORKER_PORT_B"
        )
      fi
      exec "$VENV/bin/python" -m sglang_router.launch_router \
        --host 0.0.0.0 \
        --port "$ROUTER_PORT" \
        --prometheus-host 0.0.0.0 \
        --prometheus-port "$ROUTER_METRICS_PORT" \
        --worker-urls "${worker_urls[@]}" \
        --model-path "$MODEL_PATH" \
        --tokenizer-path "$MODEL_PATH" \
        --policy "$ROUTER_POLICY" \
        --log-level info
      ;;
    stop) stop_session "$session" ;;
    status) show_session "$session" ;;
    *) usage; exit 2 ;;
  esac
}

workload_role() {
  local action="${1:-status}"
  local run_tag="${2:-}"
  local session="${SESSION_PREFIX}_workload"
  case "$action" in
    start)
      if [[ ! "$run_tag" =~ ^[a-zA-Z0-9_]+$ ]]; then
        echo "workload start requires an alphanumeric/underscore run_tag" >&2
        exit 2
      fi
      require_file "$WORKLOAD_DIR/workload_agent_multiturn_long_context.py"
      require_file "$STATE_FILE"
      start_session "$session" "$LOG_DIR/workload_${run_tag}.log" "$0" workload run "$run_tag"
      ;;
    run)
      if [[ ! "$run_tag" =~ ^[a-zA-Z0-9_]+$ ]]; then
        exit 2
      fi
      common_env
      cd "$WORKLOAD_DIR"
      exec "$VENV/bin/python" workload_agent_multiturn_long_context.py \
        --cluster-state "$STATE_FILE" \
        --node0-base-url "http://$GPU0_IP:$GPU0_SGLANG_PORT" \
        --node1-base-url "http://$GPU1_IP:$GPU1_SGLANG_PORT" \
        --node1-ssh "-p 2222 -o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=5 root@$GPU1_IP" \
        --run-tag "$run_tag" \
        --output-root "$BASE_DIR/results" \
        --request-timeout-s 300 \
        --phase-mode router \
        --router-base-url "http://$GPU0_IP:$ROUTER_PORT" \
        --base-node node0 \
        --measure-node node1 \
        --seed-node node0 \
        --sessions 96 \
        --turns 12 \
        --agent-groups 32 \
        --system-tokens 8192 \
        --user-tokens 128 \
        --tool-result-tokens 256 \
        --assistant-history-tokens 128 \
        --output-len 64 \
        --concurrency 16 \
        --schedule round_barrier \
        --turn-filler-ratio 0.0 \
        --assistant-history-mode synthetic \
        --clear-storage-backend \
        --wait-storage-settle
      ;;
    stop) stop_session "$session" ;;
    status) show_session "$session" ;;
    *) usage; exit 2 ;;
  esac
}

role="${1:-}"
action="${2:-status}"
shift $(( $# > 0 ? 1 : 0 ))
shift $(( $# > 0 ? 1 : 0 ))

case "$role" in
  control) control_role "$action" "$@" ;;
  cpu) cpu_role "$action" "$@" ;;
  gpu) gpu_role "$action" "$@" ;;
  router) router_role "$action" "$@" ;;
  workload) workload_role "$action" "$@" ;;
  *) usage; exit 2 ;;
esac
