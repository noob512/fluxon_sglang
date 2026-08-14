#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export E44_INSTALL_VENV_GPU="${E44_R43_INSTALL_VENV_GPU:-/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r43-gpu-direct-cuda-20260721}"
export E44_INSTALL_VENV_CPU="${E44_R43_INSTALL_VENV_CPU:-/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r43-gpu-direct-cuda-20260721}"
exec bash "$script_dir/install_release_e44_r38_get_prefix_reuse.sh" "$@"
