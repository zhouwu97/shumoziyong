# Paper Admission Report

## 状态

```text
ENGINEERING_VERIFICATION: PASS | FAIL
PAPER_TYPE: technical_report | submission_candidate
PAPER_ADMISSION: PASS | FAIL | PENDING
EXTERNAL_REVIEW: PENDING
SUBMISSION_STATUS: NOT_READY
PDF_SHA256: sha256:<当前 paper/submission.pdf 摘要>
LEARNING_CONTEXT: reports/learning_context.json
LEARNING_CONTEXT_SHA256: sha256:<当前学习上下文摘要>
```

工程验收未 PASS 时，Paper Admission 保持 PENDING。作者任务不得在本报告中声明 `SUBMISSION_STATUS: READY`。

机器文件必须使用 `docs/contest_v2/PAPER_ADMISSION_TEMPLATE.json` 的完整结构。顶层 `pass` 不能代替逐问矩阵；任一固定键缺失、`PARTIAL/MISSING`、空 evidence、无理由的 `NOT_APPLICABLE`、非空 `direct_blockers`、学习上下文不完整或摘要 stale 都会被交接构建器拒绝。

## 每问矩阵

对每个必答问题复制下表。每项填写 `PASS / PARTIAL / MISSING / NOT_APPLICABLE`；`NOT_APPLICABLE` 必须给题型理由。

### <QID>

| 检查项 | 状态 | 页码/公式/图表/Ledger 键 | 判定说明 |
|---|---|---|---|
| 题目具体要求 |  |  |  |
| 明确的最终回答或决策 |  |  |  |
| 变量和参数定义 |  |  |  |
| 问题专属数学表达 |  |  |  |
| 求解算法或推导过程 |  |  |  |
| 核心数值结果 |  |  |  |
| 基线或对照 |  |  |  |
| 有效性/误差/约束检查 |  |  |  |
| 图表或表格证据 |  |  |  |
| 结果解释 |  |  |  |
| 适用边界和局限 |  |  |  |

## 直接不准入项

- [ ] 漏答必答问题；
- [ ] 核心模型不能脱离代码独立审阅；
- [ ] 只有结果图，没有模型、求解或解释；
- [ ] 搜索质量不足却作“没有更优方案”等强结论；
- [ ] 同一方案反复评价但没有新的决策价值；
- [ ] 内部流程语言替代建模表达；
- [ ] 大量图表只是验证痕迹或退化对照；
- [ ] 数据泄漏、无效验证、虚构引用或无来源关键数字；
- [ ] 误差、样本、gap 或边界足以推翻核心结论。

## 判定规则

- 全部必需项 PASS、条件项处理合理且无直接不准入项：`submission_candidate / PASS`。
- 其他情况：`technical_report / FAIL`，返回作者侧大修。
- PDF 摘要改变：本报告自动过期，`PAPER_ADMISSION=PENDING`。
- 页数不作为硬门槛。
