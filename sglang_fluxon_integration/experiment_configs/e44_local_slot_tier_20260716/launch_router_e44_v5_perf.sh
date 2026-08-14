#!/usr/bin/env bash
set -euo pipefail

root="${1:-/storage/mjq/sglang_fluxon/fluxon_f1}"
variant="${2:?missing E44 performance variant}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$script_dir/e44_v5_perf_variant_20260718.sh" "$variant"

session="zth_router_${E44_PERF_RUN_ID}"
log="$root/log/current_cpu_remote_20260710/router_${E44_PERF_RUN_ID}_20260718.log"
python=/storage/mjq/.venv_sglang_fluxon/bin/python
node0_ip="${FLUXON_NODE0_IP:-10.233.114.139}"
node1_ip="${FLUXON_NODE1_IP:-10.233.114.138}"
node0_host="${E44_ROUTER_NODE0_HOST:-$node0_ip}"
node1_host="${E44_ROUTER_NODE1_HOST:-$node1_ip}"
node0_port="${E44_ROUTER_NODE0_PORT:-31001}"
node1_port="${E44_ROUTER_NODE1_PORT:-31001}"
node0_port_b="${E44_ROUTER_NODE0_PORT_B:-31002}"
node1_port_b="${E44_ROUTER_NODE1_PORT_B:-31002}"
sglang_layout="${E44_ROUTER_SGLANG_LAYOUT:-tp2}"

case "$sglang_layout" in
  tp2) ;;
  tp1x2)
    if [ "$node0_port" = "$node0_port_b" ] || [ "$node1_port" = "$node1_port_b" ]; then
      echo "tp1x2 router requires two distinct ports on each GPU node" >&2
      exit 2
    fi
    ;;
  *) echo "E44_ROUTER_SGLANG_LAYOUT must be tp2 or tp1x2" >&2; exit 2 ;;
esac

worker_urls=(
  "http://$node0_host:$node0_port"
  "http://$node1_host:$node1_port"
)
if [ "$sglang_layout" = tp1x2 ]; then
  worker_urls+=(
    "http://$node0_host:$node0_port_b"
    "http://$node1_host:$node1_port_b"
  )
fi

: > "$log"
router_command=(
  env
  -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY
  "CUDA_VISIBLE_DEVICES="
  "no_proxy=127.0.0.1,localhost,$node0_ip,$node1_ip,$node0_host,$node1_host,10.0.0.0/8,10.233.0.0/16"
  "$python" -m sglang_router.launch_router
  --host 0.0.0.0
  --port 32000
  --prometheus-host 0.0.0.0
  --prometheus-port 29100
  --worker-urls "${worker_urls[@]}"
  --model-path /storage/fanyk1/models/Qwen3-VL-8B-Instruct
  --tokenizer-path /storage/fanyk1/models/Qwen3-VL-8B-Instruct
  --policy cache_aware
  --log-level info
)
tmux new-session -d -s "$session" -n router \
  "$(printf '%q ' "${router_command[@]}") >> $(printf '%q' "$log") 2>&1"
for _ in $(seq 1 120); do
  code="$(curl -sS --max-time 2 -o /dev/null -w '%{http_code}' http://127.0.0.1:32000/health 2>/dev/null || true)"
  [ "$code" = 200 ] && exit 0
  sleep 1
done
exit 1
