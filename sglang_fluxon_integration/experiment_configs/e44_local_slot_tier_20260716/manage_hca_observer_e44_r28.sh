#!/usr/bin/env bash
set -euo pipefail

action="${1:?usage: $0 start|status|stop ROOT NODE [INTERVAL_MS] [RUN_ID]}"
root="${2:?missing fluxon root}"
node="${3:?missing node label}"
interval_ms="${4:-500}"
run_id="${5:-e44_r28_r22_netobs_replay}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
session="zth_hca_observer_${run_id}_${node}"
result_dir="${E44_HCA_OBSERVER_RESULT_DIR:-$root/e44_local_slot_tier_20260716/netobs_results}"
out="$result_dir/${run_id}_${node}.jsonl"
log="$result_dir/${run_id}_${node}.log"
tool="$script_dir/netobs_tools"
hcas="${E44_HCA_OBSERVER_HCAS:-mlx5_4,mlx5_6}"
if [[ ! "$hcas" =~ ^mlx5_[0-9]+,mlx5_[0-9]+$ ]]; then
  echo "E44_HCA_OBSERVER_HCAS must contain exactly two mlx5 devices" >&2
  exit 2
fi

case "$action" in
  start)
    tmux has-session -t "$session" 2>/dev/null && {
      echo "observer session already exists: $session" >&2
      exit 1
    }
    test "$(sha256sum "$tool/perfquery" | cut -d ' ' -f 1)" = 42c32fd2b92022754a6be5cf5f3e490c54413ddba05962c82cc4473795cbbc58
    mkdir -p "$result_dir"
    rm -f "$out" "$log"
    tmux new-session -d -s "$session" -n observer \
      "exec nice -n 19 /usr/bin/python3 '$script_dir/hca_observer_e44_r28.py' --node '$node' --output '$out' --perfquery '$tool/perfquery' --lib-dir '$tool/lib' --hcas '$hcas' --interval-ms '$interval_ms' >> '$log' 2>&1"
    for _ in $(seq 1 40); do
      if [ -s "$out" ] && [ "$(wc -l < "$out")" -ge 2 ]; then
        echo "observer started: session=$session output=$out hcas=$hcas"
        exit 0
      fi
      sleep 0.25
    done
    echo "observer failed to produce samples: $session" >&2
    test -f "$log" && tail -n 40 "$log" >&2
    exit 1
    ;;
  status)
    if tmux has-session -t "$session" 2>/dev/null; then
      state=running
    else
      state=stopped
    fi
    lines=0
    test -f "$out" && lines="$(wc -l < "$out")"
    echo "session=$session state=$state lines=$lines output=$out hcas=$hcas"
    ;;
  stop)
    if tmux has-session -t "$session" 2>/dev/null; then
      tmux send-keys -t "$session" C-c
      for _ in $(seq 1 40); do
        tmux has-session -t "$session" 2>/dev/null || break
        sleep 0.25
      done
      tmux has-session -t "$session" 2>/dev/null && tmux kill-session -t "$session"
    fi
    lines=0
    test -f "$out" && lines="$(wc -l < "$out")"
    echo "observer stopped: session=$session lines=$lines output=$out hcas=$hcas"
    ;;
  *)
    echo "unsupported action: $action" >&2
    exit 2
    ;;
esac
