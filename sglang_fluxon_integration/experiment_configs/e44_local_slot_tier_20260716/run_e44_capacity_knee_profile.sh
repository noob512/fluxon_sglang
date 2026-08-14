#!/usr/bin/env bash
set -euo pipefail

profile="${1:?usage: $0 PROFILE RUN_ID [WORKLOAD_PROFILE]}"
run_id="${2:?usage: $0 PROFILE RUN_ID [WORKLOAD_PROFILE]}"
workload_profile="${3:-s96_w2_c24}"
variant="${E44_CAPACITY_VARIANT:-tier1_independent_005_netobs_enddepth288_gpu_direct_r61_tp_execute_commit}"
cpu_variant="${E44_CAPACITY_CPU_VARIANT:-$variant}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$script_dir/e44_v5_perf_variant_20260718.sh" "$variant"
ssd_read_source_policy="${E44_PERF_SOURCE_ORDER_EVIDENCE:-${E44_PERF_SSD_READ_SOURCE_POLICY:-legacy_remote_first}}"
gpu_direct_enabled="${E44_PERF_GPU_DIRECT_ENABLED:-1}"
post_read_remote_policy="${E44_PERF_POST_READ_REMOTE_POLICY:-retain}"
host="${E44_CAPACITY_SSH_HOST:-116.238.240.2}"
gpu_key="${E44_CAPACITY_GPU_SSH_KEY:-/home/zyc/.ssh/infra44_ed25519}"
cpu_key="${E44_CAPACITY_CPU_SSH_KEY:-/home/zyc/.ssh/infra44_ed25519}"
port0="${E44_CAPACITY_GPU0_PORT:-32656}"
port1="${E44_CAPACITY_GPU1_PORT:-30245}"
port_cpu="${E44_CAPACITY_CPU_PORT:-30448}"
node0_ip_override="${E44_CAPACITY_NODE0_IP:-}"
node1_ip_override="${E44_CAPACITY_NODE1_IP:-}"
cpu_ip_override="${E44_CAPACITY_CPU_IP:-}"
node0_expected_hostname="${E44_CAPACITY_NODE0_HOSTNAME:-}"
node1_expected_hostname="${E44_CAPACITY_NODE1_HOSTNAME:-}"
gpu0_ids="${E44_CAPACITY_GPU0_IDS:-0,1}"
gpu1_ids="${E44_CAPACITY_GPU1_IDS:-0,1}"
gpu0_rdma_devices="${E44_CAPACITY_GPU0_RDMA_DEVICES:-mlx5_4,mlx5_6}"
gpu1_rdma_devices="${E44_CAPACITY_GPU1_RDMA_DEVICES:-mlx5_4,mlx5_6}"
sglang_layout="${E44_CAPACITY_SGLANG_LAYOUT:-tp2}"
gpu0_sglang_port="${E44_CAPACITY_GPU0_SGLANG_PORT:-31001}"
gpu1_sglang_port="${E44_CAPACITY_GPU1_SGLANG_PORT:-31001}"
gpu0_sglang_port_b="${E44_CAPACITY_GPU0_SGLANG_PORT_B:-31002}"
gpu1_sglang_port_b="${E44_CAPACITY_GPU1_SGLANG_PORT_B:-31002}"
gpu0_owner_cpuset="${E44_CAPACITY_GPU0_OWNER_CPUSET:-48-95,144-191}"
gpu1_owner_cpuset="${E44_CAPACITY_GPU1_OWNER_CPUSET:-48-95,144-191}"
cpu_venv_override="${E44_CAPACITY_CPU_VENV:-}"
root0=/storage/mjq/sglang_fluxon/fluxon_f1
root1=/storage/mjq/sglang_fluxon/fluxon_f2
root_cpu=/storage/mjq/sglang_fluxon/fluxon_cpu
exp_rel=e44_local_slot_tier_20260716
exp0="$root0/$exp_rel"
exp1="$root1/$exp_rel"
exp_cpu="$root_cpu/$exp_rel"
local_artifact="/mnt/nvme0/mjq_build/e44_capacity_knee_${run_id}"
tmux_tmpdir="/run/e44_capacity_${run_id}_tmux"
ssd_enabled="${E44_CAPACITY_ENABLE_SSD:-0}"
ssd_scope="${E44_CAPACITY_SSD_SCOPE:-remote_cpu_only}"
gpu_ssd_capacity_bytes="${E44_CAPACITY_GPU_SSD_BYTES:-1649267441664}"
cpu_ssd_capacity_bytes="${E44_CAPACITY_CPU_SSD_BYTES:-1649267441664}"
gpu_ssd_write_rate_bytes_per_sec="${E44_CAPACITY_GPU_SSD_WRITE_BPS:-268435456}"
gpu_ssd_write_burst_bytes="${E44_CAPACITY_GPU_SSD_WRITE_BURST_BYTES:-67108864}"
gpu_ssd_capacity_writeback_enabled="${E44_CAPACITY_GPU_SSD_CAPACITY_WRITEBACK_ENABLED:-true}"
ssd_safety_margin_bytes="${E44_CAPACITY_SSD_SAFETY_MARGIN_BYTES:-536870912000}"
gpu_idle_memory_tolerance_mib="${E44_CAPACITY_GPU_IDLE_MEMORY_TOLERANCE_MIB:-0}"
cpu_rdma_ready_timeout_seconds="${E44_CAPACITY_CPU_RDMA_READY_TIMEOUT_SECONDS:-300}"
gpu_rdma_ready_timeout_seconds="${E44_CAPACITY_GPU_RDMA_READY_TIMEOUT_SECONDS:-300}"
gpu_shared_json_timeout_seconds="${E44_CAPACITY_GPU_SHARED_JSON_TIMEOUT_SECONDS:-120}"
stagger_cpu_owner="${E44_CAPACITY_STAGGER_CPU_OWNER:-0}"
preserve_external_workloads="${E44_CAPACITY_PRESERVE_EXTERNAL_WORKLOADS:-0}"
cpu_external_stack_allowed="${E44_CAPACITY_CPU_EXTERNAL_STACK_ALLOWED:-0}"
tcp_control_lane_count="${E44_CAPACITY_TCP_CONTROL_LANE_COUNT:-}"
requested_cpu_active_capacity_bytes="${E44_CAPACITY_ACTIVE_CPU_BYTES:-}"
requested_gpu_dram_bytes="${E44_CAPACITY_GPU_DRAM_BYTES:-}"
requested_gpu_payload_bytes="${E44_CAPACITY_GPU_PAYLOAD_BYTES:-}"
workload_prefix_namespace="${E44_CAPACITY_WORKLOAD_PREFIX_NAMESPACE:-}"
expected_corpus_sha256="${E44_CAPACITY_EXPECTED_CORPUS_SHA256:-}"
assistant_history_replay_file="${E44_CAPACITY_ASSISTANT_HISTORY_REPLAY_FILE:-}"
assistant_history_replay_sha256="${E44_CAPACITY_ASSISTANT_HISTORY_REPLAY_SHA256:-}"
fast25_deployment_dir="${E44_CAPACITY_FAST25_DEPLOYMENT_DIR:-}"
fast25_workload_profile="${E44_CAPACITY_FAST25_WORKLOAD_PROFILE:-s96_wss296}"
fast25_arm="${E44_CAPACITY_FAST25_ARM:-}"
fast25_result_root="${E44_CAPACITY_FAST25_RESULT_ROOT:-/storage/mjq/mooncake_m1/results/fast25_multilevel_fluxon_mooncake_20260805}"
ssd_root="/tmp/fluxon_kv_ssd/${run_id}"
workload_ssh_pid=
cleanup_started=0
cpu_guard_active=0
cpu_guard_session="zth_cpu_guard_${run_id}"
cpu_guard_runtime_dir="/run/e44_cpu_guard/$run_id"
cpu_guard_heartbeat="$cpu_guard_runtime_dir/heartbeat"
cpu_guard_violation="$cpu_guard_runtime_dir/violation"
cpu_guard_log="$cpu_guard_runtime_dir/guard.log"
cpu_guard_evidence_heartbeat="$exp_cpu/cpu_interference_guard_${run_id}.heartbeat"
cpu_guard_evidence_violation="$exp_cpu/cpu_interference_guard_${run_id}.violation"
cpu_guard_evidence_log="$exp_cpu/cpu_interference_guard_${run_id}.log"
cpu_hca_runtime_dir="/run/e44_hca_observer/$run_id"
cpu_hca_runtime_jsonl="$cpu_hca_runtime_dir/${run_id}_cpu.jsonl"
cpu_hca_runtime_log="$cpu_hca_runtime_dir/${run_id}_cpu.log"
cpu_guard_sha256=a244ca1752535910374d762c0ed71b9c650a8ad3315128f1d33428ee35565d27
gpu0_sglang_log="$root0/log/current_cpu_remote_20260710/sglang_tp2_gpus${gpu0_ids//,/_}_port${gpu0_sglang_port}_${run_id}_20260719.log"
gpu1_sglang_log="$root1/log/current_cpu_remote_20260710/sglang_tp2_gpus${gpu1_ids//,/_}_port${gpu1_sglang_port}_${run_id}_20260719.log"
gpu0_sglang_log_b=
gpu1_sglang_log_b=
gpu0_runtime_ports="$gpu0_sglang_port"
gpu1_runtime_ports="$gpu1_sglang_port"
if [ "$sglang_layout" = tp1x2 ]; then
  gpu0_a="${gpu0_ids%%,*}"
  gpu0_b="${gpu0_ids#*,}"
  gpu1_a="${gpu1_ids%%,*}"
  gpu1_b="${gpu1_ids#*,}"
  gpu0_sglang_log="$root0/log/current_cpu_remote_20260710/sglang_tp1_gpu${gpu0_a}_port${gpu0_sglang_port}_${run_id}_20260719.log"
  gpu0_sglang_log_b="$root0/log/current_cpu_remote_20260710/sglang_tp1_gpu${gpu0_b}_port${gpu0_sglang_port_b}_${run_id}_20260719.log"
  gpu1_sglang_log="$root1/log/current_cpu_remote_20260710/sglang_tp1_gpu${gpu1_a}_port${gpu1_sglang_port}_${run_id}_20260719.log"
  gpu1_sglang_log_b="$root1/log/current_cpu_remote_20260710/sglang_tp1_gpu${gpu1_b}_port${gpu1_sglang_port_b}_${run_id}_20260719.log"
  gpu0_runtime_ports="$gpu0_sglang_port,$gpu0_sglang_port_b"
  gpu1_runtime_ports="$gpu1_sglang_port,$gpu1_sglang_port_b"
fi
gpu_sglang_log_specs=("$port0|node0a|$gpu0_sglang_log" "$port1|node1a|$gpu1_sglang_log")
if [ "$sglang_layout" = tp1x2 ]; then
  gpu_sglang_log_specs+=("$port0|node0b|$gpu0_sglang_log_b" "$port1|node1b|$gpu1_sglang_log_b")
fi

if [[ ! "$run_id" =~ ^[a-zA-Z0-9_]+$ ]]; then
  echo "invalid run id: $run_id" >&2
  exit 2
fi
if [[ ! "$cpu_variant" =~ ^[a-zA-Z0-9_]+$ ]]; then
  echo "invalid CPU performance variant: $cpu_variant" >&2
  exit 2
fi
case "$tcp_control_lane_count" in
  "" | 8) ;;
  *) echo "E44_CAPACITY_TCP_CONTROL_LANE_COUNT must be empty or 8" >&2; exit 2 ;;
esac
if [ -n "$workload_prefix_namespace" ] &&
   [[ ! "$workload_prefix_namespace" =~ ^[a-zA-Z0-9_]+$ ]]; then
  echo "E44_CAPACITY_WORKLOAD_PREFIX_NAMESPACE must contain only letters, digits, and underscores" >&2
  exit 2
fi
if [ -n "$expected_corpus_sha256" ] &&
   [[ ! "$expected_corpus_sha256" =~ ^[a-f0-9]{64}$ ]]; then
  echo "E44_CAPACITY_EXPECTED_CORPUS_SHA256 must be a lowercase SHA256 digest" >&2
  exit 2
fi
if [ -n "$assistant_history_replay_file" ] || [ -n "$assistant_history_replay_sha256" ]; then
  if [[ ! "$assistant_history_replay_file" =~ ^/[a-zA-Z0-9._/-]+$ ]] ||
     [[ ! "$assistant_history_replay_sha256" =~ ^[a-f0-9]{64}$ ]]; then
    echo "assistant-history replay requires an absolute safe path and lowercase SHA256" >&2
    exit 2
  fi
fi
if [ "$workload_profile" = fast25_mlp_c24 ]; then
  case "$fast25_deployment_dir" in
    /storage/mjq/mooncake_m1/deployments/fast25_mlp_*) ;;
    *) echo "fast25_mlp_c24 requires a sealed E44_CAPACITY_FAST25_DEPLOYMENT_DIR" >&2; exit 2 ;;
  esac
  case "$fast25_result_root" in
    /storage/mjq/mooncake_m1/results/fast25_multilevel_fluxon_mooncake_20260805) ;;
    *) echo "invalid E44_CAPACITY_FAST25_RESULT_ROOT" >&2; exit 2 ;;
  esac
  case "$fast25_arm" in F0|F1) ;; *) echo "E44_CAPACITY_FAST25_ARM must be F0 or F1" >&2; exit 2 ;; esac
  fast25_profile_helper="$script_dir/../fast25_multilevel_fluxon_mooncake_20260805/fast25_mlp_workload_profile.sh"
  test -f "$fast25_profile_helper"
  source "$fast25_profile_helper"
  resolve_fast25_mlp_workload_profile "$fast25_workload_profile"
  if [ "$fast25_arm" = F0 ] && [ "$ssd_enabled" != 0 ]; then
    echo "F0 requires SSD disabled" >&2
    exit 2
  fi
  if [ "$fast25_arm" = F1 ] && \
     { [ "$ssd_enabled" != 1 ] || [ "$ssd_scope" != remote_cpu_only ]; }; then
    echo "F1 requires remote_cpu_only SSD" >&2
    exit 2
  fi
elif [ -n "$fast25_deployment_dir" ] || [ -n "$fast25_arm" ]; then
  echo "FAST25 capacity arguments are only valid for fast25_mlp_c24" >&2
  exit 2
fi
case "$sglang_layout" in
  tp2) owner_local_reserve_value_len=4718592 ;;
  tp1x2)
    owner_local_reserve_value_len=9437184
    case "$workload_profile" in
      fast25_mlp_c24 | s96_w2_c24) ;;
      *) echo "tp1x2 is sealed only for fast25_mlp_c24 or s96_w2_c24" >&2; exit 2 ;;
    esac
    ;;
  *) echo "E44_CAPACITY_SGLANG_LAYOUT must be tp2 or tp1x2" >&2; exit 2 ;;
esac
port_specs=( \
  "E44_CAPACITY_GPU0_PORT:$port0" \
  "E44_CAPACITY_GPU1_PORT:$port1" \
  "E44_CAPACITY_CPU_PORT:$port_cpu" \
  "E44_CAPACITY_GPU0_SGLANG_PORT:$gpu0_sglang_port" \
  "E44_CAPACITY_GPU1_SGLANG_PORT:$gpu1_sglang_port" \
)
if [ "$sglang_layout" = tp1x2 ]; then
  port_specs+=(
    "E44_CAPACITY_GPU0_SGLANG_PORT_B:$gpu0_sglang_port_b"
    "E44_CAPACITY_GPU1_SGLANG_PORT_B:$gpu1_sglang_port_b"
  )
fi
for port_spec in "${port_specs[@]}"; do
  port_name="${port_spec%%:*}"
  port_value="${port_spec#*:}"
  if [[ ! "$port_value" =~ ^[1-9][0-9]*$ ]] || [ "$port_value" -gt 65535 ]; then
    echo "$port_name must be an integer in [1,65535]" >&2
    exit 2
  fi
done
if [ "$sglang_layout" = tp1x2 ] && \
   { [ "$gpu0_sglang_port" = "$gpu0_sglang_port_b" ] || [ "$gpu1_sglang_port" = "$gpu1_sglang_port_b" ]; }; then
  echo "tp1x2 requires two distinct SGLang ports on each GPU node" >&2
  exit 2
fi
for cpuset_spec in \
  "E44_CAPACITY_GPU0_OWNER_CPUSET:$gpu0_owner_cpuset" \
  "E44_CAPACITY_GPU1_OWNER_CPUSET:$gpu1_owner_cpuset"; do
  cpuset_name="${cpuset_spec%%:*}"
  cpuset_value="${cpuset_spec#*:}"
  if [[ ! "$cpuset_value" =~ ^[0-9,-]+$ ]]; then
    echo "$cpuset_name must contain only digits, commas, and dashes" >&2
    exit 2
  fi
done
for gpu_spec in "E44_CAPACITY_GPU0_IDS:$gpu0_ids" "E44_CAPACITY_GPU1_IDS:$gpu1_ids"; do
  gpu_name="${gpu_spec%%:*}"
  gpu_value="${gpu_spec#*:}"
  if [[ ! "$gpu_value" =~ ^[0-9]+,[0-9]+$ ]]; then
    echo "$gpu_name must contain exactly two comma-separated GPU indices" >&2
    exit 2
  fi
done
for rdma_spec in \
  "E44_CAPACITY_GPU0_RDMA_DEVICES:$gpu0_rdma_devices" \
  "E44_CAPACITY_GPU1_RDMA_DEVICES:$gpu1_rdma_devices"; do
  rdma_name="${rdma_spec%%:*}"
  rdma_value="${rdma_spec#*:}"
  if [[ ! "$rdma_value" =~ ^mlx5_[0-9]+,mlx5_[0-9]+$ ]]; then
    echo "$rdma_name must contain exactly two comma-separated mlx5 devices" >&2
    exit 2
  fi
done
for ip_spec in \
  "E44_CAPACITY_NODE0_IP:$node0_ip_override" \
  "E44_CAPACITY_NODE1_IP:$node1_ip_override" \
  "E44_CAPACITY_CPU_IP:$cpu_ip_override"; do
  ip_name="${ip_spec%%:*}"
  ip_value="${ip_spec#*:}"
  if [ -n "$ip_value" ] && [[ ! "$ip_value" =~ ^10\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "$ip_name must be an RFC1918 10/8 IPv4 address" >&2
    exit 2
  fi
done
test -f "$gpu_key"
test -f "$cpu_key"
if [ -n "$cpu_venv_override" ] &&
   [[ ! "$cpu_venv_override" =~ ^/[a-zA-Z0-9._/-]+$ ]]; then
  echo "E44_CAPACITY_CPU_VENV must be an absolute path without shell metacharacters" >&2
  exit 2
fi
case "$ssd_enabled" in
  0 | 1) ;;
  *) echo "E44_CAPACITY_ENABLE_SSD must be 0 or 1" >&2; exit 2 ;;
esac
case "$ssd_scope" in
  remote_cpu_only | gpu_local_only | all_owners) ;;
  *) echo "E44_CAPACITY_SSD_SCOPE must be remote_cpu_only, gpu_local_only, or all_owners" >&2; exit 2 ;;
esac
case "$gpu_direct_enabled" in
  0 | 1) ;;
  *) echo "E44_PERF_GPU_DIRECT_ENABLED must be 0 or 1" >&2; exit 2 ;;
esac
case "$post_read_remote_policy" in
  retain | drop) ;;
  *) echo "E44_PERF_POST_READ_REMOTE_POLICY must be retain or drop" >&2; exit 2 ;;
esac
case "$gpu_ssd_capacity_writeback_enabled" in
  true | false) ;;
  *) echo "E44_CAPACITY_GPU_SSD_CAPACITY_WRITEBACK_ENABLED must be true or false" >&2; exit 2 ;;
esac
case "$gpu_idle_memory_tolerance_mib" in
  0 | 4) ;;
  *) echo "E44_CAPACITY_GPU_IDLE_MEMORY_TOLERANCE_MIB must be 0 or the explicitly authorized 4 MiB driver residual" >&2; exit 2 ;;
esac
if [ "$gpu_idle_memory_tolerance_mib" = 4 ]; then
  echo "gpu_idle_gate=explicit_driver_residual_tolerance tolerance_mib=4 compute_processes=must_be_empty utilization_percent=must_be_zero" >&2
fi
if [[ ! "$cpu_rdma_ready_timeout_seconds" =~ ^[0-9]+$ ]] ||
   [ "$cpu_rdma_ready_timeout_seconds" -lt 300 ] ||
   [ "$cpu_rdma_ready_timeout_seconds" -gt 900 ]; then
  echo "E44_CAPACITY_CPU_RDMA_READY_TIMEOUT_SECONDS must be an integer in [300,900]" >&2
  exit 2
fi
if [[ ! "$gpu_rdma_ready_timeout_seconds" =~ ^[0-9]+$ ]] ||
   [ "$gpu_rdma_ready_timeout_seconds" -lt 300 ] ||
   [ "$gpu_rdma_ready_timeout_seconds" -gt 900 ]; then
  echo "E44_CAPACITY_GPU_RDMA_READY_TIMEOUT_SECONDS must be an integer in [300,900]" >&2
  exit 2
fi
if [[ ! "$gpu_shared_json_timeout_seconds" =~ ^[0-9]+$ ]] ||
   [ "$gpu_shared_json_timeout_seconds" -lt 120 ] ||
   [ "$gpu_shared_json_timeout_seconds" -gt 900 ]; then
  echo "E44_CAPACITY_GPU_SHARED_JSON_TIMEOUT_SECONDS must be an integer in [120,900]" >&2
  exit 2
fi
case "$stagger_cpu_owner" in
  0) cpu_owner_start_mode=parallel ;;
  1) cpu_owner_start_mode=after_gpu_owner_ready ;;
  *) echo "E44_CAPACITY_STAGGER_CPU_OWNER must be 0 or 1" >&2; exit 2 ;;
esac
case "$preserve_external_workloads" in
  0 | 1) ;;
  *) echo "E44_CAPACITY_PRESERVE_EXTERNAL_WORKLOADS must be 0 or 1" >&2; exit 2 ;;
esac
case "$cpu_external_stack_allowed" in
  0 | 1) ;;
  *) echo "E44_CAPACITY_CPU_EXTERNAL_STACK_ALLOWED must be 0 or 1" >&2; exit 2 ;;
esac
if [ "$cpu_external_stack_allowed" = 1 ]; then
  echo "cpu_external_stack=explicitly_allowed diagnostic_result_only=true" >&2
fi
for value in "$gpu_ssd_capacity_bytes" "$cpu_ssd_capacity_bytes" \
  "$gpu_ssd_write_rate_bytes_per_sec" "$gpu_ssd_write_burst_bytes"; do
  if [[ ! "$value" =~ ^[1-9][0-9]*$ ]]; then
    echo "SSD capacity/rate/burst values must be positive integers" >&2
    exit 2
  fi
done
effective_gpu_ssd_capacity_bytes=0
effective_cpu_ssd_capacity_bytes=0
effective_gpu_ssd_write_rate_bytes_per_sec=0
effective_gpu_ssd_write_burst_bytes=0
effective_gpu_ssd_capacity_writeback_enabled=disabled
effective_ssd_scope=disabled
foyer_block_size_bytes=67108864
foyer_nofile_headroom=4096
tmux_nofile_soft=0
if [ "$ssd_enabled" = 1 ]; then
  effective_ssd_scope="$ssd_scope"
  if [ "$ssd_scope" = all_owners ] || [ "$ssd_scope" = gpu_local_only ]; then
    effective_gpu_ssd_capacity_bytes="$gpu_ssd_capacity_bytes"
    effective_gpu_ssd_write_rate_bytes_per_sec="$gpu_ssd_write_rate_bytes_per_sec"
    effective_gpu_ssd_write_burst_bytes="$gpu_ssd_write_burst_bytes"
    effective_gpu_ssd_capacity_writeback_enabled="$gpu_ssd_capacity_writeback_enabled"
  fi
  if [ "$ssd_scope" = all_owners ] || [ "$ssd_scope" = remote_cpu_only ]; then
    effective_cpu_ssd_capacity_bytes="$cpu_ssd_capacity_bytes"
  fi
  max_ssd_capacity_bytes="$effective_cpu_ssd_capacity_bytes"
  if [ "$effective_gpu_ssd_capacity_bytes" -gt "$max_ssd_capacity_bytes" ]; then
    max_ssd_capacity_bytes="$effective_gpu_ssd_capacity_bytes"
  fi
  foyer_partition_count=$((
    (max_ssd_capacity_bytes + foyer_block_size_bytes - 1) / foyer_block_size_bytes
  ))
  tmux_nofile_soft=$((foyer_partition_count + foyer_nofile_headroom))
fi

case "$profile" in
  remote128)
    gpu_dram_bytes=137438953472
    gpu_payload_bytes=123695058124
    cpu_dram_bytes=137438953472
    ;;
  remote145)
    gpu_dram_bytes=137438953472
    gpu_payload_bytes=123695058124
    cpu_dram_bytes=155692564480
    ;;
  remote160)
    gpu_dram_bytes=137438953472
    gpu_payload_bytes=123695058124
    cpu_dram_bytes=171798691840
    ;;
  remote100)
    gpu_dram_bytes=137438953472
    gpu_payload_bytes=123695058124
    cpu_dram_bytes=107374182400
    ;;
  remote150)
    gpu_dram_bytes=137438953472
    gpu_payload_bytes=123695058124
    cpu_dram_bytes=161061273600
    ;;
  remote200)
    gpu_dram_bytes=137438953472
    gpu_payload_bytes=123695058124
    cpu_dram_bytes=214748364800
    ;;
  remote250)
    gpu_dram_bytes=137438953472
    gpu_payload_bytes=123695058124
    cpu_dram_bytes=268435456000
    ;;
  remote300)
    gpu_dram_bytes=137438953472
    gpu_payload_bytes=123695058124
    cpu_dram_bytes=322122547200
    ;;
  remote400)
    gpu_dram_bytes=137438953472
    gpu_payload_bytes=123695058124
    cpu_dram_bytes=429496729600
    ;;
  remote350)
    gpu_dram_bytes=137438953472
    gpu_payload_bytes=123695058124
    cpu_dram_bytes=375809638400
    ;;
  100)
    gpu_dram_bytes=137438953472
    gpu_payload_bytes=123695058124
    cpu_dram_bytes=274877906944
    ;;
  9921875)
    gpu_dram_bytes=136365211648
    gpu_payload_bytes=122728690483
    cpu_dram_bytes=272730423296
    ;;
  984375)
    gpu_dram_bytes=135291469824
    gpu_payload_bytes=121762322841
    cpu_dram_bytes=270582939648
    ;;
  9765625)
    gpu_dram_bytes=134217728000
    gpu_payload_bytes=120795955200
    cpu_dram_bytes=268435456000
    ;;
  96875)
    gpu_dram_bytes=133143986176
    gpu_payload_bytes=119829587558
    cpu_dram_bytes=266287972352
    ;;
  9375)
    gpu_dram_bytes=128849018880
    gpu_payload_bytes=115964116992
    cpu_dram_bytes=257698037760
    ;;
  875)
    gpu_dram_bytes=120259084288
    gpu_payload_bytes=108233175859
    cpu_dram_bytes=240518168576
    ;;
  8125)
    gpu_dram_bytes=111669149696
    gpu_payload_bytes=100502234726
    cpu_dram_bytes=223338299392
    ;;
  75)
    gpu_dram_bytes=103079215104
    gpu_payload_bytes=92771293593
    cpu_dram_bytes=206158430208
    ;;
  625)
    gpu_dram_bytes=85899345920
    gpu_payload_bytes=77309411328
    cpu_dram_bytes=171798691840
    ;;
  50)
    gpu_dram_bytes=68719476736
    gpu_payload_bytes=61847529062
    cpu_dram_bytes=137438953472
    ;;
  *)
    echo "unsupported capacity profile: $profile" >&2
    exit 2
    ;;
esac

if [ -n "$requested_gpu_dram_bytes" ]; then
  if [[ ! "$requested_gpu_dram_bytes" =~ ^[1-9][0-9]*$ ]]; then
    echo "E44_CAPACITY_GPU_DRAM_BYTES must be a positive integer" >&2
    exit 2
  fi
  gpu_dram_bytes="$requested_gpu_dram_bytes"
  derived_gpu_payload_bytes=$((gpu_dram_bytes * 9 / 10))
  if [ -n "$requested_gpu_payload_bytes" ] && \
     [ "$requested_gpu_payload_bytes" -ne "$derived_gpu_payload_bytes" ]; then
    echo "GPU payload-only resizing is unsupported: expected 90% of DRAM ($derived_gpu_payload_bytes), got $requested_gpu_payload_bytes" >&2
    exit 2
  fi
  gpu_payload_bytes="$derived_gpu_payload_bytes"
elif [ -n "$requested_gpu_payload_bytes" ]; then
  if [[ ! "$requested_gpu_payload_bytes" =~ ^[1-9][0-9]*$ ]]; then
    echo "E44_CAPACITY_GPU_PAYLOAD_BYTES must be a positive integer" >&2
    exit 2
  fi
  derived_gpu_payload_bytes=$((gpu_dram_bytes * 9 / 10))
  if [ "$requested_gpu_payload_bytes" -ne "$derived_gpu_payload_bytes" ]; then
    echo "GPU payload-only resizing cannot change the Moka boundary; set E44_CAPACITY_GPU_DRAM_BYTES and use its 90% payload ($derived_gpu_payload_bytes)" >&2
    exit 2
  fi
  gpu_payload_bytes="$requested_gpu_payload_bytes"
fi

capacity_control_enabled=0
effective_cpu_active_capacity_bytes="$cpu_dram_bytes"
if [ -n "$requested_cpu_active_capacity_bytes" ]; then
  if [[ ! "$requested_cpu_active_capacity_bytes" =~ ^[1-9][0-9]*$ ]]; then
    echo "E44_CAPACITY_ACTIVE_CPU_BYTES must be a positive integer" >&2
    exit 2
  fi
  if [ "$requested_cpu_active_capacity_bytes" -gt "$cpu_dram_bytes" ]; then
    echo "active CPU capacity cannot exceed physical CPU DRAM capacity" >&2
    exit 2
  fi
  capacity_control_enabled=1
  effective_cpu_active_capacity_bytes="$requested_cpu_active_capacity_bytes"
fi

mkdir -p "$local_artifact"
test "$(findmnt -n -o SOURCE -T "$local_artifact")" = /dev/nvme0n1p3
ssh_control_id="$(printf '%s' "$run_id" | sha256sum | cut -c1-16)"
ssh_control_dir="/mnt/nvme0/mjq_build/e44_ssh/$ssh_control_id"
rm -rf "$ssh_control_dir"
mkdir -p "$ssh_control_dir"

ssh_base=(
  -o BatchMode=yes
  -o StrictHostKeyChecking=no
  -o ConnectTimeout=15
  -o ControlMaster=auto
  -o ControlPersist=60
  -o "ControlPath=$ssh_control_dir/%C"
)
gpu_ssh_common=("${ssh_base[@]}" -i "$gpu_key")
cpu_ssh_common=("${ssh_base[@]}" -i "$cpu_key")
cpu_control_private_ip=
cpu_control_ssh_path=public_ssh

remote_cpu_private() {
  local private_ip="$1"
  shift
  local proxy_command
  proxy_command="ssh -q -o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=5 -i $gpu_key -p $port0 -W %h:%p root@$host"
  ssh "${cpu_ssh_common[@]}" -o ConnectTimeout=5 \
    -o "ProxyCommand=$proxy_command" -p 2222 "root@$private_ip" "$@"
}

remote_cpu_private_no_mux() {
  local private_ip="$1"
  shift
  local proxy_command
  proxy_command="ssh -q -o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=3 -i $gpu_key -p $port0 -W %h:%p root@$host"
  ssh "${cpu_ssh_common[@]}" -o ControlMaster=no -o ControlPath=none \
    -o ConnectTimeout=3 -o "ProxyCommand=$proxy_command" \
    -p 2222 "root@$private_ip" "$@"
}

remote() {
  local port="$1"
  shift
  if [ "$port" = "$port_cpu" ] && [ -n "$cpu_control_private_ip" ]; then
    remote_cpu_private "$cpu_control_private_ip" "$@"
    return
  fi
  if [ "$port" = "$port0" ]; then
    # The first node0 master must carry agent forwarding because the workload
    # later opens the already-verified node1 private hop through this socket.
    ssh -A "${gpu_ssh_common[@]}" -p "$port" "root@$host" "$@"
  elif [ "$port" = "$port1" ]; then
    ssh "${gpu_ssh_common[@]}" -p "$port" "root@$host" "$@"
  else
    ssh "${cpu_ssh_common[@]}" -p "$port" "root@$host" "$@"
  fi
}

run_capacity_control() {
  local phase="$1"
  local operation="$2"
  local active_capacity_bytes="${3:-}"
  local operation_args="$operation"
  if [ "$operation" = set-wait ]; then
    operation_args="set-wait --active-capacity-bytes '$active_capacity_bytes' --settle-timeout-seconds 900 --poll-interval-seconds 1"
  fi
  remote "$port0" "
    set -euo pipefail
    source '$exp0/e44_v5_perf_variant_20260718.sh' '$variant'
    venv=\$E44_PERF_VENV_GPU
    response_file='$exp0/capacity_control_${run_id}_${phase}.json'
    raw_log='$exp0/capacity_control_${run_id}_${phase}.log'
    rm -f \"\$response_file\" \"\$raw_log\"
    export LD_LIBRARY_PATH=\"\$venv/lib/python3.10/site-packages/fluxon_pyo3:\$venv/lib/python3.10/site-packages/fluxon_pyo3.libs:/usr/lib/x86_64-linux-gnu:/lib/x86_64-linux-gnu\"
    export IBV_DRIVERS_PATH=\"\$venv/lib/python3.10/site-packages/fluxon_pyo3.libs/libibverbs.d\"
    if ! RUST_LOG=warn \"\$venv/bin/python\" '$exp0/control_fluxon_node_pool_capacity.py' \
      --config '$root0/runtime_current_cpu_remote_20260710/config/fluxon_client_current_cpu_remote_tp2.yaml' \
      --instance-key 'fluxon_${run_id}_capacity_controller_${phase}' \
      --master-node-id sglang_l13_master \
      --owner-node-id sglang_l13_owner_remote_cache_cpu0 \
      --response-file \"\$response_file\" \
      --close-timeout-seconds 20 \
      $operation_args >\"\$raw_log\" 2>&1; then
      cat \"\$raw_log\" >&2
      exit 1
    fi
    cat \"\$response_file\"
  "
}

assert_gpu_owner_payload_capacity() {
  local spec port root label actual
  for spec in "$port0:$root0:node0" "$port1:$root1:node1"; do
    port="${spec%%:*}"
    spec="${spec#*:}"
    root="${spec%%:*}"
    label="${spec#*:}"
    actual=
    for _ in $(seq 1 45); do
      actual="$(remote "$port" "
        grep 'owner hot source-eviction policy snapshot' '$root/log/current_cpu_remote_20260710/owner.log' 2>/dev/null |
          tail -n 1 |
          sed -E 's/\\x1B\\[[0-9;]*[[:alpha:]]//g' |
          sed -nE 's/.*capacity_bytes=([0-9]+).*/\\1/p'
      ")"
      if [ -n "$actual" ]; then
        break
      fi
      sleep 1
    done
    if [ "$actual" != "$gpu_payload_bytes" ]; then
      echo "GPU owner payload mismatch on $label: requested=$gpu_payload_bytes actual=${actual:-missing}" >&2
      return 1
    fi
  done
}

assert_gpu_owner_local_reserve_value_len() {
  local spec port root label actual
  gpu0_owner_local_reserve_value_len_actual=
  gpu1_owner_local_reserve_value_len_actual=
  for spec in "$port0:$root0:node0:gpu0_owner_local_reserve_value_len_actual" \
              "$port1:$root1:node1:gpu1_owner_local_reserve_value_len_actual"; do
    port="${spec%%:*}"
    spec="${spec#*:}"
    root="${spec%%:*}"
    spec="${spec#*:}"
    label="${spec%%:*}"
    actual_var="${spec#*:}"
    actual="$(remote "$port" "
      sed -nE \
        '/^[[:space:]]*owner_local_reserve_expected_capacity:[[:space:]]*$/ {
          n
          s/^[[:space:]]*value_len:[[:space:]]*([0-9]+)[[:space:]]*$/\\1/p
        }' \
        '$root/runtime_current_cpu_remote_20260710/config/fluxon_owner_current_cpu_remote.yaml'
    ")"
    if [ "$actual" != "$owner_local_reserve_value_len" ]; then
      echo "GPU owner local-reserve value_len mismatch on $label: layout=$sglang_layout requested=$owner_local_reserve_value_len actual=${actual:-missing}" >&2
      return 1
    fi
    printf -v "$actual_var" '%s' "$actual"
  done
}

assert_runtime_pyo3_identity() {
  local spec port label venv require_sglang runtime_root sglang_port
  for spec in \
    "$port0|node0|$E44_PERF_VENV_GPU|1|$root0|$gpu0_runtime_ports|fluxon_owner_current_cpu_remote.yaml" \
    "$port1|node1|$E44_PERF_VENV_GPU|1|$root1|$gpu1_runtime_ports|fluxon_owner_current_cpu_remote.yaml" \
    "$port_cpu|cpu|$effective_cpu_venv|0|$root_cpu|0|fluxon_owner_current_remote_cache.yaml"; do
    IFS='|' read -r port label venv require_sglang runtime_root sglang_port owner_config_name <<<"$spec"
    remote "$port" "python3 - '$label' '$venv' '$E44_PERF_EXPECTED_PYO3_SHA256' '$require_sglang' '$runtime_root' '$sglang_port' '$owner_config_name' <<'PY'
import hashlib
import pathlib
import sys

label, venv, expected_sha256, require_sglang, runtime_root, sglang_port, owner_config_name = sys.argv[1:]
venv_path = pathlib.Path(venv)
python_path = str(venv_path / 'bin/python')
native_candidates = sorted(
    venv_path.glob('lib/python*/site-packages/fluxon_pyo3/fluxon_pyo3.abi3.so')
)
if len(native_candidates) != 1:
    raise SystemExit(
        f'{label}: expected one installed PyO3 native object in {venv}, '
        f'found {len(native_candidates)}'
    )
native_path = native_candidates[0]
actual_sha256 = hashlib.sha256(native_path.read_bytes()).hexdigest()
if actual_sha256 != expected_sha256:
    raise SystemExit(
        f'{label}: installed PyO3 mismatch: expected={expected_sha256} '
        f'actual={actual_sha256} path={native_path}'
    )

def matching_processes(module):
    matches = []
    for proc in pathlib.Path('/proc').glob('[0-9]*'):
        try:
            command = (proc / 'cmdline').read_bytes().split(b'\\0')
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        decoded = [part.decode('utf-8', errors='replace') for part in command if part]
        if decoded[:3] == [python_path, '-m', module]:
            matches.append((int(proc.name), decoded))
    return matches

owner_config = str(
    pathlib.Path(runtime_root)
    / 'runtime_current_cpu_remote_20260710/config'
    / owner_config_name
)
owners = [
    process
    for process in matching_processes('fluxon_py.runtime.start_owner_kvclient')
    if owner_config in process[1]
]
if len(owners) != 1:
    raise SystemExit(
        f'{label}: expected one owner for config={owner_config}, found {len(owners)}'
    )
owner_pid = owners[0][0]
try:
    maps = pathlib.Path(f'/proc/{owner_pid}/maps').read_text(errors='replace').splitlines()
except (FileNotFoundError, PermissionError, ProcessLookupError) as exc:
    raise SystemExit(f'{label}: cannot inspect owner maps: {exc}') from exc
mapped_native = []
for line in maps:
    fields = line.split()
    if fields and fields[-1].endswith('/fluxon_pyo3.abi3.so'):
        mapped_native.append(pathlib.Path(fields[-1]))
mapped_native = sorted(set(mapped_native))
if len(mapped_native) != 1:
    raise SystemExit(
        f'{label}: expected one mapped PyO3 native object, found {mapped_native}'
    )
mapped_path = mapped_native[0]
try:
    mapped_path.relative_to(venv_path)
except ValueError as exc:
    raise SystemExit(
        f'{label}: owner loaded PyO3 outside expected venv: {mapped_path}'
    ) from exc
mapped_sha256 = hashlib.sha256(mapped_path.read_bytes()).hexdigest()
if mapped_sha256 != expected_sha256:
    raise SystemExit(
        f'{label}: mapped PyO3 mismatch: expected={expected_sha256} '
        f'actual={mapped_sha256} path={mapped_path}'
    )
if require_sglang == '1':
    def has_port(command, expected):
        return any(
            (item == '--port' and index + 1 < len(command) and command[index + 1] == expected)
            or item == f'--port={expected}'
            for index, item in enumerate(command)
        )

    expected_ports = sglang_port.split(',')
    for expected_port in expected_ports:
        sglang = [
            process
            for process in matching_processes('sglang.launch_server')
            if has_port(process[1], expected_port)
        ]
        if len(sglang) != 1:
            raise SystemExit(
                f'{label}: expected one SGLang launcher on port={expected_port}, '
                f'found {len(sglang)}'
            )
print(
    f'runtime_pyo3_identity=passed label={label} venv={venv} '
    f'owner_pid={owner_pid} owner_config={owner_config} sha256={mapped_sha256}'
)
PY"
  done
}

assert_gpu_ssd_capacity_writeback_mode() {
  if [ "$effective_gpu_ssd_capacity_writeback_enabled" = disabled ]; then
    return 0
  fi
  local spec port root label actual
  for spec in "$port0:$root0:node0" "$port1:$root1:node1"; do
    port="${spec%%:*}"
    spec="${spec#*:}"
    root="${spec%%:*}"
    label="${spec#*:}"
    actual="$(remote "$port" "
      sed -nE 's/^[[:space:]]*ssd_capacity_writeback_enabled:[[:space:]]*(true|false)[[:space:]]*$/\\1/p' \
        '$root/runtime_current_cpu_remote_20260710/config/fluxon_owner_current_cpu_remote.yaml' |
        tail -n 1
    ")"
    if [ "$actual" != "$effective_gpu_ssd_capacity_writeback_enabled" ]; then
      echo "GPU owner SSD capacity write-back mismatch on $label: requested=$effective_gpu_ssd_capacity_writeback_enabled actual=${actual:-missing}" >&2
      return 1
    fi
  done
}

assert_gpu_direct_startup_mode() {
  if [ "$gpu_direct_enabled" != 0 ]; then
    return 0
  fi
  local spec port label log disabled_count expected_count
  expected_count=2
  if [ "$sglang_layout" = tp1x2 ]; then
    expected_count=1
  fi
  for spec in "${gpu_sglang_log_specs[@]}"; do
    IFS='|' read -r port label log <<<"$spec"
    disabled_count="$(remote "$port" "grep -Fc 'Fluxon GPU-direct staging disabled: mode=cpu_h2d_only' '$log' || true")"
    if [ "$disabled_count" -lt "$expected_count" ]; then
      echo "GDR-off startup marker missing on $label: expected at least $expected_count, got $disabled_count" >&2
      return 1
    fi
    if remote "$port" "grep -F 'Fluxon GPU-direct staging enabled:' '$log' >/dev/null"; then
      echo "GDR staging was enabled on $label during a GDR-off run" >&2
      return 1
    fi
  done
}

assert_no_fluxon_fatal_events() {
  local spec port label log
  for spec in \
    "$port0|node0_owner|$root0/log/current_cpu_remote_20260710/owner.log" \
    "$port0|master|$root0/log/current_cpu_remote_20260710/master_${run_id}_20260718.log" \
    "$port1|node1_owner|$root1/log/current_cpu_remote_20260710/owner.log" \
    "$port_cpu|cpu_owner|$root_cpu/log/current_cpu_remote_20260710/owner.log" \
    "${gpu_sglang_log_specs[@]}"; do
    IFS='|' read -r port label log <<<"$spec"
    if remote "$port" "
      grep -Eni 'out[[:space:]]+of[[:space:]]+memory|(^|[^[:alnum:]_])oom([^[:alnum:]_]|$)|(^|[^[:alnum:]_])p2p([^[:alnum:]_]|$).{0,160}([^[:alnum:]_])608([^[:alnum:]_]|$)|refill[[:space:]]+timeout|panicked[[:space:]]+at|traceback' '$log' |
        grep -Fv 'Can not initialize OpenAIServingResponses, error: Traceback'
    "; then
      echo "fatal runtime marker found in $label: $log" >&2
      return 1
    fi
  done
}

assert_gpu_direct_workload_mode() {
  if [ "$gpu_direct_enabled" != 0 ]; then
    return 0
  fi
  local spec port label log disabled_admissions
  for spec in "${gpu_sglang_log_specs[@]}"; do
    IFS='|' read -r port label log <<<"$spec"
    disabled_admissions="$(remote "$port" "grep -c 'gpu_direct_admission=disabled' '$log' || true")"
    if [ "$disabled_admissions" -le 0 ]; then
      echo "GDR-off workload had no explicit disabled admissions on $label" >&2
      return 1
    fi
    if remote "$port" "grep -Eq 'gpu_direct_selected=1([^0-9]|$)|\"gpu_direct_selected\":[[:space:]]*1([^0-9]|$)' '$log'"; then
      echo "GDR was selected on $label during a GDR-off run" >&2
      return 1
    fi
  done
}

run_tp1_cross_client_local_smoke() {
  if [ "$sglang_layout" != tp1x2 ]; then
    return 0
  fi
  local spec port root exp label gpu_a gpu_b seed
  for spec in \
    "$port0|$root0|$exp0|node0|${gpu0_ids%%,*}|${gpu0_ids#*,}|73" \
    "$port1|$root1|$exp1|node1|${gpu1_ids%%,*}|${gpu1_ids#*,}|91"; do
    IFS='|' read -r port root exp label gpu_a gpu_b seed <<<"$spec"
    remote "$port" "
      set -euo pipefail
      key='fast25_tp1_cross_client_${run_id}_${label}'
      config_a='$root/runtime_current_cpu_remote_20260710/config/fluxon_client_current_cpu_remote_tp1_gpu${gpu_a}.yaml'
      config_b='$root/runtime_current_cpu_remote_20260710/config/fluxon_client_current_cpu_remote_tp1_gpu${gpu_b}.yaml'
      log='$exp/tp1_cross_client_smoke_${run_id}_${label}.log'
      venv='$E44_PERF_VENV_GPU'
      export PYTHONPATH='$exp'
      export FLUXON_KV_SIDE_WORKER_PYTHON=\"\$venv/bin/python\"
      export LD_LIBRARY_PATH=\"\$venv/lib/python3.10/site-packages/fluxon_pyo3:\$venv/lib/python3.10/site-packages/fluxon_pyo3.libs:\${LD_LIBRARY_PATH:-}\"
      export IBV_DRIVERS_PATH=\"\$venv/lib/python3.10/site-packages/fluxon_pyo3.libs/libibverbs.d\"
      : > \"\$log\"
      timeout --signal=TERM --kill-after=10s 120s \
        \"\$venv/bin/python\" -B '$exp/smoke_e44_r42_gpu_get.py' writer \
        --config \"\$config_a\" \
        --instance-key 'fast25_smoke_${run_id}_${label}_writer' \
        --key \"\$key\" --size 4194304 --seed '$seed' \
        --hard-exit-after-success >> \"\$log\" 2>&1
      timeout --signal=TERM --kill-after=10s 120s \
        \"\$venv/bin/python\" -B '$exp/smoke_e44_r50_plan_bind.py' \
        --config \"\$config_b\" \
        --instance-key 'fast25_smoke_${run_id}_${label}_reader' \
        --key \"\$key\" --size 4194304 --seed '$seed' \
        --hard-exit-after-success >> \"\$log\" 2>&1
      timeout --signal=TERM --kill-after=10s 120s \
        \"\$venv/bin/python\" -B - \"\$config_b\" \"\$key\" '$run_id' '$label' >> \"\$log\" 2>&1 <<'PY'
import os
import sys
import time
from fluxon_py import new_store
from smoke_e44_r42_gpu_get import build_config, consume_ok

config, key, run_id, label = sys.argv[1:]
store = consume_ok(
    new_store(build_config(config, f'fast25_smoke_{run_id}_{label}_cleanup')),
    'cleanup new_store',
)
try:
    consume_ok(store.remove(key), 'cleanup remove')
    for _ in range(120):
        if not consume_ok(store.is_exist(key), 'cleanup is_exist'):
            print(
                f'cross_client_local_smoke=passed key={key} cleanup=verified',
                flush=True,
            )
            os._exit(0)
        time.sleep(0.25)
    else:
        raise RuntimeError(f'smoke key remained visible after delete: {key}')
finally:
    consume_ok(store.close(), 'cleanup close')
PY
      grep -F 'cross_client_local_smoke=passed' \"\$log\" >/dev/null
    "
  done
}

remote_tmux() {
  local port="$1"
  shift
  local nofile_prefix=
  if [ "$ssd_enabled" = 1 ]; then
    nofile_prefix="ulimit -Sn '$tmux_nofile_soft'; test \"\$(ulimit -Sn)\" -eq '$tmux_nofile_soft';"
  fi
  remote "$port" "$nofile_prefix export TMUX_TMPDIR='$tmux_tmpdir'; $*"
}

install_managed_load_pause() {
  local port="$1"
  remote "$port" '
    lease="/run/mooncake_experiment_$(hostname).lease"
    install -m 0444 /dev/null "$lease"
    test -f "$lease"
    printf "managed_load_pause=%s\n" "$lease"
  '
}

remove_managed_load_pause() {
  local port="$1"
  remote "$port" 'rm -f "/run/mooncake_experiment_$(hostname).lease"'
}

start_cpu_interference_guard() {
  remote_tmux "$port_cpu" "
    test \"\$(sha256sum '$exp_cpu/cpu_interference_guard_e44.sh' | cut -d' ' -f1)\" = '$cpu_guard_sha256'
    rm -rf '$cpu_guard_runtime_dir'
    install -d -m 700 '$cpu_guard_runtime_dir'
    tmux has-session -t '$cpu_guard_session' 2>/dev/null && exit 1
    tmux new-session -d -s '$cpu_guard_session' -n guard \
      \"exec bash '$exp_cpu/cpu_interference_guard_e44.sh' '$cpu_guard_heartbeat' '$cpu_guard_violation' 1 >> '$cpu_guard_log' 2>&1\"
    for _ in \$(seq 1 20); do
      test -s '$cpu_guard_heartbeat' && exit 0
      test -e '$cpu_guard_violation' && { cat '$cpu_guard_violation' >&2; exit 1; }
      sleep 1
    done
    cat '$cpu_guard_log' >&2 2>/dev/null || true
    exit 1
  "
  cpu_guard_active=1
}

discover_private_ip() {
  local port="$1"
  local private_ip
  private_ip="$(remote "$port" "hostname -I" | awk '{ for (i = 1; i <= NF; i++) if ($i ~ /^10\./) { print $i; exit } }')"
  if [[ ! "$private_ip" =~ ^10\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "failed to discover private IPv4 through public port $port: $private_ip" >&2
    exit 1
  fi
  printf '%s\n' "$private_ip"
}

resolve_private_ip() {
  local port="$1"
  local override="$2"
  if [ -z "$override" ]; then
    discover_private_ip "$port"
    return
  fi
  remote "$port" "hostname -I | tr ' ' '\\n' | grep -Fx '$override' >/dev/null"
  printf '%s\n' "$override"
}

assert_remote_rdma_devices_open() {
  local port="$1"
  local label="$2"
  shift 2
  local devices=("$@")
  if ! remote "$port" "
    set -euo pipefail
    for device in ${devices[*]}; do
      verbs_dir=\"/sys/class/infiniband/\$device/device/infiniband_verbs\"
      if [ ! -d \"\$verbs_dir\" ]; then
        echo \"rdma_preflight missing_sysfs device=\$device path=\$verbs_dir\" >&2
        exit 1
      fi
      uverbs=\$(find -L \"\$verbs_dir\" -mindepth 1 -maxdepth 1 -printf '%f\\n' | head -n 1)
      node=\"/dev/infiniband/\$uverbs\"
      if [ -z \"\$uverbs\" ] || [ ! -c \"\$node\" ]; then
        echo \"rdma_preflight missing_char_device device=\$device node=\$node\" >&2
        exit 1
      fi
      python3 -c 'import os, sys; fd = os.open(sys.argv[1], os.O_RDWR); os.close(fd)' \"\$node\"
      echo \"rdma_preflight open_ok device=\$device node=\$node\"
    done
  "; then
    echo "RDMA device preflight failed on $label (public port $port)" >&2
    return 1
  fi
}

node0_ip="$(resolve_private_ip "$port0" "$node0_ip_override")"
node1_ip="$(resolve_private_ip "$port1" "$node1_ip_override")"
cpu_ip="$(resolve_private_ip "$port_cpu" "$cpu_ip_override")"
node0_public_name="$(remote "$port0" hostname)"
node1_public_name="$(remote "$port1" hostname)"
if [ -n "$node0_expected_hostname" ] && [ "$node0_public_name" != "$node0_expected_hostname" ]; then
  echo "node0 hostname mismatch: expected=$node0_expected_hostname actual=$node0_public_name" >&2
  exit 1
fi
if [ -n "$node1_expected_hostname" ] && [ "$node1_public_name" != "$node1_expected_hostname" ]; then
  echo "node1 hostname mismatch: expected=$node1_expected_hostname actual=$node1_public_name" >&2
  exit 1
fi
single_gpu_host=0
if [ "$port0" = "$port1" ] && [ "$node0_public_name" = "$node1_public_name" ]; then
  single_gpu_host=1
  if [ "$node0_ip" != "$node1_ip" ]; then
    echo "single GPU host requires identical node0/node1 private IPs" >&2
    exit 1
  fi
  if [ "$gpu0_sglang_port" = "$gpu1_sglang_port" ]; then
    echo "single GPU host requires distinct SGLang ports" >&2
    exit 1
  fi
  if [ "$gpu0_ids" = "$gpu1_ids" ]; then
    echo "single GPU host requires disjoint GPU selections" >&2
    exit 1
  fi
  IFS=',' read -r gpu0_a gpu0_b <<<"$gpu0_ids"
  for gpu_id in "$gpu0_a" "$gpu0_b"; do
    if [[ ",$gpu1_ids," == *",$gpu_id,"* ]]; then
      echo "single GPU host has overlapping GPU selections: $gpu0_ids vs $gpu1_ids" >&2
      exit 1
    fi
  done
  if [ "$workload_profile" != fast25_mlp_c24 ]; then
    echo "single GPU host is currently sealed only for fast25_mlp_c24" >&2
    exit 2
  fi
fi
cpu_public_name="$(remote "$port_cpu" hostname)"
cpu_private_name="$(remote_cpu_private "$cpu_ip" hostname)"
if [ "$cpu_private_name" != "$cpu_public_name" ]; then
  echo "CPU private control endpoint identity mismatch: public=$cpu_public_name private=$cpu_private_name ip=$cpu_ip" >&2
  exit 1
fi
cpu_control_private_ip="$cpu_ip"
cpu_control_ssh_path=node0_proxy_private_2222
printf 'cpu_control_endpoint=verified public_port=%s private=%s host=%s path=%s\n' \
  "$port_cpu" "$cpu_ip" "$cpu_public_name" "$cpu_control_ssh_path"
assert_remote_rdma_devices_open "$port_cpu" cpu mlx5_4 mlx5_6
assert_remote_rdma_devices_open "$port0" node0 "${gpu0_rdma_devices%%,*}" "${gpu0_rdma_devices#*,}"
assert_remote_rdma_devices_open "$port1" node1 "${gpu1_rdma_devices%%,*}" "${gpu1_rdma_devices#*,}"
cluster_env="FLUXON_NODE0_IP='$node0_ip' FLUXON_NODE1_IP='$node1_ip' FLUXON_CPU_NODE_IP='$cpu_ip' FLUXON_NODE2_IP='$cpu_ip'"
effective_cpu_venv="$E44_PERF_VENV_CPU"
cpu_venv_env=
if [ -n "$cpu_venv_override" ]; then
  effective_cpu_venv="$cpu_venv_override"
  remote "$port_cpu" "
    test -x '$effective_cpu_venv/bin/python'
    '$effective_cpu_venv/bin/python' -c 'import fluxon_py, fluxon_pyo3, sysconfig; assert sysconfig.get_paths()[\"purelib\"]'
  "
  cpu_venv_env="E44_HOST_CPU_VENV='$effective_cpu_venv'"
fi
if [ "$single_gpu_host" = 1 ]; then
  workload_node1_ssh=single_gpu_host_fast25_unused
  node1_forwarded_name="$node1_public_name"
else
  workload_node1_ssh="-p 2222 -o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=5 root@$node1_ip"
  node1_forwarded_name="$(
    ssh -A "${gpu_ssh_common[@]}" -p "$port0" "root@$host" \
      "test -S \"\$SSH_AUTH_SOCK\" && ssh $workload_node1_ssh hostname"
  )"
  if [ "$node1_forwarded_name" != "$node1_public_name" ]; then
    echo "workload agent-forwarded node1 identity mismatch: public=$node1_public_name forwarded=$node1_forwarded_name" >&2
    exit 1
  fi
fi

stop_tmux_matching() {
  local port="$1"
  remote_tmux "$port" '
    for session in $(tmux list-sessions -F "#{session_name}" 2>/dev/null | grep -E "^(zth_fluxon_control_e44_v5_perf|zth_fluxon_master_|zth_fluxon_owner_|zth_fluxon_remote_cpu_|zth_sglang_|zth_router_|zth_hca_observer_|zth_cpu_guard_|zth_workload_)" || true); do
      tmux send-keys -t "$session" C-c 2>/dev/null || true
    done
    sleep 3
    for session in $(tmux list-sessions -F "#{session_name}" 2>/dev/null | grep -E "^(zth_fluxon_control_e44_v5_perf|zth_fluxon_master_|zth_fluxon_owner_|zth_fluxon_remote_cpu_|zth_sglang_|zth_router_|zth_hca_observer_|zth_cpu_guard_|zth_workload_)" || true); do
      tmux kill-session -t "$session" 2>/dev/null || true
    done
  '
}

stop_interference() {
  local port="$1"
  local gpu_ids="$2"
  remote "$port" "
    if [ -x /storage/zgf/gpu_burner.sh ]; then
      bash /storage/zgf/gpu_burner.sh cancel-restart '$gpu_ids' >/dev/null 2>&1 || true
      bash /storage/zgf/gpu_burner.sh stop '$gpu_ids' --no-restart >/dev/null 2>&1 || true
    fi
  "
  if [ "$preserve_external_workloads" = 1 ]; then
    remote "$port" '
      pkill -TERM -f "[g]pu_burner.sh watchdog$|[.]gpu_burn_script_" 2>/dev/null || true
      pkill -TERM -f "[g]pu_idle_guard.py" 2>/dev/null || true
      pgrep -f "^/opt/conda/bin/python -u /storage/mjq/computing/inference_like_compute.py" 2>/dev/null |
        while IFS= read -r pid; do
          pgid=$(ps -o pgid= -p "$pid" | tr -d " ")
          test -n "$pgid" && /bin/kill -TERM -- "-$pgid" 2>/dev/null || true
        done
      sleep 5
      pkill -KILL -f "[g]pu_burner.sh watchdog$|[.]gpu_burn_script_" 2>/dev/null || true
      pkill -KILL -f "[g]pu_idle_guard.py" 2>/dev/null || true
      pgrep -f "^/opt/conda/bin/python -u /storage/mjq/computing/inference_like_compute.py" 2>/dev/null |
        while IFS= read -r pid; do
          pgid=$(ps -o pgid= -p "$pid" | tr -d " ")
          test -n "$pgid" && /bin/kill -KILL -- "-$pgid" 2>/dev/null || true
        done
    '
    return
  fi
  remote "$port" '
    kill_external_runtime_groups() {
      signal="$1"
      self_pgid=$(ps -o pgid= -p $$ | tr -d " ")
      regex="[/]pvcteam/mjq/vlm_fluxon/VLCache-Sglang.*[s]glang.launch_server|[s]tart_vlcache_server.sh|[r]clone_benchmark/scripts/run_formal.py|[f]luxon_bench_keeper_[0-9]+.sh|[/]pvcteam/mjq/fluxon_s3_benchmark.*[f]luxon_py.runtime.start_(master|owner_kvclient)|[/]pvcteam/mjq/fluxon_s3_benchmark/[j]ava/bin/java|[r]eset_alluxio_formal.sh|[s]tart_alluxio_formal.sh|[/]alluxio/bin/[a]lluxio"
      pgrep -f "$regex" 2>/dev/null | while IFS= read -r pid; do
        comm=$(ps -o comm= -p "$pid" 2>/dev/null | tr -d " ")
        case "$comm" in grep|find|rg|sed|cat|ps|pgrep) continue ;; esac
        pgid=$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d " ")
        test -n "$pgid" && test "$pgid" -gt 1 && test "$pgid" != "$self_pgid" && printf "%s\n" "$pgid"
      done | sort -nu | while IFS= read -r pgid; do
        /bin/kill -s "$signal" -- "-$pgid" 2>/dev/null || true
      done
    }
    kill_external_runtime_groups TERM
    tmux list-panes -a -F "#{session_name}|#{pane_current_path}|#{pane_start_command}" 2>/dev/null |
      grep -E "[s]tart_vlcache_server.sh|[s]glang.launch_server|[r]clone_benchmark/scripts/run_formal.py|[f]luxon_bench_keeper_[0-9]+.sh|[r]eset_alluxio_formal.sh|[s]tart_alluxio_formal.sh" |
      cut -d"|" -f1 | sort -u | while IFS= read -r session; do
      test -n "$session" || continue
      tmux send-keys -t "$session" C-c 2>/dev/null || true
      tmux kill-session -t "$session" 2>/dev/null || true
    done
    pkill -TERM -f "[g]pu_burner.sh watchdog$|[.]gpu_burn_script_" 2>/dev/null || true
    pkill -TERM -f "[g]pu_idle_guard.py" 2>/dev/null || true
    pgrep -f "^/opt/conda/bin/python -u /storage/mjq/computing/inference_like_compute.py" 2>/dev/null |
      while IFS= read -r pid; do
      pgid=$(ps -o pgid= -p "$pid" | tr -d " ")
      test -n "$pgid" && /bin/kill -TERM -- "-$pgid" 2>/dev/null || true
    done
    sleep 5
    kill_external_runtime_groups KILL
    pkill -KILL -f "[g]pu_burner.sh watchdog$|[.]gpu_burn_script_" 2>/dev/null || true
    pkill -KILL -f "[g]pu_idle_guard.py" 2>/dev/null || true
    pgrep -f "^/opt/conda/bin/python -u /storage/mjq/computing/inference_like_compute.py" 2>/dev/null |
      while IFS= read -r pid; do
      pgid=$(ps -o pgid= -p "$pid" | tr -d " ")
      test -n "$pgid" && /bin/kill -KILL -- "-$pgid" 2>/dev/null || true
    done
  '
}

wait_empty_gpu() {
  local port="$1"
  local gpu_ids="$2"
  for _ in $(seq 1 30); do
    if remote "$port" "
      test -z \"\$(nvidia-smi -i '$gpu_ids' --query-compute-apps=pid --format=csv,noheader 2>/dev/null | sed '/^[[:space:]]*$/d')\" &&
      nvidia-smi -i '$gpu_ids' --query-gpu=memory.used,utilization.gpu --format=csv,noheader,nounits |
        awk -F, -v tolerance='$gpu_idle_memory_tolerance_mib' '(\$1 + 0 > tolerance || \$2 + 0 != 0) { bad=1 } END { exit bad ? 1 : 0 }'
    "; then
      return 0
    fi
    sleep 1
  done
  remote "$port" "nvidia-smi -i '$gpu_ids' --query-compute-apps=pid,process_name,used_memory --format=csv,noheader; nvidia-smi -i '$gpu_ids' --query-gpu=index,memory.used,utilization.gpu --format=csv,noheader,nounits" >&2
  return 1
}

assert_no_external_interference() {
  local spec port label
  local specs=("$port0:node0" "$port1:node1")
  if [ "$cpu_guard_active" != 1 ]; then
    specs+=("$port_cpu:cpu")
  fi
  for spec in "${specs[@]}"; do
    port="${spec%%:*}"
    label="${spec#*:}"
    if ! remote "$port" '
      self_pgid=$(ps -o pgid= -p $$ | tr -d " ")
      regex="[/]pvcteam/mjq/vlm_fluxon/VLCache-Sglang.*[s]glang.launch_server|[s]tart_vlcache_server.sh|[r]clone_benchmark/scripts/run_formal.py|[f]luxon_bench_keeper_[0-9]+.sh|[/]pvcteam/mjq/fluxon_s3_benchmark.*[f]luxon_py.runtime.start_(master|owner_kvclient)|[/]pvcteam/mjq/fluxon_s3_benchmark/[j]ava/bin/java|[r]eset_alluxio_formal.sh|[s]tart_alluxio_formal.sh|[/]alluxio/bin/[a]lluxio|[i]nference_like_compute.py|[.]gpu_burn_script_|[g]pu_burner.sh watchdog$|[g]pu_idle_guard.py"
      conflicts="$(
        pgrep -f "$regex" 2>/dev/null |
          while IFS= read -r pid; do
          comm=$(ps -o comm= -p "$pid" 2>/dev/null | tr -d " ")
          case "$comm" in grep|find|rg|sed|cat|ps|pgrep) continue ;; esac
          pgid=$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d " ")
          test -n "$pgid" && test "$pgid" = "$self_pgid" && continue
          ps -o pid=,args= -p "$pid" 2>/dev/null || true
        done
      )"
      if [ -n "$conflicts" ]; then
        printf "%s\n" "$conflicts" >&2
        exit 1
      fi
    '; then
      echo "external interference detected on $label; refusing performance measurement" >&2
      return 1
    fi
  done
}

wait_cpu_control_recovery() {
  local socket
  for socket in "$ssh_control_dir"/*; do
    [ -S "$socket" ] || continue
    timeout 2 ssh -q -S "$socket" -O exit ignored >/dev/null 2>&1 || true
    rm -f "$socket"
  done
  for _ in $(seq 1 45); do
    if remote_cpu_private_no_mux "$cpu_control_private_ip" true >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  return 1
}

finalize_cpu_runtime_evidence() {
  if ! wait_cpu_control_recovery; then
    echo "CPU control SSH did not recover after the workload" >&2
    return 1
  fi
  remote_tmux "$port_cpu" "
    set -e
    E44_HCA_OBSERVER_RESULT_DIR='$cpu_hca_runtime_dir' \
      bash '$exp_cpu/manage_hca_observer_e44_r28.sh' stop '$root_cpu' cpu 500 '$run_id'
    if tmux has-session -t '$cpu_guard_session' 2>/dev/null; then
      tmux send-keys -t '$cpu_guard_session' C-c
      for _ in \$(seq 1 20); do
        tmux has-session -t '$cpu_guard_session' 2>/dev/null || break
        sleep 0.25
      done
      tmux has-session -t '$cpu_guard_session' 2>/dev/null && tmux kill-session -t '$cpu_guard_session'
    fi
    test ! -e '$cpu_guard_violation'
    heartbeat=\$(cat '$cpu_guard_heartbeat')
    now=\$(date +%s)
    age=\$((now - heartbeat))
    test \"\$age\" -ge 0
    test \"\$age\" -le 10
    test -s '$cpu_hca_runtime_jsonl'
    install -d -m 755 '$exp_cpu/netobs_results'
    cp -a '$cpu_hca_runtime_jsonl' '$exp_cpu/netobs_results/${run_id}_cpu.jsonl'
    cp -a '$cpu_hca_runtime_log' '$exp_cpu/netobs_results/${run_id}_cpu.log'
    cp -a '$cpu_guard_heartbeat' '$cpu_guard_evidence_heartbeat'
    cp -a '$cpu_guard_log' '$cpu_guard_evidence_log'
    rm -f '$cpu_guard_evidence_violation'
  "
}

restore_burners() {
  local failures=0
  for port in "$port0" "$port1"; do
    if ! remote "$port" '
      kill_external_runtime_groups() {
        signal="$1"
        self_pgid=$(ps -o pgid= -p $$ | tr -d " ")
        regex="[/]pvcteam/mjq/vlm_fluxon/VLCache-Sglang.*[s]glang.launch_server|[s]tart_vlcache_server.sh|[r]clone_benchmark/scripts/run_formal.py|[f]luxon_bench_keeper_[0-9]+.sh|[/]pvcteam/mjq/fluxon_s3_benchmark.*[f]luxon_py.runtime.start_(master|owner_kvclient)|[/]pvcteam/mjq/fluxon_s3_benchmark/[j]ava/bin/java|[r]eset_alluxio_formal.sh|[s]tart_alluxio_formal.sh|[/]alluxio/bin/[a]lluxio"
        pgrep -f "$regex" 2>/dev/null | while IFS= read -r pid; do
          comm=$(ps -o comm= -p "$pid" 2>/dev/null | tr -d " ")
          case "$comm" in grep|find|rg|sed|cat|ps|pgrep) continue ;; esac
          pgid=$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d " ")
          test -n "$pgid" && test "$pgid" -gt 1 && test "$pgid" != "$self_pgid" && printf "%s\n" "$pgid"
        done | sort -nu | while IFS= read -r pgid; do
          /bin/kill -s "$signal" -- "-$pgid" 2>/dev/null || true
        done
      }
      kill_external_runtime_groups TERM
      tmux list-panes -a -F "#{session_name}|#{pane_current_path}|#{pane_start_command}" 2>/dev/null |
        grep -E "[s]tart_vlcache_server.sh|[s]glang.launch_server|[r]clone_benchmark/scripts/run_formal.py|[f]luxon_bench_keeper_[0-9]+.sh|[r]eset_alluxio_formal.sh|[s]tart_alluxio_formal.sh" |
        cut -d"|" -f1 | sort -u | while IFS= read -r session; do
        test -n "$session" || continue
        tmux send-keys -t "$session" C-c 2>/dev/null || true
        tmux kill-session -t "$session" 2>/dev/null || true
      done
      bash /storage/zgf/gpu_burner.sh cancel-restart 0,1 >/dev/null 2>&1 || true
      bash /storage/zgf/gpu_burner.sh stop 0,1 --no-restart >/dev/null 2>&1 || true
      pkill -TERM -f "[g]pu_burner.sh watchdog$|[.]gpu_burn_script_" 2>/dev/null || true
      pkill -TERM -f "[g]pu_idle_guard.py" 2>/dev/null || true
      pgrep -f "^/opt/conda/bin/python -u /storage/mjq/computing/inference_like_compute.py" 2>/dev/null |
        while IFS= read -r pid; do
        pgid=$(ps -o pgid= -p "$pid" | tr -d " ")
        test -n "$pgid" && /bin/kill -TERM -- "-$pgid" 2>/dev/null || true
      done
      sleep 2
      kill_external_runtime_groups KILL
      pkill -KILL -f "[g]pu_burner.sh watchdog$|[.]gpu_burn_script_" 2>/dev/null || true
      pkill -KILL -f "[g]pu_idle_guard.py" 2>/dev/null || true
      pgrep -f "^/opt/conda/bin/python -u /storage/mjq/computing/inference_like_compute.py" 2>/dev/null |
        while IFS= read -r pid; do
        pgid=$(ps -o pgid= -p "$pid" | tr -d " ")
        test -n "$pgid" && /bin/kill -KILL -- "-$pgid" 2>/dev/null || true
      done
      bash /storage/zgf/gpu_burner.sh cancel-restart 0,1 >/dev/null 2>&1 || true
      bash /storage/zgf/gpu_burner.sh start 0,1 >/dev/null
    '; then
      echo "failed to issue managed burner restore on port $port" >&2
      failures=1
      continue
    fi

    local consecutive_ready=0
    for _ in $(seq 1 60); do
      if remote "$port" '
        self_pgid=$(ps -o pgid= -p $$ | tr -d " ")
        regex="[/]pvcteam/mjq/vlm_fluxon/VLCache-Sglang.*[s]glang.launch_server|[s]tart_vlcache_server.sh|[r]clone_benchmark/scripts/run_formal.py|[f]luxon_bench_keeper_[0-9]+.sh|[/]pvcteam/mjq/fluxon_s3_benchmark.*[f]luxon_py.runtime.start_(master|owner_kvclient)|[/]pvcteam/mjq/fluxon_s3_benchmark/[j]ava/bin/java|[r]eset_alluxio_formal.sh|[s]tart_alluxio_formal.sh|[/]alluxio/bin/[a]lluxio"
        workers=$(pgrep -af "^/opt/conda/bin/python -u /public/zgf/[.]gpu_burn_script_.* --gpu [01]$" | wc -l)
        watchdogs=$(pgrep -af "^bash /storage/zgf/gpu_burner.sh watchdog$" | wc -l)
        test "$workers" -eq 2
        test "$watchdogs" -eq 1
        test -z "$(pgrep -af "^/opt/conda/bin/python -u /storage/mjq/computing/inference_like_compute.py" || true)"
        test -z "$(
          pgrep -f "$regex" 2>/dev/null |
            while IFS= read -r pid; do
            comm=$(ps -o comm= -p "$pid" 2>/dev/null | tr -d " ")
            case "$comm" in grep|find|rg|sed|cat|ps|pgrep) continue ;; esac
            pgid=$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d " ")
            test -n "$pgid" && test "$pgid" = "$self_pgid" && continue
            ps -o pid=,args= -p "$pid" 2>/dev/null || true
          done
        )"
        test -z "$(pgrep -af "[g]pu_idle_guard.py" || true)"
        nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv,noheader,nounits |
          awk -F, "
            \$1 + 0 < 2 {
              seen += 1
              if (\$2 + 0 < 1000 || \$3 + 0 < 90) bad = 1
            }
            END { exit !(seen == 2 && bad == 0) }
          "
      '; then
        consecutive_ready=$((consecutive_ready + 1))
        if [ "$consecutive_ready" -ge 3 ]; then
          break
        fi
      else
        consecutive_ready=0
      fi
      sleep 2
    done
    if [ "$consecutive_ready" -lt 3 ]; then
      echo "managed burner restore did not become stable on port $port" >&2
      remote "$port" '
        pgrep -af "[.]gpu_burn_script_|[g]pu_burner.sh watchdog$|[i]nference_like_compute.py|[/]pvcteam/mjq/vlm_fluxon/VLCache-Sglang|[g]pu_idle_guard.py" || true
        nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv,noheader,nounits
        nvidia-smi --query-compute-apps=gpu_uuid,pid,process_name,used_memory --format=csv,noheader,nounits 2>/dev/null || true
      ' >&2 || true
      failures=1
    fi
  done
  return "$failures"
}

cleanup() {
  local rc=$?
  if [ "$cleanup_started" = 1 ]; then
    return "$rc"
  fi
  cleanup_started=1
  trap - EXIT INT TERM
  set +e
  if [ -n "${workload_ssh_pid:-}" ] && kill -0 "$workload_ssh_pid" 2>/dev/null; then
    kill -TERM "$workload_ssh_pid" 2>/dev/null || true
    wait "$workload_ssh_pid" 2>/dev/null || true
  fi
  workload_ssh_pid=
  stop_tmux_matching "$port0"
  stop_tmux_matching "$port1"
  if wait_cpu_control_recovery; then
    stop_tmux_matching "$port_cpu"
  else
    echo "CPU control SSH did not recover within 90 seconds during cleanup" >&2
  fi
  remote "$port0" "rm -rf '$tmux_tmpdir'" || true
  remote "$port1" "rm -rf '$tmux_tmpdir'" || true
  remote "$port_cpu" "rm -rf '$tmux_tmpdir'" || true
  remote "$port0" 'pkill -TERM -f "[s]table_session_proxy_e44.py|[h]ca_observer_e44_r28.py|fluxon_py.runtime.[s]tart_master" 2>/dev/null || true'
  remote "$port1" 'pkill -TERM -f "[h]ca_observer_e44_r28.py" 2>/dev/null || true'
  remote "$port_cpu" 'pkill -TERM -f "[h]ca_observer_e44_r28.py" 2>/dev/null || true'
  remote "$port_cpu" "rm -rf '$cpu_guard_runtime_dir' '$cpu_hca_runtime_dir'" || true
  remote "$port0" "rm -f '/run/cluster_e44_${run_id}.env'" || true
  remote "$port0" "rm -f '$exp0/capacity_control_${run_id}_before_workload.json' '$exp0/capacity_control_${run_id}_after_workload.json' '$exp0/capacity_control_${run_id}_before_workload.log' '$exp0/capacity_control_${run_id}_after_workload.log' '$exp0/request_corpus_${run_id}.json' '$exp0/fast25_capacity_${run_id}.json' '$exp0/fast25_result_dir_${run_id}.txt' '$exp0/fast25_ssd_snapshot_${run_id}.json'" || true
  if [ "$ssd_enabled" = 1 ]; then
    remote "$port0" "rm -rf '$ssd_root'" || true
    remote "$port1" "rm -rf '$ssd_root'" || true
    remote "$port_cpu" "rm -rf '$ssd_root'" || true
  fi
  if [ "${E44_CAPACITY_KEEP_BURNERS_STOPPED:-0}" != 1 ]; then
    remove_managed_load_pause "$port0" || true
    remove_managed_load_pause "$port1" || true
    if ! restore_burners; then
      echo "one or more managed burner restores failed validation" >&2
      if [ "$rc" = 0 ]; then
        rc=1
      fi
    fi
  fi
  return "$rc"
}
on_signal() {
  exit 130
}
trap cleanup EXIT
trap on_signal INT TERM

for port in "$port0" "$port1" "$port_cpu"; do
  remote "$port" "rm -rf '$tmux_tmpdir'; install -d -m 700 '$tmux_tmpdir'"
done

if [ -n "$assistant_history_replay_file" ]; then
  remote "$port0" "
    test -f '$assistant_history_replay_file'
    test \"\$(sha256sum '$assistant_history_replay_file' | cut -d' ' -f1)\" = '$assistant_history_replay_sha256'
  "
fi

install_managed_load_pause "$port0"
install_managed_load_pause "$port1"

ssd_node0_env=
ssd_node1_env=
ssd_cpu_env=
if [ "$ssd_enabled" = 1 ]; then
  ssd_specs=()
  if [ "$ssd_scope" = all_owners ] || [ "$ssd_scope" = remote_cpu_only ]; then
    ssd_specs+=("$port_cpu:$cpu_ssd_capacity_bytes")
  fi
  if [ "$ssd_scope" = all_owners ] || [ "$ssd_scope" = gpu_local_only ]; then
    ssd_specs+=("$port0:$gpu_ssd_capacity_bytes" "$port1:$gpu_ssd_capacity_bytes")
  fi
  for spec in "${ssd_specs[@]}"
  do
    port="${spec%%:*}"
    capacity="${spec#*:}"
    required=$((capacity + ssd_safety_margin_bytes))
    remote "$port" "
      test \"\$(findmnt -n -o FSTYPE -T /tmp)\" = xfs
      test \"\$(ulimit -Hn)\" -ge '$tmux_nofile_soft'
      available=\$(df -B1 --output=avail /tmp | tail -n 1 | tr -d ' ')
      test \"\$available\" -ge '$required'
      rm -rf '$ssd_root'
      install -d -m 700 '$ssd_root'
    "
  done
  if [ "$ssd_scope" = all_owners ] || [ "$ssd_scope" = gpu_local_only ]; then
    ssd_node0_env="E44_HOST_GPU_STACK_SCRIPT='$root0/fluxon_release/start_gpu_stack_owner_numa1_ssd.sh' FLUXON_EXTERNAL_OWNER_LARGE_FILE_ROOT='$ssd_root' FLUXON_EXTERNAL_OWNER_SSD_CAPACITY_BYTES='$gpu_ssd_capacity_bytes' FLUXON_EXTERNAL_OWNER_SSD_WRITE_RATE_LIMIT_BYTES_PER_SEC='$gpu_ssd_write_rate_bytes_per_sec' FLUXON_EXTERNAL_OWNER_SSD_WRITE_BURST_BYTES='$gpu_ssd_write_burst_bytes' FLUXON_EXTERNAL_OWNER_SSD_CAPACITY_WRITEBACK_ENABLED='$gpu_ssd_capacity_writeback_enabled'"
    ssd_node1_env="E44_HOST_GPU_STACK_SCRIPT='$root1/fluxon_release/start_gpu_stack_owner_numa1_ssd.sh' FLUXON_EXTERNAL_OWNER_LARGE_FILE_ROOT='$ssd_root' FLUXON_EXTERNAL_OWNER_SSD_CAPACITY_BYTES='$gpu_ssd_capacity_bytes' FLUXON_EXTERNAL_OWNER_SSD_WRITE_RATE_LIMIT_BYTES_PER_SEC='$gpu_ssd_write_rate_bytes_per_sec' FLUXON_EXTERNAL_OWNER_SSD_WRITE_BURST_BYTES='$gpu_ssd_write_burst_bytes' FLUXON_EXTERNAL_OWNER_SSD_CAPACITY_WRITEBACK_ENABLED='$gpu_ssd_capacity_writeback_enabled'"
  fi
  if [ "$ssd_scope" = all_owners ] || [ "$ssd_scope" = remote_cpu_only ]; then
    ssd_cpu_env="E44_HOST_CPU_OWNER_SCRIPT='$root_cpu/fluxon_release/start_cpu_owner_numa1_ssd.sh' FLUXON_CPU_OWNER_LARGE_FILE_ROOT='$ssd_root' FLUXON_CPU_OWNER_SSD_CAPACITY_BYTES='$cpu_ssd_capacity_bytes'"
  fi
fi

stop_tmux_matching "$port0"
stop_tmux_matching "$port1"
stop_tmux_matching "$port_cpu"
stop_interference "$port0" "$gpu0_ids"
stop_interference "$port1" "$gpu1_ids"
wait_empty_gpu "$port0" "$gpu0_ids"
wait_empty_gpu "$port1" "$gpu1_ids"
assert_no_external_interference

remote_tmux "$port0" "$cluster_env bash '$exp0/start_control_e44_v5_perf.sh' '$root0' zth_fluxon_control_e44_v5_perf"
remote_tmux "$port0" "tmux new-session -d -s 'zth_fluxon_master_${run_id}' -n master \"$cluster_env E44_PERF_RUN_ID_OVERRIDE='$run_id' exec bash '$exp0/launch_master_e44_v5_perf.sh' '$root0' '$variant'\""

start_cpu_owner() {
  remote_tmux "$port_cpu" "$cluster_env $cpu_venv_env $ssd_cpu_env E44_PERF_RUN_ID_OVERRIDE='$run_id' E44_HOST_CPU_OWNER_DRAM_BYTES='$cpu_dram_bytes' FLUXON_CPU_RDMA_READY_TIMEOUT='$cpu_rdma_ready_timeout_seconds' FLUXON_CPU_TCP_THREAD_CONTROL_LANE_COUNT='$tcp_control_lane_count' bash '$exp_cpu/launch_cpu_e44_r28_netobs.sh' '$root_cpu' '$cpu_variant'" \
    >"$local_artifact/start_cpu.log" 2>&1 &
  pid_cpu=$!
}

pid_cpu=
if [ "$stagger_cpu_owner" = 0 ]; then
  start_cpu_owner
fi

remote "$port0" ": > '$root0/log/current_cpu_remote_20260710/owner.log'"
remote "$port1" ": > '$root1/log/current_cpu_remote_20260710/owner.log'"
remote_tmux "$port0" "$cluster_env $ssd_node0_env E44_PERF_RUN_ID_OVERRIDE='$run_id' E44_GPU_SELECTED_IDS='$gpu0_ids' E44_HOST_GPU_A='${gpu0_ids%%,*}' E44_HOST_GPU_B='${gpu0_ids#*,}' E44_HOST_SGLANG_LAYOUT='$sglang_layout' E44_HOST_OWNER_LOCAL_RESERVE_VALUE_LEN='$owner_local_reserve_value_len' E44_HOST_SGLANG_PORT='$gpu0_sglang_port' E44_HOST_SGLANG_PORT_B='$gpu0_sglang_port_b' E44_HOST_OWNER_CPUSET='$gpu0_owner_cpuset' E44_HOST_RDMA_DEVICE_0='${gpu0_rdma_devices%%,*}' E44_HOST_RDMA_DEVICE_1='${gpu0_rdma_devices#*,}' E44_HOST_GPU_OWNER_DRAM_BYTES='$gpu_dram_bytes' E44_HOST_GPU_OWNER_LOCAL_PAYLOAD_BYTES='$gpu_payload_bytes' E44_GPU_IDLE_MEMORY_TOLERANCE_MIB='$gpu_idle_memory_tolerance_mib' FLUXON_EXTERNAL_RDMA_READY_TIMEOUT='$gpu_rdma_ready_timeout_seconds' FLUXON_EXTERNAL_SHARED_JSON_TIMEOUT='$gpu_shared_json_timeout_seconds' bash '$exp0/launch_gpu_e44_r38_guarded.sh' '$root0' node0 '$variant'" \
  >"$local_artifact/start_node0.log" 2>&1 &
pid0=$!
remote_tmux "$port1" "$cluster_env $ssd_node1_env E44_PERF_RUN_ID_OVERRIDE='$run_id' E44_GPU_SELECTED_IDS='$gpu1_ids' E44_HOST_GPU_A='${gpu1_ids%%,*}' E44_HOST_GPU_B='${gpu1_ids#*,}' E44_HOST_SGLANG_LAYOUT='$sglang_layout' E44_HOST_OWNER_LOCAL_RESERVE_VALUE_LEN='$owner_local_reserve_value_len' E44_HOST_SGLANG_PORT='$gpu1_sglang_port' E44_HOST_SGLANG_PORT_B='$gpu1_sglang_port_b' E44_HOST_OWNER_CPUSET='$gpu1_owner_cpuset' E44_HOST_RDMA_DEVICE_0='${gpu1_rdma_devices%%,*}' E44_HOST_RDMA_DEVICE_1='${gpu1_rdma_devices#*,}' E44_HOST_GPU_OWNER_DRAM_BYTES='$gpu_dram_bytes' E44_HOST_GPU_OWNER_LOCAL_PAYLOAD_BYTES='$gpu_payload_bytes' E44_GPU_IDLE_MEMORY_TOLERANCE_MIB='$gpu_idle_memory_tolerance_mib' FLUXON_EXTERNAL_RDMA_READY_TIMEOUT='$gpu_rdma_ready_timeout_seconds' FLUXON_EXTERNAL_SHARED_JSON_TIMEOUT='$gpu_shared_json_timeout_seconds' bash '$exp1/launch_gpu_e44_r38_guarded.sh' '$root1' node1 '$variant'" \
  >"$local_artifact/start_node1.log" 2>&1 &
pid1=$!
if [ "$stagger_cpu_owner" = 1 ]; then
  gpu_owners_ready=0
  for _ in $(seq 1 240); do
    if ! kill -0 "$pid0" 2>/dev/null || ! kill -0 "$pid1" 2>/dev/null; then
      echo "GPU launcher exited before both GPU owners became ready" >&2
      tail -n 120 "$local_artifact/start_node0.log" >&2 || true
      tail -n 120 "$local_artifact/start_node1.log" >&2 || true
      exit 1
    fi
    if remote "$port0" "grep -F 'Owner ready: written shared.json' '$root0/log/current_cpu_remote_20260710/owner.log' >/dev/null" &&
       remote "$port1" "grep -F 'Owner ready: written shared.json' '$root1/log/current_cpu_remote_20260710/owner.log' >/dev/null"; then
      gpu_owners_ready=1
      break
    fi
    sleep 3
  done
  if [ "$gpu_owners_ready" != 1 ]; then
    echo "GPU owners did not become ready before stagger timeout" >&2
    exit 1
  fi
  start_cpu_owner
fi
if ! wait "$pid_cpu"; then
  tail -n 120 "$local_artifact/start_cpu.log" >&2
  exit 1
fi
if ! wait "$pid0"; then
  tail -n 120 "$local_artifact/start_node0.log" >&2
  exit 1
fi
if ! wait "$pid1"; then
  tail -n 120 "$local_artifact/start_node1.log" >&2
  exit 1
fi

remote "$port0" "curl -fsS --max-time 5 http://127.0.0.1:$gpu0_sglang_port/health >/dev/null"
remote "$port1" "curl -fsS --max-time 5 http://127.0.0.1:$gpu1_sglang_port/health >/dev/null"
if [ "$sglang_layout" = tp1x2 ]; then
  remote "$port0" "curl -fsS --max-time 5 http://127.0.0.1:$gpu0_sglang_port_b/health >/dev/null"
  remote "$port1" "curl -fsS --max-time 5 http://127.0.0.1:$gpu1_sglang_port_b/health >/dev/null"
fi
start_cpu_interference_guard
assert_no_external_interference
assert_runtime_pyo3_identity
assert_gpu_owner_payload_capacity
assert_gpu_owner_local_reserve_value_len
assert_gpu_ssd_capacity_writeback_mode
assert_gpu_direct_startup_mode
run_tp1_cross_client_local_smoke

if [ "$capacity_control_enabled" = 1 ]; then
  run_capacity_control before_workload set-wait "$effective_cpu_active_capacity_bytes" \
    | tee "$local_artifact/capacity_before_workload.json"
  sleep 2
  assert_no_external_interference
fi

remote_tmux "$port0" "bash '$exp0/manage_hca_observer_e44_r28.sh' start '$root0' node0 500 '$run_id'"
remote_tmux "$port1" "bash '$exp1/manage_hca_observer_e44_r28.sh' start '$root1' node1 500 '$run_id'"
remote_tmux "$port_cpu" "E44_HCA_OBSERVER_RESULT_DIR='$cpu_hca_runtime_dir' bash '$exp_cpu/manage_hca_observer_e44_r28.sh' start '$root_cpu' cpu 500 '$run_id'"
workload_script_path=
case "$workload_profile" in
  s96_w2_c24)
    router_launcher=launch_stable_session_proxy_e44.sh
    router_arg="$run_id"
    router_sha256=e7546294b4c39fb657ab2efaeacd09fa024943d615aadddf5a4b1e4dc1c3cfcf
    router_backend_sha256=1b6c32f8ae80cdd5079a0f9459172a78f44edec95959c56a268a6ca770afd100
    workload_script=run_workload_e44_r28_netobs.sh
    workload_sha256=9177f8fad0a1c07ef1ab657ab56a7893cfdb52499cc3f15d2ca6a27245007c5a
    workload_suffix=s96_t24_sys8192_out8_c24_session_stream_20260719
    expected_requests=2304
    expected_sessions=96
    expected_turns=24
    request_corpus_required=1
    ;;
  s48_w1_c12)
    router_launcher=launch_stable_session_proxy_e44_scaling_w1.sh
    router_arg="$run_id"
    router_sha256=af375835345efc712842f19b779b2addeeb3bbe07c42073bca3c413e7304b918
    workload_script=run_workload_e44_scaling_s48_c12_w1.sh
    workload_sha256=bb7456f559242a499046557258768d72a91915b54462ce79d07a63c333a34a72
    workload_suffix=s48_t24_sys8192_out8_c12_session_stream_w1_20260724
    expected_requests=1152
    expected_sessions=48
    expected_turns=24
    request_corpus_required=0
    ;;
  fast25_mlp_c24)
    router_launcher=launch_router_e44_v5_perf.sh
    router_arg="$variant"
    router_sha256=ede2145a7628be934078af572d0dd42b61029bd4b1bd90faa6ad5f7d1769d888
    workload_script=run_workload_fast25_multilevel.sh
    case "$FAST25_MLP_WORKLOAD_PROFILE_ID" in
      s96_wss296)
        workload_script_path="$exp0/$workload_script"
        workload_sha256=974d072c3205b974262bcc1bf6f52f143d1641928bf5ee8ec4630593aa42b6fc
        ;;
      s96_wss441|s80_wss364)
        workload_script_path="$fast25_deployment_dir/experiment_configs/e44_local_slot_tier_20260716/$workload_script"
        workload_sha256=35caffbbf4cd8d73a83041bdbf511e9c426e6bea9985b4fd54eef38212005c7b
        ;;
    esac
    workload_suffix="$FAST25_MLP_WORKLOAD_SUFFIX"
    expected_requests="$FAST25_MLP_EXPECTED_REQUESTS"
    expected_sessions="$FAST25_MLP_EXPECTED_SESSIONS"
    expected_turns=24
    request_corpus_required=0
    ;;
  *)
    echo "unsupported workload profile: $workload_profile" >&2
    exit 2
    ;;
esac
workload_script_path="${workload_script_path:-$exp0/$workload_script}"
router_node0_http_host="$node0_ip"
router_node1_http_host="$node1_ip"
router_http_host="$node0_ip"
if [ "$single_gpu_host" = 1 ]; then
  router_node0_http_host=127.0.0.1
  router_node1_http_host=127.0.0.1
  router_http_host=127.0.0.1
fi
remote_tmux "$port0" "
  test \"\$(sha256sum '$exp0/$router_launcher' | cut -d' ' -f1)\" = '$router_sha256'
  if [ '$workload_profile' = s96_w2_c24 ]; then
    test \"\$(sha256sum '$exp0/stable_session_proxy_e44.py' | cut -d' ' -f1)\" = '$router_backend_sha256'
  fi
  $cluster_env E44_PERF_RUN_ID_OVERRIDE='$run_id' E44_ROUTER_SGLANG_LAYOUT='$sglang_layout' E44_ROUTER_NODE0_HOST='$router_node0_http_host' E44_ROUTER_NODE1_HOST='$router_node1_http_host' E44_ROUTER_NODE0_PORT='$gpu0_sglang_port' E44_ROUTER_NODE1_PORT='$gpu1_sglang_port' E44_ROUTER_NODE0_PORT_B='$gpu0_sglang_port_b' E44_ROUTER_NODE1_PORT_B='$gpu1_sglang_port_b' bash '$exp0/$router_launcher' '$root0' '$router_arg'
"
expected_router_workers=2
[ "$sglang_layout" = tp1x2 ] && expected_router_workers=4
remote "$port0" "
  test \"\$(curl -fsS --max-time 5 http://127.0.0.1:32000/health | python3 -c 'import json, sys; print(len(json.load(sys.stdin)[\"workers\"]))')\" = '$expected_router_workers'
"

workload_tag="fluxon_${run_id}_${workload_suffix}"
workload_rc="$exp0/workload_${workload_tag}.rc"
workload_log="$exp0/workload_${workload_tag}.log"
remote "$port0" "
  test \"\$(sha256sum '$workload_script_path' | cut -d' ' -f1)\" = '$workload_sha256'
  rm -f '$workload_rc' '$workload_log'
"
workload_namespace_env=
if [ -n "$workload_prefix_namespace" ]; then
  workload_namespace_env="E44_WORKLOAD_PREFIX_NAMESPACE_OVERRIDE='$workload_prefix_namespace'"
fi
workload_replay_env=
if [ -n "$assistant_history_replay_file" ]; then
  workload_replay_env="E44_WORKLOAD_ASSISTANT_HISTORY_REPLAY_FILE='$assistant_history_replay_file' E44_WORKLOAD_ASSISTANT_HISTORY_REPLAY_SHA256='$assistant_history_replay_sha256'"
fi
fast25_workload_env=
if [ "$workload_profile" = fast25_mlp_c24 ]; then
  fast25_workload_env="FAST25_MLP_DEPLOYMENT_DIR='$fast25_deployment_dir' FAST25_MLP_WORKLOAD_PROFILE='$FAST25_MLP_WORKLOAD_PROFILE_ID' FAST25_MLP_E44_RUNTIME_SCRIPT_DIR='$exp0' FAST25_MLP_RUNTIME_DIR='$exp0' FAST25_MLP_ARM='$fast25_arm' FAST25_MLP_RESULT_ROOT='$fast25_result_root' FAST25_MLP_SGLANG_LAYOUT='$sglang_layout' FAST25_MLP_GPU0_HTTP_HOST='$router_node0_http_host' FAST25_MLP_GPU1_HTTP_HOST='$router_node1_http_host' FAST25_MLP_ROUTER_HTTP_HOST='$router_http_host'"
elif [ "$workload_profile" = s96_w2_c24 ]; then
  fast25_workload_env="E44_WORKLOAD_NODE0_HOST='$router_node0_http_host' E44_WORKLOAD_NODE1_HOST='$router_node1_http_host' E44_WORKLOAD_ROUTER_HOST='$router_http_host' E44_WORKLOAD_NODE0_PORT='$gpu0_sglang_port' E44_WORKLOAD_NODE1_PORT='$gpu1_sglang_port' E44_WORKLOAD_ROUTER_PORT=32000"
fi
ssh -A "${gpu_ssh_common[@]}" -p "$port0" "root@$host" \
  "$cluster_env $workload_namespace_env $workload_replay_env $fast25_workload_env E44_PERF_RUN_ID_OVERRIDE='$run_id' E44_WORKLOAD_NODE1_SSH='$workload_node1_ssh' FAST25_MLP_GPU0_SGLANG_PORT='$gpu0_sglang_port' FAST25_MLP_GPU1_SGLANG_PORT='$gpu1_sglang_port' FAST25_MLP_GPU0_SGLANG_PORT_B='$gpu0_sglang_port_b' FAST25_MLP_GPU1_SGLANG_PORT_B='$gpu1_sglang_port_b' FAST25_MLP_GPU0_CUDA_VISIBLE_DEVICES='$gpu0_ids' FAST25_MLP_GPU1_CUDA_VISIBLE_DEVICES='$gpu1_ids' exec bash '$workload_script_path' '$variant'" \
  >"$local_artifact/workload_ssh.log" 2>&1 &
workload_ssh_pid=$!
workload_done=0
for _ in $(seq 1 520); do
  assert_no_external_interference
  if remote "$port0" "test -f '$workload_rc'"; then
    workload_done=1
    break
  fi
  if ! kill -0 "$workload_ssh_pid" 2>/dev/null; then
    wait "$workload_ssh_pid" 2>/dev/null || true
    workload_ssh_pid=
    echo "agent-forwarded workload SSH exited without rc" >&2
    tail -n 120 "$local_artifact/workload_ssh.log" >&2 || true
    exit 1
  fi
  sleep 5
done
if [ "$workload_done" != 1 ]; then
  echo "workload did not finish before 2600s" >&2
  exit 1
fi
workload_transport_status=0
wait "$workload_ssh_pid" || workload_transport_status=$?
workload_ssh_pid=
finalize_cpu_runtime_evidence
assert_no_external_interference
workload_status="$(remote "$port0" "tr -d '[:space:]' < '$workload_rc'")"
printf 'workload_rc=%s transport_rc=%s remote_log=%s\n' "$workload_status" "$workload_transport_status" "$workload_log" \
  > "$local_artifact/workload_launcher.log"
if [ "$workload_status" != 0 ]; then
  remote "$port0" "tail -n 120 '$workload_log'" >&2 || true
  exit 1
fi
assert_gpu_direct_workload_mode
assert_no_fluxon_fatal_events

if [ "$capacity_control_enabled" = 1 ]; then
  run_capacity_control after_workload set-wait "$effective_cpu_active_capacity_bytes" \
    | tee "$local_artifact/capacity_after_workload.json"
fi

if [ "$workload_profile" = fast25_mlp_c24 ]; then
  result_dir="$(remote "$port0" "cat '$exp0/fast25_result_dir_${run_id}.txt'")"
  if [ "$result_dir" != "$fast25_result_root/$fast25_arm/$run_id" ]; then
    echo "unexpected FAST25 result path: $result_dir" >&2
    exit 1
  fi
else
  result_dir="$(remote "$port0" "find /storage/mjq/mooncake_m1/mooncake_perf_workloads/results -maxdepth 1 -type d -name '*fluxon_${run_id}_${workload_suffix}*' -printf '%T@ %p\\n' | sort -n | tail -1 | cut -d' ' -f2-")"
fi
if [ -z "$result_dir" ]; then
  echo "cannot locate workload result for $run_id" >&2
  exit 1
fi
remote "$port0" "test -s '$result_dir/summary.json'"
fast25_ssd_snapshot=
if [ "$workload_profile" = fast25_mlp_c24 ]; then
  fast25_ssd_snapshot="$exp0/fast25_ssd_snapshot_${run_id}.json"
  remote "$port0" "
    /storage/mjq/.venv_sglang_fluxon/bin/python -B \
      '$fast25_deployment_dir/experiment_configs/fast25_multilevel_fluxon_mooncake_20260805/parse_fluxon_ssd_snapshot.py' \
      --arm '$fast25_arm' \
      --log '$root_cpu/log/current_cpu_remote_20260710/owner.log' \
      --output '$fast25_ssd_snapshot'
  "
fi

request_corpus_path="$exp0/request_corpus_${run_id}.json"
request_corpus_sha256=not_collected
if [ "$request_corpus_required" = 1 ]; then
  remote "$port0" "python3 - '$result_dir/requests/router_agent.jsonl' '$request_corpus_path' '$expected_requests' '$expected_sessions' '$expected_turns' '$workload_prefix_namespace' <<'PY'
import hashlib
import json
import os
import re
import sys

source_path, output_path, expected_count, expected_sessions, expected_turns, expected_namespace = sys.argv[1:]
expected_count = int(expected_count)
expected_sessions = int(expected_sessions)
expected_turns = int(expected_turns)
digest_re = re.compile(r'^[a-f0-9]{64}$')
entries = []
seen_ids = set()
seen_coordinates = set()
namespaces = set()
with open(source_path, encoding='utf-8') as source:
    for line_number, line in enumerate(source, 1):
        if not line.strip():
            continue
        record = json.loads(line)
        request_id = record.get('request_id')
        metadata = record.get('metadata') or {}
        payload_sha256 = metadata.get('request_payload_sha256')
        namespace = metadata.get('namespace')
        session_id = metadata.get('session_id')
        turn_id = metadata.get('turn_id')
        if not isinstance(request_id, str) or not request_id:
            raise SystemExit(f'line {line_number}: missing request_id')
        if request_id in seen_ids:
            raise SystemExit(f'line {line_number}: duplicate request_id {request_id}')
        if not isinstance(payload_sha256, str) or not digest_re.fullmatch(payload_sha256):
            raise SystemExit(f'line {line_number}: invalid request_payload_sha256 for {request_id}')
        if not isinstance(namespace, str) or not namespace:
            raise SystemExit(f'line {line_number}: missing namespace for {request_id}')
        if not isinstance(session_id, int) or not isinstance(turn_id, int):
            raise SystemExit(f'line {line_number}: invalid session/turn coordinate for {request_id}')
        if metadata.get('request_kind') != 'agent':
            raise SystemExit(f'line {line_number}: unexpected request_kind for {request_id}')
        coordinate = (session_id, turn_id)
        if coordinate in seen_coordinates:
            raise SystemExit(f'line {line_number}: duplicate session/turn coordinate {coordinate}')
        seen_ids.add(request_id)
        seen_coordinates.add(coordinate)
        namespaces.add(namespace)
        entries.append({
            'request_id': request_id,
            'request_payload_sha256': payload_sha256,
            'session_id': session_id,
            'turn_id': turn_id,
        })
if len(entries) != expected_count:
    raise SystemExit(f'invalid corpus count: actual={len(entries)} expected={expected_count}')
expected_coordinates = {
    (session_id, turn_id)
    for session_id in range(expected_sessions)
    for turn_id in range(expected_turns)
}
if seen_coordinates != expected_coordinates:
    missing = sorted(expected_coordinates - seen_coordinates)[:8]
    extra = sorted(seen_coordinates - expected_coordinates)[:8]
    raise SystemExit(f'invalid session/turn topology: missing={missing} extra={extra}')
if len(namespaces) != 1:
    raise SystemExit(f'corpus has multiple namespaces: {sorted(namespaces)}')
actual_namespace = next(iter(namespaces))
if expected_namespace and actual_namespace != expected_namespace:
    raise SystemExit(f'namespace mismatch: actual={actual_namespace} expected={expected_namespace}')
entries.sort(key=lambda item: (item['session_id'], item['turn_id'], item['request_id']))
canonical_entries = json.dumps(
    entries,
    ensure_ascii=False,
    separators=(',', ':'),
    sort_keys=True,
).encode('utf-8')
corpus_sha256 = hashlib.sha256(canonical_entries).hexdigest()
document = {
    'schema_version': 1,
    'corpus_sha256': corpus_sha256,
    'corpus_sha256_definition': 'sha256(canonical_json(entries_sorted_by_session_turn_request_id))',
    'namespace': actual_namespace,
    'request_count': len(entries),
    'expected_sessions': expected_sessions,
    'expected_turns': expected_turns,
    'entries': entries,
}
temporary_path = output_path + '.tmp'
with open(temporary_path, 'w', encoding='utf-8') as output:
    json.dump(document, output, ensure_ascii=False, indent=2, sort_keys=True)
    output.write('\n')
os.replace(temporary_path, output_path)
print(corpus_sha256)
PY"
  request_corpus_sha256="$(remote "$port0" "python3 - '$request_corpus_path' <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding='utf-8'))['corpus_sha256'])
PY")"
  printf 'request_corpus_sha256=%s expected=%s path=%s\n' \
    "$request_corpus_sha256" "${expected_corpus_sha256:-unset}" "$request_corpus_path" \
    | tee "$local_artifact/request_corpus.log"
  scp "${gpu_ssh_common[@]}" -P "$port0" \
    "root@$host:$request_corpus_path" \
    "$local_artifact/request_corpus_${run_id}.json"
  if [ -n "$expected_corpus_sha256" ] && [ "$request_corpus_sha256" != "$expected_corpus_sha256" ]; then
    echo "request corpus mismatch: actual=$request_corpus_sha256 expected=$expected_corpus_sha256" >&2
    exit 1
  fi
elif [ -n "$expected_corpus_sha256" ]; then
  echo "expected corpus SHA256 was set for a workload profile without corpus capture" >&2
  exit 2
fi

if [ "$workload_profile" = fast25_mlp_c24 ]; then
  remote "$port0" "python3 - '$result_dir/summary.json' '$fast25_arm' '$fast25_ssd_snapshot' '$cpu_external_stack_allowed' '$FAST25_MLP_EXPECTED_REPLAY_PROFILE' '$FAST25_MLP_EXPECTED_REQUESTS' '$FAST25_MLP_EXPECTED_PROMPT_TOKENS' '$FAST25_MLP_EXPECTED_OUTPUT_TOKENS' <<'PY'
import json, sys
p, arm, ssd_path, cpu_external_stack_allowed, profile, requests, prompt_tokens, output_tokens = sys.argv[1:]
d = json.load(open(p, encoding='utf-8'))
ssd = json.load(open(ssd_path, encoding='utf-8'))
expected = {
    'profile': profile,
    'complete': True,
    'requests_expected': int(requests),
    'requests_observed': int(requests),
    'requests_success': int(requests),
    'requests_error': 0,
    'requests_missing_at_runtime_boundary': 0,
    'prompt_tokens_success': int(prompt_tokens),
    'output_tokens_success': int(output_tokens),
}
failed = [key for key, value in expected.items() if d.get(key) != value]
if d.get('task_errors') != []:
    failed.append('task_errors')
if failed:
    raise SystemExit(f'FAST25 summary contract failed: {failed}')
c = d['cache_hits']
print(json.dumps({
    'arm': arm,
    'profile': d['profile'],
    'success': d['requests_success'],
    'errors': d['requests_error'],
    'qps': d['achieved_qps'],
    'wall_s': d['wall_s'],
    'ttft_mean_s': d['ttft_mean_s'],
    'l1_hit_rate': c['l1_share'],
    'l2_hit_rate': c['l2_share'],
    'l3_hit_rate': c['l3_share'],
    'total_hit_rate': c['total_hit_share'],
    'cpu_external_stack_allowed': bool(int(cpu_external_stack_allowed)),
    'ssd': ssd,
}, sort_keys=True))
PY" | tee "$local_artifact/result_line.json"
else
  remote "$port0" "python3 - '$result_dir/summary.json' '$profile' '$workload_profile' '$expected_requests' '$gpu_dram_bytes' '$gpu_payload_bytes' '$cpu_dram_bytes' '$effective_cpu_active_capacity_bytes' '$capacity_control_enabled' '$ssd_enabled' '$effective_ssd_scope' '$ssd_read_source_policy' '$gpu_direct_enabled' '$post_read_remote_policy' '$effective_gpu_ssd_capacity_bytes' '$effective_cpu_ssd_capacity_bytes' '$effective_gpu_ssd_write_rate_bytes_per_sec' '$effective_gpu_ssd_write_burst_bytes' '$effective_gpu_ssd_capacity_writeback_enabled' '$gpu_idle_memory_tolerance_mib' '$cpu_rdma_ready_timeout_seconds' '$gpu_rdma_ready_timeout_seconds' '$gpu_shared_json_timeout_seconds' '$cpu_owner_start_mode' '$tmux_nofile_soft' <<'PY'
import json, sys
p, profile, workload_profile, expected, gpu, payload, cpu, cpu_active, capacity_control, ssd_enabled, ssd_scope, ssd_read_source_policy, gpu_direct_enabled, post_read_remote_policy, gpu_ssd, cpu_ssd, gpu_ssd_write_rate, gpu_ssd_write_burst, gpu_ssd_capacity_writeback, gpu_idle_memory_tolerance_mib, cpu_rdma_ready_timeout_seconds, gpu_rdma_ready_timeout_seconds, gpu_shared_json_timeout_seconds, cpu_owner_start_mode, tmux_nofile = sys.argv[1:]
d = json.load(open(p))
s = d['router_agent']['request_summary']
c = d['router_agent']['cache_summary']
if int(s['success_count']) != int(expected) or int(s['error_count']) != 0:
    raise SystemExit(f\"invalid workload completion: success={s['success_count']} errors={s['error_count']} expected={expected}\")
print(json.dumps({
  'profile': profile,
  'workload_profile': workload_profile,
  'success': s['success_count'],
  'errors': s['error_count'],
  'qps': s['request_qps'],
  'wall_s': s['wall_duration_s'],
  'ttft_mean_s': s['ttft_mean_s'],
  'l1_hit_rate': c['l1_hit_rate'],
  'l3_hit_rate': c['l3_hit_rate'],
  'gpu_dram_bytes_each': int(gpu),
  'gpu_payload_bytes_each': int(payload),
  'cpu_dram_bytes': int(cpu),
  'cpu_active_capacity_bytes': int(cpu_active),
  'capacity_control_enabled': bool(int(capacity_control)),
  'ssd_enabled': bool(int(ssd_enabled)),
  'ssd_scope': ssd_scope,
  'ssd_read_source_policy': ssd_read_source_policy,
  'gpu_direct_enabled': bool(int(gpu_direct_enabled)),
  'post_read_remote_policy': post_read_remote_policy,
  'gpu_ssd_capacity_bytes_each': int(gpu_ssd),
  'cpu_ssd_capacity_bytes': int(cpu_ssd),
  'gpu_ssd_write_rate_bytes_per_sec': int(gpu_ssd_write_rate),
  'gpu_ssd_write_burst_bytes': int(gpu_ssd_write_burst),
  'gpu_ssd_capacity_writeback_enabled': None if gpu_ssd_capacity_writeback == 'disabled' else gpu_ssd_capacity_writeback == 'true',
  'gpu_idle_memory_tolerance_mib': int(gpu_idle_memory_tolerance_mib),
  'cpu_rdma_ready_timeout_seconds': int(cpu_rdma_ready_timeout_seconds),
  'gpu_rdma_ready_timeout_seconds': int(gpu_rdma_ready_timeout_seconds),
  'gpu_shared_json_timeout_seconds': int(gpu_shared_json_timeout_seconds),
  'cpu_owner_start_mode': cpu_owner_start_mode,
  'tmux_nofile_soft': int(tmux_nofile),
}, sort_keys=True))
PY" | tee "$local_artifact/result_line.json"
fi

evidence_stage="/storage/mjq/sglang_fluxon/deploy_staging/e44_capacity_evidence_${run_id}"
evidence_name="$(basename "$evidence_stage")"
evidence_dir="$(dirname "$evidence_stage")"
remote "$port0" "
  set -euo pipefail
  rm -rf '$evidence_stage'
  mkdir -p '$evidence_stage'
  cp -a '$result_dir' '$evidence_stage/workload_result'
  mkdir -p '$evidence_stage/node0' '$evidence_stage/node1' '$evidence_stage/cpu'
  cp -a '$root0/log/current_cpu_remote_20260710/owner.log' '$evidence_stage/node0/'
  cp -a '$root0/log/current_cpu_remote_20260710/master_${run_id}_20260718.log' '$evidence_stage/node0/'
  cp -a '$gpu0_sglang_log' '$evidence_stage/node0/'
  if [ '$sglang_layout' = tp1x2 ]; then
    cp -a '$gpu0_sglang_log_b' '$evidence_stage/node0/'
    cp -a '$exp0/tp1_cross_client_smoke_${run_id}_node0.log' '$evidence_stage/node0/'
  fi
  if [ '$workload_profile' = fast25_mlp_c24 ]; then
    cp -a '$root0/log/current_cpu_remote_20260710/router_${run_id}_20260718.log' '$evidence_stage/node0/'
    cp -a '$exp0/fast25_capacity_${run_id}.json' '$evidence_stage/'
    cp -a '$fast25_ssd_snapshot' '$evidence_stage/'
  else
    cp -a '$root0/log/current_cpu_remote_20260710/router_${run_id}_stable_session.log' '$evidence_stage/node0/'
  fi
  cp -a '$root1/log/current_cpu_remote_20260710/owner.log' '$evidence_stage/node1/'
  cp -a '$gpu1_sglang_log' '$evidence_stage/node1/'
  if [ '$sglang_layout' = tp1x2 ]; then
    cp -a '$gpu1_sglang_log_b' '$evidence_stage/node1/'
    cp -a '$exp1/tp1_cross_client_smoke_${run_id}_node1.log' '$evidence_stage/node1/'
  fi
  cp -a '$root_cpu/log/current_cpu_remote_20260710/owner.log' '$evidence_stage/cpu/'
  cp -a '$root0/$exp_rel/netobs_results/${run_id}_node0.jsonl' '$evidence_stage/node0/'
  cp -a '$root1/$exp_rel/netobs_results/${run_id}_node1.jsonl' '$evidence_stage/node1/'
  cp -a '$root_cpu/$exp_rel/netobs_results/${run_id}_cpu.jsonl' '$evidence_stage/cpu/'
  cp -a '$cpu_guard_evidence_heartbeat' '$evidence_stage/cpu/'
  cp -a '$cpu_guard_evidence_log' '$evidence_stage/cpu/'
  test ! -e '$cpu_guard_evidence_violation'
  cp -a '$root0/runtime_current_cpu_remote_20260710/config' '$evidence_stage/node0/runtime_config'
  cp -a '$root1/runtime_current_cpu_remote_20260710/config' '$evidence_stage/node1/runtime_config'
  cp -a '$root_cpu/runtime_current_cpu_remote_20260710/config' '$evidence_stage/cpu/runtime_config'
  cp -a '$root0/services/master_work_${run_id}_20260718/master_config.runtime.yaml' '$evidence_stage/node0/runtime_config/master_config.runtime.yaml'
  if [ '$capacity_control_enabled' = 1 ]; then
    cp -a '$exp0/capacity_control_${run_id}_before_workload.json' '$evidence_stage/'
    cp -a '$exp0/capacity_control_${run_id}_after_workload.json' '$evidence_stage/'
    cp -a '$exp0/capacity_control_${run_id}_before_workload.log' '$evidence_stage/'
    cp -a '$exp0/capacity_control_${run_id}_after_workload.log' '$evidence_stage/'
  fi
  if [ '$request_corpus_required' = 1 ]; then
    cp -a '$request_corpus_path' '$evidence_stage/'
  fi
  if [ -n '$assistant_history_replay_file' ]; then
    cp -a '$assistant_history_replay_file' '$evidence_stage/assistant_history_replay.json'
  fi
  printf '%s\\n' 'profile=$profile' 'workload_profile=$workload_profile' 'fast25_arm=${fast25_arm:-unset}' 'fast25_deployment_dir=${fast25_deployment_dir:-unset}' 'expected_requests=$expected_requests' 'workload_prefix_namespace=$workload_prefix_namespace' 'assistant_history_replay_file=${assistant_history_replay_file:-unset}' 'assistant_history_replay_sha256=${assistant_history_replay_sha256:-unset}' 'request_corpus_required=$request_corpus_required' 'request_corpus_sha256=$request_corpus_sha256' 'expected_corpus_sha256=${expected_corpus_sha256:-unset}' 'single_gpu_host=$single_gpu_host' 'node0_ssh_port=$port0' 'node1_ssh_port=$port1' 'node0_hostname=$node0_public_name' 'node1_hostname=$node1_public_name' 'node0_private_ip=$node0_ip' 'node1_private_ip=$node1_ip' 'sglang_layout=$sglang_layout' 'owner_local_reserve_value_len_requested=$owner_local_reserve_value_len' 'gpu0_owner_local_reserve_value_len_actual=$gpu0_owner_local_reserve_value_len_actual' 'gpu1_owner_local_reserve_value_len_actual=$gpu1_owner_local_reserve_value_len_actual' 'gpu0_ids=$gpu0_ids' 'gpu1_ids=$gpu1_ids' 'gpu0_rdma_devices=$gpu0_rdma_devices' 'gpu1_rdma_devices=$gpu1_rdma_devices' 'gpu0_sglang_port=$gpu0_sglang_port' 'gpu0_sglang_port_b=$gpu0_sglang_port_b' 'gpu1_sglang_port=$gpu1_sglang_port' 'gpu1_sglang_port_b=$gpu1_sglang_port_b' 'cpu_private_ip=$cpu_ip' 'cpu_ssh_port=$port_cpu' 'cpu_control_ssh_path=$cpu_control_ssh_path' 'cpu_venv=$effective_cpu_venv' 'cpu_external_stack_allowed=$cpu_external_stack_allowed' 'gpu_dram_bytes_each=$gpu_dram_bytes' 'gpu_payload_bytes_each=$gpu_payload_bytes' 'cpu_dram_bytes=$cpu_dram_bytes' 'cpu_active_capacity_bytes=$effective_cpu_active_capacity_bytes' 'capacity_control_enabled=$capacity_control_enabled' 'ssd_enabled=$ssd_enabled' 'ssd_scope=$effective_ssd_scope' 'ssd_read_source_policy=$ssd_read_source_policy' 'gpu_ssd_capacity_bytes_each=$effective_gpu_ssd_capacity_bytes' 'cpu_ssd_capacity_bytes=$effective_cpu_ssd_capacity_bytes' 'gpu_ssd_write_rate_bytes_per_sec=$effective_gpu_ssd_write_rate_bytes_per_sec' 'gpu_ssd_write_burst_bytes=$effective_gpu_ssd_write_burst_bytes' 'gpu_ssd_capacity_writeback_enabled=$effective_gpu_ssd_capacity_writeback_enabled' 'gpu_idle_memory_tolerance_mib=$gpu_idle_memory_tolerance_mib' 'cpu_rdma_ready_timeout_seconds=$cpu_rdma_ready_timeout_seconds' 'gpu_rdma_ready_timeout_seconds=$gpu_rdma_ready_timeout_seconds' 'gpu_shared_json_timeout_seconds=$gpu_shared_json_timeout_seconds' 'cpu_owner_start_mode=$cpu_owner_start_mode' 'tmux_nofile_soft=$tmux_nofile_soft' > '$evidence_stage/capacity.env'
  printf '%s\\n' 'gpu_direct_enabled=$gpu_direct_enabled' >> '$evidence_stage/capacity.env'
  printf '%s\\n' 'post_read_remote_policy=$post_read_remote_policy' >> '$evidence_stage/capacity.env'
  tar -czf '${evidence_stage}.tar.gz' -C '$evidence_stage' .
  cd '$evidence_dir'
  sha256sum '${evidence_name}.tar.gz' > '${evidence_name}.tar.gz.sha256'
"

scp "${gpu_ssh_common[@]}" -P "$port0" \
  "root@$host:${evidence_stage}.tar.gz" \
  "root@$host:${evidence_stage}.tar.gz.sha256" \
  "$local_artifact/"
(
  cd "$local_artifact"
  sha256sum -c "${evidence_name}.tar.gz.sha256"
)
remote "$port0" "rm -rf '$evidence_stage' '${evidence_stage}.tar.gz' '${evidence_stage}.tar.gz.sha256'"

tar -xzf "$local_artifact/${evidence_name}.tar.gz" -C "$local_artifact"
sha256sum "$local_artifact/${evidence_name}.tar.gz" > "$local_artifact/evidence_local.sha256"
echo "capacity profile complete: profile=$profile workload_profile=$workload_profile run_id=$run_id artifact=$local_artifact"
