#!/usr/bin/env bash
set -euo pipefail

local_release=/mnt/nvme0/mjq_build/fluxon_e44_r30_external_ack_batch_20260719
remote_release=/storage/mjq/sglang_fluxon/releases/fluxon_e44_r30_external_ack_batch_20260719
experiment=/mnt/ceph/mjq/push_sglang/experiment_configs/e44_local_slot_tier_20260716
tool_root=/mnt/nvme0/mjq_build/e44_r28_netobs_tools_jammy/root
host=116.238.240.2
wheel_name=fluxon-0.2.1-cp38-abi3-manylinux_2_28_x86_64.whl
expected_wheel_sha256=28716b4ceeedb26036826d06ddb1d6c59d28a829ffcdce205b9eebcc5507e40c
expected_pyo3_sha256=e3a6e6f89455b759b9654bd25c822a6837f1e34aae646a9a1e5212575afe778b
expected_host_patch_sha256=482a276e701c4fdd3c44654ff6c8e2403ee59fdb671513db61c62532a9b1c878
expected_perfquery_sha256=42c32fd2b92022754a6be5cf5f3e490c54413ddba05962c82cc4473795cbbc58

deploy_node() {
  local port="$1"
  local root_name="$2"
  local role="$3"
  local root="/storage/mjq/sglang_fluxon/$root_name"
  local remote_experiment="$root/e44_local_slot_tier_20260716"
  local remote_tool="$remote_experiment/netobs_tools"

  ssh -o BatchMode=yes -o StrictHostKeyChecking=no -p "$port" "root@$host" \
    "set -e; mkdir -p '$remote_experiment'; rm -rf '$remote_release' '$remote_tool'; mkdir -p '$remote_release' '$remote_tool/lib'"

  scp -q -r -o BatchMode=yes -o StrictHostKeyChecking=no -P "$port" \
    "$local_release/." \
    "root@$host:$remote_release/"

  scp -q -o BatchMode=yes -o StrictHostKeyChecking=no -P "$port" \
    "$experiment/e44_v5_perf_variant_20260718.sh" \
    "$experiment/install_release_e44_r30_external_ack_batch.sh" \
    "$experiment/master_config_e44_r30_external_ack_batch_netobs.yaml" \
    "$experiment/master_config_e44_r30b_external_ack_batch_netobs_retry.yaml" \
    "$experiment/fluxon_wait_ready.sh" \
    "$experiment/start_control_e44_v5_perf.sh" \
    "$experiment/launch_master_e44_v5_perf.sh" \
    "$experiment/launch_gpu_e44_r28_netobs.sh" \
    "$experiment/launch_cpu_e44_r28_netobs.sh" \
    "$experiment/launch_router_e44_v5_perf.sh" \
    "$experiment/run_workload_e44_r28_netobs.sh" \
    "$experiment/cluster_e44_r11.env" \
    "$experiment/hca_observer_e44_r28.py" \
    "$experiment/manage_hca_observer_e44_r28.sh" \
    "$experiment/analyze_hca_observer_e44_r28.py" \
    "$experiment/prepare_greptime_e44_r28.py" \
    "$experiment/import_hca_observer_to_greptime_e44_r28.py" \
    "root@$host:$remote_experiment/"

  scp -q -o BatchMode=yes -o StrictHostKeyChecking=no -P "$port" \
    "$tool_root/usr/sbin/perfquery" \
    "root@$host:$remote_tool/perfquery"
  scp -q -o BatchMode=yes -o StrictHostKeyChecking=no -P "$port" \
    "$tool_root/usr/lib/x86_64-linux-gnu/libibmad.so.5.3.39.0" \
    "$tool_root/usr/lib/x86_64-linux-gnu/libibumad.so.3.2.39.0" \
    "root@$host:$remote_tool/lib/"

  ssh -o BatchMode=yes -o StrictHostKeyChecking=no -p "$port" "root@$host" \
    "set -e; \
     ln -s libibmad.so.5.3.39.0 '$remote_tool/lib/libibmad.so.5'; \
     ln -s libibumad.so.3.2.39.0 '$remote_tool/lib/libibumad.so.3'; \
     chmod 0755 '$remote_tool/perfquery'; \
     test \"\$(sha256sum '$remote_tool/perfquery' | cut -d ' ' -f 1)\" = '$expected_perfquery_sha256'; \
     cd '$remote_release'; sha256sum -c fluxon_release.sha256 >/dev/null; \
     test \"\$(sha256sum '$remote_release/$wheel_name' | awk '{print \$1}')\" = '$expected_wheel_sha256'; \
     bash -n '$remote_experiment/e44_v5_perf_variant_20260718.sh' \
       '$remote_experiment/install_release_e44_r30_external_ack_batch.sh' \
       '$remote_experiment/fluxon_wait_ready.sh' \
       '$remote_experiment/start_control_e44_v5_perf.sh' \
       '$remote_experiment/launch_master_e44_v5_perf.sh' \
       '$remote_experiment/launch_gpu_e44_r28_netobs.sh' \
       '$remote_experiment/launch_cpu_e44_r28_netobs.sh' \
       '$remote_experiment/launch_router_e44_v5_perf.sh' \
       '$remote_experiment/run_workload_e44_r28_netobs.sh' \
       '$remote_experiment/manage_hca_observer_e44_r28.sh'; \
     PYTHONDONTWRITEBYTECODE=1 python3 -B '$remote_experiment/hca_observer_e44_r28.py' --help >/dev/null; \
     PYTHONDONTWRITEBYTECODE=1 python3 -B '$remote_experiment/analyze_hca_observer_e44_r28.py' --help >/dev/null; \
     PYTHONDONTWRITEBYTECODE=1 python3 -B '$remote_experiment/prepare_greptime_e44_r28.py' --help >/dev/null; \
     PYTHONDONTWRITEBYTECODE=1 python3 -B '$remote_experiment/import_hca_observer_to_greptime_e44_r28.py' --help >/dev/null; \
     bash '$remote_experiment/install_release_e44_r30_external_ack_batch.sh' '$role' '$remote_release/$wheel_name' '$expected_pyo3_sha256'; \
     ln -sfn '$remote_release' '$root/fluxon_release'; \
     test \"\$(readlink -f '$root/fluxon_release')\" = '$remote_release'"

  if [ "$role" = gpu ]; then
    ssh -o BatchMode=yes -o StrictHostKeyChecking=no -p "$port" "root@$host" \
      "install -m 0644 '$remote_release/memory_pool_host_fluxon_metadata_only.py' /storage/zth/sglang_l13_fluxon_v2/venv-zth/lib/python3.10/site-packages/sglang/srt/mem_cache/memory_pool_host.py; test \"\$(sha256sum /storage/zth/sglang_l13_fluxon_v2/venv-zth/lib/python3.10/site-packages/sglang/srt/mem_cache/memory_pool_host.py | awk '{print \$1}')\" = '$expected_host_patch_sha256'"
  fi
}

test "$(findmnt -n -o SOURCE -T "$tool_root")" = /dev/nvme0n1p3
test "$(findmnt -n -o SOURCE -T "$local_release")" = /dev/nvme0n1p3
deploy_node 31408 fluxon_f1 gpu
deploy_node 30245 fluxon_f2 gpu
deploy_node 30729 fluxon_cpu cpu
