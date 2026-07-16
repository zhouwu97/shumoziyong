# MathModelAgent 需求提取说明

## 提取结果

固定提交 `be9c59c1aaa13c3dcb74452ea5cae11dada27589` 被提取为 4 个注册表、38 条需求和 13 个映射合同：

| 注册表 | 数量 | 主要本仓落点 |
| --- | ---: | --- |
| `production_requirements_v1` | 9 | 诊断、路线、执行记录、Formal Result |
| `paper_requirements_v1` | 9 | Paper Profile、模板、渲染、正文一致性 |
| `figure_requirements_v1` | 8 | Figure Spec、构建报告、视觉报告、结果来源 |
| `verity_requirements_v1` | 12 | 来源 Manifest、文本门禁、编译、PDF 视觉与 Gate 4 |

每条需求都记录上游相对路径、源文件 SHA-256、章节定位、固定提交、强度和映射 ID。逐文件哈希必须存在于
`upstream/mathmodelagent.sha256.json`，映射目标必须是本仓已存在合同。

## 提取原则

- 只提取可验证的能力要求，不复制上游阶段总控、工具权限或 Agent 编排。
- `blocking` 表示对应本仓 Gate 的独立 Validator 需要证据后裁决；Adapter 本身没有阻断或放行权。
- `advisory` 只形成建议，不得被升级为隐式门禁。
- 同一上游要求若已被本仓更强合同覆盖，只建立映射，不创建第二套真源。
- 上游默认值不自动覆盖 Runtime Profile 或当前 Run 的显式选择。

## Adapter 生命周期

`plugin_competition_production_v1` 当前为 `review_ready`，尚未编译进任何 Runtime Profile 或运行包。它只能生成
`competition_production_adapter_report_v1`，且生成结果、修改论文、判定 Gate、推进阶段四项权限固定为 `false`。
Profile 编译、Gate 路由和运行包导出留到 PR-4 单独验收。
