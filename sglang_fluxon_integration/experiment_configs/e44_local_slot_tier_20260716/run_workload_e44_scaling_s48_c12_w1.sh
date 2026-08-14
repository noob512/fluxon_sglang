#!/usr/bin/env bash
set -uo pipefail

variant="${1:?missing E44 performance variant}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$script_dir/e44_v5_perf_variant_20260718.sh" "$variant"

workdir=/storage/mjq/mooncake_m1/mooncake_perf_workloads
python=/storage/zth/sglang_l13_fluxon_v2/venv-zth/bin/python
tag="fluxon_${E44_PERF_RUN_ID}_s48_t24_sys8192_out8_c12_session_stream_w1_20260724"
namespace="agent_hit50_long_s48_t24_sys8192_w1_${E44_PERF_RUN_ID}"
log="$script_dir/workload_${tag}.log"
rc_file="$script_dir/workload_${tag}.rc"
node0_ip="${FLUXON_NODE0_IP:-10.233.114.139}"
node1_ip="${FLUXON_NODE1_IP:-10.233.114.138}"
cpu_ip="${FLUXON_CPU_NODE_IP:-10.233.91.204}"
node1_ssh="${E44_WORKLOAD_NODE1_SSH:--p 2222 -i /root/.ssh/id_ed25519_node1_internal -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=5 root@${node1_ip}}"
runtime_cluster_state="/run/cluster_e44_${E44_PERF_RUN_ID}.env"
sed \
  -e "s/10\\.233\\.114\\.139/${node0_ip}/g" \
  -e "s/10\\.233\\.114\\.138/${node1_ip}/g" \
  -e "s/10\\.233\\.91\\.204/${cpu_ip}/g" \
  "$script_dir/cluster_e44_r11.env" > "$runtime_cluster_state"
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
export no_proxy="127.0.0.1,localhost,${node0_ip},${node1_ip},${cpu_ip},10.0.0.0/8,10.233.0.0/16"
export NO_PROXY="$no_proxy" PYTHONUNBUFFERED=1
: > "$log"
rm -f "$rc_file"
set +e
(
  cd "$workdir"
  "$python" workload_agent_multiturn_long_context.py --cluster-state "$runtime_cluster_state" \
    --node0-base-url "http://${node0_ip}:31001" --node1-base-url "http://${node1_ip}:31001" \
    --node0-net-iface eth0 --node1-net-iface eth0 \
    --node1-ssh "$node1_ssh" \
    --run-tag "$tag" --output-root "$workdir/results" --prefix-namespace "$namespace" --request-timeout-s 300 --max-runtime-s 2400 \
    --phase-mode router --router-base-url "http://${node0_ip}:32000" --base-node node0 --measure-node node1 --seed-node node0 \
    --sessions 48 --turns 24 --agent-groups 48 --system-tokens 8192 --user-tokens 32 --tool-result-tokens 64 --assistant-history-tokens 32 \
    --output-len 8 --concurrency 12 --schedule session_stream --active-sessions 48 --think-time-s 0 --think-time-jitter-s 0 \
    --turn-filler-ratio 0.0 --assistant-history-mode actual --wait-storage-settle --greptime-no-create-tables
) >> "$log" 2>&1
rc=$?
set -e
printf '%s\n' "$rc" > "$rc_file"
exit "$rc"
