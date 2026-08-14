#!/usr/bin/env bash
set -uo pipefail

variant="${1:?missing E44 performance variant}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
runtime_script_dir="${FAST25_MLP_E44_RUNTIME_SCRIPT_DIR:-$script_dir}"
source "$runtime_script_dir/e44_v5_perf_variant_20260718.sh" "$variant"

deployment="${FAST25_MLP_DEPLOYMENT_DIR:?missing FAST25_MLP_DEPLOYMENT_DIR}"
profile_helper="$deployment/experiment_configs/fast25_multilevel_fluxon_mooncake_20260805/fast25_mlp_workload_profile.sh"
source "$profile_helper"
resolve_fast25_mlp_workload_profile "${FAST25_MLP_WORKLOAD_PROFILE:-s96_wss296}"
arm="${FAST25_MLP_ARM:?missing FAST25_MLP_ARM}"
result_root="${FAST25_MLP_RESULT_ROOT:-/storage/mjq/mooncake_m1/results/fast25_multilevel_fluxon_mooncake_20260805}"
run_id="$E44_PERF_RUN_ID"
node0_ip="${FLUXON_NODE0_IP:?missing FLUXON_NODE0_IP}"
node1_ip="${FLUXON_NODE1_IP:?missing FLUXON_NODE1_IP}"
cpu_ip="${FLUXON_CPU_NODE_IP:?missing FLUXON_CPU_NODE_IP}"
gpu0_sglang_port="${FAST25_MLP_GPU0_SGLANG_PORT:-31001}"
gpu1_sglang_port="${FAST25_MLP_GPU1_SGLANG_PORT:-31001}"
gpu0_sglang_port_b="${FAST25_MLP_GPU0_SGLANG_PORT_B:-31002}"
gpu1_sglang_port_b="${FAST25_MLP_GPU1_SGLANG_PORT_B:-31002}"
sglang_layout="${FAST25_MLP_SGLANG_LAYOUT:-tp2}"
gpu0_http_host="${FAST25_MLP_GPU0_HTTP_HOST:-$node0_ip}"
gpu1_http_host="${FAST25_MLP_GPU1_HTTP_HOST:-$node1_ip}"
router_http_host="${FAST25_MLP_ROUTER_HTTP_HOST:-$node0_ip}"
gpu0_ids="${FAST25_MLP_GPU0_CUDA_VISIBLE_DEVICES:-0,1}"
gpu1_ids="${FAST25_MLP_GPU1_CUDA_VISIBLE_DEVICES:-0,1}"
python=/storage/mjq/.venv_sglang_fluxon/bin/python
root0=/storage/mjq/sglang_fluxon/fluxon_f1
root1=/storage/mjq/sglang_fluxon/fluxon_f2
root_cpu=/storage/mjq/sglang_fluxon/fluxon_cpu
tag="fluxon_${run_id}_${FAST25_MLP_WORKLOAD_SUFFIX}"
runtime_dir="${FAST25_MLP_RUNTIME_DIR:-$script_dir}"
log="$runtime_dir/workload_${tag}.log"
rc_file="$runtime_dir/workload_${tag}.rc"
result_dir="$result_root/$arm/$run_id"
result_path_file="$runtime_dir/fast25_result_dir_${run_id}.txt"
capacity="$runtime_dir/fast25_capacity_${run_id}.json"
gpu0_owner_log="$root0/log/current_cpu_remote_20260710/owner.log"
gpu1_owner_log="$root1/log/current_cpu_remote_20260710/owner.log"
cpu_owner_log="$root_cpu/log/current_cpu_remote_20260710/owner.log"
master_log="$root0/log/current_cpu_remote_20260710/master_${run_id}_20260718.log"
gpu0_sglang_log="$root0/log/current_cpu_remote_20260710/sglang_tp2_gpus${gpu0_ids//,/_}_port${gpu0_sglang_port}_${run_id}_20260719.log"
gpu1_sglang_log="$root1/log/current_cpu_remote_20260710/sglang_tp2_gpus${gpu1_ids//,/_}_port${gpu1_sglang_port}_${run_id}_20260719.log"
gpu0_sglang_log_b=
gpu1_sglang_log_b=
case "$sglang_layout" in
  tp2) ;;
  tp1x2)
    if [ "$gpu0_sglang_port" = "$gpu0_sglang_port_b" ] || \
       [ "$gpu1_sglang_port" = "$gpu1_sglang_port_b" ]; then
      echo "tp1x2 workload requires two distinct SGLang ports on each node" >&2
      exit 2
    fi
    gpu0_sglang_log="$root0/log/current_cpu_remote_20260710/sglang_tp1_gpu${gpu0_ids%%,*}_port${gpu0_sglang_port}_${run_id}_20260719.log"
    gpu0_sglang_log_b="$root0/log/current_cpu_remote_20260710/sglang_tp1_gpu${gpu0_ids#*,}_port${gpu0_sglang_port_b}_${run_id}_20260719.log"
    gpu1_sglang_log="$root1/log/current_cpu_remote_20260710/sglang_tp1_gpu${gpu1_ids%%,*}_port${gpu1_sglang_port}_${run_id}_20260719.log"
    gpu1_sglang_log_b="$root1/log/current_cpu_remote_20260710/sglang_tp1_gpu${gpu1_ids#*,}_port${gpu1_sglang_port_b}_${run_id}_20260719.log"
    ;;
  *) echo "FAST25_MLP_SGLANG_LAYOUT must be tp2 or tp1x2" >&2; exit 2 ;;
esac
sglang_log_specs=(
  "gpu0a=$gpu0_sglang_log"
  "gpu1a=$gpu1_sglang_log"
)
worker_metrics_args=(
  --worker-metrics-url "http://$gpu0_http_host:$gpu0_sglang_port/metrics"
  --worker-metrics-url "http://$gpu1_http_host:$gpu1_sglang_port/metrics"
)
if [ "$sglang_layout" = tp1x2 ]; then
  sglang_log_specs+=(
    "gpu0b=$gpu0_sglang_log_b"
    "gpu1b=$gpu1_sglang_log_b"
  )
  worker_metrics_args+=(
    --worker-metrics-url "http://$gpu0_http_host:$gpu0_sglang_port_b/metrics"
    --worker-metrics-url "http://$gpu1_http_host:$gpu1_sglang_port_b/metrics"
  )
fi

case "$deployment" in
  /storage/mjq/mooncake_m1/deployments/fast25_mlp_*) ;;
  *) echo "invalid FAST25_MLP_DEPLOYMENT_DIR: $deployment" >&2; exit 2 ;;
esac
case "$result_root" in
  /storage/mjq/mooncake_m1/results/fast25_multilevel_fluxon_mooncake_20260805) ;;
  *) echo "invalid FAST25_MLP_RESULT_ROOT: $result_root" >&2; exit 2 ;;
esac
case "$arm" in F0|F1) ;; *) echo "FAST25_MLP_ARM must be F0 or F1" >&2; exit 2 ;; esac
test -x "$python"
replayer="$deployment/experiment_configs/fast25_multilevel_fluxon_mooncake_20260805/$FAST25_MLP_REPLAYER_BASENAME"
test -f "$replayer"
test -f "$deployment/DEPLOYMENT.sha256"
(
  cd "$deployment"
  sha256sum -c DEPLOYMENT.sha256 >/dev/null
)
for path in "$gpu0_owner_log" "$gpu1_owner_log" "$cpu_owner_log" "$master_log"; do
  test -s "$path"
done
for spec in "${sglang_log_specs[@]}"; do
  test -s "${spec#*=}"
done
test ! -e "$result_dir"
test ! -e "$capacity"
test ! -e "$result_path_file"

for _ in $(seq 1 90); do
  if grep -F 'owner=' "$master_log" | grep -F 'remote_cache' | \
     grep -F 'base_capacity_bytes=261134011596' >/dev/null; then
    break
  fi
  sleep 1
done
grep -F 'payload_capacity_bytes=123695058124' "$gpu0_owner_log" >/dev/null
grep -F 'payload_capacity_bytes=123695058124' "$gpu1_owner_log" >/dev/null
grep -F 'owner=' "$master_log" | grep -F 'remote_cache' | \
  grep -F 'base_capacity_bytes=261134011596' >/dev/null

finalize_args=(
  --arm "$arm"
  --run-id "$run_id"
  --output "$capacity"
  --gpu-owner-log "$gpu0_owner_log"
  --gpu-owner-log "$gpu1_owner_log"
  --master-log "$master_log"
  --evidence-file "gpu0_owner_log=$gpu0_owner_log"
  --evidence-file "gpu1_owner_log=$gpu1_owner_log"
  --evidence-file "cpu_owner_log=$cpu_owner_log"
  --evidence-file "master_log=$master_log"
)
for spec in "${sglang_log_specs[@]}"; do
  finalize_args+=(--evidence-file "${spec%%=*}_sglang_log=${spec#*=}")
done
if [[ "$arm" == F1 ]]; then
  finalize_args+=(--cpu-ssd-path "/tmp/fluxon_kv_ssd/$run_id")
fi
"$python" -B \
  "$deployment/experiment_configs/fast25_multilevel_fluxon_mooncake_20260805/finalize_capacity_manifest.py" \
  "${finalize_args[@]}"

unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
export no_proxy="127.0.0.1,localhost,$node0_ip,$node1_ip,$cpu_ip,$gpu0_http_host,$gpu1_http_host,$router_http_host,10.0.0.0/8,10.233.0.0/16"
export NO_PROXY="$no_proxy" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
install -d -m 0755 "$result_root/$arm"
: > "$log"
rm -f "$rc_file"
printf '%s\n' "$result_dir" > "$result_path_file"

invalid_args=()
if [[ -n "${FAST25_MLP_INVALID_MARKER:-}" ]]; then
  invalid_args=(--invalid-marker "$FAST25_MLP_INVALID_MARKER")
fi
set +e
"$python" -B \
  "$replayer" \
  --trace "$deployment/traces/total_traces_part2.txt" \
  --base-replayer "$deployment/experiment_configs/mooncake_trace_local_dram_tp2x2_20260728/mooncake_trace_replay.py" \
  --prefix-asset "$deployment/experiment_configs/fast25_multilevel_prefix_20260805/assets/multilevel_prefix_v1/token_nodes.jsonl" \
  --expected-prefix-sha256 3031eae349ade106115973bda751fca0c1b240b81d4c98937f26665993789f45 \
  replay \
  --base-url "http://$router_http_host:32000" \
  "${worker_metrics_args[@]}" \
  --expected-model /storage/fanyk1/models/Qwen3-VL-8B-Instruct \
  --capacity-manifest "$capacity" \
  --capacity-group "$arm" \
  --run-id "$run_id" \
  --output-dir "$result_dir" \
  --request-timeout-s 300 \
  --max-runtime-s 600 \
  "${invalid_args[@]}" \
  >> "$log" 2>&1
rc=$?
set -e
printf '%s\n' "$rc" > "$rc_file"
exit "$rc"
