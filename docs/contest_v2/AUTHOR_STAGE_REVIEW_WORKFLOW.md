# 作者侧阶段审核约定

三份报告是作者团队的轻量状态记录，不是新的机器状态机，也不替代 Verification、Paper Admission 或独立 Reviewer。

## 顺序

```text
MODEL_REVIEW
→ EXPERIMENT_REVIEW
→ PAPER_COHERENCE_REVIEW
→ Paper Admission
→ 手动新建独立 Reviewer 对话
```

## 状态

| 报告 | 初始状态 | 完成状态 | 需要返工 |
|---|---|---|---|
| `MODEL_REVIEW.md` | `DRAFT` | `READY` | `REVISE` 或 `BLOCKED` |
| `EXPERIMENT_REVIEW.md` | `PENDING` | `PASS` | `REVISE` 或 `BLOCKED` |
| `PAPER_COHERENCE_REVIEW.md` | `PENDING` | `READY` | `REVISE` 或 `BLOCKED` |

模型审核关注题意、变量、目标、约束和推导；实验审核关注基线、复算、稳定性、边界和预算；论文审核关注逐问回应、数字引用、图表解释、创新证据、可读性和 AI 痕迹风险。任一报告为 `REVISE/BLOCKED` 时先修复再继续。报告正文可自由写，但状态行必须保留在首行。

## 独立评审约定

Paper Admission 通过后，由作者或编排者手动新建一个独立 Reviewer 对话，并只交付隔离包。修补 MUST 后重新运行受影响的工程产物，再手动新建新的复审对话。不得在作者对话中自评，也不要求 Reviewer 计算或比较 PDF、学习上下文哈希。
