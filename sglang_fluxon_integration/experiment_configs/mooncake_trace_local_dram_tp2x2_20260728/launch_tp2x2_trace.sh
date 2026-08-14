#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
base_launcher="${BASE_LAUNCHER:-$script_dir/base_launcher_tp2x2.sh}"

role="${1:-}"
action="${2:-status}"
gpu_node="${3:-}"
group="${MOONCAKE_EXPERIMENT_GROUP:-}"
run_id="${MOONCAKE_EXPERIMENT_RUN_ID:-}"
gpu_ip="${MOONCAKE_GPU_IP:-}"
cpu_ip="${MOONCAKE_CPU_IP:-}"
gpu_hostname="${MOONCAKE_GPU_HOSTNAME:-}"
cpu_hostname="${MOONCAKE_CPU_HOSTNAME:-}"
cpu_ssh_port="${MOONCAKE_CPU_SSH_PORT:-}"
cpu_hcas="${MOONCAKE_CPU_DEVICE_NAMES:-}"
allow_gpu_capable_remote_cpu="${MOONCAKE_ALLOW_GPU_CAPABLE_REMOTE_CPU:-0}"
gpu_capable_remote_port=30448
gpu_capable_remote_ip=10.233.114.150
gpu_capable_remote_hostname=job-f8df1d36c3a6-20260728034352-6f5fb9dd4d-hl89q

case "$role" in
  control|gpu|cpu|router) ;;
  *) echo "role must be control, gpu, cpu, or router" >&2; exit 2 ;;
esac
case "$group" in
  A) expected_hicache_gb=16; expected_hicache_ratio=2.0; expected_rank_bytes=16000745472; expected_instance_segment=105437462528; expected_alignment_slack=0 ;;
  B) expected_hicache_gb=32; expected_hicache_ratio=2.0; expected_rank_bytes=32001490944; expected_instance_segment=73435971584; expected_alignment_slack=0 ;;
  C) expected_hicache_gb=48; expected_hicache_ratio=2.0; expected_rank_bytes=48002236416; expected_instance_segment=41434480640; expected_alignment_slack=0 ;;
  D) expected_hicache_gb=0; expected_hicache_ratio=4.65984; expected_rank_bytes=68716855296; expected_instance_segment=0; expected_alignment_slack=10485760 ;;
  E) expected_hicache_gb=0; expected_hicache_ratio=0; expected_rank_bytes=68702698496; expected_instance_segment=33556480; expected_alignment_slack=0 ;;
  *) echo "MOONCAKE_EXPERIMENT_GROUP must be A, B, C, D, or E" >&2; exit 2 ;;
esac
if [[ "$group" == E ]]; then
  expected_router_worker0_port=31101
  expected_router_worker1_port=31102
else
  expected_router_worker0_port=31001
  expected_router_worker1_port=31002
fi
if [[ ! "$run_id" =~ ^[a-zA-Z0-9_]+$ ]]; then
  echo "MOONCAKE_EXPERIMENT_RUN_ID must contain only letters, digits, and underscores" >&2
  exit 2
fi
if [[ ! "$gpu_ip" =~ ^[0-9]+([.][0-9]+){3}$ ]] \
  || [[ ! "$cpu_ip" =~ ^[0-9]+([.][0-9]+){3}$ ]]; then
  echo "MOONCAKE_GPU_IP and MOONCAKE_CPU_IP must be IPv4 addresses" >&2
  exit 2
fi
if [[ ! "$gpu_hostname" =~ ^[a-zA-Z0-9][a-zA-Z0-9._-]*$ ]] \
  || [[ ! "$cpu_hostname" =~ ^[a-zA-Z0-9][a-zA-Z0-9._-]*$ ]]; then
  echo "MOONCAKE_GPU_HOSTNAME and MOONCAKE_CPU_HOSTNAME must be explicit hostnames" >&2
  exit 2
fi
if [[ "$gpu_hostname" == "$cpu_hostname" || "$gpu_ip" == "$cpu_ip" ]]; then
  echo "GPU and remote CPU identities must be distinct" >&2
  exit 2
fi
if [[ ! "$cpu_ssh_port" =~ ^[1-9][0-9]{0,4}$ ]] || (( cpu_ssh_port > 65535 )); then
  echo "MOONCAKE_CPU_SSH_PORT must be an explicit valid port" >&2
  exit 2
fi
if [[ "$allow_gpu_capable_remote_cpu" != 0 \
  && "$allow_gpu_capable_remote_cpu" != 1 ]]; then
  echo "MOONCAKE_ALLOW_GPU_CAPABLE_REMOTE_CPU must be 0 or 1" >&2
  exit 2
fi
if [[ "$cpu_ssh_port" == 30245 || "$cpu_ip" == 10.233.114.145 ]]; then
  echo "refusing known GPU node as remote CPU: ssh_port=$cpu_ssh_port ip=$cpu_ip" >&2
  exit 2
fi
if [[ "$allow_gpu_capable_remote_cpu" == 1 ]]; then
  if [[ "$cpu_ssh_port" != "$gpu_capable_remote_port" \
    || "$cpu_ip" != "$gpu_capable_remote_ip" \
    || "$cpu_hostname" != "$gpu_capable_remote_hostname" ]]; then
    echo "GPU-capable remote override requires exact 30448 identity: port=$gpu_capable_remote_port ip=$gpu_capable_remote_ip hostname=$gpu_capable_remote_hostname" >&2
    exit 2
  fi
elif [[ "$cpu_ssh_port" == "$gpu_capable_remote_port" \
  || "$cpu_ip" == "$gpu_capable_remote_ip" \
  || "$cpu_hostname" == "$gpu_capable_remote_hostname" ]]; then
  echo "refusing GPU-capable 30448 without explicit MOONCAKE_ALLOW_GPU_CAPABLE_REMOTE_CPU=1" >&2
  exit 2
fi
if [[ -z "$cpu_hcas" ]]; then
  echo "MOONCAKE_CPU_DEVICE_NAMES must be explicitly discovered on the remote CPU" >&2
  exit 2
fi
if [[ ! -x "$base_launcher" ]]; then
  echo "missing executable base launcher: $base_launcher" >&2
  exit 1
fi
if [[ "$group" == E && "$role" == gpu ]]; then
  echo "group E GPU workers must use launch_vllm_lmcache_tp2x2.sh" >&2
  exit 2
fi

if [[ -d /public/mjq/.venv_sglang_fluxon ]]; then
  shared_mjq=/public/mjq
  model_path=/public/mjq/models/Qwen3-VL-8B-Instruct
elif [[ -d /storage/mjq/.venv_sglang_fluxon ]]; then
  shared_mjq=/storage/mjq
  model_path=/storage/mjq/models/Qwen3-VL-8B-Instruct
else
  echo "neither /public/mjq nor /storage/mjq runtime is available" >&2
  exit 1
fi

instance_segment="${MOONCAKE_INSTANCE_SEGMENT_BYTES:-$expected_instance_segment}"
rank_bytes="${MOONCAKE_HICACHE_RANK_BYTES:-$expected_rank_bytes}"
hicache_gb="${MOONCAKE_HICACHE_SIZE_GB:-$expected_hicache_gb}"
hicache_ratio="${MOONCAKE_HICACHE_RATIO:-$expected_hicache_ratio}"
if [[ "$hicache_gb" != "$expected_hicache_gb" ]]; then
  echo "group $group requires hicache-size=$expected_hicache_gb, got $hicache_gb" >&2
  exit 2
fi
if [[ "$hicache_ratio" != "$expected_hicache_ratio" ]]; then
  echo "group $group requires hicache-ratio=$expected_hicache_ratio, got $hicache_ratio" >&2
  exit 2
fi
if [[ ! "$instance_segment" =~ ^[0-9]+$ ]]; then
  echo "MOONCAKE_INSTANCE_SEGMENT_BYTES must be a non-negative integer" >&2
  exit 2
fi
if [[ ! "$rank_bytes" =~ ^[1-9][0-9]*$ ]]; then
  echo "MOONCAKE_HICACHE_RANK_BYTES must be a positive integer" >&2
  exit 2
fi
if [[ "$group" != E && $((rank_bytes % 4718592)) != 0 ]]; then
  echo "group $group requires TP2-page-aligned HiCache rank bytes" >&2
  exit 2
fi
if [[ "$group" == D && "$instance_segment" != 0 ]]; then
  echo "group D requires zero local Mooncake segment" >&2
  exit 2
fi
if [[ "$group" == E && "$instance_segment" != "$expected_instance_segment" ]]; then
  echo "group E requires a 16-MiB Mooncake global segment and 1024-byte local buffer per rank" >&2
  exit 2
fi
if [[ ! "$group" =~ ^(D|E)$ && "$instance_segment" == 0 ]]; then
  echo "group $group requires positive local Mooncake segments" >&2
  exit 2
fi
if (( 4 * rank_bytes + 2 * instance_segment + expected_alignment_slack != 274877906944 )); then
  echo "group $group local capacity mismatch: four_rank_bytes=$((4 * rank_bytes)) two_instance_segments=$((2 * instance_segment)) alignment_slack=$expected_alignment_slack" >&2
  exit 2
fi

export BASE_DIR="${MOONCAKE_LOCAL_RUN_DIR:-/tmp/mooncake_trace_local_dram_tp2x2_20260728/$run_id}"
export SESSION_PREFIX="mc_trace_${group}_${run_id}"
if [[ "$role" == gpu ]]; then
  case "$gpu_node" in
    node0)
      instance_port="${MOONCAKE_INSTANCE0_PORT:-31001}"
      instance_gpus="${MOONCAKE_INSTANCE0_GPUS:-0,1}"
      instance_hcas="${MOONCAKE_INSTANCE0_HCAS:-mlx5_0,mlx5_1}"
      ;;
    node1)
      instance_port="${MOONCAKE_INSTANCE1_PORT:-31002}"
      instance_gpus="${MOONCAKE_INSTANCE1_GPUS:-2,3}"
      instance_hcas="${MOONCAKE_INSTANCE1_HCAS:-mlx5_2,mlx5_3}"
      ;;
    *) echo "gpu role requires node0 or node1" >&2; exit 2 ;;
  esac
  cuda_toolkit_root="${MOONCAKE_CUDA_TOOLKIT_ROOT:-/public/zsh/miniconda3}"
  export CUDA_HOME="$BASE_DIR/cuda_home/$gpu_node"
  export XDG_CACHE_HOME="$BASE_DIR/cache/$gpu_node"
  export TORCH_EXTENSIONS_DIR="$BASE_DIR/cache/$gpu_node/torch_extensions"
  export TVM_FFI_CACHE_DIR="$BASE_DIR/cache/$gpu_node/tvm-ffi"
fi
export VENV="$shared_mjq/.venv_sglang_fluxon"
export MODEL_PATH="$model_path"
export GPU0_IP="$gpu_ip"
export GPU1_IP="$gpu_ip"
export CPU_IP="$cpu_ip"
export GPU0_SGLANG_PORT="${MOONCAKE_INSTANCE0_PORT:-31001}"
export GPU1_SGLANG_PORT="${MOONCAKE_INSTANCE1_PORT:-31002}"
export GPU0_ROUTER_WORKER_HOST="${MOONCAKE_ROUTER_WORKER_HOST:-127.0.0.1}"
export GPU1_ROUTER_WORKER_HOST="${MOONCAKE_ROUTER_WORKER_HOST:-127.0.0.1}"
export GPU0_ROUTER_WORKER_PORT="$expected_router_worker0_port"
export GPU1_ROUTER_WORKER_PORT="$expected_router_worker1_port"
if [[ "$role" == gpu ]]; then
  export SGLANG_PORT="$instance_port"
else
  export SGLANG_PORT="$GPU0_SGLANG_PORT"
fi
export ROUTER_PORT="${MOONCAKE_ROUTER_PORT:-32000}"
export ROUTER_METRICS_PORT="${MOONCAKE_ROUTER_METRICS_PORT:-29100}"
export METADATA_PORT="${METADATA_PORT:-8183}"
export MASTER_PORT="${MASTER_PORT:-51081}"
export MASTER_METRICS_PORT="${MASTER_METRICS_PORT:-9143}"
export CPU_STORE_PORT="${CPU_STORE_PORT:-50052}"
export CPU_STORE_HTTP_PORT="${CPU_STORE_HTTP_PORT:-9300}"
export GPU_SEGMENT_BYTES="$instance_segment"
export CPU_SEGMENT_BYTES=274877906944
export GPU_HOST_CACHE_TOTAL_BYTES="$((2 * rank_bytes))"
export HICACHE_SIZE_GIB="$hicache_gb"
export HICACHE_RATIO="$hicache_ratio"
export HICACHE_WRITE_POLICY=write_back
export SGLANG_MAX_TOTAL_TOKENS=200000
export SGLANG_DISABLE_OVERLAP_SCHEDULE=0
export SGLANG_TP_SIZE=2
if [[ "$role" == gpu ]]; then
  export SGLANG_CUDA_VISIBLE_DEVICES="$instance_gpus"
  export GPU_DEVICE_NAMES="$instance_hcas"
else
  export SGLANG_CUDA_VISIBLE_DEVICES=0,1
  export GPU_DEVICE_NAMES=mlx5_0,mlx5_1
fi
export GPU_NCCL_SOCKET_IFNAME="${MOONCAKE_GPU_SOCKET_IFNAME:-tunl0}"
export GPU_GLOO_SOCKET_IFNAME="${MOONCAKE_GPU_SOCKET_IFNAME:-tunl0}"
export MOONCAKE_CPU_DEVICE_NAMES="$cpu_hcas"
export RDMA_RUNTIME_LIB_DIR="$shared_mjq/rdma_runtime_jammy/lib"
export RDMA_PROVIDER_LIB_DIR="$shared_mjq/rdma_runtime_jammy/libibverbs"
export RDMA_VERBS_DRIVERS=mlx5
export PYTHON_OVERLAY_DIR="$script_dir/python_overlay"
export RUNTIME_LIB_DIR="$shared_mjq/mooncake_m1/mooncake_3node_aligned_20260712/runtime_libs"
export EVICTION_HIGH_WATERMARK_RATIO=0.95
export ENABLE_OFFLOAD=0
export CLEAN_STALE_FLUXON_SHM=1
export MOONCAKE_MEMORY_SAFETY_BYTES=17179869184

export FLUXON_STALE_CPU_SHM_PATH="${MOONCAKE_CPU_STALE_SHM_PATH:-}"
export FLUXON_STALE_CPU_MMAP_BYTES="${MOONCAKE_CPU_STALE_MMAP_BYTES:-274877906944}"

preflight_start() {
  local identity_ip="$gpu_ip"
  local identity_hostname="$gpu_hostname"
  if [[ "$role" == cpu ]]; then
    identity_ip="$cpu_ip"
    identity_hostname="$cpu_hostname"
  fi
  if [[ "$(hostname)" != "$identity_hostname" ]]; then
    echo "hostname identity mismatch: role=$role expected=$identity_hostname actual=$(hostname)" >&2
    exit 1
  fi
  if ! tr ' ' '\n' <<<"$(hostname -I)" | grep -Fx "$identity_ip" >/dev/null; then
    echo "hostname identity mismatch: role=$role expected_ip=$identity_ip actual=$(hostname -I)" >&2
    exit 1
  fi
  if [[ "$(findmnt -T /tmp -o FSTYPE -n)" != xfs ]]; then
    echo "/tmp is not the required local XFS/NVMe staging filesystem" >&2
    findmnt -T /tmp >&2
    exit 1
  fi
  if [[ "$role" == gpu ]]; then
    local gpu_count compute_pids gpu_id
    local -a selected_gpus
    gpu_count="$(nvidia-smi -L | wc -l)"
    if (( gpu_count < 4 )); then
      echo "TP2x2 requires at least four visible GPUs, found $gpu_count" >&2
      exit 1
    fi
    IFS=, read -r -a selected_gpus <<<"$SGLANG_CUDA_VISIBLE_DEVICES"
    if (( ${#selected_gpus[@]} != 2 )) || [[ "${selected_gpus[0]}" == "${selected_gpus[1]}" ]]; then
      echo "each TP2 instance requires two distinct GPU indices: $SGLANG_CUDA_VISIBLE_DEVICES" >&2
      exit 1
    fi
    for gpu_id in "${selected_gpus[@]}"; do
      if [[ ! "$gpu_id" =~ ^[0-9]+$ ]] || (( gpu_id >= gpu_count )); then
        echo "invalid selected GPU index: $gpu_id" >&2
        exit 1
      fi
      compute_pids="$(nvidia-smi -i "$gpu_id" --query-compute-apps=pid --format=csv,noheader,nounits | sed '/^[[:space:]]*$/d')"
      if [[ -n "$compute_pids" ]]; then
        echo "selected GPU $gpu_id has compute processes; refusing $gpu_node start: $compute_pids" >&2
        exit 1
      fi
    done
    test -f "$MODEL_PATH/config.json"
  elif [[ "$role" == cpu ]]; then
    local hca state device_path nvidia_device_count nvidia_enumerated_count
    local -a cpu_hca_list
    nvidia_device_count="$(find /dev -maxdepth 1 -name 'nvidia[0-9]*' -printf . 2>/dev/null | wc -c)"
    nvidia_enumerated_count=0
    if command -v nvidia-smi >/dev/null 2>&1; then
      nvidia_enumerated_count="$(nvidia-smi -L 2>/dev/null | sed '/^[[:space:]]*$/d' | wc -l)"
    fi
    if (( nvidia_device_count > 0 || nvidia_enumerated_count > 0 )) \
      && [[ "$allow_gpu_capable_remote_cpu" != 1 ]]; then
      echo "remote CPU exposes NVIDIA GPU device nodes; refusing start" >&2
      exit 1
    fi
    if [[ "$allow_gpu_capable_remote_cpu" == 1 ]]; then
      echo "explicit 30448 CPU-role override active: nvidia_device_count=$nvidia_device_count nvidia_enumerated_count=$nvidia_enumerated_count; remote launcher will not allocate GPUs"
    fi
    IFS=, read -r -a cpu_hca_list <<<"$MOONCAKE_CPU_DEVICE_NAMES"
    if (( ${#cpu_hca_list[@]} == 0 )); then
      echo "remote CPU HCA list is empty" >&2
      exit 1
    fi
    for hca in "${cpu_hca_list[@]}"; do
      device_path="/sys/class/infiniband/$hca/ports/1/state"
      if [[ ! -r "$device_path" ]]; then
        echo "remote CPU HCA state is unavailable: $device_path" >&2
        exit 1
      fi
      state="$(<"$device_path")"
      if [[ "$state" != *ACTIVE* ]]; then
        echo "remote CPU HCA is not ACTIVE: hca=$hca state=$state" >&2
        exit 1
      fi
    done
  elif [[ "$role" == router ]]; then
    test -f "$MODEL_PATH/config.json"
  fi
}

prepare_cuda_home() {
  local targets_root="$cuda_toolkit_root/targets/x86_64-linux"
  test -x "$cuda_toolkit_root/bin/nvcc"
  test -x "$cuda_toolkit_root/nvvm/bin/cicc"
  test -f "$targets_root/include/cuda.h"
  test -f "$targets_root/lib/libcudart.so"
  install -d -m 0755 "$CUDA_HOME"
  install -d -m 0755 "$XDG_CACHE_HOME" "$TORCH_EXTENSIONS_DIR" "$TVM_FFI_CACHE_DIR"
  local name target existing
  for name in bin nvvm include lib64; do
    case "$name" in
      bin) target="$cuda_toolkit_root/bin" ;;
      nvvm) target="$cuda_toolkit_root/nvvm" ;;
      include) target="$targets_root/include" ;;
      lib64) target="$targets_root/lib" ;;
    esac
    if [[ -L "$CUDA_HOME/$name" ]]; then
      existing="$(readlink "$CUDA_HOME/$name")"
      if [[ "$existing" != "$target" ]]; then
        echo "CUDA overlay symlink mismatch: $CUDA_HOME/$name -> $existing, expected $target" >&2
        exit 1
      fi
    elif [[ -e "$CUDA_HOME/$name" ]]; then
      echo "CUDA overlay path exists but is not a symlink: $CUDA_HOME/$name" >&2
      exit 1
    else
      ln -s "$target" "$CUDA_HOME/$name"
    fi
  done
  "$CUDA_HOME/bin/nvcc" --version >/dev/null
}

if [[ "$action" == start ]]; then
  test -f "$RDMA_PROVIDER_LIB_DIR/libmlx5-rdmav34.so"
  test -f "$PYTHON_OVERLAY_DIR/distro/__init__.py"
  if [[ "$role" == gpu ]]; then
    prepare_cuda_home
  fi
  preflight_start
fi

exec "$base_launcher" "$@"
