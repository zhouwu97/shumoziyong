# Gate A-C 首批执行清单证据

本表只证明 2023-B 求解前规格已经冻结，不证明 Solver 完成、Formal Result 成立、单题技术闭环或比赛资格。

| # | 状态 | 证据 |
|---:|---|---|
| 1 | 完成 | PR-0 等价修复由候选 Schema 拆分、`general` Fail-closed、Windows Job Object、AI ZIP 恢复校验、实例级 FormatChecker 和冻结哈希测试共同覆盖；全量测试通过 |
| 2 | 完成 | `policies/historical_case_registry.json` 将历史记录固定为 `integration_fixture` / `pipeline_smoke_test`，全部资格用途为 `false` |
| 3 | 完成 | `upstream/mathodology.lock.json` |
| 4 | 完成 | 来源锁固定 Commit 和四个 Blob SHA，仓库校验器检查漂移 |
| 5 | 完成 | `upstream/LICENSE.mathodology` |
| 6 | 完成 | `upstream/mathodology_requirement_mapping.md` |
| 7 | 完成 | `case_identity.yaml` |
| 8 | 完成 | `case_identity.yaml` 的 `prior_exposure`、`evidence_mode` 与 `qualification_usage` |
| 9 | 完成 | `manifest.yaml`、`hashes.sha256`；五个官方文件已现场复算匹配 |
| 10 | 完成 | `attachment_audit.json`：`Sheet1`、253x203 工作表、251x201 有效网格、无缺失值 |
| 11 | 完成 | `authority_order.md` |
| 12 | 完成 | `data_contract.yaml` |
| 13 | 完成 | `modeling/requirement_map.json` |
| 14 | 完成 | `validate_requirement_map` 检查 Source Anchor 唯一性和摘要 SHA-256 |
| 15 | 完成 | 19 个 Core Requirement 均有 required 且类型适当的验证绑定 |
| 16 | 完成 | `modeling/mechanism_scope_ledger.json` |
| 17 | 完成 | 10 个机制均登记 `coverage_scope`；局部近似和代理机制显式披露 |
| 18 | 完成 | `modeling/route_applicability.json`：Q1/Q2 不伪造三路线，Q3/Q4 要求结构竞争 |
| 19 | 完成 | `model_spec.md` 冻结 Q1/Q2 坐标、方向、宽度度量和重叠率口径 |
| 20 | 完成 | `modeling/reference_oracle_registry.json` 与 `experiments/2023b_validator_pilot_v2/pilot_result.json` |
| 21 | 完成 | `validators/problem_boundary_v2/validate.py` 闭式实现 + `scripts/run_2023b_validator_pilot.py` 三维射线-平面独立实现 |
| 22 | 完成 | `validator_contract.yaml#q3` |
| 23 | 完成 | `validator_test_cases/q3_invalid_cases.json`、`q3_illegal_overlap.json` |
| 24 | 完成 | `modeling/route_falsification_plan.json` |
| 25 | 完成 | `schemas/headline_claim_registry.schema.json` 与实例 |
| 26 | 完成 | `validation_numerics.yaml` |
| 27 | 完成 | `dependency_boundary_policy.yaml` |
| 28 | 完成 | `modeling/modeling_evidence_bundle.json`，绑定 13 个前置产物 |
| 29 | 完成 | `test_19_detects_bundle_drift_after_freeze` 与 `test_20_rejects_old_run_bound_to_new_bundle` |
| 30 | 完成 | `modeling/gate_a_c_report.json#/gates/A = true` |
| 31 | 完成 | `modeling/gate_a_c_report.json#/gates/B = true` |
| 32 | 完成 | `modeling/gate_a_c_report.json#/gates/C = true`，状态为 `gate_c_modeling_design_frozen` |

冻结结果：

```text
status = gate_c_modeling_design_frozen
formal_result_eligible = false
execution_environment = direct_local
sandboxie_enabled = false
```
