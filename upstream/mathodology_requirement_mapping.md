# Mathodology 方法论来源映射

本文件记录 `sweetcornna/mathodology` 固定提交
`987644876160d105f0fa768248f5d23764f288b2` 对本仓 Gate A-C 建模合同的影响。
本仓只进行规则提取和原生语义重实现，不打包、安装或执行上游 Agent、Workflow 或脚本。

| 本仓规则 ID | 上游来源文件 | 上游内容 | 本仓目标产物 | 提取方式 |
|---|---|---|---|---|
| MM-REQ-001 | `.claude/agents/mathodology-problem-analyst.md` | atomic requirement map | `modeling/requirement_map.json` | 语义重实现 |
| MM-MECH-001 | `.claude/agents/mathodology-problem-analyst.md` | named mechanism ledger | `modeling/mechanism_scope_ledger.json` | 扩展重实现 |
| MM-ROUTE-001 | `.claude/agents/mathodology-modeler.md` | candidate models and rejection reasons | `modeling/route_applicability.json`、`modeling/route_falsification_plan.json` | 适用性驱动重实现 |
| MM-ORACLE-001 | 本仓补强规则 | independent reference truth | `modeling/reference_oracle_registry.json` | 本仓原生补强 |
| MM-CONTRIB-001 | `.claude/agents/mathodology-modeler.md`、`.claude/agents/mathodology-critic.md` | originality and load-bearing contribution | `modeling/contribution_ledger.json` | 技术与新颖性拆分 |
| MM-ROBUST-001 | `.claude/agents/mathodology-critic.md` | headline robustness | `modeling/headline_claim_registry.json` | 类型化重实现 |

## 许可与执行边界

- 上游许可证按原文保存在 `upstream/LICENSE.mathodology`。
- 固定 Commit 与四个 Blob SHA 保存在 `upstream/mathodology.lock.json`。
- `shumoziyong` 是 Run、Gate、Evidence、Formal Result、Profile、Maturity 和 Qualification 的唯一控制面。
- 上游内容不得在正式 Run 中运行，不得授予状态，不得替代 Solver、Validator 或人工审核。
- 第一阶段不建立自动同步、动态导入或上游更新机器人。
