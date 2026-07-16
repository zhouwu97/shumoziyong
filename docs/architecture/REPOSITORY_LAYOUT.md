# 仓库目录说明

本文说明当前仓库的稳定入口、资产边界和已批准的分阶段整理方向。它不是一次性迁移
说明：任何涉及训练资产、冻结协议或正式证据的移动，都必须先证明引用关系和文件哈希
不受影响。

## 当前稳定入口

| 目录 | 职责 | 版本控制边界 |
|---|---|---|
| `docs/` | 架构、路线图、工作流、指南、状态和报告 | 提交长期项目文档 |
| `scripts/` | CLI、导出、校验和维护脚本 | 提交；移动前更新调用方和 CI |
| `schemas/`、`policies/` | 合同与晋级/成熟度政策 | 提交；变更须有兼容性验证 |
| `validators/`、`formal_result/` | 独立验证与正式结果链路 | 提交；不能由执行器替代 |
| `runtime_profiles/`、`runtime_contracts/` | Runtime 状态、Gate 与执行合同 | 提交；状态必须可派生 |
| `prompt_base/`、`prompt_plugins/`、`prompt_patches/` | 通用规则、专项规则与候选补丁 | 提交；Patch 按政策晋级 |
| `papers/` | 学习卡片、知识卡片和模板 | 提交结构化知识，不提交受限原文 |
| `protocols/` | 冻结实验协议 | 视为证据；不原地修改冻结内容 |
| `tests/` | 单元、回归、公开/受控集成和夹具 | 提交；受控材料以 manifest/夹具替代 |
| `training/` | 已知旧题训练与资格预演资产 | 先清点引用与哈希，再做单题试点 |
| `official_materials/` | 受控材料 manifest | 原始附件按 `.gitignore` 排除 |
| `runs/` | 每次工作流运行目录 | 本地生成，不纳入版本控制 |
| `output/` | 可审阅闭环摘要与生成输出 | 仅稳定摘要可提交；生成物后续隔离 |

`checklists/`、`paper_checklists/`、`paper_examples/`、`paper_profiles/`、
`paper_templates/`、`reviews/` 与 `experiments/` 是现有兼容入口或专项资产。本轮不会移动
它们；引用关系确认后再按独立 PR 规划归位。

## 资产边界

```text
长期源码
≠ 运行输出
≠ 正式证据
≠ 历史 attempt
≠ 本地个人文件
≠ 受控材料
```

- 源码、Schema、政策和长期说明使用正常版本控制；
- 正式证据必须具有可复核来源、引用关系和哈希，不能被普通日志替代；
- 历史 attempt、stdout/stderr、临时渲染物和本地工具下载不应污染长期源码；
- 原始赛题附件与受限论文保留在受控或本地位置，仓库仅提交 manifest、摘要或可公开夹具；
- 个人讨论稿、截图和命令输出后续统一进入被忽略的 `local/`，不应成为项目事实源。

## 分阶段目标结构

下列结构是目标，不表示当前文件已迁移：

```text
docs/
  architecture/ roadmap/ workflows/ contracts/ guides/ checklists/
  status/ reports/ archive/
scripts/
  cli/ validation/ paper/ maintenance/ compatibility/
papers/
  cards/ knowledge/ templates/ raw/             # raw 本地忽略
protocols/
  active/ invalidated/ archive/
tests/
  unit/ regression/ integration_public/ integration_controlled/
  modeling_microbenchmarks/ fixtures/
training/
  cases/<case_id>/{config,code,paper,formal,evidence,reports,archive}/
output/
  published/ generated/ temporary/
local/                                         # 本地忽略
```

## 迁移规则

1. 先审计，后移动；不执行批量重命名或破坏性清理。
2. 冻结协议、密封运行、manifest 引用的工件和 Formal Result 不得直接移动或改写。
3. 训练目录一次只治理一个题目；先生成包含原路径、SHA-256、引用状态、迁移目标和保留理由的 manifest。
4. 脚本、测试或合同目录移动前，必须更新 imports、CLI、CI、文档、冻结 manifest 和回归测试。
5. 任一迁移 PR 必须通过 Public CI、`git diff --check`、链接检查，并证明迁移前后哈希一致。

## 根目录规则

根目录长期只保留项目入口与必要元数据，例如 `README.md`、`LICENSE`、
`CONTRIBUTING.md`、依赖清单和稳定一级目录。当前仍存在的兼容文件不在本轮删除或移动；
其去向将在根目录收口阶段单独决定。

## 后续顺序

1. PR-DOC-0：README 与文档分流；
2. PR-HYGIENE-1：本地输出、忽略规则和清理检查；
3. PR-TRAINING-2：以一个训练题为试点建立归档 manifest；
4. PR-TESTS-3：在基础能力稳定后分层测试目录；
5. PR-ROOT-4：最后处理根目录兼容入口与历史目录。

详见[当前开发安排](../status/CURRENT_DEVELOPMENT.md)。
