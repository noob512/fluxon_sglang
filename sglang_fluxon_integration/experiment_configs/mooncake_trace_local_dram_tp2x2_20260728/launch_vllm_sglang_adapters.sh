#!/usr/bin/env bash
set -euo pipefail

action="${1:-status}"
node="${2:-}"
group="${MOONCAKE_EXPERIMENT_GROUP:-}"
run_id="${MOONCAKE_EXPERIMENT_RUN_ID:-}"
gpu_ip="${MOONCAKE_GPU_IP:-}"
gpu_hostname="${MOONCAKE_GPU_HOSTNAME:-}"

case "$action" in
  start|stop|status) ;;
  *) echo "action must be start, stop, or status" >&2; exit 2 ;;
esac
case "$node" in
  node0) listen_port=31101; upstream_port=31001 ;;
  node1) listen_port=31102; upstream_port=31002 ;;
  *) echo "node must be node0 or node1" >&2; exit 2 ;;
esac
if [[ "$group" != E ]]; then
  echo "vLLM adapters require MOONCAKE_EXPERIMENT_GROUP=E" >&2
  exit 2
fi
if [[ ! "$run_id" =~ ^[a-zA-Z0-9_]+$ ]]; then
  echo "MOONCAKE_EXPERIMENT_RUN_ID must contain only letters, digits, and underscores" >&2
  exit 2
fi
if [[ ! "$gpu_ip" =~ ^[0-9]+([.][0-9]+){3}$ ]] \
  || [[ ! "$gpu_hostname" =~ ^[a-zA-Z0-9][a-zA-Z0-9._-]*$ ]]; then
  echo "MOONCAKE_GPU_IP and MOONCAKE_GPU_HOSTNAME must be explicit" >&2
  exit 2
fi

if [[ -d /public/mjq/.venv_sglang_fluxon ]]; then
  shared_mjq=/public/mjq
elif [[ -d /storage/mjq/.venv_sglang_fluxon ]]; then
  shared_mjq=/storage/mjq
else
  echo "neither /public/mjq nor /storage/mjq runtime is available" >&2
  exit 1
fi
python="$shared_mjq/.venv_sglang_fluxon/bin/python"
model_path="$shared_mjq/models/Qwen3-VL-8B-Instruct"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
adapter="$script_dir/vllm_sglang_adapter.py"
base_dir="${MOONCAKE_LOCAL_RUN_DIR:-/tmp/mooncake_trace_local_dram_tp2x2_20260728/$run_id}"
node_dir="$base_dir/vllm_adapter/$node"
log_path="$node_dir/adapter.log"
events_path="$node_dir/requests.jsonl"
startup_path="$node_dir/startup.json"
pid_path="$node_dir/process_group_leader.pid"
argv_path="$node_dir/command.argv"
session="mc_trace_E_${run_id}_adapter_${node}"

is_running() {
  tmux has-session -t "$session" 2>/dev/null
}

if [[ "$action" == status ]]; then
  if is_running; then
    tmux list-panes -t "$session" \
      -F 'session=#{session_name} pane_pid=#{pane_pid} dead=#{pane_dead} command=#{pane_current_command}'
    exit 0
  fi
  echo "stopped"
  exit 1
fi

if [[ "$action" == stop ]]; then
  if is_running; then
    tmux send-keys -t "$session" C-c || true
    for _ in $(seq 1 30); do
      is_running || break
      sleep 1
    done
  fi
  if is_running; then
    tmux kill-session -t "$session" || true
  fi
  if [[ -r "$pid_path" ]]; then
    leader="$(<"$pid_path")"
    if [[ "$leader" =~ ^[1-9][0-9]*$ ]] && kill -0 "$leader" 2>/dev/null; then
      kill -TERM -- "-$leader" 2>/dev/null || kill -TERM "$leader" 2>/dev/null || true
      for _ in $(seq 1 30); do
        kill -0 "$leader" 2>/dev/null || break
        sleep 1
      done
      if kill -0 "$leader" 2>/dev/null; then
        kill -KILL -- "-$leader" 2>/dev/null || kill -KILL "$leader" 2>/dev/null || true
      fi
    fi
  fi
  echo "stopped $node"
  exit 0
fi

if is_running; then
  echo "adapter session already exists: $session" >&2
  exit 1
fi
if [[ "$(hostname)" != "$gpu_hostname" ]] \
  || ! tr ' ' '\n' <<<"$(hostname -I)" | grep -Fx "$gpu_ip" >/dev/null; then
  echo "GPU identity mismatch: expected=$gpu_hostname/$gpu_ip actual=$(hostname)/$(hostname -I)" >&2
  exit 1
fi
if [[ "$(findmnt -T /tmp -o FSTYPE -n)" != xfs ]]; then
  echo "/tmp is not the required local XFS/NVMe filesystem" >&2
  findmnt -T /tmp >&2
  exit 1
fi
test -x "$python"
test -x "$adapter"
test -f "$model_path/config.json"
"$python" -c 'import aiohttp; assert aiohttp.__version__ == "3.13.5"'
curl -fsS --max-time 3 "http://127.0.0.1:$upstream_port/health" >/dev/null
if curl -fsS --max-time 2 "http://127.0.0.1:$listen_port/health" >/dev/null 2>&1; then
  echo "adapter port is already serving: $listen_port" >&2
  exit 1
fi
install -d -m 0755 "$node_dir"
for path in "$log_path" "$events_path" "$startup_path" "$pid_path" "$argv_path"; do
  if [[ -e "$path" ]]; then
    echo "adapter evidence path already exists: $path" >&2
    exit 1
  fi
done

command=(
  "$python"
  "$adapter"
  --instance "$node"
  --listen-host 127.0.0.1
  --listen-port "$listen_port"
  --upstream-base-url "http://127.0.0.1:$upstream_port"
  --expected-model "$model_path"
  --vocab-size 151936
  --request-timeout-s 21600
  --events-file "$events_path"
  --startup-manifest "$startup_path"
)
printf '%q ' "${command[@]}" >"$argv_path"
printf '\n' >>"$argv_path"
chmod 0444 "$argv_path"

launch_command="exec $(printf '%q ' env PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0 "${command[@]}") >>$(printf '%q' "$log_path") 2>&1"
tmux new-session -d -s "$session" "$launch_command"
if ! is_running; then
  echo "adapter session exited during launch: $node" >&2
  tail -n 120 "$log_path" >&2 || true
  exit 1
fi
leader="$(tmux display-message -p -t "$session":0.0 '#{pane_pid}')"
if [[ ! "$leader" =~ ^[1-9][0-9]*$ ]]; then
  echo "invalid adapter pane PID: $leader" >&2
  exit 1
fi
printf '%s\n' "$leader" >"$pid_path"
chmod 0444 "$pid_path"
for _ in $(seq 1 120); do
  if curl -fsS --max-time 3 "http://127.0.0.1:$listen_port/health" >/dev/null 2>&1; then
    echo "started $node adapter listen=$listen_port upstream=$upstream_port"
    exit 0
  fi
  if ! is_running; then
    echo "adapter exited before readiness: $node" >&2
    tail -n 120 "$log_path" >&2 || true
    exit 1
  fi
  sleep 1
done
echo "adapter readiness timeout: $node" >&2
tail -n 120 "$log_path" >&2 || true
exit 1
