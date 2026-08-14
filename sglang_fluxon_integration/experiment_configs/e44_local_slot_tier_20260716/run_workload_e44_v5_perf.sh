#!/usr/bin/env bash
set -uo pipefail

variant="${1:?missing E44 performance variant}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$script_dir/e44_v5_perf_variant_20260718.sh" "$variant"

workdir=/storage/mjq/mooncake_m1/mooncake_perf_workloads
python=/storage/zth/sglang_l13_fluxon_v2/venv-zth/bin/python
tag="fluxon_${E44_PERF_RUN_ID}_s96_t24_sys8192_out8_c24_session_stream_20260718"
namespace="agent_hit50_long_s96_t24_sys8192_v2_${E44_PERF_RUN_ID}"
log="$script_dir/workload_${tag}.log"
rc_file="$script_dir/workload_${tag}.rc"
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
export no_proxy=127.0.0.1,localhost,10.233.114.129,10.233.111.134,10.233.125.121,10.0.0.0/8,10.233.0.0/16
export NO_PROXY="$no_proxy" PYTHONUNBUFFERED=1
: > "$log"
rm -f "$rc_file"
set +e
(
  cd "$workdir"
  "$python" workload_agent_multiturn_long_context.py --cluster-state "$script_dir/cluster_e44_r11.env" \
    --node0-base-url http://10.233.114.129:31001 --node1-base-url http://10.233.111.134:31001 \
    --node0-net-iface eth0 --node1-net-iface eth0 \
    --node1-ssh "-p 2222 -i /root/.ssh/id_ed25519_node1_internal -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=5 root@10.233.111.134" \
    --run-tag "$tag" --output-root "$workdir/results" --prefix-namespace "$namespace" --request-timeout-s 300 --max-runtime-s 2400 \
    --phase-mode router --router-base-url http://10.233.114.129:32000 --base-node node0 --measure-node node1 --seed-node node0 \
    --sessions 96 --turns 24 --agent-groups 96 --system-tokens 8192 --user-tokens 32 --tool-result-tokens 64 --assistant-history-tokens 32 \
    --output-len 8 --concurrency 24 --schedule session_stream --active-sessions 96 --think-time-s 0 --think-time-jitter-s 0 \
    --turn-filler-ratio 0.0 --assistant-history-mode actual --wait-storage-settle
) >> "$log" 2>&1
rc=$?
set -e
printf '%s\n' "$rc" > "$rc_file"
exit "$rc"

