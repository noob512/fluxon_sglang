#!/usr/bin/env bash
set -euo pipefail

payload_dir="${1:?usage: $0 PAYLOAD_DIR [install|rollback]}"
action="${2:-install}"
runtime_root="${FLUXON_F_RUNTIME_ROOT:-/tmp/fluxon_mooncake_f_f_synrr_r111_l3retry_30448_20260802_2125}"
run_id="${FLUXON_F_RUN_ID:-f_synrr_r111_l3retry_30448_20260802_2125}"

case "$runtime_root" in
  /tmp/fluxon_mooncake_f_*) ;;
  *) echo "invalid runtime root: $runtime_root" >&2; exit 2 ;;
esac
case "$run_id" in
  *[!A-Za-z0-9_]*) echo "invalid run id: $run_id" >&2; exit 2 ;;
esac
case "$action" in
  install|rollback) ;;
  *) echo "action must be install or rollback" >&2; exit 2 ;;
esac

test "$(hostname)" = lgsl-a4-5f02-m9-3-h100gpu145
tr ' ' '\n' <<<"$(hostname -I)" | grep -Fx 10.233.90.51 >/dev/null
test "$(findmnt -T /tmp -o FSTYPE -n)" = xfs

p8_inner="$payload_dir/start_gpu_stack_owner_tp2x2_f_p8_h2d.sh"
p9_inner="$payload_dir/start_gpu_stack_owner_tp2x2_f_p9_common2.sh"
p9_wrapper="$payload_dir/launch_fluxon_f_gpu_p9_common2_gpu4567.sh"
p9_replayer="$payload_dir/mooncake_trace_replay_p9_common2.py"
p9_finalizer="$payload_dir/finalize_fluxon_f_capacity_p9_common2.py"
p9_manifest="$payload_dir/OVERLAY.json"

p8_inner_sha=314518a086b1d18aa7ee40340ed95a662a644f8d6fcf58923d57089c725e02cd
p9_inner_sha=4f51091847b12584f180e972053fd4ff8dfbecdfb8aab709ff2700256811c924
p9_wrapper_sha=bdb4b1188b73f7ec59b6575d6578548a9f243e68465ea366fef6e9bb922a3094
p9_replayer_sha=106b655a9b384f86727a5b3a5e194f79dd860d978010d664daf3bc0f8e90ce16
p9_finalizer_sha=17063a83a06ec154459d7f27f8a95de3ad1d4386b240930c5da91a021e60adce
p9_manifest_sha=ba4ae2fcc782b3233498aba834ffded0b501acfd0f15dc7646be8485e125e7f5

check_sha() {
  local path="$1" expected="$2"
  test -f "$path"
  test "$(sha256sum "$path" | awk '{print $1}')" = "$expected"
}

check_sha "$p8_inner" "$p8_inner_sha"
check_sha "$p9_inner" "$p9_inner_sha"
check_sha "$p9_wrapper" "$p9_wrapper_sha"
check_sha "$p9_replayer" "$p9_replayer_sha"
check_sha "$p9_finalizer" "$p9_finalizer_sha"
check_sha "$p9_manifest" "$p9_manifest_sha"
bash -n "$p8_inner"
bash -n "$p9_inner"
bash -n "$p9_wrapper"

for session in "fluxon_f_${run_id}_sglang0" "fluxon_f_${run_id}_sglang1"; do
  if tmux has-session -t "$session" 2>/dev/null; then
    echo "refusing rail overlay while SGLang session is running: $session" >&2
    exit 1
  fi
done
if ss -ltn | grep -Eq ':(31001|31002) '; then
  echo "refusing rail overlay while SGLang port is listening" >&2
  exit 1
fi

site="$runtime_root/venv/lib/python3.10/site-packages/sglang/srt"
check_sha "$site/mem_cache/base_prefix_cache.py" f40a1aaf5959bbe5abd7c8cfd55cf1d2210fa676a32d76b15baa5a3db67974a2
check_sha "$site/mem_cache/unified_cache_components/full_component.py" cf567ac80479a7de5dee6dbaa0e5eae4590027c794863f5fae6f3cff92f906c9
check_sha "$site/managers/schedule_policy.py" 2c012fa22840afd7355ea20379ea7773ea47280fa465e058131d65c2edce5b1b
check_sha "$site/mem_cache/unified_radix_cache.py" 1180642c8e2c3126650b6219956a9fdd825a6701d4640c300eefdc44dc04512e

inner_dst="$runtime_root/fluxon_f1/start_gpu_stack_owner_tp2x2_f.sh"
wrapper_dst="$runtime_root/launch_fluxon_f_gpu_p9_common2_gpu4567.sh"
support_dst="$runtime_root/p9_common2"
current_inner_sha="$(sha256sum "$inner_dst" | awk '{print $1}')"

if [[ "$action" = rollback ]]; then
  case "$current_inner_sha" in
    "$p9_inner_sha")
      install -m 0755 "$p8_inner" "${inner_dst}.p8.rollback"
      check_sha "${inner_dst}.p8.rollback" "$p8_inner_sha"
      mv -f "${inner_dst}.p8.rollback" "$inner_dst"
      ;;
    "$p8_inner_sha") ;;
    *) echo "unexpected inner launcher SHA before rollback: $current_inner_sha" >&2; exit 1 ;;
  esac
  check_sha "$inner_dst" "$p8_inner_sha"
  printf 'P9_COMMON2_ROLLBACK_OK inner=%s runtime=%s\n' "$p8_inner_sha" "$runtime_root"
  exit 0
fi

case "$current_inner_sha" in
  "$p8_inner_sha")
    install -m 0755 "$p9_inner" "${inner_dst}.p9.new"
    check_sha "${inner_dst}.p9.new" "$p9_inner_sha"
    mv -f "${inner_dst}.p9.new" "$inner_dst"
    ;;
  "$p9_inner_sha") ;;
  *) echo "unexpected inner launcher SHA before install: $current_inner_sha" >&2; exit 1 ;;
esac

install -m 0755 "$p9_wrapper" "${wrapper_dst}.new"
check_sha "${wrapper_dst}.new" "$p9_wrapper_sha"
mv -f "${wrapper_dst}.new" "$wrapper_dst"

support_tmp="${support_dst}.new.$$"
test ! -e "$support_tmp"
mkdir -m 0755 "$support_tmp"
install -m 0444 "$p9_replayer" "$support_tmp/mooncake_trace_replay_p9_common2.py"
install -m 0444 "$p9_finalizer" "$support_tmp/finalize_fluxon_f_capacity_p9_common2.py"
install -m 0444 "$p9_manifest" "$support_tmp/OVERLAY.json"
if [[ -e "$support_dst" ]]; then
  check_sha "$support_dst/mooncake_trace_replay_p9_common2.py" "$p9_replayer_sha"
  check_sha "$support_dst/finalize_fluxon_f_capacity_p9_common2.py" "$p9_finalizer_sha"
  check_sha "$support_dst/OVERLAY.json" "$p9_manifest_sha"
  rm -rf "$support_tmp"
else
  mv "$support_tmp" "$support_dst"
fi

check_sha "$inner_dst" "$p9_inner_sha"
check_sha "$wrapper_dst" "$p9_wrapper_sha"
check_sha "$support_dst/mooncake_trace_replay_p9_common2.py" "$p9_replayer_sha"
check_sha "$support_dst/finalize_fluxon_f_capacity_p9_common2.py" "$p9_finalizer_sha"
check_sha "$support_dst/OVERLAY.json" "$p9_manifest_sha"
printf 'P9_COMMON2_OVERLAY_OK inner=%s wrapper=%s replayer=%s runtime=%s\n' \
  "$p9_inner_sha" "$p9_wrapper_sha" "$p9_replayer_sha" "$runtime_root"
