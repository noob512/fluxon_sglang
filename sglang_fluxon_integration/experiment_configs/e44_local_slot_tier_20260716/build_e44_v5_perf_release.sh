#!/usr/bin/env bash
set -euo pipefail

workspace=/mnt/ceph/mjq/push_sglang
repo="$workspace/Fluxon"
helpers="$workspace/experiment_configs/e16ay_get_target_pressure_shrink_20260713"
experiment="$workspace/experiment_configs/e44_local_slot_tier_20260716"
sdk=/mnt/ceph/zyc/fluxon_closed/fluxon_release_e16bk37_batch_append_20260715/closed_sdk
base="$repo/fluxon_release_e16bk30_dead_protection_rollback_20260715"
seed=/mnt/nvme0/mjq_open_fluxon_pack_env/open_fluxon/projects/511ab2c2fcc9c292dafc01629d47042763a583a8c0b0518bb8c3944465a6ffab/substrates/manylinux_container/target-caches/pack_release_tcp_thread_closed_sdk/134b3060fc2aa095473846a39de8933308054baece1ffec1e6a502867dad0368
target=/mnt/nvme0/mjq_build/fluxon_e44_v5_perf_manylinux_target_20260718
release=/media/infra44/宝宝盘2/mjq_build/fluxon_e44_v5_perf_20260718

mkdir -p "$target" "$release"
if [ ! -f "$target/.seed_complete" ]; then
  rsync -rltL --no-perms --no-owner --no-group \
    "$seed/.rustc_info.json" \
    "$seed/cxxpacked" \
    "$seed/native_runtime" \
    "$seed/release" \
    "$seed/vendor_runtime" \
    "$target/"
  touch "$target/.seed_complete"
fi
if [ ! -f "$target/.tool_seed_complete" ]; then
  rsync -rltL --no-perms --no-owner --no-group \
    "$seed/dagviz" \
    "$seed/downloads" \
    "$seed/maturin" \
    "$seed/meson-0.64.0" \
    "$seed/target_cache_manifest.json" \
    "$target/"
  touch "$target/.tool_seed_complete"
fi

export FLUXON_CARGO_TARGET_CACHE="$target"
export FLUXON_RELEASE_DIR="$release"
export FLUXON_RELEASE_BASE="$base"
export FLUXON_BUILD_CLOSED_SDK_SOURCE="$sdk"
export FLUXON_RELEASE_CLOSED_SDK_SOURCE="$sdk"
export FLUXON_RELEASE_LINK_IMMUTABLE_ASSETS=0
export CARGO_BUILD_JOBS=1

bash "$helpers/build_e16ay_release.sh"
bash "$helpers/finalize_e16ay_release.sh"

install -m 0644 \
  "$experiment/sglang_r12_metadata_host/memory_pool_host.py" \
  "$release/memory_pool_host_fluxon_metadata_only.py"

(
  cd "$repo"
  find fluxon_rs/fluxon_kv fluxon_rs/moka -type f \
    ! -path '*/target/*' \
    -print0 \
    | LC_ALL=C sort -z \
    | xargs -0 sha256sum
) > "$release/source_files.sha256"

(
  cd "$release"
  sha256sum \
    memory_pool_host_fluxon_metadata_only.py \
    source_files.sha256 \
    >> fluxon_release.sha256
  sha256sum -c fluxon_release.sha256
)

find "$release" -maxdepth 1 -type f -name '*.whl' -exec sha256sum {} +

