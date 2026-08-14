#!/usr/bin/env bash
set -euo pipefail

workspace=/mnt/ceph/mjq/push_sglang
experiment="$workspace/experiment_configs/e44_local_slot_tier_20260716"
gpu_release="${E44_DEPLOY_GPU_RELEASE:-/mnt/nvme0/mjq_build/fluxon_e44_r47_gpu_direct_post_binding_intra_ready_20260721}"
cpu_release="${E44_DEPLOY_CPU_RELEASE:-/mnt/nvme0/mjq_build/fluxon_e44_r47_gpu_direct_full_cpu_host_20260721}"
gpu_remote_release="${E44_DEPLOY_GPU_REMOTE_RELEASE:-/storage/mjq/sglang_fluxon/releases/fluxon_e44_r47_gpu_direct_full_enddepth288_netobs_20260721}"
cpu_remote_release="${E44_DEPLOY_CPU_REMOTE_RELEASE:-/storage/mjq/sglang_fluxon/releases/fluxon_e44_r47_cpu_host_full_enddepth288_netobs_20260721}"
gpu_venv="${E44_DEPLOY_GPU_VENV:-/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r47-gpu-direct-full-enddepth288-netobs-20260721}"
cpu_venv="${E44_DEPLOY_CPU_VENV:-/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r47-gpu-direct-full-cpu-host-20260721}"
cpu_python="${E44_DEPLOY_CPU_PYTHON:-}"
cpu_python_version="${E44_DEPLOY_CPU_PYTHON_VERSION:-}"
cpu_dependency_site="${E44_DEPLOY_CPU_DEPENDENCY_SITE:-}"
tool_root=/mnt/nvme0/mjq_build/e44_r28_netobs_tools_jammy/root
stage_parent="${E44_DEPLOY_STAGE_PARENT:-/mnt/nvme0/mjq_build/e44_two_stage_deploy}"
host="${E44_DEPLOY_HOST:-116.238.240.2}"
node0_port="${E44_DEPLOY_NODE0_PORT:-32656}"
node1_port="${E44_DEPLOY_NODE1_PORT:-30245}"
cpu_port="${E44_DEPLOY_CPU_PORT:-30729}"
internal_ssh_port="${E44_DEPLOY_INTERNAL_SSH_PORT:-2222}"
wheel_name="${E44_DEPLOY_WHEEL_NAME:-fluxon-0.2.1-cp38-abi3-manylinux_2_28_x86_64.whl}"
variant="${E44_DEPLOY_VARIANT:-tier1_independent_005_netobs_enddepth288_gpu_direct_r47}"
master_config="${E44_DEPLOY_MASTER_CONFIG:-master_config_e44_r47_gpu_direct_full_enddepth288_netobs.yaml}"
ssh_identity="${E44_DEPLOY_SSH_IDENTITY:-}"
gpu_ext_seed="${E44_DEPLOY_GPU_EXT_IMAGES_SEED_RELEASE:-/storage/mjq/sglang_fluxon/releases/fluxon_e44_r51_metadata_only_plan_gpu_20260723}"
cpu_ext_seed="${E44_DEPLOY_CPU_EXT_IMAGES_SEED_RELEASE:-/storage/mjq/sglang_fluxon/releases/fluxon_e44_r51_metadata_only_plan_cpu_20260723}"
existing_remote_stage="${E44_DEPLOY_EXISTING_REMOTE_STAGE:-}"
debug_node_install="${E44_DEPLOY_DEBUG_NODE_INSTALL:-0}"
allowed_active_runtime_root="${E44_DEPLOY_ALLOWED_ACTIVE_RUNTIME_ROOT:-}"

expected_host_patch_sha256=482a276e701c4fdd3c44654ff6c8e2403ee59fdb671513db61c62532a9b1c878
expected_radix_sha256="${E44_DEPLOY_EXPECTED_RADIX_SHA256:-2139404e489268fe5803d19f7be585020359a8351d4b1683733e4cb5ace9deb6}"
expected_adapter_sha256="${E44_DEPLOY_EXPECTED_ADAPTER_SHA256:-574c23041a4c185e52b5f67c98a4486138bf869639842786d2d3cf1453c5520c}"
radix_source="${E44_DEPLOY_RADIX_SOURCE:-unified_radix_cache_e44_r42_gpu_direct_staging.py}"
adapter_source="${E44_DEPLOY_ADAPTER_SOURCE:-hicache_fluxon_e44_r42_gpu_direct_staging.py}"
scheduler_source="${E44_DEPLOY_SCHEDULER_SOURCE:-}"
timeline_validator="${E44_DEPLOY_TIMELINE_VALIDATOR:-}"
expected_scheduler_sha256="${E44_DEPLOY_EXPECTED_SCHEDULER_SHA256:-}"
expected_schedule_batch_sha256="${E44_DEPLOY_EXPECTED_SCHEDULE_BATCH_SHA256:-}"
preserve_installed_sglang="${E44_DEPLOY_PRESERVE_INSTALLED_SGLANG:-0}"
expected_perfquery_sha256=42c32fd2b92022754a6be5cf5f3e490c54413ddba05962c82cc4473795cbbc58
gpu_stack_launcher_rel=e16bb_rdma_numa1_20260714/start_gpu_stack_owner_numa1.sh
expected_gpu_stack_launcher_sha256="$(sha256sum "$workspace/experiment_configs/$gpu_stack_launcher_rel" | awk '{print $1}')"

usage() {
  echo "usage: $0 [all|node0|node1|cpu]" >&2
}

mode="${1:-all}"
case "$mode" in
  all | node0 | node1 | cpu) ;;
  *) usage; exit 2 ;;
esac
case "$debug_node_install" in
  0 | 1) ;;
  *) echo "E44_DEPLOY_DEBUG_NODE_INSTALL must be 0 or 1" >&2; exit 2 ;;
esac
case "$preserve_installed_sglang" in
  0 | 1) ;;
  *) echo "E44_DEPLOY_PRESERVE_INSTALLED_SGLANG must be 0 or 1" >&2; exit 2 ;;
esac
if [ "$preserve_installed_sglang" = 1 ]; then
  test -n "$expected_scheduler_sha256"
  test -n "$expected_schedule_batch_sha256"
fi
if [ -n "$cpu_python" ]; then
  if [[ "$cpu_python" != /* ]] || [[ ! "$cpu_python_version" =~ ^[0-9]+\.[0-9]+$ ]]; then
    echo "CPU Python override requires an absolute interpreter and major.minor version" >&2
    exit 2
  fi
fi

if [ -z "$ssh_identity" ] || [ ! -f "$ssh_identity" ]; then
  echo "two-stage deploy requires E44_DEPLOY_SSH_IDENTITY to name a readable private key" >&2
  exit 2
fi

for path in "$gpu_release" "$cpu_release" "$tool_root"; do
  test "$(findmnt -n -o SOURCE -T "$path")" = /dev/nvme0n1p3
done
mkdir -p "$stage_parent"
test "$(findmnt -n -o SOURCE -T "$stage_parent")" = /dev/nvme0n1p3

gpu_wheel="$gpu_release/$wheel_name"
cpu_wheel="$cpu_release/$wheel_name"
test -f "$gpu_wheel"
test -f "$cpu_wheel"

wheel_member_sha256() {
  local wheel="$1"
  local member="$2"
  unzip -p "$wheel" "$member" | sha256sum | awk '{print $1}'
}

manifest_sha256() {
  local release="$1"
  local member="$2"
  awk -v member="$member" '$2 == member { print $1 }' "$release/fluxon_release.sha256"
}

gpu_pyo3_sha256="$(tr -d '[:space:]' < "$gpu_release/fluxon_pyo3.abi3.so.sha256")"
cpu_pyo3_sha256="$(tr -d '[:space:]' < "$cpu_release/fluxon_pyo3.abi3.so.sha256")"
gpu_core_sha256="$(wheel_member_sha256 "$gpu_wheel" 'fluxon_pyo3.libs/libfluxon_commu_core.so')"
gpu_probe_sha256="$(wheel_member_sha256 "$gpu_wheel" 'fluxon_pyo3.libs/libfluxon_rdma_probe.so')"
gpu_cudart_sha256="$(wheel_member_sha256 "$gpu_wheel" 'fluxon_pyo3.libs/libcudart.so.12')"
cpu_core_sha256="$(wheel_member_sha256 "$cpu_wheel" 'fluxon_pyo3.libs/libfluxon_commu_core.so')"
cpu_probe_sha256="$(wheel_member_sha256 "$cpu_wheel" 'fluxon_pyo3.libs/libfluxon_rdma_probe.so')"
expected_ext_images_sha256="$(manifest_sha256 "$gpu_release" ext_images.tar.gz)"
cpu_ext_images_sha256="$(manifest_sha256 "$cpu_release" ext_images.tar.gz)"
expected_ext_manifest_sha256="$(sha256sum "$gpu_release/ext_images/ext_images.sha256" | awk '{print $1}')"
cpu_ext_manifest_sha256="$(sha256sum "$cpu_release/ext_images/ext_images.sha256" | awk '{print $1}')"

test -n "$gpu_pyo3_sha256"
test -n "$cpu_pyo3_sha256"
test -n "$gpu_core_sha256"
test -n "$cpu_core_sha256"
test -n "$expected_ext_images_sha256"
test "$expected_ext_images_sha256" = "$cpu_ext_images_sha256"
test "$expected_ext_manifest_sha256" = "$cpu_ext_manifest_sha256"
! unzip -Z1 "$cpu_wheel" | grep -Eq 'libcuda|libcudart'

common_files=(
  deploy_e44_two_stage_node_install.sh
  e44_v5_perf_variant_20260718.sh
  install_release_e44_r38_get_prefix_reuse.sh
  "$master_config"
  "$radix_source"
  "$adapter_source"
  validate_e44_r42_gpu_direct_staging.py
  smoke_e44_r42_gpu_get.py
  smoke_e44_r50_plan_bind.py
  smoke_e44_r52_mixed_source.py
  smoke_e44_r55_planned_cpu_stress.py
  control_fluxon_node_pool_capacity.py
  cpu_interference_guard_e44.sh
  launch_master_e44_r43_gpu_get_smoke.sh
  launch_owner_e44_r43_gpu_get_smoke.sh
  master_config_e44_r42_gpu_get_smoke.yaml
  fluxon_wait_ready.sh
  start_control_e44_v5_perf.sh
  launch_master_e44_v5_perf.sh
  launch_gpu_e44_r28_netobs.sh
  launch_gpu_e44_r38_guarded.sh
  launch_cpu_e44_r28_netobs.sh
  launch_router_e44_v5_perf.sh
  launch_stable_session_proxy_e44.sh
  launch_stable_session_proxy_e44_scaling_w1.sh
  stable_session_proxy_e44.py
  run_workload_e44_r28_netobs.sh
  run_workload_e44_scaling_s48_c12_w1.sh
  run_workload_fast25_multilevel.sh
  cluster_e44_r11.env
  hca_observer_e44_r28.py
  manage_hca_observer_e44_r28.sh
  analyze_hca_observer_e44_r28.py
  analyze_e44_r54_prefetch_timeline.py
  validate_e44_r61_tp_execute_commit.py
  validate_e44_r92_gdr_off_parallel_backing.py
  validate_e44_r133_device_headroom.py
  smoke_e44_r133_device_headroom.py
  prepare_greptime_e44_r28.py
  import_hca_observer_to_greptime_e44_r28.py
)
if [ -n "$scheduler_source" ]; then
  test -n "$timeline_validator"
  test -n "$expected_scheduler_sha256"
  common_files+=("$scheduler_source" "$timeline_validator")
fi
for file in "${common_files[@]}"; do
  test -f "$experiment/$file"
done

local_stage="$(mktemp -d "$stage_parent/e44_two_stage.XXXXXXXX")"
agent_started=0
cleanup() {
  local rc=$?
  rm -rf -- "$local_stage"
  if [ "$agent_started" = 1 ]; then
    ssh-agent -k >/dev/null 2>&1 || true
  fi
  return "$rc"
}
trap cleanup EXIT

eval "$(ssh-agent -s)" >/dev/null
agent_started=1
ssh-add "$ssh_identity" >/dev/null

ssh_common=(-o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=15 -i "$ssh_identity" -o IdentitiesOnly=yes)
scp_common=(-q -o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=15 -i "$ssh_identity" -o IdentitiesOnly=yes)
node0_ssh=(ssh -A "${ssh_common[@]}" -p "$node0_port" "root@$host")
node0_scp=(scp "${scp_common[@]}" -P "$node0_port")
internal_ssh=(ssh -o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=15 -p "$internal_ssh_port")

gpu_archive=gpu_release.delta.tar.gz
cpu_archive=cpu_release.delta.tar.gz
common_archive=common_files.tar.gz
tools_archive=netobs_tools.tar.gz
gpu_transport_manifest=gpu_transport.sha256
cpu_transport_manifest=cpu_transport.sha256

pack_release_delta() {
  local release="$1"
  local output="$2"
  tar -czf "$output" -C "$release" \
    --exclude='./ext_images' \
    --exclude='./ext_images.tar.gz' \
    .
  if tar -tzf "$output" | grep -Eq '(^|/)(ext_images|ext_images\.tar\.gz)(/|$)'; then
    echo "local delta archive contains forbidden ext_images payload: $output" >&2
    exit 1
  fi
}

need_gpu=0
need_cpu=0
case "$mode" in
  all) need_gpu=1; need_cpu=1 ;;
  node0 | node1) need_gpu=1 ;;
  cpu) need_cpu=1 ;;
esac

if [ "$need_gpu" = 1 ]; then
  pack_release_delta "$gpu_release" "$local_stage/$gpu_archive"
fi
if [ "$need_cpu" = 1 ]; then
  pack_release_delta "$cpu_release" "$local_stage/$cpu_archive"
fi
tar -czf "$local_stage/$common_archive" \
  -C "$experiment" "${common_files[@]}" \
  -C "$workspace/experiment_configs" "$gpu_stack_launcher_rel"
tar -czf "$local_stage/$tools_archive" \
  -C "$tool_root/usr/sbin" perfquery \
  -C "$tool_root/usr/lib/x86_64-linux-gnu" \
  libibmad.so.5.3.39.0 libibumad.so.3.2.39.0

if [ "$need_gpu" = 1 ]; then
  (
    cd "$local_stage"
    sha256sum "$gpu_archive" "$common_archive" "$tools_archive" > "$gpu_transport_manifest"
  )
fi
if [ "$need_cpu" = 1 ]; then
  (
    cd "$local_stage"
    sha256sum "$cpu_archive" "$common_archive" "$tools_archive" > "$cpu_transport_manifest"
  )
fi

discover_internal_host() {
  local explicit="$1"
  local public_port="$2"
  local candidate
  if [ -n "$explicit" ]; then
    candidate="$explicit"
  else
    candidate="$(ssh "${ssh_common[@]}" -p "$public_port" "root@$host" hostname -I | \
      awk '{ for (i = 1; i <= NF; i++) if ($i ~ /^10\./) { print $i; exit } }')"
  fi
  if [[ ! "$candidate" =~ ^10\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "failed to discover a private IPv4 address through public port $public_port: $candidate" >&2
    exit 1
  fi
  printf '%s\n' "$candidate"
}

verify_internal_identity() {
  local public_port="$1"
  local internal_host="$2"
  local public_name internal_name
  public_name="$(ssh "${ssh_common[@]}" -p "$public_port" "root@$host" hostname)"
  internal_name="$("${node0_ssh[@]}" "${internal_ssh[@]}" "root@$internal_host" hostname)"
  if [ "$public_name" != "$internal_name" ]; then
    echo "internal endpoint identity mismatch: public=$public_name internal=$internal_name host=$internal_host" >&2
    exit 1
  fi
  printf 'internal_endpoint=verified public_port=%s private=%s host=%s\n' \
    "$public_port" "$internal_host" "$public_name"
}

node1_internal_host=
cpu_internal_host=
if [ "$mode" = all ] || [ "$mode" = node1 ]; then
  node1_internal_host="$(discover_internal_host "${E44_DEPLOY_NODE1_INTERNAL_HOST:-}" "$node1_port")"
  verify_internal_identity "$node1_port" "$node1_internal_host"
fi
if [ "$mode" = all ] || [ "$mode" = cpu ]; then
  cpu_internal_host="$(discover_internal_host "${E44_DEPLOY_CPU_INTERNAL_HOST:-}" "$cpu_port")"
  verify_internal_identity "$cpu_port" "$cpu_internal_host"
fi

deployment_stage_reused=0
if [ -n "$existing_remote_stage" ]; then
  case "$existing_remote_stage" in
    /storage/mjq/sglang_fluxon/deploy_staging/e44_*) ;;
    *)
      echo "refusing existing deployment stage outside the sealed stage root: $existing_remote_stage" >&2
      exit 2
      ;;
  esac
  remote_stage="$existing_remote_stage"
  "${node0_ssh[@]}" test -d "$remote_stage"
  deployment_stage_reused=1
else
  deployment_id="e44_${variant}_$(date +%Y%m%d%H%M%S)_$$"
  remote_stage="/storage/mjq/sglang_fluxon/deploy_staging/$deployment_id"
  "${node0_ssh[@]}" mkdir -p "$remote_stage"
fi

upload_files=("$local_stage/$common_archive" "$local_stage/$tools_archive")
if [ "$need_gpu" = 1 ]; then
  upload_files+=("$local_stage/$gpu_archive" "$local_stage/$gpu_transport_manifest")
fi
if [ "$need_cpu" = 1 ]; then
  upload_files+=("$local_stage/$cpu_archive" "$local_stage/$cpu_transport_manifest")
fi
# This is the only public-network payload transfer in the deployment.
public_payload_bytes=0
if [ "$deployment_stage_reused" = 0 ]; then
  for file in "${upload_files[@]}"; do
    public_payload_bytes=$((public_payload_bytes + $(stat -c %s "$file")))
  done
  "${node0_scp[@]}" "${upload_files[@]}" "root@$host:$remote_stage/"
else
  # A failed install may be retried from the exact already-uploaded shared
  # stage. Never upload the payload a second time; the per-target transport
  # and complete release manifests below remain mandatory.
  for file in "${upload_files[@]}"; do
    "${node0_ssh[@]}" test -f "$remote_stage/$(basename "$file")"
  done
fi

if [ "$need_gpu" = 1 ]; then
  "${node0_ssh[@]}" \
    "cd '$remote_stage' && sha256sum -c '$gpu_transport_manifest' >/dev/null"
fi
if [ "$need_cpu" = 1 ]; then
  "${node0_ssh[@]}" \
    "cd '$remote_stage' && sha256sum -c '$cpu_transport_manifest' >/dev/null"
fi

bootstrap_worker_local() {
  "${node0_ssh[@]}" tar -xzf "$remote_stage/$common_archive" -C "$remote_stage" \
    deploy_e44_two_stage_node_install.sh
}

fanout_archives() {
  local internal_host="$1"
  local release_archive="$2"
  local transport_manifest="$3"
  local result_var="$4"
  local shared_stage=0
  local payload_bytes
  "${node0_ssh[@]}" "${internal_ssh[@]}" "root@$internal_host" mkdir -p "$remote_stage"
  if "${node0_ssh[@]}" "${internal_ssh[@]}" "root@$internal_host" \
    test -f "$remote_stage/$release_archive"; then
    # node0 and this target see the same storage-backed stage. Re-reading and
    # hashing it on the target is sufficient; an scp onto the same inode is both
    # redundant and potentially destructive.
    shared_stage=1
    payload_bytes=0
  else
    echo "shared deployment stage is not visible on target $internal_host; refusing redundant internal scp" >&2
    return 1
  fi
  "${node0_ssh[@]}" "${internal_ssh[@]}" "root@$internal_host" \
    tar -xzf "$remote_stage/$common_archive" -C "$remote_stage" \
    deploy_e44_two_stage_node_install.sh
  printf -v "$result_var" '%s' "$shared_stage"
  printf 'internal_fanout_target=%s shared_stage=%s payload_bytes=%s\n' \
    "$internal_host" "$shared_stage" "$payload_bytes"
}

run_node0_install() {
  local installer=(bash)
  if [ "$debug_node_install" = 1 ]; then
    installer+=( -x )
  fi
  local env_args=(
    E44_NODE_ROLE=gpu
    E44_NODE_ROOT_NAME=fluxon_f1
    E44_NODE_REMOTE_RELEASE="$gpu_remote_release"
    E44_NODE_VENV="$gpu_venv"
    E44_NODE_VARIANT="$variant"
    E44_NODE_MASTER_CONFIG="$master_config"
    E44_NODE_RELEASE_ARCHIVE="$gpu_archive"
    E44_NODE_COMMON_ARCHIVE="$common_archive"
    E44_NODE_TOOLS_ARCHIVE="$tools_archive"
    E44_NODE_TRANSPORT_MANIFEST="$gpu_transport_manifest"
    E44_NODE_EXT_IMAGES_SEED_RELEASE="$gpu_ext_seed"
    E44_NODE_EXPECTED_EXT_IMAGES_SHA256="$expected_ext_images_sha256"
    E44_NODE_EXPECTED_EXT_MANIFEST_SHA256="$expected_ext_manifest_sha256"
    E44_NODE_WHEEL_NAME="$wheel_name"
    E44_NODE_EXPECTED_PYO3_SHA256="$gpu_pyo3_sha256"
    E44_NODE_EXPECTED_CORE_SHA256="$gpu_core_sha256"
    E44_NODE_EXPECTED_PROBE_SHA256="$gpu_probe_sha256"
    E44_NODE_EXPECTED_CUDART_SHA256="$gpu_cudart_sha256"
    E44_NODE_EXPECTED_PERFQUERY_SHA256="$expected_perfquery_sha256"
    E44_NODE_EXPECTED_HOST_PATCH_SHA256="$expected_host_patch_sha256"
    E44_NODE_EXPECTED_RADIX_SHA256="$expected_radix_sha256"
    E44_NODE_EXPECTED_ADAPTER_SHA256="$expected_adapter_sha256"
    E44_NODE_EXPECTED_GPU_STACK_LAUNCHER_SHA256="$expected_gpu_stack_launcher_sha256"
    E44_NODE_RADIX_SOURCE="$radix_source"
    E44_NODE_ADAPTER_SOURCE="$adapter_source"
    E44_NODE_SCHEDULER_SOURCE="$scheduler_source"
    E44_NODE_TIMELINE_VALIDATOR="$timeline_validator"
    E44_NODE_EXPECTED_SCHEDULER_SHA256="$expected_scheduler_sha256"
    E44_NODE_EXPECTED_SCHEDULE_BATCH_SHA256="$expected_schedule_batch_sha256"
    E44_NODE_PRESERVE_INSTALLED_SGLANG="$preserve_installed_sglang"
    E44_NODE_ALLOWED_ACTIVE_RUNTIME_ROOT="$allowed_active_runtime_root"
  )
  "${node0_ssh[@]}" env "${env_args[@]}" \
    "${installer[@]}" "$remote_stage/deploy_e44_two_stage_node_install.sh" "$remote_stage"
}

run_internal_install() {
  local internal_host="$1"
  local role="$2"
  local root_name="$3"
  local remote_release="$4"
  local venv="$5"
  local release_archive="$6"
  local transport_manifest="$7"
  local ext_seed="$8"
  local expected_pyo3="$9"
  local expected_core="${10}"
  local expected_probe="${11}"
  local expected_cudart="${12}"
  local reuse_materialized_release="${13}"
  local installer=(bash)
  if [ "$debug_node_install" = 1 ]; then
    installer+=( -x )
  fi
  local env_args=(
    E44_NODE_ROLE="$role"
    E44_NODE_ROOT_NAME="$root_name"
    E44_NODE_REMOTE_RELEASE="$remote_release"
    E44_NODE_VENV="$venv"
    E44_NODE_VARIANT="$variant"
    E44_NODE_MASTER_CONFIG="$master_config"
    E44_NODE_RELEASE_ARCHIVE="$release_archive"
    E44_NODE_COMMON_ARCHIVE="$common_archive"
    E44_NODE_TOOLS_ARCHIVE="$tools_archive"
    E44_NODE_TRANSPORT_MANIFEST="$transport_manifest"
    E44_NODE_EXT_IMAGES_SEED_RELEASE="$ext_seed"
    E44_NODE_EXPECTED_EXT_IMAGES_SHA256="$expected_ext_images_sha256"
    E44_NODE_EXPECTED_EXT_MANIFEST_SHA256="$expected_ext_manifest_sha256"
    E44_NODE_WHEEL_NAME="$wheel_name"
    E44_NODE_EXPECTED_PYO3_SHA256="$expected_pyo3"
    E44_NODE_EXPECTED_CORE_SHA256="$expected_core"
    E44_NODE_EXPECTED_PROBE_SHA256="$expected_probe"
    E44_NODE_EXPECTED_CUDART_SHA256="$expected_cudart"
    E44_NODE_EXPECTED_PERFQUERY_SHA256="$expected_perfquery_sha256"
    E44_NODE_EXPECTED_HOST_PATCH_SHA256="$expected_host_patch_sha256"
    E44_NODE_EXPECTED_RADIX_SHA256="$expected_radix_sha256"
    E44_NODE_EXPECTED_ADAPTER_SHA256="$expected_adapter_sha256"
    E44_NODE_EXPECTED_GPU_STACK_LAUNCHER_SHA256="$expected_gpu_stack_launcher_sha256"
    E44_NODE_RADIX_SOURCE="$radix_source"
    E44_NODE_ADAPTER_SOURCE="$adapter_source"
    E44_NODE_SCHEDULER_SOURCE="$scheduler_source"
    E44_NODE_TIMELINE_VALIDATOR="$timeline_validator"
    E44_NODE_EXPECTED_SCHEDULER_SHA256="$expected_scheduler_sha256"
    E44_NODE_EXPECTED_SCHEDULE_BATCH_SHA256="$expected_schedule_batch_sha256"
    E44_NODE_PRESERVE_INSTALLED_SGLANG="$preserve_installed_sglang"
    E44_NODE_REUSE_MATERIALIZED_RELEASE="$reuse_materialized_release"
    E44_NODE_ALLOWED_ACTIVE_RUNTIME_ROOT="$allowed_active_runtime_root"
  )
  if [ "$role" = cpu ] && [ -n "$cpu_python" ]; then
    env_args+=(
      E44_NODE_CPU_PYTHON="$cpu_python"
      E44_NODE_CPU_PYTHON_VERSION="$cpu_python_version"
      E44_NODE_CPU_DEPENDENCY_SITE="$cpu_dependency_site"
    )
  fi
  "${node0_ssh[@]}" "${internal_ssh[@]}" "root@$internal_host" \
    env "${env_args[@]}" \
    "${installer[@]}" "$remote_stage/deploy_e44_two_stage_node_install.sh" "$remote_stage"
}

bootstrap_worker_local
node1_shared_stage=0
cpu_shared_stage=0
if [ "$mode" = all ] || [ "$mode" = node1 ]; then
  fanout_archives "$node1_internal_host" "$gpu_archive" "$gpu_transport_manifest" \
    node1_shared_stage
fi
if [ "$mode" = all ] || [ "$mode" = cpu ]; then
  fanout_archives "$cpu_internal_host" "$cpu_archive" "$cpu_transport_manifest" \
    cpu_shared_stage
fi

if [ "$mode" = all ] || [ "$mode" = node0 ]; then
  run_node0_install
fi
if [ "$mode" = all ] || [ "$mode" = node1 ]; then
  node1_reuse_release=0
  if [ "$mode" = all ]; then
    node1_reuse_release="$node1_shared_stage"
  fi
  run_internal_install "$node1_internal_host" gpu fluxon_f2 \
    "$gpu_remote_release" "$gpu_venv" "$gpu_archive" "$gpu_transport_manifest" \
    "$gpu_ext_seed" "$gpu_pyo3_sha256" "$gpu_core_sha256" "$gpu_probe_sha256" \
    "$gpu_cudart_sha256" "$node1_reuse_release"
fi
if [ "$mode" = all ] || [ "$mode" = cpu ]; then
  run_internal_install "$cpu_internal_host" cpu fluxon_cpu \
    "$cpu_remote_release" "$cpu_venv" "$cpu_archive" "$cpu_transport_manifest" \
    "$cpu_ext_seed" "$cpu_pyo3_sha256" "$cpu_core_sha256" "$cpu_probe_sha256" \
    "" 0
fi

if [ "$mode" = all ] || [ "$mode" = node1 ]; then
  "${node0_ssh[@]}" "${internal_ssh[@]}" "root@$node1_internal_host" rm -rf "$remote_stage"
fi
if [ "$mode" = all ] || [ "$mode" = cpu ]; then
  "${node0_ssh[@]}" "${internal_ssh[@]}" "root@$cpu_internal_host" rm -rf "$remote_stage"
fi
"${node0_ssh[@]}" rm -rf "$remote_stage"

printf 'distribution_mode=two_stage_node0_fanout\n'
printf 'deployment_stage_reused=%s\n' "$deployment_stage_reused"
printf 'public_payload_target=%s:%s\n' "$host" "$node0_port"
printf 'public_payload_bytes=%s\n' "$public_payload_bytes"
printf 'ext_images_transport_bytes=0 ext_images_sha256=%s\n' "$expected_ext_images_sha256"
printf 'gpu_pyo3_sha256=%s\n' "$gpu_pyo3_sha256"
printf 'gpu_core_sha256=%s\n' "$gpu_core_sha256"
printf 'gpu_probe_sha256=%s\n' "$gpu_probe_sha256"
printf 'gpu_cudart_sha256=%s\n' "$gpu_cudart_sha256"
printf 'cpu_pyo3_sha256=%s\n' "$cpu_pyo3_sha256"
printf 'cpu_core_sha256=%s\n' "$cpu_core_sha256"
printf 'cpu_probe_sha256=%s\n' "$cpu_probe_sha256"
