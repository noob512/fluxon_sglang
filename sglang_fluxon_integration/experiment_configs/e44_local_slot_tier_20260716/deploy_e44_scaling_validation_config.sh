#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
deployment_id="${1:?usage: $0 UNIQUE_DEPLOYMENT_ID}"
host=116.238.240.2
key=/home/zyc/.ssh/infra44_ed25519
port0=32656
port1=30245
port_cpu=30729
target=/storage/mjq/sglang_fluxon/fluxon_f1/e44_local_slot_tier_20260716
remote_parent=/storage/mjq/sglang_fluxon/deploy_staging
remote_stage="$remote_parent/$deployment_id"
local_stage="/mnt/nvme0/mjq_build/${deployment_id}_stage"
archive="/mnt/nvme0/mjq_build/${deployment_id}.tar.gz"
files=(
  launch_stable_session_proxy_e44_scaling_w1.sh
  run_workload_e44_scaling_s48_c12_w1.sh
)

if [[ ! "$deployment_id" =~ ^[a-zA-Z0-9_]+$ ]]; then
  echo "invalid deployment id: $deployment_id" >&2
  exit 2
fi
test "$(findmnt -n -o SOURCE -T /mnt/nvme0/mjq_build)" = /dev/nvme0n1p3

ssh_common=(
  -o BatchMode=yes
  -o StrictHostKeyChecking=no
  -o ConnectTimeout=15
  -i "$key"
)

remote() {
  local port="$1"
  shift
  ssh "${ssh_common[@]}" -p "$port" "root@$host" "$@"
}

cleanup() {
  local rc=$?
  set +e
  remote "$port0" "rm -rf '$remote_stage' '${remote_stage}.tar.gz'" >/dev/null 2>&1 || true
  rm -rf "$local_stage" "$archive"
  return "$rc"
}
trap cleanup EXIT INT TERM

rm -rf "$local_stage" "$archive"
mkdir -p "$local_stage"
for file in "${files[@]}"; do
  install -m 755 "$script_dir/$file" "$local_stage/$file"
done
(
  cd "$local_stage"
  sha256sum "${files[@]}" > transport.sha256
)
tar -czf "$archive" -C "$local_stage" .
archive_sha256="$(sha256sum "$archive" | cut -d' ' -f1)"

remote "$port0" "
  set -euo pipefail
  rm -rf '$remote_stage' '${remote_stage}.tar.gz'
  mkdir -p '$remote_parent'
"
scp "${ssh_common[@]}" -P "$port0" "$archive" "root@$host:${remote_stage}.tar.gz"
remote "$port0" "
  set -euo pipefail
  test \"\$(sha256sum '${remote_stage}.tar.gz' | cut -d' ' -f1)\" = '$archive_sha256'
  mkdir -p '$remote_stage'
  tar -xzf '${remote_stage}.tar.gz' -C '$remote_stage'
  cd '$remote_stage'
  sha256sum -c transport.sha256
"

# /storage is shared: node1 and CPU validate the same staged bytes instead of
# receiving a second public or internal copy.
for port in "$port1" "$port_cpu"; do
  remote "$port" "
    set -euo pipefail
    test -d '$remote_stage'
    cd '$remote_stage'
    sha256sum -c transport.sha256
  "
done

remote "$port0" "
  set -euo pipefail
  install -d -m 755 '$target'
  install -m 755 '$remote_stage/${files[0]}' '$target/${files[0]}'
  install -m 755 '$remote_stage/${files[1]}' '$target/${files[1]}'
"
for port in "$port0" "$port1" "$port_cpu"; do
  remote "$port" "
    set -euo pipefail
    cd '$target'
    test \"\$(sha256sum '${files[0]}' | cut -d' ' -f1)\" = 078e9fc6786d72f931ee4872a0056679ebcf46b9bd89196a22801b34df7d5cc0
    test \"\$(sha256sum '${files[1]}' | cut -d' ' -f1)\" = 94a7b6c83e991f17b0289015c7deec6ee62df9d3492885ef7ba3570d40c5d20d
    printf 'verified host=%s stage=%s target=%s\n' \"\$(hostname)\" '$remote_stage' '$target'
  "
done
printf 'deployment_id=%s archive_sha256=%s node0_uploads=1 node1_uploads=0 cpu_uploads=0 ext_images_transport=0\n' \
  "$deployment_id" "$archive_sha256"
