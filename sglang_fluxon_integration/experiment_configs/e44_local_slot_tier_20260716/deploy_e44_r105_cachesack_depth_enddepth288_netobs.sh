#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export E44_DEPLOY_GPU_RELEASE="${E44_DEPLOY_GPU_RELEASE:-/mnt/nvme0/mjq_build/fluxon_e44_r105_cachesack_depth_gpu_cuda_20260731}"
export E44_DEPLOY_CPU_RELEASE="${E44_DEPLOY_CPU_RELEASE:-/mnt/nvme0/mjq_build/fluxon_e44_r105_cachesack_depth_cpu_host_20260731}"
export E44_DEPLOY_GPU_REMOTE_RELEASE="${E44_DEPLOY_GPU_REMOTE_RELEASE:-/storage/mjq/sglang_fluxon/releases/fluxon_e44_r105_cachesack_depth_gpu_20260731}"
export E44_DEPLOY_CPU_REMOTE_RELEASE="${E44_DEPLOY_CPU_REMOTE_RELEASE:-/storage/mjq/sglang_fluxon/releases/fluxon_e44_r105_cachesack_depth_cpu_20260731}"
export E44_DEPLOY_GPU_VENV="${E44_DEPLOY_GPU_VENV:-/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r105-cachesack-depth-gpu-20260731}"
export E44_DEPLOY_CPU_VENV="${E44_DEPLOY_CPU_VENV:-/tmp/fluxon_runtime/venv-r105-cachesack-depth-cpu-py311-20260731}"
export E44_DEPLOY_CPU_PYTHON="${E44_DEPLOY_CPU_PYTHON:-/opt/conda/bin/python3.11}"
export E44_DEPLOY_CPU_PYTHON_VERSION="${E44_DEPLOY_CPU_PYTHON_VERSION:-3.11}"
export E44_DEPLOY_CPU_PORT="${E44_DEPLOY_CPU_PORT:-31505}"
export E44_DEPLOY_VARIANT="${E44_DEPLOY_VARIANT:-tier1_independent_005_netobs_enddepth288_gpu_direct_r105_cachesack_control}"
export E44_DEPLOY_MASTER_CONFIG="${E44_DEPLOY_MASTER_CONFIG:-master_config_e44_r105_cachesack_depth_enddepth288_netobs.yaml.in}"
export E44_DEPLOY_EXPECTED_SOURCE_COMMIT="${E44_DEPLOY_EXPECTED_SOURCE_COMMIT:-9c7dd5d174172ddf6580cc4c8777db3481a48556}"
export E44_DEPLOY_EXPECTED_PYO3_SHA256="${E44_DEPLOY_EXPECTED_PYO3_SHA256:-44671092967510180b23df66c724b79e5875598b17b14bd230323553df82c556}"
export E44_DEPLOY_RADIX_SOURCE="${E44_DEPLOY_RADIX_SOURCE:-unified_radix_cache_e44_r92_gdr_off_parallel_backing.py}"
export E44_DEPLOY_ADAPTER_SOURCE="${E44_DEPLOY_ADAPTER_SOURCE:-hicache_fluxon_e44_r54_prefetch_timeline_observe.py}"
export E44_DEPLOY_TIMELINE_VALIDATOR="${E44_DEPLOY_TIMELINE_VALIDATOR:-validate_e44_r105_cachesack_depth.py}"
export E44_DEPLOY_EXPECTED_RADIX_SHA256="${E44_DEPLOY_EXPECTED_RADIX_SHA256:-223a70eba3e9df3eed09ae3829b1f17b75a5d4d3273bc0af41bc0fb76e30b9a9}"
export E44_DEPLOY_EXPECTED_ADAPTER_SHA256="${E44_DEPLOY_EXPECTED_ADAPTER_SHA256:-4d69197532dd6b8efeba7aac48bae97bde44775191a3b2436432fcadc666aa5e}"

grep -Fx '__E44_LOCAL_SSD_EARLY_CONTENT_GATE__' \
  "$script_dir/$E44_DEPLOY_MASTER_CONFIG" >/dev/null
grep -F 'def _absolute_content_depths(' \
  "$script_dir/$E44_DEPLOY_ADAPTER_SOURCE" >/dev/null
test "$(sha256sum "$script_dir/$E44_DEPLOY_RADIX_SOURCE" | awk '{print $1}')" = \
  "$E44_DEPLOY_EXPECTED_RADIX_SHA256"
test "$(sha256sum "$script_dir/$E44_DEPLOY_ADAPTER_SOURCE" | awk '{print $1}')" = \
  "$E44_DEPLOY_EXPECTED_ADAPTER_SHA256"
test "$(sha256sum "$script_dir/$E44_DEPLOY_TIMELINE_VALIDATOR" | awk '{print $1}')" = \
  266016551d8b4ed56a0f17b5008c5f6e356408908b74ec00cac090a018413fff
for release in "$E44_DEPLOY_GPU_RELEASE" "$E44_DEPLOY_CPU_RELEASE"; do
  grep -F 'local_ssd_early_content_max_depth' "$release/source_kv_config.rs" >/dev/null
  grep -F 'local_ssd_content_admitted' "$release/source_master_msg_pack.rs" >/dev/null
  grep -F 'content_depths' "$release/source_fluxon_pyo3_lib.rs" >/dev/null
done

exec bash "$script_dir/deploy_e44_r97_native_ssd_remerge_enddepth288_netobs.sh" "$@"
