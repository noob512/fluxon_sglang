#!/usr/bin/env bash
set -euo pipefail

action="${1:-status}"
run_id="${FLUXON_F_RUN_ID:?missing FLUXON_F_RUN_ID}"
deployment_dir="${FLUXON_F_DEPLOYMENT_DIR:?missing FLUXON_F_DEPLOYMENT_DIR}"
runtime_root="${FLUXON_F_RUNTIME_ROOT:-/tmp/fluxon_mooncake_f_${run_id}}"
gpu_ip="${FLUXON_F_GPU_IP:-10.233.90.51}"
expected_hostname="${FLUXON_F_GPU_HOSTNAME:-lgsl-a4-5f02-m9-3-h100gpu145}"
venv="${FLUXON_F_BASE_VENV:-/public/mjq/.venv_sglang_fluxon}"
model="${FLUXON_F_MODEL_PATH:-/public/mjq/models/Qwen3-VL-8B-Instruct}"
python_overlay="${FLUXON_F_PYTHON_OVERLAY:-$deployment_dir/python_overlay}"
session="fluxon_f_${run_id}_router"
log="$runtime_root/logs/router.log"

case "$run_id" in
  *[!A-Za-z0-9_]*) echo "invalid FLUXON_F_RUN_ID" >&2; exit 2 ;;
esac
case "$runtime_root" in
  /tmp/fluxon_mooncake_f_*) ;;
  *) echo "invalid FLUXON_F_RUNTIME_ROOT" >&2; exit 2 ;;
esac

start() {
  test "$(hostname)" = "$expected_hostname"
  tr ' ' '\n' <<<"$(hostname -I)" | grep -Fx "$gpu_ip" >/dev/null
  test -x "$venv/bin/python"
  test -f "$python_overlay/distro/__init__.py"
  test -f "$model/config.json"
  for port in 31001 31002; do
    test "$(curl -sS --max-time 5 -o /dev/null -w '%{http_code}' "http://127.0.0.1:${port}/health")" = 200
  done
  if tmux has-session -t "$session" 2>/dev/null; then
    echo "router session already exists: $session" >&2
    exit 1
  fi
  if ss -ltn | grep -Eq ':(32000|29100) '; then
    echo "router port already in use" >&2
    exit 1
  fi
  install -d -m 0755 "$(dirname "$log")"
  : > "$log"
  tmux new-session -d -s "$session" -n router \
    "unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY; export CUDA_VISIBLE_DEVICES= PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH='$python_overlay' no_proxy='127.0.0.1,localhost,$gpu_ip,10.0.0.0/8,10.233.0.0/16' NO_PROXY='127.0.0.1,localhost,$gpu_ip,10.0.0.0/8,10.233.0.0/16'; exec '$venv/bin/python' -B -m sglang_router.launch_router --host 0.0.0.0 --port 32000 --prometheus-host 0.0.0.0 --prometheus-port 29100 --worker-urls http://127.0.0.1:31001 http://127.0.0.1:31002 --model-path '$model' --tokenizer-path '$model' --policy cache_aware --log-level info >> '$log' 2>&1"
  local deadline=$(( $(date +%s) + 180 ))
  until [[ "$(curl -sS --max-time 5 -o /dev/null -w '%{http_code}' http://127.0.0.1:32000/health 2>/dev/null || true)" = 200 ]]; do
    if (( $(date +%s) >= deadline )); then
      tail -120 "$log" >&2 || true
      exit 1
    fi
    sleep 2
  done
  local models_path="$runtime_root/evidence/router.models.before.json"
  local models_tmp="${models_path}.tmp.$$"
  until curl -fsS --max-time 10 http://127.0.0.1:32000/v1/models -o "$models_tmp" 2>/dev/null; do
    if (( $(date +%s) >= deadline )); then
      rm -f "$models_tmp"
      tail -120 "$log" >&2 || true
      exit 1
    fi
    sleep 1
  done
  mv "$models_tmp" "$models_path"
  echo "started Fluxon F cache-aware router"
}

stop() {
  tmux kill-session -t "$session" 2>/dev/null || true
}

status() {
  if tmux has-session -t "$session" 2>/dev/null; then echo "running $session"; else echo "stopped $session"; fi
  ss -ltnp | grep -E ':(32000|29100) ' || true
}

case "$action" in
  start) start ;;
  stop) stop ;;
  status) status ;;
  *) echo "usage: $0 <start|stop|status>" >&2; exit 2 ;;
esac
