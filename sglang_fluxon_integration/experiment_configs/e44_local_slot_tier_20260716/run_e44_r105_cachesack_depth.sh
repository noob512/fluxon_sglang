#!/usr/bin/env bash
set -euo pipefail

arm="${1:?usage: $0 control|depth31 RUN_ID}"
run_id="${2:?usage: $0 control|depth31 RUN_ID}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

case "$arm" in
  control)
    variant=tier1_independent_005_netobs_enddepth288_gpu_direct_r105_cachesack_control
    ;;
  depth31)
    variant=tier1_independent_005_netobs_enddepth288_gpu_direct_r105_cachesack_depth31
    ;;
  *)
    echo "arm must be control or depth31" >&2
    exit 2
    ;;
esac

exec env \
  E44_CAPACITY_VARIANT="$variant" \
  E44_CAPACITY_CPU_PORT=31505 \
  E44_CAPACITY_CPU_VENV=/tmp/fluxon_runtime/venv-r105-cachesack-depth-cpu-py311-20260731 \
  E44_CAPACITY_ENABLE_SSD=1 \
  E44_CAPACITY_SSD_SCOPE=gpu_local_only \
  E44_CAPACITY_GPU_SSD_BYTES=1649267441664 \
  E44_CAPACITY_GPU_SSD_WRITE_BPS=67108864 \
  E44_CAPACITY_GPU_SSD_WRITE_BURST_BYTES=61341696 \
  E44_CAPACITY_GPU_SSD_CAPACITY_WRITEBACK_ENABLED=false \
  E44_CAPACITY_ACTIVE_CPU_BYTES=266287972352 \
  E44_CAPACITY_WORKLOAD_PREFIX_NAMESPACE=agent_hit50_long_s96_t24_sys8192_v2_e44_r102_cpu31505_remote248_gdroff_gpulocal_ssd24m_a1_retry3_20260730 \
  E44_CAPACITY_EXPECTED_CORPUS_SHA256=a30685c68bdd6003b5de2324d956ed880797715f9734b7632f133fcb1c692789 \
  E44_CAPACITY_ASSISTANT_HISTORY_REPLAY_FILE=/storage/mjq/mooncake_m1/mooncake_perf_workloads/replays/e44_r103_a3_assistant_history_replay.json \
  E44_CAPACITY_ASSISTANT_HISTORY_REPLAY_SHA256=691db563f42f60a00b9b7498c3859c2520eb9856bb774642ade87e1387bf771d \
  E44_CAPACITY_GPU_IDLE_MEMORY_TOLERANCE_MIB=4 \
  E44_CAPACITY_KEEP_BURNERS_STOPPED=1 \
  E44_PERF_GPU_DIRECT_ENABLED=0 \
  bash "$script_dir/run_e44_capacity_knee_profile.sh" \
    100 "$run_id" s96_w2_c24
