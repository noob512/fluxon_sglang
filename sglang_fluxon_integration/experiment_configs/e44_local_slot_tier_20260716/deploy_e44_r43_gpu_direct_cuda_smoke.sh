#!/usr/bin/env bash
set -euo pipefail

workspace=/mnt/ceph/mjq/push_sglang
experiment="$workspace/experiment_configs/e44_local_slot_tier_20260716"
local_release="${E44_R43_RELEASE_DIR:-/mnt/nvme0/mjq_build/fluxon_e44_r43_gpu_direct_cuda_20260721}"
remote_release="${E44_R43_REMOTE_RELEASE_DIR:-/storage/mjq/sglang_fluxon/releases/fluxon_e44_r43_gpu_direct_cuda_20260721}"
install_venv="${E44_R43_INSTALL_VENV_GPU:-/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r43-gpu-direct-cuda-20260721}"
host=116.238.240.2
wheel_name=fluxon-0.2.1-cp38-abi3-manylinux_2_28_x86_64.whl

test "$(findmnt -n -o SOURCE -T "$local_release")" = /dev/nvme0n1p3
wheel="$local_release/$wheel_name"
test -f "$wheel"
expected_pyo3_sha256="$(tr -d '[:space:]' < "$local_release/fluxon_pyo3.abi3.so.sha256")"
expected_commu_core_sha256="$(unzip -p "$wheel" 'fluxon_pyo3.libs/libfluxon_commu_core.so' | sha256sum | awk '{print $1}')"
expected_rdma_probe_sha256="$(unzip -p "$wheel" 'fluxon_pyo3.libs/libfluxon_rdma_probe.so' | sha256sum | awk '{print $1}')"
expected_cudart_sha256="$(unzip -p "$wheel" 'fluxon_pyo3.libs/libcudart.so.12' | sha256sum | awk '{print $1}')"
test -n "$expected_commu_core_sha256"
test -n "$expected_rdma_probe_sha256"

deploy_node() {
  local port="$1"
  local root_name="$2"
  local root="/storage/mjq/sglang_fluxon/$root_name"
  local remote_experiment="$root/e44_local_slot_tier_20260716"

  ssh -o BatchMode=yes -o StrictHostKeyChecking=no -p "$port" "root@$host" \
    "set -e; \
     if pgrep -af '[f]luxon_py.runtime.start_master|[f]luxon_py.runtime.start_owner_kvclient|[s]glang.launch_server' >/dev/null; then \
       echo 'refusing to deploy GPU-direct release over a live Fluxon/SGLang process' >&2; exit 1; \
     fi; \
     rm -rf '$remote_release'; mkdir -p '$remote_release' '$remote_experiment'"

  scp -q -r -o BatchMode=yes -o StrictHostKeyChecking=no -P "$port" \
    "$local_release/." \
    "root@$host:$remote_release/"
  scp -q -o BatchMode=yes -o StrictHostKeyChecking=no -P "$port" \
    "$experiment/install_release_e44_r38_get_prefix_reuse.sh" \
    "$experiment/install_release_e44_r43_gpu_direct_cuda.sh" \
    "$experiment/start_control_e44_v5_perf.sh" \
    "$experiment/fluxon_wait_ready.sh" \
    "$experiment/launch_master_e44_r43_gpu_get_smoke.sh" \
    "$experiment/launch_owner_e44_r43_gpu_get_smoke.sh" \
    "$experiment/smoke_e44_r42_gpu_get.py" \
    "$experiment/smoke_e44_r42_gpu_d2d_scatter.py" \
    "$experiment/master_config_e44_r42_gpu_get_smoke.yaml" \
    "root@$host:$remote_experiment/"

  ssh -o BatchMode=yes -o StrictHostKeyChecking=no -p "$port" "root@$host" \
    "set -e; \
     cd '$remote_release'; sha256sum -c fluxon_release.sha256 >/dev/null; \
     E44_R43_INSTALL_VENV_GPU='$install_venv' bash '$remote_experiment/install_release_e44_r43_gpu_direct_cuda.sh' \
       gpu '$remote_release/$wheel_name' '$expected_pyo3_sha256' \
       '$expected_commu_core_sha256' '$expected_rdma_probe_sha256' '$expected_cudart_sha256'"
}

deploy_node 32656 fluxon_f1
deploy_node 30245 fluxon_f2

printf 'pyo3_sha256=%s\n' "$expected_pyo3_sha256"
printf 'commu_core_sha256=%s\n' "$expected_commu_core_sha256"
printf 'rdma_probe_sha256=%s\n' "$expected_rdma_probe_sha256"
printf 'cudart_sha256=%s\n' "$expected_cudart_sha256"
