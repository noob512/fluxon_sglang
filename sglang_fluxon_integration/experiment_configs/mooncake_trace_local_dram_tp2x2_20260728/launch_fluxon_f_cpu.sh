#!/usr/bin/env bash
set -euo pipefail

action="${1:-status}"
run_id="${FLUXON_F_RUN_ID:?missing FLUXON_F_RUN_ID}"
deployment_dir="${FLUXON_F_DEPLOYMENT_DIR:?missing FLUXON_F_DEPLOYMENT_DIR}"
case "$run_id" in
  *[!A-Za-z0-9_]*) echo "FLUXON_F_RUN_ID must contain only letters, digits, and underscores" >&2; exit 2 ;;
esac

runtime_root="${FLUXON_F_RUNTIME_ROOT:-/tmp/fluxon_mooncake_f_${run_id}}"
case "$runtime_root" in
  /tmp/fluxon_mooncake_f_*) ;;
  *) echo "invalid FLUXON_F_RUNTIME_ROOT: $runtime_root" >&2; exit 2 ;;
esac

gpu_ip="${FLUXON_F_GPU_IP:-10.233.90.51}"
cpu_ip="${FLUXON_F_CPU_IP:-10.233.114.150}"
expected_hostname="${FLUXON_F_CPU_HOSTNAME:-job-f8df1d36c3a6-20260728034352-6f5fb9dd4d-hl89q}"
cluster_name="${FLUXON_F_CLUSTER_NAME:-fluxon-mooncake-f-${run_id}}"
master_id="${FLUXON_F_MASTER_ID:-fluxon_mooncake_f_master}"
owner_id="${FLUXON_F_REMOTE_OWNER_ID:-fluxon_mooncake_f_remote_owner}"
root="$runtime_root/fluxon_cpu"
release="${FLUXON_F_CPU_RELEASE:-/storage/mjq/sglang_fluxon/releases/fluxon_e44_r96_ssd_early_only_cpu_20260728}"
venv="${FLUXON_F_CPU_VENV:-/tmp/fluxon_runtime/venv-r96-cpu-py311-20260728}"
site="$venv/lib/python3.11/site-packages"
launcher="$release/start_cpu_owner_numa1_ssd.sh"
session="fluxon_f_${run_id}_remote_owner"
shm="/dev/shm/fluxon_mooncake_f_${run_id}/cpu"

identity_gate() {
  test "$(hostname)" = "$expected_hostname"
  tr ' ' '\n' <<<"$(hostname -I)" | grep -Fx "$cpu_ip" >/dev/null
  test "$(findmnt -T /tmp -o FSTYPE -n)" = xfs
  test -x "$launcher"
  test -x "$venv/bin/python"
  test -f "$deployment_dir/fluxon_wait_ready.sh"
  grep -F ACTIVE /sys/class/infiniband/mlx5_0/ports/1/state >/dev/null
  grep -F ACTIVE /sys/class/infiniband/mlx5_1/ports/1/state >/dev/null
  test "$(cat /sys/fs/cgroup/memory.max)" = 322122547200
  local oom oom_kill
  oom="$(awk '$1 == "oom" {print $2}' /sys/fs/cgroup/memory.events)"
  oom_kill="$(awk '$1 == "oom_kill" {print $2}' /sys/fs/cgroup/memory.events)"
  test "$oom" = 0
  test "$oom_kill" = 0
  test "$(sha256sum "$site/fluxon_pyo3/fluxon_pyo3.abi3.so" | awk '{print $1}')" = \
    "${FLUXON_F_EXPECTED_PYO3_SHA256:-9ec5a8797c786df4a8c2b43eb43893e78f780caa7de3c5f75e330ddc77392093}"
  test "$(sha256sum "$site/fluxon_pyo3.libs/libfluxon_commu_core.so" | awk '{print $1}')" = \
    "${FLUXON_F_EXPECTED_CPU_CORE_SHA256:-63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06}"
  test "$(sha256sum "$site/fluxon_pyo3.libs/libfluxon_rdma_probe.so" | awk '{print $1}')" = \
    "${FLUXON_F_EXPECTED_RDMA_PROBE_SHA256:-e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883}"
  (
    cd "$release"
    sha256sum -c fluxon_release.sha256 >/dev/null
    cd ext_images
    sha256sum -c ext_images.sha256 >/dev/null
  )
}

headroom_gate() {
  local current max required
  current="$(cat /sys/fs/cgroup/memory.current)"
  max="$(cat /sys/fs/cgroup/memory.max)"
  required=$((274877906944 + 17179869184))
  if (( current + required > max )); then
    echo "insufficient CPU-role cgroup headroom: current=$current required=$required max=$max" >&2
    exit 1
  fi
  echo "CPU-role headroom passed: current=$current required=$required max=$max"
}

start() {
  identity_gate
  headroom_gate
  if tmux has-session -t "$session" 2>/dev/null; then
    echo "remote owner session already exists: $session" >&2
    exit 1
  fi
  if [[ -e "$runtime_root" || -e "$shm" ]]; then
    echo "refusing stale F CPU runtime/shm: runtime=$runtime_root shm=$shm" >&2
    exit 1
  fi
  if pgrep -af "fluxon_mooncake_f_${run_id}|fluxon-mooncake-f-${run_id}" >/dev/null; then
    echo "run-scoped F CPU process already exists" >&2
    exit 1
  fi
  if [[ -n "${FLUXON_CPU_OWNER_SSD_CAPACITY_BYTES:-}" ]]; then
    echo "SSD capacity must remain unset for F" >&2
    exit 2
  fi
  install -d -m 0755 "$root"
  install -m 0755 "$deployment_dir/fluxon_wait_ready.sh" "$root/fluxon_wait_ready.sh"
  ulimit -Sn 28672
  env \
    ROOT_DIR="$root" \
    FLUXON_NODE0_IP="$gpu_ip" \
    FLUXON_NODE1_IP="$gpu_ip" \
    FLUXON_CPU_NODE_IP="$cpu_ip" \
    FLUXON_EXTERNAL_CLUSTER_NAME="$cluster_name" \
    FLUXON_EXTERNAL_MASTER_ID="$master_id" \
    FLUXON_CPU_OWNER_ID="$owner_id" \
    FLUXON_CPU_OWNER_SUB_CLUSTER=remote_cache \
    FLUXON_CPU_OWNER_DRAM_BYTES=274877906944 \
    FLUXON_CPU_PYTHON_BIN="$venv/bin/python" \
    FLUXON_CPU_SITE_PACKAGES="$site" \
    FLUXON_CPU_EXPECTED_COMMU_CORE_SHA256="${FLUXON_F_EXPECTED_CPU_CORE_SHA256:-63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06}" \
    FLUXON_CPU_EXPECTED_RDMA_PROBE_SHA256="${FLUXON_F_EXPECTED_RDMA_PROBE_SHA256:-e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883}" \
    FLUXON_CPU_OWNER_SESSION="$session" \
    FLUXON_CPU_SHM_BASE="$shm" \
    FLUXON_CPU_OWNER_LARGE_FILE_ROOT="$runtime_root/owner_large_files" \
    FLUXON_CPU_DISABLE_OBSERVABILITY=true \
    FLUXON_CPU_PREFER_LOCAL_PLACEMENT=true \
    FLUXON_CPU_RDMA_DEVICE_0=mlx5_0 \
    FLUXON_CPU_RDMA_DEVICE_1=mlx5_1 \
    FLUXON_CPU_USER_RPC_SYNC_HANDLER_THREAD_COUNT=8 \
    FLUXON_CPU_CLEAN_START=1 \
    ETCDCTL="$release/ext_images/etcd/etcdctl" \
    PYTHONDONTWRITEBYTECODE=1 \
    RUST_LOG=info \
    "$launcher"
}

stop() {
  if tmux has-session -t "$session" 2>/dev/null; then
    tmux send-keys -t "$session" C-c 2>/dev/null || true
    for _ in $(seq 1 45); do
      tmux has-session -t "$session" 2>/dev/null || return 0
      sleep 1
    done
    tmux kill-session -t "$session" 2>/dev/null || true
  fi
}

status() {
  if tmux has-session -t "$session" 2>/dev/null; then echo "running $session"; else echo "stopped $session"; fi
  pgrep -af "fluxon_mooncake_f_${run_id}|fluxon-mooncake-f-${run_id}" || true
  cat /sys/fs/cgroup/memory.current /sys/fs/cgroup/memory.max
  cat /sys/fs/cgroup/memory.events
}

case "$action" in
  start) start ;;
  stop) stop ;;
  status) status ;;
  *) echo "usage: $0 <start|stop|status>" >&2; exit 2 ;;
esac
