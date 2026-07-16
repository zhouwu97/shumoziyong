# MathModelAgent 论文能力审计

## 审计边界

- 参考仓库：<https://github.com/jihe520/MathModelAgent>
- 审计提交：`be9c59c1aaa13c3dcb74452ea5cae11dada27589`
- 审计日期：2026-07-14
- 研究范围：`skills/5writing/`、`skills/6verity/`、`skills/3coding-visual/`、`skills/4drawio/`、`skills/_references/math_modeling_norms.md`
- 停止条件：完成本表所列能力判断后，不再扩展到总控、Agent 编排、WebUI、RAG、检索或多模型路由。

审计提交的许可文本位于 `docs/md/License.md`，并非仓库根目录。项目维护者已确认取得上游作者的直接使用与优化许可；本仓仍按该公开文本保守处理个人免费、不得商业使用、不得闭源分发、不得提供商业服务的边界。上游原文只通过固定提交与逐文件哈希校验后进入被忽略的本地 Source Asset，不直接进入 Runtime Pack。

## 能力取舍

| 能力 | 是否接入 | 接入方式 | 不直接复制原因 |
| --- | --- | --- | --- |
| CUMCM Typst 模板 | 是 | 独立实现一个最小模板 | 避免复制完整模板族与比赛专属封面 |
| 黑白学术样式 | 是 | JSON Profile 与独立 `style.typ` | 固定本项目需要的最小样式面 |
| 三线表 | 是 | 独立 `three-line-table` 组件 | 组件小、规则稳定，适合单独验证 |
| 图表规划 | 是 | JSON Handoff 合同 | 把图与真实结果、论证目的和 Claim 绑定 |
| 数字与结论绑定 | 是 | 只读 Python 检查器 | 防止写作阶段数字、单位和方向漂移 |
| 论文文本门禁 | 是 | 只读 Python 检查器 | 发现占位符、内部路径和结构问题 |
| PDF 逐页验收 | 是 | 页面导出器、元数据检查器和人工清单 | 程序检查不能替代视觉判断 |
| Humanizer | 只做合同 | 锁定数字、公式、单位和引用 | 自由改写 Agent 容易造成事实漂移 |
| 科研炫图模板 | 否 | 不接入 | 容易偏离竞赛论文的清晰表达 |
| 多比赛模板与 LaTeX 双引擎 | 否 | 不接入 | 本轮只证明单一 CUMCM Typst 路径 |
| Agent Harness、RAG、Web Search | 否 | 不接入 | 超出论文最小能力范围 |

## 参考到的公开设计思想

1. 论文数值应追溯到结果记录，写作阶段不得重新估算或改变舍入方式。
2. 数据图与概念图必须区分；每张图都应有来源、目的、目标章节和正文解释。
3. 论文验收先识别实际入口和文件布局，不把训练目录或固定文件名写死。
4. 文本扫描、编译检查和 PDF 逐页视觉检查是三个不同层次，不能互相替代。
5. 验收阶段只报告或小范围修复表达问题，不重新设计模型或发明结果。

## 受控吸收说明

现有 Typst 结构、样式参数、Python API、JSON 输出格式和测试仍是本仓 Native 实现。后续允许从固定 Source Asset 提取可审计需求，并在模板生产阶段按来源哈希选择上游模板；Source Asset、Extracted Requirement 与 Native Adapter 三层必须保持隔离。
