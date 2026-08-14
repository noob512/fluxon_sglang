#!/usr/bin/env bash
set -euo pipefail

host=116.238.240.2
experiment=/mnt/ceph/mjq/push_sglang/experiment_configs/e44_local_slot_tier_20260716
tool_root=/mnt/nvme0/mjq_build/e44_r28_netobs_tools_jammy/root
release=/storage/mjq/sglang_fluxon/releases/fluxon_e44_r21_tier1_independent_075_20260719
expected_perfquery_sha256=42c32fd2b92022754a6be5cf5f3e490c54413ddba05962c82cc4473795cbbc58
expected_pyo3_sha256=ab733bf7b9b30b04bfb4e5dee3c4c81435d7251e4b6b62f7bfabfb7ef153e101

deploy_node() {
  local port="$1"
  local root_name="$2"
  local role="$3"
  local root="/storage/mjq/sglang_fluxon/$root_name"
  local remote_experiment="$root/e44_local_slot_tier_20260716"
  local remote_tool="$remote_experiment/netobs_tools"

  ssh -o BatchMode=yes -o StrictHostKeyChecking=no -p "$port" "root@$host" \
    "set -e; mkdir -p '$remote_experiment' '$remote_tool/lib'; rm -rf '$remote_tool'; mkdir -p '$remote_tool/lib'"

  scp -q -o BatchMode=yes -o StrictHostKeyChecking=no -P "$port" \
    "$experiment/e44_v5_perf_variant_20260718.sh" \
    "$experiment/master_config_e44_r28_r22_netobs_replay.yaml" \
    "$experiment/master_config_e44_r29_get_batch64_netobs.yaml" \
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
     test \"\$(readlink -f '$root/fluxon_release')\" = '$release'; \
     cd '$release'; sha256sum -c fluxon_release.sha256 >/dev/null; \
     bash -n '$remote_experiment/e44_v5_perf_variant_20260718.sh' \
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
     PYTHONDONTWRITEBYTECODE=1 python3 -B '$remote_experiment/import_hca_observer_to_greptime_e44_r28.py' --help >/dev/null"

  if [ "$role" = gpu ]; then
    ssh -o BatchMode=yes -o StrictHostKeyChecking=no -p "$port" "root@$host" \
      "test \"\$(sha256sum /storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r21-tier1-independent-075-20260719/lib/python3.10/site-packages/fluxon_pyo3/fluxon_pyo3.abi3.so | cut -d ' ' -f 1)\" = '$expected_pyo3_sha256'"
  else
    ssh -o BatchMode=yes -o StrictHostKeyChecking=no -p "$port" "root@$host" \
      "test \"\$(sha256sum /storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r21-tier1-independent-075-20260719/lib/python3.12/site-packages/fluxon_pyo3/fluxon_pyo3.abi3.so | cut -d ' ' -f 1)\" = '$expected_pyo3_sha256'"
  fi
}

test "$(findmnt -n -o SOURCE -T "$tool_root")" = /dev/nvme0n1p3
deploy_node 31408 fluxon_f1 gpu
deploy_node 30245 fluxon_f2 gpu
deploy_node 30729 fluxon_cpu cpu
