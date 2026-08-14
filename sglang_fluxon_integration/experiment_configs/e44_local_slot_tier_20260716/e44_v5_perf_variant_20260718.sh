#!/usr/bin/env bash

e44_perf_variant="${1:?missing E44 performance variant}"
E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-v5perf-20260718
E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-v5perf-20260718
E44_PERF_CUDA_HOME=/usr/local/cuda
E44_PERF_CUDA_WHEEL_ROOT=
E44_PERF_EXPECTED_PYO3_SHA256=ea42a5966b59b879645c23b58335f5acf501d43a20639bb23492250e786015ec
E44_PERF_EXPECTED_COMMU_CORE_SHA256=bfa6a32d991f6b6adf0f5175c07ed7da8290d1ed2a7ef4148b3a5f8b13452503
E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU="$E44_PERF_EXPECTED_COMMU_CORE_SHA256"
E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU="$E44_PERF_EXPECTED_RDMA_PROBE_SHA256"
E44_PERF_EXPECTED_MEMORY_POOL_HOST_SHA256=482a276e701c4fdd3c44654ff6c8e2403ee59fdb671513db61c62532a9b1c878
E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=72d3c7be4b71a90e5b04b944b387f9d549f3baa3a68cd4cd00703a2cd488dbee
E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=776d990f879dae2a9c543275fe3fefb623e11a73ea51792edafc7e5fd58d0e9e
E44_PERF_EXPECTED_SCHEDULER_SHA256=
E44_PERF_EXPECTED_SCHEDULE_BATCH_SHA256=
E44_PERF_HICACHE_BATCH_CONCURRENCY=32
E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
E44_PERF_GPU_DIRECT_ENABLED=1
E44_PERF_LOCAL_SSD_EARLY_CONTENT_MAX_DEPTH=
E44_PERF_POST_READ_REMOTE_POLICY=
E44_PERF_MASTER_RDMA_DEVICE_NAMES=
E44_PERF_MASTER_TCP_CONTROL_LANE_COUNT=
E44_PERF_TCP_CONTROL_LANE_COUNT=
case "$e44_perf_variant" in
  baseline)
    E44_PERF_RUN_ID=e44_r12_metadata_baseline
    E44_PERF_MASTER_CONFIG=master_config_e44_r12_metadata_baseline.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":160},"metrics_sample_interval_ms":1000}}'
    ;;
  pinaware_baseline)
    E44_PERF_RUN_ID=e44_r16_pinaware_metadata_baseline
    E44_PERF_MASTER_CONFIG=master_config_e44_r16_pinaware_metadata_baseline.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":160},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r16-pinaware-20260718
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r16-pinaware-20260718
    E44_PERF_EXPECTED_PYO3_SHA256=0628fa575180e22c99d75957c142584e2269138c4775cfa3dfb703d57f9c8fdf
    ;;
  single_kv_baseline)
    E44_PERF_RUN_ID=e44_r17_single_kv_pop_metadata_baseline
    E44_PERF_MASTER_CONFIG=master_config_e44_r17_single_kv_pop_metadata_baseline.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":160},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r17-single-kv-pop-20260718
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r17-single-kv-pop-20260718
    E44_PERF_EXPECTED_PYO3_SHA256=c62e58344e592f0cb2043545a3936faed3ef3fc314992aa9d6a58ab54c4d3e2f
    ;;
  direct_delete_singleflight_baseline)
    E44_PERF_RUN_ID=e44_r18_direct_delete_singleflight_metadata_baseline
    E44_PERF_MASTER_CONFIG=master_config_e44_r18_direct_delete_singleflight_metadata_baseline.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":160},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r18-direct-delete-singleflight-20260719
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r18-direct-delete-singleflight-20260719
    E44_PERF_EXPECTED_PYO3_SHA256=7e307f646296d37634cc3339cc0dd156c0667e4f9c2d7c66c594da50f05780c6
    ;;
  direct_delete_singleflight_tier1_075)
    E44_PERF_RUN_ID=e44_r19_direct_delete_singleflight_tier1_075
    E44_PERF_MASTER_CONFIG=master_config_e44_r19_direct_delete_singleflight_tier1_075.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":160},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r18-direct-delete-singleflight-20260719
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r18-direct-delete-singleflight-20260719
    E44_PERF_EXPECTED_PYO3_SHA256=7e307f646296d37634cc3339cc0dd156c0667e4f9c2d7c66c594da50f05780c6
    ;;
  owner_remote_put_singleflight_tier1_075)
    E44_PERF_RUN_ID=e44_r20_owner_remote_put_singleflight_tier1_075
    E44_PERF_MASTER_CONFIG=master_config_e44_r20_owner_remote_put_singleflight_tier1_075.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":160},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r20-owner-remote-put-singleflight-20260719
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r20-owner-remote-put-singleflight-20260719
    E44_PERF_EXPECTED_PYO3_SHA256=98442cc4312cee2bc3b48715eccb6aa0545b99778997f98f4de4a3fec23746eb
    ;;
  tier1_independent_075)
    E44_PERF_RUN_ID=e44_r21_tier1_independent_075
    E44_PERF_MASTER_CONFIG=master_config_e44_r21_tier1_independent_075.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":160},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r21-tier1-independent-075-20260719
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r21-tier1-independent-075-20260719
    E44_PERF_EXPECTED_PYO3_SHA256=ab733bf7b9b30b04bfb4e5dee3c4c81435d7251e4b6b62f7bfabfb7ef153e101
    ;;
  tier1_independent_005)
    E44_PERF_RUN_ID=e44_r22_tier1_independent_005
    E44_PERF_MASTER_CONFIG=master_config_e44_r22_tier1_independent_005.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":160},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r21-tier1-independent-075-20260719
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r21-tier1-independent-075-20260719
    E44_PERF_EXPECTED_PYO3_SHA256=ab733bf7b9b30b04bfb4e5dee3c4c81435d7251e4b6b62f7bfabfb7ef153e101
    ;;
  tier1_independent_005_netobs_replay)
    # Network-observability replay of r22. Cache policy, release, workload, and
    # concurrency stay byte-for-byte aligned with tier1_independent_005.
    E44_PERF_RUN_ID=e44_r28_r22_netobs_replay
    E44_PERF_MASTER_CONFIG=master_config_e44_r28_r22_netobs_replay.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":160},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r21-tier1-independent-075-20260719
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r21-tier1-independent-075-20260719
    E44_PERF_EXPECTED_PYO3_SHA256=ab733bf7b9b30b04bfb4e5dee3c4c81435d7251e4b6b62f7bfabfb7ef153e101
    ;;
  tier1_independent_005_netobs_ack_batch)
    # Single-variable replay of r28: only External holder release ACKs change
    # from one RPC per holder to generation-safe batches.
    E44_PERF_RUN_ID=e44_r30_external_ack_batch_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r30_external_ack_batch_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":160},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r30-external-ack-batch-20260719
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r30-external-ack-batch-20260719
    E44_PERF_EXPECTED_PYO3_SHA256=e3a6e6f89455b759b9654bd25c822a6837f1e34aae646a9a1e5212575afe778b
    ;;
  tier1_independent_005_netobs_ack_batch_retry)
    # Isolated retry of r30 attempt1. All behavior knobs and the release stay
    # identical; only run-scoped identifiers and output paths change.
    E44_PERF_RUN_ID=e44_r30b_external_ack_batch_netobs_retry
    E44_PERF_MASTER_CONFIG=master_config_e44_r30b_external_ack_batch_netobs_retry.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":160},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r30-external-ack-batch-20260719
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r30-external-ack-batch-20260719
    E44_PERF_EXPECTED_PYO3_SHA256=e3a6e6f89455b759b9654bd25c822a6837f1e34aae646a9a1e5212575afe778b
    ;;
  tier1_independent_005_netobs_ack_batch_source_fence_wait)
    # r31 correctness replay of r30b. The only release behavior change is
    # waiting for the exact source-selection/reclaim generation before an
    # idempotent local-first Put re-evaluates its complete atomic_batch.
    E44_PERF_RUN_ID=e44_r31_source_fence_wait_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r31_source_fence_wait_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":160},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r31-source-fence-wait-20260719
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r31-source-fence-wait-20260719
    E44_PERF_EXPECTED_PYO3_SHA256=17e627190f7a84aff2df3aa824afa7708c5d9f0d3adbbe68296f21c113730109
    ;;
  tier1_independent_005_netobs_ack_batch_source_fence_wait_enddepth288)
    # r32 single-variable replay of r31. Keep the validated r31 release,
    # Get32, tier1 5%, capacities, workload, and observability unchanged;
    # only switch replica admission from start-depth/160 to end-depth/288.
    E44_PERF_RUN_ID=e44_r32_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r32_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r31-source-fence-wait-20260719
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r31-source-fence-wait-20260719
    E44_PERF_EXPECTED_PYO3_SHA256=17e627190f7a84aff2df3aa824afa7708c5d9f0d3adbbe68296f21c113730109
    ;;
  tier1_independent_005_netobs_enddepth288_busy_activity_observe)
    # r33 attribution replay of r32. All performance knobs stay identical;
    # only the release adds structured Busy/activity and owner-wait logs.
    E44_PERF_RUN_ID=e44_r33_busy_activity_observe_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r33_busy_activity_observe_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r33-busy-activity-observe-20260720
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r33-busy-activity-observe-20260720
    E44_PERF_EXPECTED_PYO3_SHA256=d998fb2a7699a8b44d21b059785c16175359ea5ea120a71352fa6bb80224b5de
    ;;
  tier1_independent_005_netobs_enddepth288_replica_operation_identity)
    # r34 correctness replay of r33. All performance knobs and observation
    # stay identical; only replica append completion becomes operation-scoped.
    E44_PERF_RUN_ID=e44_r34_replica_operation_identity_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r34_replica_operation_identity_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r34-replica-operation-identity-20260720
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r34-replica-operation-identity-20260720
    E44_PERF_EXPECTED_PYO3_SHA256=d6bed7449ce6b5bad0c7d1514e9022065736a51dde94f5b4fb58f998e8d9f7d3
    ;;
  tier1_independent_005_netobs_enddepth288_loadback_observe)
    # r35 is observation-only on top of r34. Fluxon binaries and every
    # performance knob remain unchanged; only the deployed SGLang radix
    # source adds request-lifecycle and synchronous-eviction breakdowns.
    E44_PERF_RUN_ID=e44_r35_loadback_lifecycle_observe_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r35_loadback_lifecycle_observe_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r34-replica-operation-identity-20260720
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r34-replica-operation-identity-20260720
    E44_PERF_EXPECTED_PYO3_SHA256=d6bed7449ce6b5bad0c7d1514e9022065736a51dde94f5b4fb58f998e8d9f7d3
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=895951ad37f5f4124b046854380c72ce77118cc2fd6eea8c6fae58b6b2c70c27
    ;;
  tier1_independent_005_netobs_enddepth288_dma_descriptor_cap1152)
    # r36 changes only the maximum raw descriptor count in one H2D batch API
    # call. Logical restore batches, streams, events, operations, and all
    # Fluxon/cache policy settings remain identical to r35.
    E44_PERF_RUN_ID=e44_r36_restore_dma_descriptor_cap1152_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r36_restore_dma_descriptor_cap1152_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r34-replica-operation-identity-20260720
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r34-replica-operation-identity-20260720
    E44_PERF_EXPECTED_PYO3_SHA256=d6bed7449ce6b5bad0c7d1514e9022065736a51dde94f5b4fb58f998e8d9f7d3
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=c53cd68b75f05476d57290c65143b2bb34625c7ee78962e0056b900b2c63572f
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=1152
    ;;
  tier1_independent_005_netobs_enddepth288_get_prefix_reuse)
    # r38 derives SGLang from sealed r35 and changes only TP common-prefix
    # handle consumption. Fluxon adds consume_prefix_len and releases the
    # unconsumed tail; cache policy and all performance knobs stay fixed.
    E44_PERF_RUN_ID=e44_r38_get_prefix_reuse_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r38_get_prefix_reuse_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r38-get-prefix-reuse-20260720
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r38-get-prefix-reuse-20260720
    E44_PERF_EXPECTED_PYO3_SHA256=3e5b9d41af89357d57f09664a4029ef5c12b189b32d53cc8f58fd19c14537ac2
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=8d1b497fd35ef563e792f6195ca502b67b17e4afd2cfc79f8db0b1846236a5da
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=b2d34b0fa045a24f632f626bfdf8dc776045d90c791023765e9557ab03afb27e
    ;;
  tier1_independent_005_netobs_enddepth288_get_ready_observe)
    # r39 is observation-only relative to r38. Workload, cache policy,
    # transfer concurrency, DMA behavior, and SGLang code stay identical.
    E44_PERF_RUN_ID=e44_r39_get_ready_observe_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r39_get_ready_observe_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r39-get-ready-observe-20260720
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r39-get-ready-observe-20260720
    E44_PERF_EXPECTED_PYO3_SHA256=759333b357783b7983a4bd17bb7ea30f0828ca0d36be5afb92a5bf5c4329421f
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=8d1b497fd35ef563e792f6195ca502b67b17e4afd2cfc79f8db0b1846236a5da
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=b2d34b0fa045a24f632f626bfdf8dc776045d90c791023765e9557ab03afb27e
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    ;;
  tier1_independent_005_netobs_enddepth288_gpu_direct_r47)
    # Full r47 validation keeps the sealed r39 workload, cache policy,
    # capacities, Get32, DMA0, and admission unchanged.  The only behavior
    # change is r47 Fluxon plus the validated r42 caller-owned GPU staging.
    E44_PERF_RUN_ID=e44_r47_gpu_direct_full_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r47_gpu_direct_full_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r47-gpu-direct-full-enddepth288-netobs-20260721
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r47-gpu-direct-full-cpu-host-20260721
    E44_PERF_EXPECTED_PYO3_SHA256=ef48cf9852440a6bb33eefc9d036cf6cec3f2f5f7386d09230c0abcdbf35b162
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=55eb59eb07827010016d320eea0d7615834ea3c21d70148cc15951c081f13d09
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=2139404e489268fe5803d19f7be585020359a8351d4b1683733e4cb5ace9deb6
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=574c23041a4c185e52b5f67c98a4486138bf869639842786d2d3cf1453c5520c
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    ;;
  tier1_independent_005_netobs_enddepth288_gpu_direct_r48)
    # Exact replay of the r47 full-load configuration.  The only runtime
    # change is the closed PPLX single-worker mapping that lets TP1 register
    # a caller-owned CUDA device-1 staging buffer against worker 0.
    E44_PERF_RUN_ID=e44_r48_gpu_direct_single_worker_gpu1_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r48_gpu_direct_single_worker_gpu1_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r48-gpu-direct-single-worker-gpu1-20260722
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r48-gpu-direct-full-cpu-host-20260722
    E44_PERF_EXPECTED_PYO3_SHA256=36f8336198e1eee239bf8fbf3811dbf784c6a788cfc55b24d2614eedd0e129eb
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=075461f1af1bf710061b4bd2ab18f7f3ceee7b9bfee8a16d16ab61e0c67e19e3
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=574c23041a4c185e52b5f67c98a4486138bf869639842786d2d3cf1453c5520c
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    ;;
  tier1_independent_005_netobs_enddepth288_gpu_direct_r49_observe)
    # Observation-only replay of r48. Fluxon binaries, 288-slot staging,
    # workload, capacities, cache policy, Get32, and DMA0 stay unchanged;
    # only the two deployed SGLang sources classify GPU staging admission
    # and report lease lifetime/pool occupancy.
    E44_PERF_RUN_ID=e44_r49_gpu_direct_admission_observe_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r49_gpu_direct_admission_observe_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r48-gpu-direct-single-worker-gpu1-20260722
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r48-gpu-direct-full-cpu-host-20260722
    E44_PERF_EXPECTED_PYO3_SHA256=36f8336198e1eee239bf8fbf3811dbf784c6a788cfc55b24d2614eedd0e129eb
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=a7598aca51f52d13e9c1d7709f0f08dce3b112b7b5e3748a4840d4fc9d8c18b2
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=7678033f95bff2f9ff9dfafa8994b2aa225cae655726b3004259cdd25b1a7961
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    ;;
  tier1_independent_005_netobs_enddepth288_gpu_direct_r50_plan_bind)
    # Exact r49 workload/config replay. The only functional variable is the
    # generation-safe Get plan, exact GPU reserve, and same-plan CPU fallback.
    E44_PERF_RUN_ID=e44_r50_plan_bind_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r50_plan_bind_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r50-plan-bind-gpu-20260723
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r50-plan-bind-cpu-20260723
    E44_PERF_EXPECTED_PYO3_SHA256=5094e229e286bfed079d4971d857bf96327ed2dfd460ff344a78a35fd860fbbd
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=3bdab2956a5a255423a7331c5c84dfec9f1be35b5de6b2bdd7169c8a7ed8aab7
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=1cc7153e846ffcd9f32e11f58e55fff2c5b7725b39123b78a93de9319b33114a
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    ;;
  tier1_independent_005_netobs_enddepth288_gpu_direct_r51_metadata_only_plan)
    # Exact r49/r50 workload and configuration replay.  Relative to r50,
    # Plan is metadata-only and installs activity only after Bind revalidation.
    E44_PERF_RUN_ID=e44_r51_metadata_only_plan_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r51_metadata_only_plan_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r51-metadata-only-plan-gpu-20260723
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r51-metadata-only-plan-cpu-20260723
    E44_PERF_EXPECTED_PYO3_SHA256=0d1ee92db91ea58a31e78ce796f1d22a31a10e14ffafbb7a4e9d6715cdddba64
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=3bdab2956a5a255423a7331c5c84dfec9f1be35b5de6b2bdd7169c8a7ed8aab7
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=1cc7153e846ffcd9f32e11f58e55fff2c5b7725b39123b78a93de9319b33114a
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    ;;
  tier1_independent_005_netobs_enddepth288_gpu_direct_r52_owner_local_first)
    # Exact r51 workload/config replay. The only performance variable is that
    # owner-local holders are pinned before Plan and only remote positions
    # enter master metadata and CPU/GPU destination selection.
    E44_PERF_RUN_ID=e44_r52_owner_local_first_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r52_owner_local_first_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r52-owner-local-first-gpu-20260723
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r52-owner-local-first-cpu-20260723
    E44_PERF_EXPECTED_PYO3_SHA256=a0cf3087e32335b6dc6e25d8f6bc546a70bbb864cd5f160453030cf94ff8ee33
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=49679742cc74e581f502c622a9483639ada0937c51afbb9b6b72cbd1a887e848
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=5da41b355bf6d1bbba98dde5b746073f14b8ea3bb2215140c365d60f5884edd9
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    ;;
  tier1_independent_005_netobs_enddepth288_gpu_direct_r53_rust_slab)
    # Exact r52 attempt2 workload/config replay. The only implementation
    # variable is moving the fixed GPU staging slot freelist from Python into
    # fluxon_util and exposing it through fluxon_pyo3.FixedSlabAllocator.
    E44_PERF_RUN_ID=e44_r53_rust_slab_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r53_rust_slab_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r53-rust-slab-gpu-20260723
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r53-rust-slab-cpu-20260723
    E44_PERF_EXPECTED_PYO3_SHA256=e107038c791197bc50d02bdbbfc1fa9c5fdc6007af231ec5fdc98e8e726f0075
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=49679742cc74e581f502c622a9483639ada0937c51afbb9b6b72cbd1a887e848
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=d66e5ea4d4a61cc5d1abe81b637070a3d228dd69e6d51f9b071f6183cee9f955
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    ;;
  tier1_independent_005_netobs_enddepth288_gpu_direct_r54_prefetch_timeline)
    # Exact r53 workload/config replay. This is observation-only: request-level
    # plan/reserve/RDMA-terminal/scheduler-consume/restore/release timestamps
    # are joined without changing admission, queue order, or staging capacity.
    E44_PERF_RUN_ID=e44_r54_prefetch_timeline_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r54_prefetch_timeline_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r54-prefetch-timeline-gpu-20260723
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r54-prefetch-timeline-cpu-20260723
    E44_PERF_EXPECTED_PYO3_SHA256=2f3cf88322c937de744298716c55fef92ea30e85b18a664119872c72ee10645c
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=920cb610334668a5b0199d533d998c111d364de48328b16664010b885f9de554
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=eb1e0848c2717e7f59e82f9051ba6dbae1c06793694dd11aaa3d6e93c6c98ccd
    E44_PERF_EXPECTED_SCHEDULER_SHA256=5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    ;;
  tier1_independent_005_netobs_enddepth288_gpu_direct_r55_planned_get_cancel_safe)
    # Exact r54 workload/config replay. Only the planned CPU Get cancellation
    # ownership and foreground timeout differ in Fluxon.
    E44_PERF_RUN_ID=e44_r55_planned_get_cancel_safe_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r54_prefetch_timeline_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r55-planned-get-cancel-safe-gpu-20260723
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r55-planned-get-cancel-safe-cpu-20260723
    E44_PERF_EXPECTED_PYO3_SHA256=fb0a770a920a8a7678d809d5c31beb9e80385063e53d0ce9035929a70788ace1
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=920cb610334668a5b0199d533d998c111d364de48328b16664010b885f9de554
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=eb1e0848c2717e7f59e82f9051ba6dbae1c06793694dd11aaa3d6e93c6c98ccd
    E44_PERF_EXPECTED_SCHEDULER_SHA256=5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    ;;
  tier1_independent_005_netobs_enddepth288_gpu_direct_r56_two_stage_mixed)
    # Exact r55 workload, Fluxon release, capacity, and cache policy replay.
    # The only runtime variable is two-stage materialization: bounded early
    # owner-local DRAM warmup followed by queue-head H2D/GDR source mixing.
    E44_PERF_RUN_ID=e44_r56_two_stage_mixed_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r54_prefetch_timeline_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"two_stage_mixed_materialization":true,"materialize_queue_head_k":3,"materialize_gdr_budget_pages":96,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r55-planned-get-cancel-safe-gpu-20260723
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r55-planned-get-cancel-safe-cpu-20260723
    E44_PERF_EXPECTED_PYO3_SHA256=fb0a770a920a8a7678d809d5c31beb9e80385063e53d0ce9035929a70788ace1
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=1b259dd9ad85f4bc74589fa300d0d0830671e041ee9946437661e14775f079a2
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=9912aff219063295905bad67ba28a622683570abf49b71f5125c2b2d553133f7
    E44_PERF_EXPECTED_SCHEDULER_SHA256=5b45664cf20587938eaa062fb11fa62652e74cde51dbba2f88f90c02bdae8060
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    ;;
  tier1_independent_005_netobs_enddepth288_gpu_direct_r57_bounded_two_stage)
    # Correctness repair of r56 under the exact same workload/capacities.
    # Host warm starts only inside queue-head 6, materialization remains at
    # queue-head 3, and each TP process admits at most 576 warm pages in flight.
    E44_PERF_RUN_ID=e44_r57_bounded_two_stage_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r54_prefetch_timeline_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"two_stage_mixed_materialization":true,"host_prefetch_queue_head_k":6,"materialize_queue_head_k":3,"materialize_gdr_budget_pages":96,"warmup_pending_limit":576,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r55-planned-get-cancel-safe-gpu-20260723
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r55-planned-get-cancel-safe-cpu-20260723
    E44_PERF_EXPECTED_PYO3_SHA256=fb0a770a920a8a7678d809d5c31beb9e80385063e53d0ce9035929a70788ace1
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=ad96d28fd5c0b06dd85afa0bc0454c37c67ad798f71762436b634e5909d82c86
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=18e5e43d9ebe13cedcc83679cbc59ec8ebfadd594d995d5817d26968f191bf5b
    E44_PERF_EXPECTED_SCHEDULER_SHA256=5b45664cf20587938eaa062fb11fa62652e74cde51dbba2f88f90c02bdae8060
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    ;;
  tier1_independent_005_netobs_enddepth288_gpu_direct_r58_result_consumed)
    # r57 plus the strong Result<MemHolder> consumption fix. All scheduling,
    # capacity, workload, and H2D/GDR policy parameters remain identical.
    E44_PERF_RUN_ID=e44_r58_result_consumed_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r54_prefetch_timeline_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"two_stage_mixed_materialization":true,"host_prefetch_queue_head_k":6,"materialize_queue_head_k":3,"materialize_gdr_budget_pages":96,"warmup_pending_limit":576,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r55-planned-get-cancel-safe-gpu-20260723
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r55-planned-get-cancel-safe-cpu-20260723
    E44_PERF_EXPECTED_PYO3_SHA256=fb0a770a920a8a7678d809d5c31beb9e80385063e53d0ce9035929a70788ace1
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=ad96d28fd5c0b06dd85afa0bc0454c37c67ad798f71762436b634e5909d82c86
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=5a71165e9b8070bbd0211a603715f8e17155acc6b98d87118aae7856b342e128
    E44_PERF_EXPECTED_SCHEDULER_SHA256=5b45664cf20587938eaa062fb11fa62652e74cde51dbba2f88f90c02bdae8060
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    ;;
  tier1_independent_005_netobs_enddepth288_gpu_direct_r59_pressure_bounded)
    # Capacity-safe complement: one-position/96-page early host lane; requests
    # still above the 96-page remote budget use the existing CPU/H2D path.
    E44_PERF_RUN_ID=e44_r59_pressure_bounded_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r54_prefetch_timeline_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"two_stage_mixed_materialization":true,"host_prefetch_queue_head_k":4,"host_prefetch_budget_pages":96,"host_correction_enabled":false,"materialize_queue_head_k":3,"materialize_gdr_budget_pages":96,"warmup_pending_limit":192,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r55-planned-get-cancel-safe-gpu-20260723
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r55-planned-get-cancel-safe-cpu-20260723
    E44_PERF_EXPECTED_PYO3_SHA256=fb0a770a920a8a7678d809d5c31beb9e80385063e53d0ce9035929a70788ace1
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=6831a4fdc218e0788191114c34b155858b81c253feb5991ee9ca81178bf2f7bb
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=5a71165e9b8070bbd0211a603715f8e17155acc6b98d87118aae7856b342e128
    E44_PERF_EXPECTED_SCHEDULER_SHA256=5b45664cf20587938eaa062fb11fa62652e74cde51dbba2f88f90c02bdae8060
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    ;;
  tier1_independent_005_netobs_enddepth288_gpu_direct_r60_kv_lineage_observe)
    # Observation-only replay of the sealed r55 policy and workload. The
    # runtime records compact per-KV source/residence lineage; r56-r59 early
    # host warm and mixed materialization controls are intentionally absent.
    E44_PERF_RUN_ID=e44_r60_kv_lineage_observe_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r54_prefetch_timeline_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r55-planned-get-cancel-safe-gpu-20260723
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r55-planned-get-cancel-safe-cpu-20260723
    E44_PERF_EXPECTED_PYO3_SHA256=fb0a770a920a8a7678d809d5c31beb9e80385063e53d0ce9035929a70788ace1
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=684aff91c1b7619ac2945385036d752b3454afc45935c3d6ccf5b211033198e1
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=eb1e0848c2717e7f59e82f9051ba6dbae1c06793694dd11aaa3d6e93c6c98ccd
    E44_PERF_EXPECTED_SCHEDULER_SHA256=5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    ;;
  tier1_independent_005_netobs_enddepth288_gpu_direct_r61_tp_execute_commit)
    # Exact r60 observation policy plus one post-execute TP commit.  A rank
    # may publish an ongoing prefetch only after all peers executed one mode.
    E44_PERF_RUN_ID=e44_r61_tp_execute_commit_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r54_prefetch_timeline_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r55-planned-get-cancel-safe-gpu-20260723
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r55-planned-get-cancel-safe-cpu-20260723
    E44_PERF_EXPECTED_PYO3_SHA256=fb0a770a920a8a7678d809d5c31beb9e80385063e53d0ce9035929a70788ace1
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=9ffd1ccf488c96eab238d1fee4367de2120d8f1f63146dbbd584bef8d8b650c4
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=eb1e0848c2717e7f59e82f9051ba6dbae1c06793694dd11aaa3d6e93c6c98ccd
    E44_PERF_EXPECTED_SCHEDULER_SHA256=5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    ;;
  tier1_independent_005_netobs_enddepth288_gpu_direct_r77_ssd_unified)
    # Exact r61 SGLang/cache policy and workload with the unified owner
    # memory+SSD route release. E44_CAPACITY_ENABLE_SSD remains the sole
    # runtime switch, so this variant supports an SSD-off memory regression
    # before the otherwise identical SSD-on run.
    E44_PERF_RUN_ID=e44_r77_ssd_unified_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r54_prefetch_timeline_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r77-ssd-unified-gpu-20260724
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r77-ssd-unified-cpu-20260724
    E44_PERF_EXPECTED_PYO3_SHA256=1a835e91700268ae3fa28dd70956fc6cadfc334dc2bc6f400120e644214e9d48
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=9ffd1ccf488c96eab238d1fee4367de2120d8f1f63146dbbd584bef8d8b650c4
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=eb1e0848c2717e7f59e82f9051ba6dbae1c06793694dd11aaa3d6e93c6c98ccd
    E44_PERF_EXPECTED_SCHEDULER_SHA256=5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    ;;
  tier1_independent_005_netobs_enddepth288_gpu_direct_r79_ssd_schema_fix)
    # Exact r77 policy and workload. Only the release changes to carry the
    # Python config schema required by the existing unified SSD path.
    E44_PERF_RUN_ID=e44_r79_ssd_schema_fix_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r54_prefetch_timeline_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r79-ssd-schema-fix-gpu-20260724
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r79-ssd-schema-fix-cpu-20260724
    E44_PERF_EXPECTED_PYO3_SHA256=1a835e91700268ae3fa28dd70956fc6cadfc334dc2bc6f400120e644214e9d48
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=9ffd1ccf488c96eab238d1fee4367de2120d8f1f63146dbbd584bef8d8b650c4
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=eb1e0848c2717e7f59e82f9051ba6dbae1c06793694dd11aaa3d6e93c6c98ccd
    E44_PERF_EXPECTED_SCHEDULER_SHA256=5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    ;;
  tier1_independent_005_netobs_enddepth288_gpu_direct_r80_ssd_eviction_writeback)
    # Exact r79/r78c policy and workload. The only implementation change is
    # SSD persistence moving from every PutDone to exact owner-local victims
    # after their single-KV source fence has been installed.
    E44_PERF_RUN_ID=e44_r80_ssd_eviction_writeback_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r54_prefetch_timeline_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r80-ssd-eviction-writeback-gpu-20260724
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r80-ssd-eviction-writeback-cpu-20260724
    E44_PERF_EXPECTED_PYO3_SHA256=97bd3000cd01a49b45048fdd9ce723dc608a1c81e05e01e822bd0504b454b569
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=9ffd1ccf488c96eab238d1fee4367de2120d8f1f63146dbbd584bef8d8b650c4
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=eb1e0848c2717e7f59e82f9051ba6dbae1c06793694dd11aaa3d6e93c6c98ccd
    E44_PERF_EXPECTED_SCHEDULER_SHA256=5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    ;;
  tier1_independent_005_netobs_enddepth288_gpu_direct_r81_master_reclaim_ssd)
    # Exact r80 policy, capacities and workload. Only the Fluxon release changes
    # to persist remote-CPU master-allocation victims inside BatchOwnerReclaim.
    E44_PERF_RUN_ID=e44_r81_master_reclaim_ssd_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r54_prefetch_timeline_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r81-master-reclaim-ssd-gpu-20260725
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r81-master-reclaim-ssd-cpu-20260725
    E44_PERF_EXPECTED_PYO3_SHA256=6fb2860e8f42306fc1aad8d1cde3b64dfabe0ae71b23b65f085d6d7eb4b7cebb
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=9ffd1ccf488c96eab238d1fee4367de2120d8f1f63146dbbd584bef8d8b650c4
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=eb1e0848c2717e7f59e82f9051ba6dbae1c06793694dd11aaa3d6e93c6c98ccd
    E44_PERF_EXPECTED_SCHEDULER_SHA256=5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    ;;
  tier1_independent_005_netobs_enddepth288_gpu_direct_r82_unindexed_ssd)
    # Exact r81 policy, capacities and workload. Only the Fluxon release changes
    # so production owner_local_indexed=false CPU allocations use the existing
    # SSD-capable BatchOwnerReclaim transaction instead of master-only delete.
    E44_PERF_RUN_ID=e44_r82_unindexed_ssd_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r54_prefetch_timeline_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r82-unindexed-ssd-gpu-20260725
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r82-unindexed-ssd-cpu-20260725
    E44_PERF_EXPECTED_PYO3_SHA256=6f83a52456546d282101d3779d761b8b8ee4c06b86f438b86f82a91725498f1c
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=9ffd1ccf488c96eab238d1fee4367de2120d8f1f63146dbbd584bef8d8b650c4
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=eb1e0848c2717e7f59e82f9051ba6dbae1c06793694dd11aaa3d6e93c6c98ccd
    E44_PERF_EXPECTED_SCHEDULER_SHA256=5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    ;;
  tier1_independent_005_netobs_enddepth288_gpu_direct_r83_last_backing_ssd)
    # Exact r82 policy, capacities and workload. Only the Fluxon release changes
    # so master-coordinated SSD write-back is limited to the last live backing.
    E44_PERF_RUN_ID=e44_r83_last_backing_ssd_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r54_prefetch_timeline_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r83-last-backing-ssd-gpu-20260725
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r83-last-backing-ssd-cpu-20260725
    E44_PERF_EXPECTED_PYO3_SHA256=f8d61f4a994909d68a12207b70af6ffea84260044a863765a27cd5b4036f4a09
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=9ffd1ccf488c96eab238d1fee4367de2120d8f1f63146dbbd584bef8d8b650c4
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=eb1e0848c2717e7f59e82f9051ba6dbae1c06793694dd11aaa3d6e93c6c98ccd
    E44_PERF_EXPECTED_SCHEDULER_SHA256=5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    ;;
  tier1_independent_005_netobs_enddepth288_gpu_direct_r84_ssd_batch_noqueue)
    # Exact r83 policy, capacities and workload. Only the Fluxon release changes
    # to batch one SSD durability barrier and skip concurrent pressure batches.
    E44_PERF_RUN_ID=e44_r84_ssd_batch_noqueue_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r54_prefetch_timeline_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r84-ssd-batch-noqueue-gpu-20260725
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r84-ssd-batch-noqueue-cpu-20260725
    E44_PERF_EXPECTED_PYO3_SHA256=5f6c58b67b64721bd10267de769261dce442b136f8adcb1a28b9b30f816a55b7
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=9ffd1ccf488c96eab238d1fee4367de2120d8f1f63146dbbd584bef8d8b650c4
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=eb1e0848c2717e7f59e82f9051ba6dbae1c06793694dd11aaa3d6e93c6c98ccd
    E44_PERF_EXPECTED_SCHEDULER_SHA256=5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    ;;
  tier1_independent_005_netobs_enddepth288_gpu_direct_r85_ssd_target_pull)
    # Exact r84 policy, capacities and workload. Only the Fluxon release changes
    # so SSD reads publish load-ready and use the ordinary target-pull path.
    E44_PERF_RUN_ID=e44_r85_ssd_target_pull_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r54_prefetch_timeline_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r85-ssd-target-pull-gpu-20260725
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r85-ssd-target-pull-cpu-20260725
    E44_PERF_EXPECTED_PYO3_SHA256=2e64117ab787f81d7cb1447f60c5b7d7dd0a94fcc9cdc980809d1341a2e0c906
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=9ffd1ccf488c96eab238d1fee4367de2120d8f1f63146dbbd584bef8d8b650c4
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=eb1e0848c2717e7f59e82f9051ba6dbae1c06793694dd11aaa3d6e93c6c98ccd
    E44_PERF_EXPECTED_SCHEDULER_SHA256=5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    ;;
  tier1_independent_005_netobs_enddepth288_gpu_direct_r86_ssd_ready_control)
    # Exact r85 policy, capacities and workload. Only the Fluxon release changes
    # to close and observe the SSD load-ready control response path.
    E44_PERF_RUN_ID=e44_r86_ssd_ready_control_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r54_prefetch_timeline_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r86-ssd-ready-control-gpu-20260725
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r86-ssd-ready-control-cpu-20260725
    E44_PERF_EXPECTED_PYO3_SHA256=c8fee59ef109f05e5e160bdf4616178908a062834668157d91f51de7505f01af
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=9ffd1ccf488c96eab238d1fee4367de2120d8f1f63146dbbd584bef8d8b650c4
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=eb1e0848c2717e7f59e82f9051ba6dbae1c06793694dd11aaa3d6e93c6c98ccd
    E44_PERF_EXPECTED_SCHEDULER_SHA256=5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    ;;
  tier1_independent_005_netobs_enddepth288_gpu_direct_r87_active_pool_elastic)
    # Exact r86 workload, cache and SSD policy. Only the Fluxon release changes
    # to expose generation-fenced active/parked node-pool capacity control.
    E44_PERF_RUN_ID=e44_r87_active_pool_elastic_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r54_prefetch_timeline_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r87-active-pool-elastic-gpu-20260725
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r87-active-pool-elastic-cpu-20260725
    E44_PERF_EXPECTED_PYO3_SHA256=e82d81bcc3be8658c988316129b984667c44976ed258fa7ca23b24127e9b328f
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=9ffd1ccf488c96eab238d1fee4367de2120d8f1f63146dbbd584bef8d8b650c4
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=eb1e0848c2717e7f59e82f9051ba6dbae1c06793694dd11aaa3d6e93c6c98ccd
    E44_PERF_EXPECTED_SCHEDULER_SHA256=5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    ;;
  tier1_independent_005_netobs_enddepth288_gpu_direct_r88_gpu_ssd_selective_admission)
    # Exact r87 workload/cache/active-capacity policy. Only the Fluxon release
    # changes to filter last-backing GPU victims and drop excess SSD writes.
    E44_PERF_RUN_ID=e44_r88_gpu_ssd_selective_admission_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r54_prefetch_timeline_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r88-gpu-ssd-selective-admission-gpu-20260725
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r88-gpu-ssd-selective-admission-cpu-20260725
    E44_PERF_EXPECTED_PYO3_SHA256=63a0aa03d4da0335a9c96181b400e8f915febfa295b350b378f75cf6128e76fe
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=9ffd1ccf488c96eab238d1fee4367de2120d8f1f63146dbbd584bef8d8b650c4
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=eb1e0848c2717e7f59e82f9051ba6dbae1c06793694dd11aaa3d6e93c6c98ccd
    E44_PERF_EXPECTED_SCHEDULER_SHA256=5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    ;;
  tier1_independent_005_netobs_enddepth288_gpu_direct_r89_gpu_ssd_fast_drop)
    # Exact r88 workload/cache/capacity/SSD policy. Only the Fluxon release
    # changes to reclaim admission Drop victims before SSD durability starts.
    E44_PERF_RUN_ID=e44_r89_gpu_ssd_fast_drop_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r54_prefetch_timeline_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r89-gpu-ssd-fast-drop-gpu-20260725
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r89-gpu-ssd-fast-drop-cpu-20260725
    E44_PERF_EXPECTED_PYO3_SHA256=529cddb478f5b1c301ec8109f94c6b7a07c871ae6931aa0e444de3bf3e756c8b
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=9ffd1ccf488c96eab238d1fee4367de2120d8f1f63146dbbd584bef8d8b650c4
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=eb1e0848c2717e7f59e82f9051ba6dbae1c06793694dd11aaa3d6e93c6c98ccd
    E44_PERF_EXPECTED_SCHEDULER_SHA256=5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    ;;
  tier1_independent_005_netobs_enddepth288_gpu_direct_r90_ssd_read_legacy|tier1_independent_005_netobs_enddepth288_gpu_direct_r90_ssd_read_local_only_first)
    # One release and one master template cover the legacy control and the
    # strict requester-local SSD policy.
    E44_PERF_MASTER_CONFIG=master_config_e44_r90_ssd_read_policy_enddepth288_netobs.yaml.in
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r90-ssd-read-policy-gpu-20260726
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r90-ssd-read-policy-cpu-20260726
    E44_PERF_EXPECTED_PYO3_SHA256=5e549a2c3f7cda0202bf4a6b3f759607cf612472875086bf2d6f5c11db8d2d23
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=9ffd1ccf488c96eab238d1fee4367de2120d8f1f63146dbbd584bef8d8b650c4
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=eb1e0848c2717e7f59e82f9051ba6dbae1c06793694dd11aaa3d6e93c6c98ccd
    E44_PERF_EXPECTED_SCHEDULER_SHA256=5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    case "$e44_perf_variant" in
      *_legacy)
        E44_PERF_RUN_ID=e44_r90_ssd_read_legacy_enddepth288_netobs
        E44_PERF_SSD_READ_SOURCE_POLICY=legacy_remote_first
        ;;
      *_local_only_first)
        E44_PERF_RUN_ID=e44_r90_ssd_read_local_only_first_enddepth288_netobs
        E44_PERF_SSD_READ_SOURCE_POLICY=local_ssd_only_first
        ;;
    esac
    ;;
  tier1_independent_005_netobs_enddepth288_gpu_direct_r91_parallel_backing)
    # Same workload and scheduler as r90. The release adds independently
    # admitted remote-memory and requester-local SSD early backing writes.
    E44_PERF_RUN_ID=e44_r91_parallel_backing_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r91_parallel_backing_enddepth288_netobs.yaml.in
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r91-parallel-backing-gpu-20260727
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r91-parallel-backing-cpu-20260727
    E44_PERF_EXPECTED_PYO3_SHA256=d9404d7ea4cc8002440cd9ad642cfe334b3f01f0c22229261804e0d568249f1c
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=9ffd1ccf488c96eab238d1fee4367de2120d8f1f63146dbbd584bef8d8b650c4
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=eb1e0848c2717e7f59e82f9051ba6dbae1c06793694dd11aaa3d6e93c6c98ccd
    E44_PERF_EXPECTED_SCHEDULER_SHA256=5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    E44_PERF_SSD_READ_SOURCE_POLICY=local_ssd_only_first
    ;;
  tier1_independent_005_netobs_enddepth288_gpu_direct_r93_mixed_get)
    # Exact r91 workload, cache, backing, GDR and SSD policy. The Fluxon
    # release keeps CPU-only sources on planned H2D while later eligible
    # remote-memory pages in the same plan continue through GDR.
    E44_PERF_RUN_ID=e44_r93_mixed_get_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r91_parallel_backing_enddepth288_netobs.yaml.in
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r93-mixed-get-gpu-20260727
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r93-mixed-get-cpu-20260727
    E44_PERF_EXPECTED_PYO3_SHA256=e3bc3cd7bdab46ace2b996144e84ba04807dda316664b4726d0b7a77b7162e8c
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=9ffd1ccf488c96eab238d1fee4367de2120d8f1f63146dbbd584bef8d8b650c4
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=eb1e0848c2717e7f59e82f9051ba6dbae1c06793694dd11aaa3d6e93c6c98ccd
    E44_PERF_EXPECTED_SCHEDULER_SHA256=5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    E44_PERF_SSD_READ_SOURCE_POLICY=local_ssd_only_first
    ;;
  tier1_independent_005_netobs_enddepth288_gpu_direct_r94_ssd_atomic_batch)
    # Exact r93 workload, cache, GDR and requester-local SSD policy. The
    # release only aggregates one existing atomic_batch into one no-queue
    # SSD gate/persist task and adds route-lineage/refund observability plus
    # shutdown safety fixes.
    E44_PERF_RUN_ID=e44_r94_ssd_atomic_batch_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r91_parallel_backing_enddepth288_netobs.yaml.in
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r94-ssd-atomic-batch-gpu-20260727
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r94-ssd-atomic-batch-cpu-20260727
    E44_PERF_EXPECTED_PYO3_SHA256=bfb7acb503b30fa7f080263abe19a3a38ed1717f319a47e84e89b6fe6c16e151
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=9ffd1ccf488c96eab238d1fee4367de2120d8f1f63146dbbd584bef8d8b650c4
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=eb1e0848c2717e7f59e82f9051ba6dbae1c06793694dd11aaa3d6e93c6c98ccd
    E44_PERF_EXPECTED_SCHEDULER_SHA256=5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    E44_PERF_SSD_READ_SOURCE_POLICY=local_ssd_only_first
    ;;
  tier1_independent_005_netobs_enddepth288_gpu_direct_r95_ssd_pre_admission)
    # Exact r94 workload, cache, GDR, SSD policy, and admission limits. The
    # release only moves byte admission ahead of local-SSD flight/source-holder
    # creation, so rejected early-backing intents do no per-key/pin work.
    E44_PERF_RUN_ID=e44_r95_ssd_pre_admission_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r91_parallel_backing_enddepth288_netobs.yaml.in
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r95-ssd-pre-admission-gpu-20260727
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r95-ssd-pre-admission-cpu-20260727
    E44_PERF_EXPECTED_PYO3_SHA256=a56ca0f11ca352e222d6dac8236a1f562db89e48de354af36fafd15d9a95e1e3
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=9ffd1ccf488c96eab238d1fee4367de2120d8f1f63146dbbd584bef8d8b650c4
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=eb1e0848c2717e7f59e82f9051ba6dbae1c06793694dd11aaa3d6e93c6c98ccd
    E44_PERF_EXPECTED_SCHEDULER_SHA256=5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    E44_PERF_SSD_READ_SOURCE_POLICY=local_ssd_only_first
    ;;
  tier1_independent_005_netobs_enddepth288_gpu_direct_r96_ssd_early_only|tier1_independent_005_netobs_enddepth288_gpu_direct_r96_ssd_early_only_legacy_remote_first)
    # Exact r95 workload, cache, GDR, requester-local SSD policy, capacity,
    # and early-write admission. The release adds a runtime switch used by
    # this experiment to keep normal-Put early SSD backing while capacity
    # eviction directly drops victims instead of synchronously persisting a
    # last backing on the slot-reclaim path.
    case "$e44_perf_variant" in
      tier1_independent_005_netobs_enddepth288_gpu_direct_r96_ssd_early_only)
        E44_PERF_RUN_ID=e44_r96_ssd_early_only_enddepth288_netobs
        E44_PERF_SSD_READ_SOURCE_POLICY=local_ssd_only_first
        ;;
      tier1_independent_005_netobs_enddepth288_gpu_direct_r96_ssd_early_only_legacy_remote_first)
        E44_PERF_RUN_ID=e44_r96_ssd_early_only_legacy_remote_first_diagnostic
        E44_PERF_SSD_READ_SOURCE_POLICY=legacy_remote_first
        ;;
    esac
    E44_PERF_MASTER_CONFIG=master_config_e44_r91_parallel_backing_enddepth288_netobs.yaml.in
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r96-ssd-early-only-gpu-20260728
    E44_PERF_VENV_CPU=/tmp/fluxon_runtime/venv-r96-cpu-py311-20260728
    E44_PERF_EXPECTED_PYO3_SHA256=9ec5a8797c786df4a8c2b43eb43893e78f780caa7de3c5f75e330ddc77392093
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=9ffd1ccf488c96eab238d1fee4367de2120d8f1f63146dbbd584bef8d8b650c4
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=eb1e0848c2717e7f59e82f9051ba6dbae1c06793694dd11aaa3d6e93c6c98ccd
    E44_PERF_EXPECTED_SCHEDULER_SHA256=5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    ;;
  tier1_independent_005_netobs_enddepth288_gpu_direct_r97_native_ssd_remerge)
    # Same S96xT24/2304/c24 workload, local/remote capacities, Get32,
    # end-depth288 and GDR-on baseline as r95/r96. This variant changes only
    # the Fluxon release identity to the clean remerge with main's native
    # O_DIRECT + io_uring SSD backend. SSD-off/on and scope remain explicit
    # runner inputs so both arms use this exact release.
    E44_PERF_RUN_ID=e44_r97_native_ssd_remerge_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r97_native_ssd_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r97-native-ssd-remerge-gpu-20260729
    E44_PERF_VENV_CPU=/tmp/fluxon_runtime/venv-r97-native-ssd-remerge-cpu-py311-20260729
    E44_PERF_EXPECTED_PYO3_SHA256=291dbc31bf47f557b31ee66e9190f3860ed5aab1caa69535547f7dff2a628689
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=9ffd1ccf488c96eab238d1fee4367de2120d8f1f63146dbbd584bef8d8b650c4
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=eb1e0848c2717e7f59e82f9051ba6dbae1c06793694dd11aaa3d6e93c6c98ccd
    E44_PERF_EXPECTED_SCHEDULER_SHA256=5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    ;;
  tier1_independent_005_netobs_enddepth288_gpu_direct_r98_capacity_restore)
    # Exact r97 workload and performance settings. This variant changes only
    # the Fluxon release identity to the capacity-control restoration commit.
    E44_PERF_RUN_ID=e44_r98_capacity_restore_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r98_capacity_restore_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r98-capacity-restore-gpu-20260729
    E44_PERF_VENV_CPU=/tmp/fluxon_runtime/venv-r98-capacity-restore-cpu-py311-20260729
    E44_PERF_EXPECTED_PYO3_SHA256=fb7430e51146538b7c7f22fd6f49c032282b996fdc835c3793d7ec0a10c50da5
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=9ffd1ccf488c96eab238d1fee4367de2120d8f1f63146dbbd584bef8d8b650c4
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=eb1e0848c2717e7f59e82f9051ba6dbae1c06793694dd11aaa3d6e93c6c98ccd
    E44_PERF_EXPECTED_SCHEDULER_SHA256=5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    ;;
  tier1_independent_005_netobs_enddepth288_gpu_direct_r99_remote_replica_native_ssd)
    # Exact r98 workload, cache, capacity-control, Get32, end-depth288 and
    # GDR-on settings. This release only adds native SSD persistence after a
    # remote replica is first published; SSD scope remains a runner input.
    E44_PERF_RUN_ID=e44_r99_remote_replica_native_ssd_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r99_remote_replica_native_ssd_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r99-remote-replica-native-ssd-gpu-20260729
    E44_PERF_VENV_CPU=/tmp/fluxon_runtime/venv-r99-remote-replica-native-ssd-cpu-py311-20260729
    E44_PERF_EXPECTED_PYO3_SHA256=7a0e34274674ee540b10af5f8906e00477689427e81f67e8ad64a2df150ed82a
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=9ffd1ccf488c96eab238d1fee4367de2120d8f1f63146dbbd584bef8d8b650c4
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=eb1e0848c2717e7f59e82f9051ba6dbae1c06793694dd11aaa3d6e93c6c98ccd
    E44_PERF_EXPECTED_SCHEDULER_SHA256=5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    ;;
  tier1_independent_005_netobs_enddepth288_gpu_direct_r100_bounded_native_ssd)
    # Exact r99 workload, cache, capacity, SSD scope input and GDR settings.
    # The only runtime change is the four-permit no-queue native persist gate.
    E44_PERF_RUN_ID=e44_r100_bounded_native_ssd_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r100_bounded_native_ssd_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r100-bounded-native-ssd-gpu-20260729
    E44_PERF_VENV_CPU=/tmp/fluxon_runtime/venv-r100-bounded-native-ssd-cpu-py311-20260729
    E44_PERF_EXPECTED_PYO3_SHA256=9b64fd7e041e74787d4d04fcd9bcae616adac46460706570df0881ee783bf748
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=9ffd1ccf488c96eab238d1fee4367de2120d8f1f63146dbbd584bef8d8b650c4
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=eb1e0848c2717e7f59e82f9051ba6dbae1c06793694dd11aaa3d6e93c6c98ccd
    E44_PERF_EXPECTED_SCHEDULER_SHA256=5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    ;;
  tier1_independent_005_netobs_enddepth288_gpu_direct_r102_owner_local_ssd)
    # Keep the fixed r98/r100 S96xT24/2304/c24, Get32, tier1 5%,
    # end-depth288 and 128/115.2 + 256/248 GiB cache geometry. The runner
    # explicitly enables gpu_local_only native SSD. GDR stays off so this run
    # isolates owner-local early backing and its no-queue bytes admission.
    E44_PERF_RUN_ID=e44_r102_owner_local_ssd_gdroff_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r102_owner_local_ssd_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r102-owner-local-ssd-gpu-20260730
    E44_PERF_VENV_CPU=/tmp/fluxon_runtime/venv-r102-owner-local-ssd-cpu-py311-20260730
    E44_PERF_EXPECTED_PYO3_SHA256=c9960eb6cf2af605e323b34a8b834cde03d16536d81010c24266ab0e00b871f3
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=223a70eba3e9df3eed09ae3829b1f17b75a5d4d3273bc0af41bc0fb76e30b9a9
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=eb1e0848c2717e7f59e82f9051ba6dbae1c06793694dd11aaa3d6e93c6c98ccd
    E44_PERF_EXPECTED_SCHEDULER_SHA256=5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    E44_PERF_SOURCE_ORDER_EVIDENCE=planner_requester_local_fixed
    E44_PERF_GPU_DIRECT_ENABLED=0
    ;;
  tier1_independent_005_netobs_enddepth288_gpu_direct_r103_ssd_get_lane)
    # Exact r102 workload/cache/SSD geometry with the r103 Get-lane release.
    # Keep this as a distinct variant so runtime launchers cannot silently
    # inherit the r102 GPU/CPU venv while the active release points at r103.
    E44_PERF_RUN_ID=e44_r103_ssd_get_lane_gdroff_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r102_owner_local_ssd_enddepth288_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r103-ssd-get-lane-gpu-20260730
    E44_PERF_VENV_CPU=/tmp/fluxon_runtime/venv-r103-ssd-get-lane-cpu-py311-20260730
    E44_PERF_EXPECTED_PYO3_SHA256=fdfd92a98854eb89dff71b425cc006cf44679f44040fa2c6220584224d39b75e
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=223a70eba3e9df3eed09ae3829b1f17b75a5d4d3273bc0af41bc0fb76e30b9a9
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=eb1e0848c2717e7f59e82f9051ba6dbae1c06793694dd11aaa3d6e93c6c98ccd
    E44_PERF_EXPECTED_SCHEDULER_SHA256=5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    E44_PERF_SOURCE_ORDER_EVIDENCE=planner_requester_local_fixed
    E44_PERF_GPU_DIRECT_ENABLED=0
    ;;
  tier1_independent_005_netobs_enddepth288_gpu_direct_r105_cachesack_control)
    # Same release and resource geometry as the depth31 treatment. Omitting
    # the master content gate preserves the r103 normal-Put SSD behavior.
    E44_PERF_RUN_ID=e44_r105_cachesack_control_gdroff_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r105_cachesack_depth_enddepth288_netobs.yaml.in
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r105-cachesack-depth-gpu-20260731
    E44_PERF_VENV_CPU=/tmp/fluxon_runtime/venv-r105-cachesack-depth-cpu-py311-20260731
    E44_PERF_EXPECTED_PYO3_SHA256=44671092967510180b23df66c724b79e5875598b17b14bd230323553df82c556
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=223a70eba3e9df3eed09ae3829b1f17b75a5d4d3273bc0af41bc0fb76e30b9a9
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=4d69197532dd6b8efeba7aac48bae97bde44775191a3b2436432fcadc666aa5e
    E44_PERF_EXPECTED_SCHEDULER_SHA256=5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    E44_PERF_SOURCE_ORDER_EVIDENCE=planner_requester_local_fixed
    E44_PERF_GPU_DIRECT_ENABLED=0
    ;;
  tier1_independent_005_netobs_enddepth288_fast25_mlp_hybrid_20260805)
    # The FAST'25 multi-level-prefix experiment keeps the r105 control policy
    # and resource geometry, but seals the exact 2026-08-05 native SSD hybrid
    # release and the current compatible SGLang adapter/scheduler identities.
    E44_PERF_RUN_ID=fast25_mlp_hybrid_20260805_gdroff_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r105_cachesack_depth_enddepth288_netobs.yaml.in
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/public/zth/sglang_l13_fluxon_v2/venv-fluxon-fast25-mlp-hybrid-gpu-20260805
    E44_PERF_VENV_CPU=/tmp/fluxon_runtime/venv-fast25-mlp-hybrid-cpu-py311-20260805
    E44_PERF_CUDA_HOME=/mnt/nvme0/mjq_build/fast25_cuda_13_0
    E44_PERF_CUDA_WHEEL_ROOT=/public/zth/sglang_l13_fluxon_v2/venv-zth/lib/python3.10/site-packages/nvidia/cu13
    E44_PERF_EXPECTED_PYO3_SHA256=a8b99b700785e8d530770db636698f13cd8fb0830533062ba1f8ecc0730e9fc5
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=223a70eba3e9df3eed09ae3829b1f17b75a5d4d3273bc0af41bc0fb76e30b9a9
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=99b6ad868b3d48f0219aa2e05cf044d69bd5f5d3a7fbf2e8d3568e74e74418a6
    E44_PERF_EXPECTED_SCHEDULER_SHA256=5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    E44_PERF_SOURCE_ORDER_EVIDENCE=planner_requester_local_fixed
    E44_PERF_GPU_DIRECT_ENABLED=0
    ;;
  tier1_independent_005_netobs_enddepth288_fast25_mlp_p14_r133_device_headroom_ad8475e_20260806|tier1_independent_005_netobs_enddepth288_fast25_mlp_p14_r133_device_headroom_cuda13_31772_ad8475e_20260807)
    E44_PERF_RUN_ID=fast25_mlp_p14_r133_device_headroom_ad8475e_20260806_gdroff_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r105_cachesack_depth_enddepth288_netobs.yaml.in
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-fast25-mlp-r132-content-depths-compat-gpu-0216a00-20260806
    E44_PERF_VENV_CPU=/tmp/fluxon_runtime/venv-fast25-mlp-r132-content-depths-compat-cpu-0216a00-py311-20260806
    E44_PERF_CUDA_HOME=/usr/local/cuda-12.8
    E44_PERF_CUDA_WHEEL_ROOT=
    E44_PERF_EXPECTED_PYO3_SHA256=eebf07a3461b780e30eb14f069b80d18e0164f49bb0c7cf3fe78f410e710d58a
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=ad8475eb4c45228491c0094c3bbcbfcb2c84761a0d62d1dbb1b19c3ee318897a
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=99b6ad868b3d48f0219aa2e05cf044d69bd5f5d3a7fbf2e8d3568e74e74418a6
    E44_PERF_EXPECTED_SCHEDULER_SHA256=22e07568bf0c51f0508b1c28b1332810cc147e0197ae1939fbeb5864f5e68d92
    E44_PERF_EXPECTED_SCHEDULE_BATCH_SHA256=8e2777318c67005b4e6f540dc4a9d07661e1cf3784daafc43997c68ebe5f769a
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_HICACHE_PREFETCH_THRESHOLD=64
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    E44_PERF_SOURCE_ORDER_EVIDENCE=planner_requester_local_fixed
    E44_PERF_GPU_DIRECT_ENABLED=0
    E44_PERF_MASTER_TCP_CONTROL_LANE_COUNT=8
    E44_PERF_TCP_CONTROL_LANE_COUNT=8
    if [ "$e44_perf_variant" = tier1_independent_005_netobs_enddepth288_fast25_mlp_p14_r133_device_headroom_cuda13_31772_ad8475e_20260807 ]; then
      E44_PERF_RUN_ID=fast25_mlp_p14_r133_device_headroom_cuda13_31772_ad8475e_20260807_gdroff_enddepth288_netobs
      E44_PERF_VENV_GPU=/public/zth/sglang_l13_fluxon_v2/venv-fluxon-fast25-mlp-r132-content-depths-compat-gpu-0216a00-20260806
      E44_PERF_CUDA_HOME=/mnt/nvme0/mjq_build/fast25_cuda_13_0
      E44_PERF_CUDA_WHEEL_ROOT=/public/zth/sglang_l13_fluxon_v2/venv-zth/lib/python3.10/site-packages/nvidia/cu13
    fi
    ;;
  tier1_independent_005_netobs_enddepth288_fast25_mlp_p14_r134_post_read_drop_r132_ad8475e_20260807)
    # Exact r133 S80 runtime geometry and SGLang identities. The Fluxon release
    # is rebuilt from the r132 source baseline; only post-read remote Drop is on.
    E44_PERF_RUN_ID=fast25_mlp_p14_r134_post_read_drop_r132_ad8475e_20260807_gdroff_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r134_post_read_drop_r133.yaml.in
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-fast25-r134-post-read-drop-r132-gpu-20260807
    E44_PERF_VENV_CPU=/tmp/fluxon_runtime/venv-fast25-r134-post-read-drop-r132-cpu-py311-20260807
    E44_PERF_CUDA_HOME=/usr/local/cuda-12.8
    E44_PERF_CUDA_WHEEL_ROOT=
    E44_PERF_EXPECTED_PYO3_SHA256=b4b6f8773b0b25967cd4920e6477f6d7b1534bd31d454b763c6fe43ed2787019
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=ad8475eb4c45228491c0094c3bbcbfcb2c84761a0d62d1dbb1b19c3ee318897a
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=99b6ad868b3d48f0219aa2e05cf044d69bd5f5d3a7fbf2e8d3568e74e74418a6
    E44_PERF_EXPECTED_SCHEDULER_SHA256=22e07568bf0c51f0508b1c28b1332810cc147e0197ae1939fbeb5864f5e68d92
    E44_PERF_EXPECTED_SCHEDULE_BATCH_SHA256=8e2777318c67005b4e6f540dc4a9d07661e1cf3784daafc43997c68ebe5f769a
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_HICACHE_PREFETCH_THRESHOLD=64
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    E44_PERF_SOURCE_ORDER_EVIDENCE=planner_requester_local_fixed
    E44_PERF_GPU_DIRECT_ENABLED=0
    E44_PERF_POST_READ_REMOTE_POLICY=drop
    E44_PERF_MASTER_TCP_CONTROL_LANE_COUNT=8
    E44_PERF_TCP_CONTROL_LANE_COUNT=8
    ;;
  tier1_independent_005_netobs_enddepth288_fast25_mlp_p14_native_ssd_d839359_20260805|tier1_independent_005_netobs_enddepth288_fast25_mlp_p14_r114_holder_release_d839359_20260805|tier1_independent_005_netobs_enddepth288_fast25_mlp_p14_r115_ready_prefix_shape_d839359_20260805|tier1_independent_005_netobs_enddepth288_fast25_mlp_p14_r116_ready_plan_suffix_d839359_20260805|tier1_independent_005_netobs_enddepth288_fast25_mlp_p14_r117_prefetch64_d839359_20260805|tier1_independent_005_netobs_enddepth288_fast25_mlp_p14_r118_ready_anchor_lock_d839359_20260805|tier1_independent_005_netobs_enddepth288_fast25_mlp_p14_r119_source_admission_d839359_20260805|tier1_independent_005_netobs_enddepth288_fast25_mlp_p14_r120_hit_accounting_d839359_20260805|tier1_independent_005_netobs_enddepth288_fast25_mlp_p14_r121_planned_get_replay_1c7b37e_20260806|tier1_independent_005_netobs_enddepth288_fast25_mlp_p14_r122_get_done_control_52ef745_20260806|tier1_independent_005_netobs_enddepth288_fast25_mlp_p14_r123_get_done_stage_trace_e7fffd0_20260806|tier1_independent_005_netobs_enddepth288_fast25_mlp_p14_r124_master_rpc_fastpath_e7fffd0_20260806|tier1_independent_005_netobs_enddepth288_fast25_mlp_p14_r125_master_control8_e7fffd0_20260806|tier1_independent_005_netobs_enddepth288_fast25_mlp_p14_r126_global_control8_e7fffd0_20260806|tier1_independent_005_netobs_enddepth288_fast25_mlp_p14_r128_remote_put_admission16g4096_e7fffd0_20260806|tier1_independent_005_netobs_enddepth288_fast25_mlp_p14_r129_remote_put_admission24g6144_e7fffd0_20260806|tier1_independent_005_netobs_enddepth288_fast25_mlp_p14_r130_remote_put_batch_e02590b_20260806|tier1_independent_005_netobs_enddepth288_fast25_mlp_p14_r131_tier1_wait_memholder_97ab9f2_20260806|tier1_independent_005_netobs_enddepth288_fast25_mlp_p14_r132_content_depths_compat_0216a00_20260806)
    # Same FAST'25 workload and runtime knobs as the sealed hybrid arm above.
    # Only the Fluxon identity changes to the p14 allocator + native SSD merge.
    E44_PERF_RUN_ID=fast25_mlp_p14_native_ssd_d839359_20260805_gdroff_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r105_cachesack_depth_enddepth288_netobs.yaml.in
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/public/zth/sglang_l13_fluxon_v2/venv-fluxon-fast25-mlp-p14-native-ssd-gpu-d839359-20260805
    E44_PERF_VENV_CPU=/tmp/fluxon_runtime/venv-fast25-mlp-p14-native-ssd-cpu-d839359-py311-20260805
    E44_PERF_CUDA_HOME=/mnt/nvme0/mjq_build/fast25_cuda_13_0
    E44_PERF_CUDA_WHEEL_ROOT=/public/zth/sglang_l13_fluxon_v2/venv-zth/lib/python3.10/site-packages/nvidia/cu13
    E44_PERF_EXPECTED_PYO3_SHA256=80b023947cb535bdc79b1acd6017ac9be4e11d2b2f8065c4582f6527c6cdfdcc
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=223a70eba3e9df3eed09ae3829b1f17b75a5d4d3273bc0af41bc0fb76e30b9a9
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=99b6ad868b3d48f0219aa2e05cf044d69bd5f5d3a7fbf2e8d3568e74e74418a6
    E44_PERF_EXPECTED_SCHEDULER_SHA256=5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_HICACHE_PREFETCH_THRESHOLD=256
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    E44_PERF_SOURCE_ORDER_EVIDENCE=planner_requester_local_fixed
    E44_PERF_GPU_DIRECT_ENABLED=0
    if [ "$e44_perf_variant" = tier1_independent_005_netobs_enddepth288_fast25_mlp_p14_r114_holder_release_d839359_20260805 ]; then
      E44_PERF_RUN_ID=fast25_mlp_p14_r114_holder_release_d839359_20260805_gdroff_enddepth288_netobs
      E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=f940b82a0fcb7b08ec8c043422e6b86ead5cd0bb22bbe801c63f655e7813ceab
    elif [ "$e44_perf_variant" = tier1_independent_005_netobs_enddepth288_fast25_mlp_p14_r115_ready_prefix_shape_d839359_20260805 ]; then
      E44_PERF_RUN_ID=fast25_mlp_p14_r115_ready_prefix_shape_d839359_20260805_gdroff_enddepth288_netobs
      E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=ba2f510c1fbbadfae4879cbbc5631b89eceeddbfc3841688d26597d6d4d182d4
    elif [ "$e44_perf_variant" = tier1_independent_005_netobs_enddepth288_fast25_mlp_p14_r116_ready_plan_suffix_d839359_20260805 ]; then
      E44_PERF_RUN_ID=fast25_mlp_p14_r116_ready_plan_suffix_d839359_20260805_gdroff_enddepth288_netobs
      E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=300a259711dc869df356a41b4c1c632b5b599cf7d596f4a11ac0783a1eaee33d
    elif [ "$e44_perf_variant" = tier1_independent_005_netobs_enddepth288_fast25_mlp_p14_r117_prefetch64_d839359_20260805 ]; then
      E44_PERF_RUN_ID=fast25_mlp_p14_r117_prefetch64_d839359_20260805_gdroff_enddepth288_netobs
      E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=300a259711dc869df356a41b4c1c632b5b599cf7d596f4a11ac0783a1eaee33d
      E44_PERF_HICACHE_PREFETCH_THRESHOLD=64
    elif [ "$e44_perf_variant" = tier1_independent_005_netobs_enddepth288_fast25_mlp_p14_r118_ready_anchor_lock_d839359_20260805 ]; then
      E44_PERF_RUN_ID=fast25_mlp_p14_r118_ready_anchor_lock_d839359_20260805_gdroff_enddepth288_netobs
      E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=e41f194069cde9e01447a77688e0815ad5e522aae8f9ebe31ac59695e6580e2c
      E44_PERF_HICACHE_PREFETCH_THRESHOLD=64
    elif [ "$e44_perf_variant" = tier1_independent_005_netobs_enddepth288_fast25_mlp_p14_r119_source_admission_d839359_20260805 ]; then
      E44_PERF_RUN_ID=fast25_mlp_p14_r119_source_admission_d839359_20260805_gdroff_enddepth288_netobs
      E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=9ae25216085dec9c76fe3b7a40451e6510320045eec77032c0838fc6f2ce2f5e
      E44_PERF_HICACHE_PREFETCH_THRESHOLD=64
    elif [ "$e44_perf_variant" = tier1_independent_005_netobs_enddepth288_fast25_mlp_p14_r120_hit_accounting_d839359_20260805 ]; then
      E44_PERF_RUN_ID=fast25_mlp_p14_r120_hit_accounting_d839359_20260805_gdroff_enddepth288_netobs
      E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=9ae25216085dec9c76fe3b7a40451e6510320045eec77032c0838fc6f2ce2f5e
      E44_PERF_EXPECTED_SCHEDULER_SHA256=22e07568bf0c51f0508b1c28b1332810cc147e0197ae1939fbeb5864f5e68d92
      E44_PERF_EXPECTED_SCHEDULE_BATCH_SHA256=8e2777318c67005b4e6f540dc4a9d07661e1cf3784daafc43997c68ebe5f769a
      E44_PERF_HICACHE_PREFETCH_THRESHOLD=64
    elif [ "$e44_perf_variant" = tier1_independent_005_netobs_enddepth288_fast25_mlp_p14_r121_planned_get_replay_1c7b37e_20260806 ]; then
      E44_PERF_RUN_ID=fast25_mlp_p14_r121_planned_get_replay_1c7b37e_20260806_gdroff_enddepth288_netobs
      E44_PERF_VENV_GPU=/public/zth/sglang_l13_fluxon_v2/venv-fluxon-fast25-mlp-r121-planned-get-replay-gpu-1c7b37e-20260806
      E44_PERF_VENV_CPU=/tmp/fluxon_runtime/venv-fast25-mlp-r121-planned-get-replay-cpu-1c7b37e-py311-20260806
      E44_PERF_EXPECTED_PYO3_SHA256=c90c7995002f34e6ed24ba2dbaee48f64b2c539af3d94cda937139470d64ea4b
      E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=9ae25216085dec9c76fe3b7a40451e6510320045eec77032c0838fc6f2ce2f5e
      E44_PERF_EXPECTED_SCHEDULER_SHA256=22e07568bf0c51f0508b1c28b1332810cc147e0197ae1939fbeb5864f5e68d92
      E44_PERF_EXPECTED_SCHEDULE_BATCH_SHA256=8e2777318c67005b4e6f540dc4a9d07661e1cf3784daafc43997c68ebe5f769a
      E44_PERF_HICACHE_PREFETCH_THRESHOLD=64
    elif [ "$e44_perf_variant" = tier1_independent_005_netobs_enddepth288_fast25_mlp_p14_r122_get_done_control_52ef745_20260806 ]; then
      E44_PERF_RUN_ID=fast25_mlp_p14_r122_get_done_control_52ef745_20260806_gdroff_enddepth288_netobs
      E44_PERF_VENV_GPU=/public/zth/sglang_l13_fluxon_v2/venv-fluxon-fast25-mlp-r122-get-done-control-gpu-52ef745-20260806
      E44_PERF_VENV_CPU=/tmp/fluxon_runtime/venv-fast25-mlp-r122-get-done-control-cpu-52ef745-py311-20260806
      E44_PERF_EXPECTED_PYO3_SHA256=a276450a0bc76c7627dc6e0ad7a49e4d7cfad9180ed2c6b41909058618e5f3b5
      E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=9ae25216085dec9c76fe3b7a40451e6510320045eec77032c0838fc6f2ce2f5e
      E44_PERF_EXPECTED_SCHEDULER_SHA256=22e07568bf0c51f0508b1c28b1332810cc147e0197ae1939fbeb5864f5e68d92
      E44_PERF_EXPECTED_SCHEDULE_BATCH_SHA256=8e2777318c67005b4e6f540dc4a9d07661e1cf3784daafc43997c68ebe5f769a
      E44_PERF_HICACHE_PREFETCH_THRESHOLD=64
    elif [ "$e44_perf_variant" = tier1_independent_005_netobs_enddepth288_fast25_mlp_p14_r123_get_done_stage_trace_e7fffd0_20260806 ]; then
      E44_PERF_RUN_ID=fast25_mlp_p14_r123_get_done_stage_trace_e7fffd0_20260806_gdroff_enddepth288_netobs
      E44_PERF_VENV_GPU=/public/zth/sglang_l13_fluxon_v2/venv-fluxon-fast25-mlp-r123-get-done-stage-trace-gpu-e7fffd0-20260806
      E44_PERF_VENV_CPU=/tmp/fluxon_runtime/venv-fast25-mlp-r123-get-done-stage-trace-cpu-e7fffd0-py311-20260806
      E44_PERF_EXPECTED_PYO3_SHA256=aa93ae7eb9171c1a7410b4685bbadfb5317689b43e0b8e11d5cb9e585d57db06
      E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=9ae25216085dec9c76fe3b7a40451e6510320045eec77032c0838fc6f2ce2f5e
      E44_PERF_EXPECTED_SCHEDULER_SHA256=22e07568bf0c51f0508b1c28b1332810cc147e0197ae1939fbeb5864f5e68d92
      E44_PERF_EXPECTED_SCHEDULE_BATCH_SHA256=8e2777318c67005b4e6f540dc4a9d07661e1cf3784daafc43997c68ebe5f769a
      E44_PERF_HICACHE_PREFETCH_THRESHOLD=64
    elif [ "$e44_perf_variant" = tier1_independent_005_netobs_enddepth288_fast25_mlp_p14_r124_master_rpc_fastpath_e7fffd0_20260806 ]; then
      E44_PERF_RUN_ID=fast25_mlp_p14_r124_master_rpc_fastpath_e7fffd0_20260806_gdroff_enddepth288_netobs
      E44_PERF_VENV_GPU=/public/zth/sglang_l13_fluxon_v2/venv-fluxon-fast25-mlp-r123-get-done-stage-trace-gpu-e7fffd0-20260806
      E44_PERF_VENV_CPU=/tmp/fluxon_runtime/venv-fast25-mlp-r123-get-done-stage-trace-cpu-e7fffd0-py311-20260806
      E44_PERF_EXPECTED_PYO3_SHA256=aa93ae7eb9171c1a7410b4685bbadfb5317689b43e0b8e11d5cb9e585d57db06
      E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=9ae25216085dec9c76fe3b7a40451e6510320045eec77032c0838fc6f2ce2f5e
      E44_PERF_EXPECTED_SCHEDULER_SHA256=22e07568bf0c51f0508b1c28b1332810cc147e0197ae1939fbeb5864f5e68d92
      E44_PERF_EXPECTED_SCHEDULE_BATCH_SHA256=8e2777318c67005b4e6f540dc4a9d07661e1cf3784daafc43997c68ebe5f769a
      E44_PERF_HICACHE_PREFETCH_THRESHOLD=64
      E44_PERF_MASTER_RDMA_DEVICE_NAMES=mlx5_4,mlx5_6
    elif [ "$e44_perf_variant" = tier1_independent_005_netobs_enddepth288_fast25_mlp_p14_r125_master_control8_e7fffd0_20260806 ]; then
      E44_PERF_RUN_ID=fast25_mlp_p14_r125_master_control8_e7fffd0_20260806_gdroff_enddepth288_netobs
      E44_PERF_VENV_GPU=/public/zth/sglang_l13_fluxon_v2/venv-fluxon-fast25-mlp-r123-get-done-stage-trace-gpu-e7fffd0-20260806
      E44_PERF_VENV_CPU=/tmp/fluxon_runtime/venv-fast25-mlp-r123-get-done-stage-trace-cpu-e7fffd0-py311-20260806
      E44_PERF_EXPECTED_PYO3_SHA256=aa93ae7eb9171c1a7410b4685bbadfb5317689b43e0b8e11d5cb9e585d57db06
      E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=9ae25216085dec9c76fe3b7a40451e6510320045eec77032c0838fc6f2ce2f5e
      E44_PERF_EXPECTED_SCHEDULER_SHA256=22e07568bf0c51f0508b1c28b1332810cc147e0197ae1939fbeb5864f5e68d92
      E44_PERF_EXPECTED_SCHEDULE_BATCH_SHA256=8e2777318c67005b4e6f540dc4a9d07661e1cf3784daafc43997c68ebe5f769a
      E44_PERF_HICACHE_PREFETCH_THRESHOLD=64
      E44_PERF_MASTER_TCP_CONTROL_LANE_COUNT=8
    elif [ "$e44_perf_variant" = tier1_independent_005_netobs_enddepth288_fast25_mlp_p14_r126_global_control8_e7fffd0_20260806 ]; then
      E44_PERF_RUN_ID=fast25_mlp_p14_r126_global_control8_e7fffd0_20260806_gdroff_enddepth288_netobs
      E44_PERF_VENV_GPU=/public/zth/sglang_l13_fluxon_v2/venv-fluxon-fast25-mlp-r123-get-done-stage-trace-gpu-e7fffd0-20260806
      E44_PERF_VENV_CPU=/tmp/fluxon_runtime/venv-fast25-mlp-r123-get-done-stage-trace-cpu-e7fffd0-py311-20260806
      E44_PERF_EXPECTED_PYO3_SHA256=aa93ae7eb9171c1a7410b4685bbadfb5317689b43e0b8e11d5cb9e585d57db06
      E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=9ae25216085dec9c76fe3b7a40451e6510320045eec77032c0838fc6f2ce2f5e
      E44_PERF_EXPECTED_SCHEDULER_SHA256=22e07568bf0c51f0508b1c28b1332810cc147e0197ae1939fbeb5864f5e68d92
      E44_PERF_EXPECTED_SCHEDULE_BATCH_SHA256=8e2777318c67005b4e6f540dc4a9d07661e1cf3784daafc43997c68ebe5f769a
      E44_PERF_HICACHE_PREFETCH_THRESHOLD=64
      E44_PERF_MASTER_TCP_CONTROL_LANE_COUNT=8
      E44_PERF_TCP_CONTROL_LANE_COUNT=8
    elif [ "$e44_perf_variant" = tier1_independent_005_netobs_enddepth288_fast25_mlp_p14_r128_remote_put_admission16g4096_e7fffd0_20260806 ]; then
      E44_PERF_RUN_ID=fast25_mlp_p14_r128_remote_put_admission16g4096_e7fffd0_20260806_gdroff_enddepth288_netobs
      E44_PERF_VENV_GPU=/public/zth/sglang_l13_fluxon_v2/venv-fluxon-fast25-mlp-r123-get-done-stage-trace-gpu-e7fffd0-20260806
      E44_PERF_VENV_CPU=/tmp/fluxon_runtime/venv-fast25-mlp-r123-get-done-stage-trace-cpu-e7fffd0-py311-20260806
      E44_PERF_EXPECTED_PYO3_SHA256=aa93ae7eb9171c1a7410b4685bbadfb5317689b43e0b8e11d5cb9e585d57db06
      E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=9ae25216085dec9c76fe3b7a40451e6510320045eec77032c0838fc6f2ce2f5e
      E44_PERF_EXPECTED_SCHEDULER_SHA256=22e07568bf0c51f0508b1c28b1332810cc147e0197ae1939fbeb5864f5e68d92
      E44_PERF_EXPECTED_SCHEDULE_BATCH_SHA256=8e2777318c67005b4e6f540dc4a9d07661e1cf3784daafc43997c68ebe5f769a
      E44_PERF_HICACHE_PREFETCH_THRESHOLD=64
      E44_PERF_MASTER_TCP_CONTROL_LANE_COUNT=8
      E44_PERF_TCP_CONTROL_LANE_COUNT=8
      E44_PERF_OWNER_REMOTE_PUT_MAX_INFLIGHT_BYTES=17179869184
      E44_PERF_OWNER_REMOTE_PUT_MAX_INFLIGHT_ITEMS=4096
    elif [ "$e44_perf_variant" = tier1_independent_005_netobs_enddepth288_fast25_mlp_p14_r129_remote_put_admission24g6144_e7fffd0_20260806 ]; then
      E44_PERF_RUN_ID=fast25_mlp_p14_r129_remote_put_admission24g6144_e7fffd0_20260806_gdroff_enddepth288_netobs
      E44_PERF_VENV_GPU=/public/zth/sglang_l13_fluxon_v2/venv-fluxon-fast25-mlp-r123-get-done-stage-trace-gpu-e7fffd0-20260806
      E44_PERF_VENV_CPU=/tmp/fluxon_runtime/venv-fast25-mlp-r123-get-done-stage-trace-cpu-e7fffd0-py311-20260806
      E44_PERF_EXPECTED_PYO3_SHA256=aa93ae7eb9171c1a7410b4685bbadfb5317689b43e0b8e11d5cb9e585d57db06
      E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=9ae25216085dec9c76fe3b7a40451e6510320045eec77032c0838fc6f2ce2f5e
      E44_PERF_EXPECTED_SCHEDULER_SHA256=22e07568bf0c51f0508b1c28b1332810cc147e0197ae1939fbeb5864f5e68d92
      E44_PERF_EXPECTED_SCHEDULE_BATCH_SHA256=8e2777318c67005b4e6f540dc4a9d07661e1cf3784daafc43997c68ebe5f769a
      E44_PERF_HICACHE_PREFETCH_THRESHOLD=64
      E44_PERF_MASTER_TCP_CONTROL_LANE_COUNT=8
      E44_PERF_TCP_CONTROL_LANE_COUNT=8
      E44_PERF_OWNER_REMOTE_PUT_MAX_INFLIGHT_BYTES=25769803776
      E44_PERF_OWNER_REMOTE_PUT_MAX_INFLIGHT_ITEMS=6144
    elif [ "$e44_perf_variant" = tier1_independent_005_netobs_enddepth288_fast25_mlp_p14_r130_remote_put_batch_e02590b_20260806 ]; then
      E44_PERF_RUN_ID=fast25_mlp_p14_r130_remote_put_batch_e02590b_20260806_gdroff_enddepth288_netobs
      E44_PERF_VENV_GPU=/public/zth/sglang_l13_fluxon_v2/venv-fluxon-fast25-mlp-r130-remote-put-batch-gpu-e02590b-20260806
      E44_PERF_VENV_CPU=/tmp/fluxon_runtime/venv-fast25-mlp-r130-remote-put-batch-cpu-e02590b-py311-20260806
      E44_PERF_EXPECTED_PYO3_SHA256=2bd34590f3bb786047108eefe73f24a805e92486c9b4617f9e697bf132045b37
      E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=9ae25216085dec9c76fe3b7a40451e6510320045eec77032c0838fc6f2ce2f5e
      E44_PERF_EXPECTED_SCHEDULER_SHA256=22e07568bf0c51f0508b1c28b1332810cc147e0197ae1939fbeb5864f5e68d92
      E44_PERF_EXPECTED_SCHEDULE_BATCH_SHA256=8e2777318c67005b4e6f540dc4a9d07661e1cf3784daafc43997c68ebe5f769a
      E44_PERF_HICACHE_PREFETCH_THRESHOLD=64
      E44_PERF_MASTER_TCP_CONTROL_LANE_COUNT=8
      E44_PERF_TCP_CONTROL_LANE_COUNT=8
    elif [ "$e44_perf_variant" = tier1_independent_005_netobs_enddepth288_fast25_mlp_p14_r131_tier1_wait_memholder_97ab9f2_20260806 ]; then
      E44_PERF_RUN_ID=fast25_mlp_p14_r131_tier1_wait_memholder_97ab9f2_20260806_gdroff_enddepth288_netobs
      E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-fast25-mlp-r131-tier1-wait-memholder-gpu-97ab9f2-20260806
      E44_PERF_VENV_CPU=/tmp/fluxon_runtime/venv-fast25-mlp-r131-tier1-wait-memholder-cpu-97ab9f2-py311-20260806
      E44_PERF_CUDA_HOME=/usr/local/cuda-12.8
      E44_PERF_CUDA_WHEEL_ROOT=
      E44_PERF_EXPECTED_PYO3_SHA256=eebf07a3461b780e30eb14f069b80d18e0164f49bb0c7cf3fe78f410e710d58a
      E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=9ae25216085dec9c76fe3b7a40451e6510320045eec77032c0838fc6f2ce2f5e
      E44_PERF_EXPECTED_SCHEDULER_SHA256=22e07568bf0c51f0508b1c28b1332810cc147e0197ae1939fbeb5864f5e68d92
      E44_PERF_EXPECTED_SCHEDULE_BATCH_SHA256=8e2777318c67005b4e6f540dc4a9d07661e1cf3784daafc43997c68ebe5f769a
      E44_PERF_HICACHE_PREFETCH_THRESHOLD=64
      E44_PERF_MASTER_TCP_CONTROL_LANE_COUNT=8
      E44_PERF_TCP_CONTROL_LANE_COUNT=8
    elif [ "$e44_perf_variant" = tier1_independent_005_netobs_enddepth288_fast25_mlp_p14_r132_content_depths_compat_0216a00_20260806 ]; then
      E44_PERF_RUN_ID=fast25_mlp_p14_r132_content_depths_compat_0216a00_20260806_gdroff_enddepth288_netobs
      E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-fast25-mlp-r132-content-depths-compat-gpu-0216a00-20260806
      E44_PERF_VENV_CPU=/tmp/fluxon_runtime/venv-fast25-mlp-r132-content-depths-compat-cpu-0216a00-py311-20260806
      E44_PERF_CUDA_HOME=/usr/local/cuda-12.8
      E44_PERF_CUDA_WHEEL_ROOT=
      E44_PERF_EXPECTED_PYO3_SHA256=eebf07a3461b780e30eb14f069b80d18e0164f49bb0c7cf3fe78f410e710d58a
      E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=9ae25216085dec9c76fe3b7a40451e6510320045eec77032c0838fc6f2ce2f5e
      E44_PERF_EXPECTED_SCHEDULER_SHA256=22e07568bf0c51f0508b1c28b1332810cc147e0197ae1939fbeb5864f5e68d92
      E44_PERF_EXPECTED_SCHEDULE_BATCH_SHA256=8e2777318c67005b4e6f540dc4a9d07661e1cf3784daafc43997c68ebe5f769a
      E44_PERF_HICACHE_PREFETCH_THRESHOLD=64
      E44_PERF_MASTER_TCP_CONTROL_LANE_COUNT=8
      E44_PERF_TCP_CONTROL_LANE_COUNT=8
    fi
    ;;
  tier1_independent_005_netobs_enddepth288_gpu_direct_r105_cachesack_depth31)
    # Single-variable treatment over the r105 control: only the inclusive
    # owner-local SSD normal-Put content depth gate changes.
    E44_PERF_RUN_ID=e44_r105_cachesack_depth31_gdroff_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r105_cachesack_depth_enddepth288_netobs.yaml.in
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r105-cachesack-depth-gpu-20260731
    E44_PERF_VENV_CPU=/tmp/fluxon_runtime/venv-r105-cachesack-depth-cpu-py311-20260731
    E44_PERF_EXPECTED_PYO3_SHA256=44671092967510180b23df66c724b79e5875598b17b14bd230323553df82c556
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=223a70eba3e9df3eed09ae3829b1f17b75a5d4d3273bc0af41bc0fb76e30b9a9
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=4d69197532dd6b8efeba7aac48bae97bde44775191a3b2436432fcadc666aa5e
    E44_PERF_EXPECTED_SCHEDULER_SHA256=5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    E44_PERF_SOURCE_ORDER_EVIDENCE=planner_requester_local_fixed
    E44_PERF_GPU_DIRECT_ENABLED=0
    E44_PERF_LOCAL_SSD_EARLY_CONTENT_MAX_DEPTH=31
    ;;
  tier1_independent_005_netobs_enddepth288_r112_post_read_retain)
    # Retain/Drop A/B control. Both arms use the same r112 release, replay,
    # cache geometry, end-depth288 admission, SSD-off and GDR-off runtime.
    E44_PERF_RUN_ID=e44_r112_post_read_retain_gdroff_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r112_post_read_enddepth288_netobs.yaml.in
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r112-post-read-gpu-20260803
    E44_PERF_VENV_CPU=/tmp/fluxon_runtime/venv-r112-post-read-cpu-py311-20260803
    E44_PERF_EXPECTED_PYO3_SHA256=3efd590093ee44abdaa93fa9d359d684a7e5e649d5b4d0f94cf68d8374da593d
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=223a70eba3e9df3eed09ae3829b1f17b75a5d4d3273bc0af41bc0fb76e30b9a9
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=4d69197532dd6b8efeba7aac48bae97bde44775191a3b2436432fcadc666aa5e
    E44_PERF_EXPECTED_SCHEDULER_SHA256=5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    E44_PERF_SOURCE_ORDER_EVIDENCE=planner_requester_local_fixed
    E44_PERF_GPU_DIRECT_ENABLED=0
    E44_PERF_POST_READ_REMOTE_POLICY=retain
    ;;
  tier1_independent_005_netobs_enddepth288_r112_post_read_drop)
    # Single-variable treatment over the r112 retain arm.
    E44_PERF_RUN_ID=e44_r112_post_read_drop_gdroff_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r112_post_read_enddepth288_netobs.yaml.in
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r112-post-read-gpu-20260803
    E44_PERF_VENV_CPU=/tmp/fluxon_runtime/venv-r112-post-read-cpu-py311-20260803
    E44_PERF_EXPECTED_PYO3_SHA256=3efd590093ee44abdaa93fa9d359d684a7e5e649d5b4d0f94cf68d8374da593d
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=223a70eba3e9df3eed09ae3829b1f17b75a5d4d3273bc0af41bc0fb76e30b9a9
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=4d69197532dd6b8efeba7aac48bae97bde44775191a3b2436432fcadc666aa5e
    E44_PERF_EXPECTED_SCHEDULER_SHA256=5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    E44_PERF_SOURCE_ORDER_EVIDENCE=planner_requester_local_fixed
    E44_PERF_GPU_DIRECT_ENABLED=0
    E44_PERF_POST_READ_REMOTE_POLICY=drop
    ;;
  tier1_independent_005_netobs_r112_eager_all_post_read_retain|tier1_independent_005_netobs_r112_eager_all_post_read_drop)
    # Full local-Put remote backing diagnostic. Relative to the paired r112
    # variants, only normal-Put replica admission changes from bounded
    # prefix_end_depth_ratio/288 to the existing eager_all policy. Tier1 5%
    # stays enabled as an idempotent fallback in the shared master config.
    E44_PERF_MASTER_CONFIG=master_config_e44_r112_eager_all_post_read_netobs.yaml.in
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"eager_all"},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r112-post-read-gpu-20260803
    E44_PERF_VENV_CPU=/tmp/fluxon_runtime/venv-r112-post-read-cpu-py311-20260803
    E44_PERF_EXPECTED_PYO3_SHA256=3efd590093ee44abdaa93fa9d359d684a7e5e649d5b4d0f94cf68d8374da593d
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=223a70eba3e9df3eed09ae3829b1f17b75a5d4d3273bc0af41bc0fb76e30b9a9
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=4d69197532dd6b8efeba7aac48bae97bde44775191a3b2436432fcadc666aa5e
    E44_PERF_EXPECTED_SCHEDULER_SHA256=5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    E44_PERF_SOURCE_ORDER_EVIDENCE=planner_requester_local_fixed
    E44_PERF_GPU_DIRECT_ENABLED=0
    case "$e44_perf_variant" in
      tier1_independent_005_netobs_r112_eager_all_post_read_retain)
        E44_PERF_RUN_ID=e44_r112_eager_all_post_read_retain_gdroff_netobs
        E44_PERF_POST_READ_REMOTE_POLICY=retain
        ;;
      tier1_independent_005_netobs_r112_eager_all_post_read_drop)
        E44_PERF_RUN_ID=e44_r112_eager_all_post_read_drop_gdroff_netobs
        E44_PERF_POST_READ_REMOTE_POLICY=drop
        ;;
    esac
    ;;
  tier1_independent_005_netobs_enddepth288_r113_radix_shadow_retain|tier1_independent_005_netobs_r113_eager_all_radix_shadow_retain)
    # Both variants run the same r113 Radix-lineage shadow release. They differ
    # only in normal-Put remote replica admission, so the earlier eager-all
    # diagnostic remains reproducible while end-depth288 restores the baseline.
    case "$e44_perf_variant" in
      tier1_independent_005_netobs_enddepth288_r113_radix_shadow_retain)
        E44_PERF_RUN_ID=e44_r113_enddepth288_radix_shadow_retain_gdroff_netobs
        E44_PERF_MASTER_CONFIG=master_config_e44_r112_post_read_enddepth288_netobs.yaml.in
        E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
        ;;
      tier1_independent_005_netobs_r113_eager_all_radix_shadow_retain)
        E44_PERF_RUN_ID=e44_r113_eager_all_radix_shadow_retain_gdroff_netobs
        E44_PERF_MASTER_CONFIG=master_config_e44_r112_eager_all_post_read_netobs.yaml.in
        E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"eager_all"},"metrics_sample_interval_ms":1000}}'
        ;;
    esac
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r113-radix-shadow-gpu-20260803
    E44_PERF_VENV_CPU=/tmp/fluxon_runtime/venv-r113-radix-shadow-cpu-py311-20260803
    E44_PERF_EXPECTED_PYO3_SHA256=21f4bcf1049d22f5ab50a0b86d30dd0e469f8c136d39489551ea0dbd8fa66a2b
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=223a70eba3e9df3eed09ae3829b1f17b75a5d4d3273bc0af41bc0fb76e30b9a9
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=99b6ad868b3d48f0219aa2e05cf044d69bd5f5d3a7fbf2e8d3568e74e74418a6
    E44_PERF_EXPECTED_SCHEDULER_SHA256=5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    E44_PERF_SOURCE_ORDER_EVIDENCE=planner_requester_local_fixed
    E44_PERF_GPU_DIRECT_ENABLED=0
    E44_PERF_POST_READ_REMOTE_POLICY=retain
    ;;
  tier1_independent_005_netobs_enddepth288_r92_gdr_off_parallel_backing)
    # Exact r91 Fluxon, workload, cache, backing and SSD policy. The new
    # SGLang source keeps the GPU staging pool unconfigured and records every
    # admission as disabled, forcing both A/B arms through CPU/H2D.
    E44_PERF_RUN_ID=e44_r92_gdr_off_parallel_backing_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r91_parallel_backing_enddepth288_netobs.yaml.in
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r92-gdr-off-parallel-backing-gpu-20260727
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r92-gdr-off-parallel-backing-cpu-20260727
    E44_PERF_EXPECTED_PYO3_SHA256=d9404d7ea4cc8002440cd9ad642cfe334b3f01f0c22229261804e0d568249f1c
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=223a70eba3e9df3eed09ae3829b1f17b75a5d4d3273bc0af41bc0fb76e30b9a9
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=eb1e0848c2717e7f59e82f9051ba6dbae1c06793694dd11aaa3d6e93c6c98ccd
    E44_PERF_EXPECTED_SCHEDULER_SHA256=5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    E44_PERF_SSD_READ_SOURCE_POLICY=local_ssd_only_first
    E44_PERF_GPU_DIRECT_ENABLED=0
    ;;
  tier1_independent_005_netobs_enddepth288_r106_regression_r103_adapter)
    # Regression bisection: keep the sealed r103 SGLang adapter/radix/
    # scheduler contract and change only the Fluxon release to r106.
    E44_PERF_RUN_ID=e44_r106_regression_r103_adapter_gdroff_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r91_parallel_backing_enddepth288_netobs.yaml.in
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r106-regression-r103-adapter-gpu-20260803
    E44_PERF_VENV_CPU=/tmp/fluxon_runtime/venv-r106-regression-r103-adapter-cpu-py311-20260803
    E44_PERF_EXPECTED_PYO3_SHA256=697d6c17df50b684ca12b0f7c51ef3921c2d96fa1ba9c50f471bf857234f952f
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=223a70eba3e9df3eed09ae3829b1f17b75a5d4d3273bc0af41bc0fb76e30b9a9
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=eb1e0848c2717e7f59e82f9051ba6dbae1c06793694dd11aaa3d6e93c6c98ccd
    E44_PERF_EXPECTED_SCHEDULER_SHA256=5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    E44_PERF_SSD_READ_SOURCE_POLICY=local_ssd_only_first
    E44_PERF_GPU_DIRECT_ENABLED=0
    ;;
  tier1_independent_005_netobs_enddepth288_r107_regression_r103_adapter)
    # Isolate the first post-r106 product commit while retaining the sealed
    # r103 SGLang adapter/radix/scheduler contract and workload geometry.
    E44_PERF_RUN_ID=e44_r107_regression_r103_adapter_gdroff_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r91_parallel_backing_enddepth288_netobs.yaml.in
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r107-regression-r103-adapter-gpu-20260803
    E44_PERF_VENV_CPU=/tmp/fluxon_runtime/venv-r107-regression-r103-adapter-cpu-py311-20260803
    E44_PERF_EXPECTED_PYO3_SHA256=fe3aa743c27f52b7acd9657a18f3f86f6a0f921b302644cec4ac3f8354afb60a
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=223a70eba3e9df3eed09ae3829b1f17b75a5d4d3273bc0af41bc0fb76e30b9a9
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=eb1e0848c2717e7f59e82f9051ba6dbae1c06793694dd11aaa3d6e93c6c98ccd
    E44_PERF_EXPECTED_SCHEDULER_SHA256=5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    E44_PERF_SSD_READ_SOURCE_POLICY=local_ssd_only_first
    E44_PERF_GPU_DIRECT_ENABLED=0
    ;;
  tier1_independent_005_netobs_enddepth288_r108_regression_r103_adapter)
    # Final adjacent bisection point: r107 plus the unified OffsetAllocator,
    # before r109 adds the fragmented-pool pressure correction.
    E44_PERF_RUN_ID=e44_r108_regression_r103_adapter_gdroff_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r91_parallel_backing_enddepth288_netobs.yaml.in
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r108-regression-r103-adapter-gpu-20260803
    E44_PERF_VENV_CPU=/tmp/fluxon_runtime/venv-r108-regression-r103-adapter-cpu-py311-20260803
    E44_PERF_EXPECTED_PYO3_SHA256=6fd227c8d01836e00383f2c7de5694ab9d3f1e2f8ee6ec3a434b73c97d29bd83
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=223a70eba3e9df3eed09ae3829b1f17b75a5d4d3273bc0af41bc0fb76e30b9a9
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=eb1e0848c2717e7f59e82f9051ba6dbae1c06793694dd11aaa3d6e93c6c98ccd
    E44_PERF_EXPECTED_SCHEDULER_SHA256=5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    E44_PERF_SSD_READ_SOURCE_POLICY=local_ssd_only_first
    E44_PERF_GPU_DIRECT_ENABLED=0
    ;;
  tier1_independent_005_netobs_enddepth288_r109_regression_r103_adapter)
    # Midpoint after r106: cross r107 admission, r108 offset allocator, and
    # r109 fragmentation pressure while retaining the r103 SGLang contract.
    E44_PERF_RUN_ID=e44_r109_regression_r103_adapter_gdroff_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r91_parallel_backing_enddepth288_netobs.yaml.in
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r109-regression-r103-adapter-gpu-20260803
    E44_PERF_VENV_CPU=/tmp/fluxon_runtime/venv-r109-regression-r103-adapter-cpu-py311-20260803
    E44_PERF_EXPECTED_PYO3_SHA256=369970349226300d2371a03fecdcd49efce8128aefff25f1998cca2b6836ef12
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=223a70eba3e9df3eed09ae3829b1f17b75a5d4d3273bc0af41bc0fb76e30b9a9
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=eb1e0848c2717e7f59e82f9051ba6dbae1c06793694dd11aaa3d6e93c6c98ccd
    E44_PERF_EXPECTED_SCHEDULER_SHA256=5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    E44_PERF_SSD_READ_SOURCE_POLICY=local_ssd_only_first
    E44_PERF_GPU_DIRECT_ENABLED=0
    ;;
  tier1_independent_005_netobs_enddepth288_p13_generic_pressure_r103_adapter)
    # Validate the final generic 512 MiB grant and bounded exponential
    # pressure fix while retaining the sealed r103 SGLang contract.
    E44_PERF_RUN_ID=e44_p13_generic_pressure_r103_adapter_gdroff_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r91_parallel_backing_enddepth288_netobs.yaml.in
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-p13-generic-pressure-gpu-20260804
    E44_PERF_VENV_CPU=/tmp/fluxon_runtime/venv-p13-generic-pressure-cpu-py311-20260804
    E44_PERF_EXPECTED_PYO3_SHA256=99ae0b6cb41faa0f53b0ee4a3bf13569ab7050fadd1a0095129181e48d2923de
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=223a70eba3e9df3eed09ae3829b1f17b75a5d4d3273bc0af41bc0fb76e30b9a9
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=eb1e0848c2717e7f59e82f9051ba6dbae1c06793694dd11aaa3d6e93c6c98ccd
    E44_PERF_EXPECTED_SCHEDULER_SHA256=5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    E44_PERF_SSD_READ_SOURCE_POLICY=local_ssd_only_first
    E44_PERF_GPU_DIRECT_ENABLED=0
    ;;
  tier1_independent_005_netobs_enddepth288_p14_burst_reserve_r103_adapter)
    # Keep the p13 workload contract and change only the owner-local physical
    # grant target from 232 logical-payload grants to all 256 physical grants.
    E44_PERF_RUN_ID=e44_p14_burst_reserve_r103_adapter_gdroff_enddepth288_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r91_parallel_backing_enddepth288_netobs.yaml.in
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-p14-burst-reserve-gpu-20260804
    E44_PERF_VENV_CPU=/tmp/fluxon_runtime/venv-p14-burst-reserve-cpu-py311-20260804
    E44_PERF_EXPECTED_PYO3_SHA256=2542b33e9528117e62e28a7d22035a5d2fe57042e01cfe3524a2a06f947b58fe
    E44_PERF_EXPECTED_COMMU_CORE_SHA256=e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_COMMU_CORE_SHA256_CPU=63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06
    E44_PERF_EXPECTED_RDMA_PROBE_SHA256_CPU=e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883
    E44_PERF_EXPECTED_UNIFIED_RADIX_SHA256=223a70eba3e9df3eed09ae3829b1f17b75a5d4d3273bc0af41bc0fb76e30b9a9
    E44_PERF_EXPECTED_HICACHE_FLUXON_SHA256=eb1e0848c2717e7f59e82f9051ba6dbae1c06793694dd11aaa3d6e93c6c98ccd
    E44_PERF_EXPECTED_SCHEDULER_SHA256=5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef
    E44_PERF_HICACHE_BATCH_CONCURRENCY=32
    E44_PERF_DMA_MAX_DESCRIPTORS_PER_CALL=0
    E44_PERF_SSD_READ_SOURCE_POLICY=local_ssd_only_first
    E44_PERF_GPU_DIRECT_ENABLED=0
    ;;
  tier1_independent_005_netobs_get64)
    # Single-variable replay of r28: only Get payload transfer concurrency
    # changes from 32 to 64.
    E44_PERF_RUN_ID=e44_r29_get_batch64_netobs
    E44_PERF_MASTER_CONFIG=master_config_e44_r29_get_batch64_netobs.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":160},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r21-tier1-independent-075-20260719
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r21-tier1-independent-075-20260719
    E44_PERF_EXPECTED_PYO3_SHA256=ab733bf7b9b30b04bfb4e5dee3c4c81435d7251e4b6b62f7bfabfb7ef153e101
    E44_PERF_HICACHE_BATCH_CONCURRENCY=64
    ;;
  tier1_independent_010)
    E44_PERF_RUN_ID=e44_r23_tier1_independent_010
    E44_PERF_MASTER_CONFIG=master_config_e44_r23_tier1_independent_010.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":160},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r21-tier1-independent-075-20260719
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r21-tier1-independent-075-20260719
    E44_PERF_EXPECTED_PYO3_SHA256=ab733bf7b9b30b04bfb4e5dee3c4c81435d7251e4b6b62f7bfabfb7ef153e101
    ;;
  tier1_independent_018)
    E44_PERF_RUN_ID=e44_r24_tier1_independent_018
    E44_PERF_MASTER_CONFIG=master_config_e44_r24_tier1_independent_018.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":160},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r21-tier1-independent-075-20260719
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r21-tier1-independent-075-20260719
    E44_PERF_EXPECTED_PYO3_SHA256=ab733bf7b9b30b04bfb4e5dee3c4c81435d7251e4b6b62f7bfabfb7ef153e101
    ;;
  tier1_independent_025)
    E44_PERF_RUN_ID=e44_r25_tier1_independent_025
    E44_PERF_MASTER_CONFIG=master_config_e44_r25_tier1_independent_025.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":160},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r21-tier1-independent-075-20260719
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r21-tier1-independent-075-20260719
    E44_PERF_EXPECTED_PYO3_SHA256=ab733bf7b9b30b04bfb4e5dee3c4c81435d7251e4b6b62f7bfabfb7ef153e101
    ;;
  tier1_independent_030)
    E44_PERF_RUN_ID=e44_r27_tier1_independent_030
    E44_PERF_MASTER_CONFIG=master_config_e44_r27_tier1_independent_030.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":160},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r21-tier1-independent-075-20260719
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r21-tier1-independent-075-20260719
    E44_PERF_EXPECTED_PYO3_SHA256=ab733bf7b9b30b04bfb4e5dee3c4c81435d7251e4b6b62f7bfabfb7ef153e101
    ;;
  tier1_independent_050)
    E44_PERF_RUN_ID=e44_r26_tier1_independent_050
    E44_PERF_MASTER_CONFIG=master_config_e44_r26_tier1_independent_050.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":160},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r21-tier1-independent-075-20260719
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r21-tier1-independent-075-20260719
    E44_PERF_EXPECTED_PYO3_SHA256=ab733bf7b9b30b04bfb4e5dee3c4c81435d7251e4b6b62f7bfabfb7ef153e101
    ;;
  tier1_075)
    E44_PERF_RUN_ID=e44_r13_tier1_075
    E44_PERF_MASTER_CONFIG=master_config_e44_r13_tier1_075.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":160},"metrics_sample_interval_ms":1000}}'
    ;;
  enddepth288)
    E44_PERF_RUN_ID=e44_r14_enddepth288
    E44_PERF_MASTER_CONFIG=master_config_e44_r14_enddepth288.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    ;;
  r15_enddepth288_selected_credit)
    E44_PERF_RUN_ID=e44_r15_enddepth288_selected_credit
    E44_PERF_MASTER_CONFIG=master_config_e44_r15_enddepth288_selected_credit.yaml
    E44_PERF_REPLICA_TASK_JSON='{"hicache_storage_pass_prefix_keys":true,"replica_task":{"enabled":true,"admission":{"policy":"prefix_end_depth_ratio","admission_ratio":1.0,"min_replica_pages":8,"max_replica_pages_per_batch":288},"metrics_sample_interval_ms":1000}}'
    E44_PERF_VENV_GPU=/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r15-selected-credit-20260718
    E44_PERF_VENV_CPU=/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r15-selected-credit-20260718
    E44_PERF_EXPECTED_PYO3_SHA256=c79cdba41aa3556ec4e9a89743dc1030b8229ce964e283171ea2bde1b5380b37
    ;;
  *)
    echo "unsupported E44 performance variant: $e44_perf_variant" >&2
    return 2 2>/dev/null || exit 2
    ;;
esac

if [ -n "${E44_PERF_RUN_ID_OVERRIDE:-}" ]; then
  if [[ ! "$E44_PERF_RUN_ID_OVERRIDE" =~ ^[a-zA-Z0-9_]+$ ]]; then
    echo "invalid E44_PERF_RUN_ID_OVERRIDE: $E44_PERF_RUN_ID_OVERRIDE" >&2
    return 2 2>/dev/null || exit 2
  fi
  E44_PERF_RUN_ID="$E44_PERF_RUN_ID_OVERRIDE"
fi
