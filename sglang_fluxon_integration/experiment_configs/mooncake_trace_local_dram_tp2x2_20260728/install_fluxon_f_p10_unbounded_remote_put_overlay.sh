#!/usr/bin/env bash
set -euo pipefail

payload_dir="${1:?usage: $0 PAYLOAD_DIR}"
runtime_root="${FLUXON_F_RUNTIME_ROOT:-/tmp/fluxon_mooncake_f_f_synrr_r111_l3retry_30448_20260802_2125}"
run_id="${FLUXON_F_RUN_ID:-f_synrr_r111_l3retry_30448_20260802_2125}"

case "$runtime_root" in
  /tmp/fluxon_mooncake_f_*) ;;
  *) echo "invalid runtime root: $runtime_root" >&2; exit 2 ;;
esac
case "$run_id" in
  *[!A-Za-z0-9_]*) echo "invalid run id: $run_id" >&2; exit 2 ;;
esac

test "$(hostname)" = lgsl-a4-5f02-m9-3-h100gpu145
tr ' ' '\n' <<<"$(hostname -I)" | grep -Fx 10.233.90.51 >/dev/null
test "$(findmnt -T /tmp -o FSTYPE -n)" = xfs

p10_wrapper="$payload_dir/launch_fluxon_f_gpu_p10_unbounded_gpu4567.sh"
p10_manifest="$payload_dir/OVERLAY.json"
p10_wrapper_sha=977f94be7a1c4ff9fde6a1be77e586f81991179494e77153f09e6db07494acb8
p10_manifest_sha=3c2c4c6b1b8095bd1a5b1d059aecfb6ee547c300bc1eab1288bdb9799b56a983
p9_wrapper_sha=bdb4b1188b73f7ec59b6575d6578548a9f243e68465ea366fef6e9bb922a3094
p9_inner_sha=4f51091847b12584f180e972053fd4ff8dfbecdfb8aab709ff2700256811c924

check_sha() {
  local path="$1" expected="$2"
  test -f "$path"
  test "$(sha256sum "$path" | awk '{print $1}')" = "$expected"
}

check_sha "$p10_wrapper" "$p10_wrapper_sha"
check_sha "$p10_manifest" "$p10_manifest_sha"
bash -n "$p10_wrapper"

for session in \
  "fluxon_f_${run_id}_owner" \
  "fluxon_f_${run_id}_sglang0" \
  "fluxon_f_${run_id}_sglang1"; do
  if tmux has-session -t "$session" 2>/dev/null; then
    echo "refusing p10 overlay while target session is running: $session" >&2
    exit 1
  fi
done
if ss -ltn | grep -Eq ':(31001|31002) '; then
  echo "refusing p10 overlay while target SGLang port is listening" >&2
  exit 1
fi

p9_wrapper="$runtime_root/launch_fluxon_f_gpu_p9_common2_gpu4567.sh"
p9_inner="$runtime_root/fluxon_f1/start_gpu_stack_owner_tp2x2_f.sh"
check_sha "$p9_wrapper" "$p9_wrapper_sha"
check_sha "$p9_inner" "$p9_inner_sha"

wrapper_dst="$runtime_root/launch_fluxon_f_gpu_p10_unbounded_gpu4567.sh"
support_dst="$runtime_root/p10_unbounded_remote_put"

install -m 0555 "$p10_wrapper" "${wrapper_dst}.new"
check_sha "${wrapper_dst}.new" "$p10_wrapper_sha"
mv -f "${wrapper_dst}.new" "$wrapper_dst"

support_tmp="${support_dst}.new.$$"
test ! -e "$support_tmp"
mkdir -m 0755 "$support_tmp"
install -m 0444 "$p10_manifest" "$support_tmp/OVERLAY.json"
if [[ -e "$support_dst" ]]; then
  check_sha "$support_dst/OVERLAY.json" "$p10_manifest_sha"
  rm -rf "$support_tmp"
else
  mv "$support_tmp" "$support_dst"
fi

check_sha "$wrapper_dst" "$p10_wrapper_sha"
check_sha "$support_dst/OVERLAY.json" "$p10_manifest_sha"
printf 'P10_UNBOUNDED_REMOTE_PUT_OVERLAY_OK wrapper=%s runtime=%s\n' \
  "$p10_wrapper_sha" "$runtime_root"
