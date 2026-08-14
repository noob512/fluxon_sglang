#!/usr/bin/env bash
set -euo pipefail

local_release=/mnt/nvme0/mjq_build/fluxon_e44_r21_tier1_independent_075_20260719
remote_release=/storage/mjq/sglang_fluxon/releases/fluxon_e44_r21_tier1_independent_075_20260719
experiment=/mnt/ceph/mjq/push_sglang/experiment_configs/e44_local_slot_tier_20260716
host=116.238.240.2
wheel_name=fluxon-0.2.1-cp38-abi3-manylinux_2_28_x86_64.whl
expected_wheel_sha256=e4aeef91467f822a1c6eed85c47d2d1d2fb8c29657d6334ecdddd30f07c10468
expected_pyo3_sha256=ab733bf7b9b30b04bfb4e5dee3c4c81435d7251e4b6b62f7bfabfb7ef153e101
expected_host_patch_sha256=482a276e701c4fdd3c44654ff6c8e2403ee59fdb671513db61c62532a9b1c878

deploy_node() {
  local port="$1"
  local root_name="$2"
  local role="$3"
  local remote_experiment="/storage/mjq/sglang_fluxon/$root_name/e44_local_slot_tier_20260716"
  local root="/storage/mjq/sglang_fluxon/$root_name"

  ssh -o BatchMode=yes -o StrictHostKeyChecking=no -p "$port" "root@$host" \
    "mkdir -p '$remote_experiment'; rm -rf '$remote_release'; mkdir -p '$remote_release'"

  scp -q -r -o BatchMode=yes -o StrictHostKeyChecking=no -P "$port" \
    "$local_release/." \
    "root@$host:$remote_release/"

  scp -q -o BatchMode=yes -o StrictHostKeyChecking=no -P "$port" \
    "$experiment/e44_v5_perf_variant_20260718.sh" \
    "$experiment/install_release_e44_r21_tier1_independent_075.sh" \
    "$experiment/master_config_e44_r21_tier1_independent_075.yaml" \
    "$experiment/fluxon_wait_ready.sh" \
    "$experiment/start_control_e44_v5_perf.sh" \
    "$experiment/launch_master_e44_v5_perf.sh" \
    "$experiment/launch_gpu_e44_v5_perf.sh" \
    "$experiment/launch_cpu_e44_v5_perf.sh" \
    "$experiment/launch_router_e44_v5_perf.sh" \
    "$experiment/run_workload_e44_v5_perf.sh" \
    "$experiment/cluster_e44_r11.env" \
    "root@$host:$remote_experiment/"

  ssh -o BatchMode=yes -o StrictHostKeyChecking=no -p "$port" "root@$host" \
    "set -e; cd '$remote_release'; sha256sum -c fluxon_release.sha256; test \"\$(sha256sum '$remote_release/$wheel_name' | awk '{print \$1}')\" = '$expected_wheel_sha256'; bash -n '$remote_experiment/e44_v5_perf_variant_20260718.sh' '$remote_experiment/install_release_e44_r21_tier1_independent_075.sh' '$remote_experiment/fluxon_wait_ready.sh' '$remote_experiment/start_control_e44_v5_perf.sh' '$remote_experiment/launch_master_e44_v5_perf.sh' '$remote_experiment/launch_gpu_e44_v5_perf.sh' '$remote_experiment/launch_cpu_e44_v5_perf.sh' '$remote_experiment/launch_router_e44_v5_perf.sh' '$remote_experiment/run_workload_e44_v5_perf.sh'; bash '$remote_experiment/install_release_e44_r21_tier1_independent_075.sh' '$role' '$remote_release/$wheel_name' '$expected_pyo3_sha256'; ln -sfn '$remote_release' '$root/fluxon_release'; test \"\$(readlink -f '$root/fluxon_release')\" = '$remote_release'"

  if [ "$role" = gpu ]; then
    ssh -o BatchMode=yes -o StrictHostKeyChecking=no -p "$port" "root@$host" \
      "install -m 0644 '$remote_release/memory_pool_host_fluxon_metadata_only.py' /storage/zth/sglang_l13_fluxon_v2/venv-zth/lib/python3.10/site-packages/sglang/srt/mem_cache/memory_pool_host.py; test \"\$(sha256sum /storage/zth/sglang_l13_fluxon_v2/venv-zth/lib/python3.10/site-packages/sglang/srt/mem_cache/memory_pool_host.py | awk '{print \$1}')\" = '$expected_host_patch_sha256'"
  fi
}

deploy_node 31408 fluxon_f1 gpu
deploy_node 30245 fluxon_f2 gpu
deploy_node 30729 fluxon_cpu cpu
