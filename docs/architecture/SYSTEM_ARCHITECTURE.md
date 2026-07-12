# 数学建模 AI 系统架构

## 七层职责

| 层 | 职责 | 不能做的事 |
|---|---|---|
| Knowledge | 管理 base、plugin、patch、原文证据与适用边界 | 以学习卡替代真实运行证据 |
| Diagnosis & Planning | Gate 0/1 诊断、依赖图、基线、路线淘汰条件与人工决策 | 跳过人工确认直接交付结论 |
| Execution | 根据已批准的 `execution_spec.json` 生成并运行候选代码 | 修改合同、宣布正式成功 |
| Collection | 在干净工作目录重跑、收集原始输出并重算哈希 | 复用候选缓存作为正式结果 |
| Verification | 复算指标、检查可行性/泄漏/残差/稳定性 | 仅相信执行器自报的检查列表 |
| Paper & Review | 用正式证据生成论文，并以隔离输入执行数学、复现、论文和竞赛审稿 | 编造证据或让执行 Agent 自评 |
| Benchmark & Qualification | 记录盲测、人工干预、时限、致命错误和独立评分，派生成熟度 | 用总分掩盖致命错误 |

## 核心边界

```text
Gate 0/1/2 合同
    -> Executor Adapter（candidate）
    -> Collector（clean rerun）
    -> Validator（formal result）
    -> Paper / Review
    -> Benchmark evidence
    -> capability maturity policy
```

`code_plan.json` 保留给人阅读和历史兼容；`execution_spec.json` 是机器执行合同。Gate Contract v2 以新增文件和 Schema 实现，不覆盖历史 v1 运行记录。现有 `diagnosis.schema.json` 已承担诊断 v2 的结构化输出；新增 `model_route_v2`、`execution_spec`、`executor_handoff` 和 `executor_blocker` 用于后续 Executor Core 集成。

第一版执行环境限定为 `trusted_local`，并不宣称提供安全沙箱。联网、跨运行目录读取、修改题目材料、修改已批准合同和自行推进 Gate 均不在执行器授权范围内。
