# Gate 5 完整性修复报告

## 结论

本次修复完成了稳定晋级证据与 Gate 5 状态机、运行生命周期和证据封存之间的闭环绑定。运行只有在完整通过 Gate 0-5 后才能封存；Stable 验证会重放转换日志并校验证据内容哈希。

## 实施内容

- 新运行使用 `run_status` 记录工作流状态，使用 `integrity_status` 记录封存状态。封存操作仅将 `integrity_status` 从 `unsealed` 改为 `sealed`，不再覆写运行完成状态。
- `finalize_run_evidence.py` 仅接受 `run_status=completed`、`integrity_status=unsealed` 且严格回放为 Gate 0-5 完整完成的运行。
- Gate 5 审核改为实际执行 `gate_5_review.schema.json` 校验；`target_gate` 是必填字段，缺失时不再按默认值放行。
- Evidence Manifest v2 纳入 `gate_5_review.json`、`score.json` 和 `failure_labels.json`，并将这些文件加入晋级策略的必需证据角色。
- Stable 运行验证会重放 `transitions.jsonl`，拒绝未完成、非 Gate 5 完成、伪造或后追加的状态记录。
- Stable 人工批准摘要现在包含现场重算的内部证据 SHA-256：负控运行 evidence manifest、comparison review、失败修复记录、重测 evidence manifest、比赛 runtime manifest 与结果记录。
- Runtime Pack Manifest schema 现完整描述 `export_runtime_pack.build_manifest()` 的实际输出，不再以精简 schema 拒绝导出器产物。

## 兼容性

历史 v1 证据仍只允许 policy allowlist 中指定的只读 grandfathered 记录使用。它不是通用的 Evidence Manifest v1 兼容模式；新的晋级运行必须满足 v2 清单、生命周期拆分和 Gate 0-5 完整回放要求。

## 验证

- 首轮 `python -m pytest -q`：96 passed。
- `python scripts/validate_repository.py`：30 项通过，0 项失败。
- Stable E2E 使用完整 patch schema、真实 `build_manifest()` 输出和正式 Gate API 构造的转换日志；同时验证内部证据被篡改后人工批准摘要失效。

## 后续复核修复

- 修正 `failure_labels.json` 材料风险的交集逻辑。`M1`、`M2`、`M3`、`M5` 现在分别与 policy 的禁止材料风险集合比对，任一命中都会阻断晋级。
- `replay_transition_log()` 在读取 completed 事件时重新调用 Gate 5 审核验证，检查 Schema、审核决定、最终验收、审核人一致性和 SHA-256；不再仅相信手工写入的哈希。
- 回放拒绝 `material_ready != true` 的日志中出现任何 Gate 转换，防止直接修改 JSONL 绕过 `record_transition()`。
- Stable Evidence 摘要不再使用硬编码 policy version。调用方必须显式传入当前 policy version，人工批准记录的版本也必须与当前 policy 完全一致。
- Runtime Profile 的 `stable` 状态要求 `competition_verified=true`、`validation_level=competition_verified`，且只能导入状态同为 `stable` 的 patch；后者仍会由晋级验证器检查其 Stable Evidence。

本轮回归结果：`python -m pytest -q` 为 106 passed；`python scripts/validate_repository.py` 为 30 项通过、0 项失败。

## Profile Stable 证据级门禁

- promotion policy 已升级至 `1.4.0`，定义 Stable Profile 的最小 Gate 0-5 次数、比赛验证记录数量、非空证据、非空 stable patch 和无未关闭失败要求；负控次数复用 Patch Stable 的 policy 要求。
- `competition_verified=true` 现在必须附带可解析的 `competition_validation_records`。验证器现场检查 runtime manifest / result record 的 Schema、SHA-256、通过结果、profile 与 runtime version、结果记录绑定关系，以及 Stable Profile 中所有 patch 是否出现在比赛运行包中。
- 因此空的 `verified_patches`、`validation.evidence`、比赛记录、Gate 0-5 计数、负控计数，或未关闭 `known_failures` 都无法再使 Profile 进入 `stable`。
