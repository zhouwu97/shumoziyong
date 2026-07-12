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
- Execution Spec 所有路径统一拒绝绝对路径、空段、`.`、`..`、反斜杠、盘符和 Windows 设备名；Spec 本身也拒绝 symlink/hardlink。
- Executor 只读取 Run Root 的 `execution_spec.json`，校验完整不可变身份，并强制 Python `argv` 解析到批准的 entrypoint。
- 文件名、`artifact_type`、状态、Schema、指标、不变量、最优性声明和负控要求由公共 verifier 交叉绑定。
- Collector Attestation 的输入、代码、环境、Spec、日志、负控报告和固定输出集合均现场复算；候选输出访问标志必须为 `true`。
- Eligibility 显式进入 Verifier Summary、Gate 3、Run Evidence、Seal 和 `verify_run()` 输出。
- 在 Capability 引用深验证和真实 Sandboxie 激活前，机器派生固定为 `formal_result_eligible=false`，成熟度最高为 `foundation`。

## 未实施且不得越界声称

- P1 完整 Formal Result Builder 和 Domain Backend Registry。
- Milestone 2 的真实 Sandboxie 环境绑定与 12 项负控。
- Milestone 3 的双 Collector、空目录复现和封闭 Reproduction Bundle。
- Milestone 4 的 Capability Bundle、Reviewer 外部治理、资格题、盲测与模拟赛。

## 已确认的远程验证

- 上一轮独立复审冻结 HEAD：`3e24e15f434362e245f58c66d83b1583179d7474`
- 本轮修复代码有效 HEAD：`4e80b72becf353dea302c1eb56829ef16d4398b6`
- 本轮代码最新验证 GitHub Actions Run：`29189481081`
- 验证矩阵：Ubuntu / Windows × Python 3.11 / 3.12 全部通过。
- 冻结对象当时的本地全量回归：`269 passed, 10 skipped`，覆盖率 `82%`。
- 本次可信收口工作树：`286 passed, 10 skipped`，覆盖率 `82%`；Ruff、Pyright、仓库验证和确定性构建均通过。

该记录只确认上述提交的代码质量门，不代替独立审查，也不授权提前合入 `main`、
打正式 Tag 或声明 Sandboxie 环境已经验证。

因此当前最高允许表述为：

> Formal Result 合同和 Seal 绑定已完成代码收口候选，真实 Sandboxie 环境尚未激活。
