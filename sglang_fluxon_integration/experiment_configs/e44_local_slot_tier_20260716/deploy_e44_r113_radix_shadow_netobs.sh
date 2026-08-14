#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export E44_DEPLOY_GPU_RELEASE="${E44_DEPLOY_GPU_RELEASE:-/mnt/nvme0/mjq_build/fluxon_e44_r113_radix_shadow_gpu_cuda_20260803}"
export E44_DEPLOY_CPU_RELEASE="${E44_DEPLOY_CPU_RELEASE:-/mnt/nvme0/mjq_build/fluxon_e44_r113_radix_shadow_cpu_host_20260803}"
export E44_DEPLOY_GPU_REMOTE_RELEASE="${E44_DEPLOY_GPU_REMOTE_RELEASE:-/storage/mjq/sglang_fluxon/releases/fluxon_e44_r113_radix_shadow_gpu_20260803}"
export E44_DEPLOY_CPU_REMOTE_RELEASE="${E44_DEPLOY_CPU_REMOTE_RELEASE:-/storage/mjq/sglang_fluxon/releases/fluxon_e44_r113_radix_shadow_cpu_20260803}"
export E44_DEPLOY_GPU_VENV="${E44_DEPLOY_GPU_VENV:-/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r113-radix-shadow-gpu-20260803}"
export E44_DEPLOY_CPU_VENV="${E44_DEPLOY_CPU_VENV:-/tmp/fluxon_runtime/venv-r113-radix-shadow-cpu-py311-20260803}"
export E44_DEPLOY_CPU_PYTHON="${E44_DEPLOY_CPU_PYTHON:-/opt/conda/bin/python3.11}"
export E44_DEPLOY_CPU_PYTHON_VERSION="${E44_DEPLOY_CPU_PYTHON_VERSION:-3.11}"
export E44_DEPLOY_CPU_PORT="${E44_DEPLOY_CPU_PORT:-31505}"
export E44_DEPLOY_VARIANT="${E44_DEPLOY_VARIANT:-tier1_independent_005_netobs_r113_eager_all_radix_shadow_retain}"
export E44_DEPLOY_MASTER_CONFIG="${E44_DEPLOY_MASTER_CONFIG:-master_config_e44_r112_eager_all_post_read_netobs.yaml.in}"
export E44_DEPLOY_EXPECTED_SOURCE_COMMIT="${E44_DEPLOY_EXPECTED_SOURCE_COMMIT:-53f9efc8d23d1a9f5e15b357f05febc37ea9e2a5}"
export E44_DEPLOY_EXPECTED_PYO3_SHA256="${E44_DEPLOY_EXPECTED_PYO3_SHA256:-21f4bcf1049d22f5ab50a0b86d30dd0e469f8c136d39489551ea0dbd8fa66a2b}"
export E44_DEPLOY_RADIX_SOURCE="${E44_DEPLOY_RADIX_SOURCE:-unified_radix_cache_e44_r92_gdr_off_parallel_backing.py}"
export E44_DEPLOY_ADAPTER_SOURCE="${E44_DEPLOY_ADAPTER_SOURCE:-hicache_fluxon_e44_r54_prefetch_timeline_observe.py}"
export E44_DEPLOY_SCHEDULER_SOURCE="${E44_DEPLOY_SCHEDULER_SOURCE:-artifacts/e44_r55_planned_get_cancel_safe_enddepth288_netobs_passed_20260723/config/scheduler_e44_r54_prefetch_timeline_observe.py}"
export E44_DEPLOY_TIMELINE_VALIDATOR="${E44_DEPLOY_TIMELINE_VALIDATOR:-validate_e44_r113_radix_shadow.py}"
export E44_DEPLOY_EXPECTED_RADIX_SHA256="${E44_DEPLOY_EXPECTED_RADIX_SHA256:-223a70eba3e9df3eed09ae3829b1f17b75a5d4d3273bc0af41bc0fb76e30b9a9}"
export E44_DEPLOY_EXPECTED_ADAPTER_SHA256="${E44_DEPLOY_EXPECTED_ADAPTER_SHA256:-99b6ad868b3d48f0219aa2e05cf044d69bd5f5d3a7fbf2e8d3568e74e74418a6}"
export E44_DEPLOY_EXPECTED_SCHEDULER_SHA256="${E44_DEPLOY_EXPECTED_SCHEDULER_SHA256:-5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef}"
export E44_DEPLOY_SSH_IDENTITY="${E44_DEPLOY_SSH_IDENTITY:-/home/zyc/.ssh/infra44_ed25519}"
export E44_DEPLOY_ALLOWED_ACTIVE_RUNTIME_ROOT="${E44_DEPLOY_ALLOWED_ACTIVE_RUNTIME_ROOT:-/tmp/fluxon_internal_two_host_20260803}"

case "$E44_DEPLOY_VARIANT:$E44_DEPLOY_MASTER_CONFIG" in
  tier1_independent_005_netobs_r113_eager_all_radix_shadow_retain:master_config_e44_r112_eager_all_post_read_netobs.yaml.in) ;;
  tier1_independent_005_netobs_enddepth288_r113_radix_shadow_retain:master_config_e44_r112_post_read_enddepth288_netobs.yaml.in) ;;
  *) echo "unsupported r113 variant/master-config pairing" >&2; exit 2 ;;
esac

for release in "$E44_DEPLOY_GPU_RELEASE" "$E44_DEPLOY_CPU_RELEASE"; do
  test "$(tr -d '[:space:]' < "$release/source_merge_commit.txt")" = "$E44_DEPLOY_EXPECTED_SOURCE_COMMIT"
  test "$(tr -d '[:space:]' < "$release/fluxon_pyo3.abi3.so.sha256")" = "$E44_DEPLOY_EXPECTED_PYO3_SHA256"
  grep -F 'RadixKvMetadata' "$release/source_master_msg_pack.rs" >/dev/null
  grep -F 'observe_radix_shadow' "$release/source_master_mod.rs" >/dev/null
  grep -F '_validate_put_radix_metadata' "$release/source_python_fluxon.py" >/dev/null
  (cd "$release" && sha256sum -c fluxon_release.sha256 >/dev/null)
done

test "$(sha256sum "$script_dir/$E44_DEPLOY_ADAPTER_SOURCE" | awk '{print $1}')" = \
  "$E44_DEPLOY_EXPECTED_ADAPTER_SHA256"
grep -F "$E44_DEPLOY_VARIANT" \
  "$script_dir/launch_gpu_e44_r38_guarded.sh" >/dev/null
grep -F "$E44_DEPLOY_VARIANT" \
  "$script_dir/e44_v5_perf_variant_20260718.sh" >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -B \
  "$script_dir/$E44_DEPLOY_TIMELINE_VALIDATOR" \
  "$script_dir/$E44_DEPLOY_RADIX_SOURCE" \
  "$script_dir/$E44_DEPLOY_ADAPTER_SOURCE" \
  "$script_dir/$E44_DEPLOY_SCHEDULER_SOURCE" \
  --fluxon-python "$E44_DEPLOY_GPU_RELEASE/source_python_fluxon.py" >/dev/null

exec bash "$script_dir/deploy_e44_r61_tp_execute_commit_enddepth288_netobs.sh" "$@"
