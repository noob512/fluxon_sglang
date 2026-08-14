# E44 local slot tier（2026-07-16）

目标是在不改变 GPU0/GPU1/CPU owner `128/128/256 GiB` 容量的前提下，把
local-reserve 从 grant 级让位改成跨全部 grant 的单 KV slot 分级循环，并在与 Mooncake
S96×T24 自然冷跑完全对齐的 workload 下测量 L2+L3 命中率和 QPS。

Mooncake 对齐基线：2304/2304，QPS `6.581393`，L1/L2/L3/总命中
`3.3518%/4.4617%/63.5434%/71.3569%`；目标 L2+L3 为 `68.0051%`。Mooncake
容量已扣除进程内 HiCache L2，三机总 storage budget 与 Fluxon 对齐。

## end-depth 288 attempt1：r32（2026-07-20）

r32 复用已通过 2304/2304 的 r31 release，保持 Get32、tier1 5%、metadata-only
`128/128/256 GiB`、workload 和全部网络观测不变，只把 admission 从
`prefix_depth_ratio/160` 切到 `prefix_end_depth_ratio/288`。

本轮没有形成合法性能结果。约 647 个 router 完整响应后，node0 两个 TP rank 的 99-key
`local_fast_put_start` 持续 `msg_id=4022` timeout；workload 被人工中止，没有 requests/after/summary，
不得登记 QPS 或命中率。

node0 同一批 57 个 exact source-fenced victim 从 `00:31:49 UTC` 起持续被 master 返回 Busy，直到
清场仍未闭合；free slots=`395–429`、pending slots=`0`，且无 refill timeout/OOM。Greptime 显示
master/owners 的 Tokio global queue 始终为 0，排除了 retry RPC 数量导致的 runtime 排队饱和。

r32 前 59 秒 CPU 双 HCA TX=`822.31 GB`，是 r31 相同前 59 秒 `325.92 GB` 的 `2.52×`。这提示
end-depth 可能增加早期 CPU 恢复，但缺 token 终态，不能当成命中收益。下一门禁是归因并关闭
57-key source-fence/master activity 闭环，再原样重跑。

详细分析见
[`20260720_085408_fluxon_kv_r32_enddepth288_attempt1失败分析与下一步.md`](../../20260720_085408_fluxon_kv_r32_enddepth288_attempt1失败分析与下一步.md)，
完整证据见
[`artifacts/e44_r32_enddepth288_attempt1_failed_20260720`](./artifacts/e44_r32_enddepth288_attempt1_failed_20260720/README.md)。

## Get batch64 单变量：r29（2026-07-19）

r29 保持 r28 的 release、tier1 5%、`prefix_depth_ratio/160`、metadata-only
`128/128/256 GiB`、S96×T24 workload、observability 和双 HCA 采样不变，只把 Get
`batch_concurrency=32→64`：

```text
run_id=e44_r29_get_batch64_netobs
run_dir=/storage/mjq/mooncake_m1/mooncake_perf_workloads/results/20260719_122334_agent_multiturn_long_context_fluxon_e44_r29_get_batch64_netobs_s96_t24_sys8192_out8_c24_session_stream_20260719_dac45654
```

| 指标 | r28 Get32 | r29 Get64 | 变化 |
|---|---:|---:|---:|
| Requests / Success / Error | 2304 / 2304 / 0 | 2304 / 2304 / 0 | 不变 |
| QPS | 7.844556385 | 7.615272617 | -2.9228% |
| TTFT p50 / p90 / p99 | 2.054959 / 3.871597 / 9.654660 s | 2.134034 / 4.062147 / 9.798854 s | 全部变差 |
| E2E p50 / p90 / p99 | 2.670252 / 4.702510 / 11.395490 s | 2.810293 / 4.874785 / 11.486272 s | 全部变差 |
| L1 / L2 / L3 | 4.44217 / 0 / 60.49956% | 4.41418 / 0 / 59.54021% | L3 -0.95935pp |
| 总命中 | 64.94173% | 63.95438% | -0.98735pp |

Get64 没有提高物理吞吐。CPU 双 HCA TX 平均/active-average/p99/峰值从 r28 的
`51.130/88.794/262.550/324.775 Gbps` 降为 `48.633/84.650/248.937/314.345 Gbps`；
1s 空闲桶为 `91/303`。因此停止 Get 并发扫描，不测试 48，也不把 64 提升为默认值。

正式窗口 rc=0、2304/2304，refill timeout、P2P 608、OOM 和 panic 均为 0。清场时两侧 GPU
owner 在 `Shutdown Complete` 后发生 shutdown-only destructor panic，已作为独立退出问题登记。

详细分析见
[`20260719_203745_fluxon_kv_r29_Get64单变量测试结果与下一步.md`](../../20260719_203745_fluxon_kv_r29_Get64单变量测试结果与下一步.md)，完整证据见
[`artifacts/e44_r29_get_batch64_netobs_completed_20260719`](./artifacts/e44_r29_get_batch64_netobs_completed_20260719/README.md)。

## Greptime 网络诊断复测：r28（2026-07-19）

r28 复用 r22 的 release、tier1 5%、`prefix_depth_ratio/160`、metadata-only
`128/128/256 GiB` 和 S96×T24 workload，只把 Fluxon observability 打开，并把三节点
`mlx5_4/mlx5_6` 的 500ms 物理计数导入 Greptime：

```text
run_id=e44_r28_r22_netobs_replay
run_dir=/storage/mjq/mooncake_m1/mooncake_perf_workloads/results/20260719_112704_agent_multiturn_long_context_fluxon_e44_r28_r22_netobs_replay_s96_t24_sys8192_out8_c24_session_stream_20260719_34a7784e
```

| 指标 | r22 observability-off | r28 网络诊断 |
|---|---:|---:|
| Requests / Success / Error | 2304 / 2304 / 0 | 2304 / 2304 / 0 |
| QPS | 7.650137995 | 7.844556385 |
| TTFT p50 / p90 / p99 | 2.093514 / 4.170966 / 9.975130 s | 2.054959 / 3.871597 / 9.654660 s |
| E2E p50 / p90 / p99 | 2.735980 / 4.818375 / 11.550333 s | 2.670252 / 4.702510 / 11.395490 s |
| L1 / L2 / L3 | 4.56986 / 0 / 59.28476% | 4.44217 / 0 / 60.49956% |
| 总命中 | 63.85463% | 64.94173% |

r28 是诊断轮，不能用它替代 observability-off r22 的严格性能排名。Greptime 写入
`2148` 个时序点、`816` 个 phase fields，HCA 表写入 `9384` 行，全部 0 error。

Greptime 正式窗内 CPU 双 HCA TX 平均/p99/峰值=`51.130/262.550/324.775 Gbps`，平均只占
800 Gbps 的 `6.39%`；两卡平均=`25.570/25.560 Gbps`，没有 steering 偏载。CPU TX 与两侧
GPU RX 物理字节只差 17280 B。真正明显的是 node1 不对称：node0/node1 的 L3 cached tokens
接近，但 CPU→node1 物理读取是 node0 的 `4.62x`，direct-delete victims 是 `3.97x`；Greptime
owner 日志还两次采到 node1 `finishing_flights=512`，正好顶到 Get finish `4×128` 窗口。

该诊断提出的 Get `batch_concurrency=32→64` 已由 r29 实跑并判定为负收益；r28 仍是 Get32
网络对照基线。详细分析见
[`20260719_195008_fluxon_kv_r28_Greptime网络诊断与下一步.md`](../../20260719_195008_fluxon_kv_r28_Greptime网络诊断与下一步.md)，完整证据见
[`artifacts/e44_r28_r22_netobs_replay_passed_20260719`](./artifacts/e44_r28_r22_netobs_replay_passed_20260719/README.md)。

## tier1 30% 单变量：r27（2026-07-19）

r27 是用户追加的 30% 单变量。它复用 r21 binary 和 r22/r23 的全部固定口径，只改 ratio=`0.30`：

```text
run_id=e44_r27_tier1_independent_030
run_dir=/storage/mjq/mooncake_m1/mooncake_perf_workloads/results/20260719_093650_agent_multiturn_long_context_fluxon_e44_r27_tier1_independent_030_s96_t24_sys8192_out8_c24_session_stream_20260718_a37d755a
```

| 指标 | r22 5% | r23 10% | r27 30% |
|---|---:|---:|---:|
| Requests / Success / Error | 2304 / 2304 / 0 | 2304 / 2304 / 0 | 2304 / 2304 / 0 |
| QPS | 7.650137995 | 7.393700330 | 7.289788870 |
| L1 | 4.56986% | 3.81826% | 4.01428% |
| L2+L3 | 59.28476% | 59.52394% | 58.34688% |
| 总命中 | 63.85463% | 63.34220% | 62.36116% |
| HostKV used after | 0 / 0 | 0 / 0 | 0 / 0 |

30% 相对 10%：QPS `-1.4054%`、L2+L3 `-1.17706pp`；相对 5%：QPS `-4.7104%`、
L2+L3 `-0.93788pp`。CPU retained 也从 10% 的 241.26 GiB 降到 196.13 GiB。结论是窗口继续
放大后写回更晚，吞吐和命中同时变差；30% 不进入后续候选。

完整证据见
[`artifacts/e44_r27_tier1_independent_030_passed_20260719`](./artifacts/e44_r27_tier1_independent_030_passed_20260719/README.md)。

## tier1 小窗口扫描终止：r23 ratio=0.10（2026-07-19）

r23 只把 r22 的 tier1 ratio 从 `0.05` 改为 `0.10`，其他 binary、容量、admission 和 workload
逐字节不变：

```text
run_id=e44_r23_tier1_independent_010
run_dir=/storage/mjq/mooncake_m1/mooncake_perf_workloads/results/20260719_091119_agent_multiturn_long_context_fluxon_e44_r23_tier1_independent_010_s96_t24_sys8192_out8_c24_session_stream_20260718_e2091158
```

| 指标 | r22 5% | r23 10% | 变化 |
|---|---:|---:|---:|
| Requests / Success / Error | 2304 / 2304 / 0 | 2304 / 2304 / 0 | 不变 |
| QPS | 7.650137995 | 7.393700330 | -3.3521% |
| L1 | 4.56986% | 3.81826% | -0.75160pp |
| L2+L3 | 59.28476% | 59.52394% | +0.23917pp |
| 总命中 | 63.85463% | 63.34220% | -0.51243pp |
| HostKV used after | 0 / 0 | 0 / 0 | 不变 |

两侧 tier1 runtime capacity=`13743895347 B`，CPU retained=`54901/259055419392 B`（241.26 GiB）。
正确性和容量闭环通过，但命中收益很小且 QPS 已明显下降。用户据此停止扫描；18%/25%/50% 未
运行，不能登记结果。r19 继续是全历史性能最优，r22 是本次小窗口扫描中 QPS 最好的点。

完整证据见
[`artifacts/e44_r23_tier1_independent_010_passed_20260719`](./artifacts/e44_r23_tier1_independent_010_passed_20260719/README.md)。

## tier1 小窗口扫描：r22 ratio=0.05（2026-07-19）

r22 复用 r21 的逐字节相同 binary、metadata-only `128/128/256 GiB`、depth160 admission 和
S96×T24 workload，只把独立 tier1 ratio 从 `0.75` 改为 `0.05`：

```text
run_id=e44_r22_tier1_independent_005
run_dir=/storage/mjq/mooncake_m1/mooncake_perf_workloads/results/20260719_085023_agent_multiturn_long_context_fluxon_e44_r22_tier1_independent_005_s96_t24_sys8192_out8_c24_session_stream_20260718_94e89ced
```

| 指标 | r21 0.75 | r22 0.05 | r22 相对 r21 |
|---|---:|---:|---:|
| Requests / Success / Error | 2304 / 2304 / 0 | 2304 / 2304 / 0 | 不变 |
| QPS | 7.370114467 | 7.650137995 | +3.7994% |
| TTFT p50 / p90 / p99 | 2.061381 / 4.454487 / 9.878182 s | 2.093514 / 4.170966 / 9.975130 s | — |
| E2E p50 / p90 / p99 | 2.720383 / 5.564537 / 11.841482 s | 2.735980 / 4.818375 / 11.550333 s | — |
| L1 | 3.99133% | 4.56986% | +0.57853pp |
| L2+L3 | 58.10273% | 59.28476% | +1.18203pp |
| 总命中 | 62.09407% | 63.85463% | +1.76056pp |
| HostKV used after | 0 / 0 | 0 / 0 | 不变 |

两侧 tier1 runtime capacity 都是 `6871947673 B`（约 6.4 GiB），CPU retained 恢复为
`55341/261131599872 B`（243.20 GiB），说明“小窗口恢复早写回”的假设成立。但 r22 的 QPS 和
L2+L3 仍分别低于 r19 `3.7118%` 和 `2.18504pp`，所以它还不是新最优。

本轮 direct-delete requests/victims/completed/retryable=`1536/433310/433309/1`；唯一 busy 项已使
owner retry 状态收敛。两侧 active、pending、selected、retry、debt、selected bytes 和 master
in-progress 终态均为 0；completion missing、refill timeout、P2P 608、OOM、scheduler exception 和
正式业务错误均为 0。结果后完整停栈并恢复 managed burner。

完整证据见
[`artifacts/e44_r22_tier1_independent_005_passed_20260719`](./artifacts/e44_r22_tier1_independent_005_passed_20260719/README.md)。

该轮之后只运行了 r23 ratio=`0.10`；因 QPS 下降，后续 `0.18/0.25/0.50` 已取消。

## 当前代码验收：E44 r21 tier1 独立容量 0.75（2026-07-19）

r21 修复了 tier1 被 ring-B local-reserve reservation 错误裁剪的问题。固定配置和 workload 与 r20
完全相同，唯一核心行为变化是 tier1 从实际 5.60 GiB 恢复为名义 96 GiB：

```text
run_id=e44_r21_tier1_independent_075
run_dir=/storage/mjq/mooncake_m1/mooncake_perf_workloads/results/20260719_080636_agent_multiturn_long_context_fluxon_e44_r21_tier1_independent_075_s96_t24_sys8192_out8_c24_session_stream_20260718_f01f6126
```

| 指标 | r20 | r21 | r21 相对 r20 |
|---|---:|---:|---:|
| Requests / Success / Error | 2304 / 2304 / 0 | 2304 / 2304 / 0 | 不变 |
| QPS | 7.742272953 | 7.370114467 | -4.8068% |
| L1 | 4.47799% | 3.99133% | -0.48666pp |
| L2+L3 | 60.51801% | 58.10273% | -2.4153pp |
| 总命中 | 64.99600% | 62.09407% | -2.9019pp |
| HostKV used after | 0 / 0 | 0 / 0 | 不变 |

修复本身已通过：两侧 tier1 runtime capacity 都是 `103079215104 B`，ring-B 仍为
`6012954214 B`；`128/128/256 GiB`、grants=`232/232`、metadata-only HostKV 和 RDMA
`peer_count=2` 均满足门禁。direct-delete 完成 `199854` 个 victims，全部临时态收敛，fatal=0。

性能负收益来自策略语义：tier1 是远端写回触发窗口，不是额外物理容量。窗口从 5.60 GiB 放大到
96 GiB 后，trigger 合计从 `98184` 降到 `8279`，remote transfers 从 `94796` 降到 `56120`，CPU
最终 backing 少 `11932` 项/`52.44 GiB`；删除最后 route 反而增加 `60.01%`。所以 r19/r20 的收益
来自小窗口早写回，而不是名义 ratio `0.75`。r21 是当前代码正确性验收版，但 r19 仍是性能最优。

完整证据见
[`artifacts/e44_r21_tier1_independent_075_passed_20260719`](./artifacts/e44_r21_tier1_independent_075_passed_20260719/README.md)。

## 当前代码正确性验收：E44 r20 owner remote-Put singleflight（2026-07-19）

r20 使用与 r19 完全相同的 tier1 0.75 配置、metadata-only `128/128/256 GiB` 容量、depth160
admission 和固定 workload，只更换为当前 owner remote-Put singleflight release：

```text
run_id=e44_r20_owner_remote_put_singleflight_tier1_075
run_dir=/storage/mjq/mooncake_m1/mooncake_perf_workloads/results/20260719_063143_agent_multiturn_long_context_fluxon_e44_r20_owner_remote_put_singleflight_tier1_075_s96_t24_sys8192_out8_c24_session_stream_20260718_8f258dd9
```

| 指标 | r19 性能最优 | r20 当前代码 | r20 相对 r19 |
|---|---:|---:|---:|
| Requests / Success / Error | 2304 / 2304 / 0 | 2304 / 2304 / 0 | 不变 |
| QPS | 7.945039507 | 7.742272953 | -2.5521% |
| L1 | 4.4392% | 4.47799% | +0.03879pp |
| L2+L3 | 61.4698% | 60.51801% | -0.95179pp |
| 总命中 | 65.9090% | 64.99600% | -0.91300pp |
| HostKV used after | 0 / 0 | 0 / 0 | 不变 |

r20 的正确性目标已达成：node0/node1/master 的
`Put append operation not found for completion` 均为 0，修复了 r19 的 `701/1250`；两侧实际聚合
`742/1274` 个 followers，按单 KV slot 估算避免约 `8.859375 GiB` 重复 payload。direct-delete
`1724` 批完成 `536540/536540` victims，retryable=0，drain 后所有临时态归零，fatal=0。

r20 没有超过 r19 的 QPS 和命中率，所以它是当前代码正确性验收版，不替换下面的 r19 性能最优。
当前仍有 node0/node1=`14780/28443` 次 source unavailable/tier1 failed，以及 `278/696` 次
`load_back produced no prefix tokens`；L2+L3 距 Mooncake 仍差 `7.4871pp`。

完整证据见
[`artifacts/e44_r20_owner_remote_put_singleflight_tier1_075_passed_20260719`](./artifacts/e44_r20_owner_remote_put_singleflight_tier1_075_passed_20260719/README.md)。

## 当前最佳已测策略：E44 r19 tier1 0.75（2026-07-19）

r19 完全复用 r18 release、metadata-only `128/128/256 GiB` 公平容量、depth160 admission 和标准
workload；唯一行为变量是 master 增加
`replica_writeback_tier1_capacity_ratio: 0.75`：

```text
variant=direct_delete_singleflight_tier1_075
run_id=e44_r19_direct_delete_singleflight_tier1_075
run_dir=/storage/mjq/mooncake_m1/mooncake_perf_workloads/results/20260719_025940_agent_multiturn_long_context_fluxon_e44_r19_direct_delete_singleflight_tier1_075_s96_t24_sys8192_out8_c24_session_stream_20260718_eae5e66a
```

| 指标 | r18 baseline | r19 tier1 0.75 | r19 相对 r18 |
|---|---:|---:|---:|
| Requests / Success / Error | 2304 / 2304 / 0 | 2304 / 2304 / 0 | 不变 |
| QPS | 7.381347613 | 7.945039507 | +7.64% |
| L1 | 3.8628% | 4.4392% | +0.5764pp |
| L2+L3 | 58.9025% | 61.4698% | +2.5673pp |
| 总命中 | 62.7652% | 65.9090% | +3.1438pp |
| HostKV used after | 0 / 0 | 0 / 0 | 不变 |

r19 fatal=0，direct-delete `1857` 批处理 `579691` victims，drain 后临时态归零并已完整停栈。
它是当前最佳已测策略，但 L2+L3 仍比 Mooncake `68.0051%` 低 `6.5353pp`，还不是命中达标版本。

配置 `0.75` 的名义窗口是 96 GiB，但本轮运行时按
`min(0.75 × node_space_size, ring-B effective capacity)` 被 local-reserve reservation 裁剪为每侧
`6,012,954,214 bytes`（5.60 GiB）。两侧均保留 `1274 entries / 6,011,486,208 bytes`。此外
node0/node1 分别有 `701/1250` 次 `Put append operation not found for completion`，未造成请求失败，
但说明提前写回并发下仍有重复或过期 completion 竞争。

完整证据见
[`artifacts/e44_r19_direct_delete_singleflight_tier1_075_passed_20260719`](./artifacts/e44_r19_direct_delete_singleflight_tier1_075_passed_20260719/README.md)。

## 公平参考基线：E44 r18 direct-delete + Put singleflight（2026-07-19）

r18 覆盖当前单 KV 容量驱逐代码，取代 r16 成为正式公平 metadata-only 基线。本轮没有开启
tier1、end-depth 288 或 load-back 新优化，容量与标准 workload 均保持不变：

```text
variant=direct_delete_singleflight_baseline
run_id=e44_r18_direct_delete_singleflight_metadata_baseline
run_tag=fluxon_e44_r18_direct_delete_singleflight_metadata_baseline_s96_t24_sys8192_out8_c24_session_stream_20260718
run_dir=/storage/mjq/mooncake_m1/mooncake_perf_workloads/results/20260718_172744_agent_multiturn_long_context_fluxon_e44_r18_direct_delete_singleflight_metadata_baseline_s96_t24_sys8192_out8_c24_session_stream_20260718_156ec80d
```

观测结果（无 GPU burner）：

| 指标 | r18 |
|---|---:|
| Requests / Success | `2304 / 2304` |
| Error count | `0` |
| QPS | `7.381347613` |
| TTFT p50 / p90 | `2.053462s / 4.704732s` |
| E2E p50 / p90 / p99 | `2.733280s / 6.029544s / 11.605175s` |
| L1 / L2 / L3 | `3.8628% / 0.0000% / 58.9025%` |
| L2+L3 | `58.9025%` |
| Overall hit | `62.7652%` |
| HostKV used after（node0/node1） | `0 / 0 tokens` |

门禁状态：

- direct-delete 869 批、188066 victims，其中 868 批 `victims>1`；completed=188062、
  retryable busy=4，max/avg batch=`776/216.42`；
- 两侧 owner Prepare/Commit/Finalize=`0/0/0`；drain 后 selected/retry/debt/selected bytes 全为 0；
- `refill timeout`、`P2P(code=608)`、prefill OOM、scheduler exception、Put conflict retry exhausted
  均为 0；
- grants 保持 `232/232`，HostKV used after 为 `0/0`，没有通过扩容或额外 HostKV 容量过关；
- workload 前、中、后 burner 均为 0；结果落盘后实验栈与 burner watchdog 已全部停止。

以 r18 为参考得到的后续状态：

- r18 QPS 比 Mooncake 高 `12.15%`，但 L2+L3=`58.9025%` 低 `9.10pp`；它继续作为不启用 tier1
  的公平对照，不再是当前最高命中结果。
- 真实 workload 没有触发 Put follower reuse；singleflight 由本地 leader 成功/失败定向测试覆盖。
- tier1 `0.75` 已由 r19 有效跑完；下一候选为从 r18 独立派生的
  `prefix_end_depth_ratio=288 + batch64`。L2+L3 未达到 `68.0051%` 前不开始 load-back 优化。
- 完整证据见
  [`artifacts/e44_r18_direct_delete_singleflight_metadata_baseline_passed_20260719`](./artifacts/e44_r18_direct_delete_singleflight_metadata_baseline_passed_20260719/README.md)。

E44 当前机制：

- 所有 grant 的 committed KV slot 统一进入一个 owner-hot Moka；grant 只作为 512 MiB
  物理容器，不作为 KV 驱逐单位。
- owner slot pressure 通过 pin-aware Moka 选择非 pinned 候选；Moka 只负责“pop/提名”，不表示
  物理 slot 已释放。
- owner 逐个 pop 单 KV、逐个校验并安装精确 source fence，只按成功 fenced bytes 累计；覆盖空间
  缺口后，一次把这批 victims 交给 master direct-delete。
- master 在一个 handler 内逐项核对并删除精确 source route，最后一次性返回整批结果向量；传输
  batch 不定义容量 victim 边界，也不会被拆成逐 victim 串行 Prepare/Commit/Finalize。
- `atomic_batch` 只负责 put/get 同请求聚合与结果发布原子性，不展开容量兄弟 KV。
- proactive CPU replica 是独立命中率优化，成功与否不再作为 GPU source-delete/Free 的前置条件。
- 后续 Put/Get 从整个 local-reserve pool 的 Free slot 中领取，可跨 grant 复用；不等待
  整个 grant 变空，也不改变 expected grant 数或 owner 容量。
- local-first Put 与 prepared-slot Get 都在 master route 和 resident Moka 同步发布后才
  promotion/hot admission；GetDone 使用相同 get id 重试幂等终态。

固定首轮配置沿用 E42：depth160、owner-hot `0.90`、replica batch/inflight `64`、
200k token pool、overlap scheduler、96 sessions × 24 turns、concurrency 24、
session-stream、自然冷跑。

## pre-singleflight bring-up：无效，不计 QPS（2026-07-16）

- router 收到 `2304` 个 POST，仅 `2283` 个进入 duration 终态；两个 SGLang
  实例在 after-metrics 抓取前退出，workload `rc=1`，因此没有可验收的 QPS 或
  L1/L2/L3 命中率。
- GPU0/GPU1 owner 分别记录 `33/77` 次
  `prepared local-reserve Get target cannot replace a live replica`；SGLang 两侧又分别
  看到 `15/6` 次 `prepared local-reserve Get target could not publish current route`。
- GPU0/GPU1 SGLang 分别有 `175/184` 次
  `load_back produced no prefix tokens`，已被 master 计为命中的前缀在 prepared target
  竞争后回退为重算。
- node1 最终错误是 local-reserve refill 等待 `10001 ms` 后超时：
  `slot_size=4718592 key_count=89 remaining_slots=1 used_slots=28840 free_slots=88`，grant 已从
  expected `232` 扩到 `256`。这证明重叠 batch 的重复 prepared Get 不仅损失
  命中，还会同时消耗 local slots 并放大 refill 压力。
- node0 在 peer 退出后于 TP prefetch collective 收到
  `Connection closed by peer`，属于 node1 首发失败的连锁终止，不是独立的有效性能结果。

修复契约为设计文档 G1--G9：owner 对 required batch 与 local-visible/inflight
做逐 key 原子分流和 pin，但把差集 leaders 仍压缩成 BatchGetStart/transfer/
BatchGetDone，再按原 index 和 atomic-group 边界重组。修复后必须在同一负载下
重跑，且上述两类 prepared-target 竞争错误、refill timeout、业务失败和
SGLang 退出均为 0，才能记录 QPS/命中率。

## E44 r1 per-key singleflight：无效，不计 QPS（2026-07-16）

run tag：

```text
fluxon_e44_perkey_singleflight_s96_t24_sys8192_out8_c24_session_stream_depth160_hot090_pipe64_20260716_r1
```

结果目录：

```text
/storage/mjq/mooncake_m1/mooncake_perf_workloads/results/20260716_092239_agent_multiturn_long_context_fluxon_e44_perkey_singleflight_s96_t24_sys8192_out8_c24_session_stream_depth160_hot090_pipe64_20260716_r1_b397e18b
```

- workload `rc=1`，没有可验收 QPS。router 收到 2304 个请求，但 GPU0 SGLang 在
  after-metrics 前退出，GPU1 detokenizer 心跳停在 `09:26:33`。
- 本轮 `cannot replace a live replica` 和 `could not publish current route` 均为 0，
  因而 pre-singleflight bring-up 的 overlap 竞争已不再是本次失败原因。
- node1 末期 local-reserve 接近压满：`used_slots≈28864`、`free_slots≈64`、
  `pending_slots=256`、`grants=256`，最终触发 10 秒 refill timeout。
- owner-hot 记录 `size_evictions=3022`、`replica_enqueued=2758`，但只有
  `replica_completed=280`；`group_trigger_incomplete=2629`。master 同期记录
  `demotion_attempts=2748`、`demotion_cohorts=1`、`demotion_precheck_rejected=2340`。
  这表明 hot Moka 已经选择冷 key，但不完整 atomic/TP cohort 的 eviction event 被直接
  丢弃；对应 resident slot 离开 hot cache 后仍保留 live route，无法回到 Free。
- backlog 超过 120 秒后，旧 handle TTL 又把仍待消费的合法 Get handle 清掉，随后出现
  `external_get_start_handle:205...`。三机 `memory.events oom_kill=0`，本轮不是 OOM。
- CPU owner 的首次启动失败来自启动顺序：它在 GPU owner 出现前等待 300 秒后报
  `no eligible owner peers`。GPU owner 已在线后重启 CPU 即正常。后续顺序固定为
  master → 两个 GPU owner/SGLang → CPU owner → router。

## E44 r2 修复与开跑门禁

- 不完整 cohort 的 Moka size eviction 不再丢弃。owner 至少把触发 key送入已有的
  时间窗批量 replica actor；master 仍只在完整 cohort 可恢复后统一 demote，不放松 S3/S4
  正确性门禁。
- external Get handle TTL 从 120 秒提高到 360 秒，覆盖对齐 workload 的 300 秒合法请求窗口。
- local-reserve 默认 hard timeout 从 10 秒提高到 30 秒。它只把短时 remote write-back
  压力转成有界背压，不修改 owner、Moka 或 expected-grant 容量。
- 新增不完整 cohort fallback 定向测试；`cargo check -p fluxon_kv --lib`、owner-hot 11 项、
  local-reserve 4 项以及 `fluxon_kv` 全量 `136/136` tests 均通过。

r2 仍使用同一 2304 请求自然冷跑。验收要求为：2304/2304、两个 SGLang 不退出、
refill timeout/Get handle 过期/两类 prepared-target 竞争均为 0，并记录完整分层命中率、
QPS、CPU source Get、owner-hot replica/demotion 与最终 slot 对账。目标 Fluxon L2+L3
不低于 Mooncake 的 `68.0051%`。

## E44 r2 实测：TP transfer 终态分歧，无效（2026-07-16）

结果目录：

```text
/storage/mjq/mooncake_m1/mooncake_perf_workloads/results/20260716_103116_agent_multiturn_long_context_fluxon_e44_r2_owner_hot_fallback_s96_t24_sys8192_out8_c24_session_stream_depth160_hot090_pipe64_20260716_1f89ae56
```

- workload `rc=1`，两个实例约完成 `571/541` 个请求后冻结，因此没有可验收 QPS。
- owner-hot fallback 已实际触发：GPU0 一度记录 `size_evictions=20944`、
  `replica_enqueued=50561`；master 出现数百个完整 demotion cohort 和大量单 slot reclaim，
  free slots 能从压力区恢复，prepared-target 竞争、handle 过期和 refill timeout 均为 0。
- 同一请求 `1a624a2387d847049e32f5b5fb93de4c` 的两个 TP rank 已在 GetStart 后收敛到
  `256` pages，但 `get_transfer` 终态分歧：TP1 成功并提交 `16384` tokens restore，TP0
  收到 `P2P(code=608)` 并按 cache miss 重算。两 rank 的 radix/batch 状态由此分裂，最终
  collective 卡死。

## E44 r3 TP prepare commit 门禁

- `get_transfer` 后增加 TP SUM commit gate。只有 `prepared_ranks == tp_world_size` 才把
  restore plan 发布到 radix/load-back；任一 rank 失败时，所有 rank 都 release/cancel plan，
  统一记录 0-token cache miss，禁止单 rank restore。
- 开启 `iceoryx_external_busy_poll=true`，降低本地 RPC signal delivery 延迟和 P2P 608 风险；
  其余容量、workload、scheduler、owner-hot 和 replica pipeline 参数完全保持 r2 不变。
- r3 SGLang artifact SHA256：
  `0a71734f14eada7933e95819c8c918b6ef9a9320e81df0ed9617fcf0ceff77e4`。

## E44 r3 实测：门禁生效，但 GetStart 仍可杀进程（2026-07-16）

结果目录：

```text
/storage/mjq/mooncake_m1/mooncake_perf_workloads/results/20260716_105918_agent_multiturn_long_context_fluxon_e44_r3_tp_prepare_commit_busy_poll_s96_t24_sys8192_out8_c24_session_stream_depth160_hot090_pipe64_20260716_2ffdd36c
```

- workload `rc=1`，router 已接收全部 `2304` 个 POST，但只有 `1713` 个 200；GPU0 在
  `get_start -> BatchGetStart(3045)` 的 P2P 608 上抛出 scheduler exception 并退出，after-metrics
  随后因 31001 connection refused 失败，因此没有合法 QPS。
- TP prepare commit gate 已被真实执行。GPU1 多次 `get_transfer -> 4032` 同时失败时，两个 rank
  都记录 `prepared_ranks=0/tp_world_size=2`，统一把 restored tokens 置 0 后继续重算，没有再出现
  r2 的一侧 restore、一侧 miss。
- external busy-poll 消除了 notifier 告警，但没有消除本轮 3045/4032 RPC deadline；它不能替代
  cache-miss 级错误处理。
- GPU owner 的 reclaim commit 还暴露出一个独立 assert：Prepare 已隐藏 local index 后，新的
  external Get 会被强制走 remote 路径，但它仍在同一个 key control 中留下 singleflight marker；
  commit 原先错误地要求 marker 必须为空并 panic。该 remote marker 不持有 prepared local backing，
  所以 r4 只禁止跨 fence 的 local Put，允许 remote Get marker 与 commit 并存。

## E44 r4 修复范围

- 初次 `get_start`、TP common-prefix retry 和 Mamba `get_start` 的 transport error 都降级为本 rank
  0-page miss，再由已有 TP MIN/MAX 门禁统一取消其它 rank 的 handle；不再把远端缓存暂时不可用
  传播成 SGLang 进程退出。
- 保留 r3 的 `get_transfer` TP commit gate。
- 修复 reclaim commit 与 remote-only external Get marker 的合法并发，并增加定向单测。
- master、GPU owner/client、CPU owner 的 sync RPC handler 数统一从默认 4 提到 8，用于验证
  本轮高控制面并发下 3045/4032 deadline 是否来自 handler 饥饿；容量和 workload 不变。

## E44 r5 Get lifecycle 收口（2026-07-16）

r5 保留 r4 的 SGLang TP 门禁、RPC8、owner-hot 与固定 `128/128/256 GiB` 容量，只收口
Fluxon Get 生命周期，不引入通用 SGLang 吞吐优化：

- exact-batch shared-op 已删除，external handle 直接持有 request-local BatchPlan；不同 batch
  的重叠 keys 只通过 per-key flight 合流，leader keys 仍批量执行 BatchGetStart/Done/Revoke。
- task abort 会通过 `ExternalGetKeyInterest::Drop` 归还 `undecided` 并唤醒 flight；cohort executor
  在第一个网络 await 前移交 owner task registry，调用方取消不会丢失 executor。
- BatchGetStart 完全无响应时，prepared slots 隔离 65 秒后才释放，覆盖 master 60 秒 inflight
  TTL；已返回 get ids 的异常响应交给独立 Revoke cleanup。
- BatchGetDone 不再三次失败后遗留 pending-visible slot，而是用相同 get ids 幂等重试到严格匹配
  的逐项 identity 或 owner shutdown。
- 每 30 秒记录 active handles、Starting/Finishing/Revoking flights、undecided/retained，以及
  Free/Prepared/Pending/Committed reserve slots；三机 workload 结束后以临时态归零为验收项。

本地验证使用 `/dev/shm/mjq_fluxon_target_20260716`，避开 Ceph target 链接阻塞：定向测试
`7 + 1` 全过；`fluxon_kv --lib` 为 `138 passed, 1 failed`，唯一失败是既有
`test_memholder_pin` 等待 `owner_hold` weak allocation drop 超时，与 Get 改动无关。

r5 release：`Fluxon/fluxon_release_e44_r5_get_lifecycle_20260716`。当前 GPU0 公网端口
31408 仍为 `Connection refused`，GPU1 30245 和 CPU 30729 正常，因此三机 r5 尚未启动，
不得记录 QPS。

## E44 r6 精确定点 demotion 与容量闭环修复：已构建/待实测（2026-07-17）

r6 保持 r5 的 GPU0/GPU1/CPU owner `128/128/256 GiB`、owner-hot `0.90`、
replica batch/inflight `64`、RPC8、200k token pool 和 overlap scheduler 不变。workload 仍是
S96×T24、2304 requests、concurrency 24、session-stream、零 think-time 的单轮自然冷跑；
不做预热，不修改 owner 容量。

r6 的实验隔离命名为：

- release：`Fluxon/fluxon_release_e44_r6_point_demotion_20260716`
- GPU/master venv：`venv-fluxon-e44-r6-20260716`
- CPU venv：`venv-fluxon-e44-r6-20260716`
- owner/SGLang/router session、日志 suffix、HiCache key prefix 和 run tag 均使用 `e44_r6`

2026-07-17 使用当前 Fluxon 工作树完成宝宝盘单并发构建。本机
`fluxon_kv --lib` 为 `176/176`，PyO3 debug check 与 release 构建通过；
manylinux wheel 在 CPython 3.10/3.11/3.12 的 abi3 import probe 全部通过。

产物位于：

```text
/media/infra44/宝宝盘2/mjq_build/fluxon_current_release_20260717
```

启动门禁哈希已固化到 r6 GPU/CPU launcher：

- unified wheel: `20ae712eaafc5a25d9d8af7a6f18d69144f6c97bee1dfce79bbf909e8f3c3250`
- `fluxon_pyo3.abi3.so`: `55e7ca8b9c49f7a47b9f717e47214d6e780b200e10e9ac12ba408fad1891fd9e`
- `libfluxon_commu_core.so`: `bfa6a32d991f6b6adf0f5175c07ed7da8290d1ed2a7ef4148b3a5f8b13452503`
- `libfluxon_rdma_probe.so`: `e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883`

## E44 r9 direct source-delete：有效三机自然冷跑（2026-07-17）

r9 使用当前未提交 Fluxon 工作树，不覆盖 r8。标准 release 完整脚本返回 `0`，CPython
3.10/3.11/3.12 abi3 import probe、closed runtime 注入和 `fluxon_release.sha256` 全部通过。
部署门禁哈希为：

- unified wheel：`bc6bf39172549ea5322568b4c9459a0335cab1e4fe7d4b5de73221002937b14e`；
- `fluxon_pyo3.abi3.so`：`1ed69cf9f33924d42d32a9fb8dea46dede62167b15c1ff83b5c4b58352941e2d`；
- `libfluxon_commu_core.so`：`bfa6a32d991f6b6adf0f5175c07ed7da8290d1ed2a7ef4148b3a5f8b13452503`；
- `libfluxon_rdma_probe.so`：`e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883`。

可复现路径：本机构建 release 位于
`/media/infra44/宝宝盘2/mjq_build/fluxon_direct_source_20260717_final`，三机共享副本位于
`/storage/mjq/sglang_fluxon/releases/fluxon_e44_r9_direct_source_20260717`；GPU/master venv 为
`/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r9-20260717`，CPU venv 为
`/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r9-20260717`。r9 的 cluster、master、
GPU、CPU、router 和 workload launcher 均在本目录以 `e44_r9` 隔离命名。

实验保持 GPU0/GPU1/CPU=`128/128/256 GiB`、GPU 各 `232` grants / `26,216`
slots、S96×T24、concurrency 24、session-stream、零 think-time、无预热。正式流量前才停止
两机 burner，流量结束后立即恢复 watchdog 管理态。第一次 workload 进程在发请求前因恢复后
缺少 node0→node1 内网 SSH key 退出，不产生请求、不计实验轮次；补回 runbook 规定的
`id_ed25519_node1_internal` 后，以相同冷栈完成有效轮。

run tag：

```text
fluxon_e44_r9_direct_source_delete_s96_t24_sys8192_out8_c24_session_stream_depth160_hot090_pipe64_20260717
```

结果目录：

```text
/storage/mjq/mooncake_m1/mooncake_perf_workloads/results/20260717_121256_agent_multiturn_long_context_fluxon_e44_r9_direct_source_delete_s96_t24_sys8192_out8_c24_session_stream_depth160_hot090_pipe64_20260717_a4d4df21
```

有效结果：

- 请求 `2304/2304` 成功，error/4xx/5xx=`0`；QPS `5.609336`，输出
  `44.8065 tok/s`；
- TTFT p50/p90/p99=`2.973/7.758/10.746s`，E2E p50/p90/p99=
  `3.886/8.840/12.361s`；
- L1/L2/L3/总命中=`5.4060%/0%/54.6878%/60.0939%`；
- master 只把 proactive replica 放到 CPU owner，共 `77,384` 个；GPU0/GPU1 requester
  分别从 CPU source 读取 `103,922/80,001` 个 key，合计 `183,923` 个、
  `867,857,596,416` bytes（`808.26 GiB`），证明 CPU 节点实际参与命中；
- GPU0/GPU1 `source_evict_committed_members=130,540/145,888`，均与 handoff 相等；
  `source_evict_dispatch_failed=0`，最终 `source_eviction_selected=0`、
  `source_evict_retry_entries=0`、`selection_debt_bytes=0`；
- 最终 slots 为 GPU0 `Free/Prepared/Pending/Committed=466/0/0/25,750`、GPU1
  `488/0/0/25,728`，两侧始终 `grants=expected_grants=232`，没有扩大 owner 容量；
- 最终 active handles/flights/undecided/retained 全为 `0`；refill timeout、P2P error、
  panic、OOM、scheduler exception 均为 `0`，两侧 SGLang 与三位 owner 均保持存活。

日志中 node0/node1 有 `194/1300` 条 TP-rank 级 `load_back produced no prefix tokens`。
逐项分类表明它们全部是当前已无可读 route 时的 `recoverable_error_kind=not_ready`：所有真正
提交的 Fluxon prefetch 都以非零 prefix 成功（TP 日志 `2008/1902` 条），
TP prepare reject、GetStart/transfer error 均为 `0`。因此这是允许删除最后一份 cache
route 后的正常 miss/recompute，不是 prepared-slot、singleflight 或 RDMA 正确性失败。

相对本文件 Mooncake 对齐基线，r9 QPS 低 `14.77%`，总命中低 `11.26pp`，L2+L3 低
`13.32pp`。正确性和 owner 容量闭环已验收；剩余差距来自 proactive CPU replica 覆盖率和
实际 cache miss，不应重新把 CPU writeback 成功设为 source-delete/Free 的前置条件。

## E44 r10 公平容量 high-water pressure：失败，不计正式 QPS（2026-07-17）

r10 首次把容量改成公平的 GPU0/GPU1 owner=`96/96 GiB`、HiCache L2=`32/32 GiB`、
CPU owner=`256 GiB`，合计精确 `512 GiB`。两侧 owner 均为 `174/174 grants`、
`19,662 slots`，没有扩大 owner 容量。workload 保持 S96×T24、2304 requests、
concurrency 24、session-stream、无预热；正式流量前停止 burner，失败清理后已恢复 burner。

run tag：

```text
fluxon_e44_r10_highwater96_s96_t24_sys8192_out8_c24_session_stream_depth160_hot090_pipe64_20260717
```

失败结果目录：

```text
/storage/mjq/mooncake_m1/mooncake_perf_workloads/results/20260717_134544_agent_multiturn_long_context_fluxon_e44_r10_highwater96_s96_t24_sys8192_out8_c24_session_stream_depth160_hot090_pipe64_20260717_0c09c6fb
```

- workload `rc=1`，after-metrics 因 GPU1 SGLang 已退出而无法生成正式 phase summary，
  因此不登记为有效 QPS。按 router 首末业务完成时间约 `1232 s` 折算仅约 `1.87 QPS`，
  只用于失败诊断。
- r10 将压力 kick 从 `200 ms/256 MiB` 改为 `25 ms/4 GiB` 后，GPU1 首次满载时
  `free=242, pending=282`。Moka 选中的 `622` 个 source（约 `2.93 GiB`）仍被活跃 Get
  handle 持有；master 的正确性门禁连续返回
  `owner local memory still has active holders`，但 selection debt 已把它们计作预计 free，
  owner 因而不再选择其它可回收 victim。
- `BatchGetStart(282)` 连续四次等待 local slot `30 s` 超时，后续两个 PutStart 也超时。
  GPU1 SGLang 最终报 `Prefill out of memory` 并退出；该节点只完成 `52` 个业务请求，
  GPU0 接管并完成其余 `2252` 个。业务流量虽最终得到 2304 个 200，但实例退出、
  scheduler exception 和 metrics 失败均违反验收门禁。
- 这不是 RDMA 断链或 GPU burner 干扰：超时前 CPU owner 与两 GPU owner 的 transfer-rpc
  fast path 全部 ready，CPU replica/owner 进程持续存活；直接阻塞点是 Fluxon owner
  victim eligibility 与 selection debt 的组合。

## E44 r11 active-holder-aware victim selection：实现中（2026-07-17）

r11 只修改 Fluxon owner：Moka listener 选中 source cohort 后，若任一成员除了
`get_cached_info` 和本次 selection pin 之外仍有额外 Arc holder，则不向 master 提交这个
暂时不可回收的 cohort；立即释放 selection debt，并把触发 key 重新 admission 到 owner-hot，
刷新其 recency。下一次 `evict_some` 因而可以选择其它当前可回收 victim。master Prepare 的
active-holder 门禁、route 删除顺序和 owner 容量均不放宽。

新增 `skipped_active_holders` runtime counter 和强引用基线单测；定向 release test 已通过，
`fluxon_kv --lib` 全量为 `173/173`。
下一步必须在相同公平 `96+32 / 96+32 / 256 GiB` 配置下重跑，并要求两侧
refill timeout、SGLang OOM/退出、scheduler exception、P2P deadline 全为 0。

r11 远端流量后来被终止（workload `rc=143`），没有正式 phase summary，因此仍不计 QPS。
`96+32` 只用于暴露 high-water 活性问题；Fluxon 统一 L2/L3 后的正式性能口径恢复为
GPU owner `128/128 GiB` + CPU owner `256 GiB`。

## E44 v5 正确性封版与性能实验（2026-07-18）

v5 以 r9 的 `2304/2304`、固定 grant、最终临时态归零和无 timeout/OOM 结果封为正确性基线。
性能线不再改变 direct source-delete 容量 authority。SGLang Fluxon HostKV pool 改为强制
metadata-only：逻辑保留 `--hicache-size 32`的 slot 索引，每 TP rank 只物化一个 KV page，
不形成独立 L2 命中容量。因此公平基线是 GPU0/GPU1/CPU owner=`128/128/256 GiB`。

三个有限实验分支由 `e44_v5_perf_variant_20260718.sh` 统一定义：

| variant | 相对 metadata baseline 的唯一策略变量 | master tier1 | proactive admission |
|---|---|---:|---|
| `baseline` | 无 | 关 | `prefix_depth_ratio`, depth 160, batch 64 |
| `tier1_075` | 增加 master metadata 提前 CPU 写回窗口 | `0.75` | 与 baseline 相同 |
| `enddepth288` | 改为完整 system-prefix 边界 | 关 | `prefix_end_depth_ratio`, end depth 288, batch 64 |

master 每 owner 新增 `last_route_removed_members/bytes`，只在 exact reclaim commit 确实删除
最后可读 route 时累加。每轮必须同时记录该计数、tier1 trigger/accepted/failed、
CPU retained bytes、L2+L3 和 QPS。性能目标为 L2+L3 先达到 Mooncake `68.0050%`；达标后再开始
load-back 单次延迟与 GPU restore 数据面优化。

### metadata-only 三轮实测结论

三轮均严格保持 GPU0/GPU1/CPU=`128/128/256 GiB`，GPU owner 各 `232`
grants；两侧每 TP rank 的 HostKV 仅 `materialized_pages=1`，冷启动
`hicache_host_used_tokens=0`。因此以下失败不以扩大容量规避。

- `r12 metadata baseline` 在约 `936/2304` 后停滞。node1 终态曾为
  `used/free/pending=26091/125/158`，一个 158-slot claim 尚缺 33 slots，30 秒
  refill timeout 后 `BatchGetStart(4030)` 连续得到 P2P 608。人工终止，不计 QPS。
  final-route 删除计数为 node0 `5886 / 27,773,632,512 bytes`、node1
  `11930 / 56,292,802,560 bytes`；CPU 保留 `42578 / 200,908,210,176 bytes`。
- `r13 tier1_075` 的 master 确认 `replica_writeback_tier1_capacity_ratio=0.75`，但
  workload `rc=1`，仅观察到 GPU0/GPU1 `393/243` 个 HTTP 200。GPU1 于
  `05:04:55`、GPU0 于 `05:07:19` 先后 `Prefill out of memory`；GPU0 同时有
  3 次 refill timeout。node0 tier1 最终约 `1272 entries / 6,002,049,024 bytes`，
  trigger/accepted/failed=`55412/22322/32948`；node1 tier1 为 0，
  `43076/19913/22898`。该分支没有有效 QPS，也未证明命中提升。
- `r14 enddepth288` 确认 master tier1 关闭，proactive admission 为
  `prefix_end_depth_ratio`、`max_replica_pages_per_batch=288`、inflight batch `64`。
  局部请求曾显示 `20096/20544=97.82%` prefix cache hit，但在 GPU0/GPU1
  `340/306` 个 HTTP 200 后进入 refill/P2P 重试；首个失败是 GPU0 316-page Get
  申请 167 slots、只有 104 free，30 秒后仍缺 63。人工终止时 GPU0 已有 6 次
  refill timeout、5 次 P2P 608，GPU1 尚无 timeout/OOM；仍不计 QPS。
  CPU 已保留 `54510 / 257,210,449,920 bytes`。final-route 删除计数为 CPU
  `50 / 235,929,600 bytes`、node0 `2156 / 10,173,284,352 bytes`、node1
  `1474 / 6,955,204,608 bytes`。

### r15 exact selected-credit 修复

r14 冻结时 GPU0 `pending/free=167/104`，owner-hot 同时记录
`selection_debt_bytes=2,557,476,864`、`source_eviction_selected=0`、retry entries
`542`，`group_trigger_incomplete` 持续增长。pressure actor 把从 Moka listener
产生、尚未安装 source fence 的 candidate/retry debt 也当成 projected Free；虚假 credit
超过 `pending + high-watermark` 后，新的 `evict_some` 请求被压成 0。

r15 将 candidate debt 与 physical-reclaim credit 分开：candidate debt 继续承担诊断、
去重和 retry 生命周期；新增 `source_eviction_selected_bytes`，仅在完整 cohort 已安装精确
source-selection fence 后增加，并在 commit/restore/rollback 时精确扣减。slot pressure 只用
后者抵扣待选 victim bytes。定向回归
`retry_candidate_debt_is_not_projected_reclaim_credit` 已通过；三机验收必须观察在
`selection_debt_bytes>0 && source_eviction_selected_bytes=0` 时仍会继续选择物理 victim，且
refill timeout/P2P 608 均为 0。本机定向测试 `1/1`、`fluxon_kv --lib` 全量
`175/175` 通过（198.72s）。

### r16 pin-aware Moka metadata baseline：已构建、部署并完成干净三机冷跑

r16 在 r15 之后只加入 pin-aware Moka 共享包装层，不改变 metadata baseline 的容量、
admission、tier1 或 load-back 策略。目标是先复测 baseline，确认 owner/master 活跃 holder
不再被 Moka 选成“看似可释放”的 victim。

当前产物：

- run id：`e44_r16_pinaware_metadata_baseline`；
- variant：`pinaware_baseline`；
- release staging：`/mnt/nvme0/mjq_build/fluxon_e44_r16_pinaware_metadata_20260718`；
- 共享 release：`/storage/mjq/sglang_fluxon/releases/fluxon_e44_r16_pinaware_metadata_20260718`；
- unified wheel SHA256：`cc717d6a49fe869ee6e88ff0a5b9436ee769611ab28eed3ab60e36e3835c545b`；
- PyO3 SHA256：`0628fa575180e22c99d75957c142584e2269138c4775cfa3dfb703d57f9c8fdf`；
- GPU venv：`/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r16-pinaware-20260718`；
- CPU venv：`/storage/mjq/sglang_fluxon/fluxon_cpu/venv-fluxon-e44-r16-pinaware-20260718`；
- 部署根 `/storage/mjq/sglang_fluxon/{fluxon_f1,fluxon_f2,fluxon_cpu}` 已同步本目录配置、
  e16bb 启动脚本和 `fluxon_wait_ready.sh`，`fluxon_release` 已指向 r16 release。

CPU/GPU venv import probe、wheel/PyO3/closed runtime hash 与 metadata-only HostKV patch 均已
在对应节点通过。随后按 master → GPU owner/SGLang → CPU owner → router → workload 顺序完成
无 burner 冷跑；正式结果见本文件顶部：`2304/2304`、QPS=`6.951279`、L2+L3=`52.51%`。
本轮结束后完整实验栈和 burner watchdog 已停止，等待下一步指示。
