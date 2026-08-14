# Cache-aware Session Sweep 监督重试修改总账（已合并归档）

## 当前累计状态 Snapshot（2026-08-05 12:44 HKT）

| 项目 | 当前状态 |
|---|---|
| 状态 | 本文件的有效内容已合并到同目录`修改总账.md`；后者是当前唯一权威Snapshot。本文件只保留首次污染轮和监督设计的历史取证。 |
| 最终结果 | cache-aware S96/S80/S64/S48 QPS=`4.871536/5.666326/8.566005/23.310434`；相对RR提升`1.99%/0.60%/24.74%/76.79%`。 |
| 最终归档 | `/public/mjq/mooncake_m1/results/mooncake_h36_cacheaware_session_sweep_20260805/h36_sessions_cacheaware_guarded_1367_31772_20260805_0302_a1`，mode0555，1,184项；两端全量校验通过。 |
| 监督结论 | hard-abort会受scheduler退出竞态和探测超时影响；最终采用generation-safe PID观察并在正式窗后审计。最终S64/S48后缀1,108 samples、0 violations；外部GPU3 unittest轮已排除。 |
| 工作树 | observer、测试和resume runner已经同步为sealed r7版本并通过`4/4 + 5/5 + 2/2`测试及shell语法检查。 |
| 后续 | 不再在本文件维护新状态；所有新实验和修改继续写入主`修改总账.md`。 |

## 修改与验证历史

### 2026-08-05 12:44 HKT：合并完成

- 本文件10:29–10:33的污染判定和监督设计已经完整并入主总账；原始条目继续保留，避免把中间失败改写成最终成功。
- 最终归档、三版deployment、被替代尝试、正式结果、源码净diff和验证记录均以主总账12:44 Snapshot为准。

### 2026-08-05 10:29–10:33 HKT：否决污染S96并新增全窗监督设计

- 首次自动启动前已要求四张目标卡连续空闲10分钟；它只能防止在decoder轮次间短空窗启动，不能防止外部用户在本轮模型启动后再次发起decoder。
- S96正式replay时间为02:29:58 UTC。30秒监控在02:29:54仍记录GPU3上的额外PID58907/58908/58910；由于采样边界无法证明它们在02:29:58前已经退出，按fail-closed规则否决该点。
- 只终止本轮run-scoped tmux、服务和端口，没有向外部decoder发送信号。失败证据保存于旧结果根`INVALID_ATTEMPT_S96_20260805_0229`；旧series-id不再复用。
- 新方向是在独立进程中只读采样目标GPU compute PID并检查祖先链的唯一series-id。该观察器只产生证据和invalid marker；监督wrapper只在marker出现时终止自己的runner，外部PID始终不处理。
