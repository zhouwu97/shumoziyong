# 作者侧阶段审核约定

前四份报告是作者团队的轻量状态记录，不是新的机器状态机，也不替代 Verification、Paper Admission 或独立 Reviewer。每个阶段有主责重点，但所有 R1--R4 都有全局否决权：发现其他阶段的致命问题必须提出，不能以“不归本阶段”为由放过。

## 顺序

```text
R1 MODEL_REVIEW
→ EXPERIMENT_REVIEW
→ PAPER_COHERENCE_REVIEW
→ R4 FORMAT_SUBMISSION_REVIEW
→ Paper Admission
→ R5 AI 自动新建独立 Reviewer 对话
```

## 状态

| 审核 | 主责 | 初始状态 | 完成状态 | 需要返工 |
|---|---|---|---|
| R1 `MODEL_REVIEW.md` | 题意、变量、假设、目标、约束、模型适配、基线、验证设计 | `DRAFT` | `READY` | `REVISE` 或 `BLOCKED` |
| R2 `EXPERIMENT_REVIEW.md` | 数据处理、泄漏、划分、复现、指标、约束、稳定性、失败样本 | `PENDING` | `PASS` | `REVISE` 或 `BLOCKED` |
| R3 `PAPER_COHERENCE_REVIEW.md` | 逐问作答、推导、证据、图表价值、解释、适用范围 | `PENDING` | `READY` | `REVISE` 或 `BLOCKED` |
| R4 `FORMAT_SUBMISSION_REVIEW.md` | PDF、字体、遮挡、公式渲染、匿名、引用、附录、AI 披露、提交包 | `PENDING` | `READY` | `REVISE` 或 `BLOCKED` |

R1 还要能否决数据不足、不可计算或论文无法解释等根本问题；R2 还要能否决模型错误、图表误导或结论无法成立；R3 还要能重新发现模型错误、指标错误或实验缺口；R4 还要能否决内容缺失、图文矛盾或公式语义错误。任一报告为 `REVISE/BLOCKED` 时先修复再继续。报告正文可自由写，但状态行必须保留在首行。

## 独立评审约定

Paper Admission 通过且 R1--R4 没有未处理的否决项后，由 AI 编排层自动新建一个独立 Reviewer 对话，并只交付隔离包。R5 不预设局部范围，自主全面检查模型、实验、论文、格式、提交包、创新性、可读性和 AI 披露。修补 MUST 后重新运行受影响的工程产物，再由 AI 编排层自动新建新的复审对话。不得在作者对话中自评，也不要求 Reviewer 计算或比较 PDF、学习上下文哈希。`contest` 薄 CLI 只负责生成交接包和状态，不直接调用对话 API。
