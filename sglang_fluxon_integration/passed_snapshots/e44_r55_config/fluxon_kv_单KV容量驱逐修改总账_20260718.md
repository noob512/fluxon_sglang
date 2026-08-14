# Fluxon KV 单 KV 容量驱逐修改总账

日期：2026-07-18  
状态：r54 异常已闭合为“closed PPLX 环境停滞触发 + Fluxon handler 取消不安全永久放大”；r55 cancellation-safe 修复已通过 203 项本地测试、双 release、三节点部署、四态/228 项压力 smoke和原固定 2304 请求。正式结果 `2304/2304/0`、QPS=`10.162874`，正确性恢复但无性能收益；精确时间线证明主要浪费是 RDMA 已完成后仍提前占用 GPU staging 等待 scheduler 消费
统计范围：本轮 pin/容量驱逐收敛工作，以及从整组方案回退到单 KV 方案的过程

## 0. 当前累计状态 Snapshot

快照时间：2026-07-23 23:41 HKT
快照口径：r34 同环境正式基线、r35/r39 诊断证据、r36/r37 裁决、r38 最终结果、r39 新 GPU 无 GDR 固定负载、r40 Fluxon-only H2D 微基准、r41–r47 GPU Get 设计/构建/逐字节 smoke 演进、r48 GPU-direct correctness、r49 admission/lease 纯观测正式结果、r50 Plan/Bind no-go、r51 metadata-only Plan 正式结果、r52 最终正式 attempt2、三级缓存与 scheduler/Python 裁决、r53 fixed-slab 本地/集群/固定负载验收、r54 observation-only 异常轮诊断，以及 r55 cancellation-safe 修复、压力 smoke、正式 2304 请求和精确 prefetch 时间线；错误 checkout 上的多 MR 实现和构建结果仍全部作废

| 维度 | 当前累计最终状态 |
|---|---|
| 当前有效设计 | master metadata 与 owner-local 都按单 KV 逐个 pop、逐个 fence、逐个 reclaim；按成功进入回收的实际 bytes 累计到覆盖空间缺口。 |
| 明确禁止 | 容量路径不展开 TP/`PutAtomicGroup`/`atomic_batch` 兄弟成员，不等待完整组，不保留 incomplete-group retry 或 quarantine pin。 |
| `atomic_batch` 边界 | 仅保留 put/get 同请求聚合和发布原子性；KV key 仍是单 KV key，不定义容量 victim。 |
| 远端 Put 当前实现 | E44 owner-local generation 的远端 backing、预留 replica、tier1、proactive 已统一调用 `ensure_remote_put()`。`OwnerKeyControlTable` 的短同步临界区只按 `(key, put_id)` 选 leader；leader 立即启动独立异步任务，followers 用 `watch` 等终态。master 为每次 concrete append 分配独立 `operation_id`，Start 返回、Done/Revoke 原样回传，终态按 `(key, put_id, operation_id)` 隔离。没有 replica actor、batch actor 或全局 remote-write FIFO。 |
| pin 状态 | master/local 共用 `fluxon_util::pin_aware_moka`；`UserMemHolder` 持有 reader 的 `PinGuard`；非 pin KV 才在 Moka 可驱逐集合中。 |
| projected credit | Moka pop、candidate debt、retry-only debt 均记 0；只有已经安装精确 source fence 的 bytes 可以抵扣 pending slot demand。 |
| RPC 语义 | local 逐个 pop/校验并安装 source fence，按成功 fenced bytes 累计到覆盖缺口后，一次把多个 `victims` 发给 master；master 在一个 handler 内直接批量删除精确 source routes，完成后通过一个 `BatchDeleteResp` 一次性返回整批结果向量。向量内逐 victim 状态独立，但不是逐 victim 分开发响应；批量 delete 不等于整组驱逐。 |
| 当前工作树 | `Fluxon` HEAD=`2fa4448c7554ecbb2a50c56b3b32dbb02a28ea5b`：12 个 tracked 修改文件当前为 `+4444/-233`，另有 2 个 r53 fixed-slab 新文件 297 行，合计 `+4741/-233`。以 sealed r54 release 精确源码为基线，r55 cancellation-safe core 为 2 文件 `+58/-13`。`sglang` HEAD=`3cf22f62c58232e77a68ffdb1967ef4702472b47` 且主仓工作树仍干净；r54/r55 使用隔离实验源，不直接修改 SGLang 主仓。正确 closed 源仍为 `/mnt/ceph/zyc/fluxon_closed/fluxon_closed`，本轮不改 closed。 |
| 当前净改动量 | `Fluxon` 从 `1cb188c` 到 `2fa4448` 的既有已提交净 diff 仍为 17 文件 `+2574/-112`。当前 HEAD-relative tracked=`+4444/-233`，另有 fixed-slab 两个未跟踪文件 297 行；两者合计 `+4741/-233`。r55 相对 sealed r54 的 core 净差为 `external_api.rs +30/-10`、`external_client_api/mod.rs +28/-3`，合计 `+58/-13`；r55 新增 build/deploy/smoke wrapper 与压力程序共 285 行，另修改既有 variant、launch guard、通用 deploy/smoke runner。中间错误实现、被覆盖脚本和历史累计量不以最终净 diff 冒充。 |
| Rust fixed-slab 当前实现 | `fluxon_util::fixed_slab_allocator::FixedSlabAllocator` 使用 `parking_lot::Mutex` 管理固定 freelist、live bitmap 和预分配 validation marks；`try_reserve(count)` 保持 all-or-none 与原 `0,1,2...` 分配顺序，`release(slots)` 先整批校验越界、重复和非 live slot，再一次提交，错误不会部分释放。公开计数为 `capacity/free_count/live_count/is_empty`。release 热路径不临时构造 `HashSet`。 |
| PyO3/Python 接线 | `fluxon_pyo3.FixedSlabAllocator` 是唯一公开 class，构造、reserve、release 和只读计数均为强类型接口。`_FluxonGpuStagingPool` 已删除 Python `_free_slots`，只把 slot 状态机交给 Rust；Python 仍持有 GPU tensor、MR registration、lease、指标和指标一致性锁。slot 大小/数量、all-or-none admission、local/remote 过滤、GDR/CPU 决策和传输路径均未改变，本轮没有实现 partial GDR。 |
| fixed-slab 本地门禁 | NVMe target 已确认位于 `/dev/nvme0n1p3`。`fluxon_util` 定向单测 `5/5`；`cargo check -p fluxon_pyo3` 和 `cargo build -p fluxon_pyo3` 均 rc=0；从新构建 `.so` 实际加载的 Python smoke 覆盖 class 注册、计数、顺序、容量不足、release、重复释放、double-free 和零容量，全部通过。adapter/validator Python syntax 与完整 staging lifecycle validator 通过。裸 `.so` 前两次分别被缺 `libcudart.so.12` 和 wheel-local runtime 门禁拒绝；在 NVMe 临时复用 sealed r50 `fluxon_pyo3.libs` 后通过，临时目录随后清理。这两次属于预期打包环境门禁，不是 allocator 断言失败。 |
| fixed-slab 验收边界 | r53 已补齐正式 wheel/release、共享 stage、两 GPU 真实 staging/transfer smoke 和 2304 请求。allocator correctness 可以封存；性能仍不能封为收益，因为 QPS 相对 r52 `+1.79%` 时总命中高 `0.22pp`、selected 从 322 变为 333，且相对无 GDR r39 仍低 `1.94%`。该下沉不是 scheduler/lease 主瓶颈。 |
| r53 release/部署/smoke | GPU/CPU wheel SHA256=`c9e402be...a81ff/3521fce7...a9d39`，共同 PyO3=`e107038c...f0075`；两种 wheel 的真实 import allocator smoke 均通过。共享-stage 部署 rc=0，node0 公网上传一次 `91,498,692 B`，node1/CPU stage payload=`0`，ext_images transport=`0`；三端独立 manifest/ABI/runtime/adapter 回读通过。remote GPU、local-only、mixed 与 CPU fallback 四态逐字节 smoke rc=0。 |
| r53 正式结果 | 原固定 S96×T24/2304/c24/system8192/output8/session-stream、Get32、tier1 5%、end-depth288、DMA0、metadata-only `128/128/256 GiB`，workload SHA256=`f6721d76...03f52`；`2304/2304/0`、QPS=`10.399872`，TTFT p50/p90/p99=`1.4876/2.7433/9.1494s`，E2E=`1.8374/3.6854/10.5309s`，L1/L2/L3=`3.8686/0/72.4142%`，总命中=`76.2828%`。相对 r52 `+1.79%`，相对 r39 `-1.94%`；只封 correctness，不登记 allocator 性能收益。 |
| r53 节点/计算偏斜 | node0/node1 请求=`1224/1080`，TTFT mean=`1.995/1.124s`，scheduler queue mean=`1.274/0.535s`，prefill-forward mean=`0.434/0.348s`，prefill-compute tokens=`6.886M/5.038M`。TTFT 节点差 `0.871s` 中 queue 差 `0.739s` 约占 85%，而真实 prefill-forward 差仅 `0.086s`。owner-local 比例=`36.68%/76.18%`，说明物理等待落在 GPU prefill/空间，根因更接近有效工作和 locality 分配不均，而不是四卡均匀算力不足。 |
| r53 lease/传输瓶颈 | 每 TP pool=`288×4718592 B=1358954496 B`。node0 selected remote pages p50=`281.5`，lease mean/max=`1324.7/8878.5ms`，slot occupancy约 `48.0%`，insufficient=`562`；node1 lease mean/max=`811.6/2257.0ms`，occupancy约 `21.6%`，insufficient=`42`。owner 4003 次真实远端 Get 的 transfer wall mean/p90/p99=`24.20/45.14/76.64ms`，而成功 lifecycle ready-wait mean=`701.11ms`、restore=`196.14ms`。因此秒级 lease 不是 RDMA 搬运本身，而是 reserve 过早并跨 scheduler/restore 生命周期持有。 |
| r53 网络边界 | 正式窗三端 HCA sample error=0；CPU 双 HCA TX avg/p99/peak=`77.79/298.81/350.43Gbps`，分别为 800Gbps 的 `9.72%/37.35%/43.80%`。链路有瞬时流量和 `port_xmit_wait`，但未持续接近带宽容量，且真实 Get 为几十毫秒，不能解释秒级 queue/lease。 |
| r53 下一门禁 | P0 observation-only 补 metadata-ready、reserve/RDMA-start、RDMA-terminal、consume/restore/release 及 queue position。确认 `terminal→consume` 后，P1 只做 queue-head `K` 个候选的 scheduler-aware GDR，保持 288 slots、负载和其他参数不变；远离队头的请求先落 DRAM且不得重复 GDR。P1 通过前不扩大 pool、不做 partial split；若仍无收益，优先做 Fluxon locality/remote-cost aware routing。分析文档=`20260723_1946_fluxon_r53收益不大_瓶颈定位与精准Prefetch方案.md`。 |
| r54 observation-only 实施边界 | 同一 external GPU Get handle 在 Rust 内记录 transfer start 与 terminal 单调时间；消费时返回 transfer wall、terminal-before-consume、terminal-to-consume 和真实 finish-wait。SGLang 以现有 `req_id` 关联 plan ready、slot reserve、execute start、queue position/length/pending tokens、transfer consume、load-back consume、restore complete 和 lease release。只新增时间线；不得改变 CacheAware、队列顺序、288 slots、all-or-none admission、CPU/GPU 路径或负载。相对 r53 隔离源：runtime `+223/-1`、adapter `+8/-1`、当前 scheduler `+36/-1`，validator 207 行；新增 build/deploy/smoke/master wrapper 共 112 行。 |
| r54 当前本地门禁 | `cargo fmt --all -- --check`、`cargo check -p fluxon_pyo3 --lib`、Python compile、r42 staging lifecycle validator、r54 timeline validator、shell `bash -n` 和 `git diff --check` 已通过。Rust 时间语义定向测试=`1 passed/0 failed`；正确 ABI9 closed SDK 下全量 `cargo test -p fluxon_kv --lib`=`202 passed/0 failed`（186.15s）。scheduler 以线上 r53 精确源码 SHA256=`705c23b1...7177` 为基线；首版 `cf20558f...61ee8` 在真实健康请求因调用不存在的 `get_num_waiting_uncached_tokens()` 失败，已作废。当前版本不再调用该 API，使用 installed request fields 计算，净差=`+36/-1`，SHA256=`5bf313d8...26ef`；兼容 validator、analyzer self-test 和双 release finalize status=`0`。尚待修复版共享部署、四态 smoke 和固定负载。 |
| r54 release | NVMe GPU/CPU release=`fluxon_e44_r54_prefetch_timeline_{gpu_cuda,cpu_host}_20260723`；GPU/CPU wheel SHA256=`168dd441...aba1/9004d93f...45c`，共同 PyO3=`2f3cf883...645c`，GPU core/probe/cudart=`e64bcfb3...148c/e925553e...5883/5b8de0ee...dc82`，CPU core/probe=`63c08ee6...e06/e925553e...5883`。修复版 finalize-only status=`0`，wheel/PyO3 未变；release 内 runtime/adapter/scheduler=`920cb610...e554/eb1e0848...8ccd/5bf313d8...26ef`，validator=`18736735...c115`，两个完整 manifest 已重算并通过。 |
| r54 部署/smoke | 首版共享-stage 部署与四态 smoke status=`0`，证明 GPU terminal 强类型字段和四种数据路径正确；但该 smoke 不启动完整 SGLang scheduler，未覆盖首版不存在 API。正式启动两侧模型后，首个健康请求均在 `_prefetch_kvcache` 同形 `AttributeError`，请求量=0、无 QPS；首版部署/smoke 已被当前 scheduler 修复覆盖，不能作为当前代码验收。失败栈/HCA 全部停止，四个 managed burner 已恢复；修复版必须从共享部署和 smoke 重新验收。 |
| r54 修复版异常轮 | 修复 scheduler API 后的正式固定负载不是正常波动：node1 closed PPLX 在 228 个 planned-CPU Get 中只完成 4 批/43 项后停滞；300 秒 RPC 超时取消 owner handler，而 228 个 per-key flight 已进入 `Finishing` 且 finish future 同 handler 一起被丢弃。后续 466 次重试全部只成为 follower，形成 transfer/refill timeout、P2P 608、prefill OOM/实例退出链。证据目录=`/mnt/nvme0/mjq_build/e44_r54_prefetch_timeline_failed_20260723`；异常轮无合法 QPS，已完整停栈并恢复 burner。环境停滞是触发器，Fluxon 取消不安全是把瞬时故障放大成永久堵塞的实现缺陷。 |
| r55 实现与本地门禁 | owner 在全部 leader 发布 `Started` 后，把 `finish_external_get_key_leaders` 与 unused-operation cleanup 交给 framework 管理的独立后台任务，生命周期不再依附入站 RPC handler；external 前台 planned-CPU RPC 从 300 秒缩到 P2P 最小显式 10 秒，uncertain replay 仍保留 300 秒并复用相同 operation identity。`cargo fmt --check`、`git diff --check`、相关测试 `23/23`、新增超时边界测试 `1/1`、全量 `cargo test -p fluxon_kv --lib=203/203`（186.79s）全部通过；Cargo target 位于 `/dev/nvme0n1p3`。 |
| r55 release/部署 | GPU/CPU release=`fluxon_e44_r55_planned_get_cancel_safe_{gpu_cuda,cpu_host}_20260723`；wheel SHA256=`9361e324...3005f/48f202e8...e0551d`，共同 PyO3=`fb0a770a...88ace1`，GPU core/probe/cudart=`e64bcfb3...148c/e925553e...5883/5b8de0ee...dc82`，CPU core/probe=`63c08ee6...e06/e925553e...5883`。两个完整 manifest 通过。三节点共享-stage 部署两次均 status=0；每次仅向 node0 公网上传 `91,832,907 B`，node1/CPU 共享 stage payload=`0`，ext_images transport=`0`；三端各自 wheel/PyO3/closed runtime/ABI/adapter/active release 回读通过。第二次只为分发修正后的 ANSI-safe smoke gate。 |
| r55 压力 smoke | 修正后的 runner status=`0`。remote GPU、local-only、mixed local/remote、planned CPU fallback 均逐字节通过；关键 stress 一次写入并读取 `228×4,718,592=1,075,838,976 B`，concurrency=32，payload SHA256=`bd0c9278...ed19`。owner 实际 transfer 分为 100+128 项，wall=`15.938/17.054ms`、total=`17.962/20.305ms`；最终 `active_flights=0`、`finishing_flights=0`、master `inflight_gets=0`。首个 runner 的同一数据与状态也已成功，但 ANSI 色码使固定字符串 gate 误报失败；修正为先 strip ANSI 后重跑通过。两轮均完整停栈并恢复四个 managed burner。 |
| r55 正式结果 | 精确复用 r54/r53 固定负载：S96×T24、2304 请求、c24、system8192、output8、session-stream、Get32、tier1 5%、`prefix_end_depth_ratio=288`、DMA0、metadata-only `128/128/256 GiB`；正式窗=`1784819988.205758–1784820214.913290`。结果=`2304/2304/0`、QPS=`10.162873628`；TTFT p50/p90/p99=`1.387430/3.115027/8.871205s`，E2E=`1.898480/4.040898/10.897057s`；L1/L2/L3=`6.260350/0/69.096177%`，总命中=`75.356527%`。相对 r53 QPS `-2.279%`、总命中 `-0.926pp`；相对 r52 attempt2 QPS `-0.531%`；相对无 GDR r39 QPS `-4.177%`。因此 r55 封 correctness，不登记性能收益。 |
| r55 正确性终态 | node0/node1 请求=`1224/1080`。正式结束并等待 settle 后，两侧 `active_handles/active_flights/starting/finishing/revoking/undecided/retained=0`，remote Put `active=failed=0`，source eviction retry/debt/selected bytes=`0`；master activity 与 inflight Put/Get/replica 全 0。正式窗内 P2P608、CUDA OOM、scheduler exception、planned-CPU RPC failure 和真实 refill timeout均为 0。Ctrl-C 后两侧仍复现既有 module-view 析构 panic，发生在合法 summary和归零 Snapshot 之后，继续列为 shutdown lifecycle P1。 |
| r55 精确时间线结论 | 修正 analyzer 的重复 attempt 口径后，4777 条 TP-rank lifecycle、4416 个 request-rank key 中有 235 个 key 被扫描 2–4 次；GPU selected=`674`、成功 load-back=`661`。`545/674=80.86%` 在 scheduler consume 前 RDMA 已终态。成功项 RDMA wall mean/p50/p90/p99=`44.03/36.06/76.53/186.04ms`，真实 finish-wait=`6.80/0.001/29.90/85.22ms`；但 terminal→consume=`564.73/238.74/1031.99/7273.49ms`，reserve→release=`927.45/678.38/1466.01/7533.18ms`。平均 `84.53%` 的 lease 位于 transfer terminal 之后。node0 terminal→consume mean=`805.44ms`、node1=`346.91ms`，继续显示 scheduler/locality 偏斜。结论：DRAM-HBM/RDMA 不是秒级主瓶颈，当前 GDR admission 太早，staging slot 主要被“数据已到、请求未消费”占住。 |
| r55 网络结论 | 三端 HCA raw sample error=`0`，Greptime 导入=`9410` 行、write error=0。正式窗 CPU 双 HCA TX avg/p99/peak=`69.273/262.219/301.725Gbps`，仅为 800Gbps 的 `8.66%/32.78%/37.72%`；未持续接近带宽上限。两个 GPU pod 本轮读取到相同物理 HCA counter，不能把两份 RX 相加冒充双倍流量；即使按共享 NIC 口径，链路容量也不是 565ms terminal→consume 的解释。 |
| r55 analyzer 修正 | 旧 r54 analyzer 错把 `(node,tp_rank,req_id)` 当唯一 lifecycle；本轮同一请求可因 scheduler 再扫描产生 2–4 次独立 `load_back_not_ready`/后续 attempt，旧工具因此报 conflicting duplicate。`analyze_e44_r54_prefetch_timeline.py` 改为逐文件保留 attempt 并赋 `attempt_index`，只按 resolved source 去重重复输入文件，净差=`+40/-11`；compile/self-test通过，SHA256=`76cefc64...fb880`，只经 node0 唯一 stage 上传一次后重算成功。旧 r35 analyzer仍假设每 rank 单 lifecycle，已明确不用于本轮裁决。 |
| r55 清场/归档 | artifact=`artifacts/e44_r55_planned_get_cancel_safe_enddepth288_netobs_passed_20260723/`，含 workload、三端日志/HCA、timeline/get-ready分析、实际配置和 release provenance。router、两侧 SGLang、三 owner、master、control、Greptime 与 observer全部停止；三机实验进程为 0。32656 burner PID=`33666/33969`、watchdog=`34112`；30245 clean-restart 后 PID=`11463/11766`、watchdog=`11909`，四卡均 `1395 MiB/100%` 且 `running (managed)`，无 `inference_like_compute.py`。 |
| r55 下一门禁 | P0 不再扩大固定 staging，也不优化已很短的 transfer。把 GPU direct admission 从 plan-ready 改到“接近 scheduler consume/队头”才预留 slot，并使用短 TTL；远离队头的 remote hit继续先落 DRAM。必须保持同一 operation 不重复 RDMA，按现有 timeline 做离线阈值 replay，再单变量实装。若无法把 terminal→consume 与 post-terminal lease 显著压低，停止 GDR 方向，转做 Fluxon locality/remote-cost aware routing。 |
| r53 当前运行状态 | workload、router、两套 SGLang、三 owner、master、control、etcd、Greptime 和 HCA observer均已停止；32656/30245 四个 managed burner 恢复，约 `1395 MiB/100%`，无 `inference_like_compute.py` 或推理进程。master `active_plans=52` 与 r52 残留 45 同属既有 plan bookkeeping TODO，不是 fixed-slab 新回归。 |
| r48 正确性结果 | 单 RDMA worker 对 TP1 CUDA device 1 的注册修复已通过定向测试、CUDA SDK/wheel、两机 TP2 staging registration 和正式负载。两机 TP0 worker=`device=0`、TP1 worker=`device=1`；正式流中无 event-device mismatch、P2P 608、OOM 或实例退出。 |
| r48 正式结果 | 原固定 S96×T24、2304 请求、c24、system 8192、output 8、session-stream、Get32、tier1 5%、end-depth288、DMA0、metadata-only 128/128/256 GiB；`2304/2304/0`，QPS=`10.523661`，TTFT p50/p90/p99=`1.6022/2.6548/4.3732s`，E2E=`2.1170/3.7326/4.9355s`，L1/L2/L3=`2.88795/0/72.19078%`，总命中=`75.07873%`。 |
| r48 性能裁决 | 同口径 r39 QPS=`10.605922`，r48 为 `-0.776%`；r48 总命中同时低 `0.525pp`，差值不足以归因。按 TP0 去重，GPU-direct 仅 `36/2154` 个逻辑 prefetch、`656064/39036224` tokens，即 `1.671%/1.681%`；CPU staging 仍有 2118 次。因此 r48 只封 correctness，不登记性能收益。 |
| r48 覆盖率根因 | 每 TP staging=`288×4718592 B=1358954496 B`，而本负载一个长前缀通常需要 281–288 页，静态 staging 同时大致只能容纳一个长请求；c24 下其他并发自然回落 CPU。实际 GPU-direct 为 10251 页，双 TP 物理量约 `96.741 GB`。下一步若继续必须先解决覆盖率与 GPU KV 容量的 trade-off。 |
| r49 正式结果 | observation-only，r48 的 staging=`288 slots/TP`、Get32、tier1 5%、end-depth288、DMA0、metadata-only `128/128/256 GiB` 和 S96×T24/2304/c24/system8192/output8/session-stream 全部未变；workload SHA256 与 r48 归档相同。结果=`2304/2304/0`，QPS=`10.362389`，TTFT p50/p90/p99=`1.6933/2.8011/4.3760s`，E2E=`2.1459/3.5972/4.9434s`，L1/L2/L3=`3.3874/0/71.2182%`，总命中=`74.6056%`。相对 r48 QPS `-1.532%`、命中同时 `-0.473pp`，且本轮日志更重；只作归因，不登记性能收益或回退。 |
| r49 覆盖率根因 | TP0/TP1 逐项完全一致。2208 个 admission events 中 GPU candidates=2192：`request_exceeds_capacity=2013`（91.834%）、`insufficient_free_slots=143`（6.524%）、`selected=36`（1.642%）。过大请求原始页数均值/p50=`351.322/351`，CPU fallback 后真实 transferable p50=`288`；其中 `1265/2013` 的真实 transferable 位于 `(0,288]`，证明主要错误是 Get plan 前按完整 `hash_values` 长度过早拒绝，不是 pool 竞争。 |
| r49 lease 证据 | selected=`36`、每 TP release=`36`，均由 `layerwise_release_views` 回收；逻辑 direct=`10242 pages/655488 tokens`，占成功 load-back `1.674%`、tokens `1.686%`，与 r48 基本不变。lease 平均占 `284.5/288 slots`、TP0 平均持有 `437.814ms`，node0 最大 `2714.770ms`；真实并发竞争存在但属于第二层问题。SGLang Ctrl-C 未调用 `HiCacheFluxon.close()`，所以 close Snapshot 未落日志；selected/release 相等且停栈后显存清零，未发现 lease 泄漏。 |
| r49 下一门禁 | P0 先增加 generation-safe `plan → exact reserve → execute`：Fluxon 先只返回 transferable prefix/route plan，不传数据、不创建 CPU holder；SGLang 按 plan 和当前 GPU budget 安装 destinations，再复用同一 operation 执行。之后 P1 才做 bounded GPU prefix + CPU remainder/chunk。不能先 CPU Get 再重复 GPU Get，也不应直接扩大固定 pool。 |
| P0 当前实施状态 | r51 保留 r50 的 GPU destination/RDMA 数据面，master Plan 已收缩为不持有 route/Allocation、activity、cache pin 且不 touch Moka 的标量快照；候选选择也先投影成 node/tag/geometry 标量并在首个 await 前显式 drop route。Bind 才安装真实 Get activity并重读当前 route，按 put/source generation、地址和长度精确复核。owner planned CPU execute 仍先做 local-hit/per-key singleflight，只有 leader Bind，followers 复用终态。本地完整门禁、双 wheel、三节点部署、双路逐字节 smoke和原固定负载均已完成；正确性通过但性能 no-go，不能替代 r49 性能基线。 |
| r52 当前实现（本地已验收） | external 先向自己的 owner 做 local-only probe，并在 owner per-key fence 内安装精确 holder；只有剩余 remote keys 才进入 master metadata Plan。CPU 分支只把 remote plan 交回 owner，继续复用现有 per-key singleflight，再与 local holders 按原 key 顺序合并；GPU 分支只为 remote positions 预留 staging/安装 destination，local positions 保留 owner CPU 地址。PyO3 输出原 key 顺序的统一 source plan，SGLang 同时持有 source plan 与可选 GPU lease。mixed GPU 在 Bind 前和 transfer terminal 后各校验 owner generation/range/address，Bind 前不再通过 `holder.bytes()` 构造可能过期的 slice。取消、失败和短前缀分别 drop local holdings、Revoke remote plan、释放 GPU lease。容量驱逐、remote Put singleflight、固定负载和 288-slot 总预算均未改。 |
| r52 本地门禁 | NVMe target 已由 `findmnt` 确认为 `/dev/nvme0n1p3`。正确 schema6/ABI9 SDK 下，修改前 r52 全量=`200/200`；补 stale-owner 二次校验后新增定向测试=`1/1`，最终全量=`201 passed/0 failed/0 ignored`（184.96s）。`cargo check -p fluxon_pyo3 --lib`、Python compile、staging lifecycle validator、shell `bash -n`、`cargo fmt` 和 `git diff --check` 均通过。一次错误使用不完整 `--exact` 名称只匹配到 `0 tests/201 filtered`，随即用完整测试名重跑 `1/1`，不是代码失败。首次全量误用 schema5/ABI8 SDK 得到 `191/9`，9 项共同报 `DecodeRequest bitcode error`；切换历史已验证 ABI9 SDK 后同一源码 `200/200`，因此该轮明确记为环境无效结果。 |
| r52 release | GPU/CPU build 与 finalize 均 rc=0。GPU wheel=`d4c7a41d...ad53`，CPU wheel=`0d135970...e5bf`，共同 PyO3=`a0cf3087...ee33`；GPU core/probe/cudart=`e64bcfb3...148c/e925553e...5883/5b8de0ee...dc82`，CPU core/probe=`63c08ee6...e06/e925553e...5883`。variant/guard 精确 hash 已补齐。 |
| r52 分发与部署 | 最终模式只把 GPU/CPU delta、公共配置和 netobs tools 共 `91,471,430 B` 公网上传一次到 node0 的共享 `/storage`；node1 与 CPU 直接读取同一 stage，内部 payload=`0`。`ext_images/` 与 `ext_images.tar.gz` 均不进入 delta；三端分别从本机 r51 sealed release 硬链接复用，tar SHA256=`15319a76...7e1`，传输 bytes=`0`。node0/node1/CPU 各自独立通过 transport SHA、release manifest、`ext_images.sha256`、wheel/PyO3/closed libs、variant/runtime/adapter 和 installer 回读，最终 active release 指向 r52。 |
| r52 correctness smoke | runner rc=`0`。remote GPU、owner-local-only、mixed `[local,remote]` 和 planned CPU fallback 全部逐字节通过。remote payload SHA256=`bd0c9278...ed19`，local payload=`23e77a1d...a37`；mixed 仅 `remote_indices=[1]`、只分配 1 个 GPU destination，local-only remote indices 为空。cleanup 后 Fluxon/SGLang/inference=0，四个 managed burner 恢复。 |
| r52 固定负载 attempt1 | 请求窗=`1784790214.910–1784790438.130`，`2304/2304/0`，QPS=`10.321654`；TTFT p50/p90/p99=`1.5870/2.8363/8.8298s`，E2E=`1.9644/3.8062/10.4507s`；L1/L2/L3=`4.2428/0/71.8602%`，总命中=`76.1031%`。但 GPU observer 正式窗两节点各 `894` 个 sample errors，原因是 `libibmad/libibumad` 位于工具根目录而 `LD_LIBRARY_PATH` 指向 `lib/`；该轮不能封为最终网络同口径结果。 |
| r52 固定负载 attempt2 | netobs HCA 动态库修复和三端 `ldd`/直接查询通过后，完全相同固定负载=`2304/2304/0`，QPS=`10.217138`；TTFT p50/p90/p99=`1.4087/2.8807/9.4321s`，E2E=`1.9500/3.8717/11.0993s`；L1/L2/L3=`4.8012/0/71.2617%`，总命中=`76.0629%`。三端正式窗各 450 个 HCA interval、sample error=0；fatal/P2P608/OOM/refill timeout/conflict exhausted 均为 0。 |
| r52 性能裁决 | 正确主基线是同一批新 GPU 上的无 GDR r39=`10.605922`，不是较低的 r49。r52 attempt2 相对 r39 QPS=`-3.67%`、wall time=`+3.81%`，尽管总命中高 `0.4597pp`、TTFT p50 更好；attempt1/attempt2 均出现约 9 秒 TTFT p99，故不能按普通小波动放行。r52 只封 correctness，性能 no-go。 |
| r52 网络收益边界 | CPU 双 HCA TX avg 从 r39 的 `142.516 Gbps` 降到 `77.612 Gbps`，发送量约从 `3.867 TB` 降到 `2.183 TB`；owner 远端 Get bytes 从约 `3.829 TB` 降到 `1.669 TB`。网络量确实下降，但 r39 平均 HCA 利用率本就只有 `17.8%`，所以节省的不是吞吐临界路径。 |
| r52 尾延迟定位 | 成功 load-back initial/Get-transfer 均值从 r39 的 `28.431/10.794ms` 改善到 `20.494/3.784ms`，但 ready-wait p99 从 `2.465s` 增至 `6.917s`。r52 node0 有 76 条 TP-rank（38 个逻辑请求）ready-wait>5s，r39 两节点为 0；其中 30 个逻辑请求完全 owner-local，Get 仅约 `0.16–0.27ms`，说明秒级尾部在 SGLang ready/prefill 消费排队而非 RDMA/Plan/真实 transfer。 |
| scheduler/Python 裁决 | `ready_wait_ms` 从 observation 创建计到 waiting-queue 扫描时的 `check_prefetch_progress()`，且 hostless operation 的 `is_finished()` 恒为 true；它不是 Python CPU timer。正式 Prometheus 差值中，慢节点 node0 的 request-process mean 从 r39 `44.352ms` 改善为 r52 `29.893ms`，queue mean 却从 `798.667ms` 恶化为 `1210.543ms`。一个完全 owner-local、Get=`0.181ms`、ready-wait=`7.740s` 的请求等待期间，TP0 推进了 45 个 prefill batch、51 次 eviction，queue=`16–22`、pending tokens=`430999–593458`。现有 restore descriptor/dispatch mean 仅 `0.594/0.626ms`；background `31.659ms` 在独立 worker 且由 `perf_counter` 记录，不能当 thread CPU。故秒级尾部主因是 prefill/GPU 空间/token budget residence，不是已证实的 Python on-CPU；但当前 scrape 没有 scheduler CPU，尚不能量化 Python 的百分点税。文档=`20260723_1746_fluxon_scheduler等待是否来自Python开销分析.md`。 |
| r52 节点偏斜 | owner-local probe：node0 local/remote=`268836/495246`、local=`35.18%`；node1=`546828/166266`、local=`76.68%`。node0 staging insufficient=`574` 次、node1=`40` 次。node0 prefill queue mean/max 从 r39 `4.382/17` 增至 r52 `6.788/22`，pending tokens mean/max 从 `95499/373121` 增至 `157681/594788`，逻辑 prefetch rate-limited 从 `18` 增至 `61`；node1 未同形恶化。优化收益主要落在较轻 node1，node0 成为整轮 straggler。 |
| r39 local-first 基线纠正 | r39 封存 owner `batch_get()` 已先逐项检查 `local_visible_mem_holder()`，local hit 直接返回，只把 `missing_keys` 交给 `batch_get_start()` 并只传输这些 local miss。r52 不是首次加入 local-first，而是为 Plan/GDR 将判断显式提前成 probe。故 r39 已是 local-first、无 GDR 的有效性能基线，不需要再跑 r52 GDR-off 才获得该对照。 |
| r52 GDR 收益模型 | CPU 路径=`remote→owner CPU/L2→raw H2D→final GPU`，GDR 路径=`remote→GPU staging→D2D→final GPU`。净收益必须满足“首访节省 + 避免 CPU cache pollution”大于“后续 L2 复用损失 + restore batch 污染 + slot-time 机会成本 + Plan/Bind 控制开销”。r40 的 288-page raw H2D 约 25ms；按 r52 实际 direct pages 计算，本轮最多绕过的 raw H2D 仅 node0/node1=`2.926/1.643s` worker-time，且尚未扣 D2D/重叠，不能解释 wall time。 |
| r52 restore transport 污染 | 当前 `_start_fluxon_hostless_layerwise_loads()` 以整批 `any(gpu_staging_lease)` 选 transport；任一 GDR operation 会让同批 CPU-only operation 和 mixed 中 owner-local CPU pages 全部从 `layer_batch_dma_background` 切到 kernel。TP0 实测 direct remote pages=`52634/615478=8.55%`，但 kernel pages=`191297/615478=31.08%`；kernel 是真实 GDR payload 的 `3.63×`，其中 `138663/191297=72.49%` 不是 GDR remote page。node0 selected 与 slots-insufficient 的总 pages 近似相同，restore mean=`272.380/225.090ms`，与代码问题同方向，但不是随机因果对照。 |
| r52 L2 复用证据边界 | CPU planned remote 完成后进入 `local_hot_admissions`；GDR `ExternalSink` 要求 `holder_id=0`，不创建 CPU holder、不暖 owner L2。owner-local probe 的 `55.22%` 说明 local 层整体有价值，但混合 Put/local admission 等来源。现有日志没有 `(key, generation)` 的首次 CPU/GDR 路径、后续 local hit/remote refetch 和 L2 residence/eviction 串联，故不能把 QPS 回退归因成已测实的 GDR 复用损失；聚合网络量反而下降。 |
| r52 GPU 容量边界 | r39/r52 的最终 GPU KV 都是 `200000 tokens/TP`；r52 额外分配 `1358954496 B/TP` staging，本轮未缩小配置 L1。live lease 会阻塞其他 GDR admission，但不能说本轮 QPS 回退来自 L1 token 数下降。扩大 staging 仍会消耗 GPU headroom，未来必须重新做容量权衡。 |
| 三级缓存统一模型 | GPU/local CPU/remote 分别服务短、中、长 reuse horizon；当前 route 的可见等待为 `Visible(T,S)=max(0,T-S)`。GDR 的即时价值是 CPU 与 GDR 两条路径的可见等待差，必须再减去未来 local replica 价值、staging/带宽外部性并加上避免 L2 pollution 的收益。恢复量按连续 prefix 求 `PrefillSaved(m)-TransferVisible(m)-GpuVictimCost(m)-CongestionCost(m)+FuturePlacementValue(m)` 最大值；partial GDR 是模型输出，不是预设比例。 |
| 当前负载模型代入 | GPU=`200k tokens`；24 并发第一/末轮输入合计=`197568/261600 tokens`，后期活跃输入超过 L1。owner-local 128GiB 约 `838912` 逻辑 tokens，约为 GPU `4.2×`；从单节点看 remote=`384GiB`。最终唯一 KV=`129.984GiB`，24 轮累计请求 KV=`2692.688GiB`，累计/唯一=`20.72×`，说明负载复用强。结合 r39 94.93% 消费前终态和 HCA 未饱和，模型初判应偏 CPU+local admission；GDR 只服务 CPU 会错过消费 deadline 且未来复用低的 pages。 |
| 策略边界解耦 | 传输路径与 local admission 必须分开：支持 CPU+admit、CPU temporary/no-admit、GDR+bypass、GDR+延迟 admit 四态。高复用但本次紧急的数据可先 GDR，再在二次触达或 GPU eviction 时依据 ghost/reuse score local admit；冷数据即使 CPU fallback 也不应必然污染 Moka。router locality 通过 `p_same` 进入 local replica 价值，但不能牺牲 compute queue 平衡。 |
| r52 下一门禁（18:31 修订） | fixed-slab 只是用户指定的局部 native 化，不能替代此前性能定位。若下一步验收本轮代码，先生成正式 wheel/release并按共享-stage规约部署，再做真实 GPU staging reserve/trim/release/close smoke，最后原样运行固定 S96×T24/2304/c24 负载；在这些门禁前不登记 QPS。战略 P0 仍是补 `(key_hash,generation,session/turn/depth)` reuse lineage、tier residence/eviction、真实 terminal、scheduler wall/thread CPU、GPU busy、block reason 与 RDMA/H2D/D2D queue；P1 trace replay 必须先复现 r39/r52，再选最小策略。只有证实 scheduler 单核饱和且 GPU 等 scheduler，才继续下沉更大 Python 控制面；否则实施 replay 选出的传输/admission 解耦并清零 restore 非 GDR 页污染。 |
| r50 正式结果 | workload SHA256=`f6721d76...3f52` 与 r48/r49 相同；S96×T24/2304/c24/system8192/output8/session-stream、Get32、tier1 5%、end-depth288、DMA0、metadata-only `128/128/256 GiB` 均未变。结果=`2304/2304/0`、QPS=`6.997695`，TTFT p50/p90/p99=`1.7582/6.3047/9.9634s`，E2E=`2.2816/7.6532/11.6751s`，L1/L2/L3=`10.1375/0/56.0784%`、总命中=`66.2159%`。相对 r49 QPS `-32.470%`、L3 `-15.140pp`、总命中 `-8.390pp`，不能把 QPS 差额解释为单纯 GPU-direct overhead。 |
| r50 覆盖与流水线 | TP0 去重 selected=`196/2208`（8.877%），较 r49 的 36 次提高；direct 消费约 `3,173,696` tokens，占成功 load-back tokens 约 4.58%。但成功 load-back TP-rank operations 从 4300 降至 3682，`rate_limited` 从 32 增至 374，`zero_transferable` 从 72 增至 308，另有 26 个逻辑 Get transfer/TP commit 错误。成功项 ready-wait mean/p90/p99 从 `721/1545/2394ms` 变为 `1345/3761/7739ms`。node0 成功 load-back `2312→1704`，node1 `1988→1978`；node0 CPU/GPU 两种路径都慢，不是单独 GPU copy 慢。 |
| r50 网络与容量证据 | 正式窗 CPU 双 HCA TX avg/p99/peak=`22.547/138.250/200.488 Gbps`，相对 r49 平均 `-82.48%`，三端 sample error=0；这是上游未喂满网络，不是带宽饱和。Plan 阶段持有 key activity 后，source-evict retryable Busy 从 r49 的 299 增至 r50 的 `3353+7874=11227`；最终 master/owner active Get/Put/replica/reclaim 均为 0，不是终态泄漏。 |
| r50 根因裁决 | r50 每个 SGLang 调用者先直接访问 master Plan；master 在 `handle_get_plan_item` 即安装 Get activity，并把 lease 保留到 Bind/Revoke；owner 的 local-hit/per-key singleflight 到 planned CPU execute 才运行。因此原 owner-side 聚合发生得过晚：followers 即使最终复用 holder，也已经重复做 master route snapshot/activity pin/Revoke，GPU 分支完全绕过 owner Get 聚合。该边界放大 master/control 工作、容量回收 Busy、前缀缩短和 prefetch 限流，和正式数据同方向；r50 不得继续作为当前性能候选。 |
| r50 下一门禁 | 已进入 r51 实现：Plan 的物理资源/activity 副作用已删除，Bind-time revalidate/activity 和 CPU local/leader/follower 计数已落地。当前接口仍为每个调用者生成独立 plan identity；metadata lookup 跨调用者共享尚未实现，不能写成已完成。必须先完成正确 ABI9 SDK 全量回归、PyO3/Python/validator、双机 GPU/CPU 逐字节 smoke，再复跑同一固定负载。 |
| r51 当前实现 | `PlannedGetInfo` 只保留 put/source/controller/geometry/atomic-group 标量，不再保存 `Arc<OneKvNodesRoutes>` 或 activity lease。Plan 候选使用 `PlannedGetSourceSnapshot`，不 clone `KvRouteInfo`/Allocation；route 在 `planned_gets.insert(...).await` 前显式 drop。Plan miss 只返回 metadata miss；未 Bind plan 的 Revoke/TTL 只删除标量。Bind 在 per-operation lock 下校验 requester/target，安装 Get activity，再重读 route 并精确校验 source generation/geometry；route 变化返回独立 `StaleGetPlan`，成功后才移入 `inflight_gets` 和 touch Moka。容量驱逐、单 KV victim、GPU registration/destination 和 RDMA 数据路径均未改变。 |
| r51 观测与验证 | master 新增 `plan_items/hits/misses`、`bind_succeeded/stale/activity_busy`、`plan_revoked` 和 active plan 周期日志；owner 新增 planned CPU `local/leader/follower` 累计计数。NVMe target 位于 `/dev/nvme0n1p3`。最终 `fluxon_kv`/`fluxon_pyo3` check、3 项定向测试和全量 `198 passed/0 failed`已通过，并覆盖 11.79 的严格 source snapshot 修复；fmt/diff、四个 active Python compile、staging lifecycle validator 和 r51 编排 `bash -n` 也已通过。GPU-direct 与 CPU fallback 固定 payload 双 smoke、三节点部署哈希和正式负载现也已通过。 |
| r51 正式结果 | workload SHA256=`f6721d76...3f52`，S96×T24/2304/c24/system8192/output8/session-stream、Get32、tier1 5%、end-depth288、DMA0、metadata-only `128/128/256 GiB` 与 r49/r50 相同。结果=`2304/2304/0`、QPS=`8.150421`；TTFT p50/p90/p99=`1.2642/5.5807/9.6578s`，E2E=`1.6312/6.9649/11.3888s`；L1/L2/L3=`5.0428/0/68.1414%`、总命中=`73.1841%`。相对 r50 QPS `+16.47%`、总命中 `+6.97pp`；相对 r49 QPS `-21.35%`、总命中 `-1.42pp`。 |
| r51 Plan 控制面 | `plan_items/hits/misses=1352832/1244250/108582`；`bind_succeeded/stale/activity_busy=353000/338/0`，`plan_revoked=891250`。只有 `28.37%` hit 真正 Bind，`71.63%` hit 最终 Revoke。两个 owner planned CPU local/leader/follower=`835300/208976/0`；local 项约等于 Revoke 的 `93.72%`，说明 local-first 虽避免了重复物理传输，却发生在 master Plan 之后，仍留下大量重复 metadata/RPC/表项工作。 |
| r51 load-back/GPU-direct | 成功 load-back=`3899`，ready-wait mean/p90/p99=`1031/3600/7509ms`，total mean=`1306ms`；较 r50 的 `3681/1345ms` 恢复，但仍差于 r49 的 `4300/721ms`。GPU-direct selected=`262/2208`、tokens=`4619584`；`insufficient_free_slots=634`、`gpu_prefix_shorter_than_cpu=715`，多数请求仍整段回退 CPU。当前尚未实现同一请求 GPU+CPU 混合分段。 |
| r51 容量/网络闭环 | source-evict requests/victims/completed/retryable=`887/274641/272048/2593`；Busy 较 r50 `11227` 下降 `76.90%`，但仍高于 r49 `299`。两侧 handoff=committed=`213730+58318`，selected/retry/debt/pending 和 master activity/inflight 最终为 0。Remote Put transfers=published=`104982`、active/failed=0；CPU retained=`55341/261131599872B`。CPU 双 HCA TX avg/p99/peak=`47.688/251.418/351.881Gbps`，正式窗 sample error=0，链路未饱和。 |
| r51 性能裁决与下一步 | Mooncake L2+L3=`68.0051%` 目标已由 r51 的 `68.1414%` 达到，下一阶段转为 load-back/控制面优化。P0 把 owner local-first 和同 key/same-request 聚合提前到 master Plan 之前：local 直接复用，只有真正 remote 的 leader 才 Plan/Bind；P1 再让未使用 metadata 不产生逐 key Revoke；P2 才在固定 288-slot 预算内做分块/混合 GPU-direct。所有轮次继续固定 workload/config 单变量裁决。 |
| r50 文档与运行状态 | 分析文档=`20260723_0915_fluxon_r50_plan_bind正式结果与下一步.md`。正式窗 `1784768126.690–1784768455.942`，HCA raw 三端各 1397 行、导入 8370 rows 且 error=0。归档=`artifacts/e44_r50_plan_bind_enddepth288_netobs_no_go_20260723/`，共 192 个文件、约 220 MiB，`SHA256SUMS` 已通过。全栈停止后四卡先回到 `0 MiB/0%`；30245 在实验结束后被外部拉起的 inference 已精确终止，两侧 burner 已恢复。 |
| r49 改动与归档 | 相对 r48 正式归档，runtime/adapter/validator/variant/guard/YAML/deploy 加 admission 观测为 7 文件 `+552/-36`；正式结果后新增 286 行 analyzer，当前实现/配置/分析脚本合计 8 文件 `+838/-36`，artifact 生成证据不混入源码净 diff。归档=`artifacts/e44_r49_gpu_direct_admission_observe_passed_20260722/`，约 209 MiB；150 个非 manifest 文件进入 `SHA256SUMS` 并通过校验，含 workload、三机日志/HCA、Greptime DB、request metrics、runtime config、全量分析和清场证据。 |
| r48 容量/远端闭环 | 正式窗 direct-delete requests/victims/completed/retryable=`1874/778687/778233/454`；454 个全为 Get activity busy，owner retry scheduled/emitted=`454/454`，最终 selected/retry/debt/pending reclaim 全 0。Remote Put targets/transfers/published=`80349/80349/80349`、active/failed/replay=0；CPU retained=`55341/261131599872 B`。最后 route 计数 node0/node1/CPU members=`15020/15617/280`、bytes=`70873251840/73690251264/1321205760`。 |
| r48 网络/等待 | CPU 双 HCA TX avg/p99/peak=`130.013/352.878/421.312 Gbps`，sample error=0；GPU RX 约 130 Gbps。4308 条成功 load-back 的 total/ready-wait/restore/eviction/Get-transfer=`901.751/649.105/168.403/39.456/11.945ms`；消费前终态率=`95.487%`，真实 finish-wait 均值仅 `5.234ms`。主等待仍在 scheduler/prefill 消费侧。 |
| r48 当前运行与归档 | 32656/30245/30729 的隔离 r48 tmux server 和实验进程均为 0；恢复前四卡 `0 MiB/0%`，恢复后四个 managed burner 均约 `1395 MiB/100%`。正式 artifact 位于 `artifacts/e44_r48_gpu_direct_full_enddepth288_netobs_passed_20260722/`，包含 workload、三端 HCA、三机日志、request metrics、Greptime DB、derived 对账、runtime config 与 release manifest；SHA256 门禁见归档最终条目。 |
| r40 当前实验改动 | 新增 127 行 `benchmark_e44_r40_layer_group_submit.py`；active runtime 已恢复 sealed r39。Python compile、r35 lifecycle validator、r38 Get-prefix/adapter validator 均通过；尚未修改 Fluxon core 或 SGLang Git 工作树。 |
| r40 微基准裁决 | 30245/32656 四卡清场后，两台新机均证明 raw DMA 快于 kernel：288/576/864/1728/2880 pages 的 raw total 约 `25/50/75/150/249ms`，2880-page kernel 约 `279ms`。跨层 group=2 没有降低 submit，864/1728 pages total 反而约 `+0.8/+1.8ms`；CPU 本地/远端 NUMA 对 raw total 无实质差异。kernel、跨层合并、纯 CPU 亲和性均判 no-go，未进入正式轮。 |
| r40 已取消中间方案 | “同一 scheduler 轮首 operation 提前 H2D”没有部署或发流。它仍要求数据完整落 CPU 后再 H2D，会保留额外一跳和 GPU 等待延迟；用户明确改为部分 RDMA 直接落 GPU，因此该实现已从 active runtime 完整删除。历史估算 `15.91ms/batch` 只保留为被取消方案的理论上限。 |
| r40 当前候选 | SGLang 选择一部分完整 KV，分配并校验固定容量的 GPU staging；Fluxon 接口接收 GPU registration 与逐 KV destination，只负责把远端 bytes 传到给定地址。其余 KV 继续落 CPU 作为容量缓冲。首版不拆一个 KV 的 K/V/layer，也不改变单 KV 容量驱逐。 |
| r40 传输能力核查 | 旧 Python `register_buffer(device_kind="cuda")` 只保存描述符，PyO3 `register_buffer(ptr,len)` 仅做地址范围账本；`batch_get_into` 最终仍从 CPU holder 执行 `std::ptr::copy_nonoverlapping`。r39 `libfluxon_commu_core.so` 可见 `fabric_lib::cuda_support::host_only::Device` 和 `cuda support is disabled in host-only fabric-lib build`。这证明闭源库没有显式 CUDA device 分支，但尚不能排除 verbs `Device::Host` 配合 `nvidia-peermem` 注册 CUDA VA；必须以真实 GPU pointer registration smoke 裁决。现阶段绝不把旧 CPU copy 路径称为 GPUDirect。 |
| r41 当前接口实现 | Python 新增强类型 `GpuBufferRegistration`/`GpuDestination`，external client 显式提供 `register_gpu_buffer`、`validate_gpu_destination`、`unregister_gpu_buffer`；普通 `register_buffer` 收缩为 host-only。SGLang 提供 pointer、capacity、device id 并持有显存，Fluxon 不分配显存。Rust 为 external variant 构造 transfer engine 和零容量 `ClientSegPool`，以单一连续 staging range 的 generation token 管理 MR；逐 destination 做精确范围校验，活跃 transfer guard 存在时拒绝注销。GPU pointer 的 P2P/TCP fallback 被显式禁止，避免 CPU 解引用 CUDA VA。 |
| r41 当前数据面边界 | master wire 已新增 `ExternalSink` allocation mode 和逐 KV destination；Start 校验 external membership generation、地址/容量/registration id，且不分配 master slot；Done 不创建 holder、不做容量预留、不发布 route。external 已新增 generation/range 预校验、显式 GPU-only transfer 入口、后台 transferable-prefix 拉取、非前缀/失败/取消的整批 Revoke、成功整批 Done，以及 pending handle 终态；CUDA 地址禁止回退 CPU/P2P。当前尚未完成 PyO3/Python Get API 和 SGLang staging→最终 KV page 的 D2D scatter；旧 `batch_get_into` 仍只能复制 CPU holder。 |
| r41 本地门禁 | Cargo target `/mnt/nvme0/mjq_build/push_sglang_fluxon_target` 已由 `findmnt` 确认为 `/dev/nvme0n1p3`。registration 接口阶段的 `cargo check -p fluxon_kv --lib`、`cargo check -p fluxon_pyo3 --lib`、fmt check、`git diff --check`、Python compile 均通过；GPU registry 定向测试共 `4 passed`。2026-07-21 15:21 master `ExternalSink` 闭环、15:31 external 后台直拉核心分别用固定 NVMe target 执行 `cargo check -p fluxon_kv` 通过（仅既有 warning）；这些仍不是 PyO3、真实 GPU Get 或正式 workload 验收。首次运行旧定向测试 binary 因缺 `LD_LIBRARY_PATH` 以 rc=127 退出，补上 `fluxon_release/closed_sdk/lib` 后真实执行通过，不是代码断言失败。 |
| r41 pointer-registration 门禁（已降级解释） | NVMe release=`/mnt/nvme0/mjq_build/fluxon_e44_r41_gpu_register_smoke_20260721`，wheel SHA256=`e4fe82b8...8709265`、PyO3 SHA256=`29c774da...a4d8cf`，manifest 通过。32656 上 64 MiB Torch CUDA tensor 完成 register→范围校验→unregister，`registration_id=1`、约 `2085.895ms`、rc=0。r42 跨机证据现已证明，这只说明 raw 注册入口接受 CUDA VA，不能证明它按 GPU MR 注册或可做 GPUDirect；旧“无需 CUDA-enabled artifact”结论已取消。 |
| r41 smoke 编排结论 | 第一次 owner-only 等待因 node1 未启动，r39 fast-path readiness 按配置在 300s 后报告 `no eligible owner peers`；第二次 external 等待因 r41 commit=`1cb188c` 与 r39 shared.json=`aafac11` 的严格 protocol mismatch。两端 owner 同时改用 r41 后，真实 peer gate、segment registration 和 shared.json 均通过；两次都未调用 CUDA MR，不能算 SDK 失败。 |
| r42 open 数据面 | `ExternalSink` 不分配 CPU slot/holder、不发布 route；GPU destination 做 generation/range 校验，后台任务负责 RDMA-only Transfer 与整批 Done/Revoke，禁止 CUDA VA 落入 CPU/P2P fallback。PyO3/Python 已暴露 `get_start_gpu/get_transfer_gpu/cancel_get_transfer_gpu`。master 过滤 external 本机 share-group owner。 |
| r42 SGLang staging | 隔离 runtime 固定 288 页 staging，约 `1.266 GiB/TP`；只有整次请求且所有 TP 都拿到一致 staging 时走 GPU，否则回到原 CPU 路径；Mamba 首版仍走 CPU。transferable prefix 完成后才 trim，多余页和 success/cancel/error/reset/异步 layer finish 全生命周期均由 lease 回收；staging→最终 KV 页复用既有 restore kernel，GPU source 显式绕过 H2D DMA。相对 r39 封存源，runtime/adapter 净差分别为 `+337/-95`、`+263/-0`。 |
| r42 已通过门禁 | `cargo fmt --all`、`cargo check -p fluxon_kv`、`cargo check -p fluxon_pyo3 --lib`、GPU registry `4 passed`、新增 `get_id=0` 回归测试、Python compile、r42 AST/lease validator、全部 shell `bash -n` 通过。32656 真实 H100 的完整多层和逐层 D2D scatter 均逐字节一致，最近 786432-byte full/layerwise 分别约 `0.953/0.124ms`。这些验证不等于跨机 GPUDirect。 |
| r42 release | NVMe release=`/mnt/nvme0/mjq_build/fluxon_e44_r42_gpu_direct_staging_20260721`，修复 `get_id=0` 后 wheel SHA256=`bf1b5f90...9a89`、PyO3 SHA256=`3ac07f55...a3894`；manifest、隔离 venv 和 32656/30245 部署哈希均通过。没有切换正式 r39 active runtime。 |
| r42 跨机 attempt1 | 两机四卡清场为 `0 MiB/0%` 后，node1 写入 `4,718,592 B`，node0 GPU Get 在 master plan 校验处失败：master 的合法首个 `get_id=0` 被新 GPU 路径误当无效哨兵。master `next_get_id` 本来就从 0 开始；已删除该错误假设并补回归测试，重打 release。 |
| r42 跨机 attempt2/诊断 | `get_id=0` 修复后已进入真实 transfer，但 closed SDK 未走 RDMA fast path，转入 host/P2P callback；GPU fallback 按设计被拒绝，Get 安全 Revoke。额外只在 smoke 中等待 10 秒仍同形失败，排除单纯启动 warmup；该临时 sleep 已删除，最终 smoke SHA256 已恢复为 release 内的 `6ca9bf0a...47c2f2`。没有发生 payload 错写，也没有成功的跨机 GPU Get。 |
| r42 当前根因 | open/closed contract 的 `RegisterLocalSegment` 只有 addr/size；closed runtime 将 `Closed` 映射为 PPLX，PPLX `register_local_segment` 固定调用 `Device::Host`。当前 `libfluxon_commu_core.so` 还明确包含 `cuda support is disabled in host-only fabric-lib build`。因此 r41 的“注册成功”不是 GPU MR，现有 artifact 无法被认定为 GPUDirect-capable。 |
| r42 下一门禁 | 先让 open/closed 注册协议显式携带 `Host`/`Gpu{device_id}`，PPLX GPU 分支使用 `Device::Cuda(CudaDeviceId)`，并构建启用 `fabric-lib/cuda` 的 closed SDK；同时给 GPU transfer 提供“等待/要求 direct fast path、绝不 fallback”的可判定终态。只有同一 4,718,592-byte 两机逐字节 smoke 通过后，才接 active SGLang 做固定负载；正式参数仍为 Get32、tier1 5%、end-depth288、128/128/256 GiB、S96×T24 c24。 |
| r42 当前运行状态 | 两轮失败及 10 秒诊断轮都已完整停止 master/owner/control，并恢复两机 managed burner；`inference_like_compute.py` 和 SGLang/Fluxon 服务进程为 0。四卡当前均由 burner 占用约 `1386 MiB/100%`；32656 GPU1 的 watchdog 显示 managed-waiting，但 PID 472 已回读确认就是同一 managed burner，不是推理干扰。 |
| r43 closed/PPLX 当前设计 | open/closed schema/ABI 为 `6/9`，注册显式携带 `Host` 或 `Gpu { device_id }`；GPU Get 带 `require_fast_path`，禁止落入 P2P。正确 closed 源仍保留每个 transfer-engine client 一个 `local_segment_binding`，没有引入多 MR。external GPU Get 使用独立、零 CPU pool 的 client，因此这一处单 binding 就是 SGLang 预留的整段 GPU staging MR；普通 owner 的 CPU pool 仍由原 client 管理，二者不互相覆盖。PPLX GPU 分支使用 `Device::Cuda(CudaDeviceId)`。 |
| r43 CUDA 构建边界 | 正确 closed 源已有 `te_pplx_cuda` 和可选 GDRCopy；本轮只启用 CUDA driver/runtime。补齐旧 PPLX CUDA 的 EFA 常量、pointer-attributes、UVM import/type、按 MR device 注销问题；`pack_closed_sdk.py` 可显式挂载 NVMe target、prepare store 和只读 CUDA_HOME，SDK 同目录打包 `libcudart.so.12`。没有引入多 MR。 |
| r43 本地门禁 | 正确源 Host/CUDA check、manylinux CUDA SDK 和 wheel closure 均已通过。SDK=`/mnt/nvme0/mjq_build/fluxon_closed_sdk_abi9_pplx_cuda_correct_20260721`，release=`/mnt/nvme0/mjq_build/fluxon_e44_r43_gpu_direct_cuda_20260721`；wheel SHA256=`81a4d36887568e1bb30761fa47c52fafa03a9548e112f2919497a7ce06873e36`。wheel 内 `libcudart.so.12` 已打包，`libcuda.so.1` 只解析节点 NVIDIA Driver；两机回读 ABI/schema=`9/6` 和组件哈希一致。 |
| r43 跨机结果与根因 | 固定 key=`fluxon_e44_r42_gpu_get_smoke_20260721`、seed=`73`、payload=`4,718,592 B` 共运行首轮加三轮诊断，全部在约 5 秒、约 418–427 次 direct-only 重试后安全 Revoke；payload 未写错，未产生 QPS。诊断中没有出现 PPLX reverse-copy submit marker，结合 closed tier manager 源码确认：`should_dial_peer` 只允许 external 连接本机 owner，`direct_transfer_capability` 又没有 `External↔Client` segment 能力，因此 external reader 从未把远端 owner1 放入 direct transfer peers；不是 CUDA MR 注册失败，也不是等待时间短。 |
| r44 当前修复 | `fluxon_commu/src/p2p/tier_manager.rs` 允许 external 对跨机 Client owner 建 direct lane，并为 `External↔Client` 双向只开放 `enable_transfer_segment=true`、保持 `enable_transfer_rpc=false`；同机 owner 仍由 intra-machine gate 截获，普通 external RPC 路由不变。新增两项角色矩阵测试均在 CUDA feature 下真实执行通过。smoke runner 只新增 writer/reader `RUST_LOG` 可配置诊断旋钮，不改变 key、seed、payload 或正式负载。 |
| r44 closed SDK | 已由正确 closed 源生成 `/mnt/nvme0/mjq_build/fluxon_closed_sdk_abi9_pplx_cuda_r44_peer_gate_20260721`，manifest ABI/schema=`9/6`；core SHA256=`8978a52d...0f77`，显式依赖 `libcudart.so.12`、节点 driver `libcuda.so.1` 和 `libfluxon_rdma_probe.so`。SDK 生成不等于 wheel、两机部署或跨机数据正确性验收。 |
| r44 wheel | 独立 release=`/mnt/nvme0/mjq_build/fluxon_e44_r44_gpu_direct_peer_gate_20260721` 已构建成功，wheel SHA256=`5cff6fa7...9545`、PyO3 SHA256=`460eb98b...287b`；release manifest 全通过。wheel 内含 core/probe/cudart，`libcuda.so.1` 只由目标节点 driver 提供；本机 `ldd` 无 missing。auditwheel 会改写 ELF/RPATH，所以 wheel 内 core/probe/cudart 哈希与原 SDK 输入不同，这是打包产物变换，不是混入旧库；r44 wheel core=`55eb59eb...3d09`，也明确不同于 r43 wheel core=`367cd8ad...ba05`。 |
| r44 两机部署 | 32656/30245 已部署到隔离 venv=`/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r44-gpu-direct-peer-gate-20260721`；两端 wheel/PyO3/core/probe/cudart 哈希一致，manifest 回读 ABI/schema=`9/6`，`ldd` 均从 wheel 解析 core/probe/cudart、从各节点 driver 解析 `libcuda.so.1`，无 missing。没有覆盖 sealed r39 或 r43 venv。 |
| r44 smoke preflight | 首次 r44 smoke 在启动 control/master/owner 前被 GPU 清场门禁拒绝，没有发流、没有 transfer 结果。根因是 30245 GPU0 遗留一个真实 burner PID，但已脱离 burner 管理脚本状态，`stop --no-restart` 没有终止它；不是 inference/SGLang/Fluxon 负载。runner 已增加按命令行兜底 TERM、等待、KILL，覆盖全部 `.gpu_burn_script_` 和 `inference_like_compute.py`；`bash -n` 通过，待原样重跑。 |
| r44 smoke attempt2 | 加固后两机四卡清场为 `0 MiB/0%`，master/owners ready，固定 writer 成功写入 `4,718,592 B`、SHA256=`bd0c9278...ed19`；但 reader 初始化前 node0 etcd 已变为 connection refused，故 GPU registration/Get/transfer 均未开始。etcd 日志无正常 shutdown，节点无 OOM 记录；trap 已停栈并恢复 burner。该轮是 control-plane 编排失败，不是 r44 数据面失败，也没有 QPS。下一步先用 control-only probe 验证二次清场是否误杀 etcd。 |
| r44 control-only probe | 独立启动 control 后，执行与 reader 前逐字相同的 burner/inference 二次清场，等待 10 秒；etcd 清场前后均健康并成功提交 proposal，tmux session 与 etcd PID 仍存活。probe cleanup 已停 control 并恢复 burner。由此排除 runner 清场误杀；attempt2 的一次性 control 丢失更符合外部默认 tmux/control 干扰，当时可见另一套 benchmark 收尾 shell，当前 pilot/case/rclone/benchmark 进程已为 0。 |
| r44 smoke attempt3 根因 | attempt3 在 writer 的普通 `local_fast_put_start` 遇到 P2P 608，仍未进入 GPU Get。现场确认 32656 于 12:19:27 被另一套 `/pvcteam/mjq/fluxon_s3_benchmark` 启动 `fluxon-formal-gpu-guard`：两卡 `gpu_idle_guard.py` 各占 520 MiB、util=0%，并在默认 tmux server 中只留下 guard session；这与本轮 control/master 消失时间吻合。不是 burner、inference 或 r44 数据面失败。该 guard 当前仍在，未擅自终止。 |
| r44 smoke 编排隔离 | runner 新增独立 `TMUX_TMPDIR=/run/fluxon_e44_r44_gpu_get_tmux`，control/master/owner/cleanup 全部继承同一 socket namespace，避免外部默认 tmux 接管；并把 `gpu_idle_guard.py` 纳入发流前硬门禁。该方向精确 delta=`+12/-8`；`bash -n`、active-guard rejection、独立 tmux 与默认 formal guard 并存/独立 kill-server 验证均通过。 |
| r44 冲突清场授权 | 用户已明确授权终止冲突进程。执行时 32656 的 formal guard/default tmux 已自行退出且 GPU 已空；30245 仅剩 managed burner PID 29689/30007，已精确停止且禁用自动拉起。两节点最终 formal guard、pilot/case、burner、inference 与 GPU compute PID 均为 0，四卡均回读 `0 MiB/0%`。 |
| r44 clean attempt4 | 在外部冲突为 0、四卡 `0 MiB/0%`、独立 tmux namespace 下，control/master/owners 均 ready；writer 的 msg 4022 `ExternalBatchPutStartReq` 仍在 external→本机 node1 owner 的普通 RPC 上超时并报 P2P 608。master Put/placement 计数始终为 0，owner handler 无请求记录；GPU reader、MR、Get 和 PPLX transfer 均未开始。由此排除外部进程并将问题收敛到 r44 external 普通 RPC/local-IPC 连接回归或初始化竞态。 |
| r44 writer info 诊断 | 完全相同配置仅把 writer `RUST_LOG` 提升为 info 后，msg4022 与 commit 成功，固定 payload 写入 SHA256=`bd0c9278...ed19`；说明 attempt4 是初始化竞态而非必现协议破坏。随后 `store.close()` 从 12:38:58 卡到人工中断后的 12:44:32，20 秒时明确报告 ClusterManager/P2pModule 仍有 live `ClientTransferEngineCore` dependent；reader 未启动。 |
| r44 smoke 生命周期隔离 | `smoke_e44_r42_gpu_get.py` 新增显式 `--hard-exit-after-success`（`+12/-0`）：writer 成功发布结果后绕过有缺陷的 close；reader 先注销 GPU registration，再发布成功并绕过 close。runner 对 writer/reader 都增加 90 秒 TERM+5 秒 KILL 进程门禁（`+4/-4`）。默认行为未变，生产 API 未改；生命周期 hang 继续作为独立 P1。两机脚本 SHA256=`12ec851f...3378`，语法编译与 shell `bash -n` 通过。 |
| r44 guard 再次清场 | 20:47 32656 又被外部拉起 `fluxon-quick-gpu-guard`（PID 18007/18010）；按用户授权精确杀掉该 tmux session/PID，并再次停止 30245 burner。最终两机冲突进程与 GPU compute PID 均为 0，四卡回读 `0 MiB/0%`。 |
| r45 external init readiness（失败） | r45 在 external init 中等待 exact owner generation 的 `is_send_ready_intra_effective`。原 payload smoke 证明真实 peer 30 秒内始终为 `intra_conn_ready=false, direct_conn_ready=true`，因此该门禁等错 lane 并在 writer 初始化阶段失败。closed `resolve_outgoing_route_to_target()` 明确先选有效 intra、再选 direct，故 ForceTransport 的正确门禁应是 exact generation 的 `is_any_send_ready`，而不是强制 intra。源码相对 r44 wheel仍为 `+48/-0`，但该实现不得作为正确性基线。 |
| r45 wheel/本机闭包 | 独立 release=`/mnt/nvme0/mjq_build/fluxon_e44_r45_gpu_direct_intra_ready_20260721` 构建 rc=0；wheel SHA256=`3e04a0b5...56c9`、PyO3=`bf61de0b...a6f5`，ABI/schema=`9/6`，release manifest 与 r42 staging validator 全通过。wheel 内 core/probe/cudart 分别为 `55eb59eb...3d09`、`e925553e...5883`、`5b8de0ee...dc82`，与 r44 closed 输入打包结果一致；`libcuda.so.1` 只由目标驱动提供，本机 `ldd` 无 missing。该产物现已隔离部署，但尚未完成跨机数据正确性。 |
| r45 两机部署 | 32656/30245 已部署到独立 release=`/storage/mjq/sglang_fluxon/releases/fluxon_e44_r45_gpu_direct_intra_ready_20260721` 与 venv=`/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r45-gpu-direct-intra-ready-20260721`。两端 wheel/PyO3/core/probe/cudart 哈希、ABI/schema=`9/6` 与 smoke SHA256=`12ec851f...3378` 全部一致；`ldd` 从隔离 wheel 解析 core/probe/cudart、从节点 driver 解析 `libcuda.so.1`，无 missing。尚未启动数据面。 |
| r45 smoke 结果 | 固定 key/seed/size、writer `warn` 的 smoke 在 `new_store` 等待 30 秒后按门禁失败；peer snapshot 精确为当前 owner generation、`intra=false/direct=true`。writer 未构造成功，Put/Get/GPU MR/PPLX transfer 均未开始，没有 payload 错写或 QPS。trap 已停本轮服务并恢复两机 managed burner。 |
| r46 当前修正 | 保留 exact `(owner_id, owner_start_time)` 与 30 秒 fail-closed，把条件从 `is_send_ready_intra_effective` 改为 `is_any_send_ready`；函数、常量、日志/错误文本统一改称 owner `RPC transport route`。这与 closed ForceTransport 路由的有效 intra/direct 选择一致，不放宽 generation、不接受未 ready peer、不改 wire/Put/Get/GPU transfer。fmt、diff check 和 NVMe `cargo check -p fluxon_kv --lib` rc=0。 |
| r46 wheel/本机闭包 | 独立 release=`/mnt/nvme0/mjq_build/fluxon_e44_r46_gpu_direct_rpc_route_ready_20260721` 构建 rc=0；wheel=`85cfc1fe...1a5b`、PyO3=`58182525...6575`，均不同于 r45，证明修正进入产物。ABI/schema=`9/6`、release manifest 与 staging validator 全通过；core/probe/cudart 哈希保持 `55eb59eb...3d09`、`e925553e...5883`、`5b8de0ee...dc82`，本机 `ldd` 无 missing。现已隔离部署，但尚未完成跨机数据正确性。 |
| r46 两机部署 | 32656/30245 已部署到独立 release=`/storage/mjq/sglang_fluxon/releases/fluxon_e44_r46_gpu_direct_rpc_route_ready_20260721` 与 venv=`/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r46-gpu-direct-rpc-route-ready-20260721`。两端 wheel/PyO3/core/probe/cudart、ABI/schema 与 smoke 哈希完全一致；`ldd` 从 r46 venv 解析 closed 组件、从节点 driver 解析 `libcuda.so.1`，无 missing。该部署已用于 attempt1，未切换正式 runtime。 |
| r46 smoke attempt1 | writer `warn` 成功写入 SHA256=`bd0c9278...ed19`；reader exact-generation route 仅等 `21ms`，出现 `FLUXON_PPLX_REVERSE_COPY_BATCH batch_items=1`。GPU→CPU 回读后的 `actual != expected` 检查已通过，随后 MR 注销成功；但脚本先把 `registration=None`，再访问 `registration.registration_id`，触发 `AttributeError`，故 runner rc=1、未打印 success JSON。这是成功上报 bug，不是数据 mismatch。 |
| r46 smoke 上报修复 | smoke 在 MR 注销前保存 `registration_id`，success JSON 使用保存值；精确 delta=`+1/-1`，不改 r46 wheel/运行时/payload。Python 内存编译与 runner `bash -n` 通过，两机脚本 SHA256 均更新为 `36cd173d...9c46`。 |
| r46 smoke attempt2 | 同一 wheel/venv、修复后的 smoke 与固定输入下，writer msg4022 再次超时，owner Put/flight 仍为 0；reader 未启动。说明 r46 any-send-ready 只移除了 r45 错误阻塞，未消除原始竞态；attempt1 成功不能封为稳定基线。 |
| 新根因 | readiness 当前在 `owner_shared_mem_bundle_ready` resource 内执行，但 external 的 `set_self_share_group_binding()` 位于其后的 `init2_after_owner_shared_mem_bundle_ready()`。因此门禁看到的是绑定前临时 direct route；随后发布 binding 会让 closed tier plan 从 direct 切换为同机 intra-only，首个 PutStart 恰好撞上 teardown/建链窗口。r45 等不到 intra、r46 偶发成功/失败可由同一顺序解释。 |
| r47 当前修正 | resource 恢复为只等待 shared memory + exact owner membership；`init2_after...` 先注册 RPC，再发布 exact owner binding 与 sub-cluster，最后同时要求 tier snapshot 已观察到 self binding、owner generation 精确匹配且 `is_send_ready_intra_effective`。30 秒 fail-closed，无固定 sleep，不接受过渡 direct。fmt/diff/NVMe Cargo check rc=0。 |
| r47 wheel/本机闭包 | 独立 release=`/mnt/nvme0/mjq_build/fluxon_e44_r47_gpu_direct_post_binding_intra_ready_20260721` 构建 rc=0；统一 wheel=`983e4605...61d5`、PyO3=`ef48cf98...b162`，与 r46 均不同，证明 r47 顺序修正进入产物。release manifest、staging validator 与 ABI/schema=`9/6` 通过；core/probe/cudart 保持 `55eb59eb...3d09`/`e925553e...5883`/`5b8de0ee...dc82`，`libcuda.so.1` 仅来自系统 driver，本机 `ldd` 无 missing。该本机门禁已被后续两机 smoke 部署和本次正式 variant GPU 部署覆盖。 |
| r47 两机部署 | 32656/30245 已部署到独立 release=`/storage/mjq/sglang_fluxon/releases/fluxon_e44_r47_gpu_direct_post_binding_intra_ready_20260721` 和 venv=`/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r47-gpu-direct-post-binding-intra-ready-20260721`。两端 wheel/PyO3/core/probe/cudart 哈希、ABI/schema=`9/6`、smoke=`36cd173d...9c46` 完全一致；`ldd` 从 r47 venv 解析 closed 组件、从节点 driver 解析 `libcuda.so.1`，无 missing。部署阶段未启动服务或发流。 |
| r47 smoke attempt1 | 固定 key/size/seed、writer `warn` 下完整 rc=0。writer SHA256=`bd0c9278...ed19`；reader 在 binding 发布后约 `2026ms` 观察到 exact-generation intra ready，出现 `FLUXON_PPLX_REVERSE_COPY_BATCH batch_items=1`，GPU→CPU 回读逐字节比较通过、MR 注销成功。这是 r47 第 1 轮成功，还需连续第 2 轮排除 r46 式偶发性。 |
| r47 smoke attempt2/裁决 | 不改 wheel、脚本或输入再跑，完整 rc=0。binding 后 exact-generation intra 等待约 `2000ms`；writer/reader 仍是 SHA256=`bd0c9278...ed19`，PPLX reverse-copy 再次真实出现，逐字节比较、MR 注销均通过。r47 连续两轮排除了 r46 的直接→intra 切换竞态，可封为 remote-owner GPU Get 正确性 smoke 基线；尚不是完整 SGLang 固定负载或 QPS 验收。 |
| 完整正式轮口径 | 保持 r39 正式轮的 S96×T24、2304 请求、concurrency 24、system 8192、output 8、session-stream、Get32、tier1 5%、end-depth288、DMA0 和 metadata-only 128/128/256 GiB；唯一行为变量是 r47 Fluxon + r42 GPU staging SGLang。不得在缺 CPU owner 时偷跑两节点不可比轮。 |
| 当前集群状态 | CPU root 已用 `infra44_ed25519` 恢复登录，新内网 IP=`10.233.125.128`；r47 host-only 部署和 256 GiB owner 启动门禁均通过。r47 TP2 失败轮已停 control/master/三 owner/两 SGLang/三 observer，两 GPU 节点 managed burner 已恢复，四卡约 `1395 MiB/100%`；没有正式请求或遗留服务。 |
| CPU r47 产物准备 | host-only SDK 和 CPU wheel 均已完成。CPU release=`/mnt/nvme0/mjq_build/fluxon_e44_r47_gpu_direct_full_cpu_host_20260721`，wheel=`6e23ad05...db9b`、PyO3=`ef48cf98...b162`、wheel 内 core/probe=`63c08ee6...6e06`/`e925553e...5883`。PyO3 与 GPU wheel 精确相同，证明 open r47 一致；只有 closed runtime 按 host/CUDA 分产物。CPU wheel 不含也不依赖 `libcuda`/`libcudart`，ABI/schema=`9/6`、manifest、ABI3 cp310/cp311/cp312 import、r42 lifecycle validator 和本机 `ldd` 均通过。 |
| r47 正式轮编排改动 | 新增 fail-closed 三节点部署脚本 169 行、r47 master YAML 28 行；variant 新增 23 行，GPU/CPU launcher 各 `+2/-2`，GPU clear guard `+1/-1`，本方向当前 6 文件合计 `+225/-5`。CPU core/probe 占位已替换为实际 wheel 哈希，全目录无 `PENDING`；shell 语法、variant 参数、r39/r47 YAML 除 `log_dir` 等价和 r42 lifecycle validator 均通过。32656/30245 的正式 GPU 部署已通过；30729 不可达，CPU 部署尚未执行。 |
| r47 TP2 正式启动裁决 | 固定参数下两 GPU 节点的 TP0 可注册 288-slot GPU staging，TP1 均在 `register_gpu_buffer(device_id=1)` 稳定失败：PPLX `register_memory_allow_remote -> Worker not found`。保持 owner 不变的 `SGLANG_ONLY` 重试同形复现，排除 CPU IP、启动顺序和偶发波动。两次都在 HTTP ready/发流前失败，没有 QPS。 |
| r48 当前修复 | closed PPLX 每个 external 进程只构建一个 RDMA domain worker，其 key 固定为 0，但 MR 保留真实 CUDA device。`fabric_engine.rs` 现在仅当 worker 数精确为 1 时允许非零 CUDA device 复用该 RDMA worker；多 worker 引擎仍严格匹配。单文件本方向 patch=`+46/-7`，净增 39 行，SHA256=`0508a361...5c21`。 |
| r48 已通过门禁 | `rustfmt --check`；host 与 CUDA feature 下的 single-worker nonzero-device/multi-worker strict-match 测试各 `1 passed`；固定 NVMe target 和 prepare resource store 下 `cargo check -p fluxon_commu_closed_sdk --features tcp_thread_transport,te_pplx_cuda` rc=0。独立 CUDA SDK=`/mnt/nvme0/mjq_build/fluxon_closed_sdk_abi9_pplx_cuda_r48_single_worker_gpu1_20260722`，manifest ABI/schema=`9/6`、core=`6b39533b...d44d`；独立 GPU release=`/mnt/nvme0/mjq_build/fluxon_e44_r48_gpu_direct_single_worker_gpu1_20260722`，wheel/PyO3/wheel-core=`cc5e2e0e...590b`/`36f83361...29eb`/`e64bcfb3...148c`，release manifest、ABI3 打包和 r42 staging lifecycle validator 全部通过。首次 check 未指定封存 resource store，被 cxxpacked 完整性校验正确拒绝；补上 `/mnt/nvme0/.../fluxon_closed_prepare_resource_store_20260721` 后通过，不是代码错误。 |
| r48 编排状态 | 新增 r48 variant、等价 master YAML 和独立 deploy wrapper；r47 deploy 被收敛为带默认值的可复用入口，并显式支持 `infra44_ed25519`，默认 r47 行为不变。首轮 5 个编排文件合计 `+89/-17`；另有 CPU 新 IP 的三个 launcher 精确替换 `+3/-3`。三端部署哈希已全部通过，CPU 使用同一 ABI/wire/open 的 r47 host-only wheel但安装在独立 r48 release/venv。两机 TP0/TP1 staging 均完成，TP1 明确为 `device=1`，两侧 HTTP 31001 均达到 200，证明 closed `Worker not found` 已修复。 |
| r48 正式 attempt1 | 固定负载原样发流；约 25 秒后 workload rc=1，不能计 QPS。两机 TP1 都显示后台 DMA worker 被错误初始化为 `device=0`，首次 CPU-backed restore 即以 `Event device 1 does not match recording stream's device` 退出；TP0 无此问题。服务端日志证明已开始处理请求，但未形成完整 phase/result。owner/master/control/observer 保留用于修复后续启，burner 未恢复。 |
| r48 TP1 DMA 修复 | `self.device` 在 TP1 为 index-less `cuda`；新 Python worker thread 的默认 current device 是 0。runtime 现在在 scheduler 主线程启动 executor 前冻结真实 CUDA device id，并让后台 resolver 始终复用。runtime/validator/variant/deploy 共 5 文件本轮 `+30/-2`；新 runtime SHA256=`075461f1...19e3`。Python compile、扩展 AST 顺序/复用 validator、shell 和 variant hash 门禁均通过，尚未完成集群重启验收。 |
| 下一门禁 | 将新 runtime/variant/validator 精确部署到两机，保持现有三 owner/control/master 不变，用原生 `SGLANG_ONLY` 重启两侧；必须看到 TP1 background worker=`device=1`、TP0=`device=0` 且 HTTP 200。随后删除 attempt1 的残缺 workload 输出并按完全相同口径从头重跑 2304 请求；发流前再次确认无 burner、inference、guard 或外部 benchmark。 |
| r40 运行状态 | 微基准前已精确终止 node0 PGID `19061`、node1 PGID `17463` 的 `inference_like_compute.py`，延时确认四卡 `0 MiB/0%` 后才执行。微基准没有启动 Fluxon/SGLang 正式栈；正式实验前仍须再次清场并延时复核。 |
| r35 当前工作树 | 只改实验实际部署的 SGLang hostless runtime 源和 r35 编排，不改 `Fluxon` Rust/Python binary。按 r34 SHA256=`72d3...8bee` 的精确 SGLang 基线统计，runtime 为 `+603/-10`；variant `+13/-0`、launch hash 门禁 `+1/-1`，新增 deploy/master YAML/validator=`99/28/159` 行，发流前合计 6 文件 `+903/-11`。发流后新增 418 行离线 lifecycle 分析器，因此 r35 源/编排/分析工具累计 7 文件 `+1321/-11`；生成 JSON 与 artifact 文档单独记录，不冒充运行代码 diff。它按 rid/rank 记录 prefetch decision、Start/ready/consume pages/bytes、terminal reason，并拆同步 eviction 的 already-backed/write-back/wait/free；没有改变等待、RPC、Get32、tier1、admission、victim 选择或 handle trim。 |
| r35 当前门禁 | runtime SHA256=`895951ad...70c27`；Python compile、隔离 observation helper/格式化日志/计数器 validator、`git diff --no-index --check`、shell `bash -n`、replica JSON、r34/r35 YAML 去除隔离 `log_dir` 后等价、variant/hash 对齐均通过。测试前已精确终止外部 `inference_like_compute.py`，确认四卡 `0 MiB/0%` 后才启动；负载后完整停栈。三端 Fluxon release/venv 仍为 r34，r35 只替换 SGLang 观测源。 |
| r35 实测结果 | workload rc=0，`2304/2304/0`；QPS=`9.733413`，TTFT p50/p90/p99=`1.716768/3.097042/4.897846s`，L1/L2/L3=`3.84578/0/69.29157%`，总命中=`73.13735%`。表面 QPS 比 r34 高 `5.84%`，但 L3 低 `2.08974pp`、总命中低 `0.81655pp`，物理 L3 读取也更少；这是诊断轮，不是性能优化验收，不替代 r34。 |
| r35 load-back 结论 | prefetch submit/Get Transfer/ready/init-load/DMA complete 全部为 `4286`。478 条空 load-back 完整分解为：130 条真无 ready（76 rate-limit + 34 zero-transferable + 20 TP no-common）、61 条成功终态被尾巴尝试覆盖、287 条 consumed 后残余尾巴尝试。表面 `83.14 GB ready-not-consumed` 不是真实传输浪费，应修 observation identity。 |
| r35 eviction 结论 | 4225 条可靠 consumed 终态中，eviction mean/p50/p90/p99=`56.686/5.508/181.250/212.969ms`；free-group 累计 `218309.579ms`，占 eviction 累计时间 `91.15%`，`1439/4225` 次超过 50ms。驱逐 tokens 中 `97.699%` 已 backed，新写回只占 `2.301%`；remote write 不是当前大头。 |
| r35 容量与远端闭环 | direct-delete requests=`1537+656=2193`，victims/completed/retryable=`817102/817102/0`；handoff/committed node0=`624174/624174`、node1=`192928/192928`；selected/retry/debt/pending 与 master activity/inflight 全归零。CPU retained=`55329/261074976768B`。master replica targets=`91997`，owner transfers/published=`91997/91997`，terminal replay=0。remote-Put active=0，但累计 failed=`487+11`，仍需单独归因。 |
| 四方向串行计划 | `20260720_140543_fluxon_kv四方向逐项性能优化与实验追踪.md` 的方向 1/2/3 已裁决。r39 run ID 实际用于 observation-only Get-ready 拆解，不是方向 4 行为补丁；其 Remote Put targets/transfers/published=`80001/80001/80001`、failed/replay=0，当前没有重复传输证据，方向 4 降为观察项。 |
| r36 离线证据 | 新分析器严格按 node/TP FIFO 对齐 `2710/2710` 个 restore submitted/background batch，并用同一 background submit 终态闭合 `4286/4286` operations、`1193596` pages。background submit mean/p50/p90/p99=`30.930/18.297/56.684/198.347ms`；1/2 operations 基本线性，3/4/5/6 operations 分别放大到单 operation 线性外推的 `1.37/1.63/1.74/2.20×`。pages 与 submit 相关系数=`0.9277`，超线性从约 862 pages 开始。 |
| r36 历史候选 | `SGLANG_FLUXON_HOSTLESS_DMA_MAX_DESCRIPTORS_PER_CALL` 默认 0；r36 曾设为 `1152`。MHA 每 page 为 K/V 两个 raw descriptors，因此约 576 pages 以下保持每层一次 API；更大 batch 在同一 layer/worker stream 内顺序切 call。该候选已 no-go，active runtime 不含 cap，不得以此源继续叠加 r38。 |
| r36 当前改动量 | 相对 sealed r35 artifact：runtime `+68/-13`、variant `+14/-0`、GPU launcher `+2/-0`；新增 restore 分析器/validator/微基准/deploy/YAML=`576/212/177/106/28` 行。实验源/编排/工具合计 8 文件 `+1183/-13`。另新增四方向追踪文档 251 行；生成的 JSON 不冒充源码 diff。Fluxon 16 文件 `+2244/-912` 净 diff 未变化。 |
| r36 微基准门禁 | runtime SHA256=`c53cd68b...c63572f`，三端部署通过；r35 rollback、r34 release/PyO3/metadata patch 与两个 validator 全部对齐。四卡 288/576/864-page H2D 数据校验通过。864 pages 时 cap1152 四卡平均 submit=`47.977ms`，比 uncapped `46.566ms` 慢 `3.03%`；total=`74.753ms`，比 `74.967ms` 快 `0.28%`。该空闲微基准只证明数据正确，后续端到端已否定性能候选。 |
| r36 正式结果 | 原固定 S96×T24、2304 请求、c24、Get32、tier1 5%、end-depth 288、metadata-only 128/128/256 GiB；workload rc=0、`2304/2304/0`。QPS=`2.932363`，TTFT p50/p90/p99=`5.220/17.713/23.523s`，L1/L2/L3=`4.99181/0/57.44340%`，总命中=`62.43521%`。相对 r34 QPS `-68.11%`、L3 `-13.93791pp`，明确 no-go。 |
| r36 恢复根因 | restore batches/operations/pages=`2562/3686/1031872`；cap 把 DMA calls 增到 `112248`（若每 batch 36 次则为 `92232`）。restore p90/p99=`706.944/1127.598ms`，r35 为 `428.566/609.350ms`；load-back ready wait mean/p90=`3618.8/9242.1ms`，r35=`776.0/1797.7ms`；free-group mean/p90=`164.36/442.48ms`，r35=`51.67/176.68ms`。同 bytes 被更多 API calls 拆分后触发 restore→等待→驱逐反馈，不是普通波动。 |
| r36 网络/容量闭环 | 正式窗 CPU 双 HCA TX avg/p99/peak=`26.772/230.061/282.765Gbps`，CPU TX=`2628329325672B`、两 GPU RX=`2628329373192B`，只差 `47520B`，sample error=0；fabric 未持续饱和。direct-delete node0/node1 requests=`1047/729`、victims/completed/retryable=`419157+210422/同值/0`；handoff=committed 精确闭合，selected/retry/debt/pending/in-progress 与 master activity 全归零。CPU retained=`55341/261131599872B`，replica targets=`110284`、owner transfers/published=`110284/110284`，owner final failed=`0+17`。 |
| r36 裁决与 runtime | 不继续扫 descriptor cap 阈值。r36 全栈、observer 和 workload 已停止；两 GPU active site 已用预先封存的 r35 源回退并校验 SHA256=`895951ad...70c27`，r34 release 未动。空闲期 `inference_like_compute.py` 可占卡；正式试验前必须同时停止 managed burner/watchdog 和该脚本的所有父子进程，延时确认四卡 `0 MiB/0%`。 |
| r36 归档闭环 | artifact 共 137 个文件、约 227.4 MiB；除 manifest 自身外的 136 个文件全部纳入 `SHA256SUMS`，`sha256sum -c` 通过。已补入最新四方向追踪文档、本总账、r37 分析器与 JSON，不存在未校验的 r36 结果文件。 |
| r37 量化证据 | 新增 572 行只读分析器 `analyze_e44_r37_restore_churn.py`，生成 16860 行 JSON；三轮逻辑 restore/repeat tokens 为 r34 `38435776/36065088` (`93.8321%`)、r35 `38195072/35785472` (`93.6913%`)、r36 `33019904/29424128` (`89.1103%`)。该比例是基于相同 `(TP rank, runtime radix node id, tokens)` 重读的保守下界。 |
| r37 placement 结论 | r34/r35/r36 全部 96 sessions×24 turns 的 session 节点切换都为 0；分布依次为 `45/51`、`51/45`、`45/51`，偏斜方向会反转。r35 可归因重复全部来自同 session，cross-session=0；turn 2 已重复 `82.23%`，turn 4 后通常 `97%–99%`。 |
| r37 裁决 | 这是 round-barrier 下 GPU L1 容量小于活跃 session 工作集造成的同 session 必要重载，每次 restore 均被请求消费。“保护刚恢复 pages”只会转移驱逐，静态 router 均衡也无依据。方向 2 不实现策略补丁、不发流，直接转入方向 3。 |
| r38 有效设计 | Python 公共接口、PyO3、external client 和 owner wire 增加同一 `consume_prefix_len` 概念；默认仍消费全部 `transferable_len`，显式短前缀必须在活跃可传输范围内且不切开 atomic group。TP 只保留第一次 handle；common=0 取消，common>0 直接 Transfer。 |
| r38 tail 生命周期 | OwnerRpc 在原 `ExternalBatchGetTransfer` handler 内截断 `keys/items`、drop tail，只完成消费前缀。InlineLocal 只构造前缀 holders，tail holding IDs 无等待进入现有 1ms/1024 项 external holder-ACK 合批队列；没有用一条新同步 Cancel RTT 替换旧第二 Start。 |
| r38 SGLang 边界 | 实验源从 sealed r35 SHA256=`895951ad...70c27` 派生，明确不包含 r36 cap；当前 SHA256=`8d1b497f...236a5da`，相对 r35 `+32/-116`。删除 Cancel→第二 Start、第二轮 TP all-reduce 及其错误分支，保留 common=0、Mamba 和 atomic-group 门禁。 |
| r38 本地验证 | build target `/mnt/nvme0/mjq_build/push_sglang_fluxon_target` 在 `/dev/nvme0n1p3`。`cargo check -p fluxon_kv --lib`、`cargo check -p fluxon_pyo3 --lib`、3 组定向测试和全量 `cargo test -p fluxon_kv --lib`=`184 passed, 0 failed` 通过；r35/r38 validators、Python compile、fmt check、diff check 通过。首次定向 binary 因 closed SDK `LD_LIBRARY_PATH` 指错目录而 rc=127，改指 `closed_sdk/lib` 后通过，没有代码断言失败。 |
| r38 attempt1 release/部署门禁 | 初版 NVMe staging=`/mnt/nvme0/mjq_build/fluxon_e44_r38_get_prefix_reuse_20260720`；unified wheel SHA256=`a1b94706...1344e`，PyO3=`3e5b9d41...37ac2`。底层 release、三端安装和当时的 hash 门禁通过，但没有覆盖 SGLang `HiCacheFluxon` adapter 调用签名，故 attempt1 未验收设计；该缺口随后由 adapter 隔离源、真实调用 smoke 和新 hash 门禁补齐。 |
| r38 attempt1 | 固定负载 rc=0、`2304/2304/0`，QPS=`3.954037`，TTFT p50/p90/p99=`3.75184/5.97531/11.48989s`，L1/L2/L3=`0/0/0`。初始 Get Start=`4296`、retry Start=`0`、Cancel=`4296`；4222 次候选在 adapter 报 `unexpected keyword argument 'consume_prefix_len'`，实际 Transfer/ready/DMA=`0/0/0`。该轮是集成失败，不是性能结果。 |
| r38 attempt1 网络 | 正式窗=`1784543057.9503927–1784543640.6435392`；三端各 1164 个有效 HCA interval、sample error=0。CPU TX avg/p99/peak=`49.810/312.250/374.610 Gbps`，峰值仅为双 HCA 800Gbps 的 46.8%；CPU TX 与两 GPU RX 总字节只差 `53856B`。这些是 write/backing 流量，不能冒充成功 load-back。 |
| r38 attempt1 归档 | `artifacts/e44_r38_get_prefix_reuse_attempt1_failed_20260720/` 共 126 个文件、约 294 MiB；125 个非 manifest 文件全部进入 `SHA256SUMS` 并校验通过。已包含 workload、三机日志/request metrics/HCA、Greptime DB、分析 JSON、attempt1 旧 adapter/runtime、配置、release manifest 和清场证据。 |
| 当前性能方向 | r53 已证明 allocator 下沉不是主瓶颈。下一轮先做 observation-only 的精确 lease 生命周期，再只把 GDR 开放给 queue-head `K` 个近期可运行请求；远期请求先落 DRAM。该门禁通过前保持 288 slots，不扩大静态 staging、不做 partial split。系统级更高价值方向是用 Fluxon local/remote bytes、未命中 compute tokens 和 staging pressure 修正两节点路由偏斜。 |
| r38 `ready_wait` 口径纠正 | 4128 条成功 load-back 中，`total/ready_wait/H2D restore/eviction/free_group` 均值为 `1195.444/884.177/223.589/51.527/46.137ms`。但 `ready_wait` 从 request observation 创建一直量到 `check_prefetch_progress()` 发布 ready；当前 `_FluxonHostlessPrefetchOperation.is_finished()` 恒为 `True`，Get 后台 singleflight/RDMA 在 Get Start 后已异步启动。因此这 `884.177ms` 包含 scheduler 暂未回来消费的重叠驻留，不能再直接称为“等网络数据”或将其与其他阶段简单相加。 |
| r39 observation 实现 | owner 的 Get shared state 只新增单调 `terminal_at`；每个 handle 在消费前短锁取样 Local/Starting/Started/Finishing/Revoking/Ready/Failed，记录 handle age、ready-before-consume 时长和真实 `finish_wait`。后台批次记录 BatchGetStart、RDMA wall/sum/max/bytes、cleanup、install、BatchGetDone、publish 和 total。没有改 wire、Get 选择、传输、Done、并发或缓存策略。 |
| r39 分析/编排量 | 相对 sealed r38 artifact：新增 analyzer/build wrapper/install wrapper/master YAML/deploy=`412/6/7/28/152` 行；variant/build-base/guard 三个既有文件为 `+14/-0`、`+15/-1`、`+7/-5`，合计 8 文件 `+641/-6`。这些实验配置/工具行数不与 Fluxon core 净 diff相加冒充一个 Git 变更集。 |
| r39 本地门禁 | NVMe target 已确认位于 `/dev/nvme0n1p3`；`git diff --check`、`cargo fmt --all -- --check`、`cargo check -p fluxon_kv --lib`、`cargo check -p fluxon_pyo3 --lib` 通过。新 snapshot 定向测试 `1 passed`、external Get 模块 `13 passed`、全量库测试 `185 passed / 0 failed`；首次定向二进制因未设 closed SDK `LD_LIBRARY_PATH` 以 rc=127 退出，补上 `fluxon_release/closed_sdk/lib` 后确认真实执行通过。分析器 Python compile/self-test、release manifest 与 shell/variant 固定参数门禁均通过。 |
| r39 release/部署 | NVMe release=`/mnt/nvme0/mjq_build/fluxon_e44_r39_get_ready_observe_20260720`；unified wheel SHA256=`27c8fbfd...d1038`，PyO3 SHA256=`759333b3...29421f`，closed SDK 与 ABI3 cp310/cp311/cp312 校验通过。新 node0=`32656/10.233.114.139`、node1=`30245/10.233.114.138`、CPU=`30729/10.233.125.121` 三端部署与启动回读均通过。 |
| r39 正式结果 | 原固定 S96×T24、2304 请求、c24、Get32、tier1 5%、end-depth288、metadata-only 128/128/256 GiB；`2304/2304/0`，QPS=`10.605922`，TTFT p50/p90/p99=`1.5733/2.8023/4.2740s`，E2E=`1.9837/3.7842/4.9560s`，L1/L2/L3=`2.43450/0/73.16877%`、总命中=`75.60327%`。新 GPU/NIC 环境不等价，QPS 不登记为 r39 代码收益。 |
| r39 Get-ready 裁决 | 4336 条成功 load-back 的 total/ready_wait/H2D/eviction/free-group/Get Transfer=`952.460/691.585/177.061/43.794/39.283/10.794ms`。owner 1117527 个消费 KV 中 1060832 个（`94.93%`）消费前已终态；3969 handles 中 3712 个全部终态，真正 finish_wait 均值仅 `4.803ms`，终态后平均驻留 `447.602ms`。主等待在 scheduler/prefill 消费队列，不在 RDMA/Get。 |
| r39 scheduler 证据 | 正式窗 node0/node1 queue 最大=`17/10`，pending tokens 最大=`373121/255702`，多次 token usage 接近 `0.93`。这些是排队证据，但尚未区分 GPU prefill compute 饱和、H2D/compute 串行或 scheduler 策略；不能把 447ms 全当作可消除的 Fluxon 时间。 |
| r39 网络边界 | CPU 双 HCA TX avg/active/p99/peak=`142.516/183.535/377.098/413.336Gbps`，未持续打满 800Gbps。两个 GPU pod 暴露相同 HCA LID，正式窗各自 RX 均为 `3866506883324B`，且 90.5% 同 sequence counter vector 完全相同；证明共享一组物理 HCA counter，两侧值不得相加，也使 r34/r38 性能对比失去环境等价性。 |
| r39 容量/远端闭环 | direct-delete requests=`2252`，victim attempts/completed/retryable=`864005/864004/1`；唯一 Get-activity busy 已进入 retry，owner handoff=committed、selected/retry/debt/in-progress 最终为 0。Remote Put targets/transfers/published=`80001/80001/80001`，active/failed/replay=0；CPU retained=`55341/261131599872B`。驱逐 token `97.868%` 已 backed，新写回仅 `2.132%`。 |
| r39 正确性剩余项 | node1 在一次 direct-delete Get-activity busy 后，一个 Get leader 报 `prepared local-reserve Get target cannot replace a live replica`。最终 workload、consume misses/errors 与所有临时态闭合，但仍需专项回归。人工停栈后的 owner 析构 panic、master KeyboardInterrupt unwrap、CPU close 未消费 Result 和 Ctrl-C traceback 仍未修。 |
| r39 当前运行状态 | 已按 router/SGLang → 三位 owner → master/control → HCA observer 完整停栈。正式窗结束后自动出现的 inference PGID `17238/16044` 已精确终止；再次延时 20 秒复核三机 session/process/实验端口=0、burner/watchdog/inference=0、四卡 `0 MiB/0%`、compute PID=0。未恢复 burner。 |
| r39 归档闭环 | `artifacts/e44_r39_get_ready_observe_enddepth288_netobs_passed_20260721/` 最终 152 个文件、约 215 MiB；151 个非 manifest 文件全部进入 `SHA256SUMS` 并校验通过。包含 results、三机日志/request metrics、三端 HCA、Greptime DB、四份 derived 对账、实际 config/runtime、release manifest、README 与 CLEARANCE。 |
| 当前真正问题 | node0 比 node1 多承担 `36.7%` 的 prefill-compute tokens，owner-local 比例却只有 `36.68%`；其 scheduler queue mean=`1.274s`、staging insufficient=`562`。每 TP 288 slots 又被 selected p50=`281.5` 页的请求过早占住并平均持有 `1.325s`，而真实 Get transfer 仅几十毫秒。问题是有效负载/locality 偏斜叠加非 JIT staging lease，不是 freelist 或持续 RDMA 带宽饱和。 |
| 已排除的主因 | 网卡未持续饱和；Get32→64 变差；扩大 tier1 变差；DMA descriptor cap 严重变差；session 没有跨节点 churn；r38 删除重复 Get Start 没有性能提升；r48 正确打通 GPU-direct 但覆盖率 1.68% 同样没有性能提升。当前不能继续围绕 RDMA 带宽或控制 RTT 盲调。 |
| 下一步 | 当前保持停机并等待用户指令。若继续：P0 补 plan-ready/reserve/RDMA-terminal/consume/release 与 queue position；P1 单变量 queue-head `K` gate；P2 若 P1 无效，做 Fluxon locality/remote-cost aware routing；P3 仅在 P1 有效后再评估 partial remote GDR。master active-plan bookkeeping、shutdown lifecycle 等 correctness TODO 不与性能变量混跑。 |
| r38 adapter 修复量 | 相对已封存 attempt1 配置，9 个实现/门禁/实验文件合计 `+248/-7`：build `+13/-0`、deploy `+17/-3`、variant `+2/-0`、GPU launcher `+1/-1`、validator `+61/-1`、adapter 行为 diff `+11/-2`、adapter real-call smoke 65 行、96×2 runner 35 行、r38 GPU 干扰硬门禁 43 行。Fluxon Rust/Python core 未变；adapter 是 3343 行隔离全量源，`+11/-2` 只表示相对旧部署 adapter 的行为差。 |
| r38 adapter release | NVMe target/rootfs/staging 均确认位于 `/dev/nvme0n1p3`，剩余空间约 462 GiB。重建成功，wheel=`66566ba1...d0b1c`、PyO3=`3e5b9d41...37ac2`、adapter=`b2d34b0f...afb27e`；closed SDK、ABI3 cp310/cp311/cp312 import 和新增 release manifest 全通过。新旧 wheel 各 79 个 entry 的解压内容 SHA256 完全一致，文件级 hash 变化仅来自 ZIP 容器元数据。后续三端部署见下一行。 |
| r38 adapter 部署 | 三端 release/symlink/wheel=`66566ba1...d0b1c`、PyO3=`3e5b9d41...37ac2` 和隔离 venv import 均独立回读通过；两 GPU active adapter=`b2d34b0f...afb27e`、radix=`8d1b497f...236a5da`。两端 installed-module real-call smoke 均通过显式 prefix、默认 None、keyword-only 三条契约。部署后未启动服务，四卡仍为 `0 MiB/0%`，burner/watchdog/inference 为 0。 |
| r38 real-transfer smoke | 固定 workload 的 96 sessions×2 turns 子集 rc=0、`192/192/0`。两节点 adapter Transfer=`90+76=166`，`load_back_consumed/positive-ready/DMA operations` 均为 `166/166/166`；TypeError、`retry_count>0`、fatal、interference 均为 0。L1/L2/L3=`4.8593/0/37.5958%`，证明真实回读成功。smoke 未产生 TP 长度 mismatch（reuse marker=0），因此不验收 common-prefix 去重，也不把 QPS=`6.6391` 当性能结果。 |
| r38 attempt2 结果 | 原固定 S96×T24、2304 请求、c24 workload rc=0、`2304/2304/0`。QPS=`9.056842`，TTFT p50/p90/p99=`1.851503/3.172765/9.434473s`，E2E=`2.317365/4.136392/11.364824s`；L1/L2/L3=`3.40653/0/69.47993%`，总命中=`72.88646%`。相对 r34 QPS `-1.513%`、L3 `-1.90138pp`，不能登记为性能提升。 |
| r38 attempt2 控制面 | 两侧 Get Start/Transfer/Cancel=`4262/4134/128`，严格满足 `Transfer+Cancel=Start`；394 次 TP mismatch 复用了第一 handle，retry Start 与 `retry_count>0` 均为 0。相同流量下这 394 次旧 Cancel→second Start 被确定性消除。adapter TypeError=0，ready/prefetch/DMA 均为 `4134`；`load_back_consumed=4128`。余 6 次都有 Transfer、ready、prefetch、init-load 和 DMA 完成，只是后续残余尝试覆盖了 request-level 终态；表面 `8134852608B` 不是已证明的浪费传输。 |
| r38 attempt2 网络/观测 | 正式窗 `1784548825.718–1784549080.111`，每节点 508 个 interval、sample error=0。CPU 双 HCA TX avg/active-avg/p99/peak=`106.204/150.700/372.515/409.027Gbps`；CPU TX 与两 GPU RX 总字节仅差 `16704B`。Greptime inference/phase/HCA 行数=`1864/817/10268`。 |
| r38 attempt2 容量/远端闭环 | direct-delete requests=`570+1575=2145`，victims/completed/retryable=`777925/777925/0`；handoff=committed node0/node1=`177663/600262`，selection/retry/debt 最终归零。CPU retained=`55341/261131599872B`。master replica targets=`101904`，owner transfers/published=`101904/101904`，active/failed/terminal replay 均为 0。 |
| r38 smoke 归档 | `artifacts/e44_r38_adapter_real_transfer_smoke_passed_20260720/` 共 98 个文件、约 143 MiB；97 个非 manifest 文件全部进入 `SHA256SUMS` 并校验通过。包含结果、三机日志、request metrics、Greptime DB、运行配置/release 关键快照及清场证据。 |
| r38 attempt2 归档 | `artifacts/e44_r38_get_prefix_reuse_attempt2_passed_20260720/` 最终 135 个文件、约 202 MiB；134 个非 manifest 文件全部进入 `SHA256SUMS` 并校验通过。包含正式结果、三机日志/request metrics/HCA/Greptime、release/config 快照、三份 derived 对账、README 与清场证据。 |
| 当前运行状态 | r53 workload、三端 HCA observer 和全栈均已停止；control/etcd/Greptime 残留也已清理。32656/30245 managed burner 已恢复，四卡均约 `1395 MiB/100%`；`inference_like_compute.py`、SGLang/Fluxon 推理进程为 0。没有启动新的性能补丁。 |
| shutdown lifecycle | 正式窗口内 runtime panic=0。20:09 人工停栈后仍复现两个 GPU owner 的 `MemoryInfo::drop` late-spawn panic、master KeyboardInterrupt unwrap、CPU close 未消费 `Result<ok>` 和 SGLang/router Ctrl-C traceback；它们不污染本轮性能数据，但继续列为独立 correctness/lifecycle TODO。 |
| r30 当前实现 | 只改 External holder release ACK。最后一个 `ExternalMemHolder` Drop 同步做 liveness 检查并无等待入队，不再逐 holder spawn task/RPC；队列项不复制 key，只保留 `external_client_id/owner_generation/holder_id`。单 worker 用 1ms merge window，按 client+generation 去重分组，每个 wire batch 最多 1024 项；owner 一次校验 generation、逐项移除 holding、一次返回 released/missing 汇总。owner generation 已变化视为旧 holding 终态完成。 |
| r29 ACK 规模证据 | node0/node1 Get transfer plan=`2046/2140`，返回页=`721098/688103`；合计 `4186` plans / `1409201` holders，当前逐页 Drop 理论触发约 140.9 万次本机 IPC RPC，平均 `336.65` holder/plan。owner handler 只用 `(external_client_id, holder_id)` 查找，单项请求中的 key 是冗余 wire 字段。 |
| r29 TP 重试证据 | 两侧共 `5510` Start、`1324` Cancel、`4186` Transfer；其中约 `1300` 次 Cancel 与 `1300` 次重复 Start 来自 TP common-prefix 收敛。该项已登记为 r30 之后的独立修改，不混入 ACK 合批轮。 |
| r30 当前验证状态 | NVMe target 已确认位于 `/dev/nvme0n1p3`。`cargo check -p fluxon_kv --lib` 通过；ACK 定向测试 `4/4`；全量 `cargo test -p fluxon_kv --lib`=`180 passed, 0 failed`。隔离 release 与三端部署哈希门禁通过。首次三机运行 early no-go，没有合法 QPS；r28/r29 结果仍不覆盖当前代码。 |
| r30 release | NVMe staging=`/mnt/nvme0/mjq_build/fluxon_e44_r30_external_ack_batch_20260719`；wheel SHA256=`28716b4ceeedb26036826d06ddb1d6c59d28a829ffcdce205b9eebcc5507e40c`，PyO3 SHA256=`e3a6e6f89455b759b9654bd25c822a6837f1e34aae646a9a1e5212575afe778b`。三端隔离 venv/release 安装、import 和哈希门禁均通过。 |
| r30 attempt1 ACK 实证 | 正常退出的三个 TP rank 合计 `enqueued=rpc_items=released=521993`、`rpc_batches=1243`，平均 `419.95 items/RPC`，即 RPC 数约下降 `420×`；missing、generation mismatch、RPC failure、enqueue failure 全为 0，max batch=`1024`。第四个 node0 rank 随 scheduler 硬退出，没有最终 Snapshot，不能计入完整闭合。 |
| r30 attempt1 故障 | 约完成 `1560/2304` 后，node0 TP1 对同一 33-key Put 出现 12 次 conflict recheck、3 次 retry exhausted，随后 prefill OOM、scheduler exception、31001 退出；workload 被人工终止且没有 after/summary，故不得登记 QPS/命中。故障时 owner `pending_slots=0`、free slots=`363`，refill timeout/P2P 608 为 0，不支持容量闭环卡死。 |
| r30 attempt1 判断 | r28/r29 同负载的 conflict/retry exhausted/OOM 都为 0；本次形态与 r17 重复 write-back 竞争相似。ACK 与 Put 没有直接共享状态，但合批可能改变运行时序；当前既不能认定代码回归，也不能按普通性能波动放行，必须用不改行为参数的隔离 r30b 复跑裁决。 |
| r30b 隔离编排 | 新增 variant=`tier1_independent_005_netobs_ack_batch_retry`、run id=`e44_r30b_external_ack_batch_netobs_retry` 和独立 master log path。它与 r30 复用相同 release/venv/PyO3/Get32/replica JSON；两个 master YAML 删除 `log_dir` 后无 diff。bash、YAML 与变量对齐门禁通过，未修改 Fluxon 核心代码。 |
| r30b 正式裁决 | r30b 约半程再次在 node0 复现：同一 42-key Put 共 16 次 conflict recheck、4 次 retry exhausted，随后 prefill OOM、scheduler exception、31001 退出；workload rc=`130`，无合法 QPS。故障前 owner `pending_slots=0`、free slots=`426`，refill timeout/P2P 608=0。两个独立 run 同形失败，当前 ACK 合批版本不得进入性能基线。 |
| r30b ACK 实证 | 两个正常退出 TP rank 合计 `enqueued=rpc_items=released=325367`、`rpc_batches=812`，平均 `400.70 items/RPC`；missing、generation mismatch、RPC failure、enqueue failure 为 0，max batch=`1024`。另两个 rank 无终态 Snapshot，不能代表完整验收。 |
| r30b 清场 | workload 已中止，router、两套 SGLang、三位 owner、master/control 和三端 HCA observer 均停止；三机无 r30b session/process。node0/node1 managed burner watchdog 已恢复，四卡延时复核均为 `1395 MiB / 100%`。三端 release symlink 保持 r30。 |
| r30b 根因 | node0 `node=853` 的 TP1 generation 已于 14:35:59 备份 101 页，split 后 14:36:17 重写其中 42 页；TP0/TP1 后缀分别为 `_0_2/_1_2`，不是同 key 互撞。冲突 TP1 key 直到 14:36:51 才因 `master rejected stale source identity` 回滚 source-selection fence，约 34 秒，远超 SGLang 10ms 重试。旧 reserve 错把该可等待 fence 映射成即时 `KeyBeingWritten`。node0 失败后 node1 又出现 48 次 recheck/12 次耗尽并同形 OOM。 |
| 当前 source-fence 修复 | 每个 source-selection/reclaim generation 建立 `watch` completion。幂等 local-first Put 在 per-key 短锁内只订阅；先释放本请求已拿到的部分 batch guards，再等待 rollback/Abort/Finalize/direct-delete 终态并重新核对完整 `atomic_batch`。取消一个 receiver 不影响 source 或其他 waiter；非幂等调用仍即时冲突。没有 actor、轮询、全局 FIFO或容量 victim 语义变化。 |
| 当前本地门禁 | NVMe target 位于 `/dev/nvme0n1p3`。rollback/finalize、非 join、清 fence 后新 leader、双 live waiter 与单 waiter 取消定向用例=`1 passed, 179 filtered out`；全量 `cargo test -p fluxon_kv --lib`=`180 passed, 0 failed`（197.00s）；`cargo check`、fmt check、`git diff --check` 均通过。r30/r30b release 不包含该修复，历史实验不覆盖当前代码。 |
| r33 本地门禁 | NVMe target=`/mnt/nvme0/mjq_build/push_sglang_fluxon_target`，位于 `/dev/nvme0n1p3`。`cargo check` 通过；activity 聚合、direct-delete mixed result、source-selection fence 三组定向测试各 `1/1`；全量 `cargo test -p fluxon_kv --lib`=`181 passed, 0 failed`（196.34s）；最终 fmt check 与 `git diff --check` 通过。首次定向启动因未设置 closed SDK `LD_LIBRARY_PATH` 在测试入口前 rc=127，补入 r31 NVMe SDK 后通过，不计代码测试失败。 |
| r33 release | NVMe staging=`/mnt/nvme0/mjq_build/fluxon_e44_r33_busy_activity_observe_20260720`，约 1.4 GiB；三机 release=`/storage/mjq/sglang_fluxon/releases/fluxon_e44_r33_busy_activity_observe_20260720`。wheel SHA256=`548b956c877e9d7a35fe9ad815714b0eab1848f50ecde4b52090943a4e471208`，PyO3 SHA256=`d998fb2a7699a8b44d21b059785c16175359ea5ea120a71352fa6bb80224b5de`。三端 release/closed SDK/import/symlink 与观测 symbol 门禁通过；两 GPU metadata-only patch 哈希通过。 |
| r33 部署 | attempt1 在 node0 安装前因部署脚本 SSH 外层双引号漏转义 JSON grep pattern 静默 rc=1；release 内容逐项通过且 symlink 仍为 r31。修正两处 pattern 转义后从头幂等部署成功；node0/node1 Python 3.10 与 CPU Python 3.12 均从独立 r33 venv import。失败属于部署门禁脚本，不是 release/runtime 失败。 |
| r33 启动门禁 | 两侧 managed burner/watchdog 已按 `--no-restart` 与精确 PID 双门禁停止，四卡启动前 `0 MiB/0%`。三端 HCA observer、etcd、Greptime/schema、master、两个 GPU owner/SGLang、CPU owner和 router 全部 ready；两侧 232/232 grants、128 GiB owner、metadata-only `materialized_pages=1`、Get32、end-depth 288、peer_count=2、HTTP 200；CPU 256 GiB/transfer-ready；master tier1 0.05 和新增 activity runtime 日志均实证。正式 workload 随后启动，但正确性失败。 |
| r33 编排 | 新增 build/install/deploy=`136/74/103` 行、master YAML=`28` 行，variant 新增 10 行，累计 5 文件 `+351/-0`。r33 master YAML 相对 r32 删除 `log_dir` 后结构相等；variant 保持 end-depth 288、Get32、tier1 5%，只换 r33 venv/PyO3/run id。全部 shell、replica JSON、YAML 等价和固定 hash/symbol 门禁通过。 |
| r33 正式结果 | 失败，无合法 QPS/TTFT/命中率。router POST started/completed=`703/683`，最后正式响应在 `01:49:16 UTC`；workload 在 rc/requests/after/summary 前人工中止。node1 出现 14 次 source-fence wait、0 次 resume、6 条 P2P 608；router 对 node1 health timeout 4 次；无 prefill OOM/scheduler exception。 |
| r33 根因闭合 | master replica targets=`63200`；两个 owner transfers/published=`34687/34687 + 28513/28513 = 63200` 且 active/failed=0，但 master 稳定残留 13 个 replica activity。`replica_done_terminal_replays=13` 与泄漏 lease 精确相等。旧 completion 只按 `(key, put_id)`，会把同 KV generation 的旧 append 终态错误重放给后来新建的 append reservation，使新 reservation/activity 无人完成。 |
| r33 direct-delete | 共 698 批、victims/completed/retryable=`213974/213104/870`；870 项全部归因为 replica Busy。最终两个 owner source-evict completed/retryable=`153600/195 + 59504/610`，与总数一致；master `active_keys=replica_keys=inflight_replicas=13`，Put/Get/reclaim 均为 0。 |
| r33 Greptime/HCA | active 窗 `1784512095.470–1784512156.999` 的 CPU 双 HCA TX avg/p99/peak=`121.980/425.948/492.946 Gbps`；node0/node1 RX avg=`89.060/32.854 Gbps`。stall 窗 `1784512157–1784512323.900` 几乎全低于 0.1 Gbps。Tokio global queue 四角色峰值均 0，active 窗 max-worker 峰值 master/node0/node1/CPU=`9.60/5.25/3.24/0.14%`，排除持续带宽或 runtime 排队饱和。 |
| r33 归档与清场 | artifact=`artifacts/e44_r33_busy_activity_observe_attempt1_failed_20260720/`，约 66 MiB、105 个原始文件，现已补 README/CLEARANCE、HCA full/active/stall、Greptime summary/SQL 和时间戳根因文档。三机实验栈、observer、端口已停止；两侧 managed burner 恢复，四卡约 `1395 MiB/100%`。 |
| r34 修复实现 | master 为每次 replica append 分配单调 `operation_id`；Start/batch Start 返回该 ID，owner 统一 remote-Put leader 在 Done/Revoke 原样带回；master completion cache 改为 `(key, put_id, operation_id)`，Start/Done/Revoke 用 per-generation 异步短锁线性化。相同 operation 可重放，旧 operation 不能完成后续 reservation。不同 key 继续并发，无 actor/FIFO；单 KV capacity 路径不变。 |
| r34 核心补丁 | 相对 r33 为 4 文件 `+168/-33`：`client_kv_api/put.rs +36/-16`、`master_kv_router/mod.rs +42/-1`、`master_kv_router/msg_pack.rs +11/-0`、`master_kv_router/put.rs +79/-16`。 |
| r34 本地门禁 | NVMe target 位于 `/dev/nvme0n1p3`。新增 operation-scoped terminal 回归测试 `1 passed`；全量 `cargo test -p fluxon_kv --lib`=`182 passed, 0 failed`（195.06s）；`cargo check`、fmt、`git diff --check` 通过。首次异步测试因 Tokio 名称冲突编译失败后改为同步 cache 测试；一次错误 `--exact` 匹配 0 项后已用正确名称执行 1 项通过，均如实记录。 |
| r34 编排 | 新增 build/install/deploy=`145/75/106` 行、master YAML=`29` 行，variant 新增 11 行，累计 5 文件 `+366/-0`。r34/r33 master YAML 去掉 `log_dir` 后结构相等；variant 保持 Get32、tier1 5%、end-depth 288，只换 run/release/venv identity。build 额外固化 master `msg_pack.rs` 与 `put.rs` 源码快照。shell/YAML/JSON 门禁通过，wheel/PyO3 真实哈希已回填。 |
| r34 release | NVMe staging=`/mnt/nvme0/mjq_build/fluxon_e44_r34_replica_operation_identity_20260720`，约 1.4 GiB，位于 `/dev/nvme0n1p3`。统一 wheel SHA256=`68971f37af71f09e2a3720fadd3b1358935e064e41d9da086abaa5333b23369c`，PyO3 SHA256=`d6bed7449ce6b5bad0c7d1514e9022065736a51dde94f5b4fb58f998e8d9f7d3`。cp310/cp311/cp312 ABI3 import、closed SDK、全部 release 哈希与新增 operation-id 源码 symbol 门禁通过；现已部署三端。 |
| r34 部署 | 三端 release=`/storage/mjq/sglang_fluxon/releases/fluxon_e44_r34_replica_operation_identity_20260720`；node0/node1 Python 3.10 和 CPU Python 3.12 独立 venv import、wheel/PyO3/closed runtime、source symbol、release symlink 全部通过。两 GPU metadata-only patch SHA256=`482a276e...1c878`。GPU 共享 venv 串行安装，无部署竞态；后续正式验收已完成。 |
| r34 启动门禁 | burner 管理状态首次串节点：第一轮只停掉 node1，node0 旧 `/public/zgf` burner 和两侧 watchdog 仍在；未误放行。按完整命令行精确终止后延时复核四卡 `0 MiB/0%`、watchdog stopped。三端 HCA observer、control/Greptime/schema、master、两 GPU owner/SGLang、CPU owner、router 全 ready；128/128/256 GiB、232/232 grants、metadata-only `materialized_pages=1`、Get32、tier1 0.05、end-depth 288、peer_count=2、HTTP 200、正式前 fatal=0。 |
| r34 正式结果 | workload rc=`0`，`2304/2304`、error=0；QPS=`9.195981033`；TTFT p50/p90/p99=`1.783589/3.109419/9.585525s`，E2E=`2.266590/4.160731/11.477920s`；L1/L2/L3=`2.57259/0/71.38131%`，总命中=`73.95390%`。相对 r31 QPS=`+20.452%`、L3=`+10.46605pp`；相对 Mooncake QPS=`+39.727%`、L2+L3=`+3.37621pp`。 |
| r34 replica/容量闭环 | master targets=`95128`；node0/node1 transfers=published=`41451/41451 + 53677/53677 = 95128`，active/failed=0，terminal replay=0。direct-delete requests=`2330`、victims/completed/retryable=`859791/859791/0`；handoff=committed=`249230/249230` 与 `610561/610561`；两侧 selected/retry/debt/selected bytes/pending/in-progress 均归零。master 连续 activity Snapshot 全 0。CPU retained=`55341/261131599872 B`，deferred reclaim queued=completed=`10/10`。 |
| r34 正式错误门禁 | source-fence wait/resume、P2P 608、refill timeout、prefill OOM、scheduler exception、Put conflict retry exhausted 均为 0。退出后两 GPU owner 仍复现 module view 已销毁的析构 panic，master 仍有 KeyboardInterrupt unwrap；它们发生在正式结果和归零 Snapshot 之后，保留为 lifecycle P1。 |
| r34 HCA/Greptime | 正式窗 `1784515980.279–1784516230.824`：CPU 双 HCA TX avg/p99/peak=`121.076/414.030/482.982 Gbps`；CPU TX=`3784596977584 B`、两 GPU RX=`3784596982192 B`，只差 `4608 B`。node1/node0 RX=`2.534×`。Tokio global queue 四角色峰值均 0，max-worker 峰值 master/node0/node1/CPU=`8.835/5.756/7.329/0.191%`。三端 HCA 原始 samples=`2122/2120/2120`、导入行=`12724`、error=0。 |
| r34 load-back/控制面 | Get Start/Cancel/Transfer=`4718/466/4252`，Start-Transfer 恰为 466；Start mean/p90/p99=`25.875/50.749/70.976ms`。`load_back produced no prefix tokens`=`226+308=534`；逐条复核后全部为 `not_ready/read_pages=0/<1ms`，不是已完成 534 次数据传输。TP0/TP1 成对折算为 267 个调度事件，metadata 宣称的 host-hit 上限为 `4439872 tokens`，但当前缺 rid 生命周期，不能冒充真实可恢复量。成功 load-back 的 `evict_ms` mean node0/node1=`47.189/53.313ms`，约 33.25% rank 次数超过 50ms。下一轮先补 request 生命周期与 eviction breakdown；handle trim 单独测试。 |
| r34 归档与清场 | artifact=`artifacts/e44_r34_replica_operation_identity_enddepth288_netobs_passed_20260720/`，最终 125 个文件、约 195 MiB；results、三机日志、request metrics、HCA、原始 Greptime DB、配置、release manifest、README/CLEARANCE 和全目录 SHA256 已固化，124 项清单校验通过。三机 r34 栈/observer/端口全 0。 |
| r34 idle GPU 状态 | 停栈后四卡先为 `0 MiB/0%`。恢复 managed burner 时，外部 `/storage/mjq/computing/inference_like_compute.py` 已在两节点四卡各占约 `8483 MiB/100%`；`gpu_burner.sh` 正确拒绝覆盖非 burner workload，watchdog 为 stopped。未擅自终止外部任务；它退出后仍需执行 `start 0,1` 恢复 managed 状态。 |
| r31 隔离 release 与部署 | NVMe staging=`/mnt/nvme0/mjq_build/fluxon_e44_r31_source_fence_wait_20260719`；wheel SHA256=`81a66946b4babb28194d4bb089ca5b15dd805cbdec06198ff1afe4033101efb8`，PyO3 SHA256=`17e627190f7a84aff2df3aa824afa7708c5d9f0d3adbbe68296f21c113730109`。release、closed SDK、ABI3 cp310/cp311/cp312 import、metadata-only patch、完整源码清单和三个修复源文件快照校验通过。node0/node1/CPU 三端安装、远端哈希、closed runtime、import、metadata-only patch 和 symlink 门禁均通过；本 release 已完成 r31 正式流量验收。 |
| r31 编排 | 新增 build/install/master/deploy=`124/74/28/93` 行，并在 variant 表新增 11 行，合计 5 文件 `+330/-0`。r30b/r31 master YAML 删除 `log_dir` 后无 diff；Get concurrency 均为 32，replica JSON byte-for-byte 相同。shell/YAML、固定 wheel/PyO3 hash 和 release source symbol 门禁通过。 |
| r31 启动门禁 | 两个 GPU owner 必须共同形成 RDMA peer 集合后才发布 `shared.json`。本轮先顺序启动 node0，120s 门禁因缺 node1 peer 超时；node0 owner 本身已 transfer-ready 且 232/232 grants 健康。启动 node1 后两侧自动发布 shared.json，node1 完整启动、node0 用原生 `SGLANG_ONLY` 续启，未伪造文件或重建 owner。正式请求前两侧 Get32、depth160、metadata-only `materialized_pages=1`、128 GiB/232 grants、CPU 256 GiB/peer_count=2、HTTP health 和 fatal=0 全部通过。 |
| r31 正式结果 | workload rc=`0`，`2304/2304`、error=0；QPS=`7.634560288`；TTFT p50/p90/p99=`2.027694/5.017834/9.843239s`，E2E=`2.627600/6.563515/11.334799s`；L1/L2/L3=`4.28660/0/60.91526%`，总命中=`65.20186%`，HostKV used after=`0/0`。conflict recheck/exhausted、refill timeout、P2P 608、prefill OOM 和 scheduler exception 全为 0。 |
| r31 source-fence 实证 | node0 在真实流量中记录 1 次 `external local-first Put resumed after owner source/reclaim fence`，`items=45`、`wait_us=3761813`。该请求等待约 3.76s 后重检并成功完成；旧实现会在 SGLang 总计 10ms 重试内耗尽。本地竞态用例与这次三机触发共同覆盖修复语义。 |
| r31 ACK 实证 | 四个 TP rank shutdown Snapshot 合计 `enqueued=rpc_items=released=1,073,020`、`rpc_batches=2,960`，平均 `362.51 items/RPC`；enqueue/RPC failure、missing、generation mismatch 全为 0，max batch=`1024`。相对逐 holder RPC，控制面请求数约下降 `362.5×`。 |
| r31 容量闭环 | direct-delete `1598` 批、victims/completed/retryable=`494566/494537/29`，min/max/avg=`1/911/309.49`。node0/node1 handoff=committed=`157867/336670`；两侧 selected、retry entries、selection debt、selected bytes、pending slots与 remote-Put active/failed 终态均为 0。CPU retained=`55341 entries/261131599872 B`。 |
| r31 Greptime/HCA | workload points/phase fields/write errors=`2204/817/0`；三节点各 691 个有效 HCA samples，双 HCA 导入 `4146` 行、sample error=0。正式窗 Greptime CPU 双 HCA TX avg/p99/peak=`52.335/268.776/317.543 Gbps`，1s peak=`236.898 Gbps`；302 个 1s 桶中 97 个低于 0.1 Gbps，仅 5 个达到 200 Gbps，仍未饱和。CPU TX=`1973064247756 B`，两 GPU RX=`1973064264748 B`，只差 `16992 B`。node1/node0 RX=`2.085×`，较 r28 的 `4.62×` 收敛但仍不对称。Greptime `fluxon_logs` 也查询到 1 条 source-fence resume。 |
| r31 性能判断 | 相对 r28，同观测口径 QPS=`-2.67697%`、L3=`+0.41570pp`、总命中=`+0.26013pp`。r31 封为当前代码正确性基线，但 QPS 不是新最优；L2+L3 距 Mooncake `68.0051%` 仍差 `7.08984pp`。 |
| r31 Get 控制面复核 | 两节点四个 TP rank 合计 Get Start/Cancel/Transfer=`4882/756/4126`，Start-Transfer 恰为 `756`。Get Start mean/p90/p99=`16.414/36.391/61.699ms`，Cancel mean=`0.461ms`。common-prefix handle trim 可删除 756 次 Cancel 与 756 次重复 Start，但主要影响控制 RTT/CPU，不会补齐缺失缓存内容。r29 的 `5510/1324/4186` 只保留为旧轮证据。 |
| 当前性能 P0 | 暂停性能调参。先构建/部署 r34，用 r33 完全相同的 end-depth 288 + Get32 + tier1 5% 配置复跑，证明 operation identity 修复能让 activity/direct-delete/source fence 全部闭合；只有正确性门禁通过才比较 QPS 和命中率。 |
| r32 配置实现 | run id=`e44_r32_enddepth288_netobs`。variant 相对 r31 artifact `+11/-0`；新增 28 行 master YAML 和 51 行 config-only 三端部署脚本，总计 3 个实验文件 `+90/-0`。r32 复用 r31 GPU/CPU venv 与 PyO3 SHA256=`17e62719...a109`，Get concurrency 实测为 32；replica JSON 解析通过，两个 master YAML 删除 `log_dir` 后无 diff；shell `bash -n` 通过。没有修改核心源码或构建 release。 |
| r32 attempt1 结果 | workload 于 `00:30:58 UTC` 启动，node0/node1 SGLang 正式 HTTP 200 日志计数=`320/329`，router 完整响应=`647` 后停止推进；runner 在写 rc、requests、after 和 summary 前被人工中止。因此本轮无合法 QPS、TTFT 或命中率，不能把 partial 计数当性能结果。 |
| r32 57-key 闭环 | node0 从 `00:31:49.970 UTC` 起同一批 57 个 exact source-fenced victim 持续 Busy，selected/retry=`57/57`、selected bytes=`268959744`；master 最终记录 73 个 Busy batch response、4104 个 Busy item outcome。free slots=`395–429`、pending slots=`0`，refill timeout/OOM/scheduler exception=`0`。`00:32:22` 后两个 TP rank 同时出现 `msg_id=4022`，累计 12 条 deadline warning、6 次 99-key `P2P(code=608)` write-back failure。 |
| r32 根因边界 | direct-delete 的稳定 Busy 最可能来自 master key activity 未释放；现有日志未聚合 `puts/gets/replicas/reclaim_installed`，也未记录 `WaitForLocalAccess` 开始事件，故具体 activity 类型和两个 99-key Put 与 57 victims 的 key 交集尚未证明。`replica_done_terminal_replays=57` 只记为关联信号，不写成 lease 泄漏根因。稳定阶段约每 5 秒一个整批 RPC，Greptime global queue=0，因此 retry RPC 数量不是控制面排队饱和。 |
| r32 Greptime/HCA | 故障前 master/node0/node1 最忙 Tokio worker 峰值=`5.755/3.754/7.560%`，global queue 均为 0；stall 后全部低于 `0.23%`。前 59 秒 CPU 双 HCA TX avg/p99/peak=`112.447/378.266/410.137 Gbps`、总计 `822.31 GB`；r31 相同前 59 秒为 `44.566/257.317/290.312 Gbps`、`325.92 GB`，r32 bytes=`2.52×`。这只是更强早期 CPU 恢复信号，缺 token 终态，不能登记为命中收益。`00:32:22–00:34:32` 三端各仅约 2880 B 变化，排除持续链路饱和。 |
| r32 下一门禁 | P0 先补 batch 级 Busy 原因、master activity/inflight gauge、owner local-access wait 开始/结束。若确认只是暂时 Busy，候选修复是逐 victim 撤销 owner source-selection fence、恢复当前 generation 到 Moka并释放 selected debt；真实缺口继续 pop 其它单 KV。不得展开 TP/`atomic_batch` 兄弟或引入整组驱逐。 |
| r33 观测实现 | master direct-delete 每批新增 activity Busy item 分类、对应 inflight lease 合计和 under-fence delete Busy 数；30 秒 runtime 新增 active/Put/Get/replica/reclaim key 与 inflight Put/Get/replica 总量。owner 在 `WaitForLocalAccess` 阻塞开始时记录单个 fenced key/batch size，并为每个 Busy response batch 只记录首个 victim key/detail。wire response、逐 victim 结果、fence、retry 和回收行为均未改变。新增 activity 聚合单测并扩展 direct-delete mixed-result 单测；本地门禁已全部通过。 |
| P0 性能门禁 | r34 下一次要求 workload rc=0、`2304/2304`，master activity、owner selected/retry/debt/pending/in-progress 全归零，且无 P2P 608/OOM。通过后才应用性能门槛：L2+L3 至少 `61.91526%`（相对 r31 `+1pp`），QPS 不低于 `7.48187`（退化不超过 2%）。 |
| r32 文档与 artifact | 新建 207 行时间戳分析文档；实验 README/CLEARANCE/Greptime SQL/Greptime summary 共 135 行。失败 artifact 最终共 106 个文件、约 68 MiB，包含 partial results、三端日志、两侧 request metrics、三份 HCA、Greptime DB、精确配置、r31 release manifest、最新版计划/总账/失败分析和全目录 `SHA256SUMS`；清单 105 项全部校验通过。34 份 JSON/JSONL、8 份 shell、三份同步文档一致性和 `Fluxon git diff --check` 均通过。Fluxon/SGLang 核心源码净 diff 仍为 `+1815/-862`，本轮没有代码修改或新 release。 |
| r31 退出与清场 | 正式结果与 ACK Snapshot 落盘后，两侧 GPU owner 都在 `Shutdown Complete` 后复现 `MemoryInfo::drop -> ClientKvApiView::spawn` 析构 panic；CPU close 仍有未消费 `Result<ok>`；node0 SGLang application shutdown complete 后需第二次 Ctrl-C。这些不污染正式窗口，但继续列为 shutdown P1。三机 session/实验进程/端口最终均为 0；两侧 managed burner/watchdog 已恢复，四卡约 `1395 MiB/100%`。 |
| r31 artifact | `artifacts/e44_r31_source_fence_wait_netobs_passed_20260719/` 已固化 results、Greptime DB、三机日志、request metrics、HCA 原始/派生数据、精确配置和 release manifest，共 119 个文件、约 201 MiB；README、CLEARANCE 和 SHA256SUMS 已补齐，`sha256sum -c` 全部通过。 |
| r30b artifact | `artifacts/e44_r30b_external_ack_batch_attempt2_failed_20260719/` 已补 README、CLEARANCE 和全目录 SHA256SUMS；校验全部通过。三节点原始 HCA 各 511 行，只作失败窗口证据，不登记正式带宽/QPS。 |
| tier1 独立容量修复 | 已删除容量 reconcile 和 reservation adjust 两处 `min(tier1_base, ring_b_effective)`。ring-B 仍按 `0.95 × node_space - generation reservations` 计算；tier1 只按 `tier1_ratio × node_space` 计算。r21 运行时两侧均实证 `writeback_tier1_capacity_bytes=103079215104 B`（96 GiB），ring-B 仍为 `6012954214 B`，修复语义与容量门禁通过。 |
| source-unavailable 观测 | r21 node0/node1 的 `source_unavailable=2282/2087`，三项原因为 `fenced=0/0`、`missing=2282/2087`、`version_mismatch=0/0`，互斥原因之和精确等于总数。本轮失败全部是 source 已经消失，不是 fence 或换代。 |
| r20 编排改动量 | 当前共 5 个文件、`+270/-0`：新增 build/install/deploy 三个 shell（108/74/52 行）和 28 行 master config，并在既有 variant 表增加 8 行 r20 case。所有 shell `bash -n`、replica JSON 与 YAML 解析均通过；r19/r20 master config 去掉隔离 `log_dir` 后结构完全相等。该统计独立于 `Fluxon` 核心 8 文件 `+861/-754`。 |
| r17 实验编排 | 已新增独立的 r17 build/install 脚本和 master 配置，并在 variant 表增加 `single_kv_baseline`；仅更换 release、venv、run id 与日志隔离路径，r16 baseline 参数不变。这些工作区编排改动不计入上面的 `Fluxon` Git 核心代码 diff。 |
| r17 release | 历史失败运行使用的 NVMe staging 和三机共享路径为 `/storage/mjq/sglang_fluxon/releases/fluxon_e44_r17_single_kv_pop_metadata_20260718`；wheel SHA256=`39df79dadb5199689f84d06f09aceefb42b4c77dbfea40b30ef879947497e6db`，PyO3 SHA256=`c62e58344e592f0cb2043545a3936faed3ef3fc314992aa9d6a58ab54c4d3e2f`。该 release **不包含 00:47 当前修复代码**。 |
| r18 release | 当前修复已打成全新隔离 release：NVMe staging=`/mnt/nvme0/mjq_build/fluxon_e44_r18_direct_delete_singleflight_metadata_20260719`，三机路径=`/storage/mjq/sglang_fluxon/releases/fluxon_e44_r18_direct_delete_singleflight_metadata_20260719`，wheel SHA256=`cecd818b3c398156b15a6086ba3990ccfd459dad90c2880f0cb4e650983b0c68`，PyO3 SHA256=`7e307f646296d37634cc3339cc0dd156c0667e4f9c2d7c66c594da50f05780c6`，metadata-only patch SHA256=`482a276e701c4fdd3c44654ff6c8e2403ee59fdb671513db61c62532a9b1c878`。manylinux rootfs、Cargo target 和 staging 均位于 `/dev/nvme0n1p3`。 |
| r18 部署 | node0/node1/CPU 的远端 wheel 哈希、隔离 venv 安装、PyO3/closed-runtime 哈希和 import probe 均通过；三个 `fluxon_release` 已指向 r18。两 GPU 节点 metadata-only `memory_pool_host.py` SHA256 均为 `482a276e...1c878`。 |
| r18 启动前门禁 | master、两 GPU owner/TP2 SGLang、CPU owner、router 均 ready；GPU0/GPU1/CPU=`128/128/256 GiB`；两侧 slot class=`4,718,592`、grants=`232/232`、reserved slots=`26,216`；两侧 HostKV `materialized_pages=1`；fatal 关键词均为 0。node0/node1 burner managed state 已取消，watchdog=0、burner process=0；SGLang 启动前 GPU 为 `0 MiB / 0%`。 |
| r18 正式结果 | workload rc=0，`2304/2304`、error=0、QPS=`7.381347613`；TTFT p50/p90=`2.053/4.705s`，E2E p50/p90/p99=`2.733/6.030/11.605s`；L1/L2/L3=`3.86/0.00/58.90%`，总命中=`62.77%`，两侧 HostKV used after=`0/0`。 |
| r18 容量验收 | direct-delete 869 批、188066 victims，其中 868 批 `victims>1`；completed=188062、retryable busy=4、max batch=776、avg batch=216.42。290.36s 内约 `647.69 victims/s`，是 r17 约 37/s 的 `17.5x`；两侧 owner Prepare/Commit/Finalize 均为 `0/0/0`。drain 后 selected/retry/debt/selected bytes 全归零。 |
| r18 fatal/冲突 | 两侧 `refill timeout`、P2P 608、prefill OOM、scheduler exception、`local_fast_put_start conflict retry exhausted` 均为 0。Put follower 复用日志实际触发数为 0，因此真实 workload 只证明 r17 冲突没有复现；singleflight 行为仍由本地成功/失败定向测试覆盖。 |
| r18 清场与证据 | workload 后已停止 router、两套 SGLang、GPU/CPU owners、master/control。01:49 HKT 延时复核：三机相关 tmux/进程/实验端口计数均为 0；两侧各两张 GPU 均=`0 MiB / 0%`、compute process=0，burner watchdog 仍为 stopped。约 53 MiB 结果、before/after metrics、请求、网络样本及全栈日志已固化到 `artifacts/e44_r18_direct_delete_singleflight_metadata_baseline_passed_20260719/`。 |
| r19 正式结果 | workload rc=0，`2304/2304`、error=0、QPS=`7.945039507`；TTFT p50/p90/p99=`2.030589/3.805540/9.779753s`，E2E p50/p90/p99=`2.681179/4.635025/11.493626s`；L1/L2/L3=`4.4392/0/61.4698%`，总命中=`65.9090%`，HostKV used after=`0/0`。相对 r18 为 `+7.64% QPS/+2.5673pp L2+L3`。 |
| r19 tier1 实际语义 | 配置 ratio=`0.75` 的名义上限为每侧 96 GiB，但运行时代码取 `min(0.75×node_space, ring-B effective capacity)`；本轮 `130567005798-124554051584=6012954214 bytes`，所以实际只有 5.60 GiB。两侧终态均为 `1274 entries/6011486208 bytes`。 |
| r19 tier1 活动 | node0 trigger/accepted/failed=`36147/21751/11772`，node1=`53069/28515/20766`；failed 与两侧 `source holder is unavailable or version-mismatched` 计数完全一致。 |
| r19 容量验收 | direct-delete 1857 批、579691 victims，全部为多 victim batch，min/max/avg=`2/911/312.17`；node0/node1 completed=`141488/438203`，retryable busy/in-progress 终态为 0。两侧 handles/flights、prepared/pending、selected/retry/debt/selected bytes 全归零，grants=`232/232`。fatal、refill timeout、P2P 608、OOM、scheduler exception、Put conflict 均为 0。 |
| r19 新暴露边界 | node0/node1 有 `701/1250` 次 `Put append operation not found for completion`；未造成业务失败，但证明 proactive+tier1 真实压力下仍有重复/过期 completion 竞争。`load_back produced no prefix tokens` 为 `210/690`。 |
| r19 清场与证据 | 正式结果后已停止 router、两套 SGLang、GPU/CPU owners、master/control；11:21 HKT 延时复核三机相关 tmux/进程/端口为 0，两侧各两张 GPU=`0 MiB/0%`、compute process=0，burner/watchdog process=0，status 均为“GPU 压测已停止”。约 68 MiB、35 个文件已固化到 `artifacts/e44_r19_direct_delete_singleflight_tier1_075_passed_20260719/`，含 README、results、全栈日志、rc=0、配置与 release manifest。 |
| r17 部署 | GPU0、GPU1、CPU 的 wheel 安装、import probe、release/closed-runtime/metadata-only patch 哈希门禁均通过；三个 `fluxon_release` 均指向 r17 隔离 release。 |
| r17 启动前门禁 | 2026-07-18 23:05 HKT：master、三位 owner、两套 TP2 SGLang、router 全部 ready；GPU0/GPU1 owner=`128/128 GiB`、CPU owner=`256 GiB`；两侧 HostKV `materialized_pages=1`、used tokens=`0`；admission=`prefix_depth_ratio/160`；burner/watchdog=`0`。 |
| r17 首轮结果 | **early no-go，无合法 QPS/命中率**。node1 在 23:08:04–23:08:05 HKT 先出现 8 次 `local_fast_put_start conflict retry exhausted`，随后 TP0/TP1 各发生一次 `Prefill out of memory` 并触发 scheduler exception/SGLang 退出。run dir 只有 before-metrics，没有 after-metrics/汇总结果。 |
| r17 第一因果断点 | 单 KV 语义落地后，owner→master 虽然一次 RPC 可提交多个 victims，但 master reclaim actor 又把它们拆成 singleton 并逐个 `await`。每个无冲突成功项在 Commit 后还固定 sleep 25ms 才 Finalize/处理下一个，因此物理 slot 回收被限速为约 36–37 KV/s。node1 的 5654 次 Prepare/Commit/Finalize 全部是 `items=1`；5654 个 Commit 从 15:05:46.901 持续到 15:08:25.502，约 158.6 秒。 |
| r17 slot 压力证据 | node1 在 15:07:51 为 `free_slots=115`、`pending_slots=564`，同时已有 590 个精确 source-fenced victims 在回收队列中。这里不是虚假 projected credit；fence 已正确安装，但下游 singleton 串行事务吞吐太低。 |
| r17 Put 冲突机制 | external local-first Put 先为整批逐 key 增加 `local_puts` fence，之后才进入 FIFO 等待物理 slot。后来的相同 key 不 join leader，而是立即返回 `KeyBeingWritten`；SGLang 只重试 `1+2+3+4=10ms`。本轮 leader 的 69-page `local_fast_put_start` 实测等待 `332.463ms`，所以 follower 必然先耗尽重试。 |
| publication 排除结论 | owner 日志没有 `owner local publish retained`、PutDone unresolved 或 publish queue full；SGLang 走 ExternalClient 路径，冲突发生在 slot claim 之前，不能把 64 个 native owner publication worker 当作本轮第一断点。publication 仍缺少逐 key 延迟指标，但不是现有证据指向的主因。 |
| r17 驱逐闭环观测 | node1 owner 最终 `size_evictions=handoff=committed=5654`，`source_eviction_selected=0`、`selection_debt_bytes=0`、`source_eviction_selected_bytes=0`、retry entries=`0`；这说明本轮单 KV victim 流水线最终收敛，但不能抵消 SGLang OOM 门禁失败。 |
| r17 fatal 边界 | node0/node1 定向日志中 `refill timeout=0`、`P2P(code=608)=0`；node1 根 cgroup `oom_kill=0`。这次是 SGLang prefill 分配器主动抛错，不是内核 OOM killer，也不是 r14 的 refill-timeout/P2P-608 原故障链复现。 |
| r17 清场 | 23:16 HKT 已停止 workload、node0/node1 SGLang/owner、master/control/router 和 CPU owner；23:24 HKT 延时复核仍为 r17 tmux/进程/实验端口全空、两个 GPU 节点均 `0 MiB / 0%`、burner watchdog 停止且无自动恢复。 |
| r17 证据固化 | node0/node1 SGLang/owner、master/router、CPU owner、两侧 request metrics、workload before-metrics，以及 3 个精确运行 SGLang 源码快照已复制到 Ceph 独立 artifacts 目录。当前为 17 个证据文件、16.519 MiB，另有 1 个 README；README 内含完整 SHA256 清单。 |
| 历史本地验证 | 修复前单 KV 版本曾通过 `170 passed`，r18 direct-delete 提交曾通过 `173 passed`；这些历史结果均不覆盖当前未提交 owner remote-Put 代码。 |
| 当前修复实现 | owner pressure 的一次 `evict_some` 用显式 Begin/End 保持为一个传输批次，不再按 2ms/128 victims 切片；master handler 逐项安装 master fence、二次核对并直接删除精确 source route，处理完整批后返回一个结果向量；local 对 `Completed` 项同步完成 Prepare/Commit/Finalize 并释放 slot，不再进入 master singleton reclaim actor；同一完整 `atomic_batch` 的同 key Put follower 等 leader 终态，成功复用、失败才重新竞选，等待前释放本请求已拿到的部分 fence 以避免交叉 batch 死锁。 |
| 当前本地验证 | NVMe target=`/mnt/nvme0/mjq_build/push_sglang_fluxon_target`，位于 `/dev/nvme0n1p3`。当前修复通过 tier1 定向回归 `1/1`、`cargo check -p fluxon_kv --lib`、全量 `cargo test -p fluxon_kv --lib`=`176 passed, 0 failed`（196.21s）、最终 fmt check 与 `git diff --check`；这些门禁现已由 r21 三机同负载结果补齐。 |
| 正确性历史基线 | v5/r9：`2304/2304`、fatal=`0`、QPS=`5.609336`。这是封版参考，不覆盖当前单 KV 驱逐代码。 |
| 历史公平参考 | r18 metadata-only、`128/128/256 GiB`、无 burner：`2304/2304`、fatal=0、QPS=`7.381347613`、L2+L3=`58.9025%`。它覆盖 `aafac11` 单 KV direct-delete 代码，但不覆盖当前 remote-Put 重构。 |
| 当前代码验收 | r34 已通过本地 `182/182`、三端独立 release/哈希/import 和正式 `2304/2304` 正确性门禁；当前代码基线为 r34。r31 降为历史正确性参考，r33 保留为失败根因证据。 |
| 历史最佳已测策略 | r34 Get32、tier1 5%、end-depth 288：QPS=`9.195981033`、L2+L3=`71.38131%`，现为历史已测最优。旧 r19 `7.945039507/61.4698%` 仅保留为旧代码策略参考。 |
| 旧 release 策略参考 | r22 5% observability-off 为 `7.650137995 QPS/59.28476% L2+L3`；r28 同策略 observability-on 为 `7.844556385/60.49956%`。二者都不覆盖当前代码，只能作为下一单变量实验的历史对照。 |
| 对齐目标 | Mooncake QPS=`6.581393`、L2+L3=`68.0051%`。r34 QPS 高 `39.727%`、L2+L3 高 `3.37621pp`；“先追命中”门槛已完成，下一阶段转入不损命中的 load-back 冗余优化。 |
| r27 后核心定位 | r22→r23→r27 的 remote transfers=`90839→79538→61901`、last-route removed=`33486→41462→53102`、CPU retained=`243.20→241.26→196.13 GiB`。大 tier1 窗口推迟真实写回，但更核心的问题是 CPU 内容选择：`prefix_depth_ratio/160` 只看原子节点 start，会完整接受 300–413 页的 root child。 |
| 固定请求带宽复核 | 按每 TP rank 每 token `73,728 B` 从 `HiCache prefetch submitted` 推算，r22/r23/r27 逻辑 prefetch payload=`4649.42/4619.96/4564.49 GiB`，全程平均=`15.44/14.82/14.44 GiB/s`。r22 仅 230/301.17 个等价 1s 桶有新 prefetch，r27 为 233/316.06；说明需求爆发，但这些是逻辑提交 payload，不是 HCA wire 实测。 |
| 通信控制面 | Get 已用 `BatchGetStart/BatchGetDone`，direct-delete 已是整批单请求/单响应。remote Put 仍每 KV 独立 `PutAppendStart -> transfer -> PutAppendDone`；r22/r23/r27 约为 `195966/171055/129562` 次 Start+Done RPC。批量 API 已存在，但 `ensure_remote_put()` 未使用，master batch handler 也仍逐项 `await`。 |
| r28 Greptime 覆盖 | workload 写入 `2148` 个时序点和 `816` 个 phase fields，write errors=`0`；三节点 `mlx5_4/mlx5_6` 的 500ms 物理计数共 `9384` 行、采样错误=`0`，已按原时间戳写入 `fluxon_hca_port_timeseries`。内建 `kv_op_end_*` 与 `kv_peer_network_bytes_total` 有数据，但后者只有 owner↔external `local_ipc`；现有源码没有调用 `ReplaceSelfRdmaSnapshot` 的生产者，因此没有原生 `rdma_*` 数据，本轮物理 RDMA 结论来自导入 Greptime 的 HCA 表。 |
| r28 正式结果 | run id=`e44_r28_r22_netobs_replay`；`2304/2304`、error/fatal=0、QPS=`7.844556385`；TTFT p50/p90/p99=`2.054959/3.871597/9.654660s`，E2E=`2.670252/4.702510/11.395490s`；L1/L2/L3=`4.44217/0/60.49956%`，总命中=`64.94173%`。它只相对 r22 打开 observability，属于网络诊断轮，不替代 observability-off r22 的严格性能排名。 |
| r28 HCA 结论 | Greptime 正式窗 587 个 500ms 桶内，CPU 双 HCA TX 平均/p99/峰值=`51.130/262.550/324.775 Gbps`，仅为 800 Gbps 的 `6.39%/32.82%/40.60%`；1s 桶最大仅 `214.907 Gbps`，294 个桶中 87 个低于 0.1 Gbps。两卡平均 TX=`25.570/25.560 Gbps`，无 steering 偏载；CPU `PortXmitWait` 折算每卡约 `0.074%/0.026%` 窗口，未见 fabric 拥塞。 |
| r28 数据闭合 | node0+node1 物理 RX=`333873088664+1542296749536=1876169838200 B`，与 CPU TX=`1876169820920 B` 只差 `17280 B`。GPU→CPU 物理=`428245653464 B`；实际 remote Put transfers=`36995+52744=89739`，逻辑 payload=`423441727488 B`，物理仅高 `1.1345%`。相对 Greptime external Put `388774232064 B/82392 slots` 多出的主体是额外 `7347` 次真实 write-back，不应误写成 10% wire overhead。 |
| r28 节点不对称 | node0/node1 L3 cached tokens=`15590720/15335936`，几乎相等；但 CPU→node1/node0 物理读取为 `1542.30/333.87 GB`（`4.62x`），master Get Start 为 `380519/135419`（`2.81x`），direct-delete victims 为 `371755/93719`（`3.97x`）。node1 在 11:30 HKT 的 Greptime owner 日志两次出现 `finishing_flights=512`，恰好顶到 Get finish `4 batches × 128 keys` 的窗口，而 node0 未出现同量级积压。 |
| r28 CPU/执行器排除 | Greptime 正式窗内 process CPU 平均最高为 node1 owner `465.13%`（约 4.65 核）；Tokio overall busy 最大 `2.435%`、单 worker busy 最大 `5.419%`，global queue 只有 node0 一个样本为 1，其余均为 0。当前没有 master/owner CPU 或 Tokio 饱和证据。 |
| 当前剩余问题 | （1）Get common-prefix 在 r35 仍有 918 rank 次重复 Start；（2）r35 remote-Put failed=`498` 尚未按 outcome 归因；（3）Greptime 仍缺 native per-peer RDMA/operation breakdown；（4）shutdown panic/unwrap 与 master lock/leader 接管/multi-`atomic_batch` 专项覆盖未修。r36 descriptor cap 和静态 node 均衡已被证伪，不再列为待实现优化。 |
| 下一步门禁 | 发流前再次复核 burner/watchdog/inference PID=0、四卡只有预期 SGLang compute、observer 持续增长且 fatal=0；随后只运行固定 S96×T24、2304 请求、c24 workload。 |
| r29 授权边界 | 用户已明确要求“修改并测试”。r29 只允许把 Get 数据传输 `batch_concurrency=32→64`；run id、master log/HiCache namespace/HCA output 必须隔离。release、tier1 5%、depth160、metadata-only 128/128/256 GiB、S96×T24、请求 concurrency 24、observability 和三节点双 HCA 500ms 采样保持不变。不得顺带修改 end-depth、remote Put actor/singleflight、容量或 workload。 |
| r29 编排实现 | 新 variant=`tier1_independent_005_netobs_get64`、run id=`e44_r29_get_batch64_netobs`；variant 默认 Get 并发 32，仅 r29 覆盖为 64；GPU launcher 消费该字段；HCA manager 增加可选 run id 以隔离 session/output；新 master config 相对 r28 去掉 `log_dir` 后结构完全相等。5 个文件相对 r28 artifact 净改动=`+47/-5`。bash/YAML/JSON、r28=32/r29=64 和 NVMe tool-root 门禁均通过，三机部署和正式运行已完成。 |
| r29 正式结果 | workload rc=0、未超时，`2304/2304`、error=0；QPS=`7.615272617`；TTFT p50/p90/p99=`2.134034/4.062147/9.798854s`，E2E=`2.810293/4.874785/11.486272s`；L1/L2/L3=`4.41418/0/59.54021%`，总命中=`63.95438%`。相对 r28 QPS=`-2.9228%`、L3=`-0.95935pp`，正式窗口 refill timeout/P2P 608/OOM/panic/non-200 均为 0。 |
| r29 HCA/Greptime | 正式窗=`1784463817.437136–1784464119.987040`；CPU 双 HCA TX 平均/active-average/p99/峰值=`48.633/84.650/248.937/314.345 Gbps`，相对 r28 分别 `-4.88/-4.67/-5.18/-3.21%`。1s 桶为 303 个，91 个低于 0.1 Gbps。CPU TX=`1837149503908 B`，node0+node1 RX=`1837149521764 B`，只差 `17856 B`；HCA 导入 `5412` 行、sample error=0，workload Greptime points/phase fields/errors=`2212/817/0`。 |
| r29 决策 | Get 并发翻倍没有提高 active-average、p99 或总 wire bytes，QPS/延迟/命中也同时变差；原“32 个 Get 限制活跃带宽”的假设被本轮否定。node1 正式窗未再采到 `finishing_flights=512`，只短暂采到 `starting_flights=89`。64 不提升为默认值，不继续扫 48/更高并发。 |
| r29 退出边界 | 正式 workload 结束后清场，两侧 GPU owner 在打印 `Shutdown Complete` 后因 module view 已销毁而由 `MemoryInfo::drop` 再次 spawn，触发 destructor panic/abort；CPU owner 还有未消费 close `Result` 告警。它们发生在正式窗口之后，不改变 2304/2304，但证明 shutdown/cancel 生命周期仍需修复，不能写成全生命周期 fatal=0。 |
| r29 清场与证据 | 已按 router/SGLang → 三位 owner → master → control/Greptime 顺序停栈，三机 r29/control session 和匹配进程均为 0；两 GPU 节点 managed watchdog 已恢复，四卡均 100%。results、Greptime DB、三机日志、两侧 request metrics、原始 HCA、配置和 release manifest 共约 204 MiB，已固化到 `artifacts/e44_r29_get_batch64_netobs_completed_20260719/`。 |
| r19 启动前预审 | 10:45 HKT：三机无相关 tmux/进程；node0/node1 各两张 GPU=`0 MiB / 0%`、compute process=0，burner watchdog 均 stopped；三端 `fluxon_release` 均指向 r18，wheel SHA256=`cecd818b...c68`、PyO3 SHA256=`7e307f64...80c6`，两侧 metadata-only patch SHA256=`482a276e...1c878`。当前尚未修改配置或启动服务。 |
| r19 单变量配置 | 已新增并实跑 variant `direct_delete_singleflight_tier1_075`、r19 master config 和配置部署脚本。相对 r18 master config 的行为 diff 只有 `replica_writeback_tier1_capacity_ratio: 0.75`；另一差异仅为隔离 log 目录。r19 复用 r18 GPU/CPU venv、PyO3 哈希和相同的 `prefix_depth_ratio/160` admission JSON。 |
| r19 启动门禁 | 10:58 HKT：control/master、两套 GPU owner+TP2 SGLang、CPU owner、router 全部 ready；master 实际配置为 `Some(0.75)`；GPU0/GPU1 owner 均 `137438953472 bytes`、grants=`232/232`、slot size=`4718592`；CPU owner=`274877906944 bytes`、RDMA `peer_count=2`；两侧 HostKV `materialized_pages=1`，admission=`prefix_depth_ratio/160`；启动前 fatal=0，burner process/watchdog=0。随后正式 workload 已通过。 |
| 后续执行文档 | `20260719_101516_fluxon_kv_r18后续命中率优化执行计划.md` 已登记 r19 正式结果，并修正 tier1 运行时容量：0.75 对 128 GiB 的名义值是 96 GiB，但本轮被 effective-capacity clamp 裁剪为 5.60 GiB。 |
| 统一远端 Put 规划 | `20260719_121358_fluxon_kv_owner统一远端Put控制流实施规划.md` 已更新为验收快照：direct per-generation singleflight、无 actor、master per-operation 异步锁、r20 真实负载结果和剩余 P1 均已登记。 |
| r20 release | 三机隔离 release=`/storage/mjq/sglang_fluxon/releases/fluxon_e44_r20_owner_remote_put_singleflight_tier1_075_20260719`；wheel SHA256=`edc4175653f0c4fa31b0a4d9dfdb14dd403ca408a96c7189bd9a41275cd1a93e`，PyO3 SHA256=`98442cc4312cee2bc3b48715eccb6aa0545b99778997f98f4de4a3fec23746eb`，metadata patch=`482a276e...1c878`，source diff=`d7bf8f35...9e38`。 |
| r20 正式结果 | workload rc=0，`2304/2304`、error=0；QPS=`7.742272953`；TTFT p50/p90/p99=`2.086486/3.965337/9.885159s`，E2E=`2.680934/4.652207/11.676458s`；L1/L2/L3=`4.47799/0/60.51801%`，总命中=`64.99600%`，HostKV used after=`0/0`。 |
| r20 singleflight 验收 | node0/node1 followers=`742/1274`，约避免 `8.859375 GiB` 重复 payload；transfers=`37917/56879` 且全部 published；leaders 精确等于 published+already-satisfied；completion missing 三侧均为 0，master terminal replay=3，active/obsolete/failed 均为 0。 |
| r20 容量验收 | direct-delete `1724` 批、`536540/536540` victims，retryable=0，min/max/avg batch=`4/850/311.218`；两侧 handoff=committed=`139362/397178`；Get/remote-Put active、prepared/pending、selected/retry/debt/in-progress 全部归零，tier1 两侧均保留 `1274 entries/6011486208 B`。 |
| r20 清场与证据 | 14:47 HKT 延时复核三机相关 tmux、进程和实验端口均为 0。正式窗口内 burner 为 0；停栈后按实验规约恢复两侧 managed watchdog。约 68 MiB、43 个文件已固化到 `artifacts/e44_r20_owner_remote_put_singleflight_tier1_075_passed_20260719/`，含 README、CLEARANCE、results、全栈日志、配置和 release manifest。 |
| r21 release | NVMe staging=`/mnt/nvme0/mjq_build/fluxon_e44_r21_tier1_independent_075_20260719`、三机 release=`/storage/mjq/sglang_fluxon/releases/fluxon_e44_r21_tier1_independent_075_20260719`；unified wheel SHA256=`e4aeef91467f822a1c6eed85c47d2d1d2fb8c29657d6334ecdddd30f07c10468`，PyO3 SHA256=`ab733bf7b9b30b04bfb4e5dee3c4c81435d7251e4b6b62f7bfabfb7ef153e101`，metadata-only patch=`482a276e...1c878`，source diff=`69392a2c...2b5a6`。三端部署、import、closed-runtime 和哈希门禁均通过。 |
| r21 编排改动量 | 新增 build/install/deploy 三个 shell=`108/74/52` 行、master config=`28` 行，并在 variant 表新增 8 行；合计 5 个文件 `+270/-0`。所有 shell `bash -n`、YAML/replica JSON 解析通过；去除 `log_dir` 后 r20/r21 master 配置完全相等。 |
| r21 正式结果 | workload rc=0，`2304/2304`、error=0；QPS=`7.370114467`；TTFT p50/p90/p99=`2.061381/4.454487/9.878182s`，E2E=`2.720383/5.564537/11.841482s`；L1/L2/L3=`3.99133/0/58.10273%`，总命中=`62.09407%`，HostKV used after=`0/0`。相对 r20 为 `-4.8068% QPS/-2.4153pp L2+L3`。 |
| r21 tier1 归因 | tier1 triggered 从 r20 两侧合计 `98184` 降到 `8279`，remote transfers 从 `94796` 降到 `56120`；CPU 最终 retained 从 `55340/261126881280 B` 降到 `43408/204824641536 B`，少 `52.44 GiB`；`last_route_removed` 从 `34554/151.85 GiB` 升到 `55290/242.97 GiB`（`+60.01%`）。96 GiB 窗口延迟写回是负收益主因。 |
| r21 容量验收 | direct-delete `927` 批，victims/completed/retryable=`199874/199854/20`，min/max/avg=`1/911/215.614`；20 个 busy 项均重试完成。node0/node1 handoff=committed=`56499/143355`；Get/remote-Put active、prepared/pending、selected/retry/debt/in-progress 全部归零，grants=`232/232`。 |
| r21 清场与证据 | 16:17 HKT 复核三机 r21 tmux、进程和实验端口均为 0；两侧 managed watchdog 已恢复，四张 GPU 均只有约 1395 MiB/100% 的 burner。共 43 个文件、约 54 MiB 固化到 `artifacts/e44_r21_tier1_independent_075_passed_20260719/`。 |
| tier1 扫描编排改动量 | Fluxon 核心源码未变。当前新增 6 份 28 行 master config=`+168/-0`，既有 variant 表新增 6 个 8 行 case=`+48/-0`，实验编排最终净 diff 合计 7 文件 `+216/-0`；r27 是新增的 30% case，r24–r26 仍未运行。`bash -n`、三端部署哈希及 workload SHA256 均通过。 |
| r22 正式结果 | ratio=`0.05`，运行时两侧 tier1=`6871947673 B`（约 6.4 GiB）。workload rc=0，`2304/2304`、error/fatal=0；QPS=`7.650137995`；TTFT p50/p90/p99=`2.093514/4.170966/9.975130s`，E2E=`2.735980/4.818375/11.550333s`；L1/L2/L3=`4.56986/0/59.28476%`，总命中=`63.85463%`，HostKV used after=`0/0`。相对 r21 为 `+3.7994% QPS/+1.18203pp L2+L3`。 |
| r22 写回与容量闭环 | CPU retained=`55341/261131599872 B`（243.20 GiB），已恢复到 r20 水位；两侧 tier1 triggered/accepted/failed 合计=`93121/48559/43170`，remote transfers=`90839`，last-route removed=`33486/147.16 GiB`。direct-delete requests/victims/completed/retryable=`1536/433310/433309/1`；两侧 handoff=committed=`102447/330862`，active、pending、selected、retry entries、debt、selected bytes、in-progress 终态均为 0，completion missing=0。 |
| r22 清场与证据 | 16:58 HKT 已按 router/SGLang → owners → master/control 顺序停栈；三机实验进程、tmux 和端口为 0，两侧 managed burner/watchdog 已恢复。38 个文件、约 68 MiB 固化到 `artifacts/e44_r22_tier1_independent_005_passed_20260719/`。 |
| r23 正式结果 | ratio=`0.10`，两侧 tier1=`13743895347 B`（12.8 GiB）。workload rc=0，`2304/2304`、error/fatal=0；QPS=`7.393700330`；TTFT p50/p90/p99=`2.079607/4.535574/9.941472s`，E2E=`2.648580/5.629776/11.392305s`；L1/L2/L3=`3.81826/0/59.52394%`，总命中=`63.34220%`。相对 r22 为 `-3.3521% QPS/+0.23917pp L2+L3/-0.51243pp 总命中`。 |
| r23 写回与容量闭环 | CPU retained=`54901/259055419392 B`（241.26 GiB）；tier1 triggered/accepted/failed 合计=`74125/33231/38630`，remote transfers=`79538`。direct-delete requests/victims/completed/retryable=`1338/341848/341840/8`；两侧 handoff=committed=`102043/239797`，active、pending、selected、retry entries、debt、selected bytes、in-progress 全归零，completion missing=0。 |
| r23 清场与证据 | 17:22 HKT 三机完整停栈，实验 tmux/进程/端口为 0，两侧 managed burner/watchdog 已恢复。38 个文件、约 66 MiB 固化到 `artifacts/e44_r23_tier1_independent_010_passed_20260719/`。 |
| r23 扫描判定 | r23 ratio=0.10 的极小命中收益不足以抵消 QPS 下降，因此用户终止当时的更大窗口连续扫描；r19 仍是全历史性能最优。 |
| r27 配置门禁 | 新 run id=`e44_r27_tier1_independent_030`，ratio=`0.30`；相对 r21 master config 只有隔离 `log_dir` 和 ratio 两行差异。三端已部署相同 variant/config，仍指向 r21 release；workload SHA256=`f173859...aa71`。 |
| r27 正式结果 | workload rc=0，`2304/2304`、error/fatal=0；QPS=`7.289788870`；TTFT p50/p90/p99=`2.083927/5.170297/9.927198s`，E2E=`2.789714/7.048286/11.692579s`；L1/L2/L3=`4.01428/0/58.34688%`，总命中=`62.36116%`。相对 r23 为 `-1.4054% QPS/-1.17706pp L2+L3`，相对 r22 QPS `-4.7104%`。 |
| r27 写回与容量闭环 | 两侧 tier1=`41231686041 B`（38.4 GiB）；CPU retained=`44631/210595479552 B`（196.13 GiB）。tier1 triggered/accepted/failed=`40082/11993/27151`，remote transfers=`61901`。direct-delete requests/victims/completed/retryable=`1112/248189/248175/14`；handoff=committed=`75881/172294`，所有临时态归零，completion missing=0。 |
| r27 清场与证据 | 17:44 HKT 三机完整停栈，实验 tmux/进程/端口为 0，两侧 managed burner/watchdog 已恢复。38 个文件、约 62 MiB 固化到 `artifacts/e44_r27_tier1_independent_030_passed_20260719/`。 |
| r27 扫描判定 | r27 ratio=0.30 是明确负收益；tier1 三点中 r22 5% QPS 最好、r23 10% L2+L3 略高。r19 仍是全历史性能最优。 |
| r27 后分析文档 | `20260719_175605_fluxon_kv_r27后续优化多角度分析.md` 已从 290 行更新为 484 行；除容量、admission、turn 延迟、节点不对称、singleflight 和 load-back 外，新增固定 2,304 请求下的控制面/数据面、逻辑 payload、观测门禁和决策树。 |
| r28 复测边界 | run id=`e44_r28_r22_netobs_replay`；复用 r22 的 r21 release、tier1=`0.05`、`prefix_depth_ratio/160`、96×24/2304 请求、concurrency 24。相对 r22 服务行为配置只把 `disable_observability=true` 改为 `false`；因此它用于网络诊断，不冒充严格单变量性能复测。 |
| r28 观测编排 | 新增 10 个文件共 `+1066/-0`，variant 增加 `+10/-0`，合计最终净 `+1076/-0`：三节点双 HCA sampler/汇总/Greptime 导入、quoted-schema 建表、GPU/CPU observability-on launcher、同负载 runner 与部署脚本。工具使用 Ubuntu 22.04 `perfquery` SHA256=`42c32fd...cbbc58`，staging 位于 `/mnt/nvme0/`。静态门禁、三端部署和正式运行均已通过；Fluxon/SGLang 核心源码未改。 |
| r28 证据与清场 | 完整 results、三机日志、request metrics、三份原始 HCA、Greptime DB 与查询导出已固化到 `artifacts/e44_r28_r22_netobs_replay_passed_20260719/`，当前约 220 MiB。19:40 HKT 三机 r28/Greptime/observer 进程与 tmux 均为空；两侧 managed burner/watchdog 已恢复，四卡均约 1395 MiB/100%。 |
| 当前测试轮 | 最近正式轮仍是 r52 attempt2：correctness pass、performance no-go；历史性能基线仍是同批新 GPU 的无 GDR r39=`10.605922`。18:31 fixed-slab 代码只有本地门禁，不能写成 r53 或新性能结果。 |
| 当前运行状态复核 | 本轮没有连接或改变集群。最近可引用状态是 r52 attempt2 取证后全栈/observer 已停止、burner 已恢复；下一次集群测试仍必须重新独立确认 burner/watchdog 与 `inference_like_compute.py` 已停止、目标 PID/端口/GPU 只含预期进程，不能沿用旧清场结论。 |

维护规则：每次设计、代码、测试或三机结果变化后，先更新本 Snapshot；下方章节保留过程证据和
详细账目。历史实验必须继续标注其对应代码边界，不能自动继承为当前代码的验证结果。

### 0.1 2026-07-19 00:47 HKT：r17 P0 修复实现

本轮在 00:15 的 `+479/-1473` 修复前快照上继续修改，没有独立提交，因此当前只能精确给出
工作树相对 Git 基线的净 diff，不能把两个快照数值之差解释成实际键盘工作量。

- `client_kv_api/local_reserve_rebalance.rs`、`mod.rs`、`put.rs`：为一次 pressure pop 增加显式
  Begin/End 批次边界；取消 128 victims 传输切片；`Completed` 响应在 local 同步释放精确 slot。
- `master_kv_router/reclaim.rs`、`msg_pack.rs`：增加稳定的 batch victim epoch；master 在一个
  handler 内逐项 fence、复核、direct-delete，最后一次返回完整对齐的结果向量。
- `client_kv_api/mod.rs`、`external_api.rs`、`put.rs`：增加 per-key Put leader 终态订阅；同一完整
  `atomic_batch` 的 follower 复用成功结果，不申请 slot、不重复写 payload；leader 失败后才重选。
- 交叉 batch 等待前会先丢弃本请求已经取得的部分 leader guards，避免 A 持有 key1 等 key2、
  B 持有 key2 等 key1 的环路。
- multi-`atomic_batch` 请求暂不做跨组复用；它仍返回原 `KeyBeingWritten`，避免一个组完成就把其他
  未完成组误报为成功。

当前已通过的新增定向门禁：direct-delete 批内部分失败与幂等重放、local source 完成释放、Put
成功复用。当前尚未跑全量库测试，也尚未生成包含本轮代码的新 release。

### 0.2 2026-07-19 00:56 HKT：本地全量门禁完成

- 构建目录经 `findmnt` 确认为 `/dev/nvme0n1p3` 上的
  `/mnt/nvme0/mjq_build/push_sglang_fluxon_target`，没有向 Ceph `target/` 或 `/tmp` 回退；
- 全量 `cargo test -p fluxon_kv --lib`：`173 passed, 0 failed`，耗时 `194.95s`；
- 最终 `cargo check -p fluxon_kv --lib`、`cargo test -p fluxon_kv --lib --no-run`、
  `cargo fmt --all -- --check` 与 `git diff --check` 均通过；
- rustfmt 修正了 `client_kv_api/mod.rs` 一处纯缩进，无行为变化；
- 当前净 diff 更新为 `+1168/-1549`。这些本地结果覆盖 00:47 修复代码，但仍不能替代新 release
  的三机同负载验收。

### 0.3 2026-07-19 01:13 HKT：r18 隔离 release 构建完成

- 新 run id：`e44_r18_direct_delete_singleflight_metadata_baseline`；
- NVMe staging：`/mnt/nvme0/mjq_build/fluxon_e44_r18_direct_delete_singleflight_metadata_20260719`；
- 统一 wheel SHA256：`cecd818b3c398156b15a6086ba3990ccfd459dad90c2880f0cb4e650983b0c68`；
- PyO3 SHA256：`7e307f646296d37634cc3339cc0dd156c0667e4f9c2d7c66c594da50f05780c6`；
- metadata-only HostKV patch SHA256：`482a276e701c4fdd3c44654ff6c8e2403ee59fdb671513db61c62532a9b1c878`；
- 为遵守 NVMe 规约，打包 helper 增加 `FLUXON_PYPACK_ROOTFS` 参数，本轮 manylinux rootfs
  使用 `/mnt/nvme0/mjq_build/fluxon_pypack_rootfs`；Cargo target、rootfs 与 release staging 经
  `findmnt` 均落在 `/dev/nvme0n1p3`；
- release 内部 ABI3 cp310/cp311/cp312 import probe、closed SDK、vendor runtime、metadata patch、
  source manifest 和统一 wheel 哈希门禁全部通过；尚未部署到三机，不能登记性能结果。

### 0.4 2026-07-19 01:18 HKT：r18 三机部署完成

- `/storage` 并非三机共享目录，因此 deploy 脚本改为把 r18 release 明确复制到每个节点，再做远端
  wheel SHA256 校验；第一次尝试使用远端不存在的 `rsync` 在写入前退出，随后固定使用 `scp`；
- node0、node1、CPU 三端 wheel SHA256 均为 `cecd818b...c68`，PyO3 SHA256 均为
  `7e307f64...80c6`；三个隔离 venv 的 import probe 均指向 r18 自身路径；
- 两个 GPU 节点的 `/storage/zth` 是共享 venv 路径。第一次并行 pip 安装发生部署竞态，node1 在
  runtime 文件尚未落完时 import 失败；改为串行重装后 node0/node1 均复核通过。这是部署竞态，
  没有改代码或实验参数；
- 三个 `fluxon_release` 软链接均已切到 r18；两侧 SGLang metadata-only patch SHA256 继续为
  `482a276e...1c878`；当前尚未启动 master/owner/SGLang/router/workload。

### 0.5 2026-07-19 01:27 HKT：r18 启动前门禁通过

- 启动顺序：control → master → node0/node1 GPU owner+TP2 SGLang → 256 GiB CPU owner → router；
- 两侧 GPU owner 均为 `137438953472 bytes`，local reserve 均为 `232/232 grants`、
  `26216 reserved slots`、`slot_size=4718592`、`active class=1`；
- CPU owner segment=`274877906944 bytes`；两侧 metadata-only HostKV 均打印
  `materialized_pages=1`；node0/node1 SGLang 和 router health 均通过；
- 停 burner 时发现 node1 burner PID 与状态文件脱节，脚本把它误判为非 burner。根据完整命令行
  `.gpu_burn_script_...py --gpu 0/1` 精确终止后，两侧在 SGLang 启动前均为 GPU `0 MiB / 0%`，
  `Watchdog is stopped`，managed auto-reclaim 已取消；
- 启动前 `refill timeout`、`P2P(code=608)`、`Prefill out of memory`、scheduler exception、
  `local_fast_put_start conflict retry exhausted` 计数均为 0；尚未发 workload 请求。

### 0.6 2026-07-19 01:38 HKT：r18 三机同负载验收通过并清场

正式 workload 保持 r17 全部参数不变，结果：

- rc=0，Requests/Success/Error=`2304/2304/0`；QPS=`7.381347613`；
- TTFT p50/p90=`2.053462/4.704732s`；E2E p50/p90/p99=
  `2.733280/6.029544/11.605175s`；
- L1/L2/L3=`3.8628/0.0000/58.9025%`，总命中=`62.7652%`；两侧 metadata-only
  HostKV used after 都是 0；
- QPS 比 Mooncake 高 `12.15%`、比 r16 高 `6.19%`；L2+L3 比 r16 高 `6.39pp`，但仍比
  Mooncake 低 `9.10pp`。

容量路径验收：

- master 共完成 direct-delete 869 批、188066 victims，其中 868 批 `victims>1`；
  completed=188062、retryable busy=4，max/avg batch=`776/216.42`；
- 第一批到最后一批跨度 290.360089s，约 `647.69 victims/s`，相对 r17 约 37/s 提升约
  `17.5x`；
- node0/node1 owner 容量路径 Prepare/Commit/Finalize 均为 `0/0/0`；
- drain 后两侧 `source_eviction_selected=0`、retry entries=0、selection debt=0、selected bytes=0；
  master `source_evict_in_progress=0`；
- `refill timeout`、P2P 608、prefill OOM、scheduler exception、
  `local_fast_put_start conflict retry exhausted` 全为 0；
- 本轮 Put follower reuse 日志为 0，故 singleflight 没被真实 workload 主动触发；其成功复用和失败
  唤醒仍由本地定向测试覆盖，不能把“冲突没复现”写成“真实流量已触发复用”。

结果落盘后立即停止 router、两套 SGLang、GPU/CPU owners、master/control。三机相关 tmux、进程、
实验端口均为空；node0/node1 GPU=`0 MiB / 0%`，burner process/watchdog 均为 0。完整证据已固化到：

`experiment_configs/e44_local_slot_tier_20260716/artifacts/e44_r18_direct_delete_singleflight_metadata_baseline_passed_20260719/`

### 0.7 2026-07-19 01:49 HKT：文档同步、静态门禁与延时清场复核

- 将 `fluxon_kv_当前问题与后续优化计划_20260718.md` 和 E44 实验 README 的当前基线从 r16
  更新为 r18；r12–r17 只保留为历史归因，容量 P0 明确标记为已关闭；
- 当前优先级固定为 tier1 `0.75` 单变量 → `prefix_end_depth_ratio=288 + batch64`；聚合
  L2+L3 未达到 `68.0051%` 前不开始 load-back 优化；
- `/mnt/nvme0/mjq_build/push_sglang_fluxon_target` 经 `findmnt` 确认为
  `/dev/nvme0n1p3`；82 个 E44 shell 的 `bash -n`、`cargo fmt --all -- --check` 和 Fluxon
  `git diff --check` 均通过；本轮只改文档，Fluxon 核心代码净 diff 仍为 `+1168/-1549`；
- 01:49 HKT 通过三台节点重新查询：相关 tmux、进程、实验端口均为 0；node0/node1 各两张
  GPU 均为 `0 MiB / 0%`，compute process=0，`gpu_burner.sh status` 均为
  `Watchdog is stopped`，没有延时自动复活。

### 0.8 2026-07-19 10:15 HKT：r18 后续命中率实验执行分析

- 新增 `20260719_101516_fluxon_kv_r18后续命中率优化执行计划.md`；当前顺序仍为 tier1 `0.75`
  → end-depth 288 + inflight 64 → 命中达标后 load-back；
- 编排审计发现旧 `tier1_075`/`enddepth288` case 没有绑定 r18 venv/PyO3，且仍复用 r13/r14
  run ID 和配置。正式实验前必须从 r18 派生隔离 r19/r20 variant，不能直接运行旧 case；
- r19 只允许 master 增加 `replica_writeback_tier1_capacity_ratio: 0.75`；r20 必须从 r18
  独立派生，tier1 关闭，只切换 `prefix_end_depth_ratio` 预设、每批上限 288，并保持 inflight=64；
- 同步修正 E44 README 中 r18 variant 名：实际为 `direct_delete_singleflight_baseline`，不是
  `single_kv_baseline`；
- 本轮只新增/修正文档，没有修改 Fluxon 代码、配置或脚本，没有启动实验；核心代码净 diff 仍为
  `+1168/-1549`。

### 0.9 2026-07-19 10:24 HKT：解释 tier1 0.75 与 r18/r19 差异

- 根据当前代码确认，0.75 的分母是每个 source owner 的注册 `node_space_size`；tier1 Moka 仅保存
  metadata 并按 KV weight 限容，128 GiB owner 的名义上限约 96 GiB；
- tier1 条目因 Size 淘汰时才触发 master→source owner 的提前 replica enqueue，目标受
  remote-only placement 限制为 CPU owner；它不删除 GPU KV，也不新增物理容量；
- r18 的 tier1 字段为 `None`，该触发关闭；候选 r19 只把它改为 `Some(0.75)`，其他行为参数、
  binary、容量和 workload 全部固定；
- 新文档已增加逐项对照表、预期收益与重复副本/写回压力风险。本轮仍只改文档，未创建 r19 配置，
  未启动实验。

### 0.10 2026-07-19 10:47 HKT：r19 tier1 0.75 单变量配置派生

- `e44_v5_perf_variant_20260718.sh` 新增 8 行 r19 case，run ID 为
  `e44_r19_direct_delete_singleflight_tier1_075`，显式复用 r18 GPU/CPU venv 和 PyO3 哈希；
- 新增 28 行 `master_config_e44_r19_direct_delete_singleflight_tier1_075.yaml`。相对 r18 只有
  log 隔离路径和 `replica_writeback_tier1_capacity_ratio: 0.75` 两处 diff，后者是唯一行为变量；
- 新增 35 行 `deploy_e44_r19_tier1_075_config.sh`，只分发配置/启动脚本并校验三端仍指向 r18
  release，不复制或重装 wheel；
- 所有相关 shell `bash -n`、replica JSON `jq`、master YAML 解析均通过；尚未部署、启动或发请求；
- 本轮没有修改 Fluxon Rust 代码，核心代码净 diff 仍为 `+1168/-1549`。

### 0.11 2026-07-19 10:58 HKT：r19 启动门禁通过

- r19 配置已分发到三端，variant/config SHA256 分别为 `01c0baaa...a271`、
  `ba1f8360...9283`；三端展开出的 run ID、r18 venv/PyO3 与 depth160 admission 一致；
- control → master → 两侧 GPU owner/TP2 SGLang → CPU owner → router 按顺序启动并全部 ready；
  master 运行日志确认 `replica_writeback_tier1_capacity_ratio: Some(0.75)`；
- 两侧 owner=`128/128 GiB`、local reserve=`232/232 grants`，CPU owner=`256 GiB` 且
  transfer-rpc `peer_count=2`；两侧 metadata-only HostKV `materialized_pages=1`；
- `gpu_burner.sh stop 0,1` 默认会进入 managed-idle 并启动 watchdog，本轮立即改用
  `stop 0,1 --no-restart`、清除 managed 状态并精确终止遗留 watchdog；正式启动前两侧
  burner/watchdog 均为 0；
- 两侧 owner/SGLang、CPU owner、master/router 的 fatal 关键词计数均为 0；尚未发 workload。

### 0.12 2026-07-19 11:09 HKT：r19 tier1 0.75 正式结果通过并清场

正式 workload 与 r18 完全相同，结果：

- rc=0，Requests/Success/Error=`2304/2304/0`，QPS=`7.945039507`；
- TTFT p50/p90/p99=`2.030589/3.805540/9.779753s`；
  E2E p50/p90/p99=`2.681179/4.635025/11.493626s`；
- L1/L2/L3=`4.4392/0/61.4698%`，总命中=`65.9090%`；
- 相对 r18：QPS `+7.64%`、L2+L3 `+2.5673pp`、总命中 `+3.1438pp`；
- 相对 Mooncake：QPS `+20.72%`，L2+L3 `-6.5353pp`。tier1 方向有效，但命中尚未达标。

tier1 运行时语义：

- 0.75 对 128 GiB node space 的名义上限是 96 GiB；
- 当前代码实际取 `min(名义 tier1 上限, ring-B effective capacity)`；
- 本轮每侧 base=`130567005798`、live reservation=`124554051584`，所以 effective/tier1 capacity
  只有 `6012954214 bytes`（5.60 GiB）；
- node0/node1 终态均为 `1274 entries/6011486208 bytes`；trigger/accepted/failed 分别为
  `36147/21751/11772` 与 `53069/28515/20766`。

容量与剩余边界：

- direct-delete `1857` 批、`579691` victims，全部为多 victim batch，min/max/avg=
  `2/911/312.17`；node0/node1 completed=`141488/438203`，busy/in-progress 终态为 0；
- 两侧 active handles/flights、prepared/pending、selected/retry/debt/selected bytes 全归零；
- fatal、refill timeout、P2P 608、prefill OOM、scheduler exception、Put conflict 均为 0；
- node0/node1 出现 `701/1250` 次 `Put append operation not found for completion`，未造成请求错误，
  但暴露 proactive+tier1 并发下的重复/过期 completion 竞争；
- `load_back produced no prefix tokens` 为 `210/690`。

结果落盘后已停止 router、两套 SGLang、GPU/CPU owners、master/control。即时复核三机相关
tmux/进程/实验端口为空，两侧 GPU=`0 MiB/0%`，burner/watchdog=0。完整 results、全栈日志、
配置和 release manifest 已固化到：

`experiment_configs/e44_local_slot_tier_20260716/artifacts/e44_r19_direct_delete_singleflight_tier1_075_passed_20260719/`

### 0.13 2026-07-19 11:21 HKT：文档归档与延时清场复核

- 新增 r19 artifacts README，并把 r19 正式指标、实际 5.60 GiB tier1 clamp、completion 竞争和
  下一步门禁同步到本总账、E44 README、当前问题文档及命中率执行计划；
- 删除本机误执行产生的 rc=127 空跑 wrapper 日志，避免与远端正式 rc=0 结果混淆；该次空跑因
  本机不存在远端 workload 路径而在发请求前退出；
- 11:21 HKT 重新查询三台节点：相关 tmux、实验进程、端口均为 0；node0/node1 各两张 GPU 均
  `0 MiB/0%`、compute process=0，burner/watchdog process=0，`gpu_burner.sh status` 均报告
  “GPU 压测已停止”；
- 81 个 E44 顶层 shell 的 `bash -n`、r19 replica JSON、r18/r19 YAML 单行为变量比较、artifact
  rc/summary 精确断言和 Fluxon `git diff --check` 均通过；Fluxon 工作树保持干净；
- 当前保持停栈，未派生或启动 r20。

### 0.14 2026-07-19 12:13 HKT：远端 Put 控制流方向收敛

- 纠正术语：“普通 Put”指 external/local `put_start -> put_commit` 之后，由 owner 发起的真正
  `PutStart -> transfer -> PutDone`，不是 owner-local 提交本身；
- singleflight 的正确位置是 external→owner 边界上的 owner 发起侧。现有
  `ExternalPutKeySharedOp` 位置可复用，但它当前在 local publish 成功时即结束，生命周期没有覆盖
  remote terminal；
- 最终方向不是单独给 replica/evict 再补一套去重，而是让普通远端 Put、初次副本、tier1 和
  proactive 全部调用同一个 owner 函数。该函数统一负责 generation-safe singleflight、source pin、
  target/ticket 获取、transfer、Done/Revoke、重试和终态广播；
- master 仍可在 ticket/元数据层区分首 route 与追加 replica，但该差异只能位于很薄的 prepare/
  complete 适配层，不能复制 owner 侧传输状态机；
- evict 与 remote Put 继续正交，只通过精确 source fence 和 holder pin 仲裁；不增加 evict
  singleflight，不改变单 KV victim 与 `atomic_batch` 边界；
- 新增规划文档 `20260719_121358_fluxon_kv_owner统一远端Put控制流实施规划.md`。本轮只改文档，
  `Fluxon` 仍为干净的 `aafac11`，没有新代码、release 或实验结果；原 end-depth 实验暂后移，等待
  用户明确指令后先实施 owner 统一远端 Put P0。

### 0.15 2026-07-19 13:09 HKT：direct async owner remote-Put P0 实现与本地门禁

最终有效实现：

- 在既有 `OwnerKeyControlTable` 的 `OwnerKeyControlState` 中增加精确 `(key, put_id)` 的
  `remote_put`。短同步临界区只选 leader/follower，不在锁内执行 RPC、传输或其他 `await`；
- leader 取得当前 generation 的 `MemoryInfo`/`UserMemHolder` 后，立即启动独立
  `owner_remote_put_leader` 异步任务；followers 不拿 holder，通过 `watch` 等待并复用
  `Published/AlreadySatisfied/Obsolete/Failed` 终态；失败后重新进入同一选举，仍只能形成一个新
  leader；
- 预留 replica、owner local publish、external commit、tier1 和 proactive 全部收敛到
  `ensure_remote_put()`。旧预留 target 不再绕过公共入口，AppendStart 由 master 复用同一
  reservation；
- 删除 `ReplicaTaskJob`、`ReplicaTaskTarget`、replica task channel/rx/tx、replica task actor 及其
  batch 处理状态机。当前没有 replica actor、batch actor 或全局 remote-write FIFO；不同 key
  直接并发；
- remote flight 会阻止 owner-hot victim 选择和 reclaim 穿过正在传输的 source。payload transfer
  完成后释放 holder，但 `remote_put` 控制 fence 保留到 Done 终态；清理用 `Arc::ptr_eq` 校验精确
  flight，旧 generation 不能删除新 flight；
- master 为同一 `(key, put_id)` 的 AppendStart/Done/Revoke 共用 per-operation 异步锁。并发 Start
  只复用一份 inflight reservation；Done 终态缓存 120 秒，重放返回首次 `appended` 结果；已完成后
  的 Revoke 为幂等 no-op；
- 增加 owner active/leaders/followers/source-unavailable/transfers/各终态计数，以及 master Done
  terminal replay 计数；
- `replica_task_max_inflight` 为兼容旧配置继续解析和校验，但 direct singleflight 不再使用它建立
  actor 队列或全局限流。

设计演变与取消方案：实现过程中曾短暂保留 replica actor/channel，再由 leader 把任务送入 actor。
用户指出 actor 会形成额外排队后，该方向已完全撤销，最终工作树中不含相关类型、channel 或启动
逻辑。该中间版本未独立提交且已被后续修改覆盖，无法精确统计其新增/删除行数；下表只表示最终
工作树相对 `aafac11` 的净 diff，不能冒充全部中间工作量。

| 文件 | 新增 | 删除 | 最终职责变化 |
|---|---:|---:|---|
| `fluxon_py/config.py` | 1 | 1 | 标明旧 inflight 配置仅作兼容。 |
| `client_kv_api/external_api.rs` | 26 | 41 | external local commit 只触发公共 `ensure_remote_put`，不传递旧 target executor。 |
| `client_kv_api/mod.rs` | 418 | 53 | owner generation flight、watch 终态、leader/follower 选举、指标及 64 followers 测试。 |
| `client_kv_api/put.rs` | 221 | 650 | 删除 replica actor/batch 状态机；唯一 direct leader Start/transfer/Done/Revoke 控制流。 |
| `client_kv_api/reclaim.rs` | 6 | 1 | reclaim 与 active remote flight 使用同一 per-key fence。 |
| `config.rs` | 4 | 2 | 记录 `replica_task_max_inflight` 的兼容 no-op 语义。 |
| `master_kv_router/mod.rs` | 27 | 1 | terminal cache、per-operation 异步锁和 replay 观测。 |
| `master_kv_router/put.rs` | 67 | 5 | Start/Done/Revoke 同锁及 Done 幂等终态重放。 |
| **合计** | **770** | **754** | **8 个文件，触及 1524 行，净增 16 行。** |

本地验证：

- `findmnt -T /mnt/nvme0/mjq_build/push_sglang_fluxon_target` 确认目标位于
  `/dev/nvme0n1p3`，检查时可用约 485 GiB；没有把 Cargo target 写到 Ceph 或 `/tmp`；
- `cargo fmt --all -- --check`：通过；
- `cargo check -p fluxon_kv --lib`：通过，耗时 `17.12s`；
- `cargo test -p fluxon_kv --lib --no-run`：通过；
- `every_remote_put_trigger_joins_one_owner_generation_flight`：通过，64 followers 复用同一个 op；
- 全量 `cargo test -p fluxon_kv --lib`：`174 passed, 0 failed`，耗时 `235.00s`；
- 初次执行定向测试未设置 closed SDK loader 路径，二进制因找不到
  `libfluxon_commu_core.so` 以 rc=127 在测试入口前退出；补上既有 r18 NVMe release 的
  `LD_LIBRARY_PATH` 后定向和全量测试均通过。该 rc=127 是环境启动失败，不计为代码测试失败。

仍未验证：master Start/Done/Revoke 并发重放、owner leader 高并发失败接管、shutdown/cancel 的专项
测试；primary remote `PutStart/PutDone` 与 Append wire ticket 的 P1 合并；当前工作树的 r18/r19
三机负载。因此 r19 历史的 1951 个 completion missing 和约 8.57 GiB 重复 payload 尚不能登记为
已归零，也没有生成 r20 release。

### 0.16 2026-07-19 13:25 HKT：跨 generation flight 接管与 ABA 门禁

最终 diff 复核发现：如果旧 generation 的 remote flight 仍为 `InFlight`，而同 key 新 generation
已经成为当前 local source，原实现会直接返回 `SourceUnavailable`。这虽然不会让旧 payload
use-after-free，但会漏掉新 generation 本次应触发的远端 backing。

当前修复为：

- 相同 `(key, put_id)` 继续 join 既有 flight；
- 不同 `put_id` 不直接互相阻塞。新请求必须先从 `get_cached_info` 核对它确实是当前 local
  generation 并取得 holder，然后替换 per-key 可见 `remote_put` 槽；
- 被替换的旧任务仍持有自己的 source holder 和 shared op，可以安全完成或得到 `Obsolete`；
- 旧任务 finish 时用 `Arc::ptr_eq` 检查 visible flight，不能删除新 generation；active 计数分别在
  两个任务终态时归还。

新增定向测试
`new_remote_put_generation_replaces_old_without_aba_cleanup`，与 64 followers 测试一起运行结果为
`2 passed, 0 failed`。随后当前最终工作树全量 `cargo test -p fluxon_kv --lib` 为
`175 passed, 0 failed`，耗时 `196.40s`。

当前最终净 diff 更新为 8 个文件、`+861/-754`，触及 1615 行、净增 107 行；其中
`client_kv_api/mod.rs` 为 `+509/-53`。0.15 的 `+770/-754` 是 13:09 历史快照，未冒充当前统计。

### 0.17 2026-07-19 13:28 HKT：最终静态门禁收口

- 在 generation ABA 补丁及全量测试之后，最终 `cargo check -p fluxon_kv --lib` 再次通过，耗时
  `10.38s`；输出只有工作区既有 warning，没有编译错误；
- `cargo fmt --all -- --check` 与 `git diff --check` 最终通过；
- `git diff --numstat` 最终仍为 8 个文件、`+861/-754`，与 Snapshot 和 0.16 一致；
- 工作区顶层不是 Cargo/Git 根，格式检查最终在 `Fluxon/fluxon_rs` 执行，Git 门禁最终在
  `Fluxon` 执行；失败的顶层探测没有修改文件，也不算代码门禁失败；
- 至此 P0 本地门禁完成。仍未制作新 release，也未运行 r18/r19 三机验收，继续等待用户下一步
  指令。

### 0.18 2026-07-19 14:00 HKT：r20 最优配置复跑获准并完成预检

- 用户明确要求基于今天刚跑出的最优指标配置测试当前代码；本轮命名为
  `e44_r20_owner_remote_put_singleflight_tier1_075`；
- 固定复用 r19 的 tier1 0.75、`prefix_depth_ratio/160` admission、S96×T24、2304 请求、
  concurrency 24、session-stream、零 think-time、无预热，以及 GPU0/GPU1/CPU=
  `128/128/256 GiB` metadata-only 公平容量；唯一代码变量是当前未提交 owner remote-Put
  direct singleflight；
- 三机只读预检确认上一轮 tmux、Fluxon/SGLang 进程和实验端口均为空，三端 release 仍指向 r18；
- NVMe target 经 `findmnt` 确认为 `/dev/nvme0n1p3`，可用约 484 GiB；不会回退到 Ceph `target/`
  或 `/tmp`；
- 按实验规约，构建/部署阶段两 GPU 节点 burner watchdog 当前保持 managed 状态。正式启动 SGLang
  前才执行 `stop 0,1 --no-restart` 并保存 GPU 空闲证据；
- 当前尚未构建 r20 release、启动服务或发送请求，因此没有 r20 QPS/命中率，不能沿用 r19 指标。
- 新增 108 行隔离 release 构建脚本；脚本拒绝 `/tmp` rootfs 回退，并把 HEAD、工作树状态、完整
  diff 和源码哈希写进 release manifest。`bash -n` 已通过；Fluxon 核心净 diff 仍为
  `+861/-754`。

### 0.19 2026-07-19 14:17 HKT：r20 release 与精确复跑配置完成

- NVMe staging：
  `/mnt/nvme0/mjq_build/fluxon_e44_r20_owner_remote_put_singleflight_tier1_075_20260719`；
  最终复制路径：
  `/storage/mjq/sglang_fluxon/releases/fluxon_e44_r20_owner_remote_put_singleflight_tier1_075_20260719`；
- release 约 1.4 GiB；unified wheel SHA256=`edc4175653f0c4fa31b0a4d9dfdb14dd403ca408a96c7189bd9a41275cd1a93e`，
  PyO3 SHA256=`98442cc4312cee2bc3b48715eccb6aa0545b99778997f98f4de4a3fec23746eb`，
  metadata-only patch SHA256=`482a276e701c4fdd3c44654ff6c8e2403ee59fdb671513db61c62532a9b1c878`；
- ABI3 cp310/cp311/cp312 import、closed SDK、vendor runtime、release manifest 及复制后的二次
  `sha256sum -c` 全部通过；release 内封存 HEAD=`aafac111...`、8 文件状态、完整 worktree diff
  SHA256=`d7bf8f35...9e38` 和源码哈希；
- 打包日志中的 `/tmp/fluxon_pyo3_smoke_*` 是 `systemd-nspawn` 容器内路径；其 rootfs 为 NVMe 上的
  `/mnt/nvme0/mjq_build/fluxon_pypack_rootfs`，实际 I/O 仍位于 `/dev/nvme0n1p3`，没有回退到
  宿主机 `/tmp`；
- 新增 r20 install/deploy/config，并在 variant 表增加
  `owner_remote_put_singleflight_tier1_075`。当前编排净增合计 270 行；r19/r20 行为配置去掉
  `log_dir` 后完全相等，admission 仍为 `prefix_depth_ratio/160`；
- 尚未部署或启动，因此这些是产物门禁，不是三机结果。

### 0.20 2026-07-19 14:19 HKT：r20 三端部署完成

- 按 node0 → node1 → CPU 串行复制 1.4 GiB release 和安装隔离 venv，避免 GPU 两节点共享
  `/storage/zth` venv 的并行 pip 竞态；
- 三端 release manifest、wheel `edc41756...a93e`、PyO3 `98442cc4...46eb`、commu core
  `bfa6a32d...2503`、RDMA probe `e925553e...883` 和各自 venv import probe 均通过；
- 三个 `fluxon_release` 均已指向 r20 隔离 release；两侧 metadata-only HostKV patch 均为
  `482a276e...1c878`；
- 三端 variant/config SHA256 均分别为 `3a8c8d25...826`、`11e7a9d9...859`；部署后仍无 tmux
  或实验服务；
- 尚未停 burner、启动服务或发送请求，因此仍不能登记性能结果。

### 0.21 2026-07-19 14:30 HKT：r20 启动前总门禁通过

- control → master → 两侧 GPU owner/TP2 SGLang → CPU owner → router 已按顺序启动并全部 ready；
  master 日志确认 `replica_writeback_tier1_capacity_ratio: Some(0.75)`；
- 两侧 owner 均为 `137438953472 bytes`，local reserve 均为 `grants_after=232`、
  `expected_grants=232`、`slot_size=4718592`；CPU owner 为 `274877906944 bytes` 且 RDMA
  fast path `peer_count=2`；
- 两侧 TP0/TP1 均打印 metadata-only `materialized_pages=1`，发流前
  `hicache_host_used_tokens=0`；SGLang、router、master 和三位 owner 均存活；
- `gpu_burner.sh stop 0,1 --no-restart` 已清除 managed 标记，但旧 burner 从 `/public/zgf` 启动，
  脚本误判为非 burner，旧 watchdog 也未退出。根据完整命令行核对后，精确终止两侧各 2 个 burner
  PID 和 1 个 watchdog PID；复核均为 `Watchdog is stopped`、burner process=0；
- 两侧日志各有一条 r19 同样存在的可选 OpenAI Responses import warning：缺少
  `openai_harmony`。其后明确 `Application startup complete` 且 health=200；窄化后的 refill
  timeout、P2P 608、prefill OOM、scheduler exception、Put conflict、panic/segfault 均为 0；
- router 与两侧 SGLang health 均为 200。尚未启动正式 2304 请求，因此不能登记 QPS/命中率。

### 0.22 2026-07-19 14:40 HKT：r20 同 r19 最优配置正式验收完成

- run id=`e44_r20_owner_remote_put_singleflight_tier1_075`；配置、容量、admission、workload 和
  burner 实验窗口与 r19 完全一致，只更换为包含当前 8 文件 remote-Put 重构的 r20 release；
- workload rc=0，`2304/2304`、error=0；QPS=`7.742272953`；TTFT p50/p90/p99=
  `2.086486/3.965337/9.885159s`，E2E p50/p90/p99=`2.680934/4.652207/11.676458s`；
  L1/L2/L3=`4.47799/0/60.51801%`，总命中=`64.99600%`，HostKV used after=`0/0`；
- 相对 r19，QPS=`-2.5521%`、L2+L3=`-0.9518pp`、总命中=`-0.9130pp`；相对 r18，
  QPS=`+4.8897%`、L2+L3=`+1.6155pp`。因此 r19 仍是性能最优，r20 只封为当前代码验收版；
- node0/node1 remote-Put followers=`742/1274`；transfers=`37917/56879` 且全部 published，
  leaders 精确等于 published+already-satisfied；active/obsolete/failed=`0/0/0`；
- r19 的 `701/1250` 次 `Put append operation not found for completion` 在 node0/node1/master
  全部降为 0；2016 followers 按单 slot 估算避免 `8.859375 GiB` 重复 payload；master terminal
  replay=3，说明响应重放没有重新传 payload；
- direct-delete=`1724` 批、`536540/536540` victims，retryable=0，min/max/avg=
  `4/850/311.218`；两侧 handoff=committed=`139362/397178`，所有临时容量态归零；
- tier1 node0 trigger/accepted/failed=`38961/22820/14780`，node1=
  `59223/29494/28443`；两侧 retained 均为 `1274 entries/6011486208 B`。failed 与 owner source
  unavailable 完全相等；
- `load_back produced no prefix tokens` 为 `278/696`，合计 974，高于 r19 的 900；这是当前最值得
  继续归因的命中损失之一，不能因 singleflight 正确性通过而忽略。

### 0.23 2026-07-19 14:50 HKT：r20 清场、证据归档与总账收口

- workload、router、两套 SGLang、GPU/CPU owners、master/control 均已停止；14:47 HKT 延时复核
  node0/node1/CPU 的相关 tmux、进程和实验监听端口均为 0；
- burner 在正式 workload、drain 和 after-metrics 期间保持停止；停栈后按
  `Fluxon_Mooncake_实验规约.md` 恢复 managed watchdog。两侧各 2 个 compute process 均为恢复后的
  managed burner，不是实验残留；
- results、2304 条请求、before/after metrics、网络样本、全栈日志、rc=0、精确配置、编排脚本和
  release manifest 已复制到
  `artifacts/e44_r20_owner_remote_put_singleflight_tier1_075_passed_20260719/`；加入 README 和
  CLEARANCE 后共 43 个文件、约 68 MiB；
- artifact 内保存 source HEAD=`aafac111...200b`、工作树 diff SHA256=`d7bf8f35...9e38`、wheel
  `edc41756...a93e`、PyO3=`98442cc4...46eb` 和 metadata-only patch=`482a276e...1c878`；
- 当前停止在结果交接，不启动 end-depth 或其他实验，等待用户下一步指令。

### 0.24 2026-07-19 15:24 HKT：tier1 独立容量语义修复落地

- 设计复核确认 master tier1 是只保存 key/version/weight 的 inclusive metadata 策略窗口，容量应为
  `replica_writeback_tier1_capacity_ratio × owner segment`；local-reserve reservation 只占用物理
  ring-B allocation domain，不能裁剪 tier1；
- 删除 `reconcile_node_cache_capacity()` 与
  `adjust_node_cache_reserved_capacity_identity()` 中两处
  `min(tier1_base, ring_b_effective)`，并提取统一的 `node_cache_capacity_boundaries()`：ring-B 继续
  扣 generation-scoped reservations，tier1 始终不扣；
- 新增回归测试固定 128 GiB、ring-B 0.95、tier1 0.75、reservation 124554051584 B 的边界：
  ring-B=`6012954214 B`，tier1=`103079215104 B`（96 GiB）；
- owner remote Put 的 `source_unavailable` 新增 `fenced/missing/version_mismatch` 三项互斥原因计数，
  用于判断 r20 的 43223 次失败究竟来自 transient fence 还是已经消失/换代的 source；
- 本轮相对 14:50 快照净增 `+107/-17`，只修改两个既有 Rust 文件，没有改变单 KV victim、
  atomic_batch、owner singleflight 或 remote Put 调度；tier1 定向测试 `1/1`、Cargo check、全量
  `176/176`（196.21s）、最终 fmt/diff 均通过。真正 96 GiB tier1 三机实测尚未执行，r20 结果
  不能冒充当前代码验收；
- 首次定向测试命令曾漏设 `CARGO_TARGET_DIR`，在源码树既有 `target/` 中启动编译但未进入测试；
  发现后终止整个进程组，并确认无残留进程。为避免破坏原有共享构建缓存，没有删除该既有目录。
  后续所有可登记的 check/test 均显式使用 `/mnt/nvme0/mjq_build/push_sglang_fluxon_target`。

### 0.25 2026-07-19 15:45 HKT：r21 隔离 release 构建完成

- 新 run id=`e44_r21_tier1_independent_075`，行为配置与 r20 完全相同：metadata-only
  128/128/256 GiB、tier1 ratio 0.75、`prefix_depth_ratio/160`、相同 2304 请求 workload；唯一核心
  行为变化是 tier1 不再受 ring-B reservation clamp；
- release staging、Cargo target 和 manylinux rootfs 均位于 `/dev/nvme0n1p3`；统一 wheel=
  `e4aeef91467f822a1c6eed85c47d2d1d2fb8c29657d6334ecdddd30f07c10468`，PyO3=
  `ab733bf7b9b30b04bfb4e5dee3c4c81435d7251e4b6b62f7bfabfb7ef153e101`；
- metadata-only patch 仍为 `482a276e...1c878`；release 固化的 Fluxon source diff 为
  `69392a2c...2b5a6`，已确认包含 tier1 回归、原因计数和两处 clamp 删除；
- ABI3 cp310/cp311/cp312 import、closed SDK、vendor runtime 和全部 release SHA256 门禁通过；
- 新增 build/install/deploy=`108/74/52` 行、master config=28 行、variant=8 行，合计 `+270/-0`；
  脚本语法、YAML/JSON 解析和 r20/r21 配置结构等价检查通过。当前尚未部署或启动服务。

### 0.26 2026-07-19 16:18 HKT：r21 三机正式验收、负收益归因与清场

- r21 已部署到 GPU0/GPU1/CPU 三端；wheel、PyO3、commu core、RDMA probe 和 metadata-only patch
  哈希一致。GPU owner=`128/128 GiB`、CPU owner=`256 GiB`，两侧 grants=`232/232`、
  slot size=`4718592`，HostKV TP0/TP1 均为 `materialized_pages=1`；
- 首次 CPU owner 启动早于两个 GPU peers，300 秒 readiness gate 报
  `no eligible owner peers observed` 并退出。旧实例完整清理后，在两个 GPU owner ready 的条件下重启；
  新实例写出 `shared.json`，segment=`274877906944 B`，RDMA fast path=`peer_count=2`，启动 rc=0。
  该启动失败发生在正式 workload 前，不计入正式结果；
- 当前 workload 脚本与 r20 artifact 逐字节相同，SHA256=
  `f173859721b529c8a346f098c2c7f3d56af6607568fb8ac2bbf3331d2d6eaa71`。正式结果为
  `2304/2304`、error=0、QPS=`7.370114467`；TTFT p50/p90/p99=
  `2.061381/4.454487/9.878182s`，E2E=`2.720383/5.564537/11.841482s`；
  L1/L2/L3=`3.99133/0/58.10273%`，总命中=`62.09407%`；
- 运行时两侧 tier1 capacity 均为 `103079215104 B`，证明独立容量修复生效。终态 node0/node1
  tier1 retained=`11879/8081` 项、`56052154368/38130941952 B`；
- 相对 r20，tier1 triggered 合计从 `98184` 降到 `8279`，owner remote transfers 从 `94796`
  降到 `56120`，CPU retained 少 `11932` 项/`52.44 GiB`；删除最后 route 增加到
  `55290/242.97 GiB`，相对 r20 精确 `+60.01%`。这条链路解释了 L2+L3 `-2.4153pp`：
  96 GiB metadata 窗口把远端写回推迟过久，而 r19/r20 的 5.60 GiB 错误 clamp 恰好形成早写回；
- source unavailable node0/node1=`2282/2087`，原因全部为 `missing`，fenced/version mismatch 均为
  0。两侧 leaders 精确等于 published+already-satisfied，followers=`100/141`，completion missing=0，
  active/obsolete/failed=0；
- direct-delete `927` 批，victims/completed/retryable=`199874/199854/20`，20 个 busy 项最终全部重试
  完成；两侧 handoff=committed=`56499/143355`，selected/retry/debt/selected bytes 和 pending 全归零。
  `refill timeout`、P2P 608、OOM、scheduler exception、业务非 200 均为 0；
- workload、after-metrics 和终态快照完成后已停止 router、两套 SGLang、三位 owner、master/control。
  16:17 HKT 复核三机实验 tmux/进程/端口均为 0，并恢复两侧 managed burner watchdog。完整 43 个
  文件、约 54 MiB 证据位于
  `artifacts/e44_r21_tier1_independent_075_passed_20260719/`；当前等待用户选择小 tier1 窗口或独立
  end-depth 288 分支，不自动继续实验。

### 0.27 2026-07-19 16:59 HKT：r22 ratio=0.05 首轮扫描通过并清场

- 用户批准扫描 `0.05/0.10/0.18/0.25/0.50`。Fluxon 核心代码和 r21 release 均未变化；新增 5 份
  28 行 master config，并给 variant 表新增 5 个 8 行 case，编排净变化为 6 文件 `+180/-0`。
  workload SHA256 仍为 `f173859...aa71`；三端 wheel=`e4aeef...0468`、PyO3=`ab733b...e101`，
  两侧 metadata-only patch=`482a27...c878`；
- r22 只把 tier1 ratio 改成 `0.05`。两侧 runtime capacity 均为 `6871947673 B`，ring-B 仍为
  `6012954214 B`；GPU0/GPU1/CPU=`128/128/256 GiB`，grants=`232/232`，CPU RDMA
  `peer_count=2`，四个 TP rank 均打印 `materialized_pages=1`；
- workload rc=0，Requests/Success/Error=`2304/2304/0`，QPS=`7.650137995`；TTFT
  p50/p90/p99=`2.093514/4.170966/9.975130s`，E2E=`2.735980/4.818375/11.550333s`；
  L1/L2/L3=`4.56986/0/59.28476%`，总命中=`63.85463%`。相对 r21 是
  `+3.7994% QPS/+1.18203pp L2+L3`，但仍低于 r19 `3.7118%/2.18504pp`；
- CPU retained 恢复到 `55341/261131599872 B`（243.20 GiB），与 r20 小窗口水位相同。两侧
  tier1 triggered/accepted/failed=`93121/48559/43170`，remote transfers=`90839`；最后 route
  删除为 `33486/147.16 GiB`，比 r21 明显降低；
- direct-delete requests/victims/completed/retryable=`1536/433310/433309/1`，唯一 busy 为累计响应，
  owner 最终 retry entries=0；两侧 handoff=committed=`102447/330862`。active、pending、selected、
  debt、selected bytes、master in-progress 均为 0，completion missing=0；正式窗口 fatal/业务错误=0。
  日志里的唯一 HTTP 503 是 node1 SGLang 启动健康探针，发生在 workload 前，不计正式错误；
- `gpu_burner.sh stop 0,1 --no-restart` 本轮清除了 managed 标记，但未识别旧 job-specific burner
  PID；按规约精确匹配 watchdog 和 `.gpu_burn_script_* --gpu [01]` 终止后，确认四张 GPU 空闲才启动
  SGLang。结果落盘后完整停栈，16:58 HKT 三机实验进程/端口为 0，并用 `start 0,1` 恢复 managed
  burner。约 68 MiB 证据已固化到 `artifacts/e44_r22_tier1_independent_005_passed_20260719/`。

### 0.28 2026-07-19 17:23 HKT：r23 ratio=0.10 通过，用户终止后续扫描

- r23 继续复用 r21 release 和相同 workload，唯一策略变量从 r22 ratio `0.05` 改为 `0.10`；两侧
  runtime tier1 capacity 均为 `13743895347 B`（12.8 GiB），其他容量与版本门禁无漂移；
- workload rc=0，`2304/2304`、error=0，QPS=`7.393700330`；TTFT p50/p90/p99=
  `2.079607/4.535574/9.941472s`，E2E=`2.648580/5.629776/11.392305s`；L1/L2/L3=
  `3.81826/0/59.52394%`，总命中=`63.34220%`；
- 相对 r22，L2+L3 仅增加 `0.23917pp`，但 QPS 下降 `3.3521%`，L1 下降 `0.75160pp`，导致总命中
  下降 `0.51243pp`。CPU retained 也从 243.20 GiB 降到 241.26 GiB；
- direct-delete requests/victims/completed/retryable=`1338/341848/341840/8`；两侧
  handoff=committed=`102043/239797`，所有临时态收敛。completion missing、fatal、正式业务错误均为 0；
- after-metrics 和全栈日志固化后已完整清场，三机实验 tmux/进程/端口为 0，并恢复两侧 managed
  burner。38 个文件、约 66 MiB 位于 `artifacts/e44_r23_tier1_independent_010_passed_20260719/`；
- 用户根据 QPS 已出现下降，明确表示没有必要继续测试。因此 r24 18%、r25 25%、r26 50% 均未
  启动；配置文件仅作为未运行候选保留，不得写成实验结果。当前等待下一步指令。

### 0.29 2026-07-19 17:29 HKT：用户追加 r27 ratio=0.30 单变量

- 用户在停止原扫描后追加“直接测 30%”。为避免把未运行的 r24–r26 编号改义，新建
  `e44_r27_tier1_independent_030`；
- 新增 28 行 master config，并在既有 variant 表新增 8 行 r27 case。本次增量为 2 文件
  `+36/-0`；连同先前候选配置，tier1 扫描编排累计为 7 文件 `+216/-0`。Fluxon 核心源码无变化；
- r27 继续复用 r21 wheel/PyO3、metadata-only HostKV、`128/128/256 GiB`、depth160 和原
  S96×T24 workload；相对 r21 config 的行为差异只有 ratio=`0.30`，另一差异为隔离日志目录；
- 本地 `bash -n` 与 config diff 审查通过；variant/config 已部署到三端。启动前状态为三机实验
  tmux/端口为 0，两侧 burner 在 managed watchdog 下运行。尚未启动服务或 workload。

### 0.30 2026-07-19 17:45 HKT：r27 ratio=0.30 正式结果与清场

- r27 版本、容量、HostKV、admission 和 workload 门禁均与 r22/r23 一致；两侧运行时 tier1
  capacity=`41231686041 B`（38.4 GiB），CPU RDMA=`peer_count=2`；
- workload rc=0，`2304/2304`、error=0，QPS=`7.289788870`；TTFT p50/p90/p99=
  `2.083927/5.170297/9.927198s`，E2E=`2.789714/7.048286/11.692579s`；L1/L2/L3=
  `4.01428/0/58.34688%`，总命中=`62.36116%`；
- 相对 r23 10%，QPS `-1.4054%`、L2+L3 `-1.17706pp`、总命中 `-0.98104pp`；相对 r22 5%，
  QPS `-4.7104%`、L2+L3 `-0.93788pp`。30% 不只是吞吐下降，命中也同步回退；
- CPU retained 从 r23 的 241.26 GiB 降到 `44631/210595479552 B`（196.13 GiB）；tier1
  triggered/accepted/failed=`40082/11993/27151`，remote transfers=`61901`。窗口放大继续推迟写回，
  与 r21 的归因方向一致；
- direct-delete requests/victims/completed/retryable=`1112/248189/248175/14`，两侧
  handoff=committed=`75881/172294`。active、pending、selected、retry、debt、selected bytes、master
  in-progress 全部归零；completion missing、fatal、正式业务错误均为 0；
- 结果和 after-metrics 落盘后完整停栈，三机实验 tmux/进程/端口为 0，并恢复两侧 managed burner。
  38 个文件、约 62 MiB 位于 `artifacts/e44_r27_tier1_independent_030_passed_20260719/`。当前不再
  自动测试更大窗口，等待用户下一步指令。

### 0.31 2026-07-19 17:56 HKT：r27 后续优化多角度分析

- 新文档 `20260719_175605_fluxon_kv_r27后续优化多角度分析.md`=`+290/-0`；本总账同步前后为 `1022→1046` 行（净 `+24`，根目录非 Git 且含替换行，不冒充精确 `+/-`）；
- 本轮没有修改 Fluxon 源码、配置或实验编排，也没有启动新实验；
- 同口径复核 r22/r23/r27：tier1 从 5%→10%→30% 时，remote transfers 从
  `90839→79538→61901`，last-route removed 从 `33486→41462→53102`，CPU retained 从
  `243.20→241.26→196.13 GiB`；继续放大 tier1 没有数据支持；
- 按 4-turn bucket 复核 TTFT，各版本前 4 轮接近，r22/r23/r27 的 20–23 turn mean 为
  `5.234/5.380/5.417s`；退化随长 prefix 积累，不像固定 RPC/singleflight 开销；
- 源码快照确认 `prefix_depth_ratio/160` 只判断 atomic group 的 start depth，新路由
  root child 即使长 300–413 页也可整段入选；`prefix_end_depth_ratio/288` 按完整 group
  的 end depth 判断，不拆 group，也不改单 KV 容量 victim 边界；
- 节点拆分显示 node0 远端命中从 r22 约 66.16% 到 r27 约 68.71%，而 node1 从
  53.22% 降到 49.21%；后续必须分 owner 验收，但现有证据不足以直接改 router；
- P0 推荐以 r22 5% 为当前 release 性能基线，只切换 end-depth 288 preset。若结果
  模糊或负收益，先补副本价值生命周期观测，或做 tier1-off 两轮严格归因；不回头
  扫更大 tier1，命中未达 Mooncake `68.0051%` 前不开始 load-back 数据面优化。

### 0.32 2026-07-19 18:44 HKT：固定请求下的通信与带宽利用分析

- 用户要求在不增加请求量的前提下，从控制面、数据面和尽量用满带宽的角度重新排查；
- 本轮没有修改 Fluxon 源码、服务配置或实验编排，没有启动新实验；r27 停栈和 burner
  恢复状态未改变；
- 从同口径 SGLang `HiCache prefetch submitted` 日志累加每 TP rank 的 tokens，按
  `4,718,592 B / 64 tokens = 73,728 B/token/rank` 换算。r19/r22/r23/r27 逻辑
  prefetch payload=`4792.11/4649.42/4619.96/4564.49 GiB`，全程平均=
  `16.53/15.44/14.82/14.44 GiB/s`；这是提交层逻辑 payload，不是 HCA wire bytes；
- 按日志秒粒度聚合，r22 在 301.17s 中只有 230 个 1s 桶出现新 prefetch，活跃桶平均
  `20.21 GiB/s`、单桶提交峰值 `46.79 GiB`；r27 为 233/316.06 个活跃桶、
  `19.59 GiB/s` 和 `49.06 GiB`。这证明需求爆发，但不能单独证明 HCA 空转；
- 复核控制面：Get 已用 BatchStart/Done，direct-delete 已整批一次往返；remote Put 仍每 KV
  独立 Start/Done。r22/r23/r27 的 leaders 加 payload transfers 约对应
  `195966/171055/129562` 次控制 RPC，说明直接调用式 `ensure_remote_put_batch()` 有独立优化
  价值，但 RPC 数下降与 QPS 下降同时发生，所以它不是 tier1 退化的主因；
- 确认观测硬缺口：所有历史轮 `rdma_hcas=[]`、RDMA rx/tx=`null`，因为 `perfquery`
  缺失；SGLang 带宽直方图也全为 0，现有采集还漏掉中央 CPU owner。因此当前不宣布
  双 HCA 已满或未满；
- 下一轮先给 workload 采集器增加 sysfs RDMA fallback，覆盖 GPU0/GPU1/CPU 三节点的
  `mlx5_4`/`mlx5_6`，并与 Get/Put queued/active/bytes 时序对齐。该改动只影响观测，可与
  r22 5% + end-depth 288 的 P0 同轮完成；
- 分析文档从 290 行增至 484 行，净增 194 行；新增有用 goodput 定义、逻辑 payload
  表、观测缺口、remote Put 批量候选、在途深度、双 HCA 均衡、Get/Put 分级和拿到真实时序后的
  决策树；本总账同步前后为 `1046→1076` 行（净 `+30`，包含 Snapshot 替换行，不冒充精确
  键入工作量）。

### 0.33 2026-07-19 19:11 HKT：r22 Greptime 网络观测复测编排完成

- 用户将下一轮调整为“先复跑一个已测版本，把网络观测做足”；选择当前 release QPS 最好的
  r22 tier1 5% 作为被复跑配置，run id 隔离为 `e44_r28_r22_netobs_replay`；
- r28 复用 r22 的 r21 release、`prefix_depth_ratio/160`、tier1 5%、128/128/256 GiB、
  96 sessions×24 turns、2304 请求和 concurrency 24。本轮不叠加 end-depth 288 或网络优化；
- 唯一服务行为差异是 master、两 GPU owner/external 与 CPU owner全部从
  `disable_observability=true` 改为 `false`，用于向 Greptime 上报既有逻辑传输、peer、RPC、
  transfer-engine 与 RDMA 健康指标。因此本轮是网络诊断基线，不能把 QPS 与 r22 的差异直接
  解释为缓存实现波动；
- 三台机器的 `mlx5_4/mlx5_6` 都为 400 Gbps ACTIVE，但容器 sysfs 不暴露 counters。CPU
  自带 `perfquery`，其 glibc 2.38 binary 不能在 GPU 的 glibc 2.35 上运行；最终从 Ubuntu
  22.04 `infiniband-diags=39.0-1` 提取兼容工具到 NVMe staging，三节点定向查询四个 HCA
  均能返回 `PortXmitData/PortRcvData`；
- 新 observer 以三节点本地 500ms 采样避免 SSH 轮询，只查询已配置的两张 HCA；原始 JSONL
  保留审计证据，负载结束后按原始时间戳批量导入 Greptime 表
  `fluxon_hca_port_timeseries`，最终分析仍以 Greptime 为主视图；
- workload 原 Greptime 建表 SQL 未引用保留字 `policy`。r28 不修改共享 workload 源码，改为
  启动前创建全量 quoted-schema，并以 `--greptime-no-create-tables` 写入，避免再次出现
  `submitted_points>0/written_points=0`；
- 编排最终净改动为 variant `+10/-0`，另新增 10 个文件共 `+1066/-0`，合计
  `+1076/-0`。已通过 `bash -n`、Python `--help` 导入、YAML、replica JSON、r22/r28 配置
  等价性和 NVMe mount 门禁；尚未部署、尚未完成 observer/Greptime 运行自检，也未停止 burner。

### 0.34 2026-07-19 19:50 HKT：r28 Greptime 网络诊断轮完成

- r28 完整复用 r22 的 r21 release、tier1 5%、`prefix_depth_ratio/160`、metadata-only
  128/128/256 GiB、S96×T24、2304 请求和 concurrency 24；唯一服务差异是打开 Fluxon
  observability，所以该轮用于诊断，不替代 r22 的严格性能排名；
- workload rc=0，`2304/2304`、error/fatal=0；QPS=`7.844556385`，TTFT
  p50/p90/p99=`2.054959/3.871597/9.654660s`，E2E=`2.670252/4.702510/11.395490s`，
  L1/L2/L3=`4.44217/0/60.49956%`，总命中=`64.94173%`；
- workload 向 Greptime 写入 `2148` 个 timeseries points 和 `816` 个 phase fields，write
  errors=`0`。三节点两张 HCA 的 500ms 计数共 `9384` 行、采样错误=`0`，已导入
  `fluxon_hca_port_timeseries`；
- Greptime 正式窗查询显示 CPU 双 HCA TX 平均/p99/峰值=`51.130/262.550/324.775 Gbps`，
  对 800 Gbps 为 `6.39%/32.82%/40.60%`；两卡平均=`25.570/25.560 Gbps`，无偏载。
  1s 聚合仅一个桶超过 200 Gbps，294 个桶中 87 个低于 0.1 Gbps，链路不是饱和瓶颈；
- CPU TX 与两 GPU RX 的物理字节只差 `17280 B`。GPU→CPU 物理字节相对 89739 次固定
  4.5 MiB remote Put payload 只高 `1.1345%`；此前按 external Put 逻辑量计算出的约 10%
  差额主体是额外 7347 次真实 write-back，不是 wire overhead；
- node0/node1 的 L3 cached tokens 接近，但 CPU→GPU 物理读取为 `333.87/1542.30 GB`，node1
  是 `4.62x`；master Get Start 为 `135419/380519`，direct-delete victims 为
  `93719/371755`。Greptime owner 日志在 node1 两次采到 `finishing_flights=512`，正好顶到
  `4×128` Get finish 窗口；
- process CPU、Tokio busy/global queue 均未饱和。结合双 HCA 大量空窗，下一项单变量改为只把
  Get `batch_concurrency=32→64`，保留 r28 其他配置和同一 Greptime/HCA 采集；end-depth 288
  暂不与它同轮，避免无法归因；
- 内建 `kv_peer_network_bytes_total` 只含 `local_ipc`，源码中的 RDMA snapshot 只有 consumer、
  没有生产者调用。后续仍需补 actual Get transferred/revoked bytes、per-peer/op RDMA bytes、
  queue/active 与 transfer breakdown，不能把 HCA 总量冒充逐 operation 指标。

### 0.35 2026-07-19 19:50 HKT：r28 清场与证据固化

- 已按 router/SGLang → GPU/CPU owners → master → control/Greptime 的顺序停栈，并停止三端
  observer；临时只读 Greptime 查询实例也已在补充 SQL 后停止；
- 19:40 HKT 复核三机 r28/Greptime/observer tmux 和进程为空。两 GPU 节点均执行
  `/storage/zgf/gpu_burner.sh start 0,1`，watchdog managed，四卡约 1395 MiB/100%；
- 完整 results、三机服务日志、两侧 request metrics、原始 HCA、分析结果、Greptime DB、配置和
  release manifest 已复制到
  `experiment_configs/e44_local_slot_tier_20260716/artifacts/e44_r28_r22_netobs_replay_passed_20260719/`；
  原始复制完成时为 109 个文件；补入 README、CLEARANCE、Greptime SQL/聚合与 SHA256 清单后
  最终为 115 个文件、约 220 MiB，`sha256sum -c` 全部通过。

### 0.36 2026-07-19 20:10 HKT：r29 Get batch64 单变量编排完成

- 用户授权按 r28 诊断结论“修改并测试”；新 variant
  `tier1_independent_005_netobs_get64` 使用 run id=`e44_r29_get_batch64_netobs`；
- `e44_v5_perf_variant_20260718.sh` 增加默认
  `E44_PERF_HICACHE_BATCH_CONCURRENCY=32`，只有 r29 覆盖为 64；既有 r28 source 后仍实测为 32；
- `launch_gpu_e44_r28_netobs.sh` 不再硬编码 32，而是消费 variant 字段；CPU owner、master、
  replica admission、tier1、容量和 workload 参数不变；
- `manage_hca_observer_e44_r28.sh` 增加可选 run id，session、JSONL 和 log 均按 r29 隔离；默认值
  仍为 r28 run id；
- 新增 28 行 master config，除隔离 `log_dir` 外与 r28 YAML 结构完全相等；部署脚本只增加该配置
  的复制；
- 相对 r28 artifact 的逐文件净改动：variant `+12/-0`、GPU launcher `+1/-1`、HCA manager
  `+5/-4`、deploy `+1/-0`、新 master config `+28/-0`，合计 5 文件 `+47/-5`；
- `bash -n`、YAML 等价、replica JSON、r28=32/r29=64 和 NVMe tool root 位于
  `/dev/nvme0n1p3` 的门禁通过。尚未部署三机、尚未停 burner 或启动服务。

### 0.37 2026-07-19 20:30 HKT：r29 Get64 正式测试完成，性能 no-go

- 三端继续使用 r21 release；master tier1 实际 ratio=`0.05`，两侧 metadata-only HostKV、
  `128/128/256 GiB` 容量与各 232 grants 均通过启动门禁。两侧实际 SGLang cmdline 已确认
  `batch_concurrency=64`；其他 release、admission、workload 和观测参数与 r28 相同；
- burner 和遗留 watchdog 在正式请求前已停止。master、三位 owner、两套 TP2 SGLang、router、
  Greptime 和三端 HCA observer 全部 ready，HTTP health=200，启动前 refill timeout/P2P 608/OOM/
  fatal=0，三端 HCA 样本 `error=null`；
- workload rc=0、未超时，`2304/2304`、error=0；QPS=`7.615272617`；TTFT p50/p90/p99=
  `2.134034/4.062147/9.798854s`，E2E=`2.810293/4.874785/11.486272s`；L1/L2/L3=
  `4.41418/0/59.54021%`，总命中=`63.95438%`。相对 r28，QPS=`-2.9228%`、L3=
  `-0.95935pp`；正式窗口 non-200、refill timeout、P2P 608、OOM 和 panic 均为 0；
- 正式窗口 `1784463817.437136–1784464119.987040` 的 CPU 双 HCA TX 平均/active-average/p99/
  峰值=`48.633/84.650/248.937/314.345 Gbps`，相对 r28 全部下降。303 个 1s 桶中 91 个低于
  0.1 Gbps；CPU TX 与两 GPU RX 只差 `17856 B`，物理计数闭合。两卡平均 TX=
  `24.333/24.300 Gbps`，没有 steering 偏载；
- Greptime 正式窗未再采到 node1 `finishing_flights=512`，只采到一次
  `starting_flights=89`；process CPU 和 Tokio busy 仍未饱和。Get64 没有提高活跃带宽，且 QPS、
  延迟、命中均未改善，因此按预设门禁停止此方向，不再扫 48 或更高并发；
- workload Greptime 写入 points/phase fields/errors=`2212/817/0`；三端 HCA 导入
  `5412` 行、sample error=0。详细结论已写入
  `20260719_203745_fluxon_kv_r29_Get64单变量测试结果与下一步.md`。

### 0.38 2026-07-19 20:40 HKT：r29 退出缺陷、清场与证据固化

- 已按 router/两套 SGLang → 三位 owner → master → control/Greptime 的顺序停栈，并先停止三端
  observer、冻结正式观测窗口；
- 两侧 GPU owner 都在打印 `Shutdown Complete` 后由 `MemoryInfo::drop` 再次调用
  `ClientKvApiView::spawn`，因为 module view 已销毁而触发 destructor panic/abort；CPU owner 还报告
  close `Result<ok>` 未显式消费。这些事件发生在正式 workload 后约 4 分钟，不污染正式指标，但
  新增为 shutdown/cancel P1，后续需修析构顺序并加 close 定向测试；
- 三机 r29/control tmux 和匹配进程最终均为 0。两台 GPU 节点已执行 burner start，两个 watchdog
  均为 managed，四张 GPU 最终均为 100%、free memory 约 `79686 MiB`；
- 完整 workload results、Greptime DB、三机服务日志、两侧 request metrics、三份原始 HCA、正式窗
  汇总、配置、release manifest 和 SHA256 清单共 103 个文件、约 204 MiB，102 项校验全部通过，已固化到
  `experiment_configs/e44_local_slot_tier_20260716/artifacts/e44_r29_get_batch64_netobs_completed_20260719/`；
- r29 只改实验编排，不改 Fluxon/SGLang 核心源码；相对 r28 artifact 的最终编排净改动仍是 5 文件
  `+47/-5`。本轮新增分析/归档文档不冒充核心代码工作量。

### 0.39 2026-07-20 00:18 HKT：r31 后性能优先级与非性能 TODO 分栏

- 复核 r31 正式证据后，性能 P0 收敛为在 r31 release 上保持 Get32、tier1 5%、metadata-only
  `128/128/256 GiB`、workload 和观测不变，只切换 admission preset 为
  `prefix_end_depth_ratio/288`；当前没有创建 r32 variant，也没有启动服务或实验；
- 原因是 r31 QPS 已比 Mooncake 高约 16%，但 L2+L3 仍低 `7.08984pp`；HCA 未饱和且 r29 Get64
  已 no-go。当前应优先验证“拒绝 300–413 页后续长尾能否保护高复用 root prefix”，不是继续放大
  在途并发；
- 从 r31 两侧 SGLang 日志重新精确统计 Get Start/Cancel/Transfer=`4882/756/4126`，因此 r31
  common-prefix 冗余是 756 次 Cancel 加 756 次重复 Start，不再沿用 r29 的 1324。Get Start
  mean/p90/p99=`16.414/36.391/61.699ms`、Cancel mean=`0.461ms`；该项排 P1，预期主要改善控制
  RTT/CPU，不冒充命中率修复；
- 新建 `20260720_001033_fluxon_kv_r31后性能优化优先级与待修复TODO.md`，把性能 P0–P5 与
  shutdown/close、启动编排、专项测试、缺失观测和协议维护 TODO 分栏。GPU owner 析构 panic、CPU
  close Result、node0 二次 Ctrl-C 等明确记录为非性能问题，不与下一性能单变量混跑；
- 本轮新增 1 份 Markdown，并同步更新本总账与 ACK 计划中的 r31 common-prefix 数值；没有修改
  Fluxon/SGLang 核心源码、release、远端部署或运行状态。历史 `+1815/-862` 核心工作树净 diff
  与 r31 验收覆盖不变。

### 0.40 2026-07-20 08:20 HKT：r32 end-depth 288 单变量配置派生

- 新增 variant=`tier1_independent_005_netobs_ack_batch_source_fence_wait_enddepth288`、run id=
  `e44_r32_enddepth288_netobs`；它复用 r31 GPU/CPU venv、PyO3 哈希和 release，只把 replica
  admission 从 `prefix_depth_ratio/160` 切到 `prefix_end_depth_ratio/288`，全局默认 Get concurrency
  仍实测为 32；
- 新 master YAML 相对 r31 删除隔离 `log_dir` 后无 diff，tier1 仍为 0.05、observability 仍开启；
- 新增 config-only 三端部署脚本，只同步 variant/YAML，并强制校验三端 release symlink、r31 venv、
  Get32、admission JSON、PyO3 与文件 SHA256，不复制或重建 release；
- 精确实验文件改动：variant 相对 r31 artifact `+11/-0`，master YAML `+28/-0`，部署脚本
  `+51/-0`，合计 3 文件 `+90/-0`。`bash -n`、JSON 解析、YAML 等价和 NVMe target mount 门禁通过；
- 本时点尚未改变三端远端状态、停止 burner 或启动 r32，不能登记任何运行结果。

### 0.41 2026-07-20 08:54 HKT：r32 attempt1 失败、网络信号与根因门禁

- r32 三端部署哈希、r31 release/PyO3、Get32、tier1 5%、end-depth 288、128/128/256 GiB、
  metadata-only、双 HCA 和原 workload 启动门禁均通过；两 GPU owner 均 232/232 grants、
  `peer_count=2`，正式窗口 burner 为 0；
- workload 从 `00:30:58 UTC` 开始，只留下 before metrics/config/network partial files；node0/node1
  SGLang HTTP 200 日志计数=`320/329`，router 完整响应=`647`，但没有 requests/after/summary，
  runner 在写 rc 前收到人工中断。因此本轮严格标记为失败，无合法 QPS、TTFT 或命中率；
- node0 同一批 57 个 source-fenced victim 从 `00:31:49.970` 起持续 Busy，master 累计 73 个 Busy
  response batch、4104 个 Busy item outcome；owner selected/retry=`57/57`、selected bytes=
  `268959744`。node1 direct-delete `126305/126305` 全部完成，无 Busy；
- 故障期间 node0 free slots=`395–429`、pending/prepared=`0`，无 refill timeout、prefill OOM 或
  scheduler exception。`00:32:22` 起 node0 两个 TP rank 同时出现 `msg_id=4022`，最终累计 12 条
  deadline warning 和 6 次 99-key `P2P(code=608)` write-back failure；
- Greptime 离线副本确认 31997 条日志、source-fence resume=`0`、`msg_id=4022`=`12`；故障前
  master/node0/node1 Tokio max-worker peak=`5.755/3.754/7.560%`，global queue=0。stall 后 max-worker
  全低于 0.23%，故排除“57 个 retry RPC 把 actor/Tokio 队列排满”；
- r32 前 59 秒 CPU 双 HCA TX=`822.31 GB`、avg/p99/peak=
  `112.447/378.266/410.137 Gbps`；r31 相同前 59 秒为 `325.92 GB`、
  `44.566/257.317/290.312 Gbps`。r32 的早期 CPU 恢复量为 `2.52×`，是值得修复后复测的信号，
  但缺 token 结果，不能写成命中提升；timeout 后 130 秒三端各仅约 2880 B，链路几乎全空；
- 当前最强假设是 57 个 owner source fence 被 master put/get/replica/reclaim activity 长期挡住，
  local-first Put 等待该 generation 时无法返回。现有日志没有 Busy activity 分类和 wait-start 事件，
  因此具体 activity 类型仍未证明；`replica_done_terminal_replays=57` 仅保留为关联信号；
- 下一门禁先补 Busy 原因聚合、master activity/inflight gauge 和 owner wait start/end。若确认是暂时
  Busy，候选修复按单 KV 撤销 source-selection、恢复 Moka、释放 selected debt，并在仍有真实缺口时
  pop 其它 victim；不展开兄弟 KV、不恢复整组驱逐；
- 已按 workload/router/SGLang→owners→master/control 顺序清场。三机实验 session/进程/端口为 0，
  四张正式 GPU 均恢复约 `1395 MiB/100%` managed burner。初始证据复制为 104 个文件；补入最新版
  计划/总账/失败分析并生成校验清单后，最终 106 个文件、约 68 MiB 固化到
  `artifacts/e44_r32_enddepth288_attempt1_failed_20260720/`；新建
  `20260720_085408_fluxon_kv_r32_enddepth288_attempt1失败分析与下一步.md`。本轮核心源码净 diff
  仍为 `+1815/-862`，没有构建新 release。

### 0.42 2026-07-20 09:02 HKT：r32 失败 artifact 封存与延时清场复核

- artifact 已同步最新版性能计划、修改总账和 r32 时间戳失败分析；最终为 106 个文件、约 68 MiB，
  `SHA256SUMS` 覆盖其余 105 项并全部校验通过；
- 34 份 JSON/JSONL 均通过 `jq empty`，config 内 8 份 shell 均通过 `bash -n`，三份归档文档与根目录
  来源逐字节一致，`Fluxon git diff --check` 通过；本次只封存文档和证据，没有修改核心代码；
- 09:02 HKT 再次通过三条独立 SSH 链路复核 node0/node1/CPU：匹配 r32/Fluxon/SGLang/router/
  master/observer/Greptime/etcd 的 tmux、进程和实验端口均为空；node0/node1 四张 GPU 均为
  `1395 MiB/100%`，唯一 compute 进程是四个 managed `/public/zgf/.gpu_burn_script_*.py`。

### 0.43 2026-07-20 09:08 HKT：r33 Busy/activity 归因观测实现

- master direct-delete 内部结果增加非 wire 的结构化 Busy cause；每个整批日志聚合 activity Busy、
  Put/Get/replica/reclaim 命中项数、对应 inflight lease 合计及 under-fence delete Busy 数，不逐 victim
  打 master 日志，不改变一次请求/一次响应向量语义；
- `MasterKeyActivityTable` 新增只读聚合快照，30 秒 reporter 输出 active keys、各 activity key 数和
  inflight Put/Get/replica 总量；只在 reporter 周期内短暂获取现有 activity mutex；
- owner 在 `WaitForLocalAccess` 真正 await 前记录 fenced key 与 atomic batch size，结束日志继续记录
  同 key 与 wait_us；每个 Busy response batch 只输出首个 victim key/detail，可核对等待 Put 与 Busy
  victim 是否相交；
- 相对 r32 前工作树精确增量为 4 文件 `+287/-43`，最终工作树为 15 文件 `+2102/-905`（含 366 行
  未跟踪 ACK worker）。已运行 rustfmt；Cargo、定向测试和三机结果尚未执行，旧 r31/r32 结果不覆盖
  当前 r33 代码。

### 0.44 2026-07-20 09:15 HKT：r33 本地门禁通过

- `findmnt` 确认统一 Cargo target 位于 `/dev/nvme0n1p3`；`cargo check -p fluxon_kv --lib` 通过；
- activity observe、direct-delete mixed result、source-selection fence 三组定向测试各 `1 passed`；
  全量 `cargo test -p fluxon_kv --lib`=`181 passed, 0 failed`，耗时 `196.34s`；最终 rustfmt check 和
  `git diff --check` 通过；
- 首次定向命令没有设置 closed SDK loader 路径，测试二进制因缺 `libfluxon_commu_core.so` 在入口前
  rc=`127`；复用 r31 NVMe closed SDK（core SHA256=`bfa6a32d...3452503`）后全部通过。该次是环境
  启动失败，不记作代码测试失败；
- 当前仍未构建或部署 r33 release，r31/r32 三机结果不覆盖本工作树。下一门禁是隔离 release、三端
  哈希与 metadata-only patch 验证，再用 r32 的 end-depth 288/Get32/tier1 5% 原配置复跑。

### 0.45 2026-07-20 09:17 HKT：r33 隔离 release 编排完成、尚未构建

- 新增 `build_e44_r33_busy_activity_observe_release.sh` 136 行和
  `install_release_e44_r33_busy_activity_observe.sh` 74 行；构建、wheel 和 venv 均使用 r33 隔离名称；
- 构建 staging、统一 Cargo target、manylinux rootfs 均位于 `/dev/nvme0n1p3`，可用约 478 GiB；
  release manifest 额外封存本次 master/owner 归因源文件；两份脚本 `bash -n` 通过；
- 此时没有执行 build/install/deploy，没有停止 burner，也没有改变三端 release symlink。新增编排
  `+210/-0` 独立于 Fluxon 核心 `+2102/-905`。

### 0.46 2026-07-20 09:32 HKT：r33 release 构建完成与复跑配置固化

- manylinux release profile 编译耗时 `11m44s`，最终 staging 约 1.4 GiB；wheel SHA256=
  `548b956c...1208`，PyO3 SHA256=`d998fb2a...b5de`；release 自带清单、closed SDK、metadata-only
  patch、完整 source hash/diff 和 7 份关键源码快照均通过校验；
- 新增 r33 deploy 103 行、master YAML 28 行，并在 variant 增加 10 行；连同 build/install，本轮
  编排累计 5 文件 `+351/-0`。r33 与 r32 YAML 去掉隔离 `log_dir` 后完全相等；admission 仍为
  `prefix_end_depth_ratio/288`、Get32、tier1 5%，只更换观测 release/run id；
- 本地 `bash -n`、replica JSON、YAML 等价、release 固定 wheel/PyO3 hash 和四个观测 symbol 门禁
  全部通过。此时尚未传输、安装或切换三端 symlink，burner 未停止。

### 0.47 2026-07-20 09:37 HKT：r33 三机部署完成

- 部署 attempt1 在 node0 install 之前静默 rc=`1`；`bash -x` 证明 JSON grep pattern 在 SSH 外层
  双引号中丢失转义，远端实际搜索 `policy:prefix_end_depth_ratio`。release manifest、wheel、四个
  observation symbols 和 variant 本体逐项均通过，symlink 当时仍为 r31；
- 修正两处 pattern 的 `\"` 转义后，node0/node1/CPU 从头幂等部署成功。三端 wheel/PyO3/
  `libfluxon_commu_core.so`/`libfluxon_rdma_probe.so` 哈希一致，独立 r33 venv import 与 release
  symlink 通过；两 GPU metadata-only host patch 哈希=`482a276e...1c878`；
- 当前三端尚未启动 r33 服务；两 GPU 节点 managed burner 各 2 个、四卡约 `1395 MiB/100%`。
  下一步先按规约停止 burner并复核 0 残留，再启动 HCA/Greptime/control/master/owners/SGLang/router。

### 0.48 2026-07-20 09:47 HKT：r33 发流前门禁通过

- node0/node1 均先运行 burner `--no-restart` 停止路径，再按精确命令行清除残留 burner/watchdog；
  四卡启动前均为 `0 MiB/0%`，正式窗口不会混入 burner；
- 三端 HCA observer 首批复核各约 785 行、两张 HCA、`error=None`；etcd、Greptime、quoted schema、
  master、CPU owner 和 router ready，router/metrics=`200/200`；
- 两个 GPU stack 与 CPU owner 并行启动。node0/node1 均 232/232 grants、owner local reserve
  `123702607872 B` usable、owner-hot `123695058124 B`、RDMA `peer_count=2`；CPU owner segment=
  `274877906944 B` 且 transfer-ready；
- 两侧 SGLang HTTP 200，实际 cmdline 为 Get `batch_concurrency=32`、TP2、metadata-only
  `materialized_pages=1`，replica policy=`prefix_end_depth_ratio`、max pages=`288`；master 配置实证
  tier1 ratio=`0.05`，新增 `master key activity runtime` 已按 30 秒输出；
- 此时尚未发送正式请求，不能登记 QPS、命中率或 r32 闭环是否复现。下一步仅启动与 r32 逐字节
  相同的 S96×T24/c24 workload。

### 0.49 2026-07-20 10:00 HKT：r33 正式复跑失败并完成清场

- 正式 workload 使用 r33 已门禁的 Get32、tier1 5%、`prefix_end_depth_ratio/288`、
  S96×T24/c24；不是替换负载。router POST started/completed=`703/683`，最后正式响应在
  `01:49:16 UTC`，之后停止推进；runner 在写 rc/requests/after/summary 前被人工中止，所以本轮
  不存在合法 QPS、TTFT 或命中率；
- master replica target=`63200`。node0/node1 owner 的 transfers/published 分别为
  `34687/34687` 和 `28513/28513`，合计恰好 `63200`；owner active/failed 都为 0；
- master 却稳定残留 `active_keys=replica_keys=inflight_replicas=13`，Put/Get/reclaim 均为 0。
  direct-delete 共 698 批，victims/completed/retryable=`213974/213104/870`；870 项全部分类为
  replica Busy；
- node1 记录 14 次 source-fence wait、0 次 resume，涉及两个稳定 fenced key；SGLang 后续出现
  6 条 P2P 608，router 对 node1 health timeout 4 次。无 prefill OOM 或 scheduler exception；
- workload 中止后按顺序停止 router/SGLang、三位 owner、master/control、Greptime 和三端 HCA
  observer；三机实验进程、session、端口清空。node0/node1 managed burner 恢复，四卡约
  `1395 MiB/100%`。

### 0.50 2026-07-20 10:08 HKT：r33 根因由 operation identity 串代闭合

- `replica_done_terminal_replays=13` 与最终泄漏的 13 个 replica activity 精确相等；同时 owner
  已完成所有 63200 次 transfer/publish。这排除了 owner singleflight 丢任务，也把 Busy 定位到
  master completion/release 生命周期；
- 旧 `completed_replica_tasks` 仅用 `(key, put_id)`。同一个 KV generation 的远端 route 被回收后
  可以合法发起第二次 append；第二次 Start 已申请新 target 和 activity lease，但它的 Done 会命中
  第一次 append 的旧可重放终态并提前返回，导致第二次 reservation/activity 永远未完成；
- active HCA 窗 `1784512095.470–1784512156.999` 的 CPU 双卡 TX avg/p99/peak=
  `121.980/425.948/492.946 Gbps`；stall 窗 `1784512157–1784512323.900` 几乎全为零。Greptime
  global queue=0，active 窗 max-worker 峰值 master/node0/node1/CPU=
  `9.60/5.25/3.24/0.14%`。因此网络和 Tokio 排队都不是第一因果断点；
- 根目录新增 `20260720_102229_fluxon_kv_r33失败根因与r34修复复跑计划.md`，用直白流程记录
  串代机制、证据、修复和复跑门禁。

### 0.51 2026-07-20 10:14 HKT：r34 operation-scoped completion 实现与本地门禁

- master 增加单调 `next_replica_operation_id`，每次新 reservation 分配独立 ID；
  `PutAppendStartResp` 和 batch item 返回 ID，owner 的统一 `ensure_remote_put()` leader 在
  Done/Revoke 原样带回；
- completion cache 从 `(key, put_id)` 改成 `(key, put_id, operation_id)`。相同 concrete append
  的响应丢失仍可重放；旧 append 的终态不能再完成后来新建的 append；
- Start/Done/Revoke 在 per-generation 异步短锁内线性化，锁内没有数据传输；不同 key 继续直接
  并发。没有恢复 replica actor、batch actor、全局 FIFO 或第二套 singleflight；
- r33→r34 实际补丁为 4 文件 `+168/-33`：client put `+36/-16`、master mod `+42/-1`、master
  msg_pack `+11/-0`、master put `+79/-16`。容量 victim、source fence、direct-delete batch、
  tier1、Get 和 workload 均未改变；
- NVMe target=`/mnt/nvme0/mjq_build/push_sglang_fluxon_target`，位于 `/dev/nvme0n1p3`。
  operation-scoped terminal 定向测试 `1 passed`；全量 `182 passed, 0 failed`（195.06s）；
  `cargo check`、fmt、`git diff --check` 通过；
- 过程异常如实保留：首次异步测试因 Tokio 名称冲突编译失败，改为同步 cache 测试；一次错误
  `--exact` 匹配到 0 项，之后用正确测试名执行 1 项通过。尚未构建 r34 release，不能把本地门禁
  写成三机验收结果。

### 0.52 2026-07-20 10:22 HKT：r33 网络与 Greptime 证据补齐

- 使用既有 HCA analyzer 生成 full/active/stall 三份 JSON；三端原始 JSONL 各 1721 行；
- 在 NVMe 创建 Greptime DB 隔离副本并监听 `127.0.0.1:14010` 完成离线查询，生成
  `derived/greptime_summary.json` 和 `greptime_queries.sql`；随后停止副本并删除 NVMe 查询目录，
  未修改 artifact 原始数据库；
- r33 artifact 已补 README、CLEARANCE 和根因文档引用。SHA256 清单及总账副本将在 r34 构建前
  的归档收口步骤更新；当前不得把尚未完成的清单写成已校验。

### 0.53 2026-07-20 10:24 HKT：r34 独立 release 与同负载编排派生

- 新增 r34 build/install/deploy=`145/75/106` 行、master YAML=`29` 行，并在 variant 新增 11 行，
  共 5 文件 `+366/-0`；release、三端 venv、run id、namespace 和 master log 使用独立 r34 identity；
- build manifest 除 r33 既有关键源码外，新增固化 `source_master_msg_pack.rs` 和
  `source_master_put.rs`，部署时将校验 `next_replica_operation_id`、wire `operation_id` 与
  master `operation_identity` symbol；
- r33/r34 master YAML 删除隔离 `log_dir` 后结构相等；两 variant 的 Get concurrency 均为 32，
  replica JSON 字节相同且为 `prefix_end_depth_ratio/288`。tier1、容量、workload 和观测未变化；
- 三个 shell 与 variant `bash -n`、YAML parse、replica JSON 输出通过；Cargo target 和 release
  staging 父目录均由 `findmnt` 确认为 `/dev/nvme0n1p3`；
- deploy/variant 中 wheel/PyO3 暂为显式占位符，必须等 r34 构建产物计算真实哈希后通过
  `apply_patch` 回填，未回填前不得部署。

### 0.54 2026-07-20 10:40 HKT：r34 隔离 release 构建完成

- 长构建前和结束后 `findmnt` 均确认 Cargo target、rootfs、release staging 位于
  `/dev/nvme0n1p3`；统一 wheel release build 用时 11m45s，未向 Ceph `target/` 或 `/tmp` 回退；
- staging=`/mnt/nvme0/mjq_build/fluxon_e44_r34_replica_operation_identity_20260720`，约 1.4 GiB；
  wheel SHA256=`68971f37af71f09e2a3720fadd3b1358935e064e41d9da086abaa5333b23369c`，
  PyO3 SHA256=`d6bed7449ce6b5bad0c7d1514e9022065736a51dde94f5b4fb58f998e8d9f7d3`；
- cp310/cp311/cp312 ABI3 import、closed SDK、vendor runtime、metadata-only patch、完整 source diff、
  `source_master_mod/msg_pack/put/reclaim` 和 `fluxon_release.sha256` 全部通过；
- 真实 wheel/PyO3 哈希已用 `apply_patch` 回填 deploy 和 variant；占位符清零。重新执行三个 shell
  与 variant `bash -n`、replica JSON parse、source symbol 和全 release `sha256sum -c` 均通过；
- 该结果只证明可部署产物正确，尚未覆盖三端复制、独立 venv import 或正式 workload。

### 0.55 2026-07-20 10:43 HKT：r34 三端部署完成

- 三端目标路径均为
  `/storage/mjq/sglang_fluxon/releases/fluxon_e44_r34_replica_operation_identity_20260720`；统一 wheel
  SHA256 均为 `68971f37...369c`，PyO3 均为 `d6bed744...f7d3`；
- node0/node1 Python 3.10 与 CPU Python 3.12 都从各自 r34 独立 venv import；
  `libfluxon_commu_core.so`/`libfluxon_rdma_probe.so` 哈希一致，三端 symlink 均切到 r34；
- 三端 release 源码均实证 `next_replica_operation_id`、wire `operation_id` 和 master
  `operation_identity`；两 GPU metadata-only patch SHA256=`482a276e...1c878`；
- 两 GPU 共用 venv，但 deploy 按 node0→node1→CPU 串行执行，没有并发 pip 竞态；
- 部署前后均未启动 r34 服务。两侧 burner 仍各占约 1395 MiB/100%，这是预期 idle 状态；正式
  启动前必须走 `--no-restart` 停止和精确 PID 复核，不得带 burner 发流。

### 0.56 2026-07-20 10:53 HKT：r34 发流前门禁通过

- 第一次执行 `gpu_burner.sh stop --no-restart` 时共享 managed 状态再次串到另一节点，只实际
  停掉 node1；node0 两个 `/public/zgf/.gpu_burn_script_* --gpu 0|1` 和两侧 watchdog 仍在。
  本轮没有把脚本输出当成清场结论；按完整命令行精确终止后延时复核两侧
  `Watchdog is stopped`、compute burner=0、四卡=`0 MiB/0%`；
- 三端 HCA observer 已按 500ms 采样，发流前各约 800 行；etcd、Greptime 和 quoted schema、
  master、CPU owner、两 GPU stack、router 全 ready；
- node0/node1 owner segment=`137438953472 B`，local reserve 均为 grants=`232/232`、
  free slots=`26216`、usable bytes=`123702607872`；CPU owner=`274877906944 B` 且
  RDMA `peer_count=2`/transfer-ready；
- 两侧 SGLang cmdline 实证 TP2、Get `batch_concurrency=32`、metadata-only
  `materialized_pages=1`、policy=`prefix_end_depth_ratio`、max pages=`288`；master 配置实证
  `replica_writeback_tier1_capacity_ratio=Some(0.05)`；
- 两侧 SGLang 与 router health=`200`，master activity、owner remote-Put 和 capacity 临时态均为
  0；正式前 P2P 608/OOM/scheduler exception/conflict exhausted=0；
- 此时尚未发送正式请求。下一步只运行既有 S96×T24/c24 workload；不得用 readiness 请求冒充
  正式结果。

### 0.57 2026-07-20 11:01 HKT：r34 正式复跑通过

- 正式请求窗口为 `1784515980.279–1784516230.824`；workload rc=`0`，
  requests/success/error=`2304/2304/0`，QPS=`9.195981033`；
- TTFT p50/p90/p99=`1.783589/3.109419/9.585525s`，E2E=
  `2.266590/4.160731/11.477920s`；L1/L2/L3=`2.57259/0/71.38131%`，总命中
  `73.95390%`；Mooncake L2+L3 目标已超过 `3.37621pp`；
- master replica targets=`95128`；node0/node1 transfers=published=
  `41451/41451 + 53677/53677 = 95128`，active/failed=0，
  `replica_done_terminal_replays=0`；
- direct-delete requests=`751+1579=2330`，victims/completed/retryable=
  `859791/859791/0`；两侧 handoff=committed=`249230/249230`、
  `610561/610561`；selected、retry entries、debt、selected bytes、pending/in-progress 全为 0；
- master 连续多次 activity Snapshot 的 active/Put/Get/replica/reclaim/inflight 全 0；source-fence
  wait/resume、P2P 608、refill timeout、OOM、scheduler exception、Put retry exhausted 均为 0；
- CPU retained=`55341 entries / 261131599872 B`；10 次暂时 deferred reclaim 最终
  queued=completed=`10/10`。r33 的 13 个 activity lease 泄漏没有复现。

### 0.58 2026-07-20 11:12 HKT：停栈、网络复核与下一性能门禁

- 结果落盘后按 router/SGLang → 两 GPU owner/CPU owner → master → control/Greptime → 三端
  HCA observer 顺序停止；三机 r34 session/process/实验端口均为 0，四张实验 GPU 回到
  `0 MiB/0%`；三份 HCA 原始 JSONL 为 `2122/2120/2120` 个有效 sample record；
- 正式窗 HCA CPU TX avg/p99/peak=`121.076/414.030/482.982 Gbps`；CPU TX=
  `3784596977584 B`，两 GPU RX=`3784596982192 B`，只差 `4608 B`。node1/node0 RX=
  `2.534×`；链路峰值仍低于双 HCA 800 Gbps 名义容量；
- Greptime 正式窗 Tokio global queue 四角色峰值全 0，max-worker 峰值 master/node0/node1/CPU=
  `8.835/5.756/7.329/0.191%`；process CPU 最高 node1 owner 平均约 `480.74%`，没有 CPU 或
  executor 饱和证据；
- Get Start/Cancel/Transfer=`4718/466/4252`，Start-Transfer 恰为 466；Start
  mean/p90/p99=`25.875/50.749/70.976ms`。空 load-back=`226+308=534`；
- 两 GPU owner 在正式结果与归零 Snapshot 之后仍复现析构 panic，master Ctrl-C 仍有
  KeyboardInterrupt unwrap；保留为独立 lifecycle P1，不污染正式性能窗口；
- Greptime 原始 DB 已复制到 artifact；离线查询只在
  `/mnt/nvme0/mjq_build/r34_greptime_query_20260720` 隔离副本执行，查询后服务、端口和 NVMe 副本
  均删除，没有改 artifact 原始 DB；
- 当前性能门槛从“追命中”切换为“不损命中的 load-back 优化”。下一单变量先在 534 次空恢复
  观测/消除与 466 次 common-prefix handle trim 中二选一，不重试 Get64、不扩大 tier1。

### 0.59 2026-07-20 11:18 HKT：artifact 校验与 idle GPU 交接

- artifact 最终为 125 个文件、约 195 MiB；`SHA256SUMS` 覆盖其余 124 项并全部校验通过；全部
  JSON/JSONL 通过 `jq empty`，config 内 shell 通过 `bash -n`，workload/CPU owner rc 均为 0，
  `Fluxon git diff --check` 通过；
- root 分析文档与 TODO 已更新：r34 现在是正确性/性能基线，原 r32 失败计划明确降为历史；下一性能
  P0 改为 534 次空 load-back 量化/消除，P1 为 466 次 common-prefix handle trim；
- 停栈后两节点四卡曾实证 `0 MiB/0%`。执行 `/storage/zgf/gpu_burner.sh start 0,1` 时，外部
  `/storage/mjq/computing/inference_like_compute.py` 已依次占用四卡约 `8483 MiB/100%`；burner 脚本
  按门禁拒绝覆盖“非 burner compute”，watchdog 保持 stopped；
- 没有权限也没有必要为恢复 burner 杀掉该外部任务。当前 GPU 已保持 100% 利用，但不是 managed
  burner；外部任务退出后应补执行 `start 0,1`。该交接状态已写入 artifact `CLEARANCE.md`。

### 0.60 2026-07-20 11:31 HKT：r34 空 load-back 与 Get 重复 Start 细分复核

- 新建 `20260720_113123_fluxon_kv_r34空loadback与Get重复Start性能优化分析.md`（`+424/-0`）；
  同步替换 TODO 与本总账的当前口径。根目录不是 Git 仓库，两个既有文档的替换行不伪装成精确
  `+/-`；本轮没有修改 Fluxon/SGLang 运行代码，也没有产生覆盖 r34 的新实验结果；
- r34 的 534 条 `load_back produced no prefix tokens` 全部与
  `recoverable_error_kind=not_ready/read_pages=0` 一一对应，失败路径均低于 1ms；node0/node1 的
  TP0/TP1 分别为 `113/113`、`154/154`，即 267 个 TP 成对调度事件。它们不是 534 次已完成传输；
- 按 TP0 去重后，metadata 当时宣称的 host-hit tokens 为 node0/node1=
  `1211904/3227968`，合计 `4439872`；这是未验证的机会量上限，日志没有 rid 闭环，不能写成真实
  浪费或保证可恢复 tokens；
- 成功 prefetch node0/node1=`2022/2230`，均为正 token completion，合计恰好等于 4252 次 Get
  Transfer；Get Start 返回 0 仅 node0 39 次，不能解释全部 267 个 `not_ready` 事件。下一观测必须按
  rid 串起 match→prefetch decision→Start→ready→consume→terminal，并区分 threshold/rate-limit/
  no-keys/start-zero/TP-mismatch/ready-late；
- 成功 load-back 的同步 eviction 是新的关键路径证据：node0/node1 `evict_ms` mean=
  `47.189/53.313ms`、p90=`155.334/184.387ms`；`1414/4252`（33.25%）rank 次数超过 50ms，
  `1142/4252`（26.86%）超过 100ms。下一观测同时拆 already-backed、write-back、wait 和 allocator
  free；
- Get Start/Cancel/Transfer=`4718/466/4252`；其中 common-prefix retry 收敛日志为
  `352+66=418` 个 rank handle，明确可删除第二次 Start；另有 18 个 common=0 Cancel 应保留，剩余
  30 个 Cancel 待 r35 terminal reason 分类，不能把 466 全部写成用户请求或全都写成重复 Start；
- 实施顺序固定为：r35 observation-only；r36 只让 Get Transfer 消费第一次 handle 的 TP 公共前缀，
  删除 Cancel→第二次 Start；r37 再按 r35 最大主因选择 `not_ready` 或同步 eviction 单变量修复。
  Get32、tier1 5%、end-depth 288、负载、单 KV 容量 victim 和 remote Put singleflight 均保持不变。

### 0.61 2026-07-20 11:58 HKT：r35 observation-only 实现与本地门禁

- 实际运行的 SGLang hostless 源不是当前 `sglang` Git HEAD 下的同名文件，而是实验目录
  `unified_radix_cache_e44_r4.py`；修改前 SHA256=`72d3c7be...8bee`，与 r34 两 GPU 已安装文件及
  r17 固化快照完全相同。`sglang` Git 工作树保持干净；
- r35 为每个 rank 的 `rid` 建立轻量 observation：记录 threshold/rate-limit/no-keys/start-zero/
  TP mismatch/submitted/ready 等 decision，初次与重试 Start、Get Transfer、ready wait、metadata
  host-hit、ready/consumed pages/bytes及一次性 terminal；layerwise restore 使用 `req_id` 延续到 CUDA
  completion/abort，不把“已排队”冒充“已完成”；
- load-back 为同步 eviction 建立栈作用域 breakdown：requested/actual/candidate tokens、已 storage-backed
  直接回收、write-back 后回收、unbacked drop、新建/已有 write-back 数、write submit/wait、allocator
  free-group 和总耗时。所有新增均只做观测，不改变 eviction 分支或 victim 顺序；
- 相对 r34 runtime 源快照改动为 `+603/-10`；variant `+13/-0`，launch hash gate `+1/-1`；新增
  deploy/master YAML/validator=`99/28/159` 行，合计 6 文件 `+903/-11`。runtime 新 SHA256=
  `895951ad...0c27`；
- 本地 `py_compile`、AST/helper 行为测试、logger 36 个 format placeholder 对齐、runtime diff check、
  shell `bash -n`、variant JSON/Get32/end-depth288/hash 和 r34/r35 YAML 等价门禁通过；
- r35 部署脚本只复用 r34 Fluxon release/venv，部署前拒绝覆盖 live SGLang，备份 r34 runtime，安装
  后固定验证源码 hash、观测 symbol、validator、metadata-only patch 与 r34 PyO3 hash。当前尚未执行
  部署，r34 继续是唯一正式结果。

### 0.62 2026-07-20 12:04 HKT：r35 三端部署完成，正式发流等待 GPU

- 首次部署在 node0 覆盖运行源之前被门禁停止：第二段独立 SSH 未重新 source variant，venv 变量为空
  并尝试 `/bin/python`。当时 validator 已通过、r34 baseline 已备份，但 site runtime 仍保持 r34 hash；
  修复为每段 SSH 独立 source 后从头幂等部署；
- 第二次部署两 GPU 的 r35 site hash/import 已通过，但复核发现 node1 回滚备份没有落盘。部署脚本改为
  显式上传不可变 r34 artifact 快照，而非依赖首次覆盖时复制；第三次从头部署后，两端 r35 runtime=
  `895951ad...0c27`、r34 rollback=`72d3c7be...8bee`、validator、metadata-only patch、r34 PyO3
  hash 和实际 `import sglang...unified_radix_cache` 全部通过；
- CPU 节点 variant 指向 r35 独立 run/master config，但三端 `fluxon_release` 与 GPU/CPU venv 全部继续
  指向 r34；r34/r35 除 run id、master log_dir 和 SGLang source hash 外，全部 `E44_PERF_*` 行为变量
  无 diff；
- 三机当前没有 r35/r34 SGLang、owner、master 或 router。两 GPU 节点的四张卡仍被外部
  `/opt/conda/bin/python` 各占约 `8483 MiB/100%`，已运行约 51 分钟；这不是 managed burner，不能
  擅自杀掉。故当前只完成部署，不启动实验，也没有新 QPS/命中结果。

### 0.63 2026-07-20 13:38 HKT：r35 observation-only 实测、定位与停栈

- 用户明确授权在测试前停掉外部 GPU 计算。已精确终止两节点四卡的
  `inference_like_compute.py`，确认四卡 `0 MiB/0%` 后才启动 r35；负载与 r34 同为
  S96×T24、2304 请求、concurrency 24、Get32、tier1 5%、end-depth 288、metadata-only
  128/128/256 GiB。
- workload rc=0，`2304/2304/0`；QPS=`9.733413099`，TTFT p50/p90/p99=
  `1.716768/3.097042/4.897846s`，E2E p50/p90/p99=`2.171524/3.956332/6.072025s`；
  L1/L2/L3=`3.84578/0/69.29157%`，总命中=`73.13735%`。相对 r34 QPS `+5.84%`，但 L3
  `-2.08974pp`、总命中 `-0.81655pp`，且 CPU→GPU 物理读取少约 `194.34 GB`；因此不将
  QPS 差异当成 observation 优化收益，r34 继续是正式基线。
- lifecycle 流量闭合：prefetch submit/Get Transfer/ready/init-load/DMA complete 全为 `4286`；
  Get Start=`5258` = initial `4340` + retry `918` = Transfer `4286` + Cancel `972`。478 条空
  load-back 完整分解为 130 条真无 ready、61 条已成功但终态被后续尾巴尝试覆盖、287 条
  consumed 后残余尾巴尝试。原表面 `83.14 GB ready-not-consumed` 是 `(rid, rank)` 观测
  identity 覆盖，不是真实物理传输浪费。
- 4225 条可靠 consumed 终态的 eviction 累计 `239499.848ms`，free-group 累计
  `218309.579ms`，占 `91.15%`；`1439/4225` 次超过 50ms。实际驱逐
  `69950016 tokens`，其中 `68340352` 已 backed，新写回后驱逐仅 `1609664`，即
  `97.699%/2.301%`。下一 P0 是拆 allocator cat/divide/unique/append，而不是扩大写回并发。
- 容量闭环：direct-delete requests node0/node1=`1537/656`，victims/completed/retryable=
  `817102/817102/0`；handoff/committed=`624174/624174 + 192928/192928`；owner selected/
  retry/debt/pending 和 master activity/inflight 全归零；CPU retained=`55329/261074976768B`。
  replica targets=`91997`，owner transfers/published=`91997/91997`，terminal replay=0。remote-Put active=0，
  但累计 failed=`487+11`，作为未归因 TODO 保留。
- Greptime/HCA 正式窗 CPU 双 HCA TX avg/p99/peak 约=`121.43/361.55/391.08Gbps`；
  HCA 导入 `9936` 行，error=0；CPU TX 与两 GPU RX 守恒差值在 observer 计数边界范围内。
  Tokio global queue 四角色峰值均为 0，继续不支持“扩 Get 并发”。
- 发流后工具/文档账：新增 `analyze_e44_r35_loadback_lifecycle.py` 418 行；新增 artifact
  README/CLEARANCE/capacity summary=`74/13/75` 行；生成 load-back/HCA/Greptime JSON 共 2882 行（不含
  手工归纳的 75 行 capacity summary）。根目录三份当前文档相对 artifact 内 12:04 HKT
  快照的精确 diff 分别为：分析文档 `+117/-23`、TODO `+41/-5`、本总账在本条写入前
  `+44/-6`；本条自身是后续账目，不回填伪造自包含 diff。
- refill timeout、P2P 608、prefill/CUDA OOM、scheduler exception、Put retry exhausted 全为 0。正式窗后
  router/SGLang、三 owner、master/control、Greptime 与三端 observer 已停止，四卡当时确认回到
  `0 MiB/0%`。13:38 HKT 尝试恢复 managed burner 时两 GPU 节点 2222 端口均超时；未能复核
  现态，不写成已恢复。
- r35 artifact 最终约 199 MiB，`SHA256SUMS` 覆盖其余 126 个文件，`sha256sum -c`
  全部通过；分析器从两份原始 SGLang 日志重算的 JSON 与 artifact 中
  `loadback_lifecycle_summary.json` 逐字节一致。

### 0.64 2026-07-20 14:22 HKT：四方向建档与 r36 descriptor cap 实现

- 按用户要求建立 `20260720_140543_fluxon_kv四方向逐项性能优化与实验追踪.md`，固定数据恢复、
  节点偏斜/churn、Get 控制冗余、Remote Put 空转四个方向及 r36–r39 串行门禁。free-group 是通用
  allocator 专项，不混入四轮 Fluxon 单变量；
- 新增 `analyze_e44_r35_restore_pipeline.py`，按每个 node/TP 的单 background executor FIFO 对齐
  submitted/background，再用 operation 携带的 submit 终态归组 completion。2710 batches、4286
  operations、1,193,596 pages、76,390,144 tokens 全部闭合；分析 JSON 写入 r35 artifact 的
  `derived/restore_pipeline_summary.json`；
- r35 background submit mean/p50/p90/p99=`30.930/18.297/56.684/198.347ms`。1/2 operations
  submit mean=`16.976/34.141ms`，仍近似线性；3/4/5/6 operations 为
  `69.931/110.830/147.441/224.532ms`，分别是单 operation 线性外推的
  `1.37/1.63/1.74/2.20×`。pages→submit Pearson=`0.9277`，dispatch→submit 只有 `0.0175`；
- r36 因而不拆 logical restore batch，不改 stream/event/operation。只增加默认关闭的
  `SGLANG_FLUXON_HOSTLESS_DMA_MAX_DESCRIPTORS_PER_CALL`，r36 设 1152；超过上限时在同一 layer
  内连续切 raw descriptor view，所有 chunks 成功后才 `complete(layer_id)` 和打开 guard；
- 新 validator 用 2 layers×10 descriptors、cap=4 验证每层严格 4/4/2、无丢失/重排、同步与后台
  路径都只发布一次 layer completion。Python compile、r35 validator、r36 validator 均通过；
- variant 默认 cap=0，仅 r36=1152；GPU launcher 显式 export 并传入 tmux。r36 YAML 除隔离
  `log_dir` 外与 r35 完全相等；deploy 固定 r34 release/PyO3、r35 rollback source、r36 source hash，
  并上传真实 GPU uncapped/cap1152 数据微基准；
- 相对 sealed r35 的实验源/编排/工具净 diff 为 8 文件 `+1183/-13`：runtime `+68/-13`、
  variant `+14`、launcher `+2`，新 analyzer/validator/benchmark/deploy/YAML=
  `576/212/177/106/28` 行。追踪文档另 251 行，生成 JSON 单独记录；
- 14:20 HKT 三节点重新连通。两侧 managed watchdog 已 stopped；四卡上各有一个外部
  `inference_like_compute.py`，按本轮实验授权精确终止后，14:22 HKT 四卡均为 `0 MiB/0%`。
  本条写入时尚未部署 r36、未运行 GPU 微基准或正式 workload，不登记任何性能收益。

### 0.65 2026-07-20 14:28 HKT：r36 三端部署与四卡真实 H2D 微基准

- r36 deploy 三端通过。两 GPU site runtime=`c53cd68b...c63572f`，不可变 r35 rollback=
  `895951ad...70c27`；三端继续指向 r34 release，PyO3=`d6bed744...9f7d3`。r35 lifecycle validator
  和 r36 descriptor chunk validator 在两 GPU 节点均通过；
- 两节点四张空闲 H100 分别使用独立 worker thread/worker-owned stream，36 layers、K/V 各
  64 KiB/page、预热 1 次+正式 3 次，比较 uncapped 与 cap1152 的 288/576/864 pages。四卡 K/V
  抽样数据校验全部通过；288/576 pages 未超过 cap，保持每层一次 call；864 pages 由一次切为两次；
- 864 pages、3.797 GiB 时，四卡 uncapped/cap 的 submit mean 平均为
  `46.566/47.977ms`（cap `+3.03%`），total mean 为 `74.967/74.753ms`（cap `-0.28%`）。
  各卡 total 都没有明显退化，但 cap 也没有降低 host submit；
- 288/576/864 pages 的 total 约为 `25/50/75ms`，随实际复制 bytes 近似严格线性。由此修正
  pre-r36 判断：r35 大 batch 的 `submit_cpu_ms` 包含 copy-engine/backpressure 等待，不能全算作
  Python/CUDA descriptor 解析开销；
- 微基准只放行一次原 2304 请求端到端裁决，不支持继续扫 576/2304 等 cap。若 r36 QPS/TTFT
  无稳定改善，将回退 cap=0，并把方向 1 结论定为“物理 H2D 为主”，随后进入方向 2 的重复
  bytes/churn 量化。

### 0.66 2026-07-20 15:37 HKT：r36 端到端 no-go、回退与清场

- 原 S96×T24、2304 请求、concurrency 24、Get32、tier1 5%、end-depth 288、
  metadata-only 128/128/256 GiB 固定负载完成 `2304/2304/0`；QPS=`2.932363`，
  TTFT p50/p90/p99=`5.220/17.713/23.523s`，L3=`57.44340%`。相对 r34 QPS 下降
  `68.11%`、L3 下降 `13.93791pp`，不是可归因为波动的小幅差异；
- cap 没有减少物理 bytes，却把 DMA API calls 从当轮无 cap 等价的 `92232` 增至
  `112248`。restore p90/p99 为 `706.944/1127.598ms`，load-back ready wait mean/p90 为
  `3618.8/9242.1ms`，free-group mean/p90 为 `164.36/442.48ms`；形成
  `更多 DMA calls → restore 长尾 → ready 等待 → slot/free-group 变慢` 的反馈链；
- CPU 双 HCA TX avg/p99/peak=`26.772/230.061/282.765Gbps`，fabric 没有持续饱和。
  direct-delete `629579/629579/0`，remote-Put targets/transfers/published=`110284/110284/110284`，
  容量和发布闭环成立；
- 候选 runtime `c53cd68b...c63572f` 已从两 GPU site 回退，active source 为预先封存的
  r35 `895951ad...70c27`。全栈、observer 和归档 Greptime 已停止，Fluxon release 保持 r34。
  descriptor cap 保留为历史 no-go 证据，不继续扫参，r38 不得从它派生。

### 0.67 2026-07-20 16:15 HKT：r37 session/turn/content churn 量化与方向 2 关闭

- 新增 572 行 `analyze_e44_r37_restore_churn.py`，用 request id 将两节点 request metrics
  与 restore lifecycle 对齐，并在每个 TP rank 上按相同 `(runtime radix node id, tokens)`
  统计重复物理读取。该 identity 在 node split 后可能变化，所以重复比例是保守下界；
- r34/r35/r36 逻辑 restore tokens=`38435776/38195072/33019904`，重复比例分别为
  `93.8321%/93.6913%/89.1103%`。三轮 96 sessions 均在同一节点完成 24 turns，
  session 切换全部为 0；节点 session 分布依次为 `45/51`、`51/45`、`45/51`，
  偏斜方向会反转；
- r35 的可归因重复全部为 same-session，cross-session=`0`。turn 2 起重复比例已为
  `82.23%`，turn 4 后通常在 `97%–99%`。这与 round-barrier 负载下 GPU L1 无法保留全部
  活跃 session 工作集一致；每次 restore 后都有请求消费；
- 方向 2 因此裁决为“无可保留策略补丁”。不实现刚恢复 pages 保护，因为它只会将驱逐
  转移给其他 session；不做静态 router 均衡，因为没有稳定的节点偏置。r37 不发流，
  不改行为代码，直接转入 r38 消除 common-prefix 第二次 Get Start。

### 0.68 2026-07-20 16:18 HKT：r36/r37 artifact 最终完整性闭环

- 将最新四方向追踪文档、本总账、572 行 r37 分析器和 16860 行分析 JSON 固化到
  `artifacts/e44_r36_restore_dma_descriptor_cap1152_enddepth288_netobs_no_go_20260720/`；
- 目录最终共 137 个文件、约 227.4 MiB。`SHA256SUMS` 包含除自身外的 136 个文件，
  重新生成后 `sha256sum -c SHA256SUMS` 全部通过；
- 该 artifact 同时封存 r36 no-go 的 results/三机日志/request metrics/HCA/Greptime DB/
  微基准/容量闭环/候选与回退源，以及 r37 “无策略补丁”的跨轮只读证据。

### 0.69 2026-07-20 17:52 HKT：r38 实现、本地门禁与隔离 release

- r38 在 Python 公共接口、PyO3、external client 和 owner wire 上统一增加
  `consume_prefix_len`。TP 保留第一次 Get handle，common>0 直接 Transfer 公共前缀；OwnerRpc 在原
  handler 内 drop tail，InlineLocal 将 tail holding IDs 送入既有 1ms/1024 项 ACK 合批队列；
  common=0 仍 Cancel。没有改变 KV key、`atomic_batch`、单 KV victim 或 remote-Put singleflight；
- SGLang 实验源从 sealed r35 派生，不含 r36 descriptor cap；SHA256=
  `8d1b497fd35ef563e792f6195ca502b67b17e4afd2cfc79f8db0b1846236a5da`，相对 r35
  `+32/-116`。Fluxon 相对 16:15 Snapshot 的可精确代数变化为 8 文件 `+376/-101`；当前最终
  tracked 净 diff 仍为 19 文件 `+2254/-1013`，加 366 行未跟踪 ACK worker 为
  20 文件 `+2620/-1013`；
- NVMe target 已确认在 `/dev/nvme0n1p3`。两个 cargo check、3 组新增定向测试、全量
  `cargo test -p fluxon_kv --lib`=`184 passed, 0 failed`、r35/r38 validators、Python compile、
  fmt 与 diff check 全通过；
- 隔离 release 位于
  `/mnt/nvme0/mjq_build/fluxon_e44_r38_get_prefix_reuse_20260720`。unified wheel SHA256=
  `a1b94706ea660adba33fc22528af6b2aedb2732357025b59f342c1fa2101344e`，内嵌 PyO3 SHA256=
  `3e5b9d41af89357d57f09664a4029ef5c12b189b32d53cc8f58fd19c14537ac2`；closed SDK、ABI3
  cp310/cp311/cp312 import、31 项 release manifest、工作树 diff 和审计源快照全部通过；
- 部署前逐脚本 `bash -n` 发现 r38 deploy 的远端命令字符串有 7 处内部双引号未转义；在任何
  `ssh/scp` 执行前修正，最终 build/install/deploy/variant/launch/workload 脚本均逐个通过语法检查。
  该修复不改变行数和实验行为，只保证哈希/variant 断言确实在远端 shell 中执行；
- 该时点只完成本地构建。三端仍为 r34 Fluxon release、两 GPU active SGLang 仍为 sealed r35；
  两 GPU 节点外部 `inference_like_compute.py` 仍占四卡约 `8483 MiB/100%`。尚未部署、尚未停止
  外部占卡、尚未发流，因此没有可登记的 r38 性能结果。

### 0.70 2026-07-20 17:59 HKT：r38 三端部署与独立回读

- node0/node1/CPU 三端均完成 release manifest、r35 observation validator、r38 prefix-reuse
  validator、隔离 venv import 和 closed-runtime 哈希门禁；部署脚本 rc=`0`；
- 三端 `fluxon_release` 独立回读均指向
  `/storage/mjq/sglang_fluxon/releases/fluxon_e44_r38_get_prefix_reuse_20260720`，wheel 均为
  `a1b94706...1344e`，PyO3 均为 `3e5b9d41...37ac2`；两 GPU active SGLang runtime 均为
  `8d1b497f...236a5da`，metadata-only host patch 均为 `482a276e...1c878`；
- 部署前后均未启动 SGLang 或实验栈。node0 外部计算 PID=`28596/28748`、node1=
  `52219/52386`，分别使用 GPU0/GPU1；四卡仍为约 `8483 MiB/100%`。本条只验收部署，不把
  外部计算窗口混入实验；下一步必须停止 burner/watchdog 和这些进程，延时确认四卡
  `0 MiB/0%` 后才启动 r38。

### 0.71 2026-07-20 18:08 HKT：r38 正式启动前 GPU 清场

- node0/node1 的 `gpu_burner.sh status` 均确认 watchdog 已停止，四卡由非 burner workload 占用；
  先执行 `stop 0,1 --no-restart` 清除 managed 恢复状态；
- 清场前 node0 的两个 inference 父进程 PID=`28596/28748`、进程组=`28569`，node1 父进程
  PID=`52219/52386`、进程组=`52179`。每个父进程各有一个 `multiprocessing.resource_tracker`
  和一个实际占卡的 `multiprocessing.spawn` 子进程；四个 compute 子进程各使用约 8474 MiB；
- 对两个精确进程组先发 TERM，等待 5 秒后对残留发 KILL。即时及 12 秒延时复核均为：两侧
  watchdog stopped、burner/inference/multiprocessing compute PID=0、四卡 `0 MiB/0%`；
- 此时仍未启动 r38 服务或发送请求。下一门禁是启动全栈并验证实际容量、Get32、tier1 5%、
  end-depth 288、metadata-only、peer/grant、HTTP 与 fatal=0。

### 0.72 2026-07-20 18:22 HKT：r38 全栈启动门禁

- 三端 HCA observer 以 500ms 间隔持续采样，最新样本均 `error=null`；etcd、Greptime 和三张
  quoted-schema 表已就绪，随后启动 r38 master；
- 两个 GPU owner 并行启动并自然形成 peer 集合，没有手工创建 shared.json。两侧均为
  `137438953472` bytes、`232/232` grants、`26216` free slots、pending=0、peer_count=2；CPU owner
  wrapper rc=0，segment/shared.json 均为 `274877906944` bytes；
- 两侧 TP2 SGLang 均 HTTP 200，router HTTP 200。metadata-only HostKV 每个 TP rank 都是
  `materialized_pages=1`；实际配置为 Get32、tier1=`0.05`、`prefix_end_depth_ratio/288`，两侧
  r38 runtime/hash 门禁保持不变；
- 启动日志中 refill timeout、P2P 608、CUDA OOM、scheduler exception、retry exhausted、panic 和
  fatal 均为 0。`openai_harmony` 缺失只使未使用的 Responses API 初始化跳过；chat completion 预热
  和 health 均成功，不属于本轮 fatal；
- managed burner/watchdog 和 `inference_like_compute.py` 没有被重新拉起，四卡 compute 进程均为
  预期 SGLang scheduler。此时尚未发送正式 2304 请求。

### 0.73 2026-07-20 18:47 HKT：r38 attempt1 adapter 集成失败与停栈

- 使用与 r34/r35 相同的固定 S96×T24、2304 请求、concurrency 24 负载。workload rc=`0`、
  `2304/2304/0`，但 QPS=`3.954037`，TTFT p50/p90/p99=
  `3.75184/5.97531/11.48989s`，L1/L2/L3=`0/0/0`；该结果不具备性能比较资格；
- 初始 Get Start=`4296`、retry Start=`0`、Cancel=`4296`。74 次 zero-transferable、120 次
  rate-limit；其余 4222 次都在 SGLang storage adapter 报
  `HiCacheFluxon.get_transfer() got an unexpected keyword argument 'consume_prefix_len'`。
  owner 没有收到对应 Transfer，实际 Transfer/ready/DMA=`0/0/0`；
- 根因是 `unified_radix_cache.py` 已按新接口传参，但隔离 r38 只封存和部署了该文件，没有同步派生
  `HiCacheFluxon` adapter。已有 validator 只检查调用侧 AST，release/deploy 又固定接受旧 adapter
  hash，因而跨模块接口缺口未被门禁发现；底层 Fluxon prefix-consume 逻辑尚未被真实流量验收；
- 正式窗口 `1784543057.9503927–1784543640.6435392` 三端各有 1164 个有效 HCA interval，
  sample error=0；CPU TX avg/p99/peak=`49.810/312.250/374.610 Gbps`，CPU TX 与两 GPU RX
  总字节仅差 `53856B`。由于 load-back 为 0，这些流量仅能解释为 write/backing，不能用于评价
  Get 数据面的优化效果；
- workload 后已按顺序停止 router/SGLang、三位 owner、master/control 和 observer，实验
  session/进程/端口及 inference 进程为 0。四卡先确认 `0 MiB/0%`，随后仅为空闲保卡恢复 managed
  burner/watchdog，约 `1395 MiB/100%`；
- 下一门禁：先封存 attempt1 全证据；给 adapter 增加 keyword-only `consume_prefix_len=None` 并
  原样透传，将其加入隔离源、release manifest、三端部署 SHA256 和真实跨模块调用测试。任何 smoke
  或 attempt2 前必须停止 burner/watchdog，并清除全部 `inference_like_compute.py` 父子进程；延时
  确认四卡 `0 MiB/0%`。smoke 必须看到非零 Transfer/ready 且无 TypeError 才可正式发流。

### 0.74 2026-07-20 18:57 HKT：r38 attempt1 失败现场归档闭环

- artifact=`artifacts/e44_r38_get_prefix_reuse_attempt1_failed_20260720/`，共 126 个文件、
  约 294 MiB；`SHA256SUMS` 覆盖其自身之外的 125 个文件，`sha256sum -c` 全部通过；
- 已封存固定 workload 全目录、node0/node1/CPU 日志、两端 request metrics、三端原始 HCA、
  Greptime DB、正式窗与 lifecycle 分析 JSON、attempt1 实际旧 adapter/unified runtime、编排脚本、
  release manifest、README 和清场证据；
- 归档发生在修改 adapter/variant/build/deploy 之前，因此能精确重建 attempt1 的失败调用契约；
  后续修复文件不得回写或覆盖该目录。当前下一步仅为 adapter 透传和跨模块门禁，不改变 Fluxon
  Rust、单 KV 容量语义、`atomic_batch` 或 remote-Put singleflight。

### 0.75 2026-07-20 19:06 HKT：r38 adapter 修复与本地跨模块门禁

- 从 attempt1 artifact 中封存的 SHA256=`776d990f...d0e9e` adapter 精确派生隔离源
  `hicache_fluxon_e44_r38_get_prefix_reuse.py`。唯一运行时行为变化是给
  `HiCacheFluxon.get_transfer()` 增加 keyword-only `consume_prefix_len=None`，并连同原有
  `concurrency` 原样传给 `self.store.get_transfer()`；新 SHA256=`b2d34b0f...afb27e`；
- variant 新增 adapter expected hash，默认仍为旧 hash，只有 r38 case 覆盖为新 hash；共同 GPU
  launcher 从硬编码旧 hash 改为校验 variant 值，因此历史 variant 的运行时边界不变；
- build 将 adapter、validator 和 real-call smoke 纳入 release manifest；deploy 同时校验 release、
  remote experiment 和 active site 三处 adapter hash，安装后用真实 imported
  `HiCacheFluxon.get_transfer` + recording store 验证显式前缀、默认 None 和 keyword-only 三条契约；
- 扩展 validator 同时检查 radix 调用侧与 adapter 被调侧 AST。本地 Python compile、静态 validator、
  四个 shell `bash -n`、r38/旧 r28 variant hash 回读和 diff check 已通过；尚未重新 build/deploy，
  更未用真实 Fluxon handle 验证 Transfer/ready；
- 相对 attempt1 封存配置，7 个实现/门禁文件合计 `+165/-6`。分项为 build `+13/-0`、deploy
  `+12/-2`、variant `+2/-0`、launcher `+1/-1`、validator `+61/-1`、adapter 行为 diff
  `+11/-2`、新增 smoke 65 行。Fluxon core 没有新增变化。

### 0.76 2026-07-20 19:20 HKT：r38 adapter 隔离 release 重建

- 构建前确认 Cargo target、manylinux rootfs 和 release staging 均位于 `/dev/nvme0n1p3`；NVMe
  可用空间约 462 GiB，没有回退到 Ceph 或 `/tmp`；
- 新 release 仍位于 `/mnt/nvme0/mjq_build/fluxon_e44_r38_get_prefix_reuse_20260720`。
  unified wheel SHA256=`66566ba1f0034205fb53fce35f3684080520103bb0832cd9d271939c2a1d0b1c`，
  PyO3 SHA256=`3e5b9d41af89357d57f09664a4029ef5c12b189b32d53cc8f58fd19c14537ac2`，
  adapter SHA256=`b2d34b0fa045a24f632f626bfdf8dc776045d90c791023765e9557ab03afb27e`；
- closed SDK、ABI3 cp310/cp311/cp312 import、原有源码审计件以及新增 adapter/validator/real-call
  smoke 全部进入 release manifest 并校验通过；构建只有既有 warning，无新 error；
- attempt1 旧 wheel=`a1b94706...1344e` 与新 wheel 各含 79 个 ZIP entry；逐 entry 解压内容
  SHA256 清单完全相同。文件级 wheel hash 的变化来自重打包容器元数据，不是 Fluxon core 或 Python
  payload 变化。部署脚本已更新为新 wheel hash；当前尚未部署远端。

### 0.77 2026-07-20 19:24 HKT：r38 adapter 部署前 burner/inference 硬清场

- 第一次在两节点执行 `gpu_burner.sh stop 0,1 --no-restart` 后，node0 burner 已停但 watchdog
  仍在；node1 的旧 `/public/zgf/.gpu_burn_script_job...` 被当前 `/storage/zgf` 管理脚本误判成
  非 burner，两个 burner 与 watchdog 仍存活。门禁据此失败，没有部署或启动测试；
- node1 残留 PID=`9591/9894/10037` 全属于独立 PGID=`9399`；逐项确认该组只有 GPU0/GPU1
  burner、watchdog 及其 sleep 子进程后，精确终止该进程组。node0 watchdog 也已停止；
- 15 秒延时复核 node0/node1：burner/watchdog、`inference_like_compute.py`、resource tracker、
  multiprocessing compute PID 均为 0；四卡均为 `0 MiB/0%`，NVIDIA compute process 为空；
- 该状态放行三端部署及 adapter real-call smoke，但尚未启动 Fluxon/SGLang 服务。正式负载前还要
  再做一次同口径复核，测试结束后也必须再次清场。

### 0.78 2026-07-20 19:29 HKT：r38 adapter 三端部署与 installed-module smoke

- deploy rc=`0`。node0/node1/CPU 三端 release symlink 均指向同一 r38 隔离目录，wheel
  SHA256=`66566ba1...d0b1c`；GPU Python 3.10 与 CPU Python 3.12 的 PyO3 均为
  `3e5b9d41...37ac2`，独立 venv import 路径均落在 r38 目录；
- 两 GPU active SGLang site 的 adapter SHA256=`b2d34b0f...afb27e`，radix SHA256=
  `8d1b497f...236a5da`。release、remote experiment 和 active site 三处 hash 门禁均通过；
- 两 GPU 节点均从真实 installed SGLang module import `HiCacheFluxon`，用 recording store 调用
  其未绑定方法；显式 `consume_prefix_len=7` 原样透传、默认 None 保持旧行为、位置参数被拒绝三项
  全通过。该 smoke 验证 adapter 调用契约，但不冒充真实 owner Transfer；
- 部署和 smoke 后没有启动 Fluxon/SGLang 服务。两端实验进程/inference/burner/watchdog 仍为 0，
  四卡仍为 `0 MiB/0%`。下一步需启动隔离全栈并用少量真实请求看到非零 Transfer/ready，才放行
  attempt2 正式 2304 请求。

### 0.79 2026-07-20 19:32 HKT：r38 真实 Transfer smoke 编排

- 新增 35 行 `run_smoke_e44_r38_real_transfer.sh`，复用正式 r38 variant、模型、system 8192、
  output 8、concurrency 24、session-stream 和 96 个 active sessions；只把 turns 从 24 缩为 2，
  共 192 请求，以超过单节点 200k-token L1 工作集并触发真实写入、驱逐和回读；
- smoke 使用独立 run tag、namespace、结果目录，不作为 QPS 基线，也不替代正式 S96×T24；部署
  脚本已将其纳入远端拷贝和 `bash -n` 门禁，本地/远端 SHA256 均为
  `16557d0d...83356`；
- 相对 attempt1 封存配置的当前编排/修复净变化更新为 8 文件 `+203/-7`。新增 runner 和 wheel
  hash 更新不改变 Fluxon core 或正式性能参数；当前服务仍未启动、四卡仍为 0。

### 0.80 2026-07-20 19:37 HKT：inference 回生拦截与 r38 guarded GPU launcher

- 准备启动 smoke 时重新检查发现 node0 inference 父 PID=`62679/62831`、PGID=`62652`，
  node1 父 PID=`27408/27560`、PGID=`27381`；每个父进程均带 resource tracker 和实际占卡的
  multiprocessing spawn 子进程。它们在 19:30 HKT、上次清场约 6 分钟后自动回生；
- 当时只因同一预备命令启动了 control/master；GPU owner、SGLang、router 和 workload 均未启动。
  门禁没有把该状态放行。随后停止 control/master，精确 TERM/KILL 两个 inference 进程组；15 秒后
  四卡恢复 `0 MiB/0%`，实验 session/端口清零；
- 新增 43 行 `launch_gpu_e44_r38_guarded.sh`：只接受 r38 variant，并在 exec 共同 launcher 前
  拒绝任何 burner/watchdog/inference、任何 NVIDIA compute PID，以及 GPU0/1 任一非
  `0 MiB/0%`。提供 preflight-only 模式用于不启动服务的门禁验证；
- 两节点脚本 SHA256=`bac3f75f...256d0`，本地/远端 `bash -n` 与 preflight-only 均通过；deploy
  已纳入脚本复制和语法门禁。当前相对 attempt1 配置更新为 9 文件 `+248/-7`。

### 0.81 2026-07-20 19:43 HKT：r38 adapter 修复版 smoke 全栈启动门禁

- 第二次启动前两节点 preflight-only 再次通过；control/master ready 后，node0/node1 guarded
  launcher 并行执行其自身的第二次硬检查，均放行，CPU owner 同步启动；
- 两 GPU owner 均贡献 `137438953472` bytes，local reserve=`232/232` grants、pending=0、
  peer_count=2；CPU owner=`274877906944` bytes、peer_count=2。两个 GPU owner 自然形成
  shared.json，没有手工伪造或顺序启动绕过；
- 两侧 TP2 SGLang 和 router HTTP=200。每个 TP rank 的 metadata-only HostKV
  `materialized_pages=1`；实际参数 Get concurrency=32、tier1=5%、
  `prefix_end_depth_ratio/max_replica_pages_per_batch=288`；active adapter/radix hash 未变；
- 启动后两节点 burner/watchdog/inference 仍为 0，NVIDIA compute 只有预期 SGLang scheduler；
  owner/SGLang/CPU 启动日志的 adapter TypeError、refill timeout、P2P 608、OOM、retry exhausted、
  scheduler exception 和 panic 合计为 0。当前尚未发送 96×2 smoke 请求。

### 0.82 2026-07-20 19:47 HKT：r38 真实 Transfer smoke 通过

- 独立 tag/namespace 的 S96×T2 smoke rc=`0`、`192/192/0`，wall=`28.919s`；L1/L2/L3=
  `4.8593/0/37.5958%`，总命中=`42.4551%`。QPS=`6.639146` 只作 smoke 完整性记录，
  不与正式 S96×T24 比较；
- node0/node1 `HiCacheFluxon.get_transfer` success=`90/76`，`terminal=load_back_consumed`=
  `90/76`，positive ready=`90/76`；background DMA batches=`70/30`，其中 operations 累计=
  `90/76`。四组总数精确闭合为 `166`，样例 ready bytes 与 consumed bytes 对齐；
- 两侧 `unexpected keyword argument consume_prefix_len`、`retry_count>0`、refill timeout、P2P 608、
  OOM、retry exhausted、scheduler exception、panic 均为 0；运行期间 burner/watchdog/inference
  仍为 0；
- 本短轮未出现 TP transferable 长度不一致，`reusing first handle for TP common prefix` marker=0。
  因此它只放行 adapter→Fluxon→ready→DMA 的真实数据路径，不验收 r38 消除第二 Start 的核心性能
  假设；该项必须由原固定 2304 请求 attempt2 产生 mismatch 样本并裁决；
- 当前全栈仍运行但不会直接续跑正式负载。必须先封存 smoke、完整停栈、清空四卡/进程和 runtime
  状态，再从 clean start 重启 attempt2。

### 0.83 2026-07-20 19:51 HKT：r38 smoke 归档与正式轮清场

- smoke artifact=`artifacts/e44_r38_adapter_real_transfer_smoke_passed_20260720/`，共 98 个文件、
  约 143 MiB；`SHA256SUMS` 覆盖自身之外 97 个文件并全部校验通过；
- 已封存 192 请求原始结果、三机日志、两端 request metrics、Greptime DB、实际 adapter/radix、
  guarded launcher、runner、variant/master config、release 关键快照、README 和清场证据；
- 随后按 router/SGLang → 两 GPU owner与 CPU owner → master → control/Greptime 顺序停栈。
  延时 12 秒复核三机 r38/control session、实验进程和端口均为 0；两 GPU 节点
  burner/watchdog/inference 为 0，四卡 `0 MiB/0%`、NVIDIA compute process 为空；
- 正式 attempt2 必须重新启动 control/master/owners/SGLang/router 和 Greptime，不得复用 smoke
  cache、共享内存、metadata 或观测 DB。guarded launcher 在正式启动前会再次执行硬门禁。

### 0.84 2026-07-20 20:00 HKT：r38 attempt2 clean 启动最终门禁

- 正式启动前再次通过两端 guarded preflight，并清除已归档 smoke 的 request-metrics 和混合 master
  service log；三端 500ms HCA observer 先启动，control 重新创建 etcd/Greptime 数据目录和 quoted
  schema，随后 clean 启动 master、三 owner、两套 TP2 SGLang 与 router；
- 两 GPU 节点 HTTP 200、local reserve 232 grants、metadata-only 每侧 2 ranks、Get32、tier1 5%、
  end-depth288、adapter/radix hash 全部通过；启动 fatal/TypeError=0，burner/watchdog/inference=0，
  compute process 只有预期 SGLang；
- CPU owner etcd member/transfer-ready、256 GiB shared segment 和 peer_count=2 均通过；router HTTP=200，
  master 实际 tier1=`Some(0.05)`；
- 最终 HCA node0/node1/CPU 已分别采集 `790/793/794` 行，最新两个 HCA 均 `error=null`。
  初次聚合断言因 JSON 空格和 CPU 日志尚未 flush 提前退出，逐项核对后修正口径并重跑全部通过；
  这不是 runtime 故障。当前仍未发送正式 2304 请求。

### 0.85 2026-07-20 20:09 HKT：r38 attempt2 正式结果与初步裁决

- 固定 S96×T24、2304 请求、concurrency 24、system 8192、output 8、session-stream workload
  rc=`0`、`2304/2304/0`，wall=`254.393s`；QPS=`9.056841940`；TTFT p50/p90/p99=
  `1.851503/3.172765/9.434473s`，E2E=`2.317365/4.136392/11.364824s`；
- L1/L2/L3=`3.40653/0/69.47993%`，总命中=`72.88646%`。相对正式 r34，QPS
  `-1.5130%`、L3 `-1.90138pp`、总命中 `-1.06744pp`；这不是端到端性能提升；
- 两侧 adapter Get Start/Transfer/Cancel=`4262/4134/128`，精确满足
  `Transfer + Cancel = Start`。394 次日志明确进入“reuse first handle for TP common prefix”，
  retry Start 与 lifecycle `retry_count>0` 均为 0；旧 Cancel→second Start 的控制冗余被确定性消除；
- adapter TypeError、get-transfer error、refill timeout、P2P 608、OOM、retry exhausted、scheduler
  exception、panic 和运行期 burner/watchdog/inference 均为 0。DMA operations=`4134`；可靠
  `load_back_consumed=4128`，余 6 次成功 Transfer/DMA 未出现对应 consumed observation，需在归档前
  离线解释，不能静默写成完全闭合；
- owner Get active/flight/starting/finishing/revoking 全归零；owner remote-Put active=0，
  transfers=published=`40610+61294=101904`、failed=0；
- 正式窗=`1784548825.7177114–1784549080.1110215`。CPU 双 HCA TX
  avg/active-average/p99/peak=`106.204/150.700/372.515/409.027Gbps`；CPU TX=
  `3372860598340B`，node0+node1 RX=`3372860615044B`，仅差 `16704B`。三节点各 508 个 interval、
  sample error=0；HCA 首次分析误把输入写成 `node=path` 导致入口 FileNotFound，按工具实际 CLI
  改为纯 path 后成功，没有数据损坏；
- HCA 已停止并导入 Greptime，inference/phase/HCA 行数=`1864/817/10268`。当前全栈暂仍运行，
  下一动作是完整停栈和归档，而不是继续发请求。

### 0.86 2026-07-20 20:15 HKT：r38 attempt2 对账、停栈与正式归档闭环

- 离线 lifecycle 把表面 6 个 `Transfer/DMA - consumed` 缺口逐项闭合：六项都有 Transfer、ready、
  prefetch submit/complete、init-load 和 DMA completion；后续 residual load-back attempt 覆盖了
  request-level terminal。表面 `8134852608B` 不能认定为未消费或浪费传输；
- direct-delete requests=`2145`，victims/completed/retryable=`777925/777925/0`；node0/node1
  handoff=committed=`177663/600262`。CPU retained=`55341/261131599872B`，master activity 与 owner
  selection/retry/debt 均归零；remote Put targets/transfers/published=`101904/101904/101904`，
  active/failed=0；
- 20:09 后按依赖顺序人工停栈。正式窗口内 panic=0；停栈后复现两个 GPU owner late-spawn 析构
  panic、master KeyboardInterrupt unwrap、CPU close 未消费 `Result<ok>` 和 SGLang/router Ctrl-C
  traceback。它们发生在 workload 完成及归零 Snapshot 后，保留为 lifecycle TODO；
- 延时并再次远程复核：三机实验 session/process/port=0；两 GPU 节点 burner/watchdog/inference=0、
  compute PID=0，四张实验卡 `0 MiB/0%`。机器保持停止，没有恢复 burner；
- 正式 artifact=`artifacts/e44_r38_get_prefix_reuse_attempt2_passed_20260720/`，最终 135 个文件、
  约 202 MiB；134 个非 manifest 文件全部纳入 `SHA256SUMS` 并校验通过；
- 方向 3 最终裁决为“正确性/控制冗余修复通过，端到端性能无收益”。r34 继续作为性能基线；
  方向 4 尚未启动，等待用户下一步指令。

### 0.87 2026-07-20 21:23 HKT：截至当前验证审计与直白下一步

- 只读复核确认当前 `Fluxon` tracked diff 与 r38 attempt2 release manifest 的
  `source_worktree.diff` SHA256 都是 `761ad242...4096f16`，未跟踪 ACK worker SHA256 也一致；
  当前 adapter/radix SHA256=`b2d34b0f...afb27e/8d1b497f...236a5da` 与正式 artifact 相同。
  因而 r38 attempt2 覆盖当前实现；r34 只是历史最优性能锚点，不覆盖 r38 新 Get 路径；
- r34、r36、r38 artifact 的全目录 manifest 分别为 `124/136/134` 项，当前重新校验全部通过。
  r35 原 manifest 的 126 项通过，但后来补入的 `restore_pipeline_summary.json` 不在 r35 清单；该文件
  已在 r36 artifact 的完整 manifest 中固化，不能把 r35 当前目录单独写成全目录 checksum 闭环；
- 当前最明确的未解性能问题不是网络、Get 并发或重复 Start，而是 load-back 前同步腾 GPU 空间的
  allocator free-group 路径。r35 只定位到 `free_group` 占 eviction 累计时间 `91.15%`，还未拆到具体算子；
- 方向 4 当前没有失败或 publication 缺口证据：r38 Remote Put
  targets/transfers/published=`101904/101904/101904`、active/failed=0。因此下一步先做离线阶段/重复
  bytes/HCA idle 对账；无证据就关闭，不为减少 RPC 数盲目实现 batch；
- 真正值得接着发实验的是 allocator 子阶段 observation → 有证据时只做一个 page-aligned free 快路。
  审计末次复核发现两节点 `inference_like_compute.py` 在 20:30 HKT 后自动回生，每节点同一独立
  PGID 内含两个父进程及四个 multiprocessing 子进程，四卡均约 `8483 MiB/100%`；实验栈仍为 0。
  已只终止这两个明确进程组，延时 12 秒复核两节点 interference/compute PID=0、四卡
  `0 MiB/0%`。未启动任何实验。

## 1. 最终结论

容量驱逐的基本单位固定为单个 KV。

master metadata Moka 和 owner-local Moka 都按以下方式工作：

1. 从 Moka pop 一个当前未 pin 的 KV；
2. 只校验这个 KV 的 key、put version 和 backing；
3. 只为这个 KV 安装 source/master fence；
4. 只回收这个 KV；
5. 成功后累计它实际可回收的 bytes；
6. 空间仍不足时继续 pop 下一个 KV。

不再根据 TP rank、`PutAtomicGroup` 或 `atomic_batch` 展开兄弟 KV，也不等待“完整组”。

put/get 的 `atomic_batch` 仍保留同请求聚合和结果发布原子性。KV key 没有改成整批 key，容量驱逐
也不使用整批作为 victim 边界。

## 2. 当前代码改动量

当前工作树（包含 0.24 tier1 修复）净 diff 为 8 个文件、`+968/-771`；其中 owner remote-Put P0
的 14:50 快照为 `+861/-754`。下表是
其 Git 基线 `aafac11` 相对父提交 `568ef15` 的历史容量驱逐提交净 diff，不包含 0.15 的未提交
修改；两者不能相加冒充独立提交总工作量。中途被覆盖且没有独立提交的实现无法精确计算。

| 文件 | 新增 | 删除 | 最终职责变化 |
|---|---:|---:|---|
| `client_kv_api/external_api.rs` | 75 | 19 | 同一完整 `atomic_batch` 的 Put follower 等待并复用 leader 终态；等待前释放本请求部分 guards。 |
| `client_kv_api/get.rs` | 4 | 4 | local hot admission 改为登记单 KV，不再把 atomic group 交给容量 victim 路径。 |
| `client_kv_api/local_reserve_rebalance.rs` | 28 | 4 | 明确 projected credit 边界，并为一次 pressure pop 发送显式 Begin/End。 |
| `client_kv_api/mod.rs` | 446 | 614 | 删除容量整组/incomplete 路径；保留单 KV fence/debt；增加 Put shared terminal op 和 pressure dispatch 边界。 |
| `client_kv_api/put.rs` | 213 | 199 | 一次 pressure pop 合为一个 RPC；`Completed` 批量落本地 slot；发布成功唤醒 Put followers。 |
| `client_kv_api/reclaim.rs` | 39 | 1 | 增加 master direct-delete 完成后复用既有 Prepare/Commit/Finalize 的同步本地释放 helper。 |
| `master_kv_router/mod.rs` | 28 | 246 | master Moka Size 事件改为单 KV reclaim；删除容量侧 group expansion 和整组入口。 |
| `master_kv_router/msg_pack.rs` | 9 | 9 | RPC 使用单 KV `victims`/`victim_index`，并为一次 batch 生成稳定逐项 epoch。 |
| `master_kv_router/reclaim.rs` | 326 | 453 | 单 KV 规划与 master direct-delete；批内独立状态、一个完整响应向量及幂等测试。 |
| **合计** | **1168** | **1549** | **9 个 Rust 文件，合计触及 2717 行，净减少 381 行。** |

这里的“触及 2717 行”是新增与删除之和，不代表新增了 2717 行代码。

## 3. 一路经历的设计变化

### 阶段 A：统一 pin 管理

master 和 owner-local 复用 `fluxon_util::pin_aware_moka`：

- 第一个 pin 将同 generation 的 KV 从 Moka 可驱逐集合移出；
- 后续 pin 只增加持有关系；
- 最后一个 `PinGuard` 释放后，同 generation 的 KV 才重新进入 Moka；
- `UserMemHolder` 持有本地 reader 对应的 `PinGuard`，holder 生命周期结束时自动 unpin。

这一模块已经存在于当前代码基线，不在上面 9 个文件的净 diff 中。本轮最终实现继续复用它，
没有另建 master pin 表或 local pin 表。

### 阶段 B：统一术语为 `atomic_batch`

同一 put/get 请求的聚合对象统一称为 `atomic_batch`，替代含义不清的 `cohort`。

这次改名只描述请求聚合和发布语义，没有把 KV key 改成 batch key，也不意味着容量必须整组驱逐。

### 阶段 C：曾实现整组容量驱逐

中间版本曾尝试在一个 KV 被 Moka pop 后，继续查找同 TP/atomic group 的其他成员，再整组安装
fence 和整组 reclaim。为此曾加入：

- owner atomic-group registry；
- TP key 后缀解析和跨 rank 成员展开；
- incomplete group retry；
- 重试约 12 次、约 26 秒后再 quarantine pin 的设计；
- `OwnerSourceEvictionAtomicBatch` RPC；
- master 侧整组一致性校验、整组 fence 和整组回滚测试。

该方案暴露出一个根本问题：容量只需要释放足够的物理 bytes，但整组方案会因为某个兄弟成员
缺失、busy 或尚未发布，让已经 pop 的 candidate 长期停在 retry-only/incomplete 状态。candidate
已经离开 Moka，却没有 source fence，也不能在 hard timeout 内释放物理 slot。

这个中间版本没有独立提交，随后被最终单 KV实现覆盖，因此无法提供可信的独立增删行数。取消记录
保留在 `fluxon_kv_incomplete_atomic_batch空转与pin收敛方案_20260718.md`，防止后续误把它恢复。

### 阶段 D：回退并收敛为单 KV 驱逐

最终重构删除容量路径上的整组语义：

- 删除 owner group registry；
- 删除容量侧 TP 后缀解析；
- 删除 atomic-group/TP sibling expansion；
- 删除 incomplete-group retry 和 quarantine pin；
- owner-local 只 fence 被 Moka pop 的单个 KV；
- master metadata 只 reclaim 被 Moka pop 的单个 KV；
- owner→master RPC 使用 `victims`，每个 victim 独立处理；
- RPC 的批量只用于减少传输次数，不提供 all-or-nothing 语义；
- busy、stale、late reader 或 backing 不匹配的 victim 本轮累计 0 bytes，pressure 后续继续选其他 KV。

### 阶段 E：修复单 KV rollback 死锁

定向测试发现单 KV source fence 在 late reader 场景回滚时，会在仍持有同 key controls 锁的情况下
重入 restore 路径。修复方式是在 rollback 前先释放 controls guard，再恢复同一 key 的 fence。

这不是放宽正确性：晚到 reader 仍会让该 victim 本轮失败并恢复，只是不会因同 key 重入而死锁。

## 4. 最终保留与删除的边界

### 保留

- put/get 的 `atomic_batch` 聚合；
- owner-local 发布前的 `atomic_batch` 完整性检查；
- master/local 共用的 pin-aware Moka；
- `UserMemHolder` 持有 `PinGuard`；
- 单 KV 的 key、put version、backing 精确校验；
- 单 KV source fence、master fence、rollback 和 retry；
- 多 victim RPC 传输合并；
- pressure 只使用 exact fenced bytes 作为 projected reclaim credit。

### 删除

- 容量 victim 的 TP sibling expansion；
- 容量 victim 的 atomic-group expansion；
- owner capacity group registry；
- 为凑完整组而进行的 incomplete retry；
- incomplete quarantine pin；
- `OwnerSourceEvictionAtomicBatch`、`members` 和 `atomic_batch_index`；
- master 整组 route 校验、整组 fence、整组回滚和 sibling detach。

## 5. 关键运行口径

```text
need_bytes
    ↓
pop 一个未 pin KV
    ↓
单 KV 校验和 fence
    ├─ 成功：累计该 KV 的实际 bytes
    └─ 失败：累计 0，继续其他 KV
    ↓
累计不足则继续 pop
    ↓
最终仍以 free list 出现足够物理 slot 为完成条件
```

以下状态不能当作即将释放的空间：

- 仅被 Moka pop；
- 仅创建 candidate debt；
- 仅进入 retry queue；
- 因 busy、stale、late reader 或 backing 不匹配而尚未安装 fence。

只有安装了精确 source fence、已经能进入物理回收的 bytes，才能作为 projected reclaim credit。

## 6. 验证状态

### 6.1 修复前历史验证（不覆盖 00:47 当前代码）

- `cargo check -p fluxon_kv --lib`：通过；
- `cargo test -p fluxon_kv --lib --no-run`：通过；
- 单 KV master route/reclaim 定向测试：`7/7`；
- 单 KV source-fence late reader/rollback：`1/1`；
- pressure projected-credit：`2/2`；
- pin-aware Moka：`6/6`；
- `cargo test -p fluxon_kv --lib`：`170 passed, 0 failed`；
- `cargo fmt --all -- --check`：通过；
- `git diff --check`：通过。

### 6.2 `aafac11`/r18 历史门禁（不覆盖 0.15 当前工作树）

- `cargo check -p fluxon_kv --lib`：通过；
- `cargo test -p fluxon_kv --lib --no-run`：通过；
- direct-delete 整批结果、partial Busy/Stale 与幂等重放：`1/1`；
- source selection 完成后的 local release/finalize：`1/1`；
- Put leader 成功终态复用：`1/1`；
- Put leader 失败后唤醒 follower：通过；
- `cargo test -p fluxon_kv --lib`：`173 passed, 0 failed`；
- `cargo fmt --all -- --check`：通过；
- `git diff --check`：通过。

`aafac11` 的本地全量门禁、r18 隔离 release 构建和三机同负载验收均已完成。三机结果为
`2304/2304`、fatal=`0`、QPS=`7.381347613`、L2+L3=`58.9025%`；drain 后容量临时态全归零。

### 6.3 owner remote-Put P0 当前工作树门禁

- `cargo fmt --all -- --check`：通过；
- 64 followers 与跨 generation ABA 定向测试：`2 passed, 0 failed`；
- `cargo test -p fluxon_kv --lib`：`175 passed, 0 failed`，耗时 `196.40s`；
- Cargo target 位于 `/dev/nvme0n1p3`；执行测试时使用 r18 NVMe closed SDK 的动态库路径；
- r20 隔离 release 的三端 wheel/PyO3/closed-runtime/metadata-only 哈希和 import probe 全部通过；
- r20 三机同 r19 配置验收为 `2304/2304`、fatal=0、completion missing=0、容量临时态归零；本节
  当前工作树已获真实负载覆盖。r19 仍只覆盖旧 `aafac11`，其性能数值不能自动继承给当前代码。

Cargo 检查和测试产物均位于：

```text
/mnt/nvme0/mjq_build/push_sglang_fluxon_target
```

## 7. 文档改动

工作区根目录不属于 `Fluxon` Git 仓库，因此无法用同一 Git diff 给这些文档提供可信的净行数。
本轮保留以下文档账目：

- `fluxon_kv_单KV逐个pop驱逐方案_20260718.md`：最终方案、运行语义和剩余风险；
- `fluxon_kv_单KV容量驱逐修改总账_20260718.md`：本文件，记录改动量和设计过程；
- `20260718_234949_fluxon_kv_r17当前问题说明与修复优先级.md`：r17 singleton reclaim
  限速、同 key Put 不复用、radix split 触发链和下一步优先级的直白说明；
- `fluxon_kv_incomplete_atomic_batch空转与pin收敛方案_20260718.md`：标记整组/incomplete 方案已取消；
- `fluxon_kv_修复设计_moka边界与容量闭环_20260716.md`：顶部加入现行单 KV 修订说明；
- `fluxon_kv_当前问题与后续优化计划_20260718.md`：公平参考基线、r19 性能最优、r20 singleflight、
  r21 当前代码验收、96 GiB tier1 负收益归因和后续优先级均已同步；
- `experiment_configs/e44_local_slot_tier_20260716/README.md`：顶部已同步 r21 当前代码验收、r19
  性能最优与 r18 公平参考基线；
- `20260719_101516_fluxon_kv_r18后续命中率优化执行计划.md`：r19/r20/r21 结果、未来小 tier1 与
  end-depth 独立分支、门禁、结果选择和未达标后的归因顺序；
- `20260719_121358_fluxon_kv_owner统一远端Put控制流实施规划.md`：已从设计稿更新为 direct
  singleflight 实现快照，明确无 actor、当前代码边界、验证与剩余 P1；
- `20260719_175605_fluxon_kv_r27后续优化多角度分析.md`：汇总 tier1 扫描、turn 延迟、
  admission start/end 语义、node1 不对称、singleflight/load-back 优先级，并给出 P0–P4；
- `artifacts/e44_r18_direct_delete_singleflight_metadata_baseline_passed_20260719/`：r18 正式
  summary、请求、before/after metrics、网络样本、全栈日志、精确配置与 release manifest；
- `artifacts/e44_r19_direct_delete_singleflight_tier1_075_passed_20260719/`：r19 正式结果、三机
  全栈日志、配置、rc=0 与 release manifest；
- `artifacts/e44_r20_owner_remote_put_singleflight_tier1_075_passed_20260719/`：r20 当前代码正式
  summary、singleflight/容量验收、清场证据、配置、全栈日志和 release manifest；
- `artifacts/e44_r21_tier1_independent_075_passed_20260719/`：r21 正式 summary、96 GiB tier1 与
  source-unavailable 原因计数、容量闭环、负收益归因、清场证据和 release manifest；
- `AGENTS.md`：固化 NVMe 构建、单 KV 容量驱逐、修改总账和 direct remote-Put
  singleflight（无 actor）规约。

## 8. 尚未完成

r22/r23/r27 已完成当前 release 的小/中 tier1 窗口对比并全部清场。当前剩余问题
按优先级为：

1. P0 正确性复测：先构建 r31 验收 source-selection/reclaim fence 异步等待，保持 r30b 的
   Get32、tier1 5%、depth160、容量、workload 与观测不变；
2. r31 正确性通过后，才以 r22 5% 为直接性能基线，只把 proactive admission preset 从
   `prefix_depth_ratio/160` 切到 `prefix_end_depth_ratio/288`；
3. 若 admission 结果模糊或负收益，先补 admission depth、来源、CPU Get 次数、首/末命中距离、
   淘汰时是否从未读过等副本价值生命周期观测；
4. 按 source owner 归因 node1 不对称；r27 的 node1 远端命中约 49.21%、last-route removed
   33,977，明显差于 node0，但在更精确观测前不改通用 router 策略；
5. 补 master Start/Done/Revoke 并发重放、owner leader 高并发失败接管、shutdown/cancel 和
   multi-`atomic_batch` mixed existing/inflight/missing 专项测试；
6. primary/Append wire ticket 合并仍是可维护性改进，但当前 Append adapter 已通过真实负载，
   不作为下一轮主性能优化；
7. ratio=`0.04375` 精确对齐 r19 的 5.60 GiB 可作为低优先级归因试验，不取代
   end-depth P0；不再扫 18%/25%/50% 或更大 tier1；
8. 当前 E44 是单一 `slot_size=4,718,592`，通用多 size class pressure 仍未专项覆盖；
9. 只有 L2+L3 追到 `68.0051%`，或 admission 已明显提高命中但恢复开销拖低 QPS 时，
   才开始 load-back 数据面优化。

## 9. 已固化规约

工作区根目录 `AGENTS.md` 已明确：

- 容量驱逐只按单 KV；
- 不得展开或等待 TP/atomic-group 兄弟成员；
- `atomic_batch` 不定义容量 victim；
- 多 victim RPC 只是传输合并；
- owner-local 按成功 source-fenced bytes 攒够缺口后一次提交，master direct-delete 多个精确
  source routes；不得把 batch 再拆成 singleton 三阶段事务；
- pre-fence candidate/retry debt 不得充当 projected reclaim credit；
- 未经用户明确改变设计，不得重新引入整组驱逐；
- remote Put 按 `(key, put_id)` 由短 per-key 临界区选 leader，leader 直接发起、followers 异步等
  终态；不得恢复 replica/batch actor 或全局 FIFO；
- master Start/Done/Revoke 使用 per-operation 异步锁与可重放终态，reservation 复用不能替代 owner
  singleflight；
- 非平凡修改必须维护修改总账，并区分最终净 diff 与无法精确计数的中间修改。

## 10. r17 首次三机轮 early no-go 与清场

故障时间：2026-07-18 23:08 HKT  
清场完成：2026-07-18 23:16 HKT  
run id：`e44_r17_single_kv_pop_metadata_baseline`

已确认的直接证据：

- node1 TP0/TP1 在 23:08:04–23:08:05 共记录 8 次
  `local_fast_put_start conflict retry exhausted`，终态为 `KeyBeingWrittenError`；失败批大小包括
  49 和 69 keys；
- 23:08:05 两个 TP rank 均报告 `Prefill out of memory`，要求分配 389 tokens 时
  `full_available_size=320`；随后 TP0/TP1 均进入 `Scheduler hit an exception`，主进程收到
  SIGQUIT 并退出；
- node1 根 cgroup 的 `oom_kill=0`，故障是 SGLang 内部 prefill 分配器抛错，不是内核
  OOM killer；
- node0/node1 定向日志中 `refill timeout=0`、`P2P(code=608)=0`，因此 r14 的
  `refill timeout -> P2P 608` 故障链没有原样复现；
- node1 owner 在 23:08:45 已收敛到 `size_evictions=5654`、`handoff=5654`、`committed=5654`、
  `source_eviction_selected=0`、`selection_debt_bytes=0`、`source_eviction_selected_bytes=0`、retry entries=`0`；
- workload run dir 只生成 `workload_config.json`、reset-before 和 before-metrics，没有 after-metrics、
  summary 或正常 rc；router 日志仅能做临时故障观测，不能代替 workload 终态；
- run dir：
  `/storage/mjq/mooncake_m1/mooncake_perf_workloads/results/20260718_150523_agent_multiturn_long_context_fluxon_e44_r17_single_kv_pop_metadata_baseline_s96_t24_sys8192_out8_c24_session_stream_20260718_a9d1c0af`。

清场证据：

- workload、node0/node1 SGLang/owner、master/control/router 和 CPU owner 已全部停止；
- 三台节点与 r17 相关的 tmux、进程和实验端口均为空；
- node0/node1 两张 GPU 均为 `0 MiB / 0%`；
- 两个 GPU 节点上被外部重新拉起的 `gpu_burner.sh watchdog` 已停止，所有 GPU 已取消
  managed auto-reclaim；23:24 HKT 延时复核仍为 `Watchdog is stopped`、GPU `0 MiB / 0%`，没有自动复活。

证据已固化到：

`experiment_configs/e44_local_slot_tier_20260716/artifacts/e44_r17_single_kv_pop_metadata_baseline_failed_20260718/`

该目录包含 node0/node1 SGLang/owner、master/router、CPU owner、两侧 request metrics、workload
before-metrics 和 SHA256 清单，避免后续启动覆盖通用 `owner.log`。

### 10.1 已定位的第一因果断点

本轮 OOM 不是单 KV victim 边界本身错误，而是单 KV 改造后仍沿用了“一个事务串行跑完再处理
下一个”的 master 执行方式：

1. owner 侧会把最多 128 个独立 victims 合并进一次 `BatchEvictOwnerSource` RPC；
2. master 收到后却为每个 victim 单独 enqueue 一个 request；
3. reclaim actor 虽然最多收 256 个 request，却在 `while` 中逐个调用
   `reclaim_single_victim(...).await`；
4. singleton 的 Prepare、Commit 均已成功后，代码仍无条件 sleep 25ms，下一轮才进入
   Finalize，然后才处理下一个 victim。

node1 owner 的运行证据与代码完全对应：

- 5654 次 Prepare、5654 次 Commit、5654 次 Finalize 全部为 `items=1`；
- 第一个 Commit 为 15:05:46.901，最后一个为 15:08:25.502，5654 个 slot 用时约
  158.6 秒，约 35.6 slot/s；
- 故障附近 15:08:04.023–15:08:05.980 只有 73 个 Finalize，仍约 37 slot/s；
- 15:07:51 pool 已经只有 115 free slots，却有 564 pending slots；590 个 source-fenced
  victims 正排队等待物理回收。

因此当前 projected credit 不是旧版的虚假 candidate debt：这些 bytes 确实已安装精确 source
fence。问题是 fence 后的物理回收队列被 singleton + 25ms 串行节流，短时间无法兑现。

### 10.2 `KeyBeingWritten` 为什么会把 GPU 驱逐打失败

external local-first Put 的顺序是：先对批内每个 key 增加 `local_puts` fence，再进入 FIFO
等待 owner 物理 slot。后来的相同 key 没有 singleflight/join，而是直接收到
`KeyBeingWritten`，并且一个 key 冲突会让整个 `atomic_batch` 返回失败。

SGLang 仅重试 4 次，sleep 总计 10ms；本轮一个最终成功的 69-page leader
`local_fast_put_start` 实测耗时 332.463ms。后来的重复 write-back 不可能在 10ms 内等到 leader
结果，只会整批失败。

触发重复 write-back 的直接场景是 radix split：15:05:38 已成功备份的 118-page `node=78`
在 15:08:04 被拆成 69-page `node=181` 与 49-page `node=78`，两者 key 总数仍为 118；
hostless split 逻辑清除了两边的 `storage_backed`，于是相同 page keys 再次进入 Put。随后关键
GPU 叶节点无法及时重新备份/驱逐，同一时刻又发生“evict 14400 tokens 后 load-back 18048
tokens”的净 3648-token headroom 消耗，最终只剩 320 physical free tokens，389-token prefill
分配失败。

这也修正了早期的 publication 假设：本轮 owner 日志没有 publication retry、PutDone unresolved
或 queue-full 证据；SGLang 使用 ExternalClient 路径，确定的 332ms 长尾发生在 slot claim 阶段。
64-worker native publication dispatcher 不是现有证据支持的第一断点。

### 10.3 修复落实状态与 r18 验收结论

1. **P0 已实现并通过 r18：local 攒够 fenced bytes，master 直接批量 delete。** local 逐个 pop、逐个校验并安装
   source fence，只累计成功 fenced bytes；覆盖缺口后一次发送多个 victims。master 在一个 handler
   内逐项核对并直接删除精确 source routes，通过一个响应一次性返回完整逐项结果向量；local
   收到完整响应后批量处理，只释放成功/已删除项。
   owner-local 容量路径不再进入 singleton Prepare/Commit/Finalize。批量 delete 不得变回整组驱逐。
2. **P0 已实现单完整 `atomic_batch` 路径：Put singleflight/join。** 后来的同 key Put 等 leader 终态并复用结果；
   `atomic_batch` 只汇总每个 key 的结果，不能新增重复 slot/重复写，也不能靠放大重试窗口兜底。
3. **本地门禁已完成：** busy/partial failure、direct-delete 整批响应、逐 victim 幂等重放、leader
   成功复用和失败唤醒均通过；全量库测试 `173/173`。multi-`atomic_batch` mixed 行为仍待专项。
4. **三机容量门禁已完成：** r18 使用完全相同的 r17 workload、metadata-only
   `128/128/256 GiB`、无 burner，得到 `2304/2304`、fatal=0、868 个多 victim batch、约
   `647.69 victims/s`，owner singleton Prepare/Commit/Finalize=0。

10.1–10.2 只保留 r17 历史故障证据；当前有效结论以 0.6 和 r18 artifacts 为准。

## 11. 2026-07-19 21:44 HKT：r30 External holder ACK 合批实现与本地门禁

### 11.1 最终行为

- `ExternalMemHolder::drop()` 仍是最后一个强引用消失后的真实生命周期边界；没有把 ACK 提前到
  plan/view 释放阶段。
- Drop 不再为每个 holder spawn Tokio task 或发一个 RPC，只在持有 view guard 的短同步区间内
  把 `(external_client_id, owner_start_time, holder_id)` 无等待送入进程内队列。
- worker 用 1ms merge window 收集，按 external client 和 owner generation 分组、按 holder ID
  去重，并强制每个 wire batch 不超过 1024 项。队列和 wire 均不携带查找不需要的 key。
- owner 对一个 batch 只校验一次 generation，在一个 handler 内逐项删除
  `external_get_holding`，最后一次返回 released/missing 汇总。missing 按幂等终态处理；owner 已换代
  时，旧 holding 已整体失效，external 记录 generation-mismatch items 后视为完成。
- 旧单项 RPC 暂留为兼容入口，但当前 Drop 主路径只调用 batch。容量驱逐、remote Put singleflight、
  tier1、Get 并发和 TP handle 均未改变。

### 11.2 r30 核心逐文件净改动

统计基线是 21:23 前的 8 文件 `+968/-771` 工作树；下表是 r30 最终工作树相对该 Snapshot 的
净变化。`client_kv_api/mod.rs` 与旧修改重叠，其数值由同一 HEAD-relative numstat 前后差计算；
总和与全工作树从 `+968/-771` 变为 `+1625/-849` 的代数变化完全一致。

| 文件 | 新增 | 删除 | r30 最终职责变化 |
|---|---:|---:|---|
| `client_kv_api/mod.rs` | 110 | 12 | 注册 batch ACK handler；generation 校验、逐 holder 幂等删除和定向测试。 |
| `client_kv_api/msg_pack.rs` | 48 | 0 | 新增 4036/4037 batch wire 及 compact holder-id round-trip。 |
| `external_client_api/mod.rs` | 91 | 1 | 注册 caller、启动 worker、提供 enqueue/snapshot/send，并校验响应计数。 |
| `external_client_api/delete_ack_batch.rs` | 366 | 0 | 新增 merge、分组、去重、1024 上限、5s RPC timeout、计数和测试。 |
| `memholder/lifetime.rs` | 17 | 60 | 删除 External 逐 holder async task/RPC，Drop 改为同步 enqueue；owner→master ACK batching 不变。 |
| `memholder/mod.rs` | 0 | 1 | External Drop ctx 不再克隆冗余 key。 |
| `rpcresp_kvresult_convert/rpcresp_kvresult_convert.rs` | 25 | 4 | 增加 batch ACK response 的 ToResult/FromError；其余变化含 rustfmt。 |
| **合计** | **657** | **78** | **7 个核心文件，触及 735 行，净增 579 行。** |

实现过程中曾短暂把 key 留在队列项中只供 sample log 使用；审查后在编译前删除，避免百万级
holder backlog 复制长 key。该中间版本未独立提交，不能把其工作量加到上表最终净 diff。

### 11.3 本地验证与实验编排

- build target：`/mnt/nvme0/mjq_build/push_sglang_fluxon_target`，`findmnt` 为
  `/dev/nvme0n1p3`，未使用 Ceph `target/` 或 `/tmp`；
- `cargo check -p fluxon_kv --lib`：通过；
- `cargo test -p fluxon_kv --lib delete_ack -- --nocapture`：`4 passed, 0 failed`；
- `cargo test -p fluxon_kv --lib`：`180 passed, 0 failed`；
- 首次定向测试的 binary 因未带 closed-SDK `LD_LIBRARY_PATH` 返回 127；补上仓库既有路径后同一
  binary 全部通过，未出现断言失败；
- 新增 108 行隔离 build 脚本和 28 行 r30 master config。配置相对 r28 Get32/5% tier1
  observability 基线只有隔离 `log_dir` 不同；release 正在 NVMe staging 构建，尚无 wheel/PyO3
  哈希，也尚无三机性能结果。

### 11.4 r30 release、attempt1 与 r30b 复跑门禁

更新时间：2026-07-19 22:24 HKT。

- r30 隔离 release 已构建并通过三端部署门禁：wheel SHA256=`28716b4c...e40c`，PyO3
  SHA256=`e3a6e6f8...778b`；
- attempt1 在约 `1560/2304` 时因 node0 33-key Put 冲突重试耗尽，继而 prefill OOM 和 scheduler
  exception，被人工终止；无 after metrics/summary，不得登记性能结果；
- 三个正常退出 TP rank 的 ACK 合计为 `521993 items / 1243 RPC`，released 精确闭合，四类失败
  均为 0，约 `420×` 合批；第四个硬退出 rank 无终态 Snapshot；
- r28/r29 同负载冲突为 0，但一次 r30 失败不足以判断偶发或回归。新增 r30b 隔离 variant，只改
  run id、namespace、日志和 HCA 输出；release、Get32、tier1 5%、depth160、metadata-only
  128/128/256 GiB、S96×T24 c24 workload 与观测不变；
- r30b 编排新增 1 个 28 行 master YAML、variant 表 12 行，并让已有 deploy 脚本多传 1 个配置
  文件；这是实验编排净增，不计入 Fluxon Git 核心 `+1625/-849`；
- r30/r30b master YAML 删除 `log_dir` 后无 diff，variant 的 venv、PyO3、Get 并发和 replica JSON
  对齐；相关 shell `bash -n`、YAML 解析和变量检查均通过。

attempt1 证据目录：

`experiment_configs/e44_local_slot_tier_20260716/artifacts/e44_r30_external_ack_batch_attempt1_failed_20260719/`

裁决规则：r30b 若再次出现相同 Put conflict/OOM，ACK 合批不能进入性能基线，先定位
split/write-back 生命周期；若 `2304/2304` 且 fatal/ACK failure 为 0，再与 r28 比较 QPS、TTFT、
命中和 HCA，并在停栈、归档、恢复 burner 后决定接受或回退。

### 11.5 r30b 二次失败、根因闭合与 artifact

时间：2026-07-19 22:34–23:04 HKT。

- r30b 保持 r30 release、Get32、tier1 5%、depth160、metadata-only 128/128/256 GiB、原 workload
  与 HCA 观测不变，只隔离 run id/namespace/log；workload rc=`130`，没有正式 summary；
- node0 先对 `node=853` 的 42-key TP1 batch 发生 16 次 recheck、4 次 retry exhausted，随后
  prefill OOM/scheduler exception；故障前 owner=`pending_slots=0/free_slots=426`，refill timeout、
  P2P 608 均为 0；
- node0 失效后，node1 又记录 48 次 recheck、12 次 retry exhausted 和同形 OOM；这部分是后续
  故障，不改变 node0 已经成立的首个 no-go；
- 两个正常退出 TP rank 的 ACK 合计 `325367 items / 812 RPC`，约 `400.70 items/RPC`，released
  精确闭合，missing/generation-mismatch/RPC/enqueue failure 均为 0；
- node0 的关键 key 在 14:35:59 已完成 101 页备份，split 后 14:36:17 写其中 42 页；TP0/TP1
  key 后缀分别为 `_0_2/_1_2`，排除跨 TP 同物理 key；owner 直到 14:36:51 才因
  `master rejected stale source identity` 回滚该 TP1 source-selection fence，证明 10ms 重试面对的是
  约 34 秒的精确 source fence，而不是另一个 Put leader；
- artifact 已固化到
  `experiment_configs/e44_local_slot_tier_20260716/artifacts/e44_r30b_external_ack_batch_attempt2_failed_20260719/`，
  含 README、CLEARANCE、全目录 SHA256SUMS；`sha256sum -c` 全部通过；
- 23:04 HKT 三机无 r30b 进程，三端 release symlink 仍为 r30；node0/node1 managed burner
  watchdog 正常，四卡均约 `1395 MiB/100%`。

### 11.6 source-selection/reclaim generation 等待修复

实现时间：2026-07-19 22:39–23:05 HKT。

当前最终设计：

1. `OwnerKeyControlState` 在安装 source-selection fence 时创建一个 `watch<bool>` completion；selection
   提升为 reclaim 时沿用同一 channel；
2. `reserve_external_local_first_put_key()` 仅对同时设置 reject-inflight/reject-exist 的幂等请求返回
   `WaitForLocalAccess` receiver。普通非幂等调用保持即时 `KeyBeingWritten`；
3. External batch 若已为前部 key 取得 leader guards，等待前先释放，再异步等待 precise generation；
   completion 关闭也只触发重新核对，不误判成功；
4. selection restore、reclaim Abort、Finalize 和 direct-delete 完成都会发布 completion；请求醒来后从头
   核对完整 `atomic_batch`，不持有 source、slot 或部分 batch fence；
5. 多个 waiter 共享终态，一个 RPC 取消只 drop 自己的 receiver。没有 actor、轮询、全局 FIFO，也
   没有改变单 KV victim、fenced-bytes credit 或 direct-delete batch 语义。

相对 r30 release 的 HEAD-relative numstat 代数变化：

| 文件 | 新增 | 删除 | 行为变化 |
|---|---:|---:|---|
| `client_kv_api/external_api.rs` | 33 | 0 | 等待、释放部分 guards、重检整批。 |
| `client_kv_api/mod.rs` | 143 | 2 | completion 生命周期、reserve 分支和竞态测试。 |
| `client_kv_api/reclaim.rs` | 14 | 11 | selection→reclaim 继承及 Abort/Finalize 唤醒。 |
| **代数合计** | **190** | **13** | 当前全工作树从 `+1625/-849` 变为 `+1815/-862`。 |

这些是同一 HEAD 两份最终 Snapshot 的净差，不能统计已覆盖的中间键盘工作量。

验证结果：

- build target `/mnt/nvme0/mjq_build/push_sglang_fluxon_target` 经 `findmnt` 确认为
  `/dev/nvme0n1p3`；
- rollback、direct-delete finalize、非 join、fence 清除后重新 leader、两个 live waiter 和一个取消
  waiter：`1 passed, 179 filtered out`；
- 全量 `cargo test -p fluxon_kv --lib`：`180 passed, 0 failed`，197.00s；
- `cargo check -p fluxon_kv --lib`、`cargo fmt --all -- --check`、`git diff --check`：通过。

当前已构建 r31，但尚未三机部署，因此这些结果只关闭本地实现和 release 门禁。r30/r30b 的 ACK
功能证据可以继续作为协议证据，但它们的性能/正确性失败不能覆盖当前修复。

### 11.7 r31 隔离 release 与编排

时间：2026-07-19 23:22 HKT。

- NVMe staging：`/mnt/nvme0/mjq_build/fluxon_e44_r31_source_fence_wait_20260719`；Cargo target、
  manylinux rootfs 和 staging 均经 `findmnt` 确认为 `/dev/nvme0n1p3`；
- unified wheel SHA256：`81a66946b4babb28194d4bb089ca5b15dd805cbdec06198ff1afe4033101efb8`；
- PyO3 SHA256：`17e627190f7a84aff2df3aa824afa7708c5d9f0d3adbbe68296f21c113730109`；
- release 的 closed SDK、ABI3 cp310/cp311/cp312 import、metadata-only patch、完整 source files、
  worktree diff，以及 `external_api.rs/mod.rs/reclaim.rs` 修复源快照全部通过 SHA256 门禁；
- 新增 build/install/master/deploy 四个文件 `124/74/28/93` 行，variant 表新增 11 行；实验编排净增
  5 文件 `+330/-0`，不计入 Fluxon 核心 `+1815/-862`；
- r30b/r31 master YAML 删除隔离 `log_dir` 后无 diff；两 variant 的 Get concurrency 都是 32，
  replica JSON 完全相同；相关 shell `bash -n`、YAML 解析、release hash 和修复 symbol 检查通过；
- 该时点尚未部署；后续 11.8/11.9 已完成三端 r31 部署、正式验收和清场，不能再用本条历史状态
  描述当前集群。

### 11.8 r31 三端部署与启动门禁

时间：2026-07-19 23:20–23:42 HKT。

- node0/node1/CPU 三端 wheel、PyO3、closed runtime、import、release manifest、metadata-only patch 和
  symlink 门禁全部通过，三个 `fluxon_release` 均指向
  `fluxon_e44_r31_source_fence_wait_20260719`；
- 两侧先执行 `gpu_burner.sh stop 0,1 --no-restart`，再精确停止空转 watchdog；正式启动前四卡均为
  `0 MiB/0%`，burner/watchdog 进程为 0；
- control、Greptime 和 master 先就绪。首次顺序启动 node0 时，owner 已注册、transfer-ready 且
  local reserve 完成 `232/232` grants，但 `shared.json` 120s 内未发布；日志没有 fatal；
- 与 r28/r30b 成功启动日志对比后确认：GPU owner 要在两个 GPU owner 都进入 eligible peer 集合后才
  报 `peer_count=2` 并发布 shared.json。启动 node1 后两侧自动完成；node1 完整启动，node0 通过既有
  `FLUXON_EXTERNAL_SGLANG_ONLY=1` 路径续启，未手工创建 shared.json，也未重启已健康 owner；
- 正式请求前两侧 HTTP 200、Get32、`prefix_depth_ratio/160`、metadata-only `materialized_pages=1`、
  128 GiB、232/232 grants；CPU owner 256 GiB、peer_count=2；router HTTP 200，三端 HCA sample
  `error=null`，fatal=0。

这次启动超时属于编排顺序门禁，不是 r31 行为失败。以后两个 GPU owner 应并行启动，或先 owner-only
形成 peer 集合，再分别启动 SGLang。

### 11.9 r31 正式验收、Greptime/HCA、退出与清场

正式 workload：2026-07-19 23:42:44–23:47:49 HKT。清场完成：23:58 HKT。

- 固定复用 r30b 的 Get32、tier1 5%、depth160、metadata-only 128/128/256 GiB、S96×T24、
  concurrency 24 和 observability/HCA；workload rc=`0`，`2304/2304`、error=0；
- QPS=`7.634560288`；TTFT p50/p90/p99=`2.027694/5.017834/9.843239s`；E2E=
  `2.627600/6.563515/11.334799s`；L1/L2/L3=`4.28660/0/60.91526%`，总命中=`65.20186%`；
- node0 真实触发一次 45-key 幂等 Put source/reclaim fence 等待，`wait_us=3761813`；等待后成功重检
  并继续。两侧 conflict recheck/exhausted、refill timeout、P2P 608、prefill OOM、scheduler exception
  全为 0，直接闭合 r30/r30b 故障链；
- 四 rank ACK shutdown Snapshot 合计 `1073020 items/2960 RPC`，平均 `362.51 items/RPC`；
  enqueued=rpc_items=released，enqueue/RPC failure、missing 和 generation mismatch 为 0；
- direct-delete requests/victims/completed/retryable=`1598/494566/494537/29`，min/max/avg batch=
  `1/911/309.49`；node0/node1 handoff=committed=`157867/336670`，selected/retry/debt/pending 与
  remote-Put active/failed 终态归零；
- workload Greptime points/phase fields/errors=`2204/817/0`；HCA 三端各 691 个有效 samples，导入
  `4146` 行、sample error=0。正式窗 Greptime CPU TX avg/p99/peak=
  `52.335/268.776/317.543 Gbps`，1s peak=`236.898 Gbps`；CPU TX 与两 GPU RX 只差 `16992 B`，
  未见链路饱和；
- 相对 r28 QPS `-2.67697%`，L3 `+0.41570pp`，总命中 `+0.26013pp`。因此 r31 是当前代码正确性
  基线，不是性能新最优；
- 正式窗口后停止 observer、router/SGLang、三 owner、master/control。四 rank ACK 已先输出终态。
  两侧 GPU owner 在 `Shutdown Complete` 后仍析构 panic，CPU close 仍有未消费 Result，node0 SGLang
  需第二次 Ctrl-C；均保留为独立 shutdown P1；
- 三机最终 session/实验进程/端口为 0；两侧 managed burner/watchdog 恢复，四卡约
  `1395 MiB/100%`；
- 结果已固化到
  `experiment_configs/e44_local_slot_tier_20260716/artifacts/e44_r31_source_fence_wait_netobs_passed_20260719/`，
  含 results、Greptime DB、三机日志、request metrics、HCA、配置和 release manifest；119 个文件、
  约 201 MiB，SHA256SUMS 校验全部通过。

### 11.10 2026-07-20 22:43–23:21 HKT：r39 observation release 与未发流部署

- observation-only core 将 Get handle 消费前状态、terminal age、真实 `finish_wait`，以及
  BatchGetStart/RDMA wall-sum-max/install/Done/publish 分段写入日志；没有改变 wire、选择、并发、缓存
  或传输策略。相对封存 r38 core 精确为 3 文件 `+369/-18`；
- NVMe target/rootfs/release 均在 `/dev/nvme0n1p3`。Fluxon/PyO3 check、定向测试、external Get
  `13 passed`、全量库测试 `185 passed / 0 failed`、analyzer self-test、release manifest 和 ABI3
  cp310/cp311/cp312 均通过；wheel/PyO3 SHA256 分别为 `27c8fbfd...d1038`/
  `759333b3...29421f`；
- 固定 variant 显式保持 r38 的 S96×T24、c24、Get32、DMA0、tier1 5%、end-depth288 和
  metadata-only 128/128/256 GiB；r38/r39 master YAML 除隔离 `log_dir` 外无 diff；
- GPU1 与 CPU 已完成 release、venv、import、hash、symlink 门禁。GPU0 公网 `31408` 从部署开始即
  `Connection refused`；GPU1/CPU 到 `10.233.114.129:22/2222` 也关闭，判定 node0 pod 离线，而非
  单个 SSH 映射抖动；
- r39 release、共享 GPU venv/SGLang site 均位于持久盘；已从 GPU1 把 node0 的 `fluxon_f1`
  config/symlink 预置到 r39。该动作只缩短节点恢复后的部署时间，不能替代 node0 本机回读；
- GPU1 上两组 `inference_like_compute.py` 共用 PGID=879，已按既定实验授权精确停止。延时复核两卡
  `0 MiB/0%`、compute PID=0，guard preflight 通过；node0 不可达，故其干扰状态未知；
- 未启动任何 r39 服务、observer 或 workload，没有 r39 QPS/命中/瓶颈结论。node0 恢复后必须先做
  本机 hash、干扰和两卡空闲门禁，再以原固定负载正式发流。

### 11.11 2026-07-21 11:36–12:08 HKT：r39 新 GPU 固定负载、瓶颈裁决与清场

基础设施与门禁：

- 新 node0=`32656/10.233.114.139`、node1=`30245/10.233.114.138`，CPU 继续为
  `30729/10.233.125.121`；只替换基础设施地址，没有改变 workload 或性能参数；
- 两侧均回读 r39 wheel/PyO3、r38 sealed radix/adapter、metadata-only host pool、Get32、tier1 5%、
  end-depth288、DMA0、128 GiB 和 232/232 grants；CPU 为 256 GiB、peer_count=2；
- 正式发流前 burner/watchdog/inference/compute PID=0，四卡 `0 MiB/0%`；三端 observer/Greptime、
  master、owners、SGLang、router 与 HTTP health 均通过；
- release wheel/PyO3 SHA256=`27c8fbfd...d1038`/`759333b3...29421f`；当前 `Fluxon` 最终工作树仍为
  tracked 20 文件 `+2621/-1030`，加未跟踪 ACK worker 366 行后合计 21 文件 `+2987/-1030`。本轮没有
  新增行为代码，只有运行、分析、文档和 artifact。

正式结果：

- 请求窗口 2026-07-21 11:48:59–11:52:36 HKT；原 S96×T24、2304 请求、concurrency 24、
  system 8192、output 8、session-stream workload，rc=0、`2304/2304/0`；
- QPS=`10.6059220588`；TTFT p50/p90/p99=`1.573307/2.802262/4.273965s`；E2E=
  `1.983732/3.784153/4.955955s`；L1/L2/L3=`2.43450/0/73.16877%`，总命中=`75.60327%`；
- 数字相对 r34 高，但不能记作代码收益：两 GPU pod 换了物理环境，且两者 `mlx5_4/mlx5_6` 的 LID、
  正式窗累计 counters 完全相同，3,269 个 common sequence 中 2,959 个完整 counter vector 相同。
  两 pod 实际读取同一组物理 HCA counter，GPU HCA bytes 不得相加；r34 仍是同环境正式基线。

Get-ready 拆解与瓶颈裁决：

- 4,336 条成功 load-back 的 `total/ready_wait/H2D/eviction/free-group/Get Transfer` 均值为
  `952.460/691.585/177.061/43.794/39.283/10.794ms`；`ready_wait` 占 `72.61%`；
- owner 3,969 个消费 handle、1,117,527 个 KV 中，3,712 个 handle 在消费时全部 KV 已终态，
  1,060,832 个 KV（`94.93%`）消费前已终态；真正 `finish_wait` 均值仅 `4.803ms`，是表面
  `ready_wait` 的 `0.694%`；
- 数据终态到 scheduler 消费前平均驻留 `447.602ms`；owner RDMA batch wall 均值/p99=
  `21.766/55.821ms`；
- 正式窗 node0/node1 queue 最大=`17/10`，pending tokens 最大=`373121/255702`，多次 token usage
  接近 `0.93`。当前主等待由此定位为数据 ready 后的 scheduler/prefill 消费队列，而不是 Fluxon
  网络、Get 控制 RTT 或 Moka/free-group；
- queue residence 仍可能是 GPU prefill compute 饱和、H2D/compute 串行或调度策略的结果，不能把
  447ms 全当可删除时间。若限定 Fluxon 同步阶段，下一候选是 H2D restore 177ms，必须先用 GPU
  timeline 验证因果。

网络、容量与 Put 闭环：

- CPU 双 HCA TX avg/active/p99/peak=`142.516/183.535/377.098/413.336Gbps`，未持续打满共享
  800Gbps；三端正式窗 sample error=0；
- direct-delete requests=`1573+679=2252`，victim attempts/completed/retryable=
  `864005/864004/1`。唯一 retryable 为 Get activity busy；node0 handoff=committed=`646275`，node1=
  `217729`，node1 retry scheduled/emitted=`1/1`，selected/retry/debt/selected bytes/in-progress 最终为 0；
- master Get holding、key activity、inflight puts/gets/replicas 最终均为 0；CPU retained=
  `55341 entries/261131599872B`；
- Remote Put node0/node1 transfers=published=`37015/37015 + 42986/42986`，合计与 master targets
  `80001` 精确一致；active/failed/obsolete/terminal replay/completion missing 均为 0；
- eviction candidate tokens=`73046016`，其中 already-backed=`71488512`（`97.868%`），新写回仅
  `1557504`（`2.132%`），unbacked drop=0。Remote Put 空转没有形成当前性能候选。

剩余 correctness 与退出边界：

- node1 在一次 direct-delete Get-activity busy 后，一个 Get leader 报
  `prepared local-reserve Get target cannot replace a live replica`；最终 workload、consume
  misses/errors 和所有临时态均闭合，但该竞态需要专项回归；
- 正式窗口内 refill timeout、P2P 608、prefill/CUDA OOM、scheduler exception、runtime panic、
  workload error 和干扰均为 0；
- 正式窗结束约 8 分钟后，外部系统自动启动 node0 PGID `17238`、node1 PGID `16044` 的四个
  `inference_like_compute.py`；它们未进入正式窗。停栈后按 PGID 精确终止，再延时 20 秒复核；
- 按 router/SGLang → 三位 owner → master/control → HCA observer 顺序完整停栈。三机 r39
  session/process/实验端口最终为 0，burner/watchdog/inference=0，四卡 `0 MiB/0%`、compute PID=0；
  未恢复 burner；
- 人工退出后仍复现两 GPU owner 析构 panic、master KeyboardInterrupt unwrap、CPU close 未消费
  `Result<ok>` 和 SGLang/router Ctrl-C traceback。这些在 workload 后，不污染性能窗口，但仍是 P1。

归档目录：

`experiment_configs/e44_local_slot_tier_20260716/artifacts/e44_r39_get_ready_observe_enddepth288_netobs_passed_20260721/`

包含 results、三机日志/request metrics、三端完整 HCA、Greptime DB、Get-ready/load-back/HCA/formal
accounting JSON、实际 runtime/config、release manifest、README 与 CLEARANCE。最终共 152 个文件、约
215 MiB；151 个非 manifest 文件全部纳入 `SHA256SUMS` 并校验通过。

### 11.12 2026-07-21 12:35–13:32 HKT：r40 Fluxon-only H2D 候选预筛

- 测试前发现两台 GPU pod 各有两个 `inference_like_compute.py` 占满四卡；按独立 PGID
  node0=`19061`、node1=`17463` 精确终止，延时 15 秒确认四卡 `0 MiB/0%` 后才运行微基准；
- 在 30245/32656 的新 H100 上，用真实 36 层、K/V 各 64 KiB/page 对 288–2880 pages 比较现状
  raw DMA 与低提交开销 kernel。raw total 近似严格线性为 `25/50/75/150/249ms`；2880-page
  kernel 约 `279ms`，所以大 batch 切 kernel 不能减少物理恢复时间；
- 新增 127 行 `benchmark_e44_r40_layer_group_submit.py`，比较把 2/3/4/6 个相邻 layer 合成一次
  CUDA batch。两节点结果一致：group=2 在 864/1728 pages 比现状 total 约慢 `0.8/1.8ms`，2880
  pages 仅持平；CPU submit 也未下降。说明大 batch 的 222ms 主要是 copy-engine backpressure，
  不是 36 次固定 API 开销；该方案 no-go；
- 两节点 GPU 分别位于 NUMA1/NUMA0，而旧 owner launcher 都固定 NUMA1。用 taskset 让微基准分别
  从 GPU 本地/远端 CPU 节点 first-touch，raw total 仍稳定在 864-page `74.8ms`、2880-page
  `248.7–248.9ms`；只改 CPU 亲和性没有 H2D 先验，不发正式轮。RDMA NIC 拓扑另有差异，但 r39
  Get Transfer 仅 `10.794ms`，本轮不把它与 H2D 候选混改；
- r39 全量离线对齐显示，多 operation batch=`1130`，同 batch 最早/最晚 operation 创建时间差
  mean/p50/p90/p99=`21.65/14.89/37.71/122.52ms`。按单 operation 288 pages raw H2D 约 25ms 计算，
  “首 operation 提前启动、最终逐层 join”可隐藏上限均值约 `15.91ms/batch`；下一步只实现这一项，
  不增加总 restore bytes、不拆 descriptor、不改变容量 victim 或通用 Mooncake 路径；
- 当前仅有微基准工具新增，active runtime、Fluxon core、SGLang Git 工作树和 r39 封存 artifact 均
  未变。候选尚无代码验收或 QPS，旧 r39 数字不覆盖未来 r40。

### 11.13 2026-07-21 14:28–15:05 HKT：r41 GPU registration 接口与真实 CUDA MR smoke

- Fluxon 新增 caller-owned `GpuBufferRegistration`/`GpuDestination`，registration id 是
  generation token；destination 必须落在同一连续 MR 内，活跃 transfer guard 存在时不能注销；普通
  host `register_buffer` 不再接受 CUDA 类型。SGLang 管理地址、容量和生命周期，Fluxon 不分配显存；
- external variant 现在初始化 closed transfer engine 和零容量 `ClientSegPool`。GPU pointer 明确禁止
  落入 P2P/TCP 的 CPU 解引用 fallback；当前 Get 仍未接入 destination，因此本轮只验注册能力；
- 本地最终净 diff 为 8 文件 `+939/-54`。KV/PyO3 check、fmt、diff、Python compile 和 4 个 GPU
  registry 单测通过；Cargo target 位于 `/dev/nvme0n1p3`；
- release 位于 `/mnt/nvme0/mjq_build/fluxon_e44_r41_gpu_register_smoke_20260721`，wheel/PyO3
  SHA256=`e4fe82b8...8709265`/`29c774da...a4d8cf`，release manifest 通过。r41 安装到独立共享
  venv，没有修改 r39 active symlink；
- 第一次只启动 node0 owner，因配置要求至少一个 eligible owner peer，300 秒后按设计退出；这不是
  `shared.json` 写入 bug。第二次 r41 external 配 r39 owner 时，严格 protocol version
  `1cb188c`/`aafac11` 不匹配，external 在 bootstrap 等待；这一步同样尚未调用 MR；
- 清除两机 `inference_like_compute.py` 并确认四卡 `0 MiB/0%` 后，同时以 r41 启动 node0/node1
  owner。真实 fast-path gate、segment registration 和 `shared.json` 发布完成；master 保持 r39，证明本轮
  未变 wire 可以兼容；
- node0 用 Torch 分配 64 MiB CUDA tensor，closed SDK 真实完成 register；随后校验
  `[ptr+4096, ptr+size-4096)` destination 并注销。输出 `registration_id=1`、
  `elapsed_ms=2085.895`、rc=0。CUDA MR 门禁通过；
- smoke 后 owner/master/control 全部停止，匹配进程和端口为 0；两机 managed idle workload 已恢复，
  四卡约 `8483 MiB/100%`。本轮没有 Get、请求 workload、QPS 或命中结果，不能把 MR 成功写成数据面
  或性能验收；
- 下一步只接 `ExternalSink` Get、GPU destination RDMA 和整批 Done/Revoke，再接 SGLang 固定预算
  staging pool/D2D scatter；不改单 KV victim、Remote Put singleflight、Get32、tier1 5% 或 admission。

### 11.14 2026-07-21 15:05–16:33 HKT：r42 open GPU Get 与隔离 SGLang staging 实现

最终实现边界：

- master 新增 caller-owned `ExternalSink` Get allocation mode；只记录 destination 和 requester
  generation，不分配 CPU slot/holder，不计入 owner/master cache 容量，Done 不发布 route；
- external client 对每个 destination 做 registration generation 和范围校验，后台并发拉取 transferable
  prefix；成功整批 Done，取消、传输错误或未消费尾部整批 Revoke。CUDA 地址没有 CPU/P2P fallback；
- PyO3/Python 增加 `get_start_gpu/get_transfer_gpu/cancel_get_transfer_gpu` 以及强类型 registration、
  destination 和 handle；SGLang 仍负责显存容量、地址和生命周期，Fluxon 不分配显存；
- 隔离 r42 runtime 建 288 页连续 staging，约 `1.266 GiB/TP`。只有同一请求所有 TP 均获得 staging
  才使用 GPU Get；否则完整回退既有 CPU Get。Mamba 保持 CPU 路径，不拆单 KV，不改变容量 victim；
- GPU staging 只在 Transfer 终态后 trim 未命中尾部；成功、取消、异常、reset 和 layerwise finish 都由
  lease 幂等释放。staging 到最终 KV 页沿用现有 restore kernel，并显式选择 D2D，不提交 H2D DMA。

代码与实验账目：

- `Fluxon` 当前 HEAD-relative 最终净 diff 为 13 文件 `+2407/-118`，逐文件数字以 Snapshot 为准。
  r41 的 13 文件 `+1811/-73` 是未独立提交的中间状态；两者代数差只能描述 Snapshot 净变化，不能
  当作全部实施工作量；
- r42 runtime 相对 r39 封存源为 `+337/-95`，adapter 为 `+263/-0`；
- 新增 build/install/deploy/master/owner/run shell、master YAML、validator 和两个 smoke 共 10 文件
  `870` 行。连同 runtime/adapter 的基线差，r42 实验源/编排最终净变化为 `+1470/-95`；
- early-H2D 和本轮临时 10 秒 warmup 都是被覆盖/撤销的中间方案，不计入最终净 diff；其存在和裁决
  分别保留在 11.12、11.15，不能用当前 numstat 冒充中间工作量。

验证与 release：

- Cargo target `/mnt/nvme0/mjq_build/push_sglang_fluxon_target` 经 `findmnt` 确认为
  `/dev/nvme0n1p3`；`cargo fmt --all`、`cargo check -p fluxon_kv`、
  `cargo check -p fluxon_pyo3 --lib`、GPU registry 4 个测试、Python compile、r42 AST/lease validator、
  新增 shell `bash -n` 均通过；
- 32656 真实 H100 上，完整多层与 r42 实际逐层 scatter 均逐字节一致，未选页保持原值；最近一次
  786432-byte full/layerwise 分别约 `0.953/0.124ms`。这里只验 D2D scatter，不验网络；
- 初版 release 构建成功后，跨机 attempt1 暴露 `get_id=0` 校验错误。修复并重打后的 NVMe release 为
  `/mnt/nvme0/mjq_build/fluxon_e44_r42_gpu_direct_staging_20260721`，wheel/PyO3 SHA256=
  `bf1b5f908bacc447a5e664d25e8b02b084fb6d44ce1ba5cff87692f810e89a89`/
  `3ac07f55221e5ad86ce727c380cc908b482480b3cb5cc5357610279ed31a3894`；release manifest 和两机
  安装回读通过。构建、wheel 与随机 I/O 中间目录均在 NVMe，没有写入 Ceph `target/` 或 `/tmp`。

### 11.15 2026-07-21 16:33–17:10 HKT：r42 跨机 GPU Get 两轮失败与 SDK 边界裁决

共同门禁：

- 每轮都先停止 32656/30245 的 burner 和 `inference_like_compute.py`，延时确认四卡均为
  `0 MiB/0%`、compute PID=0，再启动 control/master 和两个 1 GiB smoke owner；
- node1 使用原 local-fast Put 写入同一个 `4,718,592 B` payload，node0 只通过新 GPU Get 接口读到
  Torch CUDA tensor并计划逐字节比较；没有修改正式 workload、Get32、tier1 或容量配置；
- 失败退出均执行 Revoke/清场，master/owner/control 无残留，并恢复两机 managed burner。

attempt1：

- master 正确返回 source=`sglang_l13_owner_external_node1`、target/base 与 GPU destination 完全一致、
  len=`4718592`，但 external plan 校验因 `get_id=0` 报 invalid；
- master `next_get_id` 明确从 0 初始化并 `fetch_add`，普通 Get 从未把 0 当哨兵。修复删除这一条 GPU-only
  假设，抽出 geometry validator，并新增 `gpu_transfer_plan_accepts_zero_as_the_first_master_get_id`；
- 定向测试第一次因未设置 closed SDK `LD_LIBRARY_PATH` 以 rc=127 退出；补上 release
  `closed_sdk/lib` 后测试通过，随后 KV/PyO3 check 通过。这不是断言失败。

attempt2 与判别实验：

- 修复后 Get Start 成功，失败点推进到真实数据传输：closed SDK 没走 RDMA fast path，而调用
  host async-bytes/P2P fallback；open runtime 因 destination 是 GPU guard，按设计返回
  `GPU destination requires the RDMA fast path; P2P fallback is disabled`，整个 Get 被安全 Revoke；
- 为区分首次 peer warmup，smoke 曾临时在 GPU registration 后 sleep 10 秒；仍得到完全相同的
  fallback 失败。该 sleep 随即用补丁删除，源码和 release 中最终 smoke SHA256 都是
  `6ca9bf0a815fc50f56a8a1b654945b21c8c513abeb0833aa9cdcc1a44847c2f2`；
- open/closed `RegisterLocalSegment` wire 只有 addr/size；closed SDK 把公开的 `Closed` 引擎映射为
  PPLX，PPLX 注册固定传 `Device::Host`。当前预编译库还包含
  `cuda support is disabled in host-only fabric-lib build`，其 Cargo 依赖只启用 `fabric-lib/tokio`，未启用
  `fabric-lib/cuda`；
- 因此 r41 只证明 Host-shaped raw 入口没有拒绝 CUDA VA，不能再称为真实 GPU MR。attempt2 没有
  成功传输，也没有 QPS；任何 r39/r34 历史结果都不覆盖当前 r42 代码。

下一门禁：

1. open/closed contract 显式增加 `Host` 与 `Gpu { device_id }` 注册种类，CPU 路径保持 Host；
2. closed/PPLX GPU 注册改用 `Device::Cuda(CudaDeviceId)`，构建并封存真正启用
   `fabric-lib/cuda` 的 SDK artifact；
3. GPU transfer 增加可观察的 direct-only readiness/terminal，不允许先尝试再静默 fallback；
4. 原 4,718,592-byte 两机 smoke 必须逐字节通过、退出闭合、burner 恢复，之后才允许把 r42 接入
   active SGLang 跑固定 S96×T24 正式负载。

### 11.16 2026-07-21 17:10–18:00 HKT：作废记录——误用 closed checkout 的多 MR 实现

> 2026-07-21 18:20 HKT 纠错：本节实现、统计和 Cargo check 均基于错误目录
> `/mnt/ceph/mjq/fluxon_fs_epoll/fluxon_closed`，不是 r43 authority。它们不得作为当前代码、构建或验收
> 结论。正确源码是 `/mnt/ceph/zyc/fluxon_closed/fluxon_closed`，当前仍采用单一
> `local_segment_binding`；r43 只需要 external GPU client 注册一段由 SGLang 持有的 staging MR，不需要
> Host/GPU 多 MR 共存。本节以下内容仅保留为误操作审计和已取消方案，不再执行。

实现结论：

- open/closed wire 同步增加 `Host`/`Gpu { device_id }` 和 `require_fast_path`，schema/ABI 为 `6/9`；
- closed core 的单一 local binding 改为 Host/GPU binding 列表，backend 初启和重建都会重放全部 MR；这一步
  避免 GPU staging 注册覆盖原 CPU pool，保留“部分直达 GPU、其余继续 CPU 缓冲”的实验前提；
- PPLX 本地注册表和远端 metadata 都支持多个带精确范围的 MR。一次 transfer 根据 source/target
  absolute address 选择 MR；远端 cache 里尚无新 GPU MR 时清 cache 并重取一次，不再把单一 descriptor
  假定为整段地址空间；
- GPU MR 使用 `Device::Cuda(CudaDeviceId)`。NIXL/Mooncake 当前显式报不支持，不会把 GPU pointer
  静默当 Host；GPU direct-only 未就绪时返回稳定 marker，open 最多等待 5 秒重试，始终禁止 P2P；
- `te_pplx_cuda` 启用 `fabric-lib/cuda`。GDRCopy 改为独立可选 feature，本轮不依赖节点上不存在的
  `gdrapi`；同时修复原 CUDA feature 中的旧 EFA 常量、UVM import/type 和非主 device MR 注销问题；
- closed SDK 打包器在 `pplx_cuda` 变体中把 `libcudart.so*` 放进 SDK `lib/`，利用 `$ORIGIN` rpath，
  运行时仍使用节点驱动提供的 `libcuda.so.1`。

验证与构建：

- 固定 Cargo target 与 CUDA toolchain 都在 `/mnt/nvme0`，`findmnt` 为 `/dev/nvme0n1p3`；
- `cargo check -p fluxon_commu_closed_sdk --no-default-features --features
  tcp_thread_transport,te_pplx` 通过；
- `CUDA_HOME=/mnt/nvme0/mjq_build/cuda-12.8-fluxon cargo check -p
  fluxon_commu_closed_sdk --no-default-features --features tcp_thread_transport,te_pplx_cuda`
  通过；两者只有既有 warning；
- CUDA 12.8 输入的 `cuda.h/libcudart/libcuda stub` SHA256 分别为
  `4568cc9e...a9acb`/`218eec4c...0f71`/`055e044b...15e8`；
- ABI9 CUDA release 正在 tmux `fluxon_closed_cuda_release` 构建，尚未形成跨机验收结果。

代码统计口径：

- open `Fluxon` 有有效 Git 基线，当前精确净 diff 为 15 文件 `+2489/-112`，逐文件见 Snapshot；
- closed 源没有有效 Git 历史。修改前备份只选择了计划文件，而且其中 `pplx.rs`、
  `build_closed_sdk.py` 等与当时实际源已有偏差；因此下面数字是“当前文件相对选择性参考”的逐文件
  reference delta，**不得作为全部键盘工作量或精确最终净 diff**：

| closed 文件 | reference delta `+/-` | 口径说明 |
|---|---:|---|
| `build_closed_sdk.py` | `+43/-11` | 选择性备份；含备份前已有版本偏差 |
| `fluxon_commu/Cargo.toml` | `+2/-1` | 选择性备份；含原版本号偏差 |
| `fluxon_commu/src/lib.rs` | `约 +1/-0` | 备份未覆盖；只新增 `LocalMemoryKind` re-export，格式化换行不冒充行为量 |
| `fluxon_commu/src/transfer_engine.rs` | `+8/-0` | 选择性备份 |
| `fluxon_commu/src/transfer_engine/client.rs` | `+93/-40` | 选择性备份；含原有格式差异 |
| `fluxon_commu/src/transfer_engine/mooncake.rs` | `+8/-3` | 选择性备份 |
| `fluxon_commu/src/transfer_engine/nixl.rs` | `+9/-4` | 选择性备份 |
| `fluxon_commu/src/transfer_engine/pplx.rs` | `+172/-510` | 参考源含已取消 reverse-copy batching，严重 skew；只可证明不可精确统计 |
| `fluxon_commu_closed_sdk/Cargo.toml` | `+1/-0` | 选择性备份 |
| `fluxon_commu_closed_sdk/include/fluxon_commu_closed.h` | `+2/-2` | 选择性备份，含旧 ABI/schema 偏差 |
| `fluxon_commu_closed_sdk/src/lib.rs` | `+30/-5` | 选择性备份 |
| `fluxon_commu_contract/src/closed_runtime.rs` | `+12/-0` | 选择性备份 |
| `pplx_vendor/fabric-lib/src/cuda_support/real.rs` | `+2/-0` | 选择性备份 |
| `pplx_vendor/fabric-lib/src/efa/efa_domain.rs` | `+4/-20` | 备份未覆盖；以同 vendor 源作参考 |
| `pplx_vendor/fabric-lib/src/fabric_engine.rs` | `+5/-3` | 备份未覆盖；以同 vendor 源作参考 |
| `pplx_vendor/rust/cuda-lib/Cargo.toml` | `+5/-1` | 选择性备份 |
| `pplx_vendor/rust/cuda-lib/src/lib.rs` | `+6/-1` | 选择性备份 |
| `pplx_vendor/rust/cuda-lib/src/gdr_stub.rs` | `+63/-0` | 新文件，精确行数 |

集群门禁变化：

- 17:51 回查时，30245 是两卡 managed burner；32656 出现了不属于 e44 的
  `/pvcteam/mjq/fluxon_s3_benchmark` master/owner/fs-master/fs-agent，且 burner 已停；
- 本轮没有终止或覆盖这些 pre-existing 进程。r43 smoke 必须先确认它们已经退出，或由用户明确允许
  在隔离 cluster/port 下共存；测试清场只能杀本轮 session，并恢复测试前 burner 状态。

### 11.17 2026-07-21 18:00–19:20 HKT：r43 正确 closed CUDA wheel、部署与跨机失败

- 正确 closed authority `/mnt/ceph/zyc/fluxon_closed/fluxon_closed` 已完成 ABI/schema=`9/6` 的
  manylinux CUDA SDK；SDK=`/mnt/nvme0/mjq_build/fluxon_closed_sdk_abi9_pplx_cuda_correct_20260721`，
  release=`/mnt/nvme0/mjq_build/fluxon_e44_r43_gpu_direct_cuda_20260721`；
- wheel SHA256=`81a4d36887568e1bb30761fa47c52fafa03a9548e112f2919497a7ce06873e36`，两机安装后
  PyO3/core/RDMA probe/cudart 哈希和 ABI/schema 回读一致。wheel 包含 `libcudart.so.12`，没有打包
  CUDA stub；`libcuda.so.1` 正确解析节点 NVIDIA Driver；
- 固定输入始终是 key=`fluxon_e44_r42_gpu_get_smoke_20260721`、seed=`73`、`4,718,592 B`。node1
  local-fast Put 成功且 SHA256=`bd0c9278...ed19`；node0 GPU Get 在约 5 秒、约 418–427 次重试后返回
  `fluxon_direct_fast_path_not_ready` 并安全 Revoke，没有 payload 错写；
- 首轮和三轮诊断复跑都没有改变 payload、owner 容量或正式配置。只逐步收窄日志 filter；最后确认一次
  PPLX reverse-copy control batch marker 都没有出现，因此失败发生在真正 transfer submit 之前；
- 每轮退出均由同一个 trap 停止本轮 master/owner/control，恢复 burner；没有正式 workload 或 QPS。
  cleanup 后 node1 的析构 panic 和 master KeyboardInterrupt unwrap 仍属既有停栈问题，不能当作本次
  data-path 根因。

### 11.18 2026-07-21 19:20–19:45 HKT：r44 external↔owner direct-segment gate 修复

根因与方案：

- closed `tier_manager` 的 `should_dial_peer` 只让 external 直连本机 share-group owner，远端 owner1 只能
  经 relay；同时 `direct_transfer_capability` 只给 `Client↔Client` 开 transfer segment，完全没有
  `External↔Client`。因此 external GPU reader 的 `desired transfer peers` 永远没有 owner1，5 秒等待再长
  也不会变 ready；
- 修复后 external 可以对跨机 Client owner 建 direct lane；`External↔Client` 双向只开放
  `enable_transfer_segment=true`，明确保持 `enable_transfer_rpc=false`。同机 owner 仍先被
  `intra_machine_eligible` 截获，不新增本机网络连接，也不改变普通 external RPC 路由或容量驱逐；
- 新增测试分别覆盖“external 会拨号跨机 remote owner”和“两个方向都只开放 segment”。

改动统计：

- 正确 closed `fluxon_commu/src/p2p/tier_manager.rs`：本方向精确 patch delta=`+62/-3`；closed 源无可用
  HEAD，这只是本方向的补丁量，不能冒充 closed 全部累计净 diff；
- `experiment_configs/e44_local_slot_tier_20260716/run_e44_r43_gpu_get_smoke.sh`：`+4/-2`，仅增加
  writer/reader `RUST_LOG` 可配置项；固定 key/seed/size 与清场、cleanup 逻辑均未变化；
- 前三轮被日志 filter 覆盖的诊断运行不是代码实现，不计入净 diff。

验证：

- 构建/测试 target=`/mnt/nvme0/mjq_build/push_sglang_fluxon_target/r43_host_validation`，`findmnt`
  确认为 `/dev/nvme0n1p3`；CUDA 与 prepare resource store 也均位于 NVMe；
- `desired_conn_plan_dials_cross_machine_remote_owner_for_external_gpu_transfer` 与
  `external_owner_direct_capability_is_segment_only_in_both_directions` 在
  `--features te_pplx_cuda` 下均真实执行为 `1 passed / 0 failed`；首次 test binary 启动分别因缺
  `libcudart.so.12`、`libfluxon_rdma_probe.so` 以 rc=127 退出，补齐 `LD_LIBRARY_PATH` 后通过，不是断言失败；
- 全仓 `cargo fmt --all -- --check` 被正确 closed 源内大量既有格式漂移阻断；定向 `rustfmt --check`
  只报告同文件三个既有 import/折行差异。为避免扩大无关 diff，没有批量格式化；新增代码本身按 rustfmt
  形态编写并已通过 Rust 编译；
- 尚未重打 r44 SDK/wheel，也没有跨机成功或 QPS。下一门禁是原 payload 逐字节 smoke，而不是正式负载。

### 11.19 2026-07-21 19:45–19:50 HKT：r44 closed CUDA SDK 构建完成

- 构建产物：`/mnt/nvme0/mjq_build/fluxon_closed_sdk_abi9_pplx_cuda_r44_peer_gate_20260721`；
  构建 target=`/mnt/nvme0/mjq_build/push_sglang_fluxon_target/r44_manylinux_abi9_cuda`，均位于
  `/dev/nvme0n1p3`，没有把构建产物写回 Ceph 或 `/tmp`；
- manifest 回读 ABI/schema=`9/6`，core SHA256=`8978a52d41fa998d4b5b3eab82db186606582d30e5e3d0c78c0c502a748e0f77`，
  probe SHA256=`ad1bc9b3e1c72a9572858fed82a9d903e35463519a90ffbd29468f2fad7dc039`，
  cudart SHA256=`218eec4c8385a32e258a0235be4d449986844f2d0de3430052f0924e6fe60f71`；
- `readelf` 确认 core 显式依赖 `libcudart.so.12`、`libcuda.so.1` 与 `libfluxon_rdma_probe.so`；SDK 内
  打包 cudart/probe，driver 继续由目标节点提供；
- 本条只验收 closed SDK 生成。独立 r44 wheel、两机部署和同一 `4,718,592 B` 逐字节 smoke 尚未完成，
  因此没有正式 QPS，也不能把 r44 写成已通过数据面验收。

### 11.20 2026-07-21 19:51–20:05 HKT：r44 独立 wheel 构建与本机闭包审计完成

- release=`/mnt/nvme0/mjq_build/fluxon_e44_r44_gpu_direct_peer_gate_20260721`，构建脚本 rc=0；
  release profile 用时约 11m55s，最终 wheel SHA256=
  `5cff6fa7d013458000af44daf1a927016baab8bfa5fe197deab2525429d29545`，PyO3 SHA256=
  `460eb98b2185c890cbb3f82ad9a959e214e87e158c634bd609a8a469ef2b287b`；
- `fluxon_release.sha256` 与 r42 staging lifecycle validator 全通过。构建日志只有仓库既有 warning；manylinux
  容器没有宿主 NVIDIA driver，三个临时 Python import 因 `libcuda.so.1` 不存在而给出预期 warning，finalizer
  明确把它作为 target-driver external dependency，没有把 driver 打进 wheel；
- wheel 内含 `libfluxon_commu_core.so`、`libfluxon_rdma_probe.so`、`libcudart.so.12`，不含
  `libcuda.so.1`。本机带真实 driver 的 `ldd` 回读上述依赖均可解析且无 `not found`；PyO3 RUNPATH 指向
  `../fluxon_pyo3.libs`，core RUNPATH 为 `$ORIGIN`；
- auditwheel 会改写 ELF/RPATH，因此 wheel 内库哈希与原 SDK 输入不同：wheel 内 core/probe/cudart 分别为
  `55eb59eb...3d09`、`e925553e...5883`、`5b8de0ee...dc82`。r44 wheel core 也明确不同于 r43 的
  `367cd8ad...ba05`，排除误复用旧 core；
- 仍未完成两机隔离 venv 部署和同 payload smoke，故本条不是跨机 GPU 数据面验收，也没有 QPS。

### 11.21 2026-07-21 20:06–20:08 HKT：r44 两机隔离部署与节点闭包回读完成

- 32656/30245 均部署到独立 release=`/storage/mjq/sglang_fluxon/releases/fluxon_e44_r44_gpu_direct_peer_gate_20260721`
  和 venv=`/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r44-gpu-direct-peer-gate-20260721`；
  sealed r39 与隔离 r43 venv 均未覆盖；
- 两端回读 wheel=`5cff6fa7...9545`、PyO3=`460eb98b...287b`、core=`55eb59eb...3d09`、
  probe=`e925553e...5883`、cudart=`5b8de0ee...dc82`，全部与本地 release 一致；manifest 均为
  ABI/schema=`9/6`；
- 两节点 `ldd` 都从隔离 venv 解析 core/probe/cudart，从各自 `/usr/lib/x86_64-linux-gnu/libcuda.so.1`
  解析 NVIDIA driver，无 `not found`；
- 部署期间没有启动本轮 master/owner/SGLang。下一步仍是脚本内先清 burner 与
  `inference_like_compute.py`，再跑固定 key/seed/size 的跨机逐字节 smoke；部署成功本身不代表数据传输成功。

### 11.22 2026-07-21 20:08–20:11 HKT：r44 smoke 首次清场门禁失败与 runner 加固

- r44 首次 smoke 在 control/master/owner 启动前退出，故没有 Put/Get、没有 GPU transfer、没有 payload
  正误或性能结果；trap cleanup 已执行并恢复 burner；
- 逐 PID 回读确认 30245 GPU0 的 PID 9679 是
  `/opt/conda/bin/python -u /public/zgf/.gpu_burn_script_*.py --gpu 0`。它是旧 burner，但已脱离当前
  watchdog 的 managed PID 状态，所以 `gpu_burner.sh stop 0,1 --no-restart` 没有杀掉它；清场门禁因此正确拒绝发流；
- `run_e44_r43_gpu_get_smoke.sh` 本轮精确 delta=`+4/-1`：先调用 burner 管理脚本，再按命令行对全部
  `.gpu_burn_script_` 和 `inference_like_compute.py` 做 TERM，等待 2 秒后对残留做 KILL。`restore_burner`
  复用同一清场函数，避免旧 orphan 与新 managed burner 并存；
- `bash -n` 通过。下一步必须仍以相同 key=`fluxon_e44_r42_gpu_get_smoke_20260721`、size=`4718592`、
  seed=`73` 重跑，清场成功前不得启动数据面。

### 11.23 2026-07-21 20:11–20:16 HKT：r44 smoke attempt2 在 reader 前丢失 etcd

- 加固后的首轮清场通过：32656/30245 四卡均回读 `0 MiB / 0%`，control、master、两个 owner 均 ready；
- writer 使用原 key/seed/size 成功写入 `4,718,592 B`，payload SHA256=
  `bd0c9278e27fd0bd53070cea6c3da1c2d0b1a36d0b0520c1174baa58387bed19`；
- 随后 runner 在 node0 再次执行 GPU 清场并启动 reader。reader 尚在构造 ClusterManager 时即连续 10 次收到
  `10.233.114.139:34579 connection refused`；因此没有注册 GPU MR，没有发 Get Start，也没有 PPLX transfer
  或逐字节比较。这不能归因于 r44 peer gate；
- etcd 日志只有正常启动，没有 shutdown；`dmesg` 无 OOM/killed-process 记录。master/owner/Greptime 日志在此前均
  正常，尚不能从现有日志区分二次清场误杀与外部默认 tmux/control 干扰；
- trap cleanup 已停本轮会话并恢复两机 burner。本轮没有 QPS。下一门禁改为 control-only 最小复现：启动独立
  control，执行与 reader 前完全相同的清场，再验证 etcd 存活；原因明确并修复前不再跑完整 smoke。

### 11.24 2026-07-21 20:16–20:18 HKT：control-only 排除二次 GPU 清场误杀

- 在 node0 单独清空 GPU 后，以独立 session=`e44_r44_control_probe` 启动同一 control plane；首次
  `etcdctl endpoint health` 成功提交 proposal；
- 随后逐字执行 runner 在 writer 与 reader 之间使用的加固清场：`gpu_burner stop --no-restart`、按命令行
  TERM burner/inference、等待 2 秒、KILL 残留；再等待 10 秒；
- 第二次 `etcdctl endpoint health` 仍成功提交 proposal，tmux session 存活，etcd PID 7703 仍监听同一
  endpoint。由此排除“新清场逻辑误杀 etcd”；
- probe trap 已停 control 并恢复 burner。此时两节点 `run_pilot.py`、`run_case.py`、rclone、
  `fluxon_s3_benchmark`、inference 相关进程均为 0。attempt2 期间曾观察到另一套 benchmark 收尾 shell，
  一次性 control 丢失更符合外部默认 tmux/control 干扰，但没有审计日志足以精确归责，故不伪造确定结论；
- 下一门禁恢复为相同 key/seed/size 的完整 smoke；若再次丢失 control，应把整套实验迁移到独立 tmux socket，
  而不是继续重复运行。

### 11.25 2026-07-21 20:18–20:24 HKT：attempt3 现场锁定 formal GPU guard/default-tmux 冲突

- attempt3 再次完成四卡清场、control/master/owners ready，但 writer 的普通 `local_fast_put_start` 最终以
  P2P 608 timeout 退出；GPU reader、GPU MR、Get 与 PPLX transfer 仍未开始；
- cleanup 后现场保留默认 tmux session=`fluxon-formal-gpu-guard`，创建时间为 12:19:27 UTC；两个 pane 分别
  运行 `/pvcteam/mjq/fluxon_s3_benchmark/rclone_benchmark/scripts/gpu_idle_guard.py`，两卡各占 520 MiB、
  util=0%。脚本源码只创建一个 CUDA tensor 后 sleep 172800 秒；它不是 Fluxon、本轮 burner 或 inference；
- 同一时刻默认 tmux server 只剩 formal guard，本轮 control/master session 已消失；该时间与 writer P2P
  失联吻合。结合 attempt2 的 etcd 消失，根因是另一套 formal benchmark 在本轮运行中启动/接管默认 tmux，
  而不是 r44 external↔owner gate；本轮仍无有效数据面裁决或 QPS；
- runner 新增独立 `TMUX_TMPDIR=/run/fluxon_e44_r44_gpu_get_tmux`，并把它传给 control、master、两个 owner
  以及 cleanup；外部默认 tmux 的 session/kill-server 不再影响本轮。该方向精确 delta=`+12/-8`；
- runner 同时把 `gpu_idle_guard.py` 加入硬门禁。验证包括：`bash -n` 通过；当前 active guard 会被门禁拒绝；
  独立 namespace 的验证 session 与默认 `fluxon-formal-gpu-guard` 可同时存在，杀独立 server 后默认 guard
  仍存活；
- 当前本轮 Fluxon/SGLang/control/inference 均为 0；30245 burner 已恢复。32656 的 formal guard 仍在，导致
  两卡 burner 未恢复；它属于另一套任务，本轮没有擅自终止。下一步需要等 guard 退出，或获得用户明确授权
  停止该 guard，再用独立 tmux namespace 重跑同一 payload。

### 11.26 2026-07-21 20:29–20:32 HKT：用户授权冲突清场，四卡恢复空闲

- 用户明确要求终止冲突的其他进程，授权边界因此覆盖 formal GPU guard、formal benchmark、burner 与
  inference 干扰项；
- 实际执行前回读发现 32656 的 `fluxon-formal-gpu-guard` 与两个 `gpu_idle_guard.py` 已由外部自行退出，
  默认 tmux server 也已不存在；没有再对已退出进程执行 kill；
- 30245 仅剩 managed burner PID 29689/30007，已通过 `gpu_burner.sh stop 0,1 --no-restart` 精确终止。
  该脚本在成功停止两卡后因末尾 shell 条件返回 rc=1，但逐 PID 与 GPU 状态回读确认停止成功；
- 最终两节点 `gpu_idle_guard.py`、pilot/case、burner、inference 与 GPU compute PID 全为 0，四卡均为
  `memory.used=0 MiB, utilization=0%`。没有本轮 Fluxon/SGLang/control 服务；
- 下一步按原 key/seed/size、独立 tmux namespace 立即重跑 r44 correctness smoke，结束后由 trap 恢复 burner。

### 11.27 2026-07-21 20:32–20:37 HKT：clean attempt4 收敛到 external 普通 Put RPC

- 本轮启动前两节点 formal guard、benchmark、burner、inference 和 GPU compute PID 全为 0，四卡均为
  `0 MiB/0%`；control/master/两个 owner 使用独立 tmux namespace 正常 ready；
- writer 在 `local_fast_put_start` 调用中两次等待后失败，错误为 P2P 608、msg_id=4022。源码回读确认 4022 是
  `ExternalBatchPutStartReq`，由 external 以 `RpcTransportPolicy::ForceTransport` 发给其本机 owner；
- master 全程 `put_keys=0/inflight_puts=0`、placement 为空，两个 owner 日志没有
  `handle_external_batch_put_start`，说明请求在进入 owner handler 前丢失/超时；
- 本轮 reader 没有启动，因此没有 GPU registration、Get Start、PPLX transfer 或 payload 比较。结果不能评价
  GPU direct 性能或正确性，但在无外部干扰条件下暴露了 r44 普通 external RPC 回归或初始化竞态；
- trap 已停止独立 tmux 内本轮服务并恢复两机 managed burner。下一步只把 writer RUST_LOG 从 warn 提升为
  info，其他 key/seed/size、二进制和流程不变，以观察 intra-machine lane 与新增 remote direct plan。

### 11.28 2026-07-21 20:37–20:49 HKT：writer 成功、close hang 与 smoke 生命周期隔离

- 同一 r44 二进制、key/seed/size 与编排，仅把 writer `RUST_LOG` 从 warn 提升为 info 后，writer 在 external
  init 完成后约 110ms 内成功完成 msg4022、commit 和 payload 发布，SHA256 仍为 `bd0c9278...ed19`；
  attempt4 的 PutStart timeout 因而是初始化竞态，不是稳定协议破坏；
- 成功后 writer 在 `store.close()` 中无界等待：12:38:58 开始 shutdown，12:39:18 的第 200 次 deferred
  drop 明确报告 ClusterManager/P2pModule 仍有 live `ClientTransferEngineCore` dependent；人工中断后到
  12:44:32 才出现 external shutdown completed。reader 尚未启动，本轮没有 GPU 数据面结果；
- 为继续 correctness 门禁而不把 workaround 混入生产，smoke Python 新增可选
  `--hard-exit-after-success`，精确 delta=`+12/-0`。writer 成功打印已提交哈希后直接退出；reader 只在 transfer
  成功且逐字节一致、并成功注销 GPU registration 后才直接退出。不开该 flag 时原 close 行为完全不变；
- runner 对 writer/reader 增加 `timeout --signal=TERM --kill-after=5s 90s` 并传该 flag，精确 delta=`+4/-4`。
  失败路径不再因 close 永久卡住；这只是 smoke 进程隔离，不是 lifecycle 修复；
- Python 内存编译、shell `bash -n` 通过；两机部署后的 smoke SHA256 均为
  `12ec851fc15535fc307ab45a814d886398f832810f17d0e6315f9015e48c3378`；
- 20:47 32656 又出现外部 `fluxon-quick-gpu-guard`（PID 18007/18010）。按用户授权精确终止 session/PID，
  同时再次停止 30245 burner；最终四卡均为 `0 MiB/0%`。下一步仍是原 payload GPU Get smoke。

### 11.29 2026-07-21 20:49–21:05 HKT：r45 external owner intra-RPC readiness 门禁

- 使用 hard-exit smoke 再跑时，warn 日志下 msg4022 再次超时；此前 info 日志只增加约百毫秒时序便成功，
  证明这是 external 初始化竞态而非 payload、owner handler 或 master 逻辑错误；
- 源码确认 external 的 `owner_shared_mem_bundle_ready` init resource 只等待 shared.json/mmap 和精确 owner
  membership generation，随后立即宣布 framework initialized；它没有等待 P2P tier snapshot 中本机 owner 的
  intra-machine lane ready。首个 `ExternalBatchPutStartReq` 又强制 `ForceTransport`，所以会随机在 lane ready 前提交；
- r45 在同一个 init resource 末尾新增 `wait_current_owner_intra_rpc_ready()`：按精确
  `(owner_id, owner_start_time)` 检查 `is_send_ready_intra_effective`，20ms 轮询，最长 30 秒；超时时携带
  当前 peer snapshot。它不使用固定启动 sleep，不放宽 generation，不接受 remote direct lane，也不修改
  Put/Get/RPC 语义；
- `Fluxon/fluxon_rs/fluxon_kv/src/external_client_api/mod.rs` 相对 r44 release source 精确 delta=`+48/-0`；
  `Fluxon` 当前 HEAD-relative 总净 diff 更新为 17 文件 `+2561/-112`；
- 第一次 `cargo check -p fluxon_kv --lib` 正确捕获 owner `String` 与 P2P `NodeID` 类型不匹配；改为显式
  `owner_node_id` 后，第二次在 `CARGO_TARGET_DIR=/mnt/nvme0/mjq_build/push_sglang_fluxon_target` rc=0，
  target 已确认位于 `/dev/nvme0n1p3`；仅有仓库既有 warning；
- 下一步用原 r44 closed SDK 打独立 r45 wheel。当前检查结果不是 wheel、部署或集群验收。

### 11.30 2026-07-21 21:05–21:21 HKT：r45 独立 wheel 与本机闭包审计完成

- 复用已验收、未改动的 r44 closed SDK=
  `/mnt/nvme0/mjq_build/fluxon_closed_sdk_abi9_pplx_cuda_r44_peer_gate_20260721`，构建独立
  release=`/mnt/nvme0/mjq_build/fluxon_e44_r45_gpu_direct_intra_ready_20260721`；完整脚本 rc=0，
  release profile 用时 `12m49s`；
- Cargo target=`/mnt/nvme0/mjq_build/push_sglang_fluxon_target` 和 release 目录均经 `findmnt` 回读为
  `/dev/nvme0n1p3` 上的 `/mnt/nvme0`，没有把 Cargo 产物写入 Ceph 源码树；
- 最终统一 wheel SHA256=
  `3e04a0b535f2dd76c76d37fb9b2cde41ecb1a44e95d7ee4678c66b37560056c9`，wheel 内 PyO3
  SHA256=`bf61de0b12ba11391533165deb6f3d314605274b365d32f8ab592446f33fa6f5`；
  `fluxon_release.sha256`、ABI3 打包检查、release manifest 和 r42 GPU staging lifecycle validator 全部通过；
- manifest 回读 ABI/schema=`9/6`。在 NVMe 审计目录解包后，wheel 内 core/probe/cudart SHA256 分别为
  `55eb59eb07827010016d320eea0d7615834ea3c21d70148cc15951c081f13d09`、
  `e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883`、
  `5b8de0eec6b33e5f785da05d89869fdbfc58af3ae5af96d7d53a53180429dc82`，与 r44 wheel 的
  closed 组件一致；这是预期结果，因为 r45 只改 open PyO3 所链接的 `fluxon_kv`，closed SDK 未变；
- `readelf` 确认 core 仍显式依赖 `libcudart.so.12`、`libcuda.so.1` 和
  `libfluxon_rdma_probe.so`；wheel 自带 cudart/probe，不打包 NVIDIA driver。本机真实 driver 环境下 PyO3/core
  的 `ldd` 均无 `not found`。manylinux 容器内临时 import 仅因刻意不打包的 `libcuda.so.1` 给出预期 warning；
- 当前只完成本机构建与闭包门禁。r45 尚未部署到 32656/30245，也没有跨机逐字节结果或 QPS；下一步是独立
  r45 release/venv 部署、节点哈希回读、冲突进程清场，再跑完全相同 key/seed/size 的 smoke。

### 11.31 2026-07-21 21:21–21:25 HKT：外部冲突清场与 r45 两机隔离部署

- 部署 preflight 在 32656 发现外部 `/pvcteam/mjq/fluxon_s3_benchmark` quick suite 正在运行：默认 tmux
  session=`fluxon-rclone-bench`，其进程树包含 etcd、Fluxon master/owner/fs master/fs agent 和 rclone formal
  case；30245 只有两卡 managed burner。该套进程不属于本轮，且会触发部署的 live-Fluxon 拒绝门禁；
- 按用户已明确给出的冲突清场授权，精确停止上述 tmux session 与
  `/pvcteam/mjq/fluxon_s3_benchmark` 进程树，并在两机停止 burner、`inference_like_compute.py` 与 GPU guard。
  清场后两端 Fluxon/SGLang/inference/guard/burner 进程均为 0，四卡均回读 `0 MiB/0%`；
- r45 部署到独立 remote release=
  `/storage/mjq/sglang_fluxon/releases/fluxon_e44_r45_gpu_direct_intra_ready_20260721` 与独立 venv=
  `/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r45-gpu-direct-intra-ready-20260721`；没有覆盖 sealed r39、
  r43 或 r44 环境；
- 32656/30245 两端 wheel/PyO3/core/probe/cudart SHA256 均精确回读为
  `3e04a0b5...56c9`、`bf61de0b...a6f5`、`55eb59eb...3d09`、`e925553e...5883`、
  `5b8de0ee...dc82`，manifest 均为 ABI/schema=`9/6`；smoke 脚本两端 SHA256 均为
  `12ec851fc15535fc307ab45a814d886398f832810f17d0e6315f9015e48c3378`；
- 两端 PyO3/core `ldd` 均无 `not found`：core/probe/cudart 从当前 r45 venv 解析，`libcuda.so.1` 从各节点
  `/usr/lib/x86_64-linux-gnu/libcuda.so.1` 解析；
- 本条只验收隔离部署和节点闭包，尚未启动本轮 control/master/owners 或发出 Put/Get。下一步运行固定
  key=`fluxon_e44_r42_gpu_get_smoke_20260721`、size=`4,718,592`、seed=`73` 的逐字节 smoke；退出时必须停止
  本轮服务并恢复 managed burner。

### 11.32 2026-07-21 21:26–21:31 HKT：r45 原 payload smoke 证明门禁选错 lane

- 输入未变：key=`fluxon_e44_r42_gpu_get_smoke_20260721`、size=`4,718,592`、seed=`73`，writer
  `RUST_LOG=warn`；两机启动前再次通过四卡 `0 MiB/0%`、无 benchmark/guard/inference/其他
  Fluxon/SGLang 的硬门禁，control/master/owners 均 ready；
- writer 在 `new_store` 的 `owner_shared_mem_bundle_ready` init resource 等待 30 秒后失败。错误内 peer snapshot
  精确匹配 owner generation `(sglang_l13_owner_external_node1, 1784640484)`，但状态持续为
  `intra_conn_ready=false, direct_conn_ready=true`；这不是 owner 缺席、generation 错配或“再等一会”问题；
- 因 writer 尚未构造成功，本轮没有 Put Start/Commit、GPU registration、Get Start、PPLX transfer 或逐字节
  比较；没有 payload 错写，也没有 QPS。失败是 r45 新门禁自身造成的 fail-closed，不是 GPU 数据面裁决；
- 源码复核 closed `resolve_outgoing_route_to_target()`：它先选择
  `is_send_ready_intra_effective`，否则合法选择 `is_send_ready_direct`，relay 再次之；`ForceTransport` 只禁止
  transfer-RPC fast path，不要求 Iceoryx/intra。open contract 的 `is_any_send_ready` 正是这两个合法直达 lane 的并集；
- 因此 r45 “必须等 intra”假设作废。下一版应保留 exact owner generation 和 30 秒 fail-closed，只把 readiness
  改为 `is_any_send_ready`，并把函数、常量、日志/错误文本从 `intra` 改为 `RPC transport`，避免再次误导；
- runner trap 已停止本轮 control/master/owners 并恢复两机 managed burner；两节点各两卡均回报 managed
  `util=100%`。下一步是上述单点代码修正、NVMe Cargo check、独立 r46 wheel 与同 payload smoke。

### 11.33 2026-07-21 21:31–21:35 HKT：r46 readiness 与 ForceTransport 路由对齐

- 只修改 `Fluxon/fluxon_rs/fluxon_kv/src/external_client_api/mod.rs`：保留 exact
  `(owner_id, owner_start_time)` 校验与 30 秒 fail-closed，把 readiness 从
  `snapshot.is_send_ready_intra_effective()` 改为 `snapshot.is_any_send_ready()`；
- 函数、常量及日志/错误文本同步从 `intra RPC lane` 改名为 `RPC transport route`，并新增 3 行注释说明
  ForceTransport 可以合法使用 effective intra 或 direct。没有修改 wire、RPC policy、Put/Get、GPU registration、
  transfer engine 或 r44 closed SDK；
- r46 相对 r45 的净 delta 是 `+3/-0` 加若干等行替换；`Fluxon` HEAD-relative 总净 diff 更新为 17 文件
  `+2564/-112`。r45 是未独立提交且已被当前工作树覆盖的中间错误实现，不能计为额外最终净 diff；
- 首次校验命令因工作目录已在 `Fluxon`、却再次拼接 `Fluxon/...` 路径而立即失败，没有执行格式或编译；修正
  invocation 后，`git diff --check`、全 workspace `cargo fmt --all -- --check` 均 rc=0；
- `CARGO_TARGET_DIR=/mnt/nvme0/mjq_build/push_sglang_fluxon_target cargo check -p fluxon_kv --lib`
  rc=0，用时约 15.46 秒，仅有仓库既有 warning；target 仍位于 `/dev/nvme0n1p3`；
- 当前验证只覆盖源码门禁。下一步复用原 r44 closed SDK 构建独立 r46 wheel并审计闭包，再部署到独立 r46
  venv；同一 key/size/seed 的跨机逐字节 smoke 成功前不运行正式 QPS。

### 11.34 2026-07-21 21:35–21:50 HKT：r46 独立 wheel 与本机闭包审计完成

- 复用未改动的 r44 closed SDK，构建独立 release=
  `/mnt/nvme0/mjq_build/fluxon_e44_r46_gpu_direct_rpc_route_ready_20260721`；完整脚本 rc=0，release profile
  用时 `12m59s`，Cargo target 与 release 均在 `/dev/nvme0n1p3`；
- 统一 wheel SHA256=
  `85cfc1fecced5a6af28b24cbe4049e8e449ec33a8e9572d38cacc118e97f1a5b`，wheel 内 PyO3
  SHA256=`581825251bc00c68c6409579602e14ceb92fe4b8fabe51485e5fa65776ec6575`；二者均不同于
  r45 的 `3e04a0b5...56c9` / `bf61de0b...a6f5`，证明 any-send-ready 修正进入实际 wheel；
- `fluxon_release.sha256`、ABI3 打包检查、release manifest 和 r42 GPU staging lifecycle validator 全通过，
  manifest 回读 ABI/schema=`9/6`；manylinux 临时 import 仍只因刻意 external 的 `libcuda.so.1` 给出预期 warning；
- 在 NVMe 审计目录解包后，core/probe/cudart SHA256 分别保持
  `55eb59eb07827010016d320eea0d7615834ea3c21d70148cc15951c081f13d09`、
  `e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883`、
  `5b8de0eec6b33e5f785da05d89869fdbfc58af3ae5af96d7d53a53180429dc82`，与 r44/r45 一致，符合
  closed SDK 未变的单变量预期；
- 本机真实 driver 下 PyO3 `ldd` 从 wheel 解析 core/probe/cudart、从系统解析 `libcuda.so.1`，无
  `not found`。本条仍不是跨机正确性验收；下一步是独立 r46 两机部署与原 payload smoke。

### 11.35 2026-07-21 21:50–21:53 HKT：r46 两机隔离部署与节点闭包回读

- 部署 preflight 显示 32656/30245 只有各自两卡 managed burner；外部 benchmark、Fluxon/SGLang、GPU guard
  与 `inference_like_compute.py` 均为 0。部署阶段没有启动本轮服务或占用额外 GPU；
- r46 部署到独立 remote release=
  `/storage/mjq/sglang_fluxon/releases/fluxon_e44_r46_gpu_direct_rpc_route_ready_20260721` 与 venv=
  `/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r46-gpu-direct-rpc-route-ready-20260721`，未覆盖 sealed r39
  或 r43/r44/r45 隔离环境；
- 两端 wheel/PyO3/core/probe/cudart SHA256 均精确为 `85cfc1fe...1a5b`、`58182525...6575`、
  `55eb59eb...3d09`、`e925553e...5883`、`5b8de0ee...dc82`；manifest 均为 ABI/schema=`9/6`，
  smoke 脚本 SHA256 均为 `12ec851fc15535fc307ab45a814d886398f832810f17d0e6315f9015e48c3378`；
- 两端 `ldd` 均从当前 r46 venv 解析 core/probe/cudart，从节点
  `/usr/lib/x86_64-linux-gnu/libcuda.so.1` 解析 driver，无 `not found`；
- 下一步运行相同 key=`fluxon_e44_r42_gpu_get_smoke_20260721`、size=`4,718,592`、seed=`73`、writer
  `warn` 的 smoke。runner 会先停止 burner 并要求四卡 `0 MiB/0%`，退出时停止本轮栈并恢复 burner。

### 11.36 2026-07-21 21:53–22:00 HKT：r46 attempt1 数据比较通过、成功上报脚本失败

- 输入与门禁未变：key=`fluxon_e44_r42_gpu_get_smoke_20260721`、size=`4,718,592`、seed=`73`、writer
  `warn`；启动前两机四卡均为 `0 MiB/0%`，control/master/owners ready；
- writer 不再触发 r44 msg4022 竞态，也不再被 r45 intra-only 门禁卡住；它成功写入 `4,718,592 B`，SHA256=
  `bd0c9278e27fd0bd53070cea6c3da1c2d0b1a36d0b0520c1174baa58387bed19`；
- reader 的 exact-generation owner RPC route 门禁在 `21ms` 后通过；随后 closed runtime 打印
  `FLUXON_PPLX_REVERSE_COPY_BATCH batch_number=1 batch_items=1 total_items=1 peer=sglang_l13_owner_external_node1`，
  证明实际进入远端 owner→external GPU staging 的 PPLX reverse-copy，而非 CPU fallback；
- reader 在 `torch.cuda.synchronize` 后把 GPU staging 拷回 CPU，计算 `actual_sha256` 并执行
  `if actual != expected: raise`；该分支没有触发，随后 `unregister_gpu_buffer` 成功。这是内存逐字节比较已通过的
  代码路径证据；
- success 打印前的 smoke-only 生命周期改动存在顺序 bug：脚本在 hard-exit 路径先注销 registration、设置
  `registration=None`，然后 JSON 又访问 `registration.registration_id`，因此抛出
  `AttributeError: 'NoneType' object has no attribute 'registration_id'`。runner 最终 rc=1，不能把该轮写成完整
  smoke passed；生产 API/数据面没有报错，也不是 payload mismatch；
- cleanup 已停止本轮 control/master/owners。30245 的 `gpu_burner.sh stop` SSH 一度超时，人工终止残留
  watchdog/burner 后重新执行 start；最终两节点均恢复两卡 managed burner，服务/inference/guard/外部 benchmark
  为 0；
- 下一步只修 smoke：注销前保存 `registration_id`，JSON 使用保存值。Python compile、两端脚本哈希同步后复用
  同一 r46 wheel/venv 原样重跑；完整 rc=0 前不运行正式 QPS。

### 11.37 2026-07-21 22:00–22:02 HKT：smoke 成功上报顺序修复

- 只修改 `experiment_configs/e44_local_slot_tier_20260716/smoke_e44_r42_gpu_get.py`：在 registration
  成功返回后保存 `registration_id`，success JSON 使用保存值；hard-exit 路径仍先注销 MR，再打印成功并
  `os._exit(0)`；
- 精确 delta=`+1/-1`。没有修改 r46 Rust/Python production API、wheel、closed SDK、key/size/seed 或 runner
  流程，因此无需重打 wheel，下一轮仍裁决同一个数据面实现；
- Python 内存编译、runner `bash -n` 与静态顺序回读通过；新脚本 SHA256=
  `36cd173d4937f72a75e98bd3d5cca4732fbe298d23c32d29b0ab92d44a889c46`，32656/30245 两端回读一致；
- 下一步复用相同 r46 release/venv 原样重跑。必须看到 writer 固定哈希、reader `status=passed` 同哈希、runner
  最终 passed/rc=0，且 cleanup 后服务为 0、burner 恢复，才完成 correctness smoke。

### 11.38 2026-07-21 22:03–22:11 HKT：r46 attempt2 复现 msg4022 并定位 init 顺序根因

- 复用完全相同 r46 wheel/venv，只同步已验收的 smoke 上报修复；key/size/seed、writer `warn`、独立 tmux 与
  GPU 清场门禁均未变。control/master/owners ready 后，writer 的 msg4022 `ExternalBatchPutStartReq` 再次等待
  30 秒并以 P2P 608 timeout 失败；reader 未启动；
- node1 owner 在 `14:04:01.288Z` 已报告 owner framework initialized，`14:04:02.294Z` 写出 shared.json；
  失败前后 owner Put/remote-flight snapshot 始终为 0，说明这不是 Put 处理慢，而是首个 external→owner RPC
  没有完成请求/响应闭环；
- r46 attempt1 的真实 PPLX transfer 和逐字节比较仍是有效的单轮数据面证据，但 attempt2 证明它不稳定，不能
  将 r46 封为 correctness baseline；
- 源码顺序给出统一解释：`wait_owner_shared_mem_bundle_ready_for_init_resource()` 先等待 route，随后才进入
  `init2_after_owner_shared_mem_bundle_ready()`；后者先注册 RPC handlers，再调用
  `set_self_share_group_binding()`。绑定发布前 external 不具备同 owner share-group 元数据，closed tier manager
  不会建 intra，只会因 r44 peer gate 暂时建立 direct；绑定发布后，同机同组策略转为 intra-only并拆 direct；
- 因此 r45 在绑定前强等 intra 必然超时；r46 在绑定前看到 direct 就返回，随后首个 PutStart 与 direct→intra
  拓扑切换竞态，表现为 attempt1 偶发成功、attempt2 超时。单纯 `is_any_send_ready` 不是充分门禁；
- 正确顺序应是：resource 只完成 shared memory + exact owner membership；`init2_after...` 注册 handlers，发布
  exact owner share-group binding 与 sub-cluster，然后等待 exact owner generation 的
  `is_send_ready_intra_effective`，稳定后才允许 external init 完成。该等待不是固定 sleep；
- cleanup 已停本轮 control/master/owners并恢复两机 managed burner；当前两端各两卡约
  `1395 MiB/100%`，无其他 Fluxon/SGLang/inference/guard/benchmark。下一步实现上述顺序为 r47，重新完成
  NVMe Cargo/wheel/部署/同 payload smoke 门禁。

### 11.39 2026-07-21 22:11–22:14 HKT：r47 binding 后稳定 intra 门禁

- `wait_owner_shared_mem_bundle_ready_for_init_resource()` 不再等待 P2P route，只负责 shared memory 映射与
  exact owner membership；这样 init resource 不会在 external 尚未发布 share-group binding 时观察临时 direct；
- `init2_after_owner_shared_mem_bundle_ready()` 保留“先注册 RPC handlers、再发布 metadata”的安全顺序；在
  `set_self_share_group_binding(exact owner generation)` 和 `set_self_sub_cluster()` 成功后，新增调用
  `wait_current_owner_intra_rpc_ready_after_binding()`，稳定后才继续完成 external init；
- 新 wait 同时检查：tier snapshot 的 self share-group binding 等于预期 owner ref、owner peer generation 的
  `node_start_time` 精确匹配、`is_send_ready_intra_effective(peer_gen)` 为真。它不接受绑定前/切换中的 direct，
  20ms 轮询、30 秒 fail-closed；超时错误同时输出 self binding 和 owner peer snapshot；
- 只修改 `Fluxon/fluxon_rs/fluxon_kv/src/external_client_api/mod.rs`，不改 wire、closed SDK、Put/Get 或 GPU
  transfer。相对 r46 最终净增 `+10/-0` 并有等行替换；`Fluxon` 总净 diff 更新为 17 文件 `+2574/-112`；
- `git diff --check`、全 workspace `cargo fmt --all -- --check`、固定 NVMe target 的
  `cargo check -p fluxon_kv --lib` 均 rc=0；Cargo check 用时约 16.01 秒，仅有既有 warning；
- 当前尚未构建 r47 wheel或集群验收。下一步复用未改的 r44 closed SDK，完成独立 wheel/闭包/部署后跑同一
  key/size/seed、writer `warn` smoke；稳定 rc=0 前不运行正式 QPS。

### 11.40 2026-07-21 22:14–22:33 HKT：r47 独立 wheel 与本机闭包审计

- 复用未改的 r44 closed SDK=`/mnt/nvme0/mjq_build/fluxon_closed_sdk_abi9_pplx_cuda_r44_peer_gate_20260721`，
  构建独立 release=`/mnt/nvme0/mjq_build/fluxon_e44_r47_gpu_direct_post_binding_intra_ready_20260721`；
  release profile 用时 `12m57s`，完整封装脚本 rc=0。Cargo target 与 release 均由 `findmnt` 确认在
  `/dev/nvme0n1p3` 上，未向 Ceph 源码树的 `target/` 写入产物；
- 统一 wheel SHA256=`983e46057168bb6ba69fb1fd03fea146003155877da70668d5d60b0c1f461d5a`，wheel 内 PyO3
  SHA256=`ef48cf9852440a6bb33eefc9d036cf6cec3f2f5f7386d09230c0abcdbf35b162`；二者都不同于 r46，
  证明 binding 后 readiness 顺序修正进入实际部署产物；
- `fluxon_release.sha256`、ABI3 打包检查、release manifest 和 r42 GPU staging lifecycle validator 全部通过；
  closed manifest 回读 ABI/schema=`9/6`。manylinux 容器的 import warning 仍只是因为刻意不打包节点 driver
  `libcuda.so.1`，不是闭包缺失；
- NVMe 审计目录解包后，core/probe/cudart SHA256 分别为
  `55eb59eb07827010016d320eea0d7615834ea3c21d70148cc15951c081f13d09`、
  `e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883`、
  `5b8de0eec6b33e5f785da05d89869fdbfc58af3ae5af96d7d53a53180429dc82`，与 r44–r46 一致，符合
  closed SDK 未改的单变量预期；
- `readelf` 确认 core 显式依赖 cudart、CUDA driver 和 RDMA probe；本机 PyO3/core `ldd` 均从当前
  wheel 解析 core/probe/cudart，从系统解析 `libcuda.so.1`，无 `not found`；
- 本条只验收本地产物。r47 尚未部署到 32656/30245，也没有新的跨机正确性或 QPS 结果。
  下一步是隔离部署、节点闭包回读，然后用原 key/size/seed 连续跑两轮 smoke。

### 11.41 2026-07-21 22:33–22:37 HKT：r47 两机隔离部署与节点闭包回读

- 部署前 32656/30245 均只有各自两个 managed burner；Fluxon/SGLang、`inference_like_compute.py`、GPU guard、
  pilot/case/rclone 外部 benchmark 均为 0。部署阶段未停 burner，也未启动或发流；
- r47 复制到两机独立 release=
  `/storage/mjq/sglang_fluxon/releases/fluxon_e44_r47_gpu_direct_post_binding_intra_ready_20260721`，安装到独立 venv=
  `/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r47-gpu-direct-post-binding-intra-ready-20260721`；没有覆盖
  sealed r39 或 r44–r46 隔离环境；
- 32656/30245 两端 wheel/PyO3/core/probe/cudart SHA256 均精确为 `983e4605...61d5`、
  `ef48cf98...b162`、`55eb59eb...3d09`、`e925553e...5883`、`5b8de0ee...dc82`；closed manifest
  均回读 ABI/schema=`9/6`，smoke 脚本均为 `36cd173d...9c46`；
- 两端 PyO3/core `ldd` 均无 `not found`：core/probe/cudart 从当前 r47 venv 解析，`libcuda.so.1`
  从各节点 `/usr/lib/x86_64-linux-gnu/libcuda.so.1` 解析；
- 本条只验收隔离部署。下一步由 runner 停止 burner/其它冲突进程、确认四卡为空，再跑
  key=`fluxon_e44_r42_gpu_get_smoke_20260721`、size=`4,718,592`、seed=`73`、writer `warn` 的原 smoke。

### 11.42 2026-07-21 22:37–22:41 HKT：r47 固定 payload smoke attempt1 完整通过

- runner 先精确停止两机 managed burner 和 `inference_like_compute.py`，四卡均回读 `0 MiB/0%`；
  启动前无 Fluxon/SGLang、GPU guard、pilot/case/rclone 外部 benchmark。输入仍为
  key=`fluxon_e44_r42_gpu_get_smoke_20260721`、size=`4,718,592`、seed=`73`、writer `RUST_LOG=warn`；
- control/master/两 owner 全部 ready；writer 成功写入，SHA256=
  `bd0c9278e27fd0bd53070cea6c3da1c2d0b1a36d0b0520c1174baa58387bed19`；
- reader 的 r47 新门禁明确打印：发布 share-group binding 后等待 exact owner generation 的 intra-machine
  route，约 `2026ms` 后 ready。这一次没有在 binding 前误放行临时 direct；
- 随后 closed runtime 打印 `FLUXON_PPLX_REVERSE_COPY_BATCH batch_number=1 batch_items=1 total_items=1`；
  reader 在 CUDA synchronize 后把 staging 回读 CPU，逐字节比较未触发 mismatch，打印相同 SHA256 和
  `status=passed`，随后 GPU registration 注销成功；
- writer、reader、runner 全部 rc=0，最终打印
  `e44_r47_gpu_get_smoke_attempt1 remote-owner GPU Get data smoke: passed`。cleanup 后本轮服务与其它冲突进程为 0，
  两机 managed burner 已恢复；
- 本轮已完整通过，但 r46 曾出现 attempt1 成功、attempt2 失败，因此尚不封稳定 correctness baseline。
  下一步是不改 wheel、脚本或输入，重新完整清场后跑 attempt2。

### 11.43 2026-07-21 22:41–22:44 HKT：r47 固定 payload smoke attempt2 连续通过与正确性裁决

- 复用 attempt1 的同一 r47 wheel/venv、smoke 脚本、key=`fluxon_e44_r42_gpu_get_smoke_20260721`、
  size=`4,718,592`、seed=`73` 和 writer `RUST_LOG=warn`；只改变本轮 session/instance tag，不改数据面或负载。
  runner 再次先停 burner/冲突进程，四卡启动前均为 `0 MiB/0%`；
- writer 第二次成功写入固定 SHA256=
  `bd0c9278e27fd0bd53070cea6c3da1c2d0b1a36d0b0520c1174baa58387bed19`；没有再现 r46 attempt2 的
  msg4022/P2P 608 超时；
- reader 明确在 share-group binding 发布后等待当前 owner exact generation，约 `2000ms` 观察到
  intra-machine route ready；closed runtime 再次打印
  `FLUXON_PPLX_REVERSE_COPY_BATCH batch_number=1 batch_items=1 total_items=1`；
- GPU staging synchronize 后的 CPU 回读逐字节比较再次通过，reader 打印同一 SHA256 与 `status=passed`，
  GPU registration 注销成功；writer、reader、runner 全部 rc=0，最终打印
  `e44_r47_gpu_get_smoke_attempt2 remote-owner GPU Get data smoke: passed`；
- cleanup 后两机 Fluxon/SGLang、`inference_like_compute.py`、GPU guard 和外部 benchmark 均为 0；四卡
  managed burner 已恢复，每卡约 `1395 MiB/100%`；
- 裁决：r47 连续两轮在同一固定 payload 上完成 writer→remote owner→PPLX/RDMA→external GPU staging
  的逐字节正确性闭环，并排除 r46 的 binding 切换竞态。因此 r47 可封为 remote-owner GPU Get
  correctness smoke 基线。它尚不是完整 SGLang 正式负载、容量压力或 QPS 验收；当前停止实验并等待
  用户下一步指令。

### 11.44 2026-07-21 22:44–23:03 HKT：完整固定负载请求、CPU 节点离线与 host-only r47 产物准备

- 用户明确要求完整跑并拿到新指标。本轮固定对照口径为 r39 的 S96×T24、2304 请求、
  concurrency 24、system 8192、output 8、session-stream、Get32、tier1 5%、end-depth288、DMA0 和
  metadata-only 128/128/256 GiB；不更换 workload 或容量；
- 正式轮 preflight 发现原 CPU owner 公网 SSH=`116.238.240.2:30729` 立即 `Connection refused`；
  从 32656 所在 node0 探测内网 `10.233.125.121:22/2222` 也均关闭。工作区无第二个已规约
  CPU owner 映射。若忽略该节点发流，会把 128/128/256 GiB 改成无 L3 的两节点实验，故未启动栈、
  未发请求，也不伪造“完整指标”；
- r47 GPU wheel 显式依赖 `libcuda.so.1`，CPU-only 节点不应使用 driver stub 或伪装 GPU 闭包。因此启动
  同一 open/source、ABI/schema=`9/6` 的 host-only PPLX closed SDK 构建；target=
  `/mnt/nvme0/mjq_build/push_sglang_fluxon_target/r47_manylinux_abi9_host`，SDK=
  `/mnt/nvme0/mjq_build/fluxon_closed_sdk_abi9_pplx_host_r47_20260721`，均在 `/dev/nvme0n1p3`；
- 首次构建为节约时间复制了 r44 CUDA target 的 native cache，链接器因 CMake 导出仍写死
  `/cargo_target/r44_manylinux_abi9_cuda/...` 而正确失败；该轮没有生成可用 SDK。已只删除本轮新建的
  r47 target/SDK，改为从空 target 完整 materialize 后重建；
- 当前 GPU 两节点仍只有 managed burner，r47 smoke 服务和其它冲突进程为 0。下一步在 CPU 节点
  恢复且 host-only 产物门禁通过后，才能开始三节点完整正式轮。

### 11.45 2026-07-21 23:03–23:11 HKT：CPU host-only ABI9 SDK 通过与 r47 正式轮编排门禁

- 从空 NVMe target 重建 host-only PPLX SDK 成功；release profile 用时约 `1m04s`，SDK=
  `/mnt/nvme0/mjq_build/fluxon_closed_sdk_abi9_pplx_host_r47_20260721`，manifest SHA256=
  `f1dad86c378f82214ecdffb826ec163b0c248996f5100a0b19ab2e5ee5c45777`，core/probe SHA256=
  `37c69516795e0f09ba4009d746bb5e4333c928497aa9a049178666ce18c9aded`/
  `ad1bc9b3e1c72a9572858fed82a9d903e35463519a90ffbd29468f2fad7dc039`；
- manifest 回读 ABI/schema=`9/6`；`readelf` 的 NEEDED 中没有 `libcuda`/`libcudart`，`ldd` 从 SDK 解析
  `libfluxon_rdma_probe.so` 且无 `not found`。这是 CPU-only owner 的正确闭包，不是用 driver stub 绕过验证；
- 已用该 SDK 启动同一 r47 open/source 的 CPU wheel 构建，release=
  `/mnt/nvme0/mjq_build/fluxon_e44_r47_gpu_direct_full_cpu_host_20260721`，构建仍在进行，尚无最终 wheel
  或 PyO3 哈希；
- 正式轮编排保持已验证的通用 launcher，只把原硬编码 core/probe 哈希收紧为 variant 变量。
  新 r47 variant 固定 Get32、tier1 5%、end-depth288、batch32、DMA0、r42 staging 两个源文件哈希
  和独立 GPU/CPU venv；master YAML 与 r39 除隔离 `log_dir` 外逐行一致；
- 新增 `deploy_e44_r47_gpu_direct_full_enddepth288_netobs.sh` 169 行，在部署时分别审计 GPU CUDA wheel
  与 CPU host-only wheel，拒绝 CPU wheel 中的 CUDA 库，并回读两端 SGLang r42 staging 及 metadata-only
  host pool 哈希。该脚本及所有修改 launcher `bash -n` 通过；
- 本方向当前编排净改动为 6 文件 `+225/-5`：新增 deploy 169 行、master YAML 28 行；
  variant `+23/-0`，GPU/CPU launcher 各 `+2/-2`，guard `+1/-1`。CPU wheel 内 core/probe 哈希仍保留
  `PENDING` 占位，这是刻意 fail-closed；完成闭包审计前脚本不能发流。

### 11.46 2026-07-21 23:11–23:20 HKT：r47 CPU host-only wheel 完成与三节点产物闭环

- CPU release=`/mnt/nvme0/mjq_build/fluxon_e44_r47_gpu_direct_full_cpu_host_20260721`，release profile
  用时 `11m48s`，完整构建/打包脚本 rc=0；Cargo target 和 release 均在 `/dev/nvme0n1p3`；
- 统一 CPU wheel SHA256=`6e23ad05c65d1dc954b4af33164464c7d70b399132866067c276f7842041db9b`，
  PyO3 SHA256=`ef48cf9852440a6bb33eefc9d036cf6cec3f2f5f7386d09230c0abcdbf35b162`。PyO3 与已连续两轮
  smoke 通过的 GPU wheel 完全相同，证明 CPU/GPU 分产物没有分叉 open r47 逻辑；
- CPU wheel 解包后 core/probe SHA256=`63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06`/
  `e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883`。wheel entry、core NEEDED 和
  `ldd` 三道门禁均确认无 `libcuda`/`libcudart`、无 `not found`；
- release manifest、ABI3 cp310/cp311/cp312 import、r42 GPU staging lifecycle validator 均通过；closed manifest
  回读 ABI/schema=`9/6`；当前 `external_client_api/mod.rs` 与 CPU release 封存源的 SHA256 均为
  `22a3e7b766e10a803046ced1eb892aa691fa47afe71374c1da6478bca51ff940`；
- variant 中 CPU core/probe 的 `PENDING` 占位已替换为上述实际 wheel 哈希；`bash -n`、无占位检查和
  哈帏对齐均通过。本地三节点产物与编排已齐备；
- 23:20 HKT 再次探测时，CPU 公网 30729 仍 `Connection refused`，内网
  `10.233.125.121:22/2222` 仍关闭。因此本条尚没有部署、启栈、请求或新 QPS；不能把产物完成
  写成正式轮验收。

### 11.47 2026-07-21 23:20–23:28 HKT：r47 正式 GPU 部署通过，CPU 节点仍离线

- 用户再次要求完整跑并获得新指标。本轮不改已锁定的 S96×T24、2304 请求、concurrency 24、
  system 8192、output 8、session-stream、Get32、tier1 5%、end-depth288、DMA0 和 metadata-only
  128/128/256 GiB；
- 本地重跑 `bash -n`、NVMe `findmnt` 和 r42 staging lifecycle validator 全部通过。部署前 32656/30245
  均只有两个 managed burner；Fluxon/SGLang、`inference_like_compute.py`、GPU guard 和外部 benchmark 为 0。
  部署阶段没有停 burner、启动服务或发送请求；
- 32656 和 30245 均已切换到正式 GPU release=
  `/storage/mjq/sglang_fluxon/releases/fluxon_e44_r47_gpu_direct_full_enddepth288_netobs_20260721` 与 venv=
  `/storage/zth/sglang_l13_fluxon_v2/venv-fluxon-e44-r47-gpu-direct-full-enddepth288-netobs-20260721`；两端回读
  wheel/PyO3/core/probe/cudart=`983e4605...61d5`/`ef48cf98...b162`/`55eb59eb...3d09`/
  `e925553e...5883`/`5b8de0ee...dc82`，均与预期精确一致；
- 两端同时安装 metadata-only host pool 与已验收 r42 radix/adapter，部署脚本的 Get32、DMA0、
  end-depth288、lifecycle 和哈希门禁全部通过。这些是 GPU 部署验收，不是正式性能结果；
- CPU 公网 `116.238.240.2:30729` 在 23:20–23:28 多次探测均为 `Connection refused`。从 GPU 节点对
  `10.233.125.121` 的 ping 和 `22/2222` 也无响应，证明是 CPU pod/节点离线，不是公网 SSH
  单点抖动。为了不把 128/128/256 GiB 基线偷换为无 CPU/L3 的两节点实验，尚未停 burner、
  启栈或发流，因此当前仍没有 r47 新 QPS；
- 下一门禁只剩 CPU 节点恢复，或获得同规格 CPU owner 的新公网 SSH/内网 IP 映射。一旦可达，
  先部署并回读 host-only wheel/ABI/`ldd`，再停两机 burner/inference/冲突进程、确认四卡
  `0 MiB/0%`，启动三端 HCA observer/Greptime/control/master/owners/SGLang/router 并发完固定 2304 请求。
- 另外核对了历史上曾获授权的 2 TiB 备用机 `116.238.240.2:31772`。它虽可达、内存充足并有
  `10.233.121.37`，但容器缺 `CAP_IPC_LOCK`，历史实测 Mooncake 在两组 HCA 上都于 `ibv_create_cq`
  返回 `ENOMEM`；当前还在运行另一套 `/tmp/fluxon_gpu_bench` Fluxon testbed。它不具备原 CPU pod
  的相同 capability/内网地址/空闲运行条件，故未用它偷换正式基线；
- 23:33 HKT 最终复核：30729 仍关闭；两个 GPU 节点没有 Fluxon/SGLang/inference/guard/外部
  benchmark，只有各自两个 managed burner 和 watchdog，四卡均约 `1395 MiB/100%`。已停止临时端口
  监视进程；当前无遗留实验服务。

### 11.48 2026-07-22 19:39–19:42 HKT：CPU SSH 服务恢复但公钥授权未恢复

- 用户表示机器已 ready 并要求继续固定正式轮。32656/30245 均可达且 IP 仍为
  `10.233.114.139/10.233.114.138`；30729 从前一日的 `Connection refused` 变为可完成 SSH 握手；
- 30729 当前 RSA/ECDSA/ED25519 host-key fingerprint 与本地历史 known-host 精确一致，
  排除连到不相干 SSH 服务的情况；但 `root` 返回
  `Permission denied (publickey,password)`；
- 已用 SSH agent 及工作区全部六把现有私钥显式 `IdentitiesOnly` 尝试，并检查
  `root/ubuntu/zyc/mjq/admin` 用户，均被拒绝。其中默认 agent 钥 fingerprint=
  `SHA256:usaXva3x7CR11A4vetk7kgkKhAfOe/1D7lX883jBF9M`；
- 从 32656 和已配置的 gvc 跳板复查，旧 CPU 内网 `10.233.125.121:22/2222` 仍全部超时；
  GPU 内部密钥也无法通过公网映射登录。因既无 SSH 权限也不知当前 CPU 内网 IP，
  无法部署/回读 r47 host-only wheel；
- 19:41–19:42 HKT 又连续重试六次，结果仍为公钥拒绝。本轮没有停 GPU burner、没有启动
  control/master/owner/SGLang，也没有发送请求；因此仍没有 r47 新 QPS。下一门禁是恢复
  30729 root 的 authorized key，或提供新的可登录 SSH/内网 IP。

### 11.49 2026-07-22 截至 20:29 HKT：CPU 恢复、r47 正式 TP2 启动失败与闭环清场

- 用户提供的 `infra44_ed25519` 私钥可登录 30729；CPU 新内网 IP 回读为 `10.233.125.128`。GPU、CPU 和
  workload launcher 中旧 `.121` 地址各做一次精确替换，合计 `+3/-3`，没有改变负载、容量或缓存参数；
- r47 三端部署哈希全部通过：GPU wheel/PyO3/core=`983e4605...61d5`/`ef48cf98...b162`/
  `55eb59eb...3d09`，CPU core=`63c08ee6...6e06`。三端 observer、control、Greptime、master、CPU owner、
  两 GPU owner 和 128/128/256 GiB reserve 均成功；
- 两台 GPU 节点的 SGLang 都在 HTTP ready 前同形失败：TP0 完成 GPU staging 注册，TP1 的
  `register_gpu_buffer(device_id=1)` 返回 PPLX `Worker not found`。保持 owner 不变执行原生
  `SGLANG_ONLY` 重试仍稳定复现，排除 CPU IP、启动顺序和随机波动；
- 本轮没有发送任何正式请求，不存在 QPS。失败栈已停止，两机 managed burner 已恢复到每卡约
  `1395 MiB/100%`，无本轮推理、Fluxon、observer 或 benchmark 残留。

### 11.50 2026-07-22 截至 20:29 HKT：r48 单 RDMA worker 非零 CUDA device 修复

- 根因位于正确 closed 源的 `pplx_vendor/fabric-lib/src/fabric_engine.rs`：每个 external 进程只创建一个
  key=`0` 的 RDMA worker，而 TP1 MR 保留真实 CUDA device=`1`，旧代码按 device id 查 worker 因而失败；
- 当前实现只在引擎精确只有一个 RDMA worker 时允许非零 CUDA device 复用该 worker；MR 的真实 CUDA
  device 信息不变，多 worker 模式继续严格匹配。该文件 SHA256 从 `3cf39108...46e62` 变为
  `0508a361...5c21`，方向 patch=`+46/-7`；
- 新增 single-worker GPU1 与 multi-worker strict-match 回归覆盖。`rustfmt --check`、host/CUDA feature
  下两项定向测试和 CUDA closed SDK `cargo check` 均通过；所有 target/resource store 位于
  `/mnt/nvme0`。首次 check 因漏传封存 resource store 被完整性门禁拒绝，补齐路径后 rc=0，不是代码错误；
- 这些是本地 correctness/build 门禁，不是集群 TP2 或性能验收。

### 11.51 2026-07-22 20:30–20:46 HKT：r48 CUDA SDK、GPU wheel与固定口径编排完成

- NVMe `findmnt` 确认 `/dev/nvme0n1p3` 后，构建独立 CUDA SDK=
  `/mnt/nvme0/mjq_build/fluxon_closed_sdk_abi9_pplx_cuda_r48_single_worker_gpu1_20260722`；manifest
  ABI/schema=`9/6`，SDK core/probe/cudart SHA256=`6b39533b...d44d`/`ad1bc9b...9039`/
  `218eec4c...0f71`，构建 rc=0；
- 以该 SDK 构建独立 GPU release=
  `/mnt/nvme0/mjq_build/fluxon_e44_r48_gpu_direct_single_worker_gpu1_20260722`，release profile 用时约
  `8m07s`。最终 wheel/PyO3/wheel 内 core/probe/cudart=`cc5e2e0e...590b`/
  `36f83361...29eb`/`e64bcfb3...148c`/`e925553e...5883`/`5b8de0ee...dc82`；release manifest、
  ABI3 封装与 r42 GPU staging lifecycle validator 全部通过。manylinux 中缺节点 driver
  `libcuda.so.1` 的 import warning 仍是预期外部依赖，不是闭包缺失；
- r48 variant 保持 S96×T24、2304 请求、c24、system 8192、output 8、session-stream、Get32、tier1 5%、
  end-depth288、DMA0 和 metadata-only 128/128/256 GiB 不变；CPU 继续复用 ABI/wire/open 相同的 r47
  host-only wheel，但使用独立 r48 remote release/venv；
- 编排新增 variant `+19/-0`、master YAML 28 行、deploy wrapper 16 行，guard `+1/-1`；r47 deploy
  参数化并增加显式 SSH identity 支持为 `+25/-16`。本轮 5 文件合计 `+89/-17`。`bash -n`、variant
  字段、r47/r48 YAML 去除 `log_dir` 后等价均通过；
- 本条尚未部署或发流。下一步先三端部署并回读闭包哈希，再清空四卡，验证两机 TP0/TP1 staging
  registration 和 HTTP ready，最后才放行原固定 2304 请求。

### 11.52 2026-07-22 20:46–21:03 HKT：r48 TP2 门禁通过、正式 attempt1 暴露后台线程 device 继承错误

- r48 三端部署完成，GPU wheel/PyO3/core/probe/cudart 和 CPU host-only wheel/core/probe 均精确匹配；
  正式启动前停止两机 burner、watchdog、`inference_like_compute.py`、GPU guard 和旧实验脚本，延时确认
  四卡全部 `0 MiB/0%`；三端 HCA observer、Greptime、control、master 与 128/128/256 GiB owner reserve
  全部 ready；
- 两机 TP0/TP1 均成功注册 288-slot staging；TP1 明确打印 `registration_id=1 device=1`，两侧 HTTP
  31001 和 router 32000 都达到 200。由此验收 r48 closed PPLX 的 `Worker not found` 修复；
- 固定 S96×T24、2304 请求、c24、system 8192、output 8、session-stream、Get32、tier1 5%、
  end-depth288、DMA0、128/128/256 GiB 原样发流。约 25 秒后 workload rc=1；监控在 phase 收尾读取
  node0 `/metrics` 时连接被拒绝。该轮没有完整 phase/result，不能计算或上报 QPS；
- 两机日志给出同形根因：TP0/TP1 的 background DMA worker 都打印 `device=0`。TP1 首次 CPU-backed
  layer restore 用 GPU0 stream 记录已绑定 GPU1 的 event，触发
  `Event device 1 does not match recording stream's device`，随后 scheduler fail-closed，HTTP 服务退出；
  这不是 RDMA payload 错写、OOM、burner 干扰或容量驱逐失败；
- 代码根因是 `self.device` 为 index-less `cuda`，`_cuda_device_index()` 在新 Python 线程里读取该线程默认
  current device=0。修复在 scheduler 主线程、executor 启动前冻结真实 device id，后台 stream 与 submit
  全程复用该值。runtime `+10/-0`、validator `+17/-0`、variant `+1/-1`、deploy 参数/哈希 `+2/-1`，
  本轮 5 文件合计 `+30/-2`；runtime SHA256=`075461f1...19e3`；
- Python compile、r42 lifecycle validator 新增的“capture 必须早于 worker start、resolver 必须复用 capture”
  AST 门禁、`bash -n` 和 variant/hash 对齐均通过。当前 owner/master/control/observer 仍保留，burner 未恢复；
  下一步精确部署两个 SGLang 文件并用 `SGLANG_ONLY` 重启两侧，先验收 TP1 worker=`device=1`，再从头重跑。

### 11.53 2026-07-22 21:03–21:40 HKT：r48 attempt2 原固定负载通过、性能无收益

- 精确部署 runtime SHA256=`075461f1af1bf710061b4bd2ab18f7f3ceee7b9bfee8a16d16ab61e0c67e19e3`，
  两机 SGLANG_ONLY 重启后 TP0/TP1 background worker 分别固定为 `device=0/1`；两侧 TP2 staging、HTTP 31001
  和 router 32000 全部 ready，未再出现 event-device mismatch；
- workload 未变：S96×T24、2304 请求、c24、system 8192、output 8、session-stream、Get32、tier1 5%、
  `prefix_end_depth_ratio/288`、DMA0、metadata-only 128/128/256 GiB。结果=`2304/2304/0`，QPS=
  `10.523661`；TTFT p50/p90/p99=`1.6022/2.6548/4.3732s`，E2E=`2.1170/3.7326/4.9355s`，
  L1/L2/L3=`2.88795/0/72.19078%`，总命中=`75.07873%`；
- 同口径 r39 QPS=`10.605922`，r48 低 `0.776%`；r48 总命中同时低 `0.525pp`，不能把差值归因成
  GPU-direct 的正负收益。裁决是 correctness 通过、性能无可见收益；
- 按 TP0 去重，node0/node1 GPU-direct logical prefetch=`12/24`、tokens=`219008/437056`；CPU staging
  prefetch=`1145/973`、tokens=`21146432/17233728`。合计 direct 只占请求 `1.671%`、tokens `1.681%`；
  10251 页双 TP 物理传输约 `96.741 GB`；
- 覆盖率根因是每 TP staging 仅 `288×4718592 B=1358954496 B`，而一次长前缀通常需要 281–288 页，
  同时大致只能容纳一个请求；c24 的其他请求回落 CPU。不能用“链路已经直达”替代“绝大多数流量直达”；
- 正式窗 direct-delete requests/victims/completed/retryable=`1874/778687/778233/454`，454 个均为 Get
  activity busy；owner scheduled/emitted retry=`454/454`，最终 selected/retry/debt/pending reclaim 全 0。
  Remote Put targets/transfers/published=`80349/80349/80349`，active/failed/replay=0；CPU retained=
  `55341/261131599872 B`；
- 最后 route 计数已实际增长：node0/node1/CPU members=`15020/15617/280`、bytes=
  `70873251840/73690251264/1321205760`，验收此前 members/bytes 计数修复；
- CPU 双 HCA TX avg/p99/peak=`130.013/352.878/421.312 Gbps`，三端 sample error=0，HCA 已导入
  Greptime `7746` rows。4308 条成功 load-back 的 total/ready-wait/restore/eviction/Get-transfer 均值=
  `901.751/649.105/168.403/39.456/11.945ms`；消费前终态率=`95.487%`，owner 真正 finish-wait 均值
  `5.234ms`，主等待仍是 scheduler/prefill 消费侧；
- 下一性能门禁不再是继续调 RDMA。先记录 GPU staging fallback reason、slot 占用时长和并发水位；若确认为
  单长请求独占，再评估固定显存预算下的分块/流式 staging 复用。直接扩大 staging 会挤压 GPU KV 容量，
  未经单变量验证不能采用。

### 11.54 2026-07-22 21:40–21:45 HKT：r48 停栈、burner 恢复与正式归档

- 当前本机对应私钥已能无交互登录 32656、30245、30729；`.pub` 只用于远端授权，实际登录使用对应私钥；
- 在复制正式窗日志和 runtime config 后，按 router/SGLang → 两 GPU owner/CPU owner → master/control 顺序精确
  停止 r48 隔离 tmux sessions；三端 r48 tmux server、Fluxon/SGLang/router/HCA observer 进程最终均为 0；
- burner 恢复前，32656/30245 四卡均回读 `0 MiB/0%` 且 compute app=0。随后两机分别启动两个 managed
  burner 和 watchdog；四卡最终均约 `1395 MiB/100%`，`inference_like_compute.py` 和实验服务为 0；
- `Fluxon` 当前 HEAD=`2fa4448c7554ecbb2a50c56b3b32dbb02a28ea5b`，17 文件 `+2574/-112` 的最终
  open-side 实现已提交，工作树干净；`sglang` HEAD=`3cf22f62c58232e77a68ffdb1967ef4702472b47`，工作树干净；
  closed 正确源没有可用 HEAD，r48 `fabric_engine.rs` SHA256=`0508a361...5c21` 并单独封存；
- 正式归档=`experiment_configs/e44_local_slot_tier_20260716/artifacts/e44_r48_gpu_direct_full_enddepth288_netobs_passed_20260722/`，
  共 163 个文件、约 207 MiB；162 个非 manifest 文件全部进入 `SHA256SUMS`，`sha256sum -c` 通过。归档包含
  workload、三端 HCA、三机日志、request metrics、Greptime DB、derived 对账、运行配置、release manifest、
  README 和清场证据；历史 attempt1 失败证据继续独立保存在原 artifact，不混入正式性能结果。

### 11.55 2026-07-22 21:57–22:06 HKT：r49 GPU-direct 覆盖率纯观测实现与本地门禁

- 本轮只定位 r48 GPU-direct `36/2154`（`1.671%`）覆盖率，不改变单 KV 驱逐、Fluxon core、288-slot
  staging 容量、Get/Put 数据面或 workload。adapter 的 pool reservation 现在返回稳定原因：`selected`、
  `request_exceeds_capacity`、`insufficient_free_slots`、`pool_unconfigured`、`pool_closed`；runtime 再补
  `mamba_required`、`no_hash_values`、`not_eligible` 和 `tp_reservation_inconsistent`；
- 每个 request 继续复用既有 `Fluxon hostless request lifecycle` 日志，新增 requested pages、capacity、
  reserve 前后 free/live slots、active leases 和 high-watermark，不为每次 fallback 另打一条重复日志。只有成功
  lease 在释放时额外输出 release reason、持有毫秒数和最终 occupancy；pool close 输出 admission/release 原因
  累计 Snapshot；
- validator 用 fake CUDA registration 完整执行 selected、请求超容量、临时 slots 不足、tail trim、显式 block、
  release 幂等、close/unregister 和 closed-pool 分支；Python 三文件 compile 与 AST/lifecycle validator 均通过；
- 相对 r48 正式归档的逐文件净 diff：runtime `+107/-7`、adapter `+172/-14`、validator `+139/-14`、
  variant `+20/-0`、guard `+1/-1`，新增 master YAML 28 行、source-only deploy 85 行，合计 7 文件
  `+552/-36`。runtime/adapter/validator SHA256=`a7598aca...18b2`/`7678033f...961`/
  `0edfeb52...eb4`；
- r49 variant 复用 r48 GPU/CPU wheel 和 venv；master YAML 与 r48 去除独立 `log_dir` 后逐行一致。
  `bash -n`、variant 回读和 hash 门禁通过。当前尚未部署、停 burner、启动服务或发送请求；下一门禁是
  source-only 三节点部署，再按规约清掉 burner/`inference_like_compute.py` 并确认四卡 `0 MiB/0%` 后发原固定负载。

### 11.56 2026-07-22 22:07–22:41 HKT：r49 原固定负载通过、admission 根因定位与清场

- source-only 三节点部署回读 runtime/adapter/validator SHA256=`a7598aca...18b2`/`7678033f...a7961`/
  `0edfeb52...3eb4`；GPU/CPU wheel 与 venv 全部复用 r48。两侧停 burner/watchdog、精确清理
  `inference_like_compute.py` 后四卡均为 `0 MiB/0%`；TP0/TP1 staging 分别注册真实 `device=0/1`；
- workload 脚本 SHA256=`f6721d76...3f52`，与 r48 正式归档逐字节相同。Get32、tier1 5%、
  `prefix_end_depth_ratio/288`、DMA0、128/128/256 GiB 不变。正式窗为 22:19:24.471–22:23:06.813 HKT，
  结果=`2304/2304/0`、QPS=`10.362389`；TTFT p50/p90/p99=`1.6933/2.8011/4.3760s`，E2E=
  `2.1459/3.5972/4.9434s`，L1/L2/L3=`3.3874/0/71.2182%`、总命中=`74.6056%`；
- 相对 r48 QPS 低 `1.532%`，但总命中也低 `0.473pp`，且 lifecycle 每行新增了大量观测字段；本轮明确只做
  attribution，不登记为性能优化或性能回退；
- TP0 与 TP1 admission 全量结果完全一致。GPU candidate=`2192`：原始请求超过 288 slots=`2013`
  （91.834%），free slots 暂不足=`143`（6.524%），selected=`36`（1.642%），TP inconsistency=0。
  超容量请求原始页数均值/p50=`351.322/351`，fallback 后真实 transferable p50=`288`；`1265/2013`
  个真实可传前缀其实在 `(0,288]`。因此主因是 Get Start 前按完整 hash 列表预留，而不是“一个 lease 占着 pool”；
- selected 仍为 36 次、`10242 pages/655488 tokens`，占 2150 次成功 load-back 的 `1.674%`、token 的
  `1.686%`，与 r48 无实质变化。每 TP selected/release 都严格相等；平均初始 lease=`284.5 slots`、TP0
  平均持有 `437.814ms`，node0 最大 `2714.770ms`。这证明并发独占确实存在，但排在错误尺寸 admission 之后；
- formal HCA CPU TX avg/p99/peak=`128.666/365.782/415.763 Gbps`，sample error=0；Greptime HCA 导入
  `9726 rows`。4300 个成功 load-back 的 total/ready-wait/restore/eviction/Get-transfer 均值=
  `972.403/721.245/167.558/46.091/11.447ms`；owner 终态先于消费比例=`96.103%`、真实 finish-wait=
  `4.946ms`，网络/Fluxon terminal 仍不是主要等待；
- 下一性能方向收敛为 generation-safe `plan → exact reserve → execute`。plan 只返回 transferable prefix 与
  route，不传数据、不创建 CPU holder；SGLang 再按 exact prefix/GPU budget 安装 destinations，并复用同一
  operation 执行。其后再做 bounded GPU prefix + CPU remainder；不能先做 CPU Get 再重复 GPU Get，也不先扩 pool；
- SGLang Ctrl-C 没有触发 adapter `close()`，所以新增 pool close Snapshot 未出现；但每 TP 36 selected 都有
  36 release，停栈后四卡为 `0 MiB/0%`，无 lease 泄漏。三端实验服务/session/observer 最终为 0；随后恢复
  两侧 managed burner，四卡约 `1395 MiB/100%`，inference=0；正式归档约 209 MiB，150 个非 manifest
  文件全部进入 `SHA256SUMS` 并通过校验。

### 11.57 2026-07-22 23:19–23:35 HKT：P0 Plan/Bind 第一阶段实现

- master 新增 target-free `BatchGetPlan` 和 late-bind `BatchGetBind`。plan 为每个单 KV 固定 `get_id`、
  `put_id`、source node/address、source tomb generation、external controller generation 和 key activity；此阶段
  不分配 target、不创建 holder、不传 payload；
- external controller 的 plan 会优先选择其 share-group owner 之外的 live source，并单独返回
  `gpu_direct_eligible`。Bind 只接受两个有限分支：同 external generation 的 caller-owned GPU sink，或该
  external 当前精确 owner generation 的 prepared CPU slot；未绑定 plan、已绑定 operation 和 Done/Revoke
  共用同一 `get_id`；
- Bind 由 per-operation async lock 串行，重复的相同 target 可重放，identity/target 不一致会 fail-closed；绑定前
  会复核 source tomb、route put generation、地址和长度。plan expiry、响应发送失败和 Revoke 都会释放 activity；
  CPU owner 可以 Revoke 自己 external 的未绑定/已绑定 operation，但不能控制其他 generation；
- 本轮 7 个 Fluxon 文件 HEAD-relative 净 diff=`+782/-17`：`client_kv_api/get.rs +53/-4`、
  `client_kv_api/mod.rs +8/-2`、`client_kv_api/msg_pack.rs +38/-0`、`master_kv_router/get.rs +499/-5`、
  `master_kv_router/mod.rs +96/-6`、`master_kv_router/msg_pack.rs +84/-0`、
  `msg_and_error.rs +4/-0`。这些是第一阶段净状态，不是完整 P0 工作量；
- `/mnt/nvme0/mjq_build/push_sglang_fluxon_target` 经 `findmnt` 确认为 `/dev/nvme0n1p3`；
  `cargo check -p fluxon_kv --lib` 通过，仅有既有 warning。尚未接 external execute、PyO3/Python、SGLang，
  也没有定向测试、真实 GPU smoke 或正式负载结果，因此 r49 仍是当前正式基线。

### 11.58 2026-07-22 23:35–23:57 HKT：P0 external/owner/Python/SGLang 接通

- external 新增 plan registry。一次 master Plan 同时返回 CPU 可传前缀和 RDMA-only GPU 可传前缀；执行时
  只允许一次状态迁移到 CPU 或 GPU。GPU 分支先校验 exact destinations，再对原 `get_id` Bind 并启动传输；
  CPU 分支把同一批 `get_id` 发给当前 share-group owner，不再调用第二次 GetStart；
- owner CPU fallback 进入现有 per-key singleflight：本地已有 holder 或已有 flight 的 follower 会 Revoke 自己
  未使用的 plan；只有新 leader 为原 plan Bind prepared slots、传输并 Done。owner execution identity 为
  `(external id, external observed owner generation, plan_handle)`，per-operation async lock 和 120 秒终态 cache
  支持响应重放；没有 actor、FIFO 或跨 key 队列；
- PyO3/Python 新增强类型 `GetPlanHandle` 及 plan/cancel/execute-CPU/execute-GPU；执行后收敛回既有
  `GetStartHandle` 或 `GpuGetStartHandle`，因此消费和 holder/GPU lease 终态仍走原路径；
- SGLang 固定 runtime 改为先 plan，再在 TP 间同步 CPU/GPU complete atomic-group prefix，最后按
  `gpu_common_pages` exact reserve。GPU prefix 短于 CPU prefix时保留 CPU 最大命中，不用较短直达换命中；
  reserve 不足也直接对同一 plan 做 CPU Bind。旧“按完整 hash 数先占 288-slot pool”的顺序已删除；
- `Fluxon` 当前 11 文件净 diff=`+2349/-40`；固定实验 3 文件相对 r49 归档净 diff=`+270/-172`。
  `cargo check -p fluxon_kv --lib`、`cargo check -p fluxon_pyo3 --lib`、四个 Python 文件 compile、扩展后的
  GPU staging AST/lease validator 均通过。尚未做 Rust 定向测试、真实进程 lifecycle 或集群验收。

### 11.59 2026-07-22 23:57–2026-07-23 00:10 HKT：P0 定向回归补齐与本地收口起点

- 新增 planned wire 往返测试，覆盖 master `BatchGetPlan → BatchGetBind` 的 late GPU binding、owner planned
  CPU execute 的 operation identity/holder terminal，以及合法首个 `get_id=0`；定向执行合计 `2 passed`；
- 新增 CPU/GPU prefix 分离测试：当第二个 item 不具备 GPU-direct 条件时，GPU prefix 停在第一个 item，CPU
  prefix 仍保留全部三个成功 item，避免为了直达主动缩短命中；定向执行 `1 passed`；
- 跨机 smoke 改为调用新的 Plan/Execute API，并保留逐字节 payload 校验。该文件改动发生在上一轮 Python
  compile 之后，所以不能沿用旧 compile 结果，必须在本轮重新执行；
- `Fluxon` 当前 HEAD-relative 最终工作树净 diff 为 11 文件 `+2522/-44`；固定实验相对 r49 正式归档
  当前为 4 文件 `+288/-177`。11.58 的 `+2349/-40` 与 3 文件 `+270/-172` 是当时中间净状态，已被
  本节覆盖，不能冒充当前累计 diff；
- 当前只证明 wire/纯函数边界，没有证明 CPU fallback/cancel/响应丢失重放和 holder/activity lease 的真实
  生命周期。下一门禁依次为 fmt、Python compile、validator、`git diff --check`、完整 `fluxon_kv --lib`
  测试、lifecycle 审计与补测；这些通过后才能构建 r50 和上双机 smoke。

### 11.60 2026-07-23 00:10–00:14 HKT：本地门禁与完整测试 SDK 口径纠正

- `cargo fmt --all`、`cargo check -p fluxon_kv --lib`、`cargo check -p fluxon_pyo3 --lib`、最新四个
  Python 文件 compile、staging lifecycle validator 和 `git diff --check` 均通过；Cargo 只有仓库既有 warning；
- 首次完整 `cargo test -p fluxon_kv --lib` 错误使用
  `Fluxon/fluxon_release/closed_sdk/lib/libfluxon_commu_core.so`。该文件 SHA256=`85a39d32...e67`，manifest
  是 schema5/ABI8；当前 open/正式 r48 要求 schema6/ABI9。结果为 `184 passed/9 failed`，失败均是会启动
  framework/closed transfer-engine 的集成测试，并共同报 `DecodeRequest { detail: "bitcode error" }`；不能把这
  9 项记成 P0 代码回归，也不能把该轮记成完整测试通过；
- 改用 r48 正确 SDK
  `/mnt/nvme0/mjq_build/fluxon_closed_sdk_abi9_pplx_cuda_r48_single_worker_gpu1_20260722/lib`，core
  SHA256=`6b39533b...3d44d` 后，代表性失败项
  `single_key_source_selection_fence_closes_late_get_and_rolls_back` 单线程复跑 `1 passed`，确认 open/closed
  request decode 和真实 framework lifecycle 正常；
- 下一步必须在同一 r48 SDK 环境完整复跑 193 项。r50 构建编排也必须显式固定该 SDK，不能继承源码树中
  的旧 bundled SDK；当前最终净 diff 未因 fmt 改变，仍为 11 文件 `+2522/-44`。

### 11.61 2026-07-23 00:14–00:18 HKT：正确 SDK 下完整 Rust 回归通过

- 使用固定 NVMe target 和 r48 schema6/ABI9 CUDA closed SDK 完整执行
  `cargo test -p fluxon_kv --lib`，最终 `193 passed/0 failed/0 ignored`，耗时 `185.64s`；
- 首次环境错误轮的 9 个失败在正确 SDK 轮中全部通过，包括 source-selection fence、two-sided owner reclaim、
  5 个 lease-manager 长测试和 2 个 memholder 生命周期测试；新 planned wire 与 CPU/GPU prefix 测试也包含在
  193 项中通过；
- 本轮只关闭“编译、静态门禁和既有 Rust 回归”门禁。新 Plan API 仍缺少针对 cancel、丢响应重放、CPU
  fallback holder/activity lease 终态的专门故障注入验证；在完成这项审计前不构建 r50。

### 11.62 2026-07-23 00:18–00:27 HKT：P0 lifecycle 审计发现的收口缺口

- master plan/activity 生命周期本身闭环：未 Bind plan 在 Revoke、响应发送失败或 60 秒 TTL 时释放；Bind 在
  per-`get_id` lock 下原子移入 `inflight_gets`；相同 target 可重放，Done/Revoke 继续共用同一终态锁；
- owner CPU execute 的 `(external id, external generation, plan_handle)` 异步锁和 120 秒 completed cache 能让
  RPC retry 复用 holder 终态；per-key singleflight 仍保证 local/follower 不重复 Bind/transfer；未发现 actor/FIFO
  或第二套 transfer 调度；
- 发现缺口一：external 的 CPU/GPU `get_transfer` 在等待后台 terminal 前先从 pending map 移除 entry。若 future
  在 wait 点取消，后台 transfer 继续但 handle 清理所有权丢失；CPU 完成后 owner holder 可能无人发送 release；
- 发现缺口二：`cancel_get_plan`、CPU tail-revoke 失败、cancel-before-owner 和 no-owner 分支没有统一的注册后台
  retry。一次控制面暂态失败后只能依赖 master 60 秒 TTL，期间 source activity fence 被白占；
- 修复方向：增加通用 pending-entry cancellation guard，等待期间 Drop 自动原样 reinsert；增加注册到 framework
  task registry 的 planned-Revoke 重试，调用者取消后任务仍负责收敛；owner generation 变化或 shutdown 才停止。
  这两项不改变传输/容量边界，也不增加正常数据面 RTT。

### 11.63 2026-07-23 00:27–00:31 HKT：P0 cancellation-safe lifecycle 收口实现

- external 新增通用 pending registry guard。CPU/GPU `get_transfer` 等待 terminal 时不再永久移除 entry；若
  future 在 await 点被取消，Drop 将完整 entry（含 watch receiver/cancel flag/keys/group boundary）原样放回；
  只有拿到明确 terminal 后才 disarm；
- 新增 planned Get Revoke cleanup task。plan 创建后到 pending handoff、GPU late Bind await、显式 plan cancel、
  CPU tail cleanup/cancel-before-owner/no-owner 等路径均有明确所有者；任务按原 get ids 幂等重试，调用 future
  被取消也不影响任务继续，只有 framework shutdown 才停止；正常成功执行不新增 RPC；
- CPU terminal 消费补齐异常清理：response shape、owner mapping、owner generation、holder offset/range/pointer 或
  tail ACK enqueue 失败时，统一把 owner 返回的 holder ids 交给 delete-ACK batch，避免错误返回路径遗留 holder；
- Python `cancel_get_plan` 只在 backend 确认成功后置 `closed=True`，失败时仍允许调用者重试；新增 pending
  guard 的 reinsert/disarm 单元测试；
- 本轮格式化后 `Fluxon` 最终工作树净 diff 为 11 文件 `+2843/-71`，相对 11.61 增加的主要净状态位于
  `external_client_api/mod.rs`。旧 `193/193` 发生在本轮之前，不能覆盖这些新改动；下一门禁是 check、定向
  lifecycle test 和正确 SDK 下完整复跑。

### 11.64 2026-07-23 00:31–00:35 HKT：收口后定向门禁与净 diff 纠正

- 固定 NVMe target 下，`cargo check -p fluxon_kv --lib` 与 `cargo check -p fluxon_pyo3 --lib` 均通过；
  lifecycle 定向命令共 `7 passed`，覆盖 pending guard Drop reinsert、异步 waiter abort 后 pending entry 恢复、
  CPU/GPU prefix 分离和合法 `get_id=0` 等边界；
- 定向 async 测试补入工作树后，当前 HEAD-relative 净 diff 实际为 11 文件 `+2866/-63`。11.63 的
  `+2843/-71` 是补测前中间状态，保留作历史过程，不代表当前最终净状态；
- 这些结果仍不是完整回归。下一门禁保持为四个 Python 文件 compile、staging validator、
  `git diff --check`，以及正确 r48 schema6/ABI9 SDK 下完整 `cargo test -p fluxon_kv --lib`。

### 11.65 2026-07-23 00:35–00:46 HKT：P0 本地完整门禁通过

- 四个 active Python 文件 `py_compile` 通过；以 active runtime/adapter 直接运行 staging lifecycle validator
  通过；`git diff --check` 通过；
- Cargo target=`/mnt/nvme0/mjq_build/push_sglang_fluxon_target`，`findmnt` 确认为
  `/dev/nvme0n1p3`，可用空间约 432 GiB。完整回归显式加载 r48 schema6/ABI9 CUDA SDK，core SHA256=
  `6b39533b615f71403b35da072d24c6afc0e99400c3d55e2b7faca2b0f163d44d`；
- 第一轮完整测试虽结束，但 tmux 自动销毁导致最终退出码未保留，按门禁不登记。第二轮启用
  `remain-on-exit` 后 pane dead status=`0`；同一 test binary `--list` 枚举 195 项，因此登记当前代码完整
  Rust 回归=`195 passed/0 failed`；
- P0 本地门禁至此关闭。下一步只允许复用 r48 closed GPU SDK/r47 CPU SDK、重建 open wheel 形成 r50，
  随后先做双机逐字节 GPU-direct smoke 和 CPU fallback smoke，再决定是否进入原固定负载正式轮。

### 11.66 2026-07-23 00:48–00:57 HKT：r50 GPU CUDA release 构建通过

- 在 NVMe manylinux 环境重建当前 open PyO3/wheel，release=
  `/mnt/nvme0/mjq_build/fluxon_e44_r50_plan_bind_gpu_cuda_20260723`；构建 tmux dead status=`0`，
  release manifest 全量校验通过；
- closed 输入固定为 r48 schema6/ABI9 CUDA SDK，未使用源码树旧 bundled SDK。最终统一 wheel/PyO3 SHA256=
  `98acb33b9503cc1aec832eca3dac1a087dd7c3f9b9ff948bb773c75cc7547307`/
  `5094e229e286bfed079d4971d857bf96327ed2dfd460ff344a78a35fd860fbbd`；
- wheel 内 core/probe/cudart SHA256=
  `e64bcfb37e2108776e56ebb3ac284d69e4a9363c7298f104003ca4bd4d65148c`/
  `e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883`/
  `5b8de0eec6b33e5f785da05d89869fdbfc58af3ae5af96d7d53a53180429dc82`；manifest 回读
  ABI/schema=`9/6`；
- 当前只完成 GPU release。CPU 节点不能安装 CUDA wheel；下一步以 r47 schema6/ABI9 host-only SDK
  重建同一 open 代码的 CPU wheel，完成无 CUDA 依赖审计后才具备三节点部署条件。

### 11.67 2026-07-23 00:59–01:07 HKT：r50 CPU host-only release 构建通过

- 以 r47 schema6/ABI9 host-only SDK 重建同一 open 代码，release=
  `/mnt/nvme0/mjq_build/fluxon_e44_r50_plan_bind_cpu_host_20260723`；构建完成到最终 checksum，独立重跑
  release manifest 校验通过；
- CPU 统一 wheel SHA256=
  `e1ba3cab4ee010623ee735b13ac252518951cc78264443e472d3cd70c65c1918`，PyO3 SHA256=
  `5094e229e286bfed079d4971d857bf96327ed2dfd460ff344a78a35fd860fbbd`，与 GPU release 的 PyO3
  逐字节相同，证明 GPU/CPU 打包没有分叉当前 open 逻辑；
- CPU wheel 内 core/probe SHA256=
  `63c08ee69f46bcc14ddfd16a952ce32bd4484bbc991419f8dd1395f4523e6e06`/
  `e925553e01d6f5f2754e667aeeac9bba8e7d829bf15136a95304f221e5dc5883`；wheel entry 和 core
  `NEEDED` 均无 `libcuda`/`libcudart`，解包后 PyO3 `ldd` 无 `not found`，SDK manifest 回读
  ABI/schema=`9/6`；
- r50 三节点构建闭环完成。下一步只做编排哈希收紧、部署和 smoke，不改变固定 workload、Get32、
  tier1 5%、end-depth288、DMA0 或 128/128/256 GiB 容量配置。

### 11.68 2026-07-23 01:07–01:12 HKT：r50 部署与 GPU/CPU 双 smoke 编排

- 新增 planned CPU fallback 逐字节 smoke：对同一远端 4,718,592-byte payload 执行
  `GetPlan → execute_get_plan_cpu → get_transfer`，从 holder plan 读取并校验 SHA256，随后显式
  `release_views`；异常路径分别 cancel plan/CPU handle 并释放 holder；
- 既有 GPU smoke 可选串接该 CPU smoke；r50 wrapper 固定新 key/tag、r50 GPU venv 和 SSH identity，
  cleanup 继续在 smoke 前停 burner/`inference_like_compute.py`，退出时停栈并恢复 burner；
- 新增 r50 master YAML 和正式 variant。除隔离 `log_dir` 外，YAML 与 r48 逐项相同；variant 固定
  Get32、tier1 5%、end-depth288、batch32、DMA0 和新 PyO3/runtime/adapter 哈希；部署继续分别校验
  GPU CUDA 与 CPU host-only wheel，并把 adapter 哈希也改为显式输入；
- 本轮 7 个编排/CPU smoke 文件相对改动前净状态=`+206/-3`：四个新文件 165 行，variant 新 case
  18 行，通用 deploy `+6/-1`，通用 smoke runner `+17/-2`。该统计不与 4 个 P0 runtime 文件的
  r49-relative `+288/-177` 混算；
- `bash -n`、新 CPU smoke 与四个 active Python 文件 compile、staging validator、r50 variant 字段、
  r48/r50 YAML 除 `log_dir` 等价均通过。下一门禁是三节点部署后回读 wheel/runtime 哈希，再执行
  双机 GPU-direct 和 planned CPU fallback 逐字节 smoke。

### 11.69 2026-07-23 01:12–01:16 HKT：r50 三节点部署闭环

- preflight 确认 32656/30245/30729 可通过指定 ed25519 key 连接，三端无旧 Fluxon/SGLang 或
  `inference_like_compute.py`；两个 GPU 节点只有 managed burner，各卡约 `1395 MiB/100%`。部署阶段
  未停 burner、未启动服务、未发送请求；
- deploy tmux dead status=`0`。32656/30245 安装 GPU release/venv，30729 安装 CPU host-only
  release/venv；三端逐项回读 release manifest、wheel、PyO3、core/probe，GPU 额外回读 cudart，全部与
  11.66/11.67 的本地哈希一致；
- 两个 GPU 节点已安装 active runtime SHA256=`3bdab295...8aab7`、adapter SHA256=
  `1cc7153e...114a` 和 metadata-only host pool；r50 variant 的 Get32、batch32、DMA0、end-depth288
  与哈希门禁通过；
- 这只是部署验收，不是数据面或正式性能结果。下一步 smoke runner 会先停止 burner 和
  `inference_like_compute.py`、确认四卡无 compute process，再启动隔离 master/owners，依次执行 GPU-direct
  与 planned CPU fallback 逐字节校验，退出时停栈并恢复 burner。

### 11.70 2026-07-23 01:16–01:24 HKT：GPU smoke 通过、CPU fallback smoke 失败与首轮修复

- runner 启动前确认 32656/30245 四卡均为 `0 MiB/0%`，无 burner、`inference_like_compute.py` 或旧栈；
  writer 写入 4,718,592-byte 固定 payload，SHA256=`bd0c9278...ed19`；GPU plan/Bind/transfer 后逐字节
  回读同一 SHA256，GPU-direct smoke 明确通过；
- 随后的 planned CPU fallback 未打印成功终态。Python 报 `execute_get_plan_cpu()` 返回的 `Result<ok>`
  未显式消费，异常路径随后进入 framework close，并卡在 Greptime exporter join，最终由 90 秒 timeout
  以 rc=124 结束。这里能确定 Python wrapper 的 Result 合同缺口；尚不能仅凭该提示断定 CPU 数据面失败
  的最终根因，因为原始 `get_transfer` 异常在阻塞 cleanup 之后没有来得及打印；
- timeout 后 trap 已停止隔离 master/owners/control；两机无残留 Fluxon/smoke/inference，四个 managed
  burner 均恢复约 `1395 MiB/100%`。本轮只登记 GPU smoke 通过，双 smoke 整体判失败；
- 已对 planned Get 新接口的成功分支补齐显式 `unwrap()`：plan payload-validation cleanup、
  `cancel_get_plan`、CPU/GPU execute、GPU payload-validation cleanup 和 GPU cancel；CPU smoke 同时在 cleanup
  前打印原始异常/traceback。`Fluxon` 净 diff 更新为 11 文件 `+2874/-63`，r50 编排/CPU smoke 为
  `+218/-3`；
- 修复后 `py_compile`、planned Result-consumption AST 门禁和 `git diff --check` 通过。因为 Python wrapper
  位于统一 wheel 内，旧 r50 wheel/部署已失效；下一步必须重建 GPU/CPU wheel、重新部署，再重跑 CPU
  fallback，不能只替换 smoke 脚本后宣称修复。

### 11.71 2026-07-23 01:24–01:40 HKT：Result 修复后的 r50 双 wheel 重建

- 保持 r48 CUDA/r47 host-only closed SDK、ABI/schema、Rust/PyO3 源和所有实验配置不变，只把 11.70 的
  Python wrapper Result-consumption 修复重新封入统一 wheel；两个构建均在 NVMe manylinux target 完整运行，
  tmux dead status=`0`、release manifest 全量通过；
- 修复后 GPU/CPU wheel SHA256 分别为
  `fc0a7fc6495f8260955487f8bf99ba2fe257f5e45129b9e4fa2707ecfee9f8a2`/
  `55afd3602882f9738d87bf2239adfa20160699b8c0471dc43645faa19ae3f35f`；旧的
  `98acb33b...7307`/`e1ba3cab...1918` 已失效，不得部署；
- 两边 PyO3 SHA256 仍逐字节同为 `5094e229...fbbd`，GPU/CPU core/probe/cudart 哈希也保持 11.66/11.67
  不变，符合“只改 Python wrapper”的预期；
- 下一步重新运行同一 r50 deploy wrapper，让三端 venv 接收新 wheel；回读哈希后再重跑完全相同的
  GPU-direct + planned CPU fallback smoke。

### 11.72 2026-07-23 01:40–01:43 HKT：修复 wheel 三节点重新部署

- 同一 r50 deploy wrapper 重新部署完成，tmux dead status=`0`。32656/30245 回读 GPU wheel=
  `fc0a7fc6...f8a2`，30729 回读 CPU wheel=`55afd360...f35f`；三端 PyO3/core/probe、GPU cudart、
  runtime/adapter 与 variant 门禁全部通过；
- 部署期间无 Fluxon/SGLang/inference 残留，GPU 两节点仍只有恢复后的 managed burner；尚未启动服务或
  发送新请求。下一步重跑同一 key/size/seed 的双 smoke，runner 仍负责清场与恢复 burner。

### 11.73 2026-07-23 01:43–01:49 HKT：CPU fallback 第二轮明确定位为 smoke reserve 缺失

- 第二轮仍使用同一 key、4,718,592-byte payload、seed=73 和修复后的 wheel。GPU-direct 再次逐字节
  通过，SHA256=`bd0c9278...ed19`；未再出现 planned execute/cancel 的未消费 `Result<ok>`；
- CPU smoke 在 cleanup 前完整打印终态：owner 返回 error_code=118，明确为
  `planned external Get requires owner-local reserve capacity`。因此本轮失败点位于 owner Bind 前置容量
  合同，尚未发起 CPU payload transfer；它不是 RDMA/CPU payload mismatch；
- 根因是旧 GPU-only smoke owner 只贡献 1 GiB DRAM，却没有设置
  `owner_local_reserve_expected_capacity`。正式 workload launcher 一直配置该 reserve，所以这是 smoke
  编排缺口，不是正式配置缺口；
- 已给 smoke 两个 owner 固定 value_len/payload_capacity=`4,718,592 B`。按 512 MiB grant quantum，
  每侧恰好预热 1 grant=`536,870,912 B`，小于 1 GiB owner contribution，并足够本轮单 KV CPU Get；
  `bash -n` 和容量数学门禁通过；
- timeout 后隔离栈再次清空，四个 managed burner 已恢复。r50 编排统计更新为 8 文件 `+220/-3`；
  下一步只部署更新后的 owner smoke launcher并重跑双 smoke，无需重建 wheel。

### 11.74 2026-07-23 01:49–01:54 HKT：r50 GPU/CPU 双 smoke 完整通过

- 两个 GPU 节点精确部署 owner smoke launcher SHA256=`bed60261...5f14`。第三轮启动前再次确认四卡
  `0 MiB/0%`，无 burner、`inference_like_compute.py` 或旧服务；两个 1 GiB owner 均打印
  `ready: owner local-reserve expected capacity`；
- writer 固定 payload、GPU-direct reader 和 planned CPU fallback reader 三者 SHA256 均为
  `bd0c9278e27fd0bd53070cea6c3da1c2d0b1a36d0b0520c1174baa58387bed19`，size 均为
  `4,718,592 B`。GPU 路径出现一批一项 PPLX reverse-copy，CPU 路径完成
  `plan → CPU Bind → transfer → holder read → release_views`；
- runner tmux dead status=`0`，明确打印 GPU 与 planned CPU 两条 `data smoke: passed`。退出 trap 后
  master/owners/control/smoke/inference 全为 0；两机四个 managed burner 均恢复约 `1395 MiB/100%`；
- r50 correctness smoke 门禁关闭。下一步才允许运行原固定
  S96×T24/2304/c24/system8192/output8/session-stream/Get32/tier1 5%/end-depth288/DMA0/
  metadata-only 128/128/256 GiB 正式负载；不得更换 workload 或容量。

### 11.75 2026-07-23 08:45–08:49 HKT：r50 正式轮启动门禁

- guarded GPU launcher 只扩展一个 r50 variant 白名单，不改变启动参数或数据路径；本地 `bash -n` 通过，
  文件 SHA256=`37951512ed5e55919a155797c7f4903e11f632626b20de7d0ccbdff25350624b`，32656/30245
  精确部署后回读相同。该改动相对 11.74 为 `+1/-1`，r50 编排/CPU smoke 累计净状态更新为 8 文件
  `+221/-4`；
- 正式 workload SHA256=`f6721d76b7248f365bf44e98bedfe3ea40db2c9f70d08a4922de620e54003f52`，
  与 r48/r49 归档逐字节一致；r50/r49 master YAML 去除隔离 `log_dir` 后无 diff。variant 回读仍为
  Get32、tier1 5%、`prefix_end_depth_ratio/288`、DMA0，正式容量仍为 GPU owner 各 128 GiB、CPU owner
  256 GiB；
- 三节点无 Fluxon/SGLang/`inference_like_compute.py` 或外部 formal guard 残留。32656/30245 的 managed
  burner 与 watchdog 已停止，两机 GPU0/1 均为 `0 MiB/0%`、compute PID 为空，r50 guarded preflight
  两侧均通过；
- 当前只完成启动前门禁，尚无正式请求或新 QPS。下一步启动 control/master、三 owner、三端 HCA observer、
  两侧 SGLang 与 router，完整运行固定 2304 请求；成功或失败都必须停止全栈并恢复 burner。

### 11.76 2026-07-23 08:49–09:16 HKT：r50 原固定负载 no-go、根因收敛与清场

- 三节点按原顺序启动 control/master、三 owner、三端 500ms HCA observer、两侧 TP2 SGLang 和 router。
  启动前 32656/30245 四卡均为 `0 MiB/0%`、compute PID 为空；workload SHA256=
  `f6721d76b7248f365bf44e98bedfe3ea40db2c9f70d08a4922de620e54003f52`，与 r48/r49
  逐字节相同。TP0/TP1 分别注册 CUDA device 0/1 的 288-slot staging；metadata-only host pool 每 TP 仍只
  materialize 1 页；
- 正式窗=`1784768126.6903312–1784768455.9415903`，workload rc=0，结果=`2304/2304/0`、QPS=
  `6.997695`。TTFT p50/p90/p99=`1.7582/6.3047/9.9634s`，E2E=
  `2.2816/7.6532/11.6751s`，L1/L2/L3=`10.1375/0/56.0784%`、总命中=`66.2159%`；
- 相对 r49，QPS `-32.470%`、L3 `-15.140pp`、总命中 `-8.390pp`。由于缓存行为同时发生大幅变化，
  本轮不能用于测量“GPU-direct 固定 overhead”，正式裁决为 no-go，r49 继续作为性能基线；
- r50 TP0 去重 admission selected=`196/2208`（8.877%），比 r49 的 36 次提高；direct 消费约
  `3,173,696` tokens，占成功 load-back tokens 约 4.58%。剩余主要原因为
  `gpu_prefix_shorter_than_cpu=947`、`insufficient_free_slots=358`、`no_gpu_transferable_prefix=319`；
- 成功 load-back TP-rank operations 从 r49 的 4300 降至 3682，`rate_limited 32→374`、
  `zero_transferable 72→308`，另有 26 个逻辑 Get transfer/TP commit 错误。成功项 ready-wait
  mean/p90/p99 从 `721/1545/2394ms` 变为 `1345/3761/7739ms`。回退集中在 node0：成功 load-back
  `2312→1704`，node1 为 `1988→1978`；node0 direct lease 平均/最大持有 `2337/8182ms`，node1 仅
  `439/1395ms`。node0 CPU 与 GPU 两种路径的 ready-wait 都在秒级，排除“只有 GPU copy 慢”；
- 正式窗 CPU 双 HCA TX avg/p99/peak=`22.547/138.250/200.488 Gbps`，相对 r49 平均低 82.48%；
  三端 raw 各 1397 行，Greptime 导入 8370 rows，sample error=0。网络没有饱和，而是上游没有持续产生
  足够传输；
- 代码边界审计确认：SGLang 每个调用者先直接 master Plan；master 在 Plan 阶段就
  `reserve_inflight_get_key()` 并把 activity lease 放进 `planned_gets`；owner local-hit/per-key singleflight
  到 planned CPU execute 才运行。owner 聚合因此发生得过晚，followers 在复用 holder 之前已经重复做
  route snapshot/activity pin/Revoke，GPU 分支完全绕过 owner Get 聚合。对应地 source-evict retryable Busy
  从 r49 的 299 增至 r50 的 `3353+7874=11227`；
- 下一门禁是把 Plan 收缩为真正 metadata-only：Plan 不安装 activity/fence，Bind 才 generation-safe
  revalidate 并安装真实 Get activity；CPU local-hit/singleflight 必须前置，leader 才 Bind，followers 复用
  holder。GPU 可共享 metadata lookup，但每个 destination Bind 保持独立 identity。必须先补 Plan/Bind/CPU
  leader-follower 按 node 计数，再复跑相同负载；
- 清场时三端 workload/router/SGLang/owner/master/control/observer 全部停止，master 与 owner active 状态归零；
  恢复 burner 前四卡均为 `0 MiB/0%`。30245 在正式轮结束后被外部重新拉起的 inference 已精确终止；它
  不在启动门禁和正式窗内。随后两侧 managed burner 恢复，各卡约 `1395 MiB/100%`；
- 新分析文档=`20260723_0915_fluxon_r50_plan_bind正式结果与下一步.md`。正式归档=
  `experiment_configs/e44_local_slot_tier_20260716/artifacts/e44_r50_plan_bind_enddepth288_netobs_no_go_20260723/`，
  共 192 个文件、约 220 MiB，包含 workload、三机日志/request metrics、三端 HCA、Greptime DB、derived
  对账、运行配置、release source manifest 与清场证据；`SHA256SUMS` 已通过。

### 11.77 2026-07-23 11:10–11:26 HKT：r51 metadata-only Plan 与 Bind-time fence 首轮实现

- 保留 r50 的注册 GPU destination、RDMA 直达 GPU、CPU fallback 和 SGLang staging 数据面，不修改容量、
  workload 或单 KV 驱逐规则；本轮只收紧 Plan/Bind 控制面边界；
- 审计发现 r50 `PlannedGetInfo` 同时持有 master Get activity、完整 route `Arc`（间接持有 Allocation）并在
  Plan 返回前 touch Moka，因此旧 Plan 既阻塞 reclaim，也会延长物理 backing 生命周期和改变替换顺序；
- `PlannedGetInfo` 已收缩为 put/source/controller/geometry/atomic-group 标量。Plan 不再调用
  `reserve_inflight_get_key()`、不保存 route/Allocation/activity/cache pin，也不 touch Moka；未 Bind 的 Revoke、
  RPC response-loss cleanup 和 TTL 仅删除标量 metadata；
- Bind 继续使用 per-`get_id` async operation lock。目标与 requester 合法后才安装真实 Get activity，随后重读
  当前 route，精确核对 put id、source node generation、地址/base/len；stale route 使用新错误
  `StaleGetPlan(code=124)`，成功后才移入 `inflight_gets` 并 touch source Moka。owner planned CPU path继续在
  Bind 前执行 local-hit/per-key singleflight，只有 leader 的 plan id 会 Bind，local/followers 的 plan id 统一
  Revoke；没有新增 actor、FIFO 或第二套传输状态机；
- 新增 master Plan/Bind 累计计数与 active-plan 周期日志，以及 owner planned CPU local/leader/follower 分类计数。
  这些用于下一次固定负载直接判断 activity 是否只出现在真实 Bind、CPU follower 是否避免传输；跨调用者
  metadata lookup 共享尚未实现，当前不得把它记录成已完成优化；
- 相对 r50 最终工作树，本轮只修改 5 个 Rust 文件：
  `master_kv_router/get.rs +172/-0`、`master_kv_router/mod.rs +56/-0`、
  `client_kv_api/external_api.rs +33/-0`、`client_kv_api/mod.rs +31/-0`、
  `rpcresp_kvresult_convert/msg_and_error.rs +3/-0`，合计 `+295/-0`。由于 r50 未独立提交，当前 HEAD-relative
  最终净状态是 11 文件 `+3169/-63`，两种基线不得混算；
- 固定 NVMe target 已由 `findmnt` 确认为 `/dev/nvme0n1p3`，约 426 GiB 可用。`cargo fmt --all -- --check`、
  `git diff --check`、`cargo check -p fluxon_kv --lib` 通过；使用 r48/r50 相同 ABI9 closed SDK，core SHA256=
  `6b39533b615f71403b35da072d24c6afc0e99400c3d55e2b7faca2b0f163d44d`，新增 exact-generation、replacement
  generation 和 metadata-plan 不持有 route 三项测试=`3 passed/0 failed`；
- 本节记录时 `cargo check -p fluxon_pyo3 --lib && cargo test -p fluxon_kv --lib` 仍在隔离 tmux 执行；最终
  结果见 11.78。r50 的 `6.997695 QPS` 不覆盖当前代码。

### 11.78 2026-07-23 11:26–11:31 HKT：r51 本地完整门禁通过

- 同一固定 NVMe target、同一 r48/r50 ABI9 CUDA closed SDK 下，`cargo check -p fluxon_pyo3 --lib` 通过；
  随后的完整 `cargo test -p fluxon_kv --lib` 以 rc=0 结束，结果=`198 passed/0 failed/0 ignored`。新增 3 项
  Plan/Bind 测试和既有 cancellation/singleflight/reclaim/lease/framework 生命周期测试全部包含在内；
- 四个 active Python 文件使用 NVMe `PYTHONPYCACHEPREFIX` 完成 compile；r42 GPU staging lifecycle validator
  直接对 active runtime/adapter 执行并通过。最终 `cargo fmt --all -- --check` 与 `git diff --check` 通过；
- 第一次最终 rustfmt 复核误在没有 `Cargo.toml` 的 `Fluxon/` 目录运行，命令以 usage error 退出；立即改到
  `Fluxon/fluxon_rs/` 重跑通过。这是验证命令工作目录错误，不是代码编译或测试失败；
- 本地门禁至此关闭。下一步只复用 r48 schema6/ABI9 CUDA SDK 与 r47 schema6/ABI9 host-only SDK，构建
  隔离 r51 GPU/CPU wheel；随后先跑完全相同的 GPU-direct 与 planned CPU fallback 逐字节 smoke。两条均通过
  后，才允许用 r49/r50 原固定负载和配置做正式性能裁决。

### 11.79 2026-07-23 11:33–11:36 HKT：封包前发现短暂 Allocation 持有并收紧 Plan 快照

- r51 GPU release 启动约两分钟后，封包前静态复核发现 Plan 虽不再把 route 放进 `PlannedGetInfo`，但候选
  列表仍通过 `.cloned()` 保存完整 `KvRouteInfo`；Allocation backing 的 `Arc` 因而会跨
  `planned_gets.insert(...).await` 短暂存活。它不是 r50 的 60 秒 activity 问题，但不满足“Plan 完全
  metadata-only、不持有物理资源”的硬边界；
- 已向本轮隔离 build tmux 发送 Ctrl-C，pane dead status=`1`，在 wheel 生成前停止；该 attempt 不产生可部署
  release，也不登记构建失败。确认没有遗留 r51 nspawn/build 进程后才修改源码；
- 新增轻量 `PlannedGetSourceSnapshot`，候选阶段只复制 node id、node generation tag、addr/base/len；不复制
  backing。构造最终 `PlannedGetInfo` 后在第一个 await 前显式 `drop(route)`。已有 weak-route 测试同时持有
  source snapshots 后再 drop route，确保 metadata 候选本身也不延长 route/Allocation 生命周期；
- 本轮在 `master_kv_router/get.rs` 相对 11.78 再净增 `+22/-0`。当前 Fluxon HEAD-relative 净状态更新为
  11 文件 `+3191/-63`，相对 r50 最终工作树为 5 文件 `+317/-0`；11.77 的 `+295/-0` 是严格收紧前中间状态；
- 11.78 的完整 `198/0` 发生在这 22 行之前，不能覆盖当前最终源码。fmt/diff 已重新通过，当前正以相同
  ABI9 SDK 串行重跑 `fluxon_kv`/`fluxon_pyo3` check、3 项定向测试和完整库测试。全部通过后才重新启动
  GPU/CPU release build。

### 11.80 2026-07-23 11:36–11:42 HKT：r51 最终本地门禁关闭

- `fluxon_r51_full_gate2` 使用固定 NVMe target 和 r48/r50 同一 schema6/ABI9 CUDA closed SDK；
  `cargo check -p fluxon_kv --lib`、`cargo check -p fluxon_pyo3 --lib` 通过，3 项 Plan/Bind 定向测试为
  `3 passed/0 failed`；
- 全量 `cargo test -p fluxon_kv --lib` 以 rc=`0` 完成，结果为 `198 passed/0 failed/0 ignored`，
  用时 `187.98s`。该轮启动于 11.79 的 22 行严格 source snapshot 改动之后，因此取代
  11.78 的中间通过结果；
- 同一最终工作树上，`cargo fmt --all -- --check`、`git diff --check`、四个 active Python 文件
  的 NVMe pycache compile、r42 staging AST/lease lifecycle validator，以及 r51 build/deploy/smoke 三个 shell
  的 `bash -n` 全部通过；
- 当前净 diff 仍为 Fluxon HEAD-relative 11 文件 `+3191/-63`；r51 相对 r50 最终工作树
  仍为 5 个 Rust 文件 `+317/-0`。本节没有代码改动，只更新验证结论；
- 本地门禁现在允许重新启动隔离 r51 GPU/CPU release build。wheel 产物、PyO3 哈希、
  双机 GPU-direct/CPU fallback 逐字节 smoke 和固定负载仍未验证，不得将本地 `198/0`
  写成集群正确性或性能结果。

### 11.81 2026-07-23 11:42–12:03 HKT：r51 双 wheel 构建、封包断言修正与 variant 门禁

- 在 `/dev/nvme0n1p3` 上串行构建 r51 GPU CUDA 与 CPU host-only 隔离 release。两个 wheel
  均完成 release compile、packaging、manifest 和 r42 staging lifecycle validator；GPU wheel SHA256=
  `c0d85b879eb6f8072e1505f19cb7e76c7cb893712e4c0820255f8a1050ec64c1`，CPU wheel SHA256=
  `1a5a06ae9318cfdb297ea62d668ef7c4407b45ba4a11e826839005cf64a02744`；两者 PyO3 均为
  `0d1ee92db91ea58a31e78ce796f1d22a31a10e14ffafbb7a4e9d6715cdddba64`；
- 首次外层 wrapper 在双 wheel 生成后 rc=`1`。逐项诊断证明不是 compile、validator、wheel 或
  manifest 失败，而是新 wrapper 错把 auditwheel 改写 RPATH/ELF 后的 wheel 内 `.so` 与原始
  closed SDK `.so` 要求逐字节相等。r50 封存的 package 哈希本就与 raw SDK 哈希不同，
  因此该断言在语义上错误；
- build wrapper 改为分层校验：raw SDK 通过 manifest copy、`closed_sdk_inputs.sha256` 和
  `readelf` provenance 封存；wheel 内 core/probe/cudart 对齐同 SDK/同 packaging tool 的 r50 封存哈希；
  CPU wheel 另确认不包含 `libcuda`/`libcudart`。同时增加 `E44_R51_FINALIZE_ONLY=1`，仅对已成功
  生成的产物补 provenance 和重封 manifest，没有为修正验证脚本重复编译。finalize-only
  rc=`0`，GPU/CPU release manifest 再次通过；
- 最终 package 哈希为 GPU core=`e64bcfb...148c`、probe=`e925553e...5883`、cudart=
  `5b8de0ee...dc82`；CPU core=`63c08ee6...e06`、probe=`e925553e...5883`。这些与 r50 同
  closed SDK 封装完全相同，只有 open-side PyO3 随 r51 代码变化；
- 新增 r51 variant 和 guarded launcher 白名单。variant 回读为 Get32、tier1 5%、
  `prefix_end_depth_ratio/288`、DMA0、相同 runtime/adapter hash；正式 workload SHA256 仍为
  `f6721d76b7248f365bf44e98bedfe3ea40db2c9f70d08a4922de620e54003f52`。r51 编排相对 r50
  归档合计 6 文件 `+202/-1`，其中四个新文件共 183 行、variant `+18/-0`、guard
  `+1/-1`。下一门禁是三节点隔离部署后先跑 GPU-direct 和 planned CPU fallback 双路逐字节
  smoke；目前不得记录为集群正确性通过。

### 11.82 2026-07-23 12:03–12:06 HKT：r51 三节点隔离部署通过

- 部署前 32656/30245/30729 均无 Fluxon、SGLang 或 `inference_like_compute.py`；两个 GPU
  节点仍只有 managed burner，GPU0/1 均约 `1395 MiB/100%`，本节未发请求；
- GPU release 部署到 32656/30245 的独立
  `venv-fluxon-e44-r51-metadata-only-plan-gpu-20260723`，CPU release 部署到 30729 的独立
  `venv-fluxon-e44-r51-metadata-only-plan-cpu-20260723`；没有覆盖 r50 venv；
- 部署 wrapper rc=`0`。两个 GPU 节点回读 wheel=`c0d85b87...64c1`、PyO3=
  `0d1ee92d...ba64`、core=`e64bcfb3...148c`、probe=`e925553e...5883`；CPU 节点回读
  wheel=`1a5a06ae...744`、同一 PyO3、core=`63c08ee6...e06`、probe=`e925553e...5883`；
- 三节点 release manifest、wheel import、runtime/adapter hash、variant Get32/DMA0/end-depth288 和 staging
  validator 全部通过。部署后再次确认无实验服务/inference，两侧 burner 未被意外停止。
  下一步由 smoke runner 精确停 burner、确认 GPU0/1 清零，再跑同 key/seed/size 的 GPU-direct
  与 planned CPU fallback 逐字节对账，退出时恢复 burner。

### 11.83 2026-07-23 12:06–12:11 HKT：r51 GPU-direct/planned CPU fallback 双 smoke 通过

- runner 启动前精确停止 32656/30245 的 managed burner 和 `inference_like_compute.py`，两机
  GPU0/1 均回读 `0 MiB/0%`后才启动隔离 control/master/两 owner；两 owner 的 1 GiB
  smoke pool 各预热 1 个 512 MiB grant，`free_slots=113`；
- writer 固定 key=`fluxon_e44_r51_metadata_only_plan_smoke_20260723`、seed=`73`、size=`4,718,592 B`，
  payload SHA256=`bd0c9278e27fd0bd53070cea6c3da1c2d0b1a36d0b0520c1174baa58387bed19`；
- GPU reader 出现 `FLUXON_PPLX_REVERSE_COPY_BATCH batch_items=1`，注册 destination 收到的 size/SHA256
  与 writer 完全相同，明确打印 `remote-owner GPU Get data smoke: passed`；planned CPU fallback
  随后完成 `plan → Bind → transfer → holder`，size/SHA256 也完全相同，明确打印
  `planned CPU fallback data smoke: passed`；
- runner rc=`0`。退出 trap 后 master/owners/control/smoke/inference 全为 0；两机四个 managed
  burner 均恢复，每卡约 `1395 MiB/100%`。owner 在 cleanup 的 `Shutdown Complete` 之后仍出现历史
  `view of module has been dropped before spawn` destructor panic；它发生在两条数据 smoke 已通过且主动
  清场之后，不影响本轮 payload 正确性，但仍保留为未修复的 shutdown 生命周期问题；
- r51 集群 correctness smoke 门禁关闭。下一步仍只允许原 S96×T24/2304/c24/system8192/
  output8/session-stream/Get32/tier1 5%/end-depth288/DMA0/metadata-only 128/128/256 GiB 固定负载；
  workload SHA256 必须为 `f6721d76...3f52`。

### 11.84 2026-07-23 12:11–12:20 HKT：r51 原固定负载启动门禁通过

- smoke 恢复 burner 后，正式启动前再次停止两机 burner 和 inference。首次 guarded
  preflight 在 GPU 已为 `0 MiB/0%` 时拒绝了一个仍存活的 burner watchdog；按 burner 脚本
  `cancel-restart` 取消自动回收并精确终止 watchdog 后，32656/30245 两侧 guarded
  preflight 均通过。该次拒绝发生在服务和请求之前，不构成 workload attempt；
- control/Greptime/master 就绪，GPU owner 每侧固定 `128 GiB`、CPU owner 固定 `256 GiB`。
  两侧 owner-local reserve 各为 232 grants、`26216` free slots、物理预留
  `124554051584 B`；CPU owner 也完成预留。两侧 TP2 SGLang health=200，TP0/TP1 分别
  注册 CUDA device 0/1 的 288-slot staging；
- 三端 500 ms HCA observer 已持续产生样本，最终发流前 node0/node1/node2 分别已有
  `220/221/221` 行；router 对两个 worker 完成注册，health=200；
- 最终发流门禁再次确认：两侧 burner/watchdog/`inference_like_compute.py` 为 0，GPU 上只有
  预期 SGLang scheduler；三 owner 存活；workload SHA256=
  `f6721d76b7248f365bf44e98bedfe3ea40db2c9f70d08a4922de620e54003f52`；Get=`32`、tier1=`5%`、
  `prefix_end_depth_ratio/288`、DMA=`0`；新 r51 result 目录不存在，没有混入旧 attempt。
  截至本节仍未发 2304 个正式请求。

### 11.85 2026-07-23 12:20–12:31 HKT：r51 原固定负载完成，正确性通过、性能 no-go

- 正式窗=`1784780437.3668532–1784780720.0516405`，即 04:20:37–04:25:20 UTC；workload rc=`0`，
  `2304/2304/0`，QPS=`8.150420906`。TTFT p50/p90/p99=`1.264154/5.580731/9.657809s`，E2E=
  `1.631151/6.964901/11.388809s`；L1/L2/L3=`5.042752/0/68.141353%`，总命中=`73.184105%`；
- 相对 r50，QPS=`+16.4729%`、总命中=`+6.9682pp`；metadata-only Plan 明显修复了 r50 回退。相对
  r49，QPS 仍为 `-21.3461%`、总命中 `-1.4215pp`，所以 r51 不能替代 r49 性能基线；
- Mooncake L2+L3=`68.0051%` 的阶段目标已达到，r51 高 `0.1363pp`。下一阶段不再优先追命中率，而是
  降低命中后的 Plan/load-back 代价；
- master Plan 终态累计 `items/hits/misses=1352832/1244250/108582`，Bind=
  `353000`、stale=`338`、activity Busy=`0`、Revoke=`891250`。hit 中只有 `28.37%` 真正 Bind，
  `71.63%` 最终 Revoke；两个 owner planned CPU local/leader/follower 合计=`835300/208976/0`，
  local 项相当于 Revoke 的 `93.72%`。证据表明当前 local-first 发生在 master Plan 之后，虽避免重复数据
  传输，却没有避免 metadata/RPC/plan-entry 工作；
- 成功 load-back=`3899`，ready-wait mean/p90/p99=`1030.562/3600.377/7508.741ms`，total mean=
  `1306.330ms`；较 r50 的 `3681/1344.839ms` 恢复，但仍差于 r49 的 `4300/721.245ms`；
- GPU-direct selected=`262/2208`、selected tokens=`4619584`；`insufficient_free_slots=634`、
  `gpu_prefix_shorter_than_cpu=715`。当前实现仍是按一次 load-back 整段选择 GPU 或 CPU，不支持同一次请求
  GPU+CPU 混合分段；
- source-evict requests/victims/completed/retryable=`887/274641/272048/2593`。Busy 相对 r50
  `11227` 下降 `76.90%`，`bind_activity_busy=0`；两侧 handoff=committed、selected/retry/debt/pending 和
  master activity/inflight 最终全部闭合。Remote Put transfers=published=`104982`，active/failed=0；CPU
  retained=`55341/261131599872B`；
- CPU 双 HCA TX avg/active-avg/p99/peak=`47.688/84.309/251.418/351.881Gbps`，远未打满 800Gbps。
  三端 HCA 共导入 `6326` 行；node0 raw 全窗有 1 个采样错误，但正式窗口三端 sample error 均为 0，不能把
  raw 窗外错误写成正式窗错误；
- 系统化扫描 master/router、两侧 owner/SGLang 和 CPU owner：正式窗口内 fatal、P2P 608、prefill OOM、
  scheduler exception、refill timeout、conflict exhausted、segfault、ERROR level 全为 0。人工停栈后才
  复现 owner 析构 panic、master KeyboardInterrupt unwrap 和 Ctrl-C traceback，继续作为独立 lifecycle TODO。

### 11.86 2026-07-23 13:04–13:38 HKT：r52 owner-local-first、remote-only Plan 与混合 source 收口

- 控制流按最终边界实现：external 先批量请求自己的 owner 做 local-only probe；owner 在
  `OwnerKeyControlTable` 同一 per-key fence 内核对可见性并安装 external holding，避免“判为 local”与 reclaim
  pin 之间出现空窗。只有 `None` 的位置才形成 `remote_keys` 并访问 master metadata Plan；全 local 请求不访问
  master Plan；
- CPU execute 只把 remote `(key,get_id)` 交回 owner，继续复用原有 per-key Get singleflight；local holders 与
  remote holders 按原 key 顺序合并。GPU execute 只对 `gpu_remote_indices` 安装 destination，local 位置保留 owner
  CPU 地址；SGLang staging reserve 也从“整个 transferable prefix 页数”收缩为“remote positions 页数”。这没有
  把 key 改成 batch，也没有改变 atomic group 或容量 victim 边界；
- PyO3/Python `get_transfer_gpu` 现在返回统一 source plan，计划本身持有 local holders；SGLang sync/layerwise
  restore 都从同一有序 plan 取 CPU/GPU 指针，并把 plan 与可选 GPU lease 一起持有到 CUDA 完成后释放。短前缀
  tail drop local holder、remote Revoke；plan/CPU/GPU terminal 等待继续使用 abort-safe pending guard；
- 最终审查又发现一个 owner restart 窗口：GPU execute 曾在 generation 二次校验前调用 `holder.bytes()` 构造
  slice。现改为 Bind 前及 transfer terminal 后各校验 owner generation、offset/len、base pointer 与保存地址，
  中间只把 `holder.addr` 当不透明地址传递，不提前解引用旧映射；新增纯几何回归覆盖 stale generation、越界和
  地址不匹配；
- 容量驱逐仍严格单 KV pop/fence/reclaim，projected credit 仍只认已安装 fence 的 bytes；remote Put 仍是
  `(key,put_id)` owner singleflight，没有新增 actor/FIFO。本节未改 master/local Moka victim 语义、tier1、Get32、
  end-depth288、metadata-only 容量或 288-slot GPU 总预算。

### 11.87 2026-07-23 13:38–13:48 HKT：r52 本地门禁、三态 smoke 编排与构建起点

- 相对 r51 release manifest 的逐文件最终净 diff：
  `client_kv_api/msg_pack.rs +73/-1`、`client_kv_api/external_api.rs +128/-12`、
  `client_kv_api/mod.rs +88/-12`、`external_client_api/mod.rs +686/-138`、
  `fluxon_pyo3/src/lib.rs +28/-0`、`fluxon_py/kvclient/fluxon.py +33/-5`、
  `hicache...py +20/-10`、`unified_radix...py +64/-78`、validator `+36/-0`、既有 GPU smoke
  `+6/-1`，合计 10 文件 `+1168/-258`。这是最终工作树净 diff；其中 rustfmt 的机械换行覆盖若干中间状态，
  不能据此反推全部人工工作量；
- 新增 `smoke_e44_r52_mixed_source.py 246` 行、build wrapper 12 行、deploy wrapper 18 行、master YAML 28 行、
  smoke wrapper 15 行，共 319 行；既有通用 build wrapper `+6/-6`、smoke runner `+23/-0`、deploy common list
  `+1/-0`。新 smoke 会先验证 local-only 的 `gpu_remote_indices=()`，再对 `[local,remote]` 断言
  `gpu_remote_indices=(1,)`、只使用一个 GPU destination、统一 plan 原顺序与两个 payload 逐字节一致；既有
  remote GPU 和 planned CPU fallback 也继续执行；
- 第一次全量测试误用了旧 bundled schema5/ABI8 SDK，结果 `191 passed/9 failed`；9 项均在 framework 创建
  closed transfer engine 时共同报 `DecodeRequest { detail: "bitcode error" }`。历史总账已有同一错误签名，
  切换到 `/mnt/nvme0/mjq_build/fluxon_closed_sdk_abi9_pplx_cuda_r48_single_worker_gpu1_20260722/lib` 后，修改前
  r52 同一源码为 `200/200`，确认前轮是无效环境结果而非回归；
- stale-owner 修复后新增测试用完整名称定向执行 `1/1`；一次不完整 `--exact` 名称得到
  `0 passed/201 filtered` 后立即纠正，明确不算测试通过。最终 ABI9 全量=`201 passed/0 failed/0 ignored`，
  184.96s；`cargo check -p fluxon_pyo3 --lib`、Python NVMe pycache compile、staging lifecycle validator、
  shell `bash -n`、fmt 与 diff check 均通过；
- 固定 target=`/mnt/nvme0/mjq_build/push_sglang_fluxon_target` 已由 `findmnt` 证明位于
  `/dev/nvme0n1p3`。13:48 HKT 已启动隔离 r52 GPU CUDA/CPU host-only 双 wheel build；本节落账时尚未取得
  build rc、wheel/PyO3 hash，不得写成构建、部署或集群 smoke 已通过。下一步只在 build rc=0 后补 variant/guard
  精确 hash，再部署并执行四条逐字节门禁。

### 11.88 2026-07-23 13:48–14:10 HKT：r52 双 release 封包完成

- GPU CUDA 与 CPU host-only build/finalize 均 rc=`0`；release 分别为
  `/mnt/nvme0/mjq_build/fluxon_e44_r52_owner_local_first_gpu_cuda_20260723` 和
  `/mnt/nvme0/mjq_build/fluxon_e44_r52_owner_local_first_cpu_host_20260723`，均位于
  `/dev/nvme0n1p3`；
- GPU wheel SHA256=`d4c7a41d3e9442dba4654e350c6671aa354b234eeda2049677643ae35a3aad53`，CPU wheel=
  `0d1359704ee6a9c9a3f288861a2be9c66c4291f0447db3aed5dd4bd9791fe5bf`，共同 PyO3=
  `a0cf3087e32335b6dc6e25d8f6bc546a70bbb864cd5f160453030cf94ff8ee33`；GPU wheel 内
  core/probe/cudart=`e64bcfb3...148c/e925553e...5883/5b8de0ee...dc82`，CPU wheel 内
  core/probe=`63c08ee6...e06/e925553e...5883`；CPU wheel 不含 CUDA runtime；
- 两份 `fluxon_release.sha256`、closed SDK provenance、PyO3/runtime/adapter hash、r52 variant 和 guard
  均补齐并通过。`ext_images.tar.gz` 两份均为
  `15319a7670d3a1d186a45586b37db5a09842353fb37dab10ea828228b484f7e1`，与 r51 sealed release
  完全相同；这为后续不重复搬运 service images 提供了精确 identity 门禁；
- 本节只关闭 release build 门禁。此时尚未完成新分发器、三节点安装或数据面 smoke，不能把 wheel 构建写成
  集群正确性结果。

### 11.89 2026-07-23 14:10–14:30 HKT：共享-stage单次上传与三节点独立部署通过

- 旧通用 deploy 会把每份 release 的 `ext_images/`（约 834 MiB）和 `ext_images.tar.gz`
  （485,462,220 B）从外部对三节点逐台复制，单轮仅不可变 service-image payload 就重复搬运约 3.8 GiB。
  用户要求改为一次进入内网后复用；进一步实测确认三个节点的 `/storage` 是共享视图，因此最终实现收紧为
  “公网只上传 node0 一次、其他节点直接读取共享 stage”，无需第二次数据复制；
- 新增 `deploy_e44_two_stage_node_install.sh` 192 行。每个目标独立执行 transport manifest、完整
  `fluxon_release.sha256`、完整 `ext_images/ext_images.sha256`、wheel/PyO3/core/probe、GPU cudart、variant、
  runtime/adapter 和 staging validator；只有所有角色门禁通过后才发布 active symlink。目标上如存在
  Fluxon/SGLang 则 fail-closed；SSH agent forwarding 只转发认证能力，不把私钥复制到远端；
- 通用 deploy 生成排除 `ext_images/` 与 tar 的 GPU/CPU delta、公共配置和 netobs tools，全部 staging I/O 位于
  `/mnt/nvme0/mjq_build/e44_two_stage_deploy`。公网实际 payload 合计=`91,471,430 B`，只传
  `116.238.240.2:32656` 一次。node1=`10.233.114.138:2222`、CPU 当前地址=
  `10.233.91.204:2222` 均先通过公网/内网 hostname identity 对账；两端随后检测到共享 stage，
  `shared_stage=1`、内部 payload=`0`，但仍各自在自己的进程/动态链接环境中重验并安装；
- `ext_images` 不进入任何 transport。每个目标从本机 r51 sealed release 以 hard link 复用 tar 和展开树，硬链接
  失败即终止，不允许静默回退成 copy。三端回读 r52/r51 tar 与 `ext_images.sha256` 的 device/inode 一致，
  tar link count=`2`；三端完整 ext manifest 也各自通过，因此不是只凭文件名复用；
- 设计演变如实保留：原三公网 `scp` attempt 在部署完成前主动中止，没有发布 r52；第一版新 installer 已通过
  node0 transport/release/wheel 门禁，但 standalone 脚本沿用了旧双引号远程命令中的转义写法，错误搜索
  `max_replica_pages_per_batch\":288`，在后置 variant gate rc=`1`。active symlink 当时仍为 r51，失败 stage
  已清理。改成搜索真实 JSON 的 `max_replica_pages_per_batch":288` 后重跑 rc=`0`。随后发现共享存储并删除
  无意义的 node0→node1/CPU `scp`，最终共享-stage版本再次完整重跑 rc=`0`；前两版是被覆盖的中间实现，
  不计为最终测试结果；
- 最终三端 active release：32656/30245 为
  `fluxon_e44_r52_owner_local_first_gpu_20260723`，30729 为
  `fluxon_e44_r52_owner_local_first_cpu_20260723`。三端 transport stage 均已清理，Fluxon/SGLang/inference
  进程为 0；两个 GPU 节点 managed burner 未被部署流程停止，每卡约 `1386 MiB`；
- 文件统计以可复核的 r48 sealed deploy 为基线：通用 deploy=`+348/-94`，新增 node installer=`+192/-0`，
  两文件合计=`+540/-94`。该 archived baseline 同时跨过 r49–r52 编排演进；相对本方向修改前，两个文件总行数
  从 `184+0` 变为 `432+192`，最终净增 440 行，但没有保存即时 preimage，故不能伪造该即时基线的精确
  added/deleted 拆分。最终文件 SHA256 分别为 deploy=`5cb544de...15c2`、installer=`3b0e1dac...c27b`；
- `bash -n`、NVMe `findmnt`、两次最终三节点真实 deploy、active symlink/hard-link inode、无进程和无残留 stage
  回读均通过。本节只验收分发与安装，不是数据面 smoke，也没有新 QPS。下一门禁仍是 local-only、remote CPU、
  remote GPU、mixed `[local,remote]` 四条逐字节 smoke；在此之前不能进入正式 2304 请求性能裁决。

### 11.90 2026-07-23 14:35–14:43 HKT：分发规约固化与 r52 四态逐字节 smoke 通过

- 根目录 `AGENTS.md` 新增“集群发布与共享存储分发规约”共 `+9/-0`：公网 payload 只允许通过 node0 上传一次
  到共享 stage；stage 已共享可见时禁止内部重复 `scp`；每个目标仍须独立完成 transport/release/wheel/ABI/
  runtime/adapter/active-symlink 门禁；`ext_images` 只有 SHA256 identity 完全一致才可 hard-link 复用，identity
  变化也只能上传一次 canonical payload；本地打包必须使用 `/mnt/nvme0`，内网 endpoint 要做 hostname identity
  对账，禁止复制工作机私钥。该规约用于防止未来重新退回“三公网传输”或无校验复用；
- smoke runner 启动前确认 32656/30245 active release 均为 r52，旧 Fluxon/SGLang/inference 为 0；随后精确停止
  两侧 burner/watchdog 并确认 GPU0/1 均为 `0 MiB/0%`，才启动隔离 control、master 和两 owner；
- remote writer 在 node1 写入 `4,718,592 B`、seed=`73` payload，SHA256=
  `bd0c9278e27fd0bd53070cea6c3da1c2d0b1a36d0b0520c1174baa58387bed19`。node0 GPU reader 出现真实
  `FLUXON_PPLX_REVERSE_COPY_BATCH batch_items=1`，注册 destination 回读 size/SHA 完全一致，remote GPU smoke
  通过；
- node0 local writer 写入同尺寸 seed=`41` payload，SHA256=
  `23e77a1dfec357463ea976ed0f7a4186b0c98d5b5c40e0608d9264118cc6da37`。local-only 请求断言
  `gpu_remote_indices=()` 并逐字节通过；mixed `[local,remote]` 断言 `remote_indices=[1]`、只分配一个 GPU
  destination、source plan 保持原 key 顺序，mixed local/remote 两份 SHA 分别与上述 payload 完全一致；
- planned CPU fallback 对 remote key 返回 path=`planned_cpu_fallback`，size=`4,718,592 B`、SHA256=
  `bd0c9278...ed19`，逐字节通过。至此 local-only、remote CPU、remote GPU、mixed 四类均有真实数据验证，
  runner rc=`0`；
- cleanup 已停止 control/master/两 owner，隔离 tmux session 为 0；32656/30245 的 Fluxon/SGLang/inference
  进程均为 0，四个 managed burner 均恢复，每卡约 `1386 MiB/100%`。本轮没有 SGLang 正式请求、没有 QPS；
- r52 correctness smoke 门禁关闭。下一步固定负载不得改动：S96×T24、2304 请求、c24、system8192、output8、
  session-stream、Get32、tier1 5%、`prefix_end_depth_ratio/288`、DMA0、metadata-only `128/128/256 GiB`，
  workload SHA256=`f6721d76b7248f365bf44e98bedfe3ea40db2c9f70d08a4922de620e54003f52`。

### 11.91 2026-07-23 14:43–14:48 HKT：正式轮前 CPU 动态地址门禁

- smoke 后正式 preflight 回读 node0/node1/CPU 私网地址分别为
  `10.233.114.139/10.233.114.138/10.233.91.204`。GPU/CPU launcher 仍把 CPU 旧实例地址
  `10.233.125.128` 写死；若原样启动，CPU owner 会以不存在的本地/peer 地址注册，三节点负载无效；
- 只做基础设施参数化：GPU launcher 的 node0/node1/node2 三个地址改为“环境变量优先、历史地址默认”，
  `+3/-1`；CPU launcher 三个地址同样改为环境变量优先，`+3/-3`。合计 `+6/-4`，没有修改容量、Get32、
  tier1、end-depth、DMA、staging、模型或 workload；本轮显式传入 CPU=`10.233.91.204`；
- 两脚本 `bash -n` 通过，SHA256 分别为 GPU=`94b371d9...4d0d`、CPU=`7f55db1a...6fa9`；随后使用最终
  shared-stage deploy 重装三端，rc=`0`，公网 payload=`91,471,469 B`、node1/CPU 内部 payload=`0`，三端完整
  manifest/install 回读再次通过；
- 14:47 HKT 三节点 Fluxon/SGLang/inference 均为 0，两侧 burner 仍在。现在允许按 r51 原固定负载清场并启动；
  本节不是 workload attempt，也没有性能结果。

### 11.92 2026-07-23 15:13–15:28 HKT：r52 netobs 修复、原样复跑与清场

- attempt1 的 GPU HCA 样本失败不是 HCA 本身不可用，而是部署后 `libibmad.so`、`libibumad.so` 位于
  netobs tools 根目录，observer 的 `LD_LIBRARY_PATH` 却固定指向 `lib/`。node installer 已把 real so 放入
  `lib/`，并在安装门禁增加 `ldd` no-missing 和直接 HCA query；三节点重新共享-stage部署、独立校验和短
  observer preflight 均通过；
- attempt2 没有修改模型、负载或性能参数。仍为 S96×T24、2304 请求、c24、system8192、output8、
  session-stream、Get32、tier1 5%、end-depth288、DMA0、metadata-only `128/128/256 GiB`，workload
  SHA256=`f6721d76...03f52`；正式请求窗=`1784791946.605422254–1784792175.981770654`；
- workload rc=`0`，三端正式 HCA window 各 450 intervals、sample error=`0`，全量 HCA 行=`13368`、错误=0。
  CPU 双 HCA TX avg/active/p99/peak=`77.612/112.298/275.772/302.455 Gbps`，TX bytes=
  `1197878446036+985206539100=2183084985136 B`；
- 全栈扫描 fatal、P2P 608、prefill OOM、scheduler exception、refill timeout、conflict exhausted 均为 0。
  结果取证完成后 router/SGLang、三 owner、master/control 和 observer 全部停止；两 GPU 节点恢复四个 managed
  burner，每卡约 `1395 MiB/100%`，`inference_like_compute.py` 和推理进程为 0。

### 11.93 2026-07-23 15:28–16:04 HKT：r52 attempt2 正式结果与 r39 主基线纠正

- attempt2=`2304/2304/0`，QPS=`10.217138124`，wall=`225.503460s`；TTFT p50/p90/p99=
  `1.408684/2.880661/9.432097s`，E2E=`1.949966/3.871677/11.099260s`；L1/L2/L3=
  `4.801224/0/71.261703%`，总命中=`76.062927%`；
- 用户明确纠正性能口径：主对照必须是同一批新 GPU 上的无 GDR r39=`10.605922059`，不能用更低的 r49
  给 r52 作放行基线。r52 相对 r39 QPS=`-3.67%`、wall=`+3.81%`；总命中反而高 `0.4597pp`，TTFT/E2E
  p50 也略好，但 TTFT/E2E p99 分别恶化到 `9.432/11.099s`。attempt1 同样为 QPS=`10.321654`、TTFT
  p99=`8.830s`，两轮尾部方向重复。正式裁决为 correctness pass、performance no-go；
- 成功 load-back 从 r39 的 4336 个 TP-rank 降至 r52 的 4202 个；逻辑 rate-limited 从 18 增至 61。
  initial-start/Get-transfer 均值从 `28.431/10.794ms` 降到 `20.494/3.784ms`，证明新的 local-first/remote-only
  准备路径没有整体变慢；但 ready-wait p99 从 `2.465s` 升到 `6.917s`，total p99 从 `2.926s` 升到
  `7.142s`；
- r52 node0 有 76 条 TP-rank，即 38 个逻辑请求，ready-wait>`5s`；node1 和 r39 两节点均为 0。38 个中
  30 个是 `no_remote_sources`、6 个 selected、2 个 insufficient。最慢 local-only 请求的 initial-start 约
  `15–20ms`、Get-transfer 约 `0.16–0.27ms`，ready-wait 却为 `7.4–7.8s`，因此不能归因于 RDMA、master
  Plan 或真实 transfer；
- owner-local probe 最终 node0 local/remote=`268836/495246`，node1=`546828/166266`，合计
  local/remote=`815664/661512`，local=`55.22%`。node0 local 仅 `35.18%`、remote 是 node1 的约 2.98 倍；
  node0/node1 GPU admission insufficient=`574/40`。同一 prompt 分配下，node0 总命中从 r39 `77.68%`
  降至 `74.67%`，node1 从 `73.25%` 升至 `77.64%`；收益偏到 node1，node0 成为 straggler；
- node0 TP0 prefill queue mean/max 从 r39 `4.382/17` 变为 r52 `6.788/22`，pending-token mean/max 从
  `95499/373121` 变为 `157681/594788`；node1 queue mean 则从 `3.753` 降至 `3.032`。已证实 node0 出现
  排队→prefetch 限流→少命中/多计算→进一步排队的闭环；当前尚未用同代码开关 A/B 证明最初触发点是 GDR
  staging lease 过早占用、local-first 的突发节奏，还是当轮路由/缓存放置偏斜，不能把相关性伪装成根因闭环；
- CPU HCA TX avg/bytes 相对 r39 从 `142.516 Gbps/3.867 TB` 降至 `77.612 Gbps/2.183 TB`；owner remote
  transfer bytes 从约 `3.829 TB` 降至约 `1.669 TB`。网络削减真实存在，但 r39 HCA avg utilization 仅
  `17.8%`，所以它没有转成 QPS；
- 本节最初把“当前 r52 完整 GDR-off”列为下一必跑单变量；16:49 HKT 经用户纠正并回读 r39 封存源码后确认，
  r39 owner `batch_get()` 本来就先 local visible hit、只把 `missing_keys` 交给 Start/remote transfer。该建议已
  取消：r39 本身就是 local-first、无 GDR 基线；r52 GDR-off 只在未来需要拆 Plan/Bind 固定开销时作为辅助诊断。

### 11.94 2026-07-23 16:04 HKT：r52 attempt2 分析文档与证据归档

- 新增直白分析文档 `20260723_1604_fluxon_r52相对r39无GDR性能裁决与下一步.md`；初版 131 行，16:49 HKT
  修正后 135 行。文档明确 r39 主基线、既有 local-first 语义、网络收益边界、node0 尾部、节点 locality/命中
  偏斜和有界 GPU-direct + CPU remainder 下一步；
- 远端证据原包 SHA256=`d85fc62f69d719293602b9ef3179824a3de9771200f215e35d3a8a75baea0963`。
  先在 `/mnt/nvme0/mjq_build/e44_r52_attempt2_full_extract_20260723` 完整解压，再复制到 Ceph artifact，未把
  大量随机 I/O 中间目录写到源码树；
- artifact=`experiment_configs/e44_local_slot_tier_20260716/artifacts/e44_r52_owner_local_first_attempt2_passed_20260723/`，
  包含完整 remote snapshot、原始 evidence tar、load-back/Get-ready derived JSON 和 15 行 README。旧 46 MiB
  中断快照已由同一证据包完整补齐，没有删除或覆盖用户源码。artifact 最终 97 个文件、约 352 MiB；96 个
  非 manifest 文件全部进入 `SHA256SUMS`，`sha256sum -c` 全量通过。

### 11.95 2026-07-23 16:49 HKT：r39 已有 local-first 的事实纠正与实验计划收口

- 用户指出“以前那版就已经有 local-first，remote 只有 local miss”。回读 r39 封存
  `release_manifest/source_client_get.rs` 后确认：`batch_get()` 先逐项调用 `local_visible_mem_holder()`，local hit
  直接构造 holder 返回；只收集 `missing_indices/missing_keys`，且仅对 `missing_keys` 调
  `batch_get_start()`。后续 transfer 也只遍历这些 miss 的 Start items。用户纠正成立；
- 先前将“r39 没有 local-first”作为 r52 GDR-off 必跑理由是错误表述，已从 Snapshot 和分析文档撤销。
  r52 的真实变化是为了 Plan/GDR 把既有判断显式提前成 owner-local probe，并让 miss 进入 Plan/Bind/GPU
  destination；不是首次实现 local-first；
- 下一步不重复跑 GDR-off 来建立基线。P0 直接针对 GDR 增量做 remote 内部分流：local 过滤后，remote items
  使用有界 GPU-direct 子集，剩余 remote 同请求走 CPU staging；不得因拿不到全部 slots 就整批 CPU fallback，
  也不得让单个 281–288 页 lease 在 scheduler 队列中占满整个 288-slot pool 数秒；
- 新实现补 submit/terminal/first-poll/load-back-start、lease ready/release age 与申请时 queue/pending tokens，
  然后原固定负载直接与 r39 QPS=`10.605922` 裁决。若未来仍需区分 GDR 数据面与 Plan/Bind 固定开销，
  r52 GDR-off 只作为辅助诊断，不冒充新的无 GDR 基线。

### 11.96 2026-07-23 17:04–17:08 HKT：GDR 收益模型、restore 污染定位与计划修订

- 按用户要求停止直接优化和发流，先从理论、代码、实际采集三条线核查 r52 无收益原因。本节未修改
  Fluxon/SGLang 运行代码、未构建、未部署、未启动实验；`Fluxon` 仍为相同 11 文件
  HEAD-relative=`+4236/-240`，`sglang` 仍干净，旧实验结果不冒充当前新验收；
- 理论模型收敛为：`Net_GDR = 首访 remote→CPU+H2D 相对 remote→GPU+D2D 的节省 + 避免 CPU cache
  pollution - 后续 L2 复用损失 - restore batch 污染 - staging slot-time 机会成本 - Plan/Bind 控制开销`。
  r40 288-page raw H2D 约 25ms；r52 selected 的 remote pages mean node0/node1=`213.35/115.39`，理想
  H2D 绕过上限约 `18.52/10.02ms/request`，全轮 node0/node1 worker-time 上限约 `2.926/1.643s`，且尚未
  扣 D2D 和异步重叠；
- 代码复核发现此前未纳入计划的放大问题：`_start_fluxon_hostless_layerwise_loads()` 用整批
  `any(gpu_staging_lease)` 选择 transport。只要一个 operation 有 staging，整批所有 operations 的 CPU/local
  pages 都从后台 raw H2D 切到 `gpu_direct_d2d_kernel`。这不是单纯“GDR 首访快、L2 复用差”的二选一，
  而是当前实现额外把代价扩散到了非 GDR pages；
- r52 TP0 原始日志重新聚合：node0 kernel=`151 batches/364 operations/104838 pages`，direct remote=
  `33710 pages`；node1 kernel=`158/288/86459`，direct remote=`18924`。全局 restore=`615478 pages`，真实
  GDR remote=`52634=8.55%`，kernel=`191297=31.08%`；kernel/GDR=`3.63×`，其中 `138663=72.49%`
  kernel pages 并非 GDR payload。node0 selected 与 insufficient 两类总 pages mean=`288.39/287.75`，
  initial+Get 约快 `3.27ms`，restore mean 却为 `272.380/225.090ms`；该对比与代码问题同方向，但因合批
  与 local/remote mix 不同，不伪装成随机因果实验；
- lease slot-time 复算：node0 layerwise leases=`158`、slots=`33710`、slot-ms=`31008310.968`，正式窗平均
  live=`137.507/288=47.75%`；node1=`164/18924/13792325.398`，平均 live=`61.162/288=21.24%`。
  node0 slots p50=`287`、held mean/p99/max=`1102.834/7616.759/7993.647ms`，所以平均未满仍会因整段
  申请和长 lease 出现 574 次 insufficient；
- CPU planned path 经原 Get finish 产生 `353643` 个 `local_hot_admissions`；GDR `ExternalSink` 不创建
  holder、不暖 L2。该设计差异已证实，但现有日志没有按 `(key,generation)` 串联首次路径、后续 local hit/
  remote refetch 和 L2 residence/eviction，不能声称复用损失已经被实测为主因。r39/r52 GPU KV 都为
  `200000 tokens/TP`；本轮 staging 未缩小配置 L1，也不能把回退归因于 L1 token 数变少；
- 新增 379 行分析文档 `20260723_1704_fluxon_GDR无收益理论模型_实现核查与下一步.md`；既有 16:04
  文档由 135 行更新为 140 行，增加后续裁决告警并撤销旧 partial-GDR 下一步。新的 P0 是先隔离 restore
  transport，并同版补 per-key reuse/terminal 观测；保持当前 admission/288 slots 测这一单变量。只有首访
  收益确实落在关键路径，才继续 reuse-aware/queue-aware partial GDR。若 CPU 数据在 first poll 前已终态且
  matched 首访收益很小，就停止该性能方向，只保留 GDR 接口正确性能力。

### 11.97 2026-07-23 17:19–17:22 HKT：三级缓存有机协同模型与 trace/replay 门禁

- 用户进一步明确：需要的不是 kernel 搬运快慢或一个 GDR 比例，而是 remote cache、owner-local cache、
  local GPU 容量递减时，对命中复用、搬运带宽和推理输入做统一权衡的底层模型。17:04 的 restore
  transport 污染结论继续有效，但降为必须消除的实现税，不能代替缓存策略模型；
- 模型以三个时间尺度统一决策：`tau(k)`/reuse distance 决定 KV 应驻留 GPU/local/remote 哪层；从现在到
  scheduler 消费的 slack `S` 决定传输是否在关键路径；新 page 挤出的 GPU/local victim 价值和 RDMA/H2D/
  D2D queue 决定容量/带宽影子价格。当前路径的可见等待定义为 `Visible(T,S)=max(0,T-S)`；若 CPU 路径
  能在 deadline 前完成，GDR 即使物理更快，本次可见收益仍为 0；
- GDR 判定收敛为：`NowGain_GDR` 必须大于 `p_same × local-retention 内复用概率 × 下次远端相对 local
  hit 成本差 - local victim value`，再计 staging/传输外部性和避免 L2 pollution 的收益。传输 route 与 local
  admission 因而必须解耦为 CPU+admit、CPU temporary/no-admit、GDR+bypass、GDR+延迟 admit 四态；高复用
  又紧急的 page 可第一次 GDR、二次触达或 GPU eviction 再依据 ghost/reuse score local admit；
- 推理输入按连续 prefix 建模，选择 `m* = argmax[PrefillSaved(m)-TransferVisible(m)-GpuVictimCost(m)-
  CongestionCost(m)+FuturePlacementValue(m)]`。这里的 prefix utility 不改变容量 victim 单 KV 边界，也不把
  `atomic_batch` 变成整组驱逐；partial GDR 只能是该优化的动态输出，不能预设成 10/18/30/50%；
- 当前固定负载代入：GPU=`200000 tokens`；24 并发第一/末轮输入合计=`197568/261600 tokens`，后期超过
  L1。owner-local 128GiB/26216 shard slots 在 TP2 下等价约 `838912` 逻辑 tokens，约为 GPU `4.2×`；单节点
  视角 remote 物理容量=`384GiB`。workload 最终唯一 KV=`129.984GiB`、累计请求 KV=`2692.688GiB`，
  累计/唯一=`20.72×`；输入 token 口径=`21.06×`，说明多轮复用很强。结合 r39 `94.93%` 消费前终态和
  HCA 未饱和，当前模型先验偏向 CPU+local admission，仅把 GDR 用于 CPU 会错过 deadline 且未来低复用的
  pages；这是模型推导，不冒充新实验结果；
- 新增 445 行 `20260723_1719_fluxon_三级缓存有机协同收益模型与策略评估方法.md`，覆盖三级 retention
  horizon、deadline route、prefix utility、带宽影子价格、staging Little's Law、在线三控制器和反事实 replay。
  16:04/17:04 两份旧分析文档均增加后续模型指针，保留历史设计演变；
- 最新门禁随模型修订：P0 只补 reuse lineage、tier residence/eviction、scheduler slack、真实 terminal、
  prefill-saved 与四条 service curve；P1 的离线 replay 必须先复现 r39/r52，随后才比较 deadline-only、
  deadline+reuse、2-hit/ghost、depth-aware、locality-aware 和容量分配。P2 才实现 replay 最优的最小策略，
  同时清零 restore 非 GDR pages 污染；P3 保持固定负载只测一个候选。本节没有代码、构建、部署或 QPS。

### 11.98 2026-07-23 18:31 HKT：GPU staging fixed-slab 下沉 Rust/PyO3

- 本轮响应用户“allocator 交给 Rust，并在 Fluxon PyO3 暴露 tool lib”的明确要求。范围只包括 r52 GPU
  staging 的固定 slot allocator；没有改 GPU tensor/MR ownership、lease 生命周期、all-or-none admission、
  local-first、remote-only Plan、容量驱逐、remote Put singleflight 或 GDR/CPU route。未引入新的配置项、
  actor、partial GDR 或整组驱逐；
- `fluxon_util/src/fixed_slab_allocator.rs` 新增 245 行通用实现：固定容量、确定性 freelist、live bitmap、
  预分配 release validation marks 和内部 `parking_lot::Mutex`。reserve 一次拿齐或完全不改状态；release
  先校验完整向量的越界、重复和 double-free，再一次提交。早期实现曾用每次 release 临时 `HashSet`，
  在代码审查中已被预分配 epoch marks 覆盖；最终工作树不含该中间分配路径，不能把它计入最终净 diff；
- `fluxon_pyo3/src/fixed_slab_allocator.rs` 新增 52 行唯一公开 class
  `fluxon_pyo3.FixedSlabAllocator`，API 为构造、`try_reserve`、`release`、`capacity/free_count/live_count` 和
  `is_empty`；`fluxon_util/src/lib.rs`、`fluxon_pyo3/src/lib.rs` 分别 `+1/-0`、`+3/-0` 完成导出和 module
  registration。没有增加 Python fallback、alias 或 duck-typing 路径；
- 当前 adapter 相对本轮前封存 r52 GPU source SHA256=`5da41b35...edd9` 为 `+29/-18`：删除
  `_free_slots` 的 Python `range/list/pop/extend`，通过 `fluxon_py.tool.import_fluxon_pyo3_local()` 取得强类型
  class，再把 reserve/release/count 交给 Rust；Python `_lock` 继续保证 allocator snapshot 与 admission/
  lease 指标的一致性。validator 相对封存 SHA256=`d2ea3709...185a` 为 `+59/-3`，新增无 Python freelist、
  单次 Rust reserve/release 接线和 reserve→trim→release→close 生命周期断言；
- 本轮实现/validator 即时净 diff 为 6 文件 `+389/-21`；本总账自身相对修改前为 `+56/-8`，完整工作区
  本轮合计 7 文件 `+445/-29`。实现逐文件为
  `fluxon_util/src/fixed_slab_allocator.rs +245/-0`、`fluxon_util/src/lib.rs +1/-0`、
  `fluxon_pyo3/src/fixed_slab_allocator.rs +52/-0`、`fluxon_pyo3/src/lib.rs +3/-0`、adapter `+29/-18`、
  validator `+59/-3`。`Fluxon` 当前 tracked 12 文件 `+4240/-240`，加两个新文件后为 14 文件
  `+4537/-240`；其中本轮前 11 文件 `+4236/-240` 是未独立提交的既有累计状态，未与本轮相加冒充
  键盘工作量；
- 构建目标 `/mnt/nvme0/mjq_build/push_sglang_fluxon_target` 经 `findmnt` 确认位于
  `/dev/nvme0n1p3`。`cargo test -p fluxon_util fixed_slab_allocator --lib` 为 `5 passed/0 failed`，覆盖零容量、
  分配顺序、all-or-none、重用/计数、invalid-release 原子性和 8 线程 64 slot 唯一性；
  `cargo check -p fluxon_pyo3` 与 `cargo build -p fluxon_pyo3` 均 rc=0；Python syntax 和完整 r42/r52
  staging lifecycle validator rc=0；
- 新构建 `libfluxon_pyo3.so` 的真实 Python smoke 最终通过：class 可见，`4→reserve 3→capacity miss→
  release/reuse→duplicate error→full release→double-free error` 和零容量错误均符合契约。第一次裸加载因本机
  找不到 `libcudart.so.12` 被 dynamic loader 拒绝；补 CUDA 路径后又被 Fluxon wheel-local runtime authority
  门禁拒绝。随后只在 NVMe 临时展开 sealed r50 wheel 的 `fluxon_pyo3.libs`，同一新 `.so` smoke 通过，临时
  runtime stage 已清理。前两次是安全打包门禁，不是测试断言失败；
- 当前文件 SHA256：Rust util=`7e848550...f03d`、PyO3 wrapper=`38fbd4da...c8fa`、adapter=
  `d66e5ea4...f955`、validator=`620bccb3...fcf`。这些哈希只标识本地源码，不是 release manifest；
- 剩余未验证项：没有正式 wheel/release，没有三节点共享-stage安装，没有真实两 GPU staging
  registration/transfer smoke，也没有固定 2304 请求结果。因此本轮只能封 allocator correctness，不能把
  r52 QPS=`10.217138` 或任何历史命中率继承为当前代码验收，更不能声称 Rust freelist 已提高吞吐。下一步
  若测试本轮代码，必须先走 release/部署/真实 GPU smoke，再保持原负载与 r39 基线裁决；三级缓存 trace/
  replay、restore 非 GDR 页污染和 scheduler residence 仍是独立的主要性能问题。

### 11.99 2026-07-23 18:39–19:05 HKT：r53 release、共享部署与四态 smoke

- 未再修改 Fluxon/SGLang core，只补 r53 正式编排：build/deploy/smoke/master config 新文件分别
  `12/18/15/28` 行，variant 新 case `+19/-0`，GPU guard allowlist `+1/-1`，合计 `+93/-1`；仍保持
  r52 attempt2 的 Get32、tier1 5%、end-depth288、DMA0、288 slots 和容量/负载不变；
- NVMe GPU/CPU release 分别为
  `/mnt/nvme0/mjq_build/fluxon_e44_r53_rust_slab_gpu_cuda_20260723` 和
  `/mnt/nvme0/mjq_build/fluxon_e44_r53_rust_slab_cpu_host_20260723`；GPU/CPU wheel SHA256=
  `c9e402bed97c2f16974a9221df45444d7f6324a22e90e19cbf492b84cdaa81ff`/
  `3521fce78369908f15a0e985d1a67cf2b53a2a66a03e18dcab569ff8c43a9d39`，共同 PyO3=
  `e107038c791197bc50d02bdbbfc1fa9c5fdc6007af231ec5fdc98e8e726f0075`。两种 wheel 均实际 import
  `FixedSlabAllocator` 并通过 reserve/release/error smoke；
- 共享-stage 部署 rc=`0`。只向 node0 公网上传一次 `91,498,692 B`，node1/CPU 从共享 stage 安装，第二阶段
  payload=`0`；ext_images transport=`0`。三节点独立通过 transport/release/ext_images manifest、wheel、
  PyO3、closed SDK、ABI、runtime、adapter、variant 和 active symlink 回读；
- remote GPU、owner-local-only、mixed `[local,remote]` 和 planned CPU fallback 四态逐字节 smoke rc=`0`。
  allocator 的 GPU/CPU wheel接线、真实 HBM registration、remote→GPU 和释放生命周期通过；smoke 清场后
  未发现 double-free、slot leak、P2P 608、OOM 或 inference 干扰。

### 11.100 2026-07-23 19:05–19:46 HKT：r53 固定负载、性能裁决与瓶颈拆解

- 正式负载逐项复用 r52 attempt2：S96×T24、2304 请求、c24、system8192、output8、session-stream、Get32、
  tier1 5%、`prefix_end_depth_ratio=288`、DMA0、metadata-only `128/128/256 GiB`，workload SHA256=
  `f6721d76b7248f365bf44e98bedfe3ea40db2c9f70d08a4922de620e54003f52`；请求窗=
  `1784805366.5350559–1784805588.0762432`；
- 结果=`2304/2304/0`、QPS=`10.399872043`，TTFT p50/p90/p99=
  `1.487552/2.743263/9.149403s`，E2E=`1.837399/3.685375/10.530922s`，L1/L2/L3=
  `3.868615/0/72.414164%`，总命中=`76.282779%`。相对 r52 attempt2 QPS `+1.79%`，但总命中同时高约
  `0.22pp`、GPU selected 从 322 变为 333；相对无 GDR r39 仍 `-1.94%`。因此只封 allocator correctness，
  不登记性能收益；
- node0/node1 正式请求=`1224/1080`；Prometheus queue mean=`1.2735/0.5350s`，TTFT mean=
  `1.9951/1.1241s`，prefill-forward mean=`0.4344/0.3485s`，prefill-compute tokens=
  `6,885,952/5,038,016`。TTFT 节点差 `0.871s` 中 queue 差 `0.739s` 约占 85%；node0 的有效计算量比
  node1 高 `36.7%`，证明最终等待落在 GPU prefill/空间，而根因更接近路由/locality/未命中工作分配偏斜；
- owner-local plan items 比例 node0/node1=`281585/767680=36.68%`、
  `543991/714058=76.18%`。node0/node1 staging insufficient=`562/42`；selected=`138/195`。每 TP pool=
  `288×4718592 B=1358954496 B`，node0 selected remote pages p50=`281.5`，一个请求几乎吃满 pool；TP0
  slot-time 正式窗 occupancy node0/node1约 `47.98%/21.61%`，但 all-or-none 和突发到达使平均未满仍大量失败；
- selected lease node0 mean/max=`1324.662/8878.476ms`，node1=`811.649/2256.953ms`。与此同时 owner
  4003 次真实远端 Get 的 transfer wall mean/p90/p99=`24.199/45.140/76.636ms`，Get finish total mean=
  `38.065ms`；4235 条成功 SGLang TP-rank lifecycle 的 initial/ready-wait/evict/restore/total mean=
  `20.557/701.108/47.562/196.140/980.624ms`。两种记录不是逐条 operation identity join，不能直接相减，
  但数量级足以排除“RDMA 搬了约 1 秒”；秒级 lease 主要跨越 scheduler 等待与 restore；
- 三端 HCA sample error=`0`。CPU 双 HCA TX avg/p99/peak=`77.792/298.808/350.430Gbps`，为 800Gbps 的
  `9.72%/37.35%/43.80%`。不能排除微观 flow-control stall，但链路未持续饱和，且 Get transfer 为几十毫秒，
  网络容量不是当前秒级尾部主因；
- correctness 扫描：333 次 selected 中消费 331 次；layerwise selected lease release=`333`，另 50 次
  reservation fallback 均释放；无 double-free/slot leak、OOM、P2P608、refill timeout 或 conflict exhausted。
  Remote Put 两侧 transfers=published、failed=0，owner active handles/flights/debt均归零；master holdings/activity
  为 0。master `active_plans=52`，r52 也残留 45，登记为既有 Plan bookkeeping TODO，不算 r53 回归；
- 结果目录=`/storage/mjq/mooncake_m1/mooncake_perf_workloads/results/20260723_111603_agent_multiturn_long_context_fluxon_e44_r53_rust_slab_enddepth288_netobs_s96_t24_sys8192_out8_c24_session_stream_20260719_b9a25d47`；
  HCA summary=`/storage/mjq/sglang_fluxon/fluxon_f1/e44_local_slot_tier_20260716/netobs_results/e44_r53_rust_slab_enddepth288_netobs_formal_summary.json`；
  admission=`.../e44_r53_gpu_admission.json`，新增 derived=`.../e44_r53_get_ready_breakdown.json` 与
  `.../e44_r53_loadback_lifecycle.json`。Greptime 已导入 HCA 3984 行；完整 r53 artifact 尚未复制回工作区；
- 新增 144 行直白分析文档 `20260723_1946_fluxon_r53收益不大_瓶颈定位与精准Prefetch方案.md`。下一门禁先补
  metadata-ready、reserve/RDMA-start、terminal、consume/restore/release 和 queue position；确认
  `terminal→consume` 后，只让 queue-head `K` 个近期请求 GDR。P1 前保持 288 slots、不扩大 pool、不做
  partial split；远期请求先落 DRAM且不得重复传输。若该单变量仍无 QPS，转做 Fluxon locality/remote-cost
  aware routing；
- 取证后 r53 workload/router/SGLang、三 owner、master、HCA observer、control/etcd/Greptime均已停止。
  32656/30245 四个 managed burner恢复，约 `1395 MiB/100%`；无 `inference_like_compute.py` 或推理进程。

### 11.101 2026-07-23 20:08–20:27 HKT：r54 精确 prefetch 时间线首轮实现

- 本轮只做 observation-only。Rust external GPU Get 在后台 transfer task 发布终态时记录 `Instant`，pending
  handle 同时保存 transfer start；`get_transfer_gpu()` 由同一进程直接计算 `transfer_wall_us`、
  `terminal_before_consume`、`terminal_to_consume_us` 和 `finish_wait_us`。该终态位于数据传输、cleanup 与
  master Done 之后，能够把“数据早已完成但 scheduler 尚未消费”与“消费调用真实等待 RDMA”拆开；
- PyO3 把四个强类型字段加入既有 terminal dict；Python `GpuGetStartHandle` 在原一次性 consume 后保存这些
  字段，adapter 仍返回同一个 `int plan_ptr`。没有新增 status RPC、轮询线程、actor、第二次 Get 或新 RTT；
- 隔离 runtime 继续复用现有 `req_id`，记录 enqueue/实际 post-policy scan 的 queue position、queue length、
  pending/uncached tokens，以及 plan ready、reserve、execute return、transfer consume、RDMA start/terminal、
  load-back consume、restore queued/complete 与 staging release。scheduler 只在原调用点前写快照，不按任何
  新字段分支；CacheAware、队列顺序、288 slots、all-or-none admission 和 CPU/GPU 决策未改；
- 相对 sealed r53 源快照，Fluxon 三文件为 `+176/-10`；隔离 runtime/adapter/scheduler 分别为
  `+223/-1`、`+8/-1`、`+26/-1`，新增 validator 195 行。r54 build/deploy/smoke/master wrapper 共 112 行；
  共享部署入口增加可选 scheduler payload/hash 门禁，旧 variant 未设置该字段时维持原行为；
- 本地门禁：NVMe target 位于 `/dev/nvme0n1p3`；Rust fmt、PyO3 check、四份 Python compile、旧 r42 lifecycle
  validator、新 r54 AST/identity validator、shell syntax 和 diff check均通过。定向 timing test 覆盖 terminal
  先于/晚于 consume 两态，最终真实结果 `1 passed/0 failed`。第一次误带不完整 `--exact` 只过滤出 0 tests，
  随后正确重跑；该空跑未计通过；
- 尚未通过全量 202 tests、双 release、wheel import、共享 stage、四态 smoke 或正式 2304 请求，因此当前只算
  implementation/local-gate pass。variant 内 PyO3 SHA 仍为 `PENDING`，必须在 release 完成后回填并重新跑
  hash/配置门禁，不能以 r53 QPS 或命中率验收 r54。

### 11.102 2026-07-23 20:27–20:43 HKT：r54 全量门禁与 scheduler 基线纠正

- 正确 ABI9 closed SDK 下执行 `cargo test -p fluxon_kv --lib`，最终 `202 passed/0 failed/0 ignored`，耗时
  `186.15s`，status=`0`；完整日志与状态分别为
  `/mnt/nvme0/mjq_build/e44_r54_full_test_20260723.log` 和
  `/mnt/nvme0/mjq_build/e44_r54_full_test_20260723.status`；
- scheduler 隔离源重新以线上 sealed r53 的精确版本为基线，而不是相近的本地副本。r53 基线
  SHA256=`705c23b1...7177`，r54 净差仍仅为观测代码 `+26/-1`，当前
  SHA256=`cf20558f2a13f01a858e2e4155ca4283b0f6a28fba118446944c47fb37161ee8`；runtime/adapter
  SHA256 继续为 `920cb610...e554/eb1e0848...8ccd`；
- 双 release 已于 20:36 从 NVMe target 启动构建，构建 target 经 `findmnt` 确认为 `/dev/nvme0n1p3`。因为构建
  启动早于 scheduler 基线纠正，产物完成后必须逐项核对三份源码；若产物 scheduler 不是上述 SHA256，只允许
  覆盖 release provenance 文件并重算、全量校验 `fluxon_release.sha256` 后再部署；
- 当前仍无新的集群性能结果。后续门禁保持：补 PyO3 hash、三端共享-stage 独立安装校验、四态逐字节 smoke、
  固定 S96×T24/2304/c24/Get32/tier1 5%/end-depth288/128/128/256 GiB 正式负载，再以 r54 时间线裁决
  `RDMA terminal → scheduler consume → restore → lease release`。

### 11.103 2026-07-23 20:43–20:54 HKT：r54 双 release 封存

- 双 release 构建最终 status=`0`，GPU/CPU 目录均位于 `/dev/nvme0n1p3`。GPU/CPU wheel SHA256 分别为
  `168dd441222d50c743282a277bae9476207633fba9d00bb9ed0d07b52d94aba1` 和
  `9004d93f799ce0de630794f90128bebc1b1b03314bd2286e42fd3b17156b0ccc`，共同 PyO3 SHA256=
  `2f3cf88322c937de744298716c55fef92ea30e85b18a664119872c72ee10645c`；
- GPU core/probe/cudart=`e64bcfb3...148c/e925553e...5883/5b8de0ee...dc82`；CPU core/probe=
  `63c08ee6...e06/e925553e...5883`，CPU wheel 明确不含 `libcuda/libcudart`。CPU wheel 的
  cp310/cp311/cp312 ABI3 import 全通过；GPU wheel 在无 NVIDIA driver 的本地 build rootfs 中仅因外置
  `libcuda.so.1` 不存在给出预期 warning，必须由真实 GPU 节点安装/import 和四态 smoke 收口；
- 两个 release 的 `fluxon_release.sha256` 均全量通过。构建后逐项复核 release 内 runtime/adapter/scheduler
  SHA256=`920cb610...e554/eb1e0848...8ccd/cf20558f...61ee8`，validator 与当前源一致；
  `source_external_client_mod.rs/source_fluxon_pyo3_lib.rs/source_python_fluxon.py` 也与当前 Fluxon 源逐字节一致，
  因此没有发生“构建启动早于 scheduler 纠正”造成的旧文件混入；
- variant 中 r54 的 PyO3 从 `PENDING` 回填为上述共同 hash（既有文件单行 `+1/-1`），随后 shell syntax、r54
  validator、Get32/DMA0/run-id/hash 配置门禁通过。下一步是共享-stage 部署，不能跳过三节点独立回读。

### 11.104 2026-07-23 20:54–21:00 HKT：r54 共享部署与四态 smoke

- 共享-stage 部署 status=`0`。公网 payload 只经 node0 上传一次，共 `91,814,244 B`；node1 与 CPU 均检测到
  `shared_stage=1`，内部 payload bytes=`0/0`。`ext_images` identity=`15319a76...7e1`，传输 bytes=`0`；
- node0/node1/CPU 分别完成 transport manifest、完整 release manifest、`ext_images.sha256`、wheel/PyO3、
  GPU/CPU closed runtime、variant、runtime/adapter/scheduler、metadata-only host patch 与 active symlink 回读。
  三端 PyO3 均为 `2f3cf883...645c`，真实 GPU 节点 import 成功，收口本地 build rootfs 无 driver 的预期 warning；
- 四态 smoke status=`0`：remote GPU payload SHA256=`bd0c9278...ed19`；owner-local payload=
  `23e77a1d...a37`；mixed 只为 `remote_indices=[1]` 分配一个 GPU destination；planned CPU fallback 返回同一
  remote payload。真实 remote GPU 路径输出 `transfer_wall_us=7599`、`finish_wait_us=7561`、
  `terminal_before_consume=false`、`terminal_to_consume_us=0`，新增 terminal timing 强类型字段验收通过；
- smoke cleanup 后两 GPU 节点无 owner/master/smoke 进程，managed burner/watchdog 已恢复，四卡约
  `1395 MiB/100%`。下一门禁是再次停 burner 并清场，启动原固定 S96×T24/2304/c24/Get32/tier1 5%/
  end-depth288/128/128/256 GiB 正式负载，同时采集 Greptime 与三节点双 HCA。

### 11.105 2026-07-23 21:00–21:16 HKT：正式启动 API 失败与兼容修复

- 首次正式启动前已再次停 burner/worker，四卡 `0 MiB/0%`；control/Greptime、三端 HCA、master、CPU 256 GiB
  owner、两侧 128 GiB owner 均 ready。第一次 GPU launch 被仍存活的 burner watchdog 正确拦截，模型加载前
  两侧 rc=`1/1`；精确停止 watchdog 并复核四卡空闲后 attempt2 进入模型加载；
- attempt2 两侧模型均完成约 `30374 MiB/GPU` 加载，但首个健康请求同形失败：
  `SchedulerLoadInquirer` 没有 `get_num_waiting_uncached_tokens()`。错误位于 r54 scheduler 观测代码，不是
  Fluxon transfer、容量路径或模型 OOM；两侧未进入正式 workload，请求量=0，因此无合法 QPS/命中率；
- 根因是本地相近 SGLang 源含该新 API，而线上 sealed r53 的 installed load-inquirer SHA256=
  `8e61f49f...420e` 只有 `_get_num_pending_tokens()`。scheduler 虽以线上 r53 文件为文本基线，但首版 validator
  没核对其依赖 API，四态数据 smoke 也不启动 scheduler，故此前门禁未覆盖；
- 修复保持 observation-only：pending 继续调用线上存在的 `_get_num_pending_tokens()`；uncached 改为遍历
  `waiting_queue`，用既有 `seqlen - len(prefix_indices)` 且下限 0 计算。没有改队列、CacheAware、reserve、
  GDR/DRAM 决策或负载。scheduler 相对 r53 由 `+26/-1` 变为 `+36/-1`，新 SHA256=
  `5bf313d801c8aded9ea43eee32515b47569324b8f507f5b9f8a895b722f026ef`；validator 从 195 行增至 207 行，
  明确禁止再次调用缺失 API并要求 enqueue/consume 两处均从 installed request fields 派生；
- Python compile、r54 validator、analyzer self-test、variant/deploy shell/hash 门禁通过。双 release finalize-only
  status=`0`，wheel/PyO3 不变；scheduler/validator 已替换，两个 `fluxon_release.sha256` 已重算并全量通过；
- 失败栈、三端 HCA、control 已停止，四个 managed burner 恢复。修复版尚未部署/smoke/正式负载；旧 smoke
  不覆盖当前 `5bf313d8...26ef`，不得复用为验收结果。

### 11.106 2026-07-23 21:16–22:06 HKT：r54 修复版正式轮异常与环境/实现边界

- 修复 scheduler API 后完成共享部署、smoke 和正式启动门禁，负载仍为原 S96×T24/2304/c24/Get32/tier1 5%/
  end-depth288/metadata-only `128/128/256 GiB`；异常不是换负载或正常 QPS 波动；
- node1 closed PPLX 在一次 228-item planned-CPU Get 中只完成 4 个 batch/43 items 后不再推进。环境/closed
  数据面停滞是最初触发器；但旧 owner handler 已把 228 个 per-key flight 从 `Starting` 推到 `Finishing`，随后
  300 秒 P2P RPC timeout 直接取消整个 handler，把其中的 finish future 一起丢弃；
- 后续相同 operation 的 466 个请求均命中 singleflight follower，没有 caller 能再取得 leader 并完成 Done，最终
  形成 planned transfer/refill timeout、P2P 608、prefill OOM 与实例退出。也就是说，环境故障解释“第一次为什么
  超时”，Fluxon 取消不安全解释“为什么一次超时永久毒化所有重试”；两者不能只归为环境波动；
- 异常轮没有完整 2304 请求和合法 summary，禁止登记 QPS。证据已固化到
  `/mnt/nvme0/mjq_build/e44_r54_prefetch_timeline_failed_20260723`；workload/router/SGLang、三 owner、master、
  observer/control 全部停止，四个 managed burner 恢复。

### 11.107 2026-07-23 22:06–22:31 HKT：r55 cancellation-safe 修复与本地门禁

- 在 owner 已为所有 leader 发布 `Started` 后，不再在入站 `external_execute_planned_get` RPC future 内直接拥有
  `finish_external_get_key_leaders`。改为由 framework task registry 启动独立后台任务，并行完成 leader
  transfer/Done 与 unused-operation revoke cleanup；caller timeout/drop 不再能把 flight 留在 `Finishing`；
- external scheduler 前台 planned-CPU RPC timeout 从 300 秒缩为 P2P 允许的最小显式 10 秒，让 SGLang 尽快
  fallback；generation-safe uncertain replay 仍使用相同 operation identity 和 300 秒 timeout，拿到终态后只负责
  释放未消费 holder。没有新增 actor、FIFO、第二套 singleflight 或容量 victim 语义；
- 相对 sealed r54 core 为 2 文件 `+58/-13`：`client_kv_api/external_api.rs +30/-10`、
  `external_client_api/mod.rs +28/-3`。当前 Fluxon HEAD-relative tracked 总计 12 文件 `+4444/-233`，另有 r53
  fixed-slab 两个未跟踪文件 297 行；不能用当前累计净 diff冒充本轮独立工作量；
- NVMe target 已确认为 `/dev/nvme0n1p3`。fmt/diff check、相关测试 `23/23`、新增 timeout 边界测试 `1/1`、
  `cargo test -p fluxon_kv --lib=203/203`（186.79s）通过。

### 11.108 2026-07-23 22:31–23:01 HKT：r55 双 release、共享部署与 228-item 压力 smoke

- 新增 r55 build/deploy/smoke wrapper 与压力程序共 285 行，并在既有 variant、GPU guard、通用 deploy/smoke
  runner 中接线；正式 variant 明确复用 r54 master config、runtime/adapter/scheduler 和负载，只替换 Fluxon wheel；
- 双 release 构建 status=`0`。GPU/CPU wheel SHA256=`9361e324...3005f/48f202e8...e0551d`，共同 PyO3=
  `fb0a770a...88ace1`；完整 release manifest、CPU ABI3 import 和 GPU/CPU closed runtime identity 均通过；
- 两次共享-stage部署均只向 node0 上传一次 `91,832,907 B`，node1/CPU `shared_stage=1` 且 payload=`0`，
  ext_images transport=`0`。第二次部署只为了分发修正后的 smoke gate，没有重编 core/wheel；
- 第一轮 stress 已实际成功：228 items、`1,075,838,976 B` 数据校验正确，owner 分 100+128 items 完成，
  transfer wall=`15.938/17.054ms`、finish total=`17.962/20.305ms`，35 秒后的 owner/master 状态均为 0。但 tracing
  日志字段夹有 ANSI code，旧 `grep -F active_flights=0` 误报失败；runner 已停栈并恢复 burner。随后先 strip ANSI
  再检查固定字段，同一历史日志 replay gate 通过；
- 修正后从头重跑 status=`0`：remote GPU、local-only、mixed、planned CPU fallback 和 228-item stress 全部逐字节
  通过，最终 `active_flights=0`、`finishing_flights=0`、`inflight_gets=0`。cleanup 后四个 managed burner 均为
  managed/running、100%；没有进入正式性能轮。停栈时既有 module-view 析构 panic 只在首个误判后的强制清理日志
  中出现，与历史 r34 的 lifecycle P1 同形，单列待办，不冒充本次数据路径失败。

### 11.109 2026-07-23 23:01–23:19 HKT：正式轮环境门禁与等价配置启动

- variant/source/YAML 门禁确认 r55 逐项复用 r54：S96×T24、2304、c24、system8192、output8、session-stream、
  Get32、tier1 5%、`prefix_end_depth_ratio=288`、DMA0、metadata-only `128/128/256 GiB`；共同 PyO3=
  `fb0a770a...88ace1`。没有换负载、调并发或改容量；
- 第一次并发启动时，两个 burner compute 已清零，但 watchdog PID=`55831/39808` 仍存活；GPU guard 在模型加载前
  正确拒绝两侧启动。等待中的 CPU launcher被中断并清理，未发正式请求。精确 kill watchdog 后四卡重新确认为
  `0 MiB/0%`，从三端启动阶段完整重来；该轮属于环境门禁拦截，不算正式 attempt；
- 第二次启动两侧 owner member/transfer-ready/shared.json、128 GiB reserve、CPU 256 GiB owner、两侧 SGLang HTTP
  200全部通过。metadata-only 两个 TP 均为 `materialized_pages=1`；实际 launcher内 Get32、depth288 JSON与
  128 GiB owner config回读一致；master activity=0；
- node0/node1 HCA observer在首次门禁前已运行。CPU observer随 CPU retry cleanup被同 run-id session规则清掉，
  正式前 `status=stopped` 被复核发现并重新启动，旧文件被清空；因此正式窗三端均有连续 500ms sample，而不是
  静默复用旧 CPU 样本。router健康后才启动 workload。

### 11.110 2026-07-23 23:19–23:41 HKT：r55 固定负载、精确时间线裁决与清场

- 正式请求窗口=`2026-07-23 15:19:48.205758–15:23:34.913290 UTC`，runner rc=`0`、timed_out=false、
  Greptime points/phase/write errors=`1656/1/0`。请求=`2304/2304/0`、QPS=`10.162873628`；TTFT
  p50/p90/p99=`1.387430/3.115027/8.871205s`，E2E=`1.898480/4.040898/10.897057s`；L1/L2/L3=
  `6.260350/0/69.096177%`，总命中=`75.356527%`；
- 相对 r53 QPS `-2.279%`且总命中同时低 `0.926pp`；相对 r52 attempt2 QPS `-0.531%`；相对 r39 no-GDR
  QPS `-4.177%`。当前数据只能封 cancellation-safe correctness，不能把 r55写成吞吐优化；
- 正式完成后 owner/master所有 flight/activity/remote-Put/retry/debt终态归零；正式窗 P2P608、OOM、scheduler
  exception、planned owner RPC failure 和真实 refill timeout均为 0。两个 SGLang `server_args` 长行含 refill/
  timeout 字段，被宽松 grep各误计 1 次，逐行复核后排除；
- 原 analyzer 首次因同一 req/rank出现不同 attempt 报 conflicting duplicate。日志证明 scheduler会为同一 req进行
  2–4 次独立 scan，而不是同一终态被破坏。工具净改 `+40/-11`：保留每次 attempt、增加 `attempt_index`，只对
  重复输入的同一 resolved file去重；compile/self-test和集群重算通过。旧 r35 analyzer同样依赖单 lifecycle，
  本轮不再使用；
- 最终 4777 条 TP-rank timeline：selected=`674`、成功 consume=`661`、terminal-before-consume=`545`
  (`80.86%`)；RDMA wall mean=`44.03ms`、finish wait mean/p50=`6.80/0.001ms`，terminal→consume
  mean/p90/p99=`564.73/1031.99/7273.49ms`，reserve→release mean=`927.45ms`，post-terminal lease fraction
  mean=`84.53%`。node0 terminal→consume=`805.44ms`，node1=`346.91ms`；
- HCA正式窗三端 error=0，Greptime HCA导入 9410 行。CPU双 HCA TX avg/p99/peak=
  `69.273/262.219/301.725Gbps`，未接近 800Gbps。GPU两个 pod看到相同物理 HCA counter，明确不重复求和；
- artifact=`artifacts/e44_r55_planned_get_cancel_safe_enddepth288_netobs_passed_20260723/`。取证后正式栈和三端
  observer全部停止，实验进程为0；Ctrl-C后既有 module-view析构 panic仅列 lifecycle P1。node1首次恢复 burner
  时 GPU0 状态为 managed-waiting，执行 stop/kill/空卡复核/clean-start 后两侧四卡最终均为
  `running (managed)`、`1395 MiB/100%`，无 inference 干扰。
