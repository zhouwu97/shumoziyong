# contest_v2 原型裁决

| 原型 | 主裁决 | 落地方式 |
|---|---|---|
| `result_ledger.py` | `REWRITE_IN_PLACE` | 删除 append-only 与手工追加语义；唯一入口从全部 `result.json` 和当前有效 Verification 完整重建 |
| `typst_values.py` | `KEEP` | 保留转义、排序和确定性生成，适配新 Ledger 并增加名称冲突检查 |
| `question_slice.py` | `EXPERIMENTAL_REFERENCE` | 不再作为生产 CLI 事实源；兼容旧 packaging smoke，生产状态只读 `question.json` 和客观文件 |
| `verify_package.py` | `REWRITE_IN_PLACE` | 收敛为 Verification 与 Package 内部实现；公开入口统一为薄 CLI |
| `migrate_2024c.py` | `SMOKE_TEST_ONLY` | 明确 `packaging_smoke_only`，禁止输出生产试点结论，产物只验证包装链 |

每项职责只保留一个权威实现：Result 解析与 Ledger 位于 `result_ledger.py`；Verification 位于 `verification.py`；Typst 位于 `typst_values.py`；Status 位于 `status.py`；Package 位于 `verify_package.py`；公开命令位于 `cli.py`。
