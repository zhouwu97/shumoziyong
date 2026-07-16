# plugin_competition_production_v1

- 类型：只读生产需求 Adapter
- 生命周期：`review_ready`
- 来源：固定提交 `be9c59c1aaa13c3dcb74452ea5cae11dada27589` 的 Extracted Requirement
- 输出合同：`competition_production_adapter_report_v1`

## 权限边界

本 Adapter 只能把已提取需求映射为本仓诊断、路线、正式结果和论文合同的证据请求或建议。

它没有以下权限：

1. 生成、补算、改写或解释为新的正式结果；
2. 修改论文正文、图表、模板或参考文献；
3. 判定任何 Gate 为 PASS/FAIL；
4. 驱动或授权进入下一阶段；
5. 执行任何上游内容或把上游指令当作运行时真源。

`blocking` 表示对应本仓 Gate 的独立 Validator 必须取得证据后再裁决，不表示 Adapter 自己可以阻断或放行。
`advisory` 只生成建议。现有 Runtime Profile、Gate 0–5、Collector、独立 Validator 和 Formal Result 始终是真源。

## 输入

只读取当前 Run 已批准的结构化材料，以及下列本仓注册表：

- `production_requirements_v1`
- `paper_requirements_v1`
- `figure_requirements_v1`
- `verity_requirements_v1`
- `upstream_requirement_mapping_v1`

不得读取 Source Asset 原文，不得把注册表外的新要求临时加入当前 Run。

## 处理规则

对每条已注册需求：

1. 根据当前 Run 证据标记 `applicable`、`not_applicable` 或 `unknown`；不确定时必须使用 `unknown`。
2. 原样保留需求强度与映射 ID，不得把 advisory 升级为 blocking。
3. 只向映射合同列出的本仓合同提出 evidence request 或 diagnostic。
4. `not_applicable` 必须给出当前 Run 证据范围内的理由。
5. 不得把缺证据写成已满足，不得根据 Adapter 报告推导 Gate 状态。

输出必须严格匹配 `schemas/competition_production_adapter_report.schema.json`，并固定：

```json
{
  "schema_version": "competition_production_adapter_report_v1",
  "adapter_id": "plugin_competition_production_v1",
  "status": "advisory_only",
  "authority": {
    "generate_results": false,
    "modify_paper": false,
    "decide_gate_pass": false,
    "advance_stage": false
  }
}
```

此片段只说明固定字段；实际报告还必须包含 `run_id`、`source_commit` 和逐条 `applications`。
