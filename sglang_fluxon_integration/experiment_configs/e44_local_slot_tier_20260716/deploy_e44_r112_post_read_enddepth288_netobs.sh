#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export E44_DEPLOY_GPU_RELEASE="${E44_DEPLOY_GPU_RELEASE:-/mnt/nvme0/mjq_build/fluxon_e44_r112_post_read_drop_gpu_cuda_20260803}"
export E44_DEPLOY_CPU_RELEASE="${E44_DEPLOY_CPU_RELEASE:-/mnt/nvme0/mjq_build/fluxon_e44_r112_post_read_drop_cpu_host_20260803}"
export E44_DEPLOY_GPU_REMOTE_RELEASE="${E44_DEPLOY_GPU_REMOTE_RELEASE:-/storage/mjq/sglang_fluxon/releases/fluxon_e44_r112_post_read_drop_gpu_20260803}"
export E44_DEPLOY_CPU_REMOTE_RELEASE="${E44_DEPLOY_CPU_REMOTE_RELEASE:-/storage/mjq/sglang_fluxon/releases/fluxon_e44_r112_post_read_drop_cpu_20260803}"
export E44_DEPLOY_GPU_VENV="${E44_DEPLOY_GPU_VENV:-/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r112-post-read-gpu-20260803}"
export E44_DEPLOY_CPU_VENV="${E44_DEPLOY_CPU_VENV:-/tmp/fluxon_runtime/venv-r112-post-read-cpu-py311-20260803}"
export E44_DEPLOY_CPU_PYTHON="${E44_DEPLOY_CPU_PYTHON:-/opt/conda/bin/python3.11}"
export E44_DEPLOY_CPU_PYTHON_VERSION="${E44_DEPLOY_CPU_PYTHON_VERSION:-3.11}"
export E44_DEPLOY_CPU_PORT="${E44_DEPLOY_CPU_PORT:-31505}"
export E44_DEPLOY_VARIANT="${E44_DEPLOY_VARIANT:-tier1_independent_005_netobs_enddepth288_r112_post_read_retain}"
export E44_DEPLOY_MASTER_CONFIG="${E44_DEPLOY_MASTER_CONFIG:-master_config_e44_r112_post_read_enddepth288_netobs.yaml.in}"
export E44_DEPLOY_EXPECTED_SOURCE_COMMIT="${E44_DEPLOY_EXPECTED_SOURCE_COMMIT:-21ea90885a99cb70616abd2d2a9483da00ff53be}"
export E44_DEPLOY_EXPECTED_PYO3_SHA256="${E44_DEPLOY_EXPECTED_PYO3_SHA256:-3efd590093ee44abdaa93fa9d359d684a7e5e649d5b4d0f94cf68d8374da593d}"
export E44_DEPLOY_RADIX_SOURCE="${E44_DEPLOY_RADIX_SOURCE:-unified_radix_cache_e44_r92_gdr_off_parallel_backing.py}"
export E44_DEPLOY_ADAPTER_SOURCE="${E44_DEPLOY_ADAPTER_SOURCE:-hicache_fluxon_e44_r54_prefetch_timeline_observe.py}"
export E44_DEPLOY_SCHEDULER_SOURCE="${E44_DEPLOY_SCHEDULER_SOURCE:-artifacts/e44_r55_planned_get_cancel_safe_enddepth288_netobs_passed_20260723/config/scheduler_e44_r54_prefetch_timeline_observe.py}"
export E44_DEPLOY_TIMELINE_VALIDATOR="${E44_DEPLOY_TIMELINE_VALIDATOR:-validate_e44_r105_cachesack_depth.py}"
export E44_DEPLOY_EXPECTED_RADIX_SHA256="${E44_DEPLOY_EXPECTED_RADIX_SHA256:-223a70eba3e9df3eed09ae3829b1f17b75a5d4d3273bc0af41bc0fb76e30b9a9}"
export E44_DEPLOY_EXPECTED_ADAPTER_SHA256="${E44_DEPLOY_EXPECTED_ADAPTER_SHA256:-4d69197532dd6b8efeba7aac48bae97bde44775191a3b2436432fcadc666aa5e}"
export E44_DEPLOY_EXPECTED_SCHEDULER_SHA256="${E44_DEPLOY_EXPECTED_SCHEDULER_SHA256:-5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef}"
export E44_DEPLOY_SSH_IDENTITY="${E44_DEPLOY_SSH_IDENTITY:-/home/zyc/.ssh/infra44_ed25519}"
export E44_DEPLOY_ALLOWED_ACTIVE_RUNTIME_ROOT="${E44_DEPLOY_ALLOWED_ACTIVE_RUNTIME_ROOT:-/tmp/fluxon_internal_two_host_20260803}"

for release in "$E44_DEPLOY_GPU_RELEASE" "$E44_DEPLOY_CPU_RELEASE"; do
  test "$(tr -d '[:space:]' < "$release/source_merge_commit.txt")" = "$E44_DEPLOY_EXPECTED_SOURCE_COMMIT"
  test "$(tr -d '[:space:]' < "$release/fluxon_pyo3.abi3.so.sha256")" = "$E44_DEPLOY_EXPECTED_PYO3_SHA256"
  grep -F 'post_read_remote_policy' "$release/source_kv_config.rs" >/dev/null
  grep -F 'PostReadDuplicate' "$release/source_master_reclaim.rs" >/dev/null
  (cd "$release" && sha256sum -c fluxon_release.sha256 >/dev/null)
done
grep -F '__E44_POST_READ_REMOTE_POLICY__' "$script_dir/$E44_DEPLOY_MASTER_CONFIG" >/dev/null
grep -F 'tier1_independent_005_netobs_enddepth288_r112_post_read_retain' "$script_dir/launch_gpu_e44_r38_guarded.sh" >/dev/null
grep -F 'tier1_independent_005_netobs_enddepth288_r112_post_read_drop' "$script_dir/launch_gpu_e44_r38_guarded.sh" >/dev/null
grep -F 'offset-pool refill completed' "$script_dir/../e16bb_rdma_numa1_20260714/start_gpu_stack_owner_numa1.sh" >/dev/null
test "$(sha256sum "$script_dir/$E44_DEPLOY_TIMELINE_VALIDATOR" | awk '{print $1}')" = \
  266016551d8b4ed56a0f17b5008c5f6e356408908b74ec00cac090a018413fff

exec bash "$script_dir/deploy_e44_r61_tp_execute_commit_enddepth288_netobs.sh" "$@"
