# MathModelAgent Source Asset 边界

## 固定来源

- 远端：`https://github.com/jihe520/MathModelAgent.git`
- 提交：`be9c59c1aaa13c3dcb74452ea5cae11dada27589`
- 本地目录：`.vendor/mathmodelagent/`（被 Git 忽略）
- 锁：`UPSTREAM.lock.json`
- 逐文件哈希：`upstream/mathmodelagent.sha256.json`

同步器只通过 Git 读取上述提交的固定 blob，并且只物化锁文件允许的路径。它不检出、注册或执行
`skills/1start-mathmodel`，也不运行任何上游 Skill、脚本、Hook 或总控提示词。

## 三层隔离

1. **Source Asset**：`.vendor/mathmodelagent/` 中的上游原文，只读、忽略、不可被 Runtime Pack 读取。
2. **Extracted Requirement**：带来源路径、提交、强度和映射合同的本仓结构化需求。
3. **Native Adapter**：只消费 Extracted Requirement，并映射到本仓现有 Gate、Collector、Validator、Formal Result 和 Paper 合同。

Source Asset 不能直接成为 Agent 注册项，不能生成结果、修改论文、判定 Gate PASS，不能驱动下一阶段。

## 允许路径

- `docs/md/License.md`
- `skills/3coding-visual/`
- `skills/4drawio/`
- `skills/5writing/`
- `skills/6verity/`
- `skills/_references/math_modeling_norms.md`

任何远端、提交、许可哈希、允许路径 Git 对象、清单哈希或逐文件哈希漂移都会使同步失败。

## 授权与分发

项目维护者已说明取得上游作者的直接使用与优化许可。本仓仍按上游公开许可文本保守处理：个人免费使用，
不得用于商业用途，不得闭源分发，不得在其基础上提供商业服务。该直接许可不被解释为可向第三方转授的
通用许可证；如需商业使用或更宽分发范围，应取得作者的单独书面许可。
