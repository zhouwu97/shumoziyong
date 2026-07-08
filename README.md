# 数模 AI 专用训练与比赛工作流

这个仓库用于训练一套面向数学建模竞赛的 AI 协作系统。它不是提示词合集，也不是让 AI 一步写完整论文，而是通过优秀论文学习、提示词分层、旧题闭环测试和失败复盘，把 AI 训练成更稳定的数模队友。

核心目标：

```text
优秀论文学习
-> 沉淀 base / plugin / patch
-> 用旧题做总控诊断闭环
-> 按评分和失败标签复盘
-> 局部修复提示词
-> 比赛时按闸门执行
```

## 三个入口

以后只从这三个入口中选一个：

| 场景 | 入口 | 目标 |
|---|---|---|
| 学优秀论文 | `docs/workflows/01_论文学习流.md` | 生成学习卡片、知识卡片 JSON 和 patch 草案 |
| 测旧题 | `docs/workflows/02_旧题闭环流.md` | 完成旧题总控诊断、评分、复盘和日志建议 |
| 做新题 | `docs/workflows/03_新题执行流.md` | 比赛当天先总控诊断，再按人工确认推进 |

总览见：`docs/workflows/00_工作流总览.md`。

三条流程不能混用：

- 论文学习流不跑旧题、不改正式 base/plugin、不标记 stable。
- 旧题闭环流不写代码、不写论文、不求最终答案。
- 新题执行流不使用 T0-T4、M1-M5 或 stable 判定。

## 目录结构

```text
docs/workflows/
  00_工作流总览.md
  01_论文学习流.md
  02_旧题闭环流.md
  03_新题执行流.md
  rules/
    材料等级_T0-T4.md
    材料风险_M1-M5.md
    失败标签_P1-P10.md
    总控诊断评分表.md
    stable判定规则.md
  archive/
    旧版长提示词和历史启动模板存档

prompt_base/
  通用总控诊断规则。

prompt_plugins/
  题型专项规则，例如工程优化、预测、评价、仿真。

prompt_patches/
  单篇优秀论文经验补丁。

papers/
  优秀论文学习卡片和知识卡片 JSON。

tests/old_problems/
  旧题测试记录。

reviews/failure_cards/
  失败复盘卡。

output/closed_loop/
  候选题排序、闭环摘要、重测任务、修复草案。

official_materials/
  官方旧题材料 manifest；原始附件不提交。

training_log.md
  训练和测试事实记录。
```

## 提示词分层

| 层级 | 位置 | 只负责 |
|---|---|---|
| base | `prompt_base/prompt_base_v1.0.md` | 通用读题、拆题、题型判断、输入输出链、数据需求、候选模型、人工确认 |
| plugin | `prompt_plugins/` | 某类题的专项规则，例如优化题的目标、变量、约束、算法质疑、敏感性分析 |
| patch | `prompt_patches/` | 某篇论文的可迁移经验、适用条件和误用风险 |
| rules | `docs/workflows/rules/` | 旧题闭环的材料等级、风险标签、评分、stable 判定 |
| workflow | `docs/workflows/` | 本次任务按什么步骤跑、读哪些文件、产出哪些文件 |

## 常用执行方式

### 学论文

```text
执行 docs/workflows/01_论文学习流.md

材料：
- papers/raw/xxx.pdf 或我上传的优秀论文

目标：
生成学习卡片、知识卡片 JSON、patch 草案。
不要修改正式 base/plugin。
```

### 测旧题

```text
执行 docs/workflows/02_旧题闭环流.md

目标：
自动完成一轮旧题总控诊断闭环测试。

要求：
第一步先生成本轮执行计划。
如果我没有指定旧题，自动扫描候选题。
优先使用 T3/T4 官方材料。
本轮不写代码、不写论文。
```

### 做新题

```text
执行 docs/workflows/03_新题执行流.md

材料：
- 当前赛题
- 附件数据

本轮只做总控诊断。
不写代码，不写论文，不给最终答案。
```

## 与 MathModelAgent 结合

本仓库负责规则、经验、闸门和复盘；MathModelAgent 负责比赛目录内的代码、图表、论文和验收。

如需读取 Excel 附件或运行基础数模代码，先安装依赖：

```bash
pip install -r requirements.txt
```

导出运行包：

```bash
python scripts/export_runtime_pack.py
```

默认导出：

```text
export/cumcm_runtime_pack.md
```

比赛目录建议：

```text
比赛工作目录/
  problem/
  rules/
    runtime_pack.md
  reports/
  code/
  results/
  figures/
  paper/
```

第一轮只让执行代理读取题面和 `rules/runtime_pack.md`，输出总控诊断和需要人工确认的路线。

## 当前状态

- 已有工程优化 base/plugin/patch。
- 已有 A092、A127 学习卡片和知识卡片。
- 当前工程优化 runtime 状态：stable candidate，未 stable。
- 依据：
  1. 2024-C 农作物种植策略完成 Gate 0-5 full smoke chain pass；
  2. 2023-B 多波束测线问题完成 Gate 0-5 full smoke chain pass；
  3. 2024-B 生产过程中的决策问题完成 Gate 0-2 third-mechanism generalization pass。
- 边界：该状态只说明工程优化 runtime 已具备初步跨题可用性，不代表正式提交质量、完整最优化算法能力或最终 stable。
- 建议比赛时默认使用本状态对应的 `export/cumcm_runtime_pack.md`；后续大改应另开分支，不直接在当前验证结构上重写。

## 使用原则

1. 先诊断，后建模。
2. 先评价函数，后优化算法。
3. 先简单方法，后高级模型。
4. 先结果解释，后论文写作。
5. 先失败复盘，后提示词修复。
6. 没有人工确认，不进入下一阶段。
7. 没有执行计划，不开始旧题闭环。
8. 没有人工确认，不正式标记 stable。
