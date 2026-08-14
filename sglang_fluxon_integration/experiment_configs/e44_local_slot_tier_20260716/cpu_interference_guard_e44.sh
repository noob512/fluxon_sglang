#!/usr/bin/env bash
set -euo pipefail

heartbeat_file="${1:?usage: $0 HEARTBEAT_FILE VIOLATION_FILE [INTERVAL_SECONDS]}"
violation_file="${2:?usage: $0 HEARTBEAT_FILE VIOLATION_FILE [INTERVAL_SECONDS]}"
interval_seconds="${3:-1}"

case "$interval_seconds" in
  '' | *[!0-9]*) echo "interval must be a positive integer" >&2; exit 2 ;;
esac
if [ "$interval_seconds" -le 0 ]; then
  echo "interval must be greater than zero" >&2
  exit 2
fi

mkdir -p "$(dirname "$heartbeat_file")" "$(dirname "$violation_file")"
rm -f "$heartbeat_file" "$violation_file"

regex="[/]pvcteam/mjq/vlm_fluxon/VLCache-Sglang.*[s]glang.launch_server|[s]tart_vlcache_server.sh|[r]clone_benchmark/scripts/run_formal.py|[f]luxon_bench_keeper_[0-9]+.sh|[/]pvcteam/mjq/fluxon_s3_benchmark.*[f]luxon_py.runtime.start_(master|owner_kvclient)|[/]pvcteam/mjq/fluxon_s3_benchmark/[j]ava/bin/java|[r]eset_alluxio_formal.sh|[s]tart_alluxio_formal.sh|[/]alluxio/bin/[a]lluxio|[i]nference_like_compute.py|[.]gpu_burn_script_|[g]pu_burner.sh watchdog$|[g]pu_idle_guard.py"

while true; do
  self_pgid="$(ps -o pgid= -p $$ | tr -d ' ')"
  conflicts="$({
    pgrep -f "$regex" 2>/dev/null || true
  } | while IFS= read -r pid; do
    [ -n "$pid" ] || continue
    comm="$(ps -o comm= -p "$pid" 2>/dev/null | tr -d ' ')"
    case "$comm" in grep | find | rg | sed | cat | ps | pgrep) continue ;; esac
    pgid="$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d ' ')"
    [ -n "$pgid" ] && [ "$pgid" = "$self_pgid" ] && continue
    ps -o pid=,ppid=,pgid=,args= -p "$pid" 2>/dev/null || true
  done)"
  if [ -n "$conflicts" ]; then
    tmp="${violation_file}.$$"
    {
      printf 'timestamp_epoch=%s\n' "$(date +%s)"
      printf '%s\n' "$conflicts"
    } > "$tmp"
    mv -f "$tmp" "$violation_file"
    exit 1
  fi

  tmp="${heartbeat_file}.$$"
  printf '%s\n' "$(date +%s)" > "$tmp"
  mv -f "$tmp" "$heartbeat_file"
  sleep "$interval_seconds"
done
