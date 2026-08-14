#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export E44_DEPLOY_GPU_RELEASE="${E44_DEPLOY_GPU_RELEASE:-/mnt/nvme0/mjq_build/fluxon_p13_generic_gpu_cuda_20260804}"
export E44_DEPLOY_CPU_RELEASE="${E44_DEPLOY_CPU_RELEASE:-/mnt/nvme0/mjq_build/fluxon_p13_generic_cpu_host_20260804}"
export E44_DEPLOY_GPU_REMOTE_RELEASE="${E44_DEPLOY_GPU_REMOTE_RELEASE:-/storage/mjq/sglang_fluxon/releases/fluxon_p13_generic_pressure_gpu_20260804}"
export E44_DEPLOY_CPU_REMOTE_RELEASE="${E44_DEPLOY_CPU_REMOTE_RELEASE:-/storage/mjq/sglang_fluxon/releases/fluxon_p13_generic_pressure_cpu_20260804}"
export E44_DEPLOY_GPU_VENV="${E44_DEPLOY_GPU_VENV:-/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-p13-generic-pressure-gpu-20260804}"
export E44_DEPLOY_CPU_VENV="${E44_DEPLOY_CPU_VENV:-/tmp/fluxon_runtime/venv-p13-generic-pressure-cpu-py311-20260804}"
export E44_DEPLOY_CPU_PYTHON="${E44_DEPLOY_CPU_PYTHON:-/opt/conda/bin/python3.11}"
export E44_DEPLOY_CPU_PYTHON_VERSION="${E44_DEPLOY_CPU_PYTHON_VERSION:-3.11}"
export E44_DEPLOY_CPU_PORT="${E44_DEPLOY_CPU_PORT:-31505}"
export E44_DEPLOY_VARIANT="${E44_DEPLOY_VARIANT:-tier1_independent_005_netobs_enddepth288_p13_generic_pressure_r103_adapter}"
export E44_DEPLOY_MASTER_CONFIG="${E44_DEPLOY_MASTER_CONFIG:-master_config_e44_r91_parallel_backing_enddepth288_netobs.yaml.in}"
export E44_DEPLOY_EXPECTED_SOURCE_COMMIT="${E44_DEPLOY_EXPECTED_SOURCE_COMMIT:-ba6c83826a1b094f30873216eb9a9ad0a88a706a}"
export E44_DEPLOY_EXPECTED_PYO3_SHA256="${E44_DEPLOY_EXPECTED_PYO3_SHA256:-99ae0b6cb41faa0f53b0ee4a3bf13569ab7050fadd1a0095129181e48d2923de}"
export E44_DEPLOY_RADIX_SOURCE="${E44_DEPLOY_RADIX_SOURCE:-unified_radix_cache_e44_r92_gdr_off_parallel_backing.py}"
export E44_DEPLOY_ADAPTER_SOURCE="${E44_DEPLOY_ADAPTER_SOURCE:-artifacts/e44_r55_planned_get_cancel_safe_enddepth288_netobs_passed_20260723/config/hicache_fluxon_e44_r54_prefetch_timeline_observe.py}"
export E44_DEPLOY_SCHEDULER_SOURCE="${E44_DEPLOY_SCHEDULER_SOURCE:-artifacts/e44_r55_planned_get_cancel_safe_enddepth288_netobs_passed_20260723/config/scheduler_e44_r54_prefetch_timeline_observe.py}"
export E44_DEPLOY_TIMELINE_VALIDATOR="${E44_DEPLOY_TIMELINE_VALIDATOR:-validate_e44_r92_gdr_off_parallel_backing.py}"
export E44_DEPLOY_EXPECTED_RADIX_SHA256="${E44_DEPLOY_EXPECTED_RADIX_SHA256:-223a70eba3e9df3eed09ae3829b1f17b75a5d4d3273bc0af41bc0fb76e30b9a9}"
export E44_DEPLOY_EXPECTED_ADAPTER_SHA256="${E44_DEPLOY_EXPECTED_ADAPTER_SHA256:-eb1e0848c2717e7f59e82f9051ba6dbae1c06793694dd11aaa3d6e93c6c98ccd}"
export E44_DEPLOY_EXPECTED_SCHEDULER_SHA256="${E44_DEPLOY_EXPECTED_SCHEDULER_SHA256:-5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef}"
export E44_DEPLOY_SSH_IDENTITY="${E44_DEPLOY_SSH_IDENTITY:-/home/zyc/.ssh/infra44_ed25519}"

test "$E44_DEPLOY_VARIANT" = tier1_independent_005_netobs_enddepth288_p13_generic_pressure_r103_adapter
test "$E44_DEPLOY_MASTER_CONFIG" = master_config_e44_r91_parallel_backing_enddepth288_netobs.yaml.in

for release in "$E44_DEPLOY_GPU_RELEASE" "$E44_DEPLOY_CPU_RELEASE"; do
  test "$(tr -d '[:space:]' < "$release/source_merge_commit.txt")" = \
    "$E44_DEPLOY_EXPECTED_SOURCE_COMMIT"
  test "$(tr -d '[:space:]' < "$release/fluxon_pyo3.abi3.so.sha256")" = \
    "$E44_DEPLOY_EXPECTED_PYO3_SHA256"
  grep -F 'OWNER_SLOT_PRESSURE_INITIAL_COARSE_BYTES' \
    "$release/source_client_local_reserve_rebalance.rs" >/dev/null
  grep -F 'installed_refill_grant_consumes_count_but_keeps_failure_authorization' \
    "$release/source_client_local_reserve_rebalance.rs" >/dev/null
  grep -F 'production_owner_grant_remains_a_generic_mixed_size_extent' \
    "$release/source_kv_lib.rs" >/dev/null
  ! grep -F 'aligned_grant_size_bytes' \
    "$release/source_client_local_reserve_rebalance.rs" >/dev/null
  (cd "$release" && sha256sum -c fluxon_release.sha256 >/dev/null)
done

test "$(sha256sum "$script_dir/$E44_DEPLOY_RADIX_SOURCE" | awk '{print $1}')" = \
  "$E44_DEPLOY_EXPECTED_RADIX_SHA256"
test "$(sha256sum "$script_dir/$E44_DEPLOY_ADAPTER_SOURCE" | awk '{print $1}')" = \
  "$E44_DEPLOY_EXPECTED_ADAPTER_SHA256"
test "$(sha256sum "$script_dir/$E44_DEPLOY_SCHEDULER_SOURCE" | awk '{print $1}')" = \
  "$E44_DEPLOY_EXPECTED_SCHEDULER_SHA256"
grep -F "$E44_DEPLOY_VARIANT" "$script_dir/launch_gpu_e44_r38_guarded.sh" >/dev/null
grep -F "$E44_DEPLOY_VARIANT" "$script_dir/e44_v5_perf_variant_20260718.sh" >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -B \
  "$script_dir/$E44_DEPLOY_TIMELINE_VALIDATOR" \
  "$script_dir/$E44_DEPLOY_RADIX_SOURCE" \
  "$script_dir/$E44_DEPLOY_ADAPTER_SOURCE" \
  "$script_dir/$E44_DEPLOY_SCHEDULER_SOURCE" >/dev/null

exec bash "$script_dir/deploy_e44_r61_tp_execute_commit_enddepth288_netobs.sh" "$@"
