#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export E44_RELEASE_DIR=/mnt/nvme0/mjq_build/fluxon_e44_r39_get_ready_observe_20260720
exec bash "$script_dir/build_e44_r38_get_prefix_reuse_release.sh"
