# Contest Production v2 工作树审计

审计时间：2026-07-19（Asia/Shanghai）

## Git 基线

- 当前分支：`pilot/2025c-nipt-paper-quality-v1`
- 当前 HEAD：`f7c8211bc0a7b2b2e6a45d546c56f8b5d5c421a2`
- 结论：工作树高度脏，不适合切换分支、合并或整体提交。本轮不执行 clean、reset、restore、stash、pull、rebase 或 merge。

## 已跟踪修改

`git diff --stat` 报告 20 个已跟踪文件，共 731 行新增、245 行删除。修改包括：

```text
.gitignore
README.md
capability_evidence/paper_compiler_v1_1_1/ai_pre_review_packages/admin_only/AI_PRE_REVIEW_SUMMARY.md
docs/entrypoints/AI_WORKSPACE_BOOTSTRAP.md
docs/guides/COMPETITION_GUIDE.md
docs/guides/WORKSPACE_AUTORUN_GUIDE.md
docs/roadmap/ROADMAP.md
docs/status/CURRENT_DEVELOPMENT.md
docs/workflows/00_工作流总览.md
docs/workflows/03_新题执行流.md
paper_templates/cumcm_typst/components.typ
protocols/a092_v2/2024c_validator_contract_freeze.json
scripts/run_a092_stage3.py
scripts/validate_a092_formal_run.py
tests/test_2024c_validator_v2.py
tests/test_execution_isolation.py
tests/test_validate_a092_formal_run.py
training/2021_C_round2_retry1/constraint_inventory.md
validators/problem_positive/validate.py
validators/problem_positive_v2/validate.py
```

这些文件在本轮开始前已修改，均视为用户工作，不覆盖、不回退。尤其冻结 `paper_templates/`、`validators/`、旧 Gate、Formal Result 与 capability evidence。

## 未跟踪内容

`git ls-files --others --exclude-standard` 报告 296 个文件。主要顶层集合为：

```text
CUMCM2025Problems/
capability_evidence/ 下的新证据与审查包
contest_v2/
docs/reports/、docs/workpackages/ 与新增路线文档
output/review_output.json
protocols/gate_4b_v0_1/
scripts/ 与 tests/ 下的 Gate 4B、能力台账、2016-C 运行文件
```

其中只有 `contest_v2/` 是本轮直接继承的原型。`CUMCM2025Problems/`、新增 capability evidence、Gate 4B、2016-C B2 运行和相关脚本测试明显与本轮无关，禁止覆盖。

## contest_v2 原型

```text
contest_v2/README.md
contest_v2/contest_v2/__init__.py
contest_v2/contest_v2/migrate_2024c.py
contest_v2/contest_v2/question_slice.py
contest_v2/contest_v2/result_ledger.py
contest_v2/contest_v2/typst_values.py
contest_v2/contest_v2/verify_package.py
contest_v2/runs/2024C-contest-v2-migration-20260719*/
```

两个迁移 Run 属于 packaging 原型产物，不作为 Production Pilot 结果源。

## 写入边界与 Git 建议

本轮只写入 `contest_v2/`、`docs/contest_v2/`、`docs/CONTEST_V2_ARCHITECTURE.md` 及隔离的 v2 运行产物。旧系统只读。当前不创建分支、不提交；完成后按文件归属拆分提交，避免混入审计前已有修改。
