# 数学建模能力提升第一阶段执行计划（修订定稿）

> 项目：`zhouwu97/shumoziyong`  
> 核心目标：优先提升数学建模、数值验证和国赛论文输出能力  
> 首个验证对象：`A092 engineering optimization patch`  
> 执行方式：本地修改、测试、提交，通过 SSH 直接推送；不要求创建 Pull Request  
> 计划性质：项目设计说明，不作为每次做题时完整注入给执行 AI 的提示词

---

## 1. 阶段目标

本阶段不再继续扩展安全隔离、供应链证明或复杂执行审计，而是集中回答：

> **A092 是否能够让 AI 少犯建模错误、得到更可靠的结果，并写出更有竞争力的数学建模论文？**

重点提升：

1. 题意理解与子问题拆分；
2. 工程机理、能量流、损失链和评价体系分析；
3. 目标函数、变量、约束和求解路线设计；
4. 简单基线与优化方案的真实比较；
5. 目标函数和关键约束的独立复算；
6. 敏感性、稳健性和最优性边界判断；
7. 结果驱动的摘要、正文、图表和结论表达；
8. Patch 是否真正产生增量能力的可重复验证。

本阶段优先级固定为：

```text
数学正确性
>
建模质量
>
结果可复算性
>
验证与敏感性
>
论文表达
>
必要工程维护
>
安全与供应链增强
```

---

# 2. 执行方式

本阶段不要求使用 PR。

每个阶段由执行 AI：

```text
读取本计划
→ 检查当前 main
→ 创建或修改对应文件
→ 运行测试
→ 生成阶段总结
→ git commit
→ 通过 SSH push
```

建议仍保持一个阶段一个提交，便于回退和审查。

示例：

```bash
git checkout main
git pull --ff-only origin main

# 完成一个阶段后
git status
git add <本阶段相关文件>
git commit -m "feat: implement A092 experiment protocol"
git push origin main
```

如果远程 `origin` 不是 SSH 地址，先设置：

```bash
git remote set-url origin git@github.com:zhouwu97/shumoziyong.git
```

执行 AI 不应一次把所有阶段混在同一个提交中。

建议提交顺序：

```text
Commit 1：两个工程尾项
Commit 2：A092 操作化、Pilot 和实验预注册
Commit 3：正式 baseline/treatment 与晋级决定
```

---

# 3. 总体路线

```text
阶段一
两个工程尾项
↓
冻结安全主线
↓
阶段二
A092 证据与操作化
Validator v0
非晋级 Pilot
根据 Pilot 修正规则
冻结确认性实验协议
A092 保持 review_ready
↓
阶段三
三类题正式 baseline/treatment
最低限度配对重复
Gate 0–5
独立数学复算
盲化评分
论文比较
↓
满足门槛：regression_verified
不满足：继续 review_ready
```

---

# 4. 阶段一：最后两个工程小修复

## 4.1 修改内容

只处理：

```text
1. CLI 输出完整 trusted_local scope；
2. 原始输出目录拒绝 symlink / junction / hardlink。
```

CLI 应输出完整摘要，而不是只有裸布尔值：

```json
{
  "run_id": "...",
  "formal_result_activation_status": "run_execution_verified",
  "formal_result_eligible": true,
  "formal_result_eligibility_scope": "trusted_local",
  "execution_trust_model": "trusted_local",
  "git_head": "...",
  "git_state_clean": true,
  "targeted_host_read_controls_passed": true,
  "default_deny_host_reads_verified": false
}
```

复制候选输出前检查：

```text
symlink
junction
hardlink
```

发现链接型输出时：

```text
拒绝进入正式结果
记录文件路径和链接类型
不复制目标内容
返回明确失败原因
```

## 4.2 明确不做

阶段一不包含：

- 完整 venv 绑定；
- Executor、Collector、Validator 顶层拆分；
- GitHub Actions SHA 固定；
- 新 Sandboxie 后端；
- 新签名和安全证明；
- 多人 Review 门禁；
- Profile 成熟度重构；
- A092 实验内容。

## 4.3 验收

```text
现有测试通过
CLI 完整摘要测试通过
symlink 输出拒绝测试通过
hardlink 输出拒绝测试通过
合法 Fixture 结果不变
```

完成后提交并 SSH 推送，然后冻结安全主线。

---

# 5. 阶段二：A092 能力实现与实验预注册

阶段二的目标不是晋级 A092，而是建立一套：

```text
可执行
可校准
可复算
可重复
允许失败
```

的验证协议。

阶段二结束时必须保持：

```json
{
  "patch_id": "A092",
  "status": "review_ready"
}
```

不得在本阶段写入正式晋级结论。

---

# 6. A092 的职责边界

现有 optimization plugin 已经负责：

- 目标函数；
- 决策变量；
- 约束条件；
- 简单方法优先；
- 智能优化算法质疑；
- 降维；
- 基线比较；
- 敏感性分析计划。

因此 A092 不得成为 optimization plugin 的重复版。

A092 不是：

```text
optimization plugin v2
通用优化原则合集
论文套话扩写器
复杂算法推荐器
为了晋级而增加的评分模板
```

A092 只保留现有 plugin 容易遗漏，并且能够机器检查的增量行为。

---

# 7. A092 七项核心行为

## A092-R1：机制损失链

建立：

```text
输入
→ 转换过程
→ 中间状态
→ 损失项
→ 有效输出
```

输出：

```json
{
  "mechanism_chain": {
    "inputs": [],
    "transformations": [],
    "intermediate_states": [],
    "loss_terms": [],
    "outputs": []
  }
}
```

要求：

- 每个损失项有现实或题面来源；
- 关键量说明含义和单位；
- 不允许为满足格式虚构机理；
- 边界题和负控题允许明确关闭本模块。

---

## A092-R2：固定方案评价器

优化前先实现固定方案评价器：

```python
evaluate_solution(solution, problem_data)
```

同一个评价器用于：

```text
基线方案
优化候选方案
最终报告方案
独立目标复算
关键约束计算
```

禁止：

- Baseline 和 Treatment 使用不同目标口径；
- 优化器内部值与论文值使用不同公式；
- 结果出来后修改评价函数以提高改进率。

---

## A092-R3：简单基线

调用复杂优化器前，至少计算一个简单、可解释、可复算的基线：

- 规则方案；
- 均匀方案；
- 经验方案；
- 枚举或粗网格方案；
- 简化线性或整数规划方案；
- 随机可行方案中的最好结果。

输出：

```json
{
  "baseline_result": {
    "method": "...",
    "decision_variables": {},
    "objective": 0,
    "feasible": true
  }
}
```

---

## A092-R4：目标函数独立复算

不得直接把优化器内部返回值写入论文。

必须输出：

```text
objective_reported
objective_recomputed
objective_difference
```

其中：

```text
objective_reported
```

是求解器或候选程序报告值；

```text
objective_recomputed
```

是独立评价器重算值。

---

## A092-R5：关键约束独立检查

不得使用：

```text
solver_status = success
```

代替可行性验证。

所有关键约束统一转换为：

```text
不等式：g_i(x) <= 0
等式：h_j(x) = 0
```

每条约束输出：

```json
{
  "constraint_id": "...",
  "constraint_type": "inequality | equality",
  "raw_residual": 0.000001,
  "scaled_residual": 0.0000002,
  "absolute_tolerance": 1e-6,
  "relative_tolerance": 1e-5,
  "satisfied": true
}
```

浮点问题不要求残差严格等于 0。

---

## A092-R6：按适用性执行敏感性分析

不再机械要求所有题都执行三个参数。

### 正向题

原则上预注册三个关键参数。

如果只有一到两个真正重要且可解释的参数，允许减少，但必须在实验协议中提前说明原因。

### 边界题

只对实际适用的参数进行扰动。

允许关闭敏感性模块，但必须说明：

```text
为什么不适用
关闭后是否影响核心结论
```

### 负控题

不得为了完成 A092 产物强行进行敏感性分析。

### 敏感性分类

不允许只靠文字主观判断：

```text
stable
moderately_sensitive
highly_sensitive
```

必须在协议中预注册阈值。

建议第一版按相对变化定义：

```text
stable：
参数在预注册范围扰动时，目标变化绝对值 <= 5%，且方案结构不改变。

moderately_sensitive：
目标变化绝对值在 5% 到 15% 之间，或方案结构有局部变化但主要结论不变。

highly_sensitive：
目标变化绝对值 > 15%，或最优方案结构改变，或主要结论反转。
```

不同题目可以调整，但必须在正式 Treatment 前冻结。

---

## A092-R7：最优性声明降级与论文证据绑定

根据求解方式，只允许使用以下等级：

```text
global_optimum_verified
solver_certified_optimum
best_feasible_in_enumerated_space
best_found_in_search
locally_optimal_candidate
feasible_improved_solution
unverified_candidate
```

### solver_certified_optimum 的最低要求

必须同时满足：

1. 完整优化模型已输入求解器；
2. 求解器属于能够给出最优性证书的类别；
3. termination status 合法；
4. 若为 MIP，MIP gap 不超过预注册阈值；
5. 没有用非凸局部优化器的普通 `success` 冒充全局最优；
6. 最终方案通过独立目标和约束复算。

论文中的关键结论必须绑定：

```text
结果文件
结果字段
图表或表格
计算脚本
Validator 记录
```

缺少独立复算或证据时，禁止使用“最优方案”等强结论。

---

# 8. A092 最小机器产物

正向题完整触发时，至少产生：

```text
mechanism_chain
evaluation_function
baseline_result
optimized_result
objective_recomputed
constraint_results
sensitivity_results
optimality_claim_level
claim_map
```

建议目录：

```text
artifacts/a092/
├── mechanism_chain.json
├── evaluation_definition.json
├── baseline_result.json
├── optimized_result.json
├── validator_result.json
├── sensitivity_results.json
├── optimality_claim.json
└── claim_map.json
```

边界题和负控题允许关闭部分产物，但必须输出：

```json
{
  "module": "sensitivity_results",
  "status": "not_applicable",
  "reason": "..."
}
```

禁止为了补齐文件而虚构内容。

---

# 9. A092 原论文证据补全

每条证据保存：

```json
{
  "claim_id": "A092-C01",
  "page_ref": "p.xx",
  "evidence_quote": "...",
  "source_behavior": "...",
  "transferable_mechanism": "...",
  "operational_rule": "A092-Rx",
  "applicable_when": [],
  "not_applicable_when": [],
  "misuse_risk": []
}
```

每条证据必须形成：

```text
论文原始做法
→
可迁移机制
→
适用条件
→
关闭条件
→
A092 强制行为
→
机器可检查产物
```

不允许只有摘录，没有行为映射。

---

# 10. Validator v0

## 10.1 定位

Validator v0 不是通用数学平台。

第一版只实现工程优化题需要的核心检查：

```python
recompute_objective(...)
check_variable_bounds(...)
check_integrality(...)
check_constraints(...)
compare_with_baseline(...)
run_sensitivity_checks(...)
derive_optimality_claim(...)
```

## 10.2 通用薄壳

输出：

```json
{
  "objective_direction": "maximize",
  "feasible": true,
  "objective_reported": 17276602.82,
  "objective_recomputed": 17276602.82,
  "objective_difference": 0.0,
  "max_raw_constraint_violation": 0.0,
  "max_scaled_constraint_violation": 0.0,
  "violated_constraints": [],
  "baseline_objective": 16250142.79,
  "improvement_ratio": 0.0632,
  "bounds_valid": true,
  "integrality_valid": true,
  "sensitivity_checks_passed": true,
  "optimality_claim_allowed": "best_found_in_search",
  "global_optimality_verified": false
}
```

---

## 10.3 目标改进率口径

### 最大化问题

```text
improvement = new - baseline
```

### 最小化问题

```text
improvement = baseline - new
```

### 分母

默认：

```text
denominator = abs(baseline)
```

当：

```text
abs(baseline) > epsilon
```

时：

```text
improvement_ratio = improvement / abs(baseline)
```

当 baseline 接近 0 时：

```text
improvement_ratio = null
```

同时报告：

```text
absolute_improvement
baseline_near_zero = true
```

禁止通过极小 baseline 生成夸大的百分比。

### baseline 为负数

仍使用：

```text
abs(baseline)
```

作分母，同时必须报告绝对改进量，避免符号误读。

### 多目标问题

只有以下情况允许直接比较综合目标：

1. Baseline 与 Treatment 使用完全相同的目标函数；
2. 权重、归一化和方向完全相同；
3. 所有配置在 Treatment 前冻结。

如果权重或目标定义改变：

```text
improvement_ratio = not_comparable
```

必须分别报告各子目标。

---

## 10.4 约束残差口径

不等式：

```text
g_i(x) <= 0
```

原始违反量：

```text
raw_violation = max(g_i(x), 0)
```

等式：

```text
h_j(x) = 0
```

原始违反量：

```text
raw_violation = abs(h_j(x))
```

缩放违反量建议：

```text
scaled_violation =
raw_violation / max(scale_i, 1)
```

满足条件：

```text
raw_violation <= absolute_tolerance
或
scaled_violation <= relative_tolerance
```

容差必须在协议中冻结。

每道题可根据量纲设定不同容差，但不得在看到 Treatment 结果后调整。

---

## 10.5 题目适配器

建议：

```text
validators/
├── common/
│   ├── result_schema.py
│   ├── residuals.py
│   ├── improvement.py
│   └── claim_level.py
├── pilot_case/
│   └── validate.py
├── problem_positive/
│   ├── objective.py
│   ├── constraints.py
│   ├── sensitivity.py
│   └── validate.py
├── problem_boundary/
│   └── ...
└── problem_negative/
    └── ...
```

数学公式保留在各题适配器中，不强行建立万能接口。

---

# 11. 非晋级 Pilot

## 11.1 目的

A092 七项规则、Schema 和 Validator 第一次实际使用时，不直接进入正式晋级实验。

先使用一个：

```text
人造小题
或
明确排除在正式证据之外的旧题
```

完成 Pilot。

Pilot 只检查：

1. A092 产物是否能生成；
2. 评价器接口是否可用；
3. Validator 是否能独立复算；
4. 残差和容差是否合理；
5. 敏感性模块是否能有依据地开启或关闭；
6. 最优性等级是否能正确派生；
7. Claim Map 是否能绑定结果。

## 11.2 Pilot 必须包含故障注入

至少人工构造：

- 一个错误目标值；
- 一个越界变量；
- 一个非整数的整数变量；
- 一个违反关键约束的方案；
- 一个错误改进率；
- 一个伪造敏感性结果；
- 一个把启发式结果写成全局最优的声明。

Validator 应识别这些错误。

## 11.3 Pilot 不计入晋级

Pilot 不能计入：

```text
positive
boundary
negative
regression_verified
competition_evidenced
```

Pilot 只用于校准：

```text
规则
Schema
Validator
容差
执行说明
```

Pilot 完成并修订后，再冻结确认性实验协议。

---

# 12. 确认性实验协议冻结

正式 Treatment 之前保存：

```json
{
  "protocol_commit": "...",
  "patch_sha256": "...",
  "validator_sha256": "...",
  "scoring_rubric_sha256": "...",
  "baseline_config_sha256": "...",
  "treatment_config_sha256": "...",
  "runtime_pack_sha256": "...",
  "case_role_manifest_sha256": "..."
}
```

正式实验后不得修改：

- 题目角色；
- 评分权重；
- 晋级门槛；
- Validator 核心公式；
- 容差；
- A092 七条规则；
- 敏感性阈值；
- 最优性派生规则。

若必须修改，记录：

```json
{
  "protocol_deviation": true,
  "reason": "...",
  "affected_runs": [],
  "rerun_required": true
}
```

受影响实验必须重新运行。

---

# 13. 三类题角色选择

## 13.1 正向题

2024-C 可作为候选正向题。

正向题应明显包含：

- 工程机制；
- 可计算评价器；
- 设计变量；
- 现实约束；
- 方案优化；
- 可独立复算的结果。

预期 A092 大部分规则触发。

---

## 13.2 边界题

不直接写死 2023-B。

在冻结前必须回答：

```text
是否存在固定评价器？
是否需要完整变量—目标—约束优化链？
A092 七项中预计关闭哪些？
为什么关闭？
```

如果无法明确指出至少两项应关闭或部分关闭，该题不应作为边界题。

边界题应当：

- 部分适合工程优化思路；
- 但不适合完整 A092 链；
- 能检验 Patch 是否会机械化输出。

---

## 13.3 负控题

不能选一个完全不涉及数学或代码的简单题。

困难负控应满足：

```text
仍需要建模
仍需要代码或计算
但不适合“工程评价器—基线—方案优化”完整链
```

负控用于检验：

- A092 是否过度触发；
- 是否强行制造无关评价器；
- 是否增加无关敏感性分析；
- 是否降低原本清晰的解题路线。

---

# 14. Baseline 与 Treatment

## 14.1 控制变量

必须保持一致：

```text
同一 AI 模型
同一模型版本
同一 reasoning effort
同一温度和随机设置
同一题面和附件
同一工具权限
同一代码执行权限
同一时间限制
同一迭代次数
同一人工确认策略
同一 Gate 规则
同一论文页数限制
同一摘要字数限制
同一图表数量上限
```

唯一主要差异：

```text
Baseline：
base + optimization plugin

Treatment：
base + optimization plugin + A092
```

不得让 Treatment 获得：

- 更多人工提示；
- 更多错误反馈；
- 更多执行时间；
- 更多修改次数；
- Baseline 没有的参考材料。

---

# 15. 最低限度重复实验

单次运行不足以证明稳定提升。

采用两阶段策略控制成本。

## 15.1 第一阶段筛查

每题先运行一对：

```text
Baseline 1
Treatment 1
```

如果出现以下任一情况，直接停止该题进一步重复：

- Treatment 出现 Solution P0；
- Treatment 明显错误触发；
- 总分显著下降；
- Validator 无法运行；
- 实验条件失效。

## 15.2 第二阶段确认

满足初步门槛的正向题和边界题补第二对：

```text
Baseline 2
Treatment 2
```

负控题至少一对；成本允许时补第二对。

## 15.3 顺序随机化

避免固定 Baseline 总在前。

可使用：

```text
Case A：
Baseline 1
Treatment 1
Treatment 2
Baseline 2
```

或提前随机生成顺序。

每次运行必须使用：

- 全新上下文；
- 全新 run_id；
- 不读取上一轮模型路线；
- 不读取上一轮代码；
- 不读取上一轮论文；
- 不把人工熟悉后的额外信息传给后运行版本。

## 15.4 判断依据

不看最好一次，重点观察：

1. 两组提升方向是否一致；
2. 关键行为是否重复出现；
3. 是否新增 Solution P0；
4. 提升是否主要来自模型与验证；
5. 是否只是篇幅或语言波动。

---

# 16. Gate 0–5 产物

## Gate 0：题目与材料诊断

对比：

- 每问目标；
- 输入输出；
- 题型判断；
- 数据需求；
- 候选路线；
- 最大风险；
- A092 是否过早触发。

产物：

```text
diagnosis.md
diagnosis.json
material_inventory.json
```

## Gate 1：模型路线

对比：

- 机理是否合理；
- 变量是否完整；
- 目标是否正确；
- 约束是否遗漏；
- 单位是否一致；
- 是否有基线；
- 是否有验证路线。

产物：

```text
model_route.md
model_spec.json
variable_table.json
constraint_table.json
```

## Gate 2：代码计划

对比：

- 固定评价器；
- Baseline；
- 优化器；
- 独立复算；
- 随机性；
- 失败降级。

产物：

```text
implementation_plan.md
experiment_config.json
validation_plan.json
```

## Gate 3：结果确认

对比：

- 目标值复算；
- 约束残差；
- 基线改进；
- 敏感性；
- 图表一致性；
- 最优性声明。

产物：

```text
result_summary.json
validator_result.json
sensitivity_results.json
figures/
tables/
```

## Gate 4：论文确认

对比：

- 写入论文的结果是否已验证；
- 定量结论是否有证据；
- 是否区分可行、较优和最优；
- 是否报告局限；
- 是否只增加空泛语言。

产物：

```text
paper_claim_map.json
paper_draft.md
paper_evidence_check.json
```

## Gate 5：最终验收

对比：

- 是否存在核心模型错误；
- 是否可复算；
- 摘要是否突出方法和结果；
- 图表是否服务于结论；
- 是否夸大；
- 是否存在证据断裂。

产物：

```text
final_review.json
solution_failures.json
experiment_validity.json
score_sheet.json
```

---

# 17. 评分表

| 维度 | 分值 | 核心检查 |
|---|---:|---|
| 题意与问题拆解 | 10 | 每问目标、输入输出和依赖关系 |
| 假设与机理 | 10 | 假设必要性、现实机理和量纲 |
| 模型设计 | 20 | 变量、目标、约束和公式 |
| 求解策略 | 10 | 算法匹配、基线和降级方案 |
| 代码与数值结果 | 15 | 可运行、可复算、结果一致 |
| 独立验证 | 15 | 目标、约束、敏感性和误差 |
| 论文与图表 | 15 | 摘要、结构、图表和结果解释 |
| 结论边界 | 5 | 不夸大，诚实报告限制 |
| **总分** | **100** | |

论文中没有以下证据支持的结论，不计入论文加分：

```text
结果文件
图表
代码输出
Validator 记录
```

关键定量结论与结果冲突时，按 Solution P0 处理。

---

# 18. Solution P0 与 Experiment Invalid 分离

## 18.1 Solution P0

### P0-A：核心数学错误

包括：

- 核心机理错误；
- 关键公式错误；
- 目标方向错误；
- 变量含义错误；
- 关键约束遗漏；
- 数据泄漏；
- 错误模型导致结论失效。

### P0-B：结果不可复算或不可行

包括：

- 关键目标值无法独立复算；
- 最终方案违反关键约束；
- 论文数值与代码结果冲突；
- 关键结果文件缺失；
- 用 solver success 代替可行性验证。

处理：

```text
出现 P0-A 或 P0-B：
Treatment 不能判优；
该次运行可保留为失败证据；
不得作为正向晋级证据。
```

---

## 18.2 Experiment Invalid

### E1：Baseline/Treatment 条件不公平

例如：

- Treatment 获得更多提示；
- Treatment 获得更多时间；
- Treatment 得到 Baseline 没有的结果或答案。

### E2：协议事后修改

例如：

- 修改题目角色；
- 修改评分权重；
- 修改晋级门槛；
- 修改 Validator 公式而不重跑。

### E3：盲化泄露

例如：

- 评审者提前知道 X/Y 身份；
- 论文中保留明显的 Treatment 标签；
- 评分提示泄露预期结果。

### E4：输入或评分证据缺失

例如：

- 缺少模型配置；
- 缺少运行记录；
- 缺少评分依据；
- 无法确认比较的是同一题面。

处理：

```text
出现 E1–E4：
本轮实验整体无效；
不得作为晋级证据；
修复问题后重新运行。
```

---

# 19. 晋级门槛

## 19.1 正向题

必须满足：

```text
无 Solution P0
无 Experiment Invalid
至少完成两对配对运行
两对主要提升方向一致
每对总分原则上提升 >= 5
模型设计 + 独立验证合计提升 >= 3
目标函数可独立复算
关键约束可独立重算
优化结果确实优于冻结基线
新增论文结论均有证据
```

若一对提高 5 分、另一对提高 4 分，但关键行为稳定复现，可进入人工复核，不自动失败。

至少重复出现两个有效行为改善：

- 补上关键机理损失项；
- 补上关键约束；
- 固定评价器更可靠；
- 发现目标值不一致；
- 增加有效基线；
- 降级错误最优声明；
- 通过敏感性修正不稳健结论。

---

## 19.2 边界题

必须满足：

```text
无 Solution P0
无 Experiment Invalid
至少完成两对配对运行
模型设计不得出现稳定下降
代码与结果不得出现稳定下降
独立验证不得出现稳定下降
能关闭至少两个不适用或部分适用模块
不为补齐产物虚构内容
平均分变化 >= -2
```

边界题不强制提高 5 分。

---

## 19.3 负控题

必须满足：

```text
无 Solution P0
无 Experiment Invalid
不错误进入完整工程优化链
不制造无关评价器
不强行敏感性分析
不增加明显无关篇幅
不引入额外数学错误
分数变化接近 0
```

建议：

```text
-2 <= Treatment - Baseline <= 2
```

---

## 19.4 总体条件

只有同时满足：

```text
正向题通过
边界题通过
负控题通过
无未处理的 Experiment Invalid
增益来自可检查行为
增益可重复
增益不是单纯篇幅增加
```

才建议人工改为：

```text
regression_verified
```

否则：

```text
继续 review_ready
记录失败原因
修订 A092
重新进行 Pilot 或重新预注册
```

---

# 20. 盲化评审

## 20.1 数学评审包

包含：

```text
模型定义
公式
变量与约束
代码结果
Validator 输出
核心图表
敏感性结果
```

随机标记：

```text
方案 X
方案 Y
```

## 20.2 论文评审包

统一：

```text
论文模板
页数上限
摘要字数
正文篇幅
图表数量上限
附录规则
引用规则
```

不给评审者：

- Patch 身份；
- 晋级门槛；
- Treatment 预期改善点；
- Baseline/Treatment 标签。

## 20.3 防止通过篇幅识别

Baseline 和 Treatment 必须使用相同：

- 页数限制；
- 图表数量；
- 摘要字数；
- 章节模板；
- 附录限制。

Treatment 不能仅靠更长内容获得论文优势。

---

# 21. 论文输出规则

## 21.1 摘要

必须包含：

```text
问题对象
主要模型
求解方法
关键结果
基线改进
约束或误差验证
敏感性结论
主要限制
```

禁止只写：

```text
建立多个模型
取得良好效果
具有参考价值
```

## 21.2 结果章节

每个关键结果按：

```text
结果数值
→
基线比较
→
约束或误差检查
→
现实含义
→
敏感性或稳定性
→
结论边界
```

## 21.3 Claim Map

```json
{
  "claim_id": "C-RESULT-001",
  "claim": "优化方案相较基线提高 6.32%",
  "source_result": "results/summary.json",
  "source_fields": [
    "baseline_objective",
    "optimized_objective"
  ],
  "validator_record": "validator/result.json",
  "figure_or_table": "table_4_2",
  "paper_location": "section_4_2",
  "supported": true
}
```

## 21.4 最优性表述

| 证据 | 允许表述 |
|---|---|
| 严格数学证明 | 全局最优 |
| 完整模型 + 合法求解器证书 | 求解器认证最优 |
| 完整有限空间穷举 | 搜索空间内最优 |
| 多次启发式最好结果 | 当前搜索中最好可行方案 |
| 仅找到改进解 | 改进的可行方案 |
| 未完成独立检查 | 候选方案 |

---

# 22. 文件拆分

本计划只作为设计说明，不直接完整注入执行 AI。

建议拆为：

```text
docs/roadmap/MODELING_QUALITY_PHASE1.md
    背景、原则、阶段路线、解释和验收。

protocols/a092_experiment_protocol.json
    题目角色、模型配置、运行次数、阈值、容差、冻结哈希。

prompt_patches/patch_A092_engineering_optimization.md
    只保留 A092 七条短规则和启用/关闭条件。

schemas/
    保存机器产物合同。

validators/
    保存目标、约束、敏感性和最优性验证代码。
```

真正提供给 Baseline/Treatment 的上下文不应包含：

```text
晋级门槛
评分者偏好
Treatment 预期改善点
Baseline/Treatment 历史对比
哪些行为会得到额外分数
```

避免模型主动迎合实验。

---

# 23. 执行 AI 的阶段任务

## 阶段一任务

```text
读取本计划的阶段一。
只修复 CLI 完整 scope 输出和输出链接检查。
运行全部相关测试。
生成变更摘要。
提交并通过 SSH 推送。
不要扩展其他安全功能。
```

## 阶段二任务

```text
读取本计划的阶段二。
补全 A092 论文证据。
删除与 optimization plugin 重复的内容。
将 A092 压缩为七条增量行为。
实现 Validator v0 和题目适配器接口。
设计并运行非晋级 Pilot。
根据 Pilot 修正规则、Schema、容差和输出。
冻结确认性实验协议。
保持 A092.status = review_ready。
提交并通过 SSH 推送。
```

## 阶段三任务

```text
读取冻结后的实验协议。
不得修改题目角色、评分、阈值和 Validator 公式。
重新运行三类题的 Baseline/Treatment。
执行最低限度配对重复。
完成 Gate 0–5。
独立重算目标和约束。
生成统一篇幅论文和 Claim Map。
进行盲化评分。
区分 Solution P0 与 Experiment Invalid。
根据冻结规则决定晋级或继续 review_ready。
提交全部实验记录并通过 SSH 推送。
```

---

# 24. 阶段完成标准

成功结果：

```text
A092 在正向题上可重复提高建模和验证质量；
在边界题上能够主动关闭不适用模块；
在困难负控上不会错误触发；
提升来自真实数学行为和结果证据；
因此达到 regression_verified。
```

失败但有效的结果：

```text
A092 未达到晋级门槛；
已明确与 plugin 重复、错误触发或无稳定增益的规则；
保留 review_ready；
形成下一轮修订和实验计划。
```

两种结果都有效。

本阶段不允许为了得到“成功晋级”而修改实验规则。

---

# 25. 最终检查清单

## 阶段一

- [ ] CLI 输出完整 trusted_local scope；
- [ ] symlink 输出被拒绝；
- [ ] junction 输出被拒绝；
- [ ] hardlink 输出被拒绝；
- [ ] 原有合法结果不变；
- [ ] 提交并 SSH 推送；
- [ ] 安全主线冻结。

## 阶段二

- [ ] A092 论文证据补全；
- [ ] 删除 plugin 重复内容；
- [ ] 固定七条增量行为；
- [ ] 数值口径明确；
- [ ] 容差明确；
- [ ] 敏感性支持关闭；
- [ ] 实现 Validator v0；
- [ ] Pilot 包含故障注入；
- [ ] Pilot 不计晋级；
- [ ] 根据 Pilot 修订；
- [ ] 正式题目角色冻结；
- [ ] 运行次数冻结；
- [ ] 评分和阈值冻结；
- [ ] A092 保持 review_ready；
- [ ] 提交并 SSH 推送。

## 阶段三

- [ ] 每题先完成一对筛查；
- [ ] 正向和边界补第二对；
- [ ] 运行顺序随机化或交错；
- [ ] 全部使用新上下文；
- [ ] 完成 Gate 0–5；
- [ ] 目标函数独立复算；
- [ ] 约束按容差检查；
- [ ] 敏感性按适用性执行；
- [ ] 论文结论全部绑定证据；
- [ ] 完成盲化评分；
- [ ] 区分 Solution P0 与 Experiment Invalid；
- [ ] 按冻结规则作出状态决定；
- [ ] 提交并 SSH 推送。

---

# 26. 最终原则

必须始终守住：

1. A092 必须产生可观察、可重复、可机器检查的行为差异；
2. 先做 Pilot，再冻结确认性协议；
3. 正式实验规则必须先于 Treatment 固定；
4. 实验允许失败；
5. 敏感性分析按题目适用性开启，不机械凑三个参数；
6. 浮点约束按容差判断，不要求严格等于零；
7. 数学错误与实验无效必须分开记录；
8. 单次高分不能证明稳定增益；
9. 论文得分必须建立在真实、可复算结果上；
10. 求解器 success 不等于方案可行；
11. 启发式最好结果不等于全局最优；
12. 完整设计说明不应全部注入执行 AI；
13. 安全工程不得再次挤占建模与论文主线。

本阶段真正要回答的是：

> **A092 的增益是否可重复，是否来自数学建模和结果验证能力，而不是随机波动、篇幅增加或对评分规则的迎合。**
