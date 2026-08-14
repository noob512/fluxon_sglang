#!/usr/bin/env bash
set -euo pipefail

root="${1:-/storage/mjq/sglang_fluxon/fluxon_f1}"
session="${2:-zth_fluxon_control_e44_v5_perf}"
node0_ip="${FLUXON_NODE0_IP:-10.233.114.139}"
release="$root/fluxon_release"
helper="$root/fluxon_wait_ready.sh"
run_dir="$root/runtime_control_e44_v5_perf_20260718"
config_dir="$run_dir/config"
log_dir="$root/log/current_cpu_remote_20260710"

mkdir -p "$config_dir" "$run_dir" "$log_dir"

if [ ! -x "$release/ext_images/etcd/start.sh" ]; then
  echo "missing etcd start script: $release/ext_images/etcd/start.sh" >&2
  exit 1
fi
if [ ! -x "$release/ext_images/greptime/start.sh" ]; then
  echo "missing greptime start script: $release/ext_images/greptime/start.sh" >&2
  exit 1
fi
if [ ! -x "$helper" ]; then
  echo "missing wait helper: $helper" >&2
  exit 1
fi

if tmux has-session -t "$session" 2>/dev/null; then
  echo "tmux session already exists: $session" >&2
  exit 1
fi

busy_ports="$(ss -ltn 2>/dev/null | grep -E ':(34579|34580|4010|50051|50161) ' || true)"
if [ -n "$busy_ports" ]; then
  echo "Fluxon control ports are busy:" >&2
  echo "$busy_ports" >&2
  exit 1
fi

cat > "$config_dir/etcd.sh" <<'EOF_ETCD'
ETCD_ARGS=(
  --data-dir "$WORKDIR/etcd-data"
  --name e44-etcd0
  --advertise-client-urls "http://0.0.0.0:34579"
  --listen-client-urls "http://0.0.0.0:34579"
  --listen-peer-urls "http://0.0.0.0:34580"
  --initial-advertise-peer-urls "http://0.0.0.0:34580"
  --initial-cluster "e44-etcd0=http://0.0.0.0:34580"
  --initial-cluster-token "e44-v5-perf"
  --initial-cluster-state "new"
  --auto-compaction-retention=1
)
EOF_ETCD

cat > "$config_dir/greptime.sh" <<'EOF_GREPTIME'
GREPTIME_ARGS=(
  standalone start
  --data-home "$WORKDIR/greptimedb"
  --http-addr 0.0.0.0:4010
  --rpc-bind-addr 127.0.0.1:0
  --mysql-addr 127.0.0.1:0
  --postgres-addr 127.0.0.1:0
)
EOF_GREPTIME

rm -rf "$run_dir/etcd-data" "$run_dir/greptimedb"
: > "$log_dir/etcd_e44_v5_perf_20260718.log"
: > "$log_dir/greptime_e44_v5_perf_20260718.log"

tmux new-session -d -s "$session" -n etcd \
  "cd '$run_dir' && exec '$release/ext_images/etcd/start.sh' --config '$config_dir/etcd.sh' --workdir '$run_dir' >> '$log_dir/etcd_e44_v5_perf_20260718.log' 2>&1"

TIMEOUT=90 ETCDCTL="$release/ext_images/etcd/etcdctl" ETCD_ENDPOINT="http://${node0_ip}:34579" "$helper" wait-etcd

tmux new-window -t "$session" -n greptime \
  "cd '$run_dir' && exec '$release/ext_images/greptime/start.sh' --config '$config_dir/greptime.sh' --workdir '$run_dir' >> '$log_dir/greptime_e44_v5_perf_20260718.log' 2>&1"

echo "started control plane: session=$session root=$root"
