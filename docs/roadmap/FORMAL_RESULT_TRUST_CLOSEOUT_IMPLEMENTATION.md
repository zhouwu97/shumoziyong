# Formal Result Trust-closeout 实施状态

## 执行基线

本分支按 `shumoziyong 正式结果信任收口、真实环境验证与能力证明路线图 v1.1`
的 Milestone 1 实施。这一阶段只收口代码与证据合同，不声称真实 Sandboxie
环境、Executor 或建模能力已被证明。

## 已实施的 P0 边界

- `full_replay` 和 `new_problem` 新 Run 默认使用 `formal_result_policy=required_v1`。
- 策略、Execution/Formal/Gate Contract Version 与 Canonicalization Version 进入 Run 不可变身份。
- `legacy_read_only_v1` 只允许历史验证与导出，禁止 advance、complete、seal 和 fork。
- 文件 SHA-256 与 Schema 后的 JSON 语义 SHA-256 分开记录。
- Gate 3 通过公共 `verify_formal_result_bundle()` 强制 Envelope、Domain Manifest、精确文件集、身份和哈希链。
- Formal Result 核心文件进入 Run Evidence Manifest，Seal 再绑定该 Evidence 与 Envelope。
- 删除、替换、改名、格式哈希混用、策略降级和合同版本漂移均失败即关闭。

## 未实施且不得越界声称

- P1 完整 Formal Result Builder 和 Domain Backend Registry。
- Milestone 2 的真实 Sandboxie 环境绑定与 12 项负控。
- Milestone 3 的双 Collector、空目录复现和封闭 Reproduction Bundle。
- Milestone 4 的 Capability Bundle、Reviewer 外部治理、资格题、盲测与模拟赛。
- 远程 Ubuntu/Windows × Python 3.11/3.12 CI 独立确认。

因此当前最高允许表述为：

> Formal Result 合同和 Seal 绑定已完成代码收口候选，真实 Sandboxie 环境尚未激活。
