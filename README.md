# 数学建模 AI 协作、执行与验证系统

本仓库构建面向数学建模竞赛的 AI 协作系统：由人工确认题意与建模路线，
可替换执行器生成候选代码和结果，独立 Collector 重跑，Validator 复算，
再以 Claim–Result Map 约束论文结论。

它不是提示词合集，也不主张让 AI 一步生成完整论文。在完成独立旧题、留出题和
限时盲测前，项目只提供面向国奖目标的可信基础设施，不宣称已经达到国奖水平。

## 项目定位

- 用机器可读 Gate 合同约束诊断、执行、收集、验证和论文环节；
- 将执行器产生的 Candidate Result 与独立验证后的 Formal Result 分离；
- 将可复现证据、能力成熟度和论文主张绑定，而非由人工填写状态。

项目不替代人工的题意判断、路线选择和关键确认；也不把一次运行、一次求解器报告
或模型内部自检当作独立的数学验证。

## 核心流程

```text
题面与附件
→ Gate 合同
→ Executor Candidate
→ Collector Clean Rerun
→ Numeric / Mathematical Validator
→ Formal Result
→ Claim–Result Map
→ Paper & Independent Review
```

## 5 分钟快速开始

### 1. 安装并运行公开校验

```bash
git clone <本仓库地址>
cd <仓库目录>
python -m pip install -r requirements.lock
python scripts/validate_repository.py
```

校验应以 `0 项失败` 结束。若失败，先按 `[FAIL]` 修复路径、状态或 Schema；不要继续
导出运行包或把失败结果用作正式证据。

### 2. 导出一个新题 Runtime Pack

```bash
python scripts/export_runtime_pack.py --context new_problem --profile general
```

导出结果位于 `export/`：运行包提供给执行 AI，manifest 记录输入文件、Patch 选择和
SHA-256。导出后可运行 `python scripts/check_runtime_manifest.py` 检查 manifest。

### 3. 初始化一个 Run

```bash
python scripts/run_workflow.py init --workflow new_problem --problem 2026-A --materials competition/problem
```

这会冻结材料、Profile、Patch 与运行包。继续推进前必须由审核人按 Gate 要求确认；
完整命令与材料计划见[比赛执行指南](docs/guides/COMPETITION_GUIDE.md)。

## 三个入口

| 场景 | 入口 | 目标 |
|---|---|---|
| 学优秀论文 | [论文学习流](docs/workflows/01_论文学习流.md) | 生成学习卡片、知识卡片和 Patch 草案 |
| 测旧题 | [旧题闭环流](docs/workflows/02_旧题闭环流.md) | 完成诊断、评分、复盘与验证记录 |
| 做新题 | [新题执行流](docs/workflows/03_新题执行流.md) | 先完成总控诊断，再按人工确认推进 |

三个工作流的调度边界见[工作流总览](docs/workflows/00_工作流总览.md)。论文学习流不提升
正式 Patch 状态；轻量提示词回归不产生 Gate 或晋级证据；`full_replay` 与 `new_problem`
必须遵守完整 Gate 0—5 合同。

## 开始一次旧题训练

旧题训练使用 `full_replay`，必须先完成材料来源、历史陌生性和题解污染审计。已用于开发、
修复或论文学习的题目只能作为回归题，不计入资格证据。

```text
私有候选池 → 人工确认未见 → 只复制最终选中的官方材料 → 从最新 main 创建干净 worktree
→ 初始化 full_replay → Gate 0—2 人工确认 → 候选执行与独立重跑 → Gate 3—5
→ Validator 与论文验收 → 记录训练边界
```

```powershell
python scripts/run_workflow.py init `
  --workflow full_replay `
  --problem 2018-B `
  --profile engineering_optimization `
  --materials E:\AI\shumo_training_private\2018_B\official_materials
```

初始化后每次只推进一个 Gate：

```powershell
python scripts/run_workflow.py advance `
  --run-dir runs\<run_id> `
  --reviewer <审核人>
```

完成 Gate 5 后再执行：

```powershell
python scripts/run_workflow.py complete --run-dir runs\<run_id> --reviewer <审核人>
python scripts/run_workflow.py verify --run-dir runs\<run_id>
```

训练题默认标记为 `qualification_rehearsal`。除非满足正式留出、独立重跑、数学验证和独立
评审要求，否则不得修改 Profile maturity 或声明 `profile_qualified`。

## 当前稳定能力

Runtime Pack、Gate 0—5、材料冻结、运行身份、Candidate Result 与 Formal Result 隔离等
基础链路已具备相应合同。具体 Profile、Patch、资格和成熟度必须由状态派生脚本生成，
不在 README 手工维护。

机器生成的状态快照、来源与刷新规则见[当前状态](docs/status/CURRENT_STATUS.md)。
该状态页由状态事实源流程生成；本分支依赖其先合并。

## 仓库地图

```text
docs/                 架构、路线图、工作流、指南、状态和报告
scripts/              CLI、校验、导出与维护脚本
schemas/              机器可读合同 Schema
policies/             成熟度、Claim 与晋级政策
validators/           独立验证器
formal_result/        正式结果与执行信任模型
runtime_profiles/     Runtime 规则和机器状态
runtime_contracts/    Gate 与运行合同
prompt_base/          通用总控规则
prompt_plugins/       题型专项规则
prompt_patches/       经论文学习形成的候选补丁
papers/               学习卡片、知识卡片和模板
protocols/            冻结实验协议
tests/                单元、回归、集成和夹具
training/             已知旧题训练与资格预演资产
official_materials/   受控材料 manifest；原始附件不提交
runs/                 本地运行目录，不纳入版本控制
output/               生成报告与闭环摘要
```

完整的现状、资产边界和分阶段目标见[仓库目录说明](docs/architecture/REPOSITORY_LAYOUT.md)。

## 文档索引

- [系统架构](docs/architecture/SYSTEM_ARCHITECTURE.md)与[仓库目录说明](docs/architecture/REPOSITORY_LAYOUT.md)
- [实施路线图](docs/roadmap/ROADMAP.md)与[工作流](docs/workflows/00_工作流总览.md)
- [Runtime Pack 指南](docs/guides/RUNTIME_PACK_GUIDE.md)、[比赛执行指南](docs/guides/COMPETITION_GUIDE.md)和[Patch 实验指南](docs/guides/PATCH_EXPERIMENT_GUIDE.md)
- [机器合同](schemas/)、[运行政策](policies/)与[A092 状态](docs/status/A092_STATUS.md)
- [Competition Production 六题隐藏盲测资格](docs/architecture/COMPETITION_QUALIFICATION.md)
- [Competition Production 72 小时模拟赛](docs/architecture/COMPETITION_72H_SIMULATION.md)
- [当前开发安排](docs/status/CURRENT_DEVELOPMENT.md)和[历史/实现报告](docs/reports/)

## 可信边界

- Candidate Result 不等于 Formal Result；
- 求解器报告不等于独立验证；
- 模型内部检查不等于外部有效性；
- Profile 成熟度与 Patch 晋级资格必须由政策和证据现场派生；
- 缺少受控材料时，公开校验仍应检查合同、Schema 和可公开的夹具，而不能伪造结果。

## 开发与测试

所有 PR 应通过 Public CI、`git diff --check`、链接检查和与变更范围相称的回归测试。
冻结协议、已封存运行和正式证据不能原地改写；新证据应以新运行、sidecar 或明确的
失效记录表达。详细工作安排见[当前开发安排](docs/status/CURRENT_DEVELOPMENT.md)。

## 许可与归属

仓库尚未提供 `LICENSE` 文件；在明确许可前，请勿假定可将仓库内容用于再分发或商业用途。
外部材料、赛题和论文应保留其原有来源与使用限制；原始受控材料不应提交到本仓库。
