# 论文写作编译器 v1.1.1 探索性评审冻结报告

## 当前定性

论文写作编译器已完成第一阶段自动化试点。自动安全链在单题、单问、两个章节和当前十类故障范围内通过；写作增益与人工原文复核尚无外部证据。

```text
automated_status: passed
automated_scope: paper_compiler_v1_1_1_pilot
qualification_status: awaiting_external_human_review
production_allowed: false
```

## 仓库边界

- 论文专项测试使用 `python -m pytest -q tests/paper`。
- 仓库 Validator 的两项 Markdown 链接失败已绑定基础提交 `2c132858c2f271374fcfa80904251a4cc40f5da5`，保持失败状态。
- 全工作区测试被未跟踪参考工程的 `pypandoc` 与 `e2b_code_interpreter` 阻塞，不归类为论文编译器缺陷。
- 裸 `pytest.exe` 指向 Python 3.11，资格证据不使用该入口。

## 冻结边界

- 评审尚未开始，`review_started_at` 为 `null`。
- 工作树尚未提交，因此 `pilot_commit_sha` 为 `null`；源码以快照 SHA-256 绑定。
- A/B/C、卡片包、协议、评分表、判定策略、自动重合报告和三套评委材料均已哈希冻结。
- 两名主评委使用不同展示排列，私有映射不得交给评委。
- 自动原文检查只提供筛查证据；`human_overlap_review.json` 必须由真人完成。

## 下一步

1. 分别向两名评委提供其 `reviewer_packages/<reviewer_id>/` 目录与对应评审 JSON。
2. 两人独立完成、计时并签署，完成前不得讨论或解盲。
3. 由独立人员完成 `human_overlap_review.json`。
4. 运行 `validate_exploratory_review.py`；存在实质分歧时再启用仲裁包。
5. 只输出 `continue`、`revise` 或 `stop`，不进入 Production。
