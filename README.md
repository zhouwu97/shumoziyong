# 数学建模 AI 协作、执行与验证系统

这个仓库用于构建面向数学建模竞赛的 AI 协作、执行与验证系统。它不是提示词合集，也不让 AI 一步写完整论文；优秀论文学习、提示词分层、旧题闭环和失败复盘仍是底座，但系统目标已扩展为可执行合同、独立重跑、数值验证、证据驱动论文和盲测资格验证。

总目标是：在未知赛题上，以人工关键决策为边界，完成题目诊断、模型设计、代码实验、结果验证、论文生成和独立评审，并以可复现的盲测证据评估其全国奖竞争力。未完成盲测与独立评审前，项目只宣称为“国奖级目标的基础设施”，不宣称已达到国奖水平。

系统愿景、分层架构、能力成熟度和分阶段实施计划分别见：

- [国奖竞争力目标](docs/vision/NATIONAL_AWARD_AI_GOAL.md)
- [系统架构](docs/architecture/SYSTEM_ARCHITECTURE.md)
- [实施路线图](docs/roadmap/ROADMAP.md)

核心目标：

```text
知识与规则
-> 机器可执行 Gate 合同
-> 可替换 Executor Adapter
-> 独立 Collector 与数值验证
-> 证据驱动论文与独立审稿
-> 盲测与资格评估
```

## 5 分钟快速开始

### 1. 安装与校验

```bash
git clone <本仓库地址>
cd <仓库目录>
python -m pip install -r requirements.lock
python scripts/validate_repository.py
```

校验结果应以 `0 项失败` 结束。若失败，先按 `[FAIL]` 修复路径、状态或 Schema，不要继续导出比赛包。

### 2. 导出比赛运行包

```bash
python scripts/export_runtime_pack.py --context new_problem --profile general
python scripts/check_runtime_manifest.py
```

命令会生成：

- `export/cumcm_runtime_pack.md`：提供给执行 AI 的规则包；
- `export/cumcm_runtime_pack.manifest.json`：记录版本、源文件、patch 选择和 SHA-256；
- 默认包不会包含 `review_ready` patch；正式包只包含 `regression_verified` 或 `competition_evidenced` patch。

### 3. 在 AI 中执行

把新赛题 PDF 和附件放到比赛工作目录的 `problem/`，把运行包复制到 `rules/runtime_pack.md`。本项目不绑定具体 AI 客户端；只要该工具能读取本地文件、按阶段暂停并在确认后继续即可。

第一轮发送：

```text
执行 docs/workflows/03_新题执行流.md，模式 standard。
题面位于 problem/，规则位于 rules/runtime_pack.md。
第一轮只输出总控诊断和人工确认项，不写代码、论文或最终答案。
```

成功标准：AI 输出题目理解、子问题拆解、数据需求、候选路线、图表计划和人工确认项，并停在 Gate 前。若 AI 越过 Gate，停止当前输出，重新附上禁止项；不要把越权生成的代码或结论计入正式结果。

### 4. 初始化工作流

比赛新题默认使用保守的 `general` Profile：

```bash
python scripts/run_workflow.py init --workflow new_problem --problem 2026-A --materials competition/problem
```

正式比赛建议先准备并人工确认材料计划，再创建 Run：

```bash
python scripts/prepare_competition.py plan --problem 2026-A --materials competition/problem --output competition/material_plan.json
# 人工逐项填写 material_plan.json 中的 confirmed_category 后执行：
python scripts/prepare_competition.py apply --plan competition/material_plan.json --materials competition/problem --profile general --mode standard --confirm-no-solution --reviewer <审核人>
```

若 Gate 0 确认需要专项 Profile，可从尚未推进的 general Run 创建可恢复子 Run：

```bash
python scripts/run_workflow.py fork-profile --from-run runs/<GENERAL_RUN_ID> --profile engineering_optimization --reviewer <审核人> --reason "Gate 0 确认该题为工程优化题"
```

旧题回归必须显式选择专项 Profile：

```bash
python scripts/run_workflow.py init --workflow full_replay --problem 2024-C --profile engineering_optimization --materials official_materials/2024_C
python scripts/run_workflow.py advance --run-dir runs/<run_id> --reviewer <审核人>
python scripts/run_workflow.py complete --run-dir runs/<run_id> --reviewer <审核人>
python scripts/run_workflow.py verify --run-dir runs/<run_id>
```

命令会在 `runs/` 下冻结材料、Profile、Patch 与 runtime pack，并按 Gate 0-5 校验业务产物。`complete` 同时封存证据，任何命令都不会自动修改 Patch 或 Profile 状态。

## 三个入口

以后只从这三个入口中选一个：

| 场景 | 入口 | 目标 |
|---|---|---|
| 学优秀论文 | `docs/workflows/01_论文学习流.md` | 生成学习卡片、知识卡片 JSON 和 patch 草案 |
| 测旧题 | `docs/workflows/02_旧题闭环流.md` | 完成旧题总控诊断、评分、复盘和日志建议 |
| 做新题 | `docs/workflows/03_新题执行流.md` | 比赛当天先总控诊断，再按人工确认推进 |

总览见：`docs/workflows/00_工作流总览.md`。

三条流程不能混用：

- 论文学习流不跑旧题、不改正式 base/plugin、不标记 `competition_evidenced`。
- `prompt_regression` 只测轻量提示词行为，不能生成 Gate 或晋级证据。
- `full_replay` 与 `new_problem` 都执行完整 Gate 0-5 产物契约。

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
    stable判定规则.md  # 文件名为兼容保留，内容使用 competition_evidenced 口径
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
| rules | `docs/workflows/rules/` | 旧题闭环的材料等级、风险标签、评分、晋级判定 |
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

本仓库负责规则、经验、闸门、执行合同、证据、独立验证和复盘。MathModelAgent 仅是首个可替换的 Executor Adapter：它可以在受批准的合同内生成代码、图表和论文，但不拥有 Gate 状态、正式结果或 Patch 晋级权。正式结果必须由独立 Collector 在干净工作目录重跑并通过专项验证后生成。

如需读取 Excel 附件或运行基础数模代码，先安装依赖：

```bash
python -m pip install --require-hashes -r requirements.lock
```

导出运行包：

```bash
python scripts/export_runtime_pack.py --context new_problem --profile general
```

默认导出：

```text
export/cumcm_runtime_pack.md
export/cumcm_runtime_pack.manifest.json
```

导出器读取 `prompt_patches/patch_index.json` 与 `runtime_profiles/<profile>.json`。正式运行包只导入同时满足三条件的 patch：

1. `patch_index` 中状态为 `regression_verified` 或 `competition_evidenced`；
2. patch 的 `runtime_profiles` 包含当前 profile。

`runtime_profiles/*.json` 只保存结构化证据引用；成熟度由验证器现场派生。

显式加入待审 patch 做旧题实验（可重复传入，每个必须状态为 `review_ready` 且支持当前 profile）：

```bash
python scripts/export_runtime_pack.py --context full_replay --profile engineering_optimization --candidate-patch B311
```

隔离实验（Baseline / A092 Treatment）：

```bash
# Baseline
python scripts/export_runtime_pack.py \
  --context full_replay \
  --profile engineering_optimization

# A092 Treatment
python scripts/export_runtime_pack.py \
  --context full_replay \
  --profile engineering_optimization \
  --candidate-patch A092
```

仅使用 `--exclude-patch A127` 不会自动加载状态为 `review_ready` 的 A092，因此不能视为 A092-only Treatment。

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
- 当前工程优化 runtime：版本 `0.2.0`，现场派生成熟度为 `assembled`。
- A092、A127、B311、B477 当前均为 `review_ready`；旧证据不参与主动晋级。
- A092 第一轮确认性实验已经完成，但没有形成满足 `regression_verified` 门槛的有效证据；A127、B311、B477 也未宣称 `regression_verified` 或 `competition_evidenced`。
- trusted-local 实际执行、运行证明、Collector 固定派生与 Formal Result
  验证链已经建立；满足完整范围要求的运行可以产生
  `formal_result_eligible=true`。
- 该资格必须同时绑定
  `formal_result_eligibility_scope=trusted_local`、
  `execution_trust_model=trusted_local`、干净 Git 状态和定向宿主读取控制结果。
- trusted-local 资格只证明可信本地代码确实运行，以及 raw output 到
  Formal Result 的派生关系一致；不自动证明数学模型正确、约束完整或结果全局最优。
- 后续修改按阶段保持独立提交，完成测试后可通过 SSH 直接推送；
  是否使用功能分支根据改动风险决定。

## 当前建模质量验证状态

A092 第一轮确认性实验已经完成。

结论：

- A092 保持 `review_ready`；
- 当前没有获得满足 `regression_verified` 门槛的有效证据；
- 正控和边界题均出现独立数学验证失败；
- 负控实验因执行并发覆盖和外部用量限制未形成有效配对；
- 本轮结果不证明 A092 无效，只说明当前证据不足以晋级。

详细报告：

- [数学建模质量计划阶段三最终报告](docs/reports/MODELING_QUALITY_PHASE3_FINAL_REPORT.md)

### 正式比赛说明

A092 当前仍为 `review_ready`，因此不会进入正式 `new_problem` Runtime Pack。正式包只自动加载状态为 `regression_verified` 或 `competition_evidenced` 且支持当前 Profile 的 Patch。

目标值、改进率和最优性结论只有在外部 Validator 通过后才能用于论文强结论。这里的独立复算必须由候选解生成过程之外的固定适配器执行；AI 再次调用生成阶段使用的同一函数，不构成独立复算。

## 当前开发重点

1. 修复运行超时后的完整进程树清理、唯一 `attempt_id` 目录和结果目录原子提升，禁止同一 Run 存在两个 active attempt。
2. 以题面原始公式、2–3 个手算小点和符号/方向故障注入复核 2023-B 数学适配器口径，确认后重新冻结。
3. 强化外部 Validator 对论文 Claim 的阻断：验证失败时不得使用目标值、改进率或最优性强结论。
4. 分层定位 2024-C 正控中 `objective_reported` 与 `objective_recomputed` 不一致的根因。
5. 完成 A092 修订、新 Pilot 和预注册后，再考虑冻结并执行 `a092_confirmatory_v2`。

## 使用原则

1. 先诊断，后建模。
2. 先评价函数，后优化算法。
3. 先简单方法，后高级模型。
4. 先结果解释，后论文写作。
5. 先失败复盘，后提示词修复。
6. 没有人工确认，不进入下一阶段。
7. 没有执行计划，不开始旧题闭环。
8. 没有完整可复核证据和人工确认，不进入 `competition_evidenced`。
