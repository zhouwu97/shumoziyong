# 当前开发安排

本页记录维护顺序和范围规则，不作为运行状态、Patch 晋级或实验结果的事实源。具体工作项
应以 GitHub Issue、Pull Request 或项目看板为准；完成情况必须由相应证据与 CI 记录支持。

## 当前顺序

1. **PR-DOC-0：README 与文档分流**
   - 将项目入口、详细命令、状态摘要和目录说明分离；
   - 不移动源码、训练目录或冻结协议。
2. **PR-HYGIENE-1：本地输出与 `.gitignore`**
   - 建立 `local/`、`scratch/`、`output/generated/`、`output/temporary/` 的隔离策略；
   - 先分类未跟踪文件，绝不以 `git clean` 代替审计。
3. **PR-TRAINING-2：单题训练目录试点**
   - 仅选择一个训练题；先生成 archive manifest，再决定保留、归档或迁移；
   - 不删除历史 attempt，不修改被正式引用的证据。
4. **PR-TESTS-3：测试目录分层**
   - 在基础能力 PR 稳定后再更新 imports、CI、文档和 CLI 测试。
5. **PR-ROOT-4：根目录收口**
   - 最后处理兼容入口、历史目录、`CONTRIBUTING.md` 与 `LICENSE` 决策。

## 每个阶段的共同门槛

- 不混入现有能力 PR 或无关本地工件；
- Public CI、`git diff --check`、链接检查和相称的回归测试通过；
- 冻结哈希不被原地修改，正式结果不丢失；
- 涉及迁移时，保留迁移前后 SHA-256 清单与引用关系；
- 无法证明安全性或来源时停止在当前 Gate，不用推测填补证据。

## 不在本阶段做的事

- 不批量移动 `scripts/`、`tests/` 或 `training/`；
- 不删除未跟踪训练图表、日志、原始材料或个人文档；
- 不修改 Runtime Profile 成熟度、Patch 状态、冻结协议或现有正式结果；
- 不用目录整理掩盖需要修复的结果漂移或 CI 问题。

目录边界见[仓库目录说明](../architecture/REPOSITORY_LAYOUT.md)。机器状态由独立的状态
事实源流程生成，不在本开发安排中手工维护。
