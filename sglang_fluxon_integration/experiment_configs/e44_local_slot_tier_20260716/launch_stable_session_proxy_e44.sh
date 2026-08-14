#!/usr/bin/env bash
set -euo pipefail

root="${1:-/storage/mjq/sglang_fluxon/fluxon_f1}"
run_id="${2:?missing run id}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
session="zth_router_${run_id}"
log="$root/log/current_cpu_remote_20260710/router_${run_id}_stable_session.log"
python="${E44_ROUTER_PYTHON:-/storage/zth/sglang_l13_fluxon_v2/venv-zth/bin/python}"
node0_ip="${FLUXON_NODE0_IP:-10.233.114.139}"
node1_ip="${FLUXON_NODE1_IP:-10.233.114.138}"
node0_host="${E44_ROUTER_NODE0_HOST:-$node0_ip}"
node1_host="${E44_ROUTER_NODE1_HOST:-$node1_ip}"
node0_port="${E44_ROUTER_NODE0_PORT:-31001}"
node1_port="${E44_ROUTER_NODE1_PORT:-31001}"
node0_port_b="${E44_ROUTER_NODE0_PORT_B:-31002}"
node1_port_b="${E44_ROUTER_NODE1_PORT_B:-31002}"
layout="${E44_ROUTER_SGLANG_LAYOUT:-tp2}"

if [[ ! "$run_id" =~ ^[a-zA-Z0-9_]+$ ]]; then
  echo "invalid run id: $run_id" >&2
  exit 2
fi
for value in "$node0_port" "$node1_port" "$node0_port_b" "$node1_port_b"; do
  if [[ ! "$value" =~ ^[1-9][0-9]*$ ]] || [ "$value" -gt 65535 ]; then
    echo "invalid SGLang port: $value" >&2
    exit 2
  fi
done
case "$layout" in tp2|tp1x2) ;; *) echo "invalid SGLang layout: $layout" >&2; exit 2 ;; esac
test -x "$python"

workers=("http://${node0_host}:${node0_port}" "http://${node1_host}:${node1_port}")
if [ "$layout" = tp1x2 ]; then
  workers=(
    "http://${node0_host}:${node0_port}"
    "http://${node0_host}:${node0_port_b}"
    "http://${node1_host}:${node1_port}"
    "http://${node1_host}:${node1_port_b}"
  )
fi

: > "$log"
tmux new-session -d -s "$session" -n router \
  "unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY; export CUDA_VISIBLE_DEVICES=; exec '$python' '$script_dir/stable_session_proxy_e44.py' --host 0.0.0.0 --port 32000 --workers ${workers[*]} >> '$log' 2>&1"

for _ in $(seq 1 120); do
  code="$(curl -sS --max-time 2 -o /dev/null -w '%{http_code}' http://127.0.0.1:32000/health 2>/dev/null || true)"
  [ "$code" = 200 ] && exit 0
  sleep 1
done
exit 1
