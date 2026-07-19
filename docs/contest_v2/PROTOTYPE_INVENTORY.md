# contest_v2 原型盘点

## `result_ledger.py`

| 字段 | 内容 |
|---|---|
| 当前职责 | 定义 `ResultEntry`、append-only `ResultLedger`、JSON Pointer 与源值回查 |
| 输入 | 手工构造的条目及其 `source_path/source_pointer` |
| 输出 | 带 `append_only: true` 的 `result_ledger.json` |
| 旧系统依赖 | 间接依赖迁移脚本提供的旧 Formal Result/报告路径 |
| 核心 API | `ResultEntry`、`ResultLedger.append/load/write/verify_sources`、`resolve_pointer` |
| 测试 | 原型目录无测试 |
| 可复用部分 | 数值比较、稳定 JSON 写入思路 |
| 冲突 | append-only、手工条目、Ledger 自身持有源指针，不是从当前 Result 全量派生 |
| 风险 | 旧条目滞留、键覆盖语义、无法自然派生 stale/verified |

## `typst_values.py`

| 字段 | 内容 |
|---|---|
| 当前职责 | 从 Ledger 确定性生成 Typst 映射 |
| 输入 | `result_ledger.json` |
| 输出 | `paper/generated/results.typ` |
| 旧系统依赖 | 无 |
| 核心 API | `_escape`、`_formatted`、`render_typst`、`generate` |
| 测试 | 原型目录无测试 |
| 可复用部分 | 转义、排序、确定性生成 |
| 冲突 | 条目模型仍是旧 append-only 结构；缺原始值/格式值/单位/验证状态四元绑定 |
| 风险 | Typst 名称冲突与非法数值未显式检查 |

## `question_slice.py`

| 字段 | 内容 |
|---|---|
| 当前职责 | 定义 `slice.json` 交接对象并检查声明文件存在 |
| 输入 | 每问 `slice.json` |
| 输出 | 同结构 JSON |
| 旧系统依赖 | 无直接依赖 |
| 核心 API | `QuestionSlice`、`load_question_slice`、`write_question_slice` |
| 测试 | 原型目录无测试 |
| 可复用部分 | 相对路径约束 |
| 冲突 | 缓存手工 `status` 与 `verification` 文字，和动态状态、派生验证冲突 |
| 风险 | 成为第二个事实源，允许人为推进状态 |

## `verify_package.py`

| 字段 | 内容 |
|---|---|
| 当前职责 | 检查 Slice/Ledger/Typst/PDF，并将整个运行目录打成单个 ZIP |
| 输入 | 迁移 Run、旧式 Slice 与 Ledger |
| 输出 | `verify_report.json`、`submission_bundle.zip` |
| 旧系统依赖 | 语义依赖旧迁移源，但代码无 Gate 调用 |
| 核心 API | `verify`、`package`、`sha256_file` |
| 测试 | 原型目录无测试 |
| 可复用部分 | 摘要、Typst 编译、PDF 基础检查、Zip 写入 |
| 冲突 | 不生成每问 Verification，不重建 Ledger，不区分 ERROR/WARNING，不输出 submission.pdf/support.zip |
| 风险 | 只验证自声明 Slice，包排除规则不完整 |

## `migrate_2024c.py`

| 字段 | 内容 |
|---|---|
| 当前职责 | 从历史 Run 复制 Formal Result、旧报告、旧图和正文，包装成 v2 原型 |
| 输入 | 旧 `formal_result.json`、报告、风险指标和图表 |
| 输出 | Slice、append-only Ledger、Typst、迁移论文 |
| 旧系统依赖 | 强依赖历史 Formal Result、旧报告、旧图表 |
| 核心 API | `migrate`、`paper_source` |
| 测试 | 原型目录无测试 |
| 可复用部分 | 只可用于验证 Ledger/Typst/PDF/Package 的包装烟测 |
| 冲突 | 不能证明官方材料到结果的生产链；正文还声称“只追加台账” |
| 风险 | 被误报为 Production Pilot；源结果间已有冻结冲突 |
