#!/usr/bin/env bash
set -euo pipefail

workspace=/mnt/ceph/mjq/push_sglang
local_release="${E44_R43_RELEASE_DIR:-/mnt/nvme0/mjq_build/fluxon_e44_r43_gpu_direct_cuda_20260721}"
smoke_tag="${E44_R43_SMOKE_TAG:-e44_r43_gpu_get_smoke}"
instance_prefix="${E44_R43_INSTANCE_PREFIX:-e44_r43_gpu_get}"
host=116.238.240.2
port0=32656
port1=30245
root0=/storage/mjq/sglang_fluxon/fluxon_f1
root1=/storage/mjq/sglang_fluxon/fluxon_f2
experiment_name=e44_local_slot_tier_20260716
experiment0="$root0/$experiment_name"
experiment1="$root1/$experiment_name"
venv="${E44_R43_VENV:-/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r43-gpu-direct-cuda-20260721}"
tmux_tmpdir="${E44_R43_TMUX_TMPDIR:-/run/fluxon_e44_r44_gpu_get_tmux}"
ssh_identity="${E44_R43_SSH_IDENTITY:-/home/zyc/.ssh/infra44_ed25519}"
site="$venv/lib/python3.10/site-packages"
runtime_ld="$site/fluxon_pyo3:$site/fluxon_pyo3.libs:/usr/lib/x86_64-linux-gnu:/lib/x86_64-linux-gnu"
wheel="$local_release/fluxon-0.2.1-cp38-abi3-manylinux_2_28_x86_64.whl"
expected_pyo3_sha256="$(tr -d '[:space:]' < "$local_release/fluxon_pyo3.abi3.so.sha256")"
expected_commu_core_sha256="$(unzip -p "$wheel" 'fluxon_pyo3.libs/libfluxon_commu_core.so' | sha256sum | awk '{print $1}')"
expected_rdma_probe_sha256="$(unzip -p "$wheel" 'fluxon_pyo3.libs/libfluxon_rdma_probe.so' | sha256sum | awk '{print $1}')"
key="${E44_R43_KEY:-fluxon_e44_r42_gpu_get_smoke_20260721}"
payload_size=4718592
payload_seed=73
writer_rust_log="${E44_R43_WRITER_RUST_LOG:-warn}"
reader_rust_log="${E44_R43_READER_RUST_LOG:-info}"
cpu_fallback_smoke="${E44_R43_CPU_FALLBACK_SMOKE:-0}"
mixed_source_smoke="${E44_R52_MIXED_SOURCE_SMOKE:-0}"
require_terminal_timing="${E44_R54_REQUIRE_TERMINAL_TIMING:-0}"
planned_cpu_stress="${E44_R55_PLANNED_CPU_STRESS:-0}"
planned_cpu_stress_count="${E44_R55_PLANNED_CPU_STRESS_COUNT:-228}"
owner_dram_bytes="${E44_R43_OWNER_DRAM_BYTES:-1073741824}"
owner_reserve_value_len="${E44_R43_OWNER_LOCAL_RESERVE_VALUE_LEN:-4718592}"
owner_reserve_capacity_bytes="${E44_R43_OWNER_LOCAL_RESERVE_PAYLOAD_CAPACITY_BYTES:-4718592}"
cleaned=0

case "$cpu_fallback_smoke" in
  0|1) ;;
  *) echo "E44_R43_CPU_FALLBACK_SMOKE must be 0 or 1" >&2; exit 2 ;;
esac
case "$mixed_source_smoke" in
  0|1) ;;
  *) echo "E44_R52_MIXED_SOURCE_SMOKE must be 0 or 1" >&2; exit 2 ;;
esac
case "$require_terminal_timing" in
  0) terminal_timing_arg= ;;
  1) terminal_timing_arg=--require-terminal-timing ;;
  *) echo "E44_R54_REQUIRE_TERMINAL_TIMING must be 0 or 1" >&2; exit 2 ;;
esac
case "$planned_cpu_stress" in
  0|1) ;;
  *) echo "E44_R55_PLANNED_CPU_STRESS must be 0 or 1" >&2; exit 2 ;;
esac
if ! [[ "$planned_cpu_stress_count" =~ ^[1-9][0-9]*$ ]]; then
  echo "E44_R55_PLANNED_CPU_STRESS_COUNT must be positive" >&2
  exit 2
fi
test -f "$ssh_identity"

ssh_node() {
  local port="$1"
  shift
  ssh -i "$ssh_identity" -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=no -p "$port" "root@$host" "$@"
}

stop_interference() {
  local port="$1"
  ssh_node "$port" \
    "bash /storage/zgf/gpu_burner.sh stop 0,1 --no-restart >/dev/null 2>&1 || true; \
     pkill -TERM -f '[.]gpu_burn_script_' || true; \
     pkill -TERM -f '[i]nference_like_compute.py' || true; \
     sleep 2; \
     pkill -KILL -f '[.]gpu_burn_script_|[i]nference_like_compute.py' || true"
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
    "export TMUX_TMPDIR='$tmux_tmpdir'; tmux send-keys -t '${smoke_tag}_owner_node1' C-c 2>/dev/null || true; sleep 3; tmux kill-session -t '${smoke_tag}_owner_node1' 2>/dev/null || true"
  ssh_node "$port0" \
    "export TMUX_TMPDIR='$tmux_tmpdir'; tmux send-keys -t '${smoke_tag}_owner_node0' C-c 2>/dev/null || true; \
     tmux send-keys -t '${smoke_tag}_master' C-c 2>/dev/null || true; sleep 3; \
     tmux kill-session -t '${smoke_tag}_owner_node0' 2>/dev/null || true; \
     tmux kill-session -t '${smoke_tag}_master' 2>/dev/null || true; \
     tmux kill-session -t '${smoke_tag}_control' 2>/dev/null || true"
  restore_burner "$port0"
  restore_burner "$port1"
  sleep 5
  ssh_node "$port0" "bash /storage/zgf/gpu_burner.sh status"
  ssh_node "$port1" "bash /storage/zgf/gpu_burner.sh status"
}
trap cleanup EXIT

ssh_node "$port0" \
  "test -z \"\$(pgrep -af '[r]un_pilot.py|[r]un_case.py|[r]clone .*fluxon_s3_benchmark' || true)\""
for port in "$port0" "$port1"; do
  ssh_node "$port" \
    "set -e; test -z \"\$(pgrep -af '[f]luxon_py.runtime.start_master|[f]luxon_py.runtime.start_owner_kvclient|[s]glang.launch_server' || true)\"; \
     test -z \"\$(pgrep -af '[g]pu_idle_guard.py' || true)\"; \
     mkdir -p '$tmux_tmpdir'; chmod 700 '$tmux_tmpdir'; \
     export TMUX_TMPDIR='$tmux_tmpdir'; tmux kill-server 2>/dev/null || true"
  stop_interference "$port"
done
sleep 8
assert_gpu_clear "$port0"
assert_gpu_clear "$port1"

ssh_node "$port0" \
  "env TMUX_TMPDIR='$tmux_tmpdir' bash '$experiment0/start_control_e44_v5_perf.sh' '$root0' '${smoke_tag}_control'"
ssh_node "$port0" \
  "env TMUX_TMPDIR='$tmux_tmpdir' E44_R43_SMOKE_TAG='$smoke_tag' E44_R43_VENV='$venv' bash '$experiment0/launch_master_e44_r43_gpu_get_smoke.sh' '$root0'"

ssh_node "$port0" \
  "env TMUX_TMPDIR='$tmux_tmpdir' E44_R43_SMOKE_TAG='$smoke_tag' E44_R43_VENV='$venv' E44_R43_OWNER_DRAM_BYTES='$owner_dram_bytes' E44_R43_OWNER_LOCAL_RESERVE_VALUE_LEN='$owner_reserve_value_len' E44_R43_OWNER_LOCAL_RESERVE_PAYLOAD_CAPACITY_BYTES='$owner_reserve_capacity_bytes' bash '$experiment0/launch_owner_e44_r43_gpu_get_smoke.sh' '$root0' node0 '$expected_pyo3_sha256' '$expected_commu_core_sha256' '$expected_rdma_probe_sha256'" &
owner0_ssh=$!
ssh_node "$port1" \
  "env TMUX_TMPDIR='$tmux_tmpdir' E44_R43_SMOKE_TAG='$smoke_tag' E44_R43_VENV='$venv' E44_R43_OWNER_DRAM_BYTES='$owner_dram_bytes' E44_R43_OWNER_LOCAL_RESERVE_VALUE_LEN='$owner_reserve_value_len' E44_R43_OWNER_LOCAL_RESERVE_PAYLOAD_CAPACITY_BYTES='$owner_reserve_capacity_bytes' bash '$experiment1/launch_owner_e44_r43_gpu_get_smoke.sh' '$root1' node1 '$expected_pyo3_sha256' '$expected_commu_core_sha256' '$expected_rdma_probe_sha256'" &
owner1_ssh=$!
wait "$owner0_ssh"
wait "$owner1_ssh"

config1="$root1/runtime_current_cpu_remote_20260710/config/fluxon_client_current_cpu_remote_tp2.yaml"
config0="$root0/runtime_current_cpu_remote_20260710/config/fluxon_client_current_cpu_remote_tp2.yaml"
ssh_node "$port1" \
  "timeout --signal=TERM --kill-after=5s 90s env RUST_LOG='$writer_rust_log' LD_LIBRARY_PATH='$runtime_ld' PYTHONDONTWRITEBYTECODE=1 '$venv/bin/python' -B '$experiment1/smoke_e44_r42_gpu_get.py' writer \
    --config '$config1' --instance-key '${instance_prefix}_writer_node1' \
    --key '$key' --size '$payload_size' --seed '$payload_seed' --hard-exit-after-success"

stop_interference "$port0"
sleep 5
assert_gpu_clear "$port0"
ssh_node "$port0" \
  "timeout --signal=TERM --kill-after=5s 90s env CUDA_VISIBLE_DEVICES=0 RUST_LOG='$reader_rust_log' LD_LIBRARY_PATH='$runtime_ld' PYTHONDONTWRITEBYTECODE=1 '$venv/bin/python' -B '$experiment0/smoke_e44_r42_gpu_get.py' reader \
    --config '$config0' --instance-key '${instance_prefix}_reader_node0' \
    --key '$key' --size '$payload_size' --seed '$payload_seed' --device 0 $terminal_timing_arg --hard-exit-after-success"

echo "$smoke_tag remote-owner GPU Get data smoke: passed"

if [ "$mixed_source_smoke" = 1 ]; then
  local_key="${key}_owner0_local"
  local_seed=41
  ssh_node "$port0" \
    "timeout --signal=TERM --kill-after=5s 90s env RUST_LOG='$writer_rust_log' LD_LIBRARY_PATH='$runtime_ld' PYTHONDONTWRITEBYTECODE=1 '$venv/bin/python' -B '$experiment0/smoke_e44_r42_gpu_get.py' writer \
      --config '$config0' --instance-key '${instance_prefix}_local_writer_node0' \
      --key '$local_key' --size '$payload_size' --seed '$local_seed' --hard-exit-after-success"
  stop_interference "$port0"
  sleep 5
  assert_gpu_clear "$port0"
  ssh_node "$port0" \
    "timeout --signal=TERM --kill-after=5s 120s env CUDA_VISIBLE_DEVICES=0 RUST_LOG='$reader_rust_log' LD_LIBRARY_PATH='$runtime_ld' PYTHONDONTWRITEBYTECODE=1 '$venv/bin/python' -B '$experiment0/smoke_e44_r52_mixed_source.py' \
      --config '$config0' --instance-key '${instance_prefix}_mixed_reader_node0' \
      --local-key '$local_key' --remote-key '$key' --size '$payload_size' \
      --local-seed '$local_seed' --remote-seed '$payload_seed' --device 0 \
      --hard-exit-after-success"
  echo "$smoke_tag local-only plus mixed local/remote GPU source smoke: passed"
fi

if [ "$cpu_fallback_smoke" = 1 ]; then
  ssh_node "$port0" \
    "timeout --signal=TERM --kill-after=5s 90s env RUST_LOG='$reader_rust_log' LD_LIBRARY_PATH='$runtime_ld' PYTHONDONTWRITEBYTECODE=1 '$venv/bin/python' -B '$experiment0/smoke_e44_r50_plan_bind.py' \
      --config '$config0' --instance-key '${instance_prefix}_cpu_reader_node0' \
      --key '$key' --size '$payload_size' --seed '$payload_seed' --hard-exit-after-success"
  echo "$smoke_tag planned CPU fallback data smoke: passed"
fi

if [ "$planned_cpu_stress" = 1 ]; then
  stress_prefix="${key}_planned_cpu_stress"
  ssh_node "$port1" \
    "timeout --signal=TERM --kill-after=10s 300s env RUST_LOG='$writer_rust_log' LD_LIBRARY_PATH='$runtime_ld' PYTHONDONTWRITEBYTECODE=1 '$venv/bin/python' -B '$experiment1/smoke_e44_r55_planned_cpu_stress.py' writer \
      --config '$config1' --instance-key '${instance_prefix}_stress_writer_node1' \
      --key-prefix '$stress_prefix' --count '$planned_cpu_stress_count' \
      --size '$payload_size' --seed '$payload_seed'"
  ssh_node "$port0" \
    "timeout --signal=TERM --kill-after=10s 300s env RUST_LOG='$reader_rust_log' LD_LIBRARY_PATH='$runtime_ld' PYTHONDONTWRITEBYTECODE=1 '$venv/bin/python' -B '$experiment0/smoke_e44_r55_planned_cpu_stress.py' reader \
      --config '$config0' --instance-key '${instance_prefix}_stress_reader_node0' \
      --key-prefix '$stress_prefix' --count '$planned_cpu_stress_count' \
      --size '$payload_size' --seed '$payload_seed' --concurrency 32"
  sleep 35
  ssh_node "$port0" \
    "owner_line=\$(grep 'owner Get lifecycle snapshot' '$root0/log/current_cpu_remote_20260710/owner.log' | tail -1 | sed -E 's/\\x1B\\[[0-9;]*[[:alpha:]]//g'); \
     master_line=\$(grep 'master key activity runtime' '$root0/log/current_cpu_remote_20260710/master_${smoke_tag}_20260721.log' | tail -1 | sed -E 's/\\x1B\\[[0-9;]*[[:alpha:]]//g'); \
     test -n \"\$owner_line\"; test -n \"\$master_line\"; \
     grep -F 'active_flights=0' <<<\"\$owner_line\"; \
     grep -F 'finishing_flights=0' <<<\"\$owner_line\"; \
     grep -F 'inflight_gets=0' <<<\"\$master_line\""
  echo "$smoke_tag planned CPU ${planned_cpu_stress_count}-item stress smoke: passed"
fi
