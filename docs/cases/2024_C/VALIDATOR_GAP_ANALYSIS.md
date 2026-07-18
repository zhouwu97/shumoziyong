# 2024-C Validator 覆盖差距

## 现有实现

| 组件 | 当前覆盖 | 限制 |
| --- | --- | --- |
| `validators/problem_positive_v2/validate.py` | 附件加载、合并单元格恢复、部分目标函数和约束 | 不是完整 2024-C Q1–Q3 结果 Validator |
| `scripts/validate_2024c_dryland.py` | Q1 旱地单季基线的容量、域、利润独立复算 | 仅覆盖作物 1–15、露天地块和单季；不覆盖模板全量、跨年、豆类窗口或 Q2/Q3 |
| `tests/test_2024c_validator_v2.py` | 真实官方附件的加载和若干目标/轮作回归 | 未证明完整输出工作簿可验收 |
| `tests/official_integration.py` | 受控环境下检查附件存在与 SHA | 不重算模型结果 |
| `validators/competition_full_replay/problem_2024_c.py` | fail-closed scaffold | 当前拒绝正式全题验收，不能声称 Validator 已完成 |
| `runtime_contracts/2024c_q1_dryland_extraction.json` | Q1 旱地字段提取合同 | 不是全题数据合同 |

## 必须补齐的 Validator 能力

### Q1

- 两种超产销售口径的逐作物—季次销售上限和目标复算；
- 2024–2030 七年、第一季/第二季全量工作簿读取；
- 地块容量、适宜性、单季/双季、连续重茬和三年豆类窗口；
- 输出模板版式、作物列、地块行和所有数值单元格检查。

### Q2

- 对销量、亩产、成本、价格情景的随机种子和样本清单；
- 风险目标、约束和情景聚合方式的独立复算；
- 结果工作簿与情景 Formal Result 的一一绑定。

### Q3

- 替代/互补关系和参数相关矩阵的来源、范围、随机种子；
- 与 Q2 的同口径对比、敏感性和稳定性报告；
- 禁止把手写相关系数或模拟摘要当成 Formal Result。

## 进入 Solver 前的缺口

当前没有完整的 `problem_id=2024-C` 独立 Validator，不能生成正式 Candidate 或资格证据。A0 退出条件只要求材料和接口冻结；补齐上述 Validator 后才能进入 Q1 Solver，随后才可形成 Q1–Q3 Formal Result。

```yaml
validator_full_replay: not_ready
validator_independent: partial
solver_started: false
proxy_data_used: false
qualification_claimed: false
```

