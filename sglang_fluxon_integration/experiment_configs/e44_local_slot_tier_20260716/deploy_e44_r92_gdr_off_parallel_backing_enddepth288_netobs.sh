#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
r55_config=artifacts/e44_r55_planned_get_cancel_safe_enddepth288_netobs_passed_20260723/config

# r92 reuses the sealed r91 Fluxon release. The only runtime behavior change is
# the SGLang experiment source keeping the GPU staging pool unconfigured, so
# both SSD-off and SSD-on materialize every remote page through CPU/H2D.
export E44_DEPLOY_GPU_RELEASE="${E44_DEPLOY_GPU_RELEASE:-/mnt/nvme0/mjq_build/fluxon_e44_r91_parallel_backing_gpu_cuda_20260727}"
export E44_DEPLOY_CPU_RELEASE="${E44_DEPLOY_CPU_RELEASE:-/mnt/nvme0/mjq_build/fluxon_e44_r91_parallel_backing_cpu_host_20260727}"
export E44_DEPLOY_GPU_REMOTE_RELEASE="${E44_DEPLOY_GPU_REMOTE_RELEASE:-/storage/mjq/sglang_fluxon/releases/fluxon_e44_r92_gdr_off_parallel_backing_gpu_20260727}"
export E44_DEPLOY_CPU_REMOTE_RELEASE="${E44_DEPLOY_CPU_REMOTE_RELEASE:-/storage/mjq/sglang_fluxon/releases/fluxon_e44_r92_gdr_off_parallel_backing_cpu_20260727}"
export E44_DEPLOY_GPU_VENV="${E44_DEPLOY_GPU_VENV:-/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r92-gdr-off-parallel-backing-gpu-20260727}"
export E44_DEPLOY_CPU_VENV="${E44_DEPLOY_CPU_VENV:-/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r92-gdr-off-parallel-backing-cpu-20260727}"
export E44_DEPLOY_VARIANT="${E44_DEPLOY_VARIANT:-tier1_independent_005_netobs_enddepth288_r92_gdr_off_parallel_backing}"
export E44_DEPLOY_MASTER_CONFIG=master_config_e44_r91_parallel_backing_enddepth288_netobs.yaml.in
export E44_DEPLOY_SSH_IDENTITY="${E44_DEPLOY_SSH_IDENTITY:-/home/zyc/.ssh/infra44_ed25519}"
export E44_DEPLOY_RADIX_SOURCE=unified_radix_cache_e44_r92_gdr_off_parallel_backing.py
export E44_DEPLOY_ADAPTER_SOURCE="$r55_config/hicache_fluxon_e44_r54_prefetch_timeline_observe.py"
export E44_DEPLOY_SCHEDULER_SOURCE="$r55_config/scheduler_e44_r54_prefetch_timeline_observe.py"
export E44_DEPLOY_TIMELINE_VALIDATOR=validate_e44_r92_gdr_off_parallel_backing.py
export E44_DEPLOY_EXPECTED_RADIX_SHA256=223a70eba3e9df3eed09ae3829b1f17b75a5d4d3273bc0af41bc0fb76e30b9a9
export E44_DEPLOY_EXPECTED_ADAPTER_SHA256=eb1e0848c2717e7f59e82f9051ba6dbae1c06793694dd11aaa3d6e93c6c98ccd
export E44_DEPLOY_EXPECTED_SCHEDULER_SHA256=5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef

for release in "$E44_DEPLOY_GPU_RELEASE" "$E44_DEPLOY_CPU_RELEASE"; do
  test -f "$release/source_parallel_backing_design.md"
  test -f "$release/source_workspace_agents.md"
  test -f "$release/source_rpc_msg_and_error.rs"
  test -x "$release/start_gpu_stack_owner_numa1_ssd.sh"
  test -x "$release/start_cpu_owner_numa1_ssd.sh"
  (
    cd "$release"
    sha256sum -c fluxon_release.sha256 >/dev/null
  )
done

exec bash "$script_dir/deploy_e44_r47_gpu_direct_full_enddepth288_netobs.sh" "$@"
