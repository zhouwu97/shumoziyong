# 建模能力升级长期路线图 v1.1
## ——题目专属建模、可信验证、结论边界与竞赛表达双主线

> 建议仓库路径：`docs/roadmap/MODELING_CAPABILITY_ROADMAP.md`  
> 文档属性：长期架构约束，不是一次性 Codex 施工单  
> 适用项目：`zhouwu97/shumoziyong`  
> 版本：v1.1  
> 日期：2026-07-15

---

# 0. 文档定位

本路线图定义项目未来的能力方向、不可妥协边界和阶段依赖。它不授权执行器一次性创建全部 Schema、Validator、微型题、旧题训练和盲测资产。

实际施工必须由独立短周期合同驱动：

```text
docs/roadmap/NEXT_SPRINT_MODELING_CONTRACT_V01.md
```

长期路线图与近期施工单的关系为：

```text
长期路线图
= 方向、边界、依赖、最终验收

近期施工单
= 本轮允许修改的文件、测试、停止条件和 PR 顺序
```

任何未进入近期施工单的内容均属于 `LATER`，不得被执行器提前实现。

---

# 1. 总体判断

项目当前最有价值的能力是可信控制面：

- 材料与运行身份冻结；
- Gate 状态机；
- Executor、Collector、Validator 职责隔离；
- Candidate Result 与 Formal Result 隔离；
- 目标值、约束、Excel 和跨语言复算；
- 可行、不可行、限时可行、未证最优等状态边界；
- Patch、Profile 和能力成熟度的证据化管理；
- 论文数值、单位、舍入和来源绑定。

下一阶段不应继续把主要精力投入到新增协议版本、堆叠检查数量或题目专属确认流程，而应提高下列能力：

1. 未知题首次建模正确率；
2. 决策空间完整率；
3. 题目专属结构发现能力；
4. 模型参数和时间语义的真实性；
5. 模型外部或独立合理性验证；
6. 理论最优向可执行方案的转化；
7. 结论作用域和措辞强度控制；
8. 竞赛论文的机理解释和阅读冲击力。

项目的目标链路由：

```text
执行是否真实
→ 解是否满足当前模型
```

升级为：

```text
题意是否理解正确
→ 模型是否匹配现实机制
→ 决策空间是否完整
→ 参数和时间语义是否正确
→ 求解是否可信
→ 结论是否受证据约束
→ 方案是否可执行
→ 论文是否清楚解释结构与价值
```

---

# 2. 双主线架构

## 2.1 主线 A：可信计算与证据链

继续保持：

```text
题面与材料
→ Gate Contract
→ Executor Candidate
→ Collector Clean Rerun
→ Numeric Validator
→ Formal Result
→ Claim–Result Map
→ Paper / Independent Review
```

负责证明：

- 输入、代码和运行身份没有漂移；
- 执行命令真实发生；
- 正式结果由独立重跑生成；
- 目标值与硬约束可独立复算；
- 论文数字有唯一来源；
- 结论不超过求解状态和证据范围。

## 2.2 主线 B：题目专属建模与竞赛表达

新增：

```text
现实过程
→ 机制链与业务语义
→ 变量、参数和结构
→ 基线与候选模型
→ 规律发现
→ 子问题递进
→ 外部或独立合理性验证
→ 理论解与推荐解
→ 图形解释与决策建议
```

负责回答：

- 为什么使用这套模型；
- 哪些结构来自题目而非通用套模；
- 第一问发现了什么；
- 后续问题如何利用前序发现；
- 数学结果为什么呈现当前形态；
- 现实使用者应该如何执行；
- 哪些条件变化会使结论失效。

两条主线必须同时通过，才允许将一次运行评价为“高质量竞赛方案”。

---

# 3. 训练资产定位

## 3.1 A092《定日镜场的优化设计》

### 正向能力

- 太阳位置、入射反射、镜面姿态、光学效率和输出功率的连续机理链；
- 坐标系、投影、遮挡和光线追迹的题目专属推导；
- 模型构造图参与解释公式；
- 第一问认识空间规律，后续问题利用规律优化；
- 结果图解释空间结构，而不仅汇报目标值。

### 反向警示

- 随机生成少量可行解不能证明全局最优；
- 物理趋势相符不能替代严格模型验证；
- 正文宣称的联合优化变量必须与实际代码一致；
- 循环次数、归一化分母和实现口径必须可复核；
- 图形数量不能掩盖缺少最优性和复现证据。

## 3.2 2021-C《生产企业原材料的订购与运输》

### 正向能力

- 区分未订购零供货与已订购零供货；
- 25 家不足、26 家可行的上下界闭合；
- 全部候选空间中的词典序 MILP；
- 后续阶段只锁定前序目标值；
- 求解状态、作用域和外推边界表达诚实；
- Python、MATLAB、Excel 和故障注入的独立验证。

### 改进方向

- 强化“供应能力长尾—低损耗运力—库存安全”的题目专属耦合结构；
- 将 24 周重复解释为时间可分性结论，或引入真实动态；
- 对历史能力参数开展回测或稳健性验证；
- 将 305 家理论最优方案转化为近优可执行方案；
- 压缩正文中的软件验收细节，突出结构、原因和管理建议。

## 3.3 训练原则

两篇论文不用于简单排名，而承担互补角色：

```text
A092
= 机理深度、图形推导、逐问递进

2021-C
= 完整决策空间、最优性闭合、独立复算、诚实边界
```

理想能力组合为：

> A092 前半部分的题目专属建模深度，加上 2021-C 后半部分的可信求解与结论约束。

---

# 4. 不可妥协的实施原则

## 4.1 不新增第四个用户工作流

继续保持三个入口：

1. 论文学习流；
2. 旧题闭环流；
3. 新题执行流。

优秀论文的正向提取与技术红队统一并入论文学习流。

## 4.2 不把质量属性做成题型 Profile

以下内容属于所有题型的横向质量属性：

- 决策空间完整性；
- 候选缩减证明；
- 参数语义；
- 时间语义；
- 最优性边界；
- Claim 作用域；
- 模型外部验证；
- 运营可执行性。

它们应进入 Schema、Validator、Checklist 和 Reviewer，而不是创建新的 Profile。

## 4.3 不继续平铺 P11、P12 等编号

采用命名空间失败码：

```yaml
failure_code: OPT-SCOPE-001
layer: model
dimension: decision_space
severity: P0
```

建议命名空间：

- `SEM-*`：题意与业务语义；
- `DATA-*`：数据和参数；
- `MODEL-*`：模型结构；
- `OPT-*`：优化与最优性；
- `STAT-*`：统计与预测；
- `TIME-*`：时间和稳态；
- `EXEC-*`：执行与复现；
- `CLAIM-*`：结论作用域；
- `PAPER-*`：论文表达。

P0、P1、P2 仅表示严重程度。

## 4.4 禁止人工提升 Profile maturity

`runtime_profiles/*.json` 继续作为机器事实源。

允许修改：

- 派生逻辑；
- 证据引用；
- Schema 错误；
- 事实记录错误。

禁止：

- 为与训练日志一致而手工把 `assembled` 改成更高状态；
- 把 smoke、dry-run 或已知训练题记录直接计为 Profile Qualification；
- 用人工总结覆盖政策派生结果。

## 4.5 历史冻结记录不可追随代码更新

冻结后只允许两条路径：

### 路径 A：恢复被冻结组件

将当前组件恢复到原冻结哈希，继续使用旧协议。

### 路径 B：宣告旧协议失效

保留原冻结记录，新增不可变的失效旁证：

```yaml
state: invalidated_by_component_drift
frozen_manifest_sha256:
observed_component_sha256:
reason:
superseded_by:
```

随后创建新协议重新冻结。

禁止直接把旧 freeze 中的哈希改成当前文件哈希。

## 4.6 题目专属性不等于强迫创新

通用 LP、回归、排队模型或经典统计方法可以是正确答案。

审核目标是：

> 禁止无理由套模，而不是强迫每道题虚构新机理。

质量合同必须允许：

```yaml
specificity_level:
  - strong_problem_specific
  - domain_specific
  - standard_model_with_specific_parameters
  - no_additional_structure_found

not_forced_novelty: true
```

诚实报告“未发现可证明的额外结构”不是失败。

---

# 5. 模型路线合同演进

## 5.1 版本策略

不得破坏性修改已经封存的 `model_route_v2` 语义。

建议新增：

```text
schema_version: 2.1.0
```

使用兼容容器：

```yaml
quality_contract:
  full_decision_space:
  mechanism_chain:
  candidate_reduction:
  parameter_semantics:
  time_semantics:
  optimality_target:
  external_validation:
  operational_plan:
```

迁移规则：

- 历史 2.0 Run 按原 Schema 验证；
- 新建 `full_replay` 和 `new_problem` Run 强制使用 2.1；
- 不重写历史 Run；
- 不重算历史封存哈希；
- 不因 2.1 新字段缺失而让 2.0 记录失效；
- 转换器只能创建新派生文件，不能覆盖 sealed artifact。

## 5.2 完整决策空间

```yaml
full_decision_space:
  objects:
  variables:
  variable_domains:
  time_dimension:
  spatial_dimension:
  omitted_elements:
  omission_justification:
```

## 5.3 机制链

```yaml
mechanism_chain:
  specificity_level:
  real_process:
  mathematical_links:
  problem_specific_structure:
  evidence:
  no_additional_structure_reason:
  not_forced_novelty: true
```

## 5.4 候选缩减

```yaml
candidate_reduction:
  applied:
  rule:
  removed_objects:
  preservation_target:
    - feasibility
    - optimality
  proof_type:
    - dominance
    - exact_bound
    - decomposition
    - exhaustive_equivalence
    - none
  proof_artifact:
  claim_scope_after_reduction:
```

规则：

```text
applied = true 且 proof_type = none
=> 禁止“全局最优”“全局不可行”
```

合法缩减必须有负控，避免 Validator 把严格支配、对称压缩和精确分解误报为错误。

## 5.5 参数语义

```yaml
parameter_semantics:
  parameter_id:
  statistical_definition:
  business_interpretation:
  model_role:
  hard_constraint:
  hardening_justification:
  optimism_direction:
  uncertainty_treatment:
```

## 5.6 时间语义

```yaml
time_semantics:
  type:
    - one_shot
    - steady_state
    - transition
    - rolling
  decomposition_proof:
  initial_state_source:
  terminal_state_requirement:
  immediate_implementability:
```

## 5.7 最优性目标

```yaml
optimality_target:
  type:
    - exact_global
    - bounded_near_optimal
    - heuristic_best_known
    - candidate_set_optimum
  expected_solver_evidence:
  wording_boundary:
```

## 5.8 外部或独立合理性验证

外部验证不等于所有题都做训练集—测试集划分。

```yaml
external_validation:
  applicability:
    - required
    - recommended
    - not_applicable
  validation_type:
  target:
  held_out_information:
  acceptance_threshold:
  result:
  limitations:
```

不同题型的推荐验证：

| 模型 | 验证方式 |
|---|---|
| 预测 | 时间留出、滚动回测、外部样本 |
| 参数估计 | Bootstrap、区间估计、留出检验 |
| 确定性优化 | 小规模精确解、上下界、独立基线 |
| 几何物理 | 解析特例、守恒、极限状态、网格收敛 |
| 评价排序 | 权重空间、排名概率、指标冗余 |
| 仿真 | 重复实验、置信区间、稳态和方差分析 |

## 5.9 运营推荐触发条件

不是所有优化题都强制求两次。

```yaml
operational_plan:
  recommended_solution_required:
  trigger_reasons:
  thresholds:
  reason_when_not_required:
```

出现下列任一情况时强制生成推荐解：

- 启用对象数超过业务阈值；
- 小额决策比例超过阈值；
- 存在拆分运输；
- 解高度集中于单一对象；
- 缺少备用能力；
- 核心变量来自连续松弛；
- 题面明确要求可执行计划；
- 人工审查认定管理复杂度过高。

若理论解已经可执行：

```yaml
recommended_solution_required: false
reason_when_not_required: theoretical_solution_already_operational
```

---

# 6. Claim–Result Map v0.1

## 6.1 多维证据为事实源

单一 C1—C5 不能同时表达执行可信性、可行性、最优性、决策空间、参数外推和时间作用域。

底层使用：

```yaml
evidence_status:
  execution_trust:
    - verified
    - candidate
    - failed

  feasibility:
    - independently_verified
    - solver_reported
    - failed
    - unknown

  optimality:
    - mathematically_proven
    - solver_proven
    - bounded_gap
    - heuristic
    - unknown

  decision_scope:
    - full
    - safely_reduced
    - reduced_without_proof

  parameter_scope:
    - deterministic_observed
    - estimated_expected
    - robust
    - stochastic

  time_scope:
    - one_shot
    - steady_state
    - transition
    - rolling

  external_validity:
    - validated
    - partially_validated
    - model_internal_only
```

## 6.2 展示等级为派生结果

由政策派生：

```yaml
display_evidence_level: C1
allowed_wording:
forbidden_wording:
```

C1—C5 只用于论文展示，不作为底层唯一事实。

## 6.3 示例

```yaml
claim_id: Q2_MIN_SUPPLIER
claim_text: 在确定性历史期望能力模型下，最少需要26家供应商

evidence_status:
  execution_trust: verified
  feasibility: independently_verified
  optimality: mathematically_proven
  decision_scope: full
  parameter_scope: estimated_expected
  time_scope: steady_state
  external_validity: model_internal_only

allowed_wording:
  - 在当前确定性模型下最少需要26家
  - 26家是数学最小基数

forbidden_wording:
  - 企业未来只需要26家
  - 26家能够保证逐周稳定供货
  - 26家是推荐长期合作规模
```

---

# 7. 标准 LP/MILP 模型快照

通用程序不宣称理解任意论文和任意代码的完全语义等价。

将原计划中的：

```text
model_implementation_consistency.py
```

改为：

```text
model_contract_coverage.py
```

其职责只包括：

- 合同声明变量是否出现在模型快照中；
- 变量维度、域和上下界是否一致；
- 目标函数是否有唯一来源；
- 约束类别是否有对应矩阵块或独立检查器；
- 实际优化变量是否少于论文声明；
- 报告中的模型尺寸是否与快照一致。

LP/MILP 标准快照至少包含：

```yaml
model_identity:
objective_sense:
variable_manifest:
objective_vector:
constraint_matrix_coo:
constraint_lower:
constraint_upper:
variable_lower:
variable_upper:
integrality:
solution_vector:
solver_status:
best_bound:
mip_gap:
```

独立 Validator 复算：

\[
c^\top x,\qquad
l \le Ax \le u,
\]

并检查：

- 变量边界；
- 约束残差；
- 整数性；
- 目标值；
- incumbent；
- best bound；
- MIP gap；
- 结论措辞。

Executor 可以导出 candidate snapshot；Formal snapshot 必须由 Collector 在干净重跑后生成。

---

# 8. 微型数学回归体系

## 8.1 分批实施

### 第一批：结论作用域

- MB01 候选截断；
- MB02 局部不可行；
- MB03 词典序锁错；
- MB10 限时可行未证最优。

### 第二批：参数与时间语义

- MB04 期望硬化；
- MB05 稳态与过渡态；
- MB08 单位混用；
- MB12 时间可分性。

### 第三批：实现和运营

- MB06 连续最优不可执行；
- MB07 启发式越级；
- MB09 目标篡改；
- MB11 正文与实现不一致。

## 8.2 每题四类 Oracle

```yaml
expected_diagnosis:
expected_contract:
expected_validator_result:
expected_claim_wording:
```

## 8.3 合法负控

每个错误用例必须配至少一个合法近邻：

- MB01：严格支配安全删变量；
- MB02：正式证明全空间不可行；
- MB03：正确锁定目标值；
- MB04：机会约束或稳健下界；
- MB05：已满足稳态初始条件；
- MB06：理论解本身满足运营阈值；
- MB07：存在精确界证明；
- MB08：单位转换声明完整；
- MB09：目标独立复算一致；
- MB10：求解器已证明最优；
- MB11：模型快照覆盖全部变量；
- MB12：存在真实周际耦合，不能分解。

系统必须拦截错误，也不能误伤合法建模。

---

# 9. 论文学习流升级

继续使用：

```text
docs/workflows/01_论文学习流.md
```

每篇论文生成：

1. 正向能力提取；
2. 技术红队审核；
3. 可迁移规则；
4. 不可照搬内容；
5. 最小反例；
6. 合法负控；
7. 回归测试建议；
8. 题目专属机制链；
9. 结论作用域风险；
10. 竞赛表达经验；
11. Patch 草案。

新增审核问题：

- 最有辨识度的结构是什么；
- 哪张图实际参与模型推导；
- 第一问发现了什么；
- 后续问题是否利用该发现；
- 是否存在正文与代码变量不一致；
- 是否把启发式结果写成全局最优；
- 是否只验证解而没有验证模型；
- 理论方案是否实际可执行；
- 是否为了“创新”强行制造机理；
- 核心贡献能否用一句话准确表达。

---

# 10. 竞赛论文表达原则

每个核心结论至少使用一种最合适的证据载体：

- 数学推导；
- 数据表；
- 机理图；
- 结构图；
- 结果图；
- 回测图；
- 权衡曲线；
- 独立验证表。

仅在确有不同论证作用时增加第二种图形，不设“每问至少两类图”的机械要求。

每一问推荐形成：

1. 现实过程；
2. 结构或规律；
3. 模型目标；
4. 关键约束；
5. 求解方式；
6. 结果与基线；
7. 原因与建议；
8. 适用边界。

正文应减少：

- 大量六位小数；
- 重复的执行状态；
- 逐项单元格检查数量；
- 冗长源码。

详细审计进入附录或证据包。

---

# 11. 资格层级

已用于开发和修复的 2024-C、2023-B、2021-C 只能用于：

```text
三题端到端资格预演
```

正式层级：

```text
微型题通过
→ 三道已知旧题资格预演
→ 至少一道冻结前未参与开发的留出旧题
→ 未知题限时盲测
→ Profile Qualification
```

训练题通过不能单独升级 Profile maturity。

---

# 12. CI 双通道

## 12.1 Public CI

任何正常 clone 均可运行：

- 单元测试；
- Schema 校验；
- Ruff；
- Pyright；
- 微型回归；
- 不依赖受控材料的集成测试；
- Runtime 确定性构建。

Public CI 必须全绿。

## 12.2 Controlled Integration CI

依赖官方受控附件或本地环境：

- 完整旧题重跑；
- 真实 Excel/PDF 集成；
- 材料哈希；
- Collector/Validator；
- MATLAB 或受控执行器；
- Profile Qualification 证据。

材料不存在时输出：

```text
NOT_RUN_MISSING_CONTROLLED_MATERIAL
```

不得伪装为 PASS，也不得让 Public CI 永久红色。

能力派生脚本必须要求：

```yaml
ci_lanes:
  public_required: passed
  controlled_required_for_qualification: passed
```

Controlled 未运行不影响普通 PR 的 Public CI，但禁止产生 Qualification 资格。

---

# 13. 72 小时比赛模式

时间点是最晚检查点，不是固定流程。

| 最晚时间 | 必须达到 |
|---|---|
| 2 小时 | Gate 0—1、题意和候选路线 |
| 6 小时 | 首个可运行基线 |
| 18 小时 | 各问首个候选结果 |
| 30 小时 | 主模型、作用域审计和独立复算 |
| 42 小时 | 合理性验证、敏感性和必要的推荐解 |
| 54 小时 | 论文初稿 |
| 66 小时 | 数学、复现、论文和竞赛审稿 |
| 72 小时 | 封存与提交 |

停止规则：

```text
6 小时仍无可运行基线
=> 强制降级模型路线

30 小时仍无独立复算通过的主结果
=> 禁止进入完整论文美化

54 小时仍有共同 P0
=> 停止新增模型，优先保证一套正确完整方案
```

比赛模式不可放弃：

- 决策空间审计；
- 目标独立复算；
- 硬约束检查；
- Claim Map；
- 结论等级；
- 模型快照覆盖。

比赛模式可以放弃：

- Patch 晋级实验；
- Profile 成熟度升级；
- 大规模跨语言复现；
- 题目专属确认协议；
- 非关键故障注入；
- 非关键源码附录。

---

# 14. 长期衡量指标

不再主要以测试数量、Schema 数量、协议版本和代码行数衡量进展。

核心指标：

| 指标 | 含义 |
|---|---|
| 未知题首次建模正确率 | 第一版是否误解题意、漏变量或漏约束 |
| 决策空间完整率 | 是否覆盖全部关键对象和变量 |
| 合法缩减识别率 | 是否同时拦截错误缩减并放行严格安全缩减 |
| 结论越级率 | 是否把局部、启发式或未证最优结果写成强结论 |
| 模型快照覆盖率 | 论文合同与正式矩阵模型是否对应 |
| 合理性验证完成率 | 是否采用与模型类型匹配的验证 |
| 题目专属结构得分 | 是否发现真实而非强迫制造的结构 |
| 运营推荐触发准确率 | 是否在必要时生成推荐解，非必要时不增加复杂度 |
| 论文独立可读性 | 不看代码能否理解机制、结果和建议 |
| 72 小时完成率 | 是否能在时限内形成完整可提交方案 |
| 独立评审共同 P0 | 是否存在多位评审一致确认的致命错误 |

---

# 15. 最终路线

```text
先修事实和 CI
→ 版本化模型质量合同
→ 多维 Claim–Result Map
→ 第一批微型作用域回归
→ 标准 LP/MILP 快照与残差验证
→ 参数与时间语义
→ 2021-C 试点
→ 三题资格预演
→ 留出旧题
→ 未知题限时盲测
→ Profile Qualification
```

项目最终目标不是仅证明代码真实运行，而是：

> 在未知赛题上建出与题意匹配的模型，明确决策空间和参数语义，形成可执行方案，以独立证据限制结论强度，并用竞赛论文清楚解释其结构和价值。
