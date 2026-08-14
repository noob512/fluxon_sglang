#!/usr/bin/env bash
set -euo pipefail

action="${1:-status}"
run_id="${FLUXON_F_RUN_ID:?missing FLUXON_F_RUN_ID}"
case "$run_id" in
  *[!A-Za-z0-9_]*) echo "FLUXON_F_RUN_ID must contain only letters, digits, and underscores" >&2; exit 2 ;;
esac

runtime_root="${FLUXON_F_RUNTIME_ROOT:-/tmp/fluxon_mooncake_f_${run_id}}"
case "$runtime_root" in
  /tmp/fluxon_mooncake_f_*) ;;
  *) echo "invalid FLUXON_F_RUNTIME_ROOT: $runtime_root" >&2; exit 2 ;;
esac

node_ip="${FLUXON_F_GPU_IP:-10.233.90.51}"
expected_hostname="${FLUXON_F_GPU_HOSTNAME:-lgsl-a4-5f02-m9-3-h100gpu145}"
cluster_name="${FLUXON_F_CLUSTER_NAME:-fluxon-mooncake-f-${run_id}}"
master_id="${FLUXON_F_MASTER_ID:-fluxon_mooncake_f_master}"
release="${FLUXON_F_GPU_RELEASE:-/public/mjq/sglang_fluxon/releases/fluxon_e44_r96_ssd_early_only_gpu_20260728}"
venv="$runtime_root/venv"
wait_script="$runtime_root/fluxon_f1/fluxon_wait_ready.sh"
run_dir="$runtime_root/control"
config_dir="$run_dir/config"
log_dir="$runtime_root/logs"
control_session="fluxon_f_${run_id}_control"
master_session="fluxon_f_${run_id}_master"
etcd_port=34579
etcd_peer_port=34580
greptime_port=4010
master_port=50051
master_ui_port=50161
etcdctl="$release/ext_images/etcd/etcdctl"

site="$venv/lib/python3.10/site-packages"
pyo3="$site/fluxon_pyo3"
pyo3_libs="$site/fluxon_pyo3.libs"
runtime_ld="$pyo3:$pyo3_libs:/usr/lib/x86_64-linux-gnu:/lib/x86_64-linux-gnu"
ibv_drivers="$pyo3_libs/libibverbs.d"

identity_gate() {
  test "$(hostname)" = "$expected_hostname"
  tr ' ' '\n' <<<"$(hostname -I)" | grep -Fx "$node_ip" >/dev/null
  test "$(findmnt -T /tmp -o FSTYPE -n)" = xfs
  test -x "$venv/bin/python"
  test -x "$wait_script"
  test -x "$release/ext_images/etcd/start.sh"
  test -x "$release/ext_images/greptime/start.sh"
  test -x "$etcdctl"
  test "$(sha256sum "$pyo3/fluxon_pyo3.abi3.so" | awk '{print $1}')" = \
    "${FLUXON_F_EXPECTED_PYO3_SHA256:-9ec5a8797c786df4a8c2b43eb43893e78f780caa7de3c5f75e330ddc77392093}"
}

wait_port() {
  local port="$1"
  local deadline=$(( $(date +%s) + 120 ))
  until ss -ltn | awk -v p=":$port" '$4 ~ p"$" {found=1} END {exit found ? 0 : 1}'; do
    if (( $(date +%s) >= deadline )); then
      echo "timeout waiting for port $port" >&2
      exit 1
    fi
    sleep 1
  done
}

start() {
  identity_gate
  if tmux has-session -t "$control_session" 2>/dev/null || tmux has-session -t "$master_session" 2>/dev/null; then
    echo "F control/master session already exists" >&2
    exit 1
  fi
  if ss -ltn | grep -Eq ":(${etcd_port}|${etcd_peer_port}|${greptime_port}|${master_port}|${master_ui_port}) "; then
    echo "Fluxon F control port is already in use" >&2
    ss -ltnp | grep -E ":(${etcd_port}|${etcd_peer_port}|${greptime_port}|${master_port}|${master_ui_port}) " >&2 || true
    exit 1
  fi

  install -d -m 0755 "$config_dir" "$log_dir" "$run_dir/master_work"
  rm -rf -- "$run_dir/etcd-data" "$run_dir/greptimedb" "$run_dir/master_work"
  install -d -m 0755 "$run_dir/master_work"

  cat > "$config_dir/etcd.sh" <<EOF
ETCD_ARGS=(
  --data-dir "\$WORKDIR/etcd-data"
  --name fluxon-f-etcd0
  --advertise-client-urls "http://0.0.0.0:${etcd_port}"
  --listen-client-urls "http://0.0.0.0:${etcd_port}"
  --listen-peer-urls "http://0.0.0.0:${etcd_peer_port}"
  --initial-advertise-peer-urls "http://0.0.0.0:${etcd_peer_port}"
  --initial-cluster "fluxon-f-etcd0=http://0.0.0.0:${etcd_peer_port}"
  --initial-cluster-token "${cluster_name}"
  --initial-cluster-state new
  --auto-compaction-retention=1
)
EOF
  cat > "$config_dir/greptime.sh" <<EOF
GREPTIME_ARGS=(
  standalone start
  --data-home "\$WORKDIR/greptimedb"
  --http-addr 0.0.0.0:${greptime_port}
  --rpc-bind-addr 127.0.0.1:0
  --mysql-addr 127.0.0.1:0
  --postgres-addr 127.0.0.1:0
)
EOF
  cat > "$config_dir/master.yaml" <<EOF
etcd_endpoints:
- "${node_ip}:${etcd_port}"
cluster_name: "${cluster_name}"
instance_key: "${master_id}"
port: ${master_port}
monitoring:
  prometheus_base_url: "http://${node_ip}:${greptime_port}/v1/prometheus"
  prom_remote_write_url:
  - "http://${node_ip}:${greptime_port}/v1/prometheus/write"
  otlp_log_api:
    otlp_endpoint: "http://${node_ip}:${greptime_port}/v1/otlp/v1/logs"
master_ui:
  http_listen_addr: "0.0.0.0:${master_ui_port}"
network:
  subnet_whitelist:
  - "10.233.0.0/16"
log_dir: "${run_dir}/master_logs"
replica_task_placement:
  policy: "bounded_role_queue_aware"
  active_node_roles: ["prefill", "decode"]
  remote_only_node_roles: ["remote_cache"]
  restrict_to_remote_only_node_roles: true
  remote_only_shard_weight: 1.02
replica_cache_capacity_ratio: 0.95
replica_writeback_tier1_capacity_ratio: 0.05
test_spec_config:
  disable_observability: false
  user_rpc_sync_handler_thread_count: 8
  ssd_read_source_policy: local_ssd_only_first
EOF

  : > "$log_dir/etcd.log"
  : > "$log_dir/greptime.log"
  : > "$log_dir/master.log"
  tmux new-session -d -s "$control_session" -n etcd \
    "cd '$run_dir' && exec '$release/ext_images/etcd/start.sh' --config '$config_dir/etcd.sh' --workdir '$run_dir' >> '$log_dir/etcd.log' 2>&1"
  ETCDCTL="$etcdctl" ETCD_ENDPOINT="http://${node_ip}:${etcd_port}" \
    FLUXON_CLUSTER_NAME="$cluster_name" TIMEOUT=90 "$wait_script" wait-etcd
  tmux new-window -t "$control_session" -n greptime \
    "cd '$run_dir' && exec '$release/ext_images/greptime/start.sh' --config '$config_dir/greptime.sh' --workdir '$run_dir' >> '$log_dir/greptime.log' 2>&1"
  wait_port "$greptime_port"

  tmux new-session -d -s "$master_session" -n master \
    "cd '$run_dir/master_work' && exec env PATH='$venv/bin':\$PATH LD_LIBRARY_PATH='$runtime_ld' IBV_DRIVERS_PATH='$ibv_drivers' PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 RUST_LOG=info '$venv/bin/python' -B -m fluxon_py.runtime.start_master -c '$config_dir/master.yaml' -w '$run_dir/master_work' >> '$log_dir/master.log' 2>&1"
  ETCDCTL="$etcdctl" ETCD_ENDPOINT="http://${node_ip}:${etcd_port}" \
    FLUXON_CLUSTER_NAME="$cluster_name" TIMEOUT=180 "$wait_script" wait-member "$master_id"
  echo "started Fluxon F control/master: cluster=$cluster_name master=$master_id"
}

stop() {
  tmux kill-session -t "$master_session" 2>/dev/null || true
  tmux kill-session -t "$control_session" 2>/dev/null || true
}

status() {
  for session in "$control_session" "$master_session"; do
    if tmux has-session -t "$session" 2>/dev/null; then
      echo "running $session"
    else
      echo "stopped $session"
    fi
  done
  ss -ltnp | grep -E ":(${etcd_port}|${etcd_peer_port}|${greptime_port}|${master_port}|${master_ui_port}) " || true
}

case "$action" in
  start) start ;;
  stop) stop ;;
  status) status ;;
  *) echo "usage: $0 <start|stop|status>" >&2; exit 2 ;;
esac
