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

- `python -m pytest -q`：96 passed。
- `python scripts/validate_repository.py`：30 项通过，0 项失败。
- Stable E2E 使用完整 patch schema、真实 `build_manifest()` 输出和正式 Gate API 构造的转换日志；同时验证内部证据被篡改后人工批准摘要失效。
