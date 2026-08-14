#!/usr/bin/env bash
set -euo pipefail

action="${1:-status}"
gpu_node="${2:-}"
group="${MOONCAKE_EXPERIMENT_GROUP:-}"
run_id="${MOONCAKE_EXPERIMENT_RUN_ID:-}"
gpu_ip="${MOONCAKE_GPU_IP:-}"
gpu_hostname="${MOONCAKE_GPU_HOSTNAME:-}"
cpu_ip="${MOONCAKE_CPU_IP:-}"
cpu_hostname="${MOONCAKE_CPU_HOSTNAME:-}"
cpu_ssh_port="${MOONCAKE_CPU_SSH_PORT:-}"
cpu_hcas="${MOONCAKE_CPU_DEVICE_NAMES:-}"
allow_gpu_capable_remote_cpu="${MOONCAKE_ALLOW_GPU_CAPABLE_REMOTE_CPU:-0}"
gpu_capable_remote_port=30448
gpu_capable_remote_ip=10.233.114.150
gpu_capable_remote_hostname=job-f8df1d36c3a6-20260728034352-6f5fb9dd4d-hl89q
overlay="${VLLM_LMCACHE_OVERLAY_DIR:-}"
overlay_manifest_sha="${VLLM_LMCACHE_OVERLAY_MANIFEST_SHA256:-}"
expected_ninja_sha256=696f9628a79d9ce50314cf9556d7cd1a1d1ec52b8fd52828f6f9db1719565b67
expected_ninja_version=1.13.0.git.kitware.jobserver-pipe-1
lmcache_rank_bytes=68702698496
lmcache_rank_gib=63.984374046325684
mooncake_rank_segment_bytes=16777216
mooncake_rank_local_buffer_bytes=1024
if (( 4 * (lmcache_rank_bytes + mooncake_rank_segment_bytes + mooncake_rank_local_buffer_bytes) != 274877906944 )); then
  echo "internal group-E local capacity mismatch" >&2
  exit 1
fi

case "$action" in
  start|stop|status) ;;
  *) echo "action must be start, stop, or status" >&2; exit 2 ;;
esac
case "$gpu_node" in
  node0)
    port="${MOONCAKE_INSTANCE0_PORT:-31001}"
    visible_gpus="${MOONCAKE_INSTANCE0_GPUS:-0,1}"
    device_names="${MOONCAKE_INSTANCE0_HCAS:-mlx5_0,mlx5_1}"
    ;;
  node1)
    port="${MOONCAKE_INSTANCE1_PORT:-31002}"
    visible_gpus="${MOONCAKE_INSTANCE1_GPUS:-2,3}"
    device_names="${MOONCAKE_INSTANCE1_HCAS:-mlx5_2,mlx5_3}"
    ;;
  *) echo "gpu_node must be node0 or node1" >&2; exit 2 ;;
esac
if [[ "$group" != E ]]; then
  echo "vLLM/LMCache launcher requires MOONCAKE_EXPERIMENT_GROUP=E" >&2
  exit 2
fi
if [[ ! "$run_id" =~ ^[a-zA-Z0-9_]+$ ]]; then
  echo "MOONCAKE_EXPERIMENT_RUN_ID must contain only letters, digits, and underscores" >&2
  exit 2
fi
if [[ ! "$gpu_ip" =~ ^[0-9]+([.][0-9]+){3}$ ]] \
  || [[ ! "$gpu_hostname" =~ ^[a-zA-Z0-9][a-zA-Z0-9._-]*$ ]]; then
  echo "MOONCAKE_GPU_IP and MOONCAKE_GPU_HOSTNAME must be explicit" >&2
  exit 2
fi
if [[ ! "$cpu_ip" =~ ^[0-9]+([.][0-9]+){3}$ ]] \
  || [[ ! "$cpu_hostname" =~ ^[a-zA-Z0-9][a-zA-Z0-9._-]*$ ]] \
  || [[ ! "$cpu_ssh_port" =~ ^[1-9][0-9]{0,4}$ ]] \
  || (( cpu_ssh_port > 65535 )) \
  || [[ -z "$cpu_hcas" ]]; then
  echo "remote CPU IP, hostname, SSH port, and HCA list must be explicit" >&2
  exit 2
fi
if [[ "$gpu_ip" == "$cpu_ip" || "$gpu_hostname" == "$cpu_hostname" ]]; then
  echo "GPU and remote CPU identities must be distinct" >&2
  exit 2
fi
if [[ "$allow_gpu_capable_remote_cpu" != 0 \
  && "$allow_gpu_capable_remote_cpu" != 1 ]]; then
  echo "MOONCAKE_ALLOW_GPU_CAPABLE_REMOTE_CPU must be 0 or 1" >&2
  exit 2
fi
if [[ "$cpu_ssh_port" == 30245 || "$cpu_ip" == 10.233.114.145 ]]; then
  echo "refusing known GPU node as remote CPU" >&2
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
if [[ ! "$port" =~ ^[1-9][0-9]{0,4}$ ]] || (( port > 65535 )); then
  echo "invalid vLLM port: $port" >&2
  exit 2
fi

if [[ -d /public/mjq/.venv_sglang_fluxon ]]; then
  shared_mjq=/public/mjq
elif [[ -d /storage/mjq/.venv_sglang_fluxon ]]; then
  shared_mjq=/storage/mjq
else
  echo "neither /public/mjq nor /storage/mjq runtime is available" >&2
  exit 1
fi
python="$shared_mjq/.venv_sglang_fluxon/bin/python"
ninja_bin="$shared_mjq/.venv_sglang_fluxon/bin/ninja"
model_path="$shared_mjq/models/Qwen3-VL-8B-Instruct"
rdma_lib="$shared_mjq/rdma_runtime_jammy/lib"
rdma_provider="$shared_mjq/rdma_runtime_jammy/libibverbs"
runtime_lib="$shared_mjq/mooncake_m1/mooncake_3node_aligned_20260712/runtime_libs"
base_dir="${MOONCAKE_LOCAL_RUN_DIR:-/tmp/mooncake_trace_local_dram_tp2x2_20260728/$run_id}"
node_dir="$base_dir/vllm_lmcache/$gpu_node"
config_path="$node_dir/lmcache.yaml"
log_path="$node_dir/vllm.log"
pid_path="$node_dir/process_group_leader.pid"
runtime_tools_path="$node_dir/runtime_tools.env"
tmux_tmp="/tmp/mce_tmux_${run_id}_${gpu_node}"
tmux_socket="mce_${gpu_node}"
tmux_session="server"
cuda_toolkit_root="${MOONCAKE_CUDA_TOOLKIT_ROOT:-/public/zsh/miniconda3}"
cuda_home="$node_dir/cuda_home"

tmux_cmd() {
  TMUX_TMPDIR="$tmux_tmp" tmux -L "$tmux_socket" "$@"
}

is_running() {
  tmux_cmd has-session -t "$tmux_session" 2>/dev/null
}

if [[ "$action" == status ]]; then
  if is_running; then
    tmux_cmd list-panes -t "$tmux_session" -F 'session=#{session_name} pane_pid=#{pane_pid} dead=#{pane_dead} command=#{pane_current_command}'
    exit 0
  fi
  echo "stopped"
  exit 1
fi

if [[ "$action" == stop ]]; then
  if is_running; then
    tmux_cmd send-keys -t "$tmux_session" C-c || true
    for _ in $(seq 1 60); do
      is_running || break
      sleep 1
    done
  fi
  if is_running; then
    tmux_cmd kill-session -t "$tmux_session" || true
  fi
  if [[ -r "$pid_path" ]]; then
    leader="$(<"$pid_path")"
    if [[ "$leader" =~ ^[1-9][0-9]*$ ]] && kill -0 "$leader" 2>/dev/null; then
      kill -TERM -- "-$leader" 2>/dev/null || true
      for _ in $(seq 1 30); do
        kill -0 "$leader" 2>/dev/null || break
        sleep 1
      done
      if kill -0 "$leader" 2>/dev/null; then
        kill -KILL -- "-$leader" 2>/dev/null || true
      fi
    fi
  fi
  echo "stopped $gpu_node"
  exit 0
fi

if is_running; then
  echo "$gpu_node vLLM session already exists" >&2
  exit 1
fi
if [[ "$(hostname)" != "$gpu_hostname" ]] \
  || ! tr ' ' '\n' <<<"$(hostname -I)" | grep -Fx "$gpu_ip" >/dev/null; then
  echo "GPU identity mismatch: expected=$gpu_hostname/$gpu_ip actual=$(hostname)/$(hostname -I)" >&2
  exit 1
fi
if [[ "$(findmnt -T /tmp -o FSTYPE -n)" != xfs ]]; then
  echo "/tmp is not the required local XFS/NVMe filesystem" >&2
  findmnt -T /tmp >&2
  exit 1
fi
if [[ ! "$overlay" = /tmp/* ]] || [[ ! -d "$overlay" ]]; then
  echo "VLLM_LMCACHE_OVERLAY_DIR must be an existing absolute /tmp path" >&2
  exit 1
fi
overlay_manifest="$overlay/OVERLAY_MANIFEST.json"
if [[ ! -f "$overlay_manifest" ]] || [[ ! "$overlay_manifest_sha" =~ ^[0-9a-f]{64}$ ]]; then
  echo "overlay manifest and expected SHA256 are required" >&2
  exit 1
fi
if [[ "$(sha256sum "$overlay_manifest" | awk '{print $1}')" != "$overlay_manifest_sha" ]]; then
  echo "overlay manifest SHA256 mismatch" >&2
  exit 1
fi
test -x "$python"
test -x "$ninja_bin"
test -f "$model_path/config.json"
test -f "$rdma_provider/libmlx5-rdmav34.so"
ninja_sha256="$(sha256sum "$ninja_bin" | awk '{print $1}')"
ninja_version="$($ninja_bin --version)"
if [[ "$ninja_sha256" != "$expected_ninja_sha256" \
  || "$ninja_version" != "$expected_ninja_version" ]]; then
  echo "ninja runtime identity mismatch: path=$ninja_bin sha256=$ninja_sha256 version=$ninja_version" >&2
  exit 1
fi
ninja_dir="$(dirname "$ninja_bin")"
runtime_path="$ninja_dir:${PATH:-/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin}"

IFS=, read -r -a gpu_ids <<<"$visible_gpus"
if (( ${#gpu_ids[@]} != 2 )) || [[ "${gpu_ids[0]}" == "${gpu_ids[1]}" ]]; then
  echo "each TP2 instance requires two distinct GPUs" >&2
  exit 1
fi
gpu_count="$(nvidia-smi -L | wc -l)"
for gpu_id in "${gpu_ids[@]}"; do
  if [[ ! "$gpu_id" =~ ^[0-9]+$ ]] || (( gpu_id >= gpu_count )); then
    echo "invalid GPU index: $gpu_id" >&2
    exit 1
  fi
  compute_pids="$(nvidia-smi -i "$gpu_id" --query-compute-apps=pid --format=csv,noheader,nounits | sed '/^[[:space:]]*$/d')"
  if [[ -n "$compute_pids" ]]; then
    echo "selected GPU $gpu_id is busy: $compute_pids" >&2
    exit 1
  fi
done
IFS=, read -r -a hcas <<<"$device_names"
if (( ${#hcas[@]} == 0 )); then
  echo "empty HCA list" >&2
  exit 1
fi
for hca in "${hcas[@]}"; do
  state_path="/sys/class/infiniband/$hca/ports/1/state"
  if [[ ! -r "$state_path" ]] || [[ "$(<"$state_path")" != *ACTIVE* ]]; then
    echo "HCA is not ACTIVE: $hca" >&2
    exit 1
  fi
done

targets_root="$cuda_toolkit_root/targets/x86_64-linux"
test -x "$cuda_toolkit_root/bin/nvcc"
test -x "$cuda_toolkit_root/nvvm/bin/cicc"
test -f "$targets_root/include/cuda.h"
test -f "$targets_root/lib/libcudart.so"
install -d -m 0755 "$node_dir" "$cuda_home" "$node_dir/cache" "$tmux_tmp"
install -d -m 0755 "$node_dir/lmcache_prometheus"
for name in bin nvvm include lib64; do
  case "$name" in
    bin) target="$cuda_toolkit_root/bin" ;;
    nvvm) target="$cuda_toolkit_root/nvvm" ;;
    include) target="$targets_root/include" ;;
    lib64) target="$targets_root/lib" ;;
  esac
  if [[ -L "$cuda_home/$name" ]]; then
    [[ "$(readlink "$cuda_home/$name")" == "$target" ]] || exit 1
  elif [[ -e "$cuda_home/$name" ]]; then
    echo "unexpected CUDA overlay path: $cuda_home/$name" >&2
    exit 1
  else
    ln -s "$target" "$cuda_home/$name"
  fi
done

if [[ -e "$config_path" || -e "$log_path" || -e "$pid_path" \
  || -e "$runtime_tools_path" || -e "$node_dir/command.argv" ]]; then
  echo "run evidence path already exists for $gpu_node" >&2
  exit 1
fi
printf '%s\n' \
  'chunk_size: 512' \
  'local_cpu: true' \
  "max_local_cpu_size: $lmcache_rank_gib" \
  'local_cpu_use_hugepages: false' \
  'remote_serde: "naive"' \
  'remote_url: "mooncakestore://127.0.0.1:51081/"' \
  'numa_mode: "auto"' \
  'pre_caching_hash_algorithm: "sha256_cbor_64bit"' \
  'extra_config:' \
  '  save_chunk_meta: false' \
  '  use_exists_sync: true' \
  "  local_hostname: \"$gpu_ip\"" \
  '  metadata_server: "http://127.0.0.1:8183/metadata"' \
  '  protocol: "rdma"' \
  "  device_name: \"$device_names\"" \
  "  mooncake_rdma_devices: \"$device_names\"" \
  "  global_segment_size: $mooncake_rank_segment_bytes" \
  "  local_buffer_size: $mooncake_rank_local_buffer_bytes" \
  '  master_server_address: "127.0.0.1:51081"' \
  '  mooncake_master_server_addr: "127.0.0.1:51081"' \
  '  mooncake_prefer_local_alloc: false' \
  '  transfer_timeout: 10' >"$config_path"
chmod 0444 "$config_path"
printf '%s\n' \
  "ninja_path=$ninja_bin" \
  "ninja_sha256=$ninja_sha256" \
  "ninja_version=$ninja_version" \
  "lmcache_rank_bytes=$lmcache_rank_bytes" \
  "mooncake_rank_segment_bytes=$mooncake_rank_segment_bytes" \
  "mooncake_rank_local_buffer_bytes=$mooncake_rank_local_buffer_bytes" \
  "effective_path=$runtime_path" >"$runtime_tools_path"
chmod 0444 "$runtime_tools_path"

common_ld="$overlay/vllm:$shared_mjq/.venv_sglang_fluxon/lib/python3.10/site-packages/torch/lib:$rdma_lib:$rdma_provider:$runtime_lib"
kv_config='{"kv_connector":"LMCacheConnectorV1","kv_role":"kv_both"}'
command=(
  "$python" -m vllm.entrypoints.cli.main serve "$model_path"
  --served-model-name "$model_path"
  --host 0.0.0.0
  --port "$port"
  --tensor-parallel-size 2
  --distributed-executor-backend mp
  --max-model-len 200000
  --max-num-batched-tokens 8192
  --max-num-seqs 1024
  --gpu-memory-utilization 0.90
  --cpu-offload-gb 0
  --enable-chunked-prefill
  --enable-prefix-caching
  --enable-prompt-tokens-details
  --generation-config vllm
  --kv-transfer-config "$kv_config"
)
printf '%q ' "${command[@]}" >"$node_dir/command.argv"
printf '\n' >>"$node_dir/command.argv"
chmod 0444 "$node_dir/command.argv"

launch_cmd="exec env CUDA_VISIBLE_DEVICES=$(printf %q "$visible_gpus") PATH=$(printf %q "$runtime_path") PYTHONPATH=$(printf %q "$overlay") LD_LIBRARY_PATH=$(printf %q "$common_ld") CUDA_HOME=$(printf %q "$cuda_home") XDG_CACHE_HOME=$(printf %q "$node_dir/cache") TORCH_EXTENSIONS_DIR=$(printf %q "$node_dir/cache/torch_extensions") TVM_FFI_CACHE_DIR=$(printf %q "$node_dir/cache/tvm_ffi") PROMETHEUS_MULTIPROC_DIR=$(printf %q "$node_dir/lmcache_prometheus") LMCACHE_CONFIG_FILE=$(printf %q "$config_path") PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0 LMCACHE_LOG_LEVEL=INFO IBV_DRIVERS=mlx5 IBV_DRIVER_PATH=$(printf %q "$rdma_provider") NCCL_SOCKET_IFNAME=tunl0 GLOO_SOCKET_IFNAME=tunl0 VLLM_WORKER_MULTIPROC_METHOD=spawn $(printf '%q ' "${command[@]}") >>$(printf %q "$log_path") 2>&1"
tmux_cmd new-session -d -s "$tmux_session" "$launch_cmd"
leader="$(tmux_cmd display-message -p -t "$tmux_session" '#{pane_pid}')"
printf '%s\n' "$leader" >"$pid_path"
chmod 0444 "$pid_path"
sleep 2
if ! is_running; then
  echo "vLLM session exited during startup: $log_path" >&2
  tail -n 120 "$log_path" >&2 || true
  exit 1
fi
echo "started $gpu_node port=$port gpus=$visible_gpus config=$config_path log=$log_path"
