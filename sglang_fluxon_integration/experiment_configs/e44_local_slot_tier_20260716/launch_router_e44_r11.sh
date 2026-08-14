#!/usr/bin/env bash
set -euo pipefail

root="${1:-/storage/mjq/sglang_fluxon/fluxon_f1}"
session=zth_router_e44_r11
log="$root/log/current_cpu_remote_20260710/router_e44_r11_20260717.log"
python=/storage/mjq/.venv_sglang_fluxon/bin/python
: > "$log"
tmux new-session -d -s "$session" -n router "unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY; export CUDA_VISIBLE_DEVICES=; export no_proxy=127.0.0.1,localhost,10.233.114.129,10.233.111.134,10.0.0.0/8,10.233.0.0/16; exec '$python' -m sglang_router.launch_router --host 0.0.0.0 --port 32000 --prometheus-host 0.0.0.0 --prometheus-port 29100 --worker-urls http://10.233.114.129:31001 http://10.233.111.134:31001 --model-path /storage/fanyk1/models/Qwen3-VL-8B-Instruct --tokenizer-path /storage/fanyk1/models/Qwen3-VL-8B-Instruct --policy cache_aware --log-level info >> '$log' 2>&1"
for _ in $(seq 1 60); do
  code="$(curl -sS --max-time 2 -o /dev/null -w '%{http_code}' http://127.0.0.1:32000/health 2>/dev/null || true)"
  [ "$code" = 200 ] && exit 0
  sleep 1
done
exit 1
