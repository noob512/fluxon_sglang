#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export E44_BUILD_GPU_RELEASE=/mnt/nvme0/mjq_build/fluxon_e44_r54_prefetch_timeline_gpu_cuda_20260723
export E44_BUILD_CPU_RELEASE=/mnt/nvme0/mjq_build/fluxon_e44_r54_prefetch_timeline_cpu_host_20260723
export E44_BUILD_GPU_SDK=/mnt/nvme0/mjq_build/fluxon_closed_sdk_abi9_pplx_cuda_r48_single_worker_gpu1_20260722
export E44_BUILD_CPU_SDK=/mnt/nvme0/mjq_build/fluxon_closed_sdk_abi9_pplx_host_r47_20260721
export E44_BUILD_FINALIZE_ONLY="${E44_R54_FINALIZE_ONLY:-0}"

PYTHONDONTWRITEBYTECODE=1 python3 -B \
  "$script_dir/validate_e44_r42_gpu_direct_staging.py" \
  "$script_dir/unified_radix_cache_e44_r54_prefetch_timeline_observe.py" \
  "$script_dir/hicache_fluxon_e44_r54_prefetch_timeline_observe.py"
PYTHONDONTWRITEBYTECODE=1 python3 -B \
  "$script_dir/validate_e44_r54_prefetch_timeline.py" \
  "$script_dir/unified_radix_cache_e44_r54_prefetch_timeline_observe.py" \
  "$script_dir/hicache_fluxon_e44_r54_prefetch_timeline_observe.py" \
  "$script_dir/scheduler_e44_r54_prefetch_timeline_observe.py" \
  "$script_dir/../../Fluxon"

bash "$script_dir/build_e44_r51_metadata_only_plan_releases.sh"

for release in "$E44_BUILD_GPU_RELEASE" "$E44_BUILD_CPU_RELEASE"; do
  install -m 0644 \
    "$script_dir/unified_radix_cache_e44_r54_prefetch_timeline_observe.py" \
    "$release/sglang_unified_radix_cache_r54.py"
  install -m 0644 \
    "$script_dir/hicache_fluxon_e44_r54_prefetch_timeline_observe.py" \
    "$release/sglang_hicache_fluxon_r54.py"
  install -m 0644 \
    "$script_dir/scheduler_e44_r54_prefetch_timeline_observe.py" \
    "$release/sglang_scheduler_r54.py"
  install -m 0644 \
    "$script_dir/validate_e44_r54_prefetch_timeline.py" \
    "$release/validate_e44_r54_prefetch_timeline.py"
  (
    cd "$release"
    rm -f fluxon_release.sha256
    find . -maxdepth 1 -type f ! -name fluxon_release.sha256 -printf '%P\0' \
      | LC_ALL=C sort -z \
      | xargs -0 sha256sum > fluxon_release.sha256
    sha256sum -c fluxon_release.sha256 >/dev/null
  )
done
