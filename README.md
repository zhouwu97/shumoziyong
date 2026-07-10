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

## 5 分钟快速开始

### 1. 安装与校验

```bash
git clone <本仓库地址>
cd <仓库目录>
python -m pip install -r requirements.txt
python scripts/validate_repository.py
```

校验结果应以 `0 项失败` 结束。若失败，先按 `[FAIL]` 修复路径、状态或 Schema，不要继续导出比赛包。

### 2. 导出比赛运行包

```bash
python scripts/export_runtime_pack.py --profile engineering_optimization
python scripts/check_runtime_manifest.py
```

命令会生成：

- `export/cumcm_runtime_pack.md`：提供给执行 AI 的规则包；
- `export/cumcm_runtime_pack.manifest.json`：记录版本、源文件、patch 选择和 SHA-256；
- 默认包不会包含 `candidate` patch。

### 3. 在 AI 中执行

把新赛题 PDF 和附件放到比赛工作目录的 `problem/`，把运行包复制到 `rules/runtime_pack.md`。本项目不绑定具体 AI 客户端；只要该工具能读取本地文件、按阶段暂停并在确认后继续即可。

第一轮发送：

```text
执行 docs/workflows/03_新题执行流.md，模式 standard。
题面位于 problem/，规则位于 rules/runtime_pack.md。
第一轮只输出总控诊断和人工确认项，不写代码、论文或最终答案。
```

成功标准：AI 输出题目理解、子问题拆解、数据需求、候选路线、图表计划和人工确认项，并停在 Gate 前。若 AI 越过 Gate，停止当前输出，重新附上禁止项；不要把越权生成的代码或结论计入正式结果。

### 4. 初始化旧题回归

```bash
python scripts/run_workflow.py --workflow old_problem --problem 2024-C --profile engineering_optimization --gates 0-2
```

命令会在 `runs/` 下创建本轮 manifest、材料审查、runtime pack、执行计划、评分、失败标签和 patch 建议文件；它不会自动把任何状态升级为 `stable`。完整执行产物可参考 `examples/2023B_gate2_5/` 到 `examples/2023B_gate5/`。

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
  patch_index.json 用于按题型、状态和 profile 自动筛选 patch。

runtime_profiles/
  Markdown 定义运行规则；同名 JSON 是状态唯一事实源。

schemas/
  patch、知识卡片、runtime、旧题测试和失败卡的 JSON Schema。

papers/
  优秀论文学习卡片和知识卡片 JSON。
  templates/ 存放学习卡片和知识卡片模板。

tests/old_problems/
  旧题测试记录。

tests/prompt_regression/
  小粒度提示词语义回归用例和 patch 负控矩阵。

runs/
  由旧题 CLI 创建的逐次运行目录。

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
export/cumcm_runtime_pack.manifest.json
```

导出器会读取 `prompt_patches/patch_index.json`，默认只导入状态为 `verified_candidate` 或 `stable` 的 patch。若要做旧题实验，可以显式加入候选 patch：

```bash
python scripts/export_runtime_pack.py --include-candidate-patches
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

状态唯一事实源是 `runtime_profiles/*.json`，README 只做展示。

- 已有工程优化 base/plugin/patch。
- 已有 A092、A127、B311、B477 学习卡片和知识卡片。
- 当前工程优化 runtime：版本 `0.2.0`，成熟度 `verified_candidate`，验证级别 `cross_mechanism`，未经过正式比赛验证。
- 依据：
  1. 2024-C 农作物种植策略完成 Gate 0-5 full smoke chain pass；
  2. 2023-B 多波束测线问题完成 Gate 0-5 full smoke chain pass；
  3. 2024-B 生产过程中的决策问题完成 Gate 0-2 third-mechanism generalization pass。
- 边界：该状态只说明工程优化 runtime 已具备初步跨题可用性，不代表正式提交质量、完整最优化算法能力或 `stable`。
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
