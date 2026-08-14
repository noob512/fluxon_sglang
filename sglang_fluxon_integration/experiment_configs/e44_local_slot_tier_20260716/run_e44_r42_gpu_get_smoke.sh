#!/usr/bin/env bash
set -euo pipefail

workspace=/mnt/ceph/mjq/push_sglang
local_release=/mnt/nvme0/mjq_build/fluxon_e44_r42_gpu_direct_staging_20260721
host=116.238.240.2
port0=32656
port1=30245
root0=/storage/mjq/sglang_fluxon/fluxon_f1
root1=/storage/mjq/sglang_fluxon/fluxon_f2
experiment_name=e44_local_slot_tier_20260716
experiment0="$root0/$experiment_name"
experiment1="$root1/$experiment_name"
venv=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r42-gpu-direct-staging-20260721
site="$venv/lib/python3.10/site-packages"
runtime_ld="$site/fluxon_pyo3:$site/fluxon_pyo3.libs:/usr/lib/x86_64-linux-gnu:/lib/x86_64-linux-gnu"
expected_pyo3_sha256="$(tr -d '[:space:]' < "$local_release/fluxon_pyo3.abi3.so.sha256")"
key=fluxon_e44_r42_gpu_get_smoke_20260721
payload_size=4718592
payload_seed=73
cleaned=0

ssh_node() {
  local port="$1"
  shift
  ssh -o BatchMode=yes -o StrictHostKeyChecking=no -p "$port" "root@$host" "$@"
}

stop_interference() {
  local port="$1"
  ssh_node "$port" \
    "bash /storage/zgf/gpu_burner.sh stop 0,1 --no-restart >/dev/null 2>&1 || true; \
     pkill -TERM -f '^/opt/conda/bin/python -u /storage/mjq/computing/inference_like_compute.py' || true"
}

assert_gpu_clear() {
  local port="$1"
  ssh_node "$port" \
    "test -z \"\$(pgrep -af '[i]nference_like_compute.py|[.]gpu_burn_script_' || true)\"; \
     test -z \"\$(nvidia-smi --query-compute-apps=pid --format=csv,noheader,nounits)\"; \
     nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv,noheader,nounits"
}

restore_burner() {
  local port="$1"
  stop_interference "$port"
  ssh_node "$port" "bash /storage/zgf/gpu_burner.sh start 0,1 >/dev/null"
}

cleanup() {
  if [ "$cleaned" = 1 ]; then
    return
  fi
  cleaned=1
  set +e
  ssh_node "$port1" \
    "tmux send-keys -t e44_r42_gpu_get_smoke_owner_node1 C-c 2>/dev/null || true; sleep 3; tmux kill-session -t e44_r42_gpu_get_smoke_owner_node1 2>/dev/null || true"
  ssh_node "$port0" \
    "tmux send-keys -t e44_r42_gpu_get_smoke_owner_node0 C-c 2>/dev/null || true; \
     tmux send-keys -t e44_r42_gpu_get_smoke_master C-c 2>/dev/null || true; sleep 3; \
     tmux kill-session -t e44_r42_gpu_get_smoke_owner_node0 2>/dev/null || true; \
     tmux kill-session -t e44_r42_gpu_get_smoke_master 2>/dev/null || true; \
     tmux kill-session -t e44_r42_gpu_get_smoke_control 2>/dev/null || true"
  restore_burner "$port0"
  restore_burner "$port1"
  sleep 5
  ssh_node "$port0" "bash /storage/zgf/gpu_burner.sh status"
  ssh_node "$port1" "bash /storage/zgf/gpu_burner.sh status"
}
trap cleanup EXIT

for port in "$port0" "$port1"; do
  ssh_node "$port" \
    "test -z \"\$(pgrep -af '[f]luxon_py.runtime.start_master|[f]luxon_py.runtime.start_owner_kvclient|[s]glang.launch_server' || true)\""
  stop_interference "$port"
done
sleep 8
assert_gpu_clear "$port0"
assert_gpu_clear "$port1"

ssh_node "$port0" \
  "bash '$experiment0/start_control_e44_v5_perf.sh' '$root0' e44_r42_gpu_get_smoke_control"
ssh_node "$port0" \
  "bash '$experiment0/launch_master_e44_r42_gpu_get_smoke.sh' '$root0'"

ssh_node "$port0" \
  "bash '$experiment0/launch_owner_e44_r42_gpu_get_smoke.sh' '$root0' node0 '$expected_pyo3_sha256'" &
owner0_ssh=$!
ssh_node "$port1" \
  "bash '$experiment1/launch_owner_e44_r42_gpu_get_smoke.sh' '$root1' node1 '$expected_pyo3_sha256'" &
owner1_ssh=$!
wait "$owner0_ssh"
wait "$owner1_ssh"

config1="$root1/runtime_current_cpu_remote_20260710/config/fluxon_client_current_cpu_remote_tp2.yaml"
config0="$root0/runtime_current_cpu_remote_20260710/config/fluxon_client_current_cpu_remote_tp2.yaml"
ssh_node "$port1" \
  "env LD_LIBRARY_PATH='$runtime_ld' PYTHONDONTWRITEBYTECODE=1 '$venv/bin/python' -B '$experiment1/smoke_e44_r42_gpu_get.py' writer \
    --config '$config1' --instance-key e44_r42_gpu_get_writer_node1 \
    --key '$key' --size '$payload_size' --seed '$payload_seed'"

stop_interference "$port0"
sleep 5
assert_gpu_clear "$port0"
ssh_node "$port0" \
  "env CUDA_VISIBLE_DEVICES=0 LD_LIBRARY_PATH='$runtime_ld' PYTHONDONTWRITEBYTECODE=1 '$venv/bin/python' -B '$experiment0/smoke_e44_r42_gpu_get.py' reader \
    --config '$config0' --instance-key e44_r42_gpu_get_reader_node0 \
    --key '$key' --size '$payload_size' --seed '$payload_seed' --device 0"

echo "e44 r42 remote-owner GPU Get data smoke: passed"
