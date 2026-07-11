# `competition_evidenced` 判定规则

文件名为兼容旧链接保留。`competition_evidenced` 表示已有正式比赛证据，不表示 Patch 已被普遍证明有效。

## 候选条件

只有同时满足当前 `promotion_policy.json` 的回归、失败修复重测、比赛记录和人工批准要求，才允许建议进入 `competition_evidenced`：

1. 至少通过 2 道不同题号的 T3/T4 官方旧题。
2. 两次总控诊断均 >= 80。
3. 两次均未出现 P3/P4/P5。
4. 两次均未出现 M1/M2/M3/M5。
5. 测试题不与当前 patch 来源论文同题、同附件或共享关键结果。
6. 测试记录、闭环摘要和训练日志均完整。
7. 已由人工确认是否正式标记 `competition_evidenced`。

## 禁止标记 `competition_evidenced`

出现以下任一情况，不得标记 `competition_evidenced`：

- 只通过 1 道旧题。
- 只跑了 T0/T1/T2。
- 读取了优秀论文、题解、参考答案或含结果解析作为题面。
- 材料存在 M1/M2/M3/M5。
- 出现 P3/P4/P5。
- 依赖大量人工补题意。
- 新版本表现低于旧版本。
- 缺少可追踪测试记录。

## 日志口径

`training_log.md` 中“通过旧题数量”只统计 T3/T4。T0/T1/T2 可记录事实，但不得增加通过次数。
