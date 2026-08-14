#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
workspace=/mnt/ceph/mjq/push_sglang
repo="$workspace/Fluxon"
release="${E44_RELEASE_DIR:-/mnt/nvme0/mjq_build/fluxon_e44_r42_gpu_direct_staging_20260721}"

test "$(findmnt -n -o SOURCE -T /mnt/nvme0/mjq_build/push_sglang_fluxon_target)" = /dev/nvme0n1p3
test "$(findmnt -n -o SOURCE -T "$(dirname "$release")")" = /dev/nvme0n1p3

E44_RELEASE_DIR="$release" bash "$script_dir/build_e44_r38_get_prefix_reuse_release.sh"

rm -f \
  "$release/sglang_unified_radix_cache_r38.py" \
  "$release/sglang_hicache_fluxon_r38.py" \
  "$release/validate_e44_r38_get_prefix_reuse.py" \
  "$release/smoke_e44_r38_hicache_adapter.py"

install -m 0644 \
  "$script_dir/unified_radix_cache_e44_r42_gpu_direct_staging.py" \
  "$release/sglang_unified_radix_cache_r42.py"
install -m 0644 \
  "$script_dir/hicache_fluxon_e44_r42_gpu_direct_staging.py" \
  "$release/sglang_hicache_fluxon_r42.py"
install -m 0755 \
  "$script_dir/validate_e44_r42_gpu_direct_staging.py" \
  "$release/validate_e44_r42_gpu_direct_staging.py"
install -m 0755 \
  "$script_dir/smoke_e44_r42_gpu_d2d_scatter.py" \
  "$release/smoke_e44_r42_gpu_d2d_scatter.py"
install -m 0755 \
  "$script_dir/smoke_e44_r42_gpu_get.py" \
  "$release/smoke_e44_r42_gpu_get.py"

install -m 0644 \
  "$repo/fluxon_rs/fluxon_commu/src/facade/transfer_engine.rs" \
  "$release/source_commu_transfer_engine.rs"
install -m 0644 \
  "$repo/fluxon_rs/fluxon_kv/src/client_seg_pool/mod.rs" \
  "$release/source_client_seg_pool.rs"
install -m 0644 \
  "$repo/fluxon_rs/fluxon_kv/src/client_transfer_engine/mod.rs" \
  "$release/source_client_transfer_engine.rs"
install -m 0644 \
  "$repo/fluxon_rs/fluxon_kv/src/master_kv_router/get.rs" \
  "$release/source_master_get.rs"
install -m 0644 \
  "$repo/fluxon_py/__init__.py" \
  "$release/source_python_init.py"

PYTHONDONTWRITEBYTECODE=1 python3 -B \
  "$release/validate_e44_r42_gpu_direct_staging.py" \
  "$release/sglang_unified_radix_cache_r42.py" \
  "$release/sglang_hicache_fluxon_r42.py"

(
  cd "$release"
  rm -f fluxon_release.sha256
  find . -maxdepth 1 -type f ! -name fluxon_release.sha256 -printf '%P\0' \
    | LC_ALL=C sort -z \
    | xargs -0 sha256sum > fluxon_release.sha256
  sha256sum -c fluxon_release.sha256
)

find "$release" -maxdepth 1 -type f -name '*.whl' -exec sha256sum {} +
cat "$release/fluxon_pyo3.abi3.so.sha256"
