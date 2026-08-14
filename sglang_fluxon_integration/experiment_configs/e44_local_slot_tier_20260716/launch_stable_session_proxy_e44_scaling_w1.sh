#!/usr/bin/env bash
set -euo pipefail

root="${1:-/storage/mjq/sglang_fluxon/fluxon_f1}"
run_id="${2:?missing run id}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
session="zth_router_${run_id}"
log="$root/log/current_cpu_remote_20260710/router_${run_id}_stable_session.log"
python=/storage/zth/sglang_l13_fluxon_v2/venv-zth/bin/python
node0_ip="${FLUXON_NODE0_IP:-10.233.114.139}"
worker="http://${node0_ip}:31001"

if [[ ! "$run_id" =~ ^[a-zA-Z0-9_]+$ ]]; then
  echo "invalid run id: $run_id" >&2
  exit 2
fi

# Keep the two virtual parity lanes so the existing deterministic proxy and
# health schema remain unchanged, but point both lanes at node0.  This creates
# one active TP2 serving worker while node1 remains an idle metrics control.
: > "$log"
tmux new-session -d -s "$session" -n router \
  "unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY; export CUDA_VISIBLE_DEVICES=; exec '$python' '$script_dir/stable_session_proxy_e44.py' --host 0.0.0.0 --port 32000 --workers '$worker' '$worker' >> '$log' 2>&1"

for _ in $(seq 1 120); do
  code="$(curl -sS --max-time 2 -o /dev/null -w '%{http_code}' http://127.0.0.1:32000/health 2>/dev/null || true)"
  [ "$code" = 200 ] && exit 0
  sleep 1
done
exit 1
