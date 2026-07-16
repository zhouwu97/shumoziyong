# Gate 5 失败审核与历史账本审计

## 审计结论

当前 Gate 5 是一个单一、可覆盖的根文件合同：`<run_dir>/gate_5_review.json`。它只允许成功完成审核，不存在失败审核记录、不可变 history、当前指针或恢复协议。计划中的 `needs_revision` 闭环不能通过向该文件直接追加字段而安全实现。

审计样本：`runs/2024C_v21_full_replay_20260715/`。

## 单文件绑定证据

| 责任 | 实际位置 | 当前行为 |
| --- | --- | --- |
| Schema | `schemas/gate_5_review.schema.json` | `decision` 固定为 `approved`，`final_acceptance` 固定为 `true`，八项 checklist 均固定为 `true`。 |
| 初始化 | `scripts/run_workflow.py` 的 `_initialize_common_gate_artifacts` | 创建根文件 `gate_5_review.json`。 |
| Gate artifact | `scripts/run_workflow.py` 的 `GATE_ARTIFACT_SPECS` | Gate 5 固定绑定 `gate_5_review.json`；样本 manifest 同样指向该文件。 |
| Evidence | `scripts/run_workflow.py` 的公共 Evidence 构建逻辑 | Evidence 固定包含该根文件。 |
| 完成校验 | `scripts/run_workflow.py` 的 `_load_and_validate_gate_5_review`、`mark_run_completed` | 再验根文件，拒绝非 approved、非 final acceptance 或任一 checklist 为 false 的内容。 |
| 转换事件 | `scripts/run_workflow.py` 的 `mark_run_completed` | `completed` 事件固定引用 `gate_5_review.json` 及其 SHA。 |

因此，`gate_5_review.json` 不是可选展示文件，而是完成转换、Gate manifest 和 Evidence 的同一事实源。

## 当前状态机边界

`replay_transition_log` 与 `_replay_v2_transition_log` 允许 Gate 0 至 Gate 4 记录 `approved` 或 `rejected`；`rejected` 不推进当前 Gate。Gate 5 的 `completed` 转换则只接受 approved，并再次校验同一个根审核文件。

当前没有以下能力：

- `record_gate_5_review` 写入入口；
- `reviews/gate5/` 之类的审核记录目录；
- `gate_5_review_history.jsonl`、当前审核指针或审核 ID；
- 从 `needs_revision` 返回可执行修订 Run 的状态转换；
- 审核记录到 history、Evidence、Gate manifest 的事务或孤立文件恢复。

## 持久化、并发与封存顺序

| 主题 | 实际实现 | 风险/限制 |
| --- | --- | --- |
| JSON 单文件写入 | `scripts/run_workflow.py` 的 `write_json` | 使用临时文件、fsync、replace；单文件落盘原子，但不覆盖多文件事务。 |
| 转换日志写入 | `_append_transition_event` | 使用全量原子重写并维护哈希链；没有单 Run 写锁，多个写者可产生 lost update。 |
| 既有锁 | `_acquire_fork_lock`、`fork_profile` | 仅为 fork-profile 服务，不是 Gate 5 可复用的通用写锁。 |
| 完成与封存 | `complete_and_seal_run`、`scripts/finalize_run_evidence.py` | 现顺序是先 `mark_run_completed` 写 completed transition，后生成最终 Evidence/Seal；不满足计划中同一完成临界区的目标顺序。 |

## 运行样本确认

在 `runs/2024C_v21_full_replay_20260715/` 中，以下文件均围绕唯一根审核文件建立：

- `gate_5_review.json`
- `gate_artifacts/gate_5.manifest.json`
- `run_evidence_manifest.json`
- `transitions.jsonl`

样本与基线代码一致，不存在隐藏的 Gate 5 history 或失败记录目录。

## 后续改造的实际落点

这是审计确认的 PR 2 实施面，不是本次变更：

| 目标 | 必经现有位置 |
| --- | --- |
| 版本化审核记录及兼容规则 | `schemas/gate_5_review.schema.json`，并视版本策略新增独立 Schema |
| 记录、历史、当前指针、写锁与恢复 | `scripts/run_workflow.py` 的 Run 路径、JSON 写入与转换日志逻辑 |
| Gate 5 manifest/Evidence 绑定 | `scripts/run_workflow.py` 的 `GATE_ARTIFACT_SPECS` 与 Evidence 构建逻辑 |
| `needs_revision` 状态重放 | `_replay_v2_transition_log` 及相关事件 Schema/写入入口 |
| 最终完成临界区 | `mark_run_completed`、`complete_and_seal_run`、`scripts/finalize_run_evidence.py` |
| 修订 Run 创建 | `fork_profile` 之外或其扩展后的明确入口，以及初始化和父子关系验证 |

兼容要求应保留历史 v1 Run 的可验证性：历史 `gate_5_review.json`、已写入的 manifest、Evidence 和完成转换必须仍可重放。新建审核账本不能反向重写已有运行样本。

## PR 2 前的确认项

1. 新审核记录的目录、命名、不可变 ID 和 current pointer 合同。
2. `needs_revision` 是否为 Gate 5 的正式事件，以及其与修订 Run 的父子关系和修订范围如何编码。
3. 完成临界区采用何种锁、故障恢复标记和事务顺序。
4. 如何让 v1 固定根文件与新审核记录共同被 manifest/Evidence 引用，同时保持历史 replay 兼容。

本报告未修改 Gate 5 Schema、脚本、状态机或任何运行产物。
