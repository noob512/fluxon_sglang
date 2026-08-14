#!/usr/bin/env bash
set -euo pipefail

local_release=/mnt/nvme0/mjq_build/fluxon_e44_r39_get_ready_observe_20260720
remote_release=/storage/mjq/sglang_fluxon/releases/fluxon_e44_r39_get_ready_observe_20260720
experiment=/mnt/ceph/mjq/push_sglang/experiment_configs/e44_local_slot_tier_20260716
tool_root=/mnt/nvme0/mjq_build/e44_r28_netobs_tools_jammy/root
host=116.238.240.2
wheel_name=fluxon-0.2.1-cp38-abi3-manylinux_2_28_x86_64.whl
expected_wheel_sha256=27c8fbfd455b51f5326432af7468c8001b8fdf13db6313dc9a25ce736d5d1038
expected_pyo3_sha256=759333b357783b7983a4bd17bb7ea30f0828ca0d36be5afb92a5bf5c4329421f
expected_host_patch_sha256=482a276e701c4fdd3c44654ff6c8e2403ee59fdb671513db61c62532a9b1c878
expected_radix_sha256=8d1b497fd35ef563e792f6195ca502b67b17e4afd2cfc79f8db0b1846236a5da
expected_hicache_fluxon_sha256=b2d34b0fa045a24f632f626bfdf8dc776045d90c791023765e9557ab03afb27e
expected_perfquery_sha256=42c32fd2b92022754a6be5cf5f3e490c54413ddba05962c82cc4473795cbbc58

deploy_node() {
  local port="$1"
  local root_name="$2"
  local role="$3"
  local root="/storage/mjq/sglang_fluxon/$root_name"
  local remote_experiment="$root/e44_local_slot_tier_20260716"
  local remote_tool="$remote_experiment/netobs_tools"

  ssh -o BatchMode=yes -o StrictHostKeyChecking=no -p "$port" "root@$host" \
    "set -e; \
     if pgrep -af '[s]glang.launch_server' >/dev/null; then \
       echo 'refusing to deploy r39 over a live SGLang process' >&2; exit 1; \
     fi; \
     mkdir -p '$remote_experiment'; rm -rf '$remote_release' '$remote_tool'; mkdir -p '$remote_release' '$remote_tool/lib'"

  scp -q -r -o BatchMode=yes -o StrictHostKeyChecking=no -P "$port" \
    "$local_release/." \
    "root@$host:$remote_release/"

  scp -q -o BatchMode=yes -o StrictHostKeyChecking=no -P "$port" \
    "$experiment/e44_v5_perf_variant_20260718.sh" \
    "$experiment/install_release_e44_r39_get_ready_observe.sh" \
    "$experiment/install_release_e44_r38_get_prefix_reuse.sh" \
    "$experiment/master_config_e44_r39_get_ready_observe_enddepth288_netobs.yaml" \
    "$experiment/unified_radix_cache_e44_r38_get_prefix_reuse.py" \
    "$experiment/hicache_fluxon_e44_r38_get_prefix_reuse.py" \
    "$experiment/validate_e44_r35_loadback_observe.py" \
    "$experiment/validate_e44_r38_get_prefix_reuse.py" \
    "$experiment/smoke_e44_r38_hicache_adapter.py" \
    "$experiment/analyze_e44_r39_get_ready_breakdown.py" \
    "$experiment/fluxon_wait_ready.sh" \
    "$experiment/start_control_e44_v5_perf.sh" \
    "$experiment/launch_master_e44_v5_perf.sh" \
    "$experiment/launch_gpu_e44_r28_netobs.sh" \
    "$experiment/launch_gpu_e44_r38_guarded.sh" \
    "$experiment/launch_cpu_e44_r28_netobs.sh" \
    "$experiment/launch_router_e44_v5_perf.sh" \
    "$experiment/run_workload_e44_r28_netobs.sh" \
    "$experiment/run_smoke_e44_r38_real_transfer.sh" \
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
     grep -F 'consume_prefix_len' '$remote_release/source_client_msg_pack.rs' >/dev/null; \
     grep -F 'external Get start lifecycle:' '$remote_release/source_client_external_api.rs' >/dev/null; \
     grep -F 'external Get consume lifecycle:' '$remote_release/source_client_external_api.rs' >/dev/null; \
     grep -F 'external Get finish lifecycle:' '$remote_release/source_client_get.rs' >/dev/null; \
     grep -F 'released owner tail' '$remote_release/source_client_external_api.rs' >/dev/null; \
     grep -F 'enqueued tail release' '$remote_release/source_external_client_mod.rs' >/dev/null; \
     grep -F 'consume_prefix_len=None' '$remote_release/source_fluxon_pyo3_lib.rs' >/dev/null; \
     grep -F 'consume_prefix_len: Optional[int] = None' '$remote_release/source_python_fluxon.py' >/dev/null; \
     grep -F 'consume_prefix_len: Optional[int] = None' '$remote_release/sglang_hicache_fluxon_r38.py' >/dev/null; \
     test \"\$(sha256sum '$remote_release/sglang_hicache_fluxon_r38.py' | awk '{print \$1}')\" = '$expected_hicache_fluxon_sha256'; \
     source '$remote_experiment/e44_v5_perf_variant_20260718.sh' tier1_independent_005_netobs_enddepth288_get_ready_observe; \
     test \"\$E44_PERF_RUN_ID\" = e44_r39_get_ready_observe_enddepth288_netobs; \
     test \"\$E44_PERF_HICACHE_BATCH_CONCURRENCY\" = 32; \
     test \"\$E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL\" = 0; \
     test \"\$E44_PERF_EXPECTED_PYO3_SHA256\" = '$expected_pyo3_sha256'; \
     test \"\$E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256\" = '$expected_radix_sha256'; \
     test \"\$E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256\" = '$expected_hicache_fluxon_sha256'; \
     printf '%s' \"\$E44_PERF_REPLICA_TASK_JSON\" | grep -F '\"policy\":\"prefix_end_depth_ratio\"' >/dev/null; \
     printf '%s' \"\$E44_PERF_REPLICA_TASK_JSON\" | grep -F '\"max_replica_pages_per_batch\":288' >/dev/null; \
     bash -n '$remote_experiment/e44_v5_perf_variant_20260718.sh' \
       '$remote_experiment/install_release_e44_r39_get_ready_observe.sh' \
       '$remote_experiment/install_release_e44_r38_get_prefix_reuse.sh' \
       '$remote_experiment/fluxon_wait_ready.sh' \
       '$remote_experiment/start_control_e44_v5_perf.sh' \
       '$remote_experiment/launch_master_e44_v5_perf.sh' \
       '$remote_experiment/launch_gpu_e44_r28_netobs.sh' \
       '$remote_experiment/launch_gpu_e44_r38_guarded.sh' \
       '$remote_experiment/launch_cpu_e44_r28_netobs.sh' \
       '$remote_experiment/launch_router_e44_v5_perf.sh' \
       '$remote_experiment/run_workload_e44_r28_netobs.sh' \
       '$remote_experiment/run_smoke_e44_r38_real_transfer.sh' \
       '$remote_experiment/manage_hca_observer_e44_r28.sh'; \
     PYTHONDONTWRITEBYTECODE=1 python3 -B '$remote_experiment/hca_observer_e44_r28.py' --help >/dev/null; \
     PYTHONDONTWRITEBYTECODE=1 python3 -B '$remote_experiment/analyze_hca_observer_e44_r28.py' --help >/dev/null; \
     PYTHONDONTWRITEBYTECODE=1 python3 -B '$remote_experiment/prepare_greptime_e44_r28.py' --help >/dev/null; \
     PYTHONDONTWRITEBYTECODE=1 python3 -B '$remote_experiment/import_hca_observer_to_greptime_e44_r28.py' --help >/dev/null; \
     PYTHONDONTWRITEBYTECODE=1 python3 -B '$remote_experiment/analyze_e44_r39_get_ready_breakdown.py' --self-test >/dev/null; \
     grep -F 'replica_writeback_tier1_capacity_ratio: 0.05' '$remote_experiment/master_config_e44_r39_get_ready_observe_enddepth288_netobs.yaml' >/dev/null; \
     PYTHONDONTWRITEBYTECODE=1 python3 -B '$remote_experiment/validate_e44_r35_loadback_observe.py' '$remote_experiment/unified_radix_cache_e44_r38_get_prefix_reuse.py'; \
     PYTHONDONTWRITEBYTECODE=1 python3 -B '$remote_experiment/validate_e44_r38_get_prefix_reuse.py' '$remote_experiment/unified_radix_cache_e44_r38_get_prefix_reuse.py' '$remote_experiment/hicache_fluxon_e44_r38_get_prefix_reuse.py'; \
     test \"\$(sha256sum '$remote_experiment/unified_radix_cache_e44_r38_get_prefix_reuse.py' | awk '{print \$1}')\" = '$expected_radix_sha256'; \
     test \"\$(sha256sum '$remote_experiment/hicache_fluxon_e44_r38_get_prefix_reuse.py' | awk '{print \$1}')\" = '$expected_hicache_fluxon_sha256'; \
     bash '$remote_experiment/install_release_e44_r39_get_ready_observe.sh' '$role' '$remote_release/$wheel_name' '$expected_pyo3_sha256'; \
     ln -sfn '$remote_release' '$root/fluxon_release'; \
     test \"\$(readlink -f '$root/fluxon_release')\" = '$remote_release'"

  if [ "$role" = gpu ]; then
    ssh -o BatchMode=yes -o StrictHostKeyChecking=no -p "$port" "root@$host" \
      "set -e; \
       site=/storage/zth/sglang_l13_fluxon_v2/venv-zth/lib/python3.10/site-packages/sglang/srt/mem_cache; \
       install -m 0644 '$remote_release/memory_pool_host_fluxon_metadata_only.py' \"\$site/memory_pool_host.py\"; \
       install -m 0644 '$remote_experiment/unified_radix_cache_e44_r38_get_prefix_reuse.py' \"\$site/unified_radix_cache.py\"; \
       install -m 0644 '$remote_experiment/hicache_fluxon_e44_r38_get_prefix_reuse.py' \"\$site/storage/fluxon/hicache_fluxon.py\"; \
       test \"\$(sha256sum \"\$site/memory_pool_host.py\" | awk '{print \$1}')\" = '$expected_host_patch_sha256'; \
       test \"\$(sha256sum \"\$site/unified_radix_cache.py\" | awk '{print \$1}')\" = '$expected_radix_sha256'; \
       test \"\$(sha256sum \"\$site/storage/fluxon/hicache_fluxon.py\" | awk '{print \$1}')\" = '$expected_hicache_fluxon_sha256'; \
       PYTHONDONTWRITEBYTECODE=1 /storage/zth/sglang_l13_fluxon_v2/venv-zth/bin/python -B '$remote_experiment/smoke_e44_r38_hicache_adapter.py'"
  fi
}

test "$(findmnt -n -o SOURCE -T "$tool_root")" = /dev/nvme0n1p3
test "$(findmnt -n -o SOURCE -T "$local_release")" = /dev/nvme0n1p3
case "${1:-all}" in
  all)
    deploy_node 32656 fluxon_f1 gpu
    deploy_node 30245 fluxon_f2 gpu
    deploy_node 30729 fluxon_cpu cpu
    ;;
  node0) deploy_node 32656 fluxon_f1 gpu ;;
  node1) deploy_node 30245 fluxon_f2 gpu ;;
  cpu) deploy_node 30729 fluxon_cpu cpu ;;
  *) echo "usage: $0 [all|node0|node1|cpu]" >&2; exit 2 ;;
esac
