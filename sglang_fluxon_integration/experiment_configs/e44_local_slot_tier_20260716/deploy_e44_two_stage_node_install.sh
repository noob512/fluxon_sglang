#!/usr/bin/env bash
set -euo pipefail

stage="${1:?missing node-local transport stage}"

require_env() {
  local name="$1"
  if [ -z "${!name:-}" ]; then
    echo "missing required environment variable: $name" >&2
    exit 2
  fi
}

required_env=(
  E44_NODE_ROLE
  E44_NODE_ROOT_NAME
  E44_NODE_REMOTE_RELEASE
  E44_NODE_VENV
  E44_NODE_VARIANT
  E44_NODE_MASTER_CONFIG
  E44_NODE_RELEASE_ARCHIVE
  E44_NODE_COMMON_ARCHIVE
  E44_NODE_TOOLS_ARCHIVE
  E44_NODE_TRANSPORT_MANIFEST
  E44_NODE_EXT_IMAGES_SEED_RELEASE
  E44_NODE_EXPECTED_EXT_IMAGES_SHA256
  E44_NODE_EXPECTED_EXT_MANIFEST_SHA256
  E44_NODE_WHEEL_NAME
  E44_NODE_EXPECTED_PYO3_SHA256
  E44_NODE_EXPECTED_CORE_SHA256
  E44_NODE_EXPECTED_PROBE_SHA256
  E44_NODE_EXPECTED_PERFQUERY_SHA256
  E44_NODE_EXPECTED_HOST_PATCH_SHA256
  E44_NODE_EXPECTED_RADIX_SHA256
  E44_NODE_EXPECTED_ADAPTER_SHA256
  E44_NODE_EXPECTED_GPU_STACK_LAUNCHER_SHA256
)
for name in "${required_env[@]}"; do
  require_env "$name"
done

radix_source="${E44_NODE_RADIX_SOURCE:-unified_radix_cache_e44_r42_gpu_direct_staging.py}"
adapter_source="${E44_NODE_ADAPTER_SOURCE:-hicache_fluxon_e44_r42_gpu_direct_staging.py}"
scheduler_source="${E44_NODE_SCHEDULER_SOURCE:-}"
timeline_validator="${E44_NODE_TIMELINE_VALIDATOR:-}"
expected_scheduler_sha256="${E44_NODE_EXPECTED_SCHEDULER_SHA256:-}"
expected_schedule_batch_sha256="${E44_NODE_EXPECTED_SCHEDULE_BATCH_SHA256:-}"
preserve_installed_sglang="${E44_NODE_PRESERVE_INSTALLED_SGLANG:-0}"
if [ -n "$scheduler_source" ]; then
  test -n "$timeline_validator"
  test -n "$expected_scheduler_sha256"
fi
case "$preserve_installed_sglang" in
  0 | 1) ;;
  *) echo "E44_NODE_PRESERVE_INSTALLED_SGLANG must be 0 or 1" >&2; exit 2 ;;
esac
if [ "$preserve_installed_sglang" = 1 ]; then
  test -n "$expected_scheduler_sha256"
  test -n "$expected_schedule_batch_sha256"
fi

case "$E44_NODE_ROLE" in
  gpu | cpu) ;;
  *)
    echo "unsupported node role: $E44_NODE_ROLE" >&2
    exit 2
    ;;
esac

root="/storage/mjq/sglang_fluxon/$E44_NODE_ROOT_NAME"
remote_experiment="$root/e44_local_slot_tier_20260716"
remote_tool="$remote_experiment/netobs_tools"
release_archive="$stage/$E44_NODE_RELEASE_ARCHIVE"
common_archive="$stage/$E44_NODE_COMMON_ARCHIVE"
tools_archive="$stage/$E44_NODE_TOOLS_ARCHIVE"
transport_manifest="$stage/$E44_NODE_TRANSPORT_MANIFEST"
seed_release="$E44_NODE_EXT_IMAGES_SEED_RELEASE"
seed_tar="$seed_release/ext_images.tar.gz"
seed_ext="$seed_release/ext_images"
reuse_materialized_release="${E44_NODE_REUSE_MATERIALIZED_RELEASE:-0}"
allowed_active_runtime_root="${E44_NODE_ALLOWED_ACTIVE_RUNTIME_ROOT:-}"

case "$reuse_materialized_release" in
  0 | 1) ;;
  *)
    echo "E44_NODE_REUSE_MATERIALIZED_RELEASE must be 0 or 1" >&2
    exit 2
    ;;
esac
case "$allowed_active_runtime_root" in
  "" | /tmp/fluxon_internal_two_host_20260803) ;;
  *)
    echo "unsupported active-runtime coexistence root: $allowed_active_runtime_root" >&2
    exit 2
    ;;
esac

test -d "$stage"
test -f "$release_archive"
test -f "$common_archive"
test -f "$tools_archive"
test -f "$transport_manifest"

# Every target verifies the exact bytes received over its own transport leg.
(
  cd "$stage"
  sha256sum -c "$E44_NODE_TRANSPORT_MANIFEST" >/dev/null
)

# A delta archive is not allowed to smuggle the immutable service-image payload.
if tar -tzf "$release_archive" | grep -Eq '(^|/)(ext_images|ext_images\.tar\.gz)(/|$)'; then
  echo "release delta unexpectedly contains ext_images payload: $release_archive" >&2
  exit 1
fi

test "$seed_release" != "$E44_NODE_REMOTE_RELEASE"
test -f "$seed_tar"
test -f "$seed_ext/ext_images.sha256"
test "$(sha256sum "$seed_ext/ext_images.sha256" | awk '{print $1}')" = \
  "$E44_NODE_EXPECTED_EXT_MANIFEST_SHA256"

# Do not modify an active E44 runtime and do not destroy the prior release until
# all transport and immutable-seed preflight checks have succeeded. A named
# external stack may coexist only when its exact root is explicitly allowed by
# the experiment wrapper; the default remains fail-closed.
active_runtimes="$(
  pgrep -af '[f]luxon_py.runtime.start_master|[f]luxon_py.runtime.start_owner_kvclient|[s]glang.launch_server' || true
)"
if [ -n "$active_runtimes" ]; then
  if printf '%s\n' "$active_runtimes" | grep -F '/storage/mjq/sglang_fluxon/' >/dev/null; then
    echo "an existing E44 runtime is active under /storage/mjq/sglang_fluxon/:" >&2
    printf '%s\n' "$active_runtimes" >&2
    exit 1
  fi
  if [ -z "$allowed_active_runtime_root" ]; then
    echo "an active runtime exists and coexistence was not enabled:" >&2
    printf '%s\n' "$active_runtimes" >&2
    exit 1
  fi
  disallowed_runtimes="$(
    printf '%s\n' "$active_runtimes" | grep -Fv -- "$allowed_active_runtime_root" || true
  )"
  if [ -n "$disallowed_runtimes" ]; then
    echo "an active runtime exists outside the allowed coexistence root:" >&2
    printf '%s\n' "$disallowed_runtimes" >&2
    exit 1
  fi
  printf 'active_runtime_coexistence=allowed root=%s processes=%s\n' \
    "$allowed_active_runtime_root" "$(printf '%s\n' "$active_runtimes" | wc -l)"
fi

rm -rf -- "$remote_tool"
if [ "$reuse_materialized_release" = 0 ]; then
  rm -rf -- "$E44_NODE_REMOTE_RELEASE"
  mkdir -p "$E44_NODE_REMOTE_RELEASE"
else
  test -d "$E44_NODE_REMOTE_RELEASE"
fi
mkdir -p "$remote_experiment" "$remote_tool/lib"

if [ "$reuse_materialized_release" = 0 ]; then
tar -xzf "$release_archive" -C "$E44_NODE_REMOTE_RELEASE"
fi
tar -xzf "$common_archive" -C "$remote_experiment"
tar -xzf "$tools_archive" -C "$remote_tool"
gpu_stack_launcher="$remote_experiment/e16bb_rdma_numa1_20260714/start_gpu_stack_owner_numa1.sh"
test -x "$gpu_stack_launcher"
test "$(sha256sum "$gpu_stack_launcher" | awk '{print $1}')" = \
  "$E44_NODE_EXPECTED_GPU_STACK_LAUNCHER_SHA256"
mv -- "$remote_tool/libibmad.so.5.3.39.0" "$remote_tool/lib/"
mv -- "$remote_tool/libibumad.so.3.2.39.0" "$remote_tool/lib/"

# ext_images is immutable across these releases. Reuse local sealed bytes with
# hard links; failure to hard-link is fatal rather than silently copying 1.3 GiB.
if [ "$reuse_materialized_release" = 0 ]; then
  ln -- "$seed_tar" "$E44_NODE_REMOTE_RELEASE/ext_images.tar.gz"
  cp -al -- "$seed_ext" "$E44_NODE_REMOTE_RELEASE/"
fi
test "$(stat -c '%d:%i' "$seed_tar")" = \
  "$(stat -c '%d:%i' "$E44_NODE_REMOTE_RELEASE/ext_images.tar.gz")"
test "$(stat -c '%d:%i' "$seed_ext/ext_images.sha256")" = \
  "$(stat -c '%d:%i' "$E44_NODE_REMOTE_RELEASE/ext_images/ext_images.sha256")"

ln -s libibmad.so.5.3.39.0 "$remote_tool/lib/libibmad.so.5"
ln -s libibumad.so.3.2.39.0 "$remote_tool/lib/libibumad.so.3"
chmod 0755 "$remote_tool/perfquery"
test "$(sha256sum "$remote_tool/perfquery" | awk '{print $1}')" = \
  "$E44_NODE_EXPECTED_PERFQUERY_SHA256"
if LD_LIBRARY_PATH="$remote_tool/lib" ldd "$remote_tool/perfquery" | grep -F 'not found'; then
  echo "netobs perfquery has unresolved shared libraries" >&2
  exit 1
fi

# The release manifest includes ext_images.tar.gz, the wheel, source snapshot,
# closed-SDK manifests, and every other shipped top-level artifact.
test "$(awk '$2 == "ext_images.tar.gz" { print $1 }' \
  "$E44_NODE_REMOTE_RELEASE/fluxon_release.sha256")" = \
  "$E44_NODE_EXPECTED_EXT_IMAGES_SHA256"
(
  cd "$E44_NODE_REMOTE_RELEASE"
  sha256sum -c fluxon_release.sha256 >/dev/null
)
# The materialized etcd/Greptime/TiKV tree has its own complete manifest.
(
  cd "$E44_NODE_REMOTE_RELEASE/ext_images"
  sha256sum -c ext_images.sha256 >/dev/null
)

expected_cudart="${E44_NODE_EXPECTED_CUDART_SHA256:-}"
install_env=(
  E44_INSTALL_VENV_GPU="$E44_NODE_VENV"
  E44_INSTALL_VENV_CPU="$E44_NODE_VENV"
)
if [ "$E44_NODE_ROLE" = cpu ] && [ -n "${E44_NODE_CPU_PYTHON:-}" ]; then
  install_env+=(
    E44_INSTALL_CPU_PYTHON="$E44_NODE_CPU_PYTHON"
    E44_INSTALL_CPU_PYTHON_VERSION="${E44_NODE_CPU_PYTHON_VERSION:?missing CPU Python version}"
    E44_INSTALL_CPU_DEPENDENCY_SITE="${E44_NODE_CPU_DEPENDENCY_SITE:-}"
  )
fi
env "${install_env[@]}" \
  bash "$remote_experiment/install_release_e44_r38_get_prefix_reuse.sh" \
  "$E44_NODE_ROLE" \
  "$E44_NODE_REMOTE_RELEASE/$E44_NODE_WHEEL_NAME" \
  "$E44_NODE_EXPECTED_PYO3_SHA256" \
  "$E44_NODE_EXPECTED_CORE_SHA256" \
  "$E44_NODE_EXPECTED_PROBE_SHA256" \
  "$expected_cudart"

test -f "$remote_experiment/$E44_NODE_MASTER_CONFIG"

# Keep the pre-existing runtime/config gates on every node, even though only
# node0 will run the master and control services.
source "$remote_experiment/e44_v5_perf_variant_20260718.sh" "$E44_NODE_VARIANT"
test "$E44_PERF_HICACHE_BATCH_CONCURRENCY" = 32
test "$E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL" = 0
case "$E44_NODE_VARIANT" in
  tier1_independent_005_netobs_r112_eager_all_post_read_retain|tier1_independent_005_netobs_r112_eager_all_post_read_drop|tier1_independent_005_netobs_r113_eager_all_radix_shadow_retain)
    printf '%s' "$E44_PERF_REPLICA_TASK_JSON" | grep -F '"policy":"eager_all"' >/dev/null
    if printf '%s' "$E44_PERF_REPLICA_TASK_JSON" | grep -F 'prefix_end_depth_ratio' >/dev/null; then
      echo "eager-all variant unexpectedly retained bounded prefix admission" >&2
      exit 1
    fi
    ;;
  *)
    printf '%s' "$E44_PERF_REPLICA_TASK_JSON" | grep -F 'prefix_end_depth_ratio' >/dev/null
    printf '%s' "$E44_PERF_REPLICA_TASK_JSON" | grep -F 'max_replica_pages_per_batch":288' >/dev/null
    ;;
esac
if [ "$preserve_installed_sglang" = 0 ]; then
  PYTHONDONTWRITEBYTECODE=1 python3 -B \
    "$remote_experiment/validate_e44_r42_gpu_direct_staging.py" \
    "$remote_experiment/$radix_source" \
    "$remote_experiment/$adapter_source" >/dev/null
  if [ -n "$scheduler_source" ]; then
    PYTHONDONTWRITEBYTECODE=1 python3 -B \
      "$remote_experiment/$timeline_validator" \
      "$remote_experiment/$radix_source" \
      "$remote_experiment/$adapter_source" \
      "$remote_experiment/$scheduler_source" >/dev/null
    grep -F 'struct ExternalGpuGetTerminalEvent' \
      "$E44_NODE_REMOTE_RELEASE/source_external_client_mod.rs" >/dev/null
    grep -F 'terminal_before_consume' \
      "$E44_NODE_REMOTE_RELEASE/source_fluxon_pyo3_lib.rs" >/dev/null
    grep -F 'transfer_wall_us: Optional[int]' \
      "$E44_NODE_REMOTE_RELEASE/source_python_fluxon.py" >/dev/null
  fi
fi

if [ "$E44_NODE_ROLE" = gpu ]; then
  site=/storage/zth/sglang_l13_fluxon_v2/venv-zth/lib/python3.10/site-packages/sglang/srt/mem_cache
  scheduler_site=/storage/zth/sglang_l13_fluxon_v2/venv-zth/lib/python3.10/site-packages/sglang/srt/managers/scheduler.py
  schedule_batch_site=/storage/zth/sglang_l13_fluxon_v2/venv-zth/lib/python3.10/site-packages/sglang/srt/managers/schedule_batch.py
  if [ "$preserve_installed_sglang" = 1 ]; then
    test "$(sha256sum "$site/unified_radix_cache.py" | awk '{print $1}')" = \
      "$E44_NODE_EXPECTED_RADIX_SHA256"
    test "$(sha256sum "$site/storage/fluxon/hicache_fluxon.py" | awk '{print $1}')" = \
      "$E44_NODE_EXPECTED_ADAPTER_SHA256"
    test "$(sha256sum "$scheduler_site" | awk '{print $1}')" = \
      "$expected_scheduler_sha256"
    test "$(sha256sum "$schedule_batch_site" | awk '{print $1}')" = \
      "$expected_schedule_batch_sha256"
  fi
  install -m 0644 "$E44_NODE_REMOTE_RELEASE/memory_pool_host_fluxon_metadata_only.py" \
    "$site/memory_pool_host.py"
  if [ "$preserve_installed_sglang" = 0 ]; then
    install -m 0644 "$remote_experiment/$radix_source" \
      "$site/unified_radix_cache.py"
    install -m 0644 "$remote_experiment/$adapter_source" \
      "$site/storage/fluxon/hicache_fluxon.py"
    if [ -n "$scheduler_source" ]; then
      install -m 0644 "$remote_experiment/$scheduler_source" "$scheduler_site"
    fi
  fi
  test "$(sha256sum "$site/memory_pool_host.py" | awk '{print $1}')" = \
    "$E44_NODE_EXPECTED_HOST_PATCH_SHA256"
  test "$(sha256sum "$site/unified_radix_cache.py" | awk '{print $1}')" = \
    "$E44_NODE_EXPECTED_RADIX_SHA256"
  test "$(sha256sum "$site/storage/fluxon/hicache_fluxon.py" | awk '{print $1}')" = \
    "$E44_NODE_EXPECTED_ADAPTER_SHA256"
  if [ -n "$scheduler_source" ] || [ "$preserve_installed_sglang" = 1 ]; then
    test "$(sha256sum "$scheduler_site" | awk '{print $1}')" = \
      "$expected_scheduler_sha256"
  fi
  if [ "$preserve_installed_sglang" = 1 ]; then
    test "$(sha256sum "$schedule_batch_site" | awk '{print $1}')" = \
      "$expected_schedule_batch_sha256"
  fi
fi

# Publish the release only after every role-specific install and hash gate has
# passed. No service is running while the symlink is switched.
ln -sfn "$E44_NODE_REMOTE_RELEASE" "$root/fluxon_release"
test "$(readlink "$root/fluxon_release")" = "$E44_NODE_REMOTE_RELEASE"
resolved_release="$(readlink -f "$root/fluxon_release")"
test -f "$resolved_release/fluxon_release.sha256"
(
  cd "$resolved_release"
  sha256sum -c fluxon_release.sha256 >/dev/null
)

printf 'two_stage_node_install=passed role=%s host=%s release=%s shared_release_reuse=%s\n' \
  "$E44_NODE_ROLE" "$(hostname)" "$E44_NODE_REMOTE_RELEASE" \
  "$reuse_materialized_release"
