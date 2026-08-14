#!/usr/bin/env bash
set -euo pipefail

cmd="${1:?missing command: wait-etcd | wait-member | wait-transfer-ready}"
member_id="${2:-}"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
timeout="${TIMEOUT:-120}"
cluster="${FLUXON_CLUSTER_NAME:-${FLUXON_EXTERNAL_CLUSTER_NAME:-fluxon-sglang-l13-single}}"

endpoint="${ETCD_ENDPOINT:-}"
if [ -z "$endpoint" ]; then
  raw="${FLUXON_ETCD_FULL_ADDRESS:-10.233.114.139:34579}"
  case "$raw" in
    http://*|https://*) endpoint="$raw" ;;
    *) endpoint="http://$raw" ;;
  esac
fi

etcdctl="${ETCDCTL:-$script_dir/fluxon_release/ext_images/etcd/etcdctl}"

require_etcdctl() {
  if [ ! -x "$etcdctl" ]; then
    echo "missing etcdctl: $etcdctl" >&2
    exit 1
  fi
}

etcd_get() {
  ETCDCTL_API=3 "$etcdctl" --endpoints="$endpoint" get "$1" --print-value-only 2>/dev/null || true
}

wait_until() {
  local label="$1"
  shift
  local deadline=$(( $(date +%s) + timeout ))
  until "$@"; do
    if [ "$(date +%s)" -ge "$deadline" ]; then
      echo "timeout waiting for $label after ${timeout}s endpoint=$endpoint cluster=$cluster" >&2
      exit 1
    fi
    sleep 1
  done
  echo "ready: $label"
}

is_etcd_ready() {
  ETCDCTL_API=3 "$etcdctl" --endpoints="$endpoint" endpoint health >/dev/null 2>&1
}

is_member_ready() {
  local key="/fluxon_commu_member_base/$cluster/members/$member_id"
  [ -n "$(etcd_get "$key")" ]
}

is_transfer_ready() {
  local key="/fluxon_commu_member_ext/$cluster/members/$member_id/transfer_ready"
  [ -n "$(etcd_get "$key")" ]
}

main() {
  require_etcdctl
  case "$cmd" in
    wait-etcd)
      wait_until "etcd" is_etcd_ready
      ;;
    wait-member)
      if [ -z "$member_id" ]; then
        echo "wait-member requires member id" >&2
        exit 2
      fi
      wait_until "member $member_id" is_member_ready
      ;;
    wait-transfer-ready)
      if [ -z "$member_id" ]; then
        echo "wait-transfer-ready requires member id" >&2
        exit 2
      fi
      wait_until "transfer_ready $member_id" is_transfer_ready
      ;;
    *)
      echo "unsupported command: $cmd" >&2
      exit 2
      ;;
  esac
}

main "$@"
