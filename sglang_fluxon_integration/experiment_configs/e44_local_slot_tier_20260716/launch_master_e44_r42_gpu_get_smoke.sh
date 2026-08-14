#!/usr/bin/env bash
set -euo pipefail

root="${1:-/storage/mjq/sglang_fluxon/fluxon_f1}"
session=e44_r42_gpu_get_smoke_master
experiment="$root/e44_local_slot_tier_20260716"
venv=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r42-gpu-direct-staging-20260721
config="$experiment/master_config_e44_r42_gpu_get_smoke.yaml"
work="$root/services/master_work_e44_r42_gpu_get_smoke_20260721"
log="$root/log/current_cpu_remote_20260710/master_e44_r42_gpu_get_smoke_20260721.log"
site="$venv/lib/python3.10/site-packages"

if tmux has-session -t "$session" 2>/dev/null; then
  echo "master session already exists: $session" >&2
  exit 1
fi
rm -rf "$work"
mkdir -p "$work" "$(dirname "$log")"
: > "$log"

tmux new-session -d -s "$session" -n master \
  "cd '$work' && exec env PATH='$venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin' LD_LIBRARY_PATH='$site/fluxon_pyo3:$site/fluxon_pyo3.libs:/usr/lib/x86_64-linux-gnu:/lib/x86_64-linux-gnu' PYTHONUNBUFFERED=1 RUST_LOG=info '$venv/bin/python' -m fluxon_py.runtime.start_master -c '$config' -w '$work' >> '$log' 2>&1"

TIMEOUT=120 ETCDCTL="$root/fluxon_release/ext_images/etcd/etcdctl" \
  ETCD_ENDPOINT=http://10.233.114.139:34579 \
  "$root/fluxon_wait_ready.sh" wait-member sglang_l13_master
echo "started r42 smoke master: session=$session log=$log"
