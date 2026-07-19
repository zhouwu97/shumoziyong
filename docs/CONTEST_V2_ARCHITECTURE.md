# Contest Production v2 架构事实源

本文是 Contest Production v2 当前唯一长期架构事实源。此前路线图、一次性执行书和原型 README 仅作为历史设计与执行材料；发生冲突时以本文和可复现测试为准。

## 1. 目标与非目标

v2 服务于比赛期间的模型、代码、结果、图表、论文和提交包生产。核心闭环是：

```text
官方材料 → 题意与模型 → 求解代码 → Result → Verification
         → Ledger → 图表/表格 → results.typ → 正文 → PDF → 提交包
```

旧系统只读冻结，保留已存在的关键验证器、复算器和最终封存能力。v2 不推进旧 Gate，不写资格或成熟度状态，不生成 capability evidence，也不把 v2 PASS 解释为资格认证、生产成熟度或竞赛奖项水平。

v2 不负责 Agent 调度、LLM 调用、模型路线自动选择、资格判断或自动修改论文结论。

## 2. 每问纵向闭环

每个必答问题独立形成：

```text
模型 → 代码 → 结果 → 图表/表格 → 正文 → 最小检查
```

标准路径为：

```text
questions/<qid>/question.json
questions/<qid>/model.md
questions/<qid>/run.py
questions/<qid>/results/result.json
questions/<qid>/results/verification.json
questions/<qid>/results/tables/
questions/<qid>/figures/
questions/<qid>/paper.typ
questions/<qid>/check.md
```

`contest.json` 只声明 `question_ids`；`question.json` 是题号、标题、是否必答及本问 required/recommended checks 的唯一完整配置源。它不存储可手工推进的进度状态。

## 3. 结果真源

唯一计算真源是每问的 `result.json`。结果链固定为：

```text
result.json
→ verification.json
→ result_ledger.json
→ paper/generated/results.typ
→ paper/main.typ 与各问 paper.typ
```

求解代码只声明计算值、单位、显示格式、资源路径、求解器事实、警告及请求执行的检查。Result 中禁止 `verified: true` 或同义自证字段。

Result 指标名使用 ASCII 小写 snake_case。指标值必须是有限整数、有限浮点、字符串或布尔值；单位是显式字符串；格式声明可指定 `scale`、`decimals` 与 `suffix`。

## 4. Verification

Verification 由独立检查器派生，不由求解代码写入 passed。验证器读取 Result、题目声明、结果资源和官方附件，运行对应检查后写 `verification.json`。

Verification 必须记录当前 Result 的规范化 SHA-256 摘要。状态仅有：

```text
unchecked  无 verification.json
failed     摘要匹配，但至少一个所需检查失败
stale      verification 摘要与当前 result.json 不匹配
verified   摘要匹配且全部所需检查通过
```

任何 Result 字节语义改变都会使既有 Verification 自动 stale。求解脚本不能导入 Verification 写入 API。

Checker 是题目运行目录中由 `question.json` 声明的普通 Python 入口。通用框架只负责调用、规范结果与摘要，不把 2024-C 规则写入通用代码。

## 5. Ledger

Ledger 是当前全部 Result 与有效 Verification 的派生快照，不是日志。构建规则是：

```text
当前全部 questions/*/results/result.json
+ 对应 verification.json 的派生状态
→ 完整覆盖重建 result_ledger.json
```

禁止 append-only、事件历史、superseded/current、手工追加和手工状态。删除 Ledger 后必须能从当前输入完整重建。同一输入必须生成字节一致输出。

Ledger 中每项保留 question id、metric id、raw value、unit、format、display value 与 verification status。排序固定为 question id 后 metric id。

## 6. Typst 数字绑定

`paper/generated/results.typ` 只从 Ledger 生成，首行必须是：

```typst
// AUTO-GENERATED. DO NOT EDIT.
```

每个指标生成 raw、display、unit 与 verification 四个变量。变量名由 `<qid>-<metric>` 稳定转换而来；冲突直接报 ERROR。论文的关键数字必须引用这些生成变量，不允许手抄。

## 7. 动态 Status

Status 每次从客观文件和检查结果推导：比赛配置、问题配置、模型、运行入口、Result、Verification、图表/表格、问级正文、Ledger、results.typ、主论文 PDF 和官方附件。

状态词只使用 `missing`、`draft`、`ready`、`failed`、`stale`、`unchecked`、`verified`。可选 `.status_cache.json` 必须可删除、可重建、不影响 verify，且缓存过期不能产生 PASS。第一版默认不生成缓存。

## 8. Fast 与 Standard

`contest_fast` 的 ERROR 包括：必答问题无结果、Result 无法解析、硬约束失败、关键结果冲突、Ledger/Typst 过期、论文编译失败、官方附件缺失及提交包缺核心内容。其他质量项默认 WARNING。

`contest_standard` 在 Fast 上读取每问声明：缺 required checks 是 ERROR，缺 recommended checks 是 WARNING。框架不全局要求三路线、多 seed、敏感性、消融或基线；这些由题意和模型决定。

## 9. CLI

公开 CLI 只有四个命令：

```text
init     创建最小运行目录与模板，不覆盖用户文件
status   报告动态客观状态
verify   校验 Result、运行 Checker、重建 Ledger/Typst、编译论文并检查附件
package  生成 submission.pdf 与 support.zip
```

CLI 不推进 Gate、不维护 progress、不判断资格、不调用 LLM。

## 10. Package

Package 只产出：

```text
package/submission.pdf
package/support.zip
```

ZIP 包含复现所需的配置、模型、代码、Result、Verification、Ledger、生成值、图表、表格和官方要求附件。必须排除 `.git`、`__pycache__`、`.venv`、cache、临时文件、review 草稿、旧 Gate 文件、密钥和本地环境文件。

## 11. Smoke 与 Pilot

读取历史 Formal Result、旧图表或旧报告的 2024-C migration 只能是 `packaging_smoke_only`。它只能证明 Ledger、Typst、PDF 和 Package 可工作，成功标识只能是 `PACKAGING_SMOKE_PASS`。

Production Pilot 必须从官方题面和附件实际读取、建模、求解、复算、作图、写正文与回填官方附件。2024-C 的 seed、scenario 数、风险参数和阶段预算只属于 `examples/2024_C/PILOT_PLAN.md`，不得进入通用架构。

## 12. Reviewer 与结论边界

工程状态与论文质量状态属于两条不同语义。CLI 的 `verified`、verify PASS、PDF 编译成功和 package 完整只支持：

```text
ENGINEERING_VERIFICATION = PASS
```

它们不支持 `PAPER_ADMISSION=PASS`、Reviewer 推荐或提交就绪。

建模前，作者任务必须从优秀论文注册表生成 LEARNING_CONTEXT：只加载适用的 `global_active` 规则和少量已核验跨题模式，明确排除同题答案，首次完整编译前完成每文章节覆盖计划，成稿后回填实际采用位置或拒绝理由。未验证候选规则不得进入作者上下文。

工程 PASS 后，作者任务必须按 `docs/workflows/03_新题执行流.md` 对每问填写 Paper Admission 矩阵。任一核心模型、明确回答、求解证据、结果解释或适用边界缺失，论文只能标为 `technical_report / PAPER_ADMISSION=FAIL`。页数不是硬门槛。

准入不是作者顶层字段自声明。交接构建器必须校验全部必需问题、11 个固定矩阵项、PASS 状态、非空 evidence、条件项 NOT_APPLICABLE 理由、空 direct_blockers、学习资产选择权限、章节覆盖和应用回填。准入 PASS 必须同时绑定当前 PDF 与 LEARNING_CONTEXT SHA-256；任一文件改变后准入自动 PENDING。

只有 Paper Admission 对当前 PDF 有效，才允许由独立新对话执行 Final Review。评审采用 `docs/contest_v2/NATIONAL_CONTEST_REVIEW_WORKFLOW.md`：以仓库内优秀论文学习卡片抽象出的高分论文画像为标准，同时检查题目覆盖、模型、求解证据、结果决策价值、图表、可读性和创新性，不得把技术一致性检查当成竞赛质量评审。Reviewer 只读取隔离交接包，不读取主任务完整对话或同题优秀论文。Reviewer 输出 `review/final_review.md`，其必须修复项经修补后必须另建一个全新的 Reviewer 对话复审。

新题只有在工程验收和 Paper Admission 均通过后，作者任务才自动创建新的 Codex 桌面 Reviewer 任务；修补后重建全部受影响产物、重新准入，并创建另一全新任务复审。此自动触发属于 Agent/桌面运行时，不进入薄 CLI；没有新任务接口时只能交付隔离包，不能在作者任务内自评。

Reviewer 固定采用 20/20/20/15/15/10 六维权重。`SUBMISSION_RECOMMENDED` 要求总分至少 80、MUST 为空、题目覆盖/模型/求解三个核心维度各至少 14/20、其他维度至少达到满分 60%。创新性不单独一票否决。作者任务无权声明 `SUBMISSION_STATUS=READY`；只有全新复审推荐、MUST 为空、Paper Admission 有效、最终 PDF/package 与被评摘要一致且完成附件核包时，编排层才能派生 READY。

新优秀论文必须按 `docs/workflows/01_论文学习流.md` 写入学习卡、知识卡、训练日志和 `papers/EXCELLENT_PAPER_REVIEW_STANDARD_REGISTRY.json`。单篇或未核验经验只能作为候选；只有具备已核验 source claim、跨论文支持和明确 production replay/陌生题完整生产 Run 证据的规则才能进入 `global_active`。缺少生产 Run ID 时必须降级并记录 activation blocker。

Final Reviewer 不能修改资格状态。v2 verify PASS 仅表示当前工程检查在所声明范围内通过，不表示论文准入、Reviewer 推荐、`SUBMISSION_STATUS=READY`、`production_ready`、`qualification passed` 或任何奖项水平。

## 13. 通用性边界

2024-C 的农业参数、场景规模、相关结构和求解预算留在试点目录。两道不同题目真实运行前不新增 JSON Schema、Registry、Profile、合同生成器或复杂状态机。

陌生旧题用于暴露 Result/Verification/Ledger、CLI、论文同步和题型适配的通用缺陷。只把两题共同问题或显然属于框架的缺陷提升为通用实现；单题模型机制留在各自示例中。
