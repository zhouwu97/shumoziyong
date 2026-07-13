# A092 建模质量阶段二实施总结

## 1. 执行边界

本次只实施 `MODELING_QUALITY_PHASE1_REVISED.md` 的阶段二：A092 证据与操作化、Validator v0、非晋级 Pilot、Pilot 后校准和确认性实验协议冻结。未运行阶段三的正式 Baseline/Treatment，未作晋级判断，也未扩展安全与供应链功能。

阶段结束状态保持：

```json
{
  "patch_id": "A092",
  "status": "review_ready"
}
```

## 2. 已完成内容

### 2.1 A092 原论文证据

对本地 A092 原论文 PDF 进行了逐页文本抽取，并对第 3、15、20、23、25、26、28 页进行了渲染核验。知识卡新增 7 条 Claim，分别记录原始做法、可迁移机制、适用/关闭条件、A092 规则和机器产物。

证据支持的主要路线是：先建立光学效率与输出功率评价模型，再进入约束优化；使用统一指标比较候选；通过结构参数化降低维度；用基准与候选对比解释改进。

论文第 26 页以 100 组随机可行解对照支撑“最优解”表述，证据强度不足。阶段二没有继承该强结论，而是将其转化为 R5 约束独立检查和 R7 最优性声明降级的误用防线。

### 2.2 A092 七条增量规则

Patch 已删除与 `plugin_optimization_v1` 重复的目标、变量、约束、算法选择和一般降维说明，仅保留：

1. 机制损失链；
2. 固定方案评价器；
3. 简单可复算基线；
4. 目标独立复算；
5. 变量域、整数性和关键约束独立检查；
6. 可关闭、可派生分类的敏感性分析；
7. 最优性声明降级与 Claim Map 绑定。

每条规则均指定机器产物；边界题和负控题允许输出 `not_applicable`，但必须给出原因及对核心结论的影响。

### 2.3 Validator v0

通用薄壳实现了计划规定的七类能力：

- `recompute_objective`；
- `check_variable_bounds`；
- `check_integrality`；
- `check_constraints`；
- `compare_with_baseline`；
- `run_sensitivity_checks`；
- `derive_optimality_claim`。

数学公式保留在题目适配器中。通用层只负责合同、容差、改进率、证据等级和统一输出，不试图构建万能数学平台。

数值口径已经冻结：最大化用 `new-baseline`，最小化用 `baseline-new`；相对改进以 `abs(baseline)` 为分母；近零基线只报告绝对改进；约束按绝对容差或缩放相对容差满足其一判定。

### 2.4 非晋级 Pilot

Pilot 使用人造两产品产能分配小题，明确设置：

```text
promotion_evidence = false
excluded_from_roles = positive, boundary, negative
```

有效样例能够生成 A092 的 8 类最小产物。七类故障注入全部被识别：

| 故障 | 被触发的失败检查 |
|---|---|
| 错误目标值 | `objective_consistent=false` |
| 越界变量 | `bounds_valid=false` |
| 非整数的整数变量 | `integrality_valid=false` |
| 关键约束违反 | `feasible=false` |
| 错误改进率 | `improvement_ratio_consistent=false` |
| 伪造敏感性分类 | `sensitivity_checks_passed=false` |
| 启发式结果宣称全局最优 | `optimality_claim_consistent=false` |

Pilot 后校准项已固化为：浮点约束使用双容差；敏感性分类由数值和结构证据派生；启发式结果最高只能声明 `best_found_in_search`。Pilot 未改变正式题角色、评分权重或晋级门槛。

### 2.5 确认性协议

正式角色冻结为：

- 正向题：2024-C 全题，两对配对运行；
- 边界题：2023-B 问题一、二范围，两对配对运行；该范围有固定评价器但不需要完整优化链，R3、R6 关闭，R5、R7 部分启用；
- 困难负控：2016-C 全题，至少一对配对运行；保留拟合、预测与代码计算，但禁止制造工程评价器—基线—设计变量优化链。

协议同时冻结运行顺序、控制变量、评分权重、晋级阈值、P0/Experiment Invalid 分类、容差、敏感性阈值和最优性规则。Pilot 不得计入任何正式角色或晋级证据。

冻结记录通过确定性脚本绑定 Patch、Validator 通用层、评分表、两组配置、运行合同和题目角色清单。由于 Git 提交哈希不能自包含在同一提交中，冻结记录在阶段二实现提交之后生成，并以该实现提交为 `protocol_commit`。

## 3. 验证结果

阶段二定向门禁：

```text
python -m validators.pilot_case.run_pilot
python -m pytest tests/test_a092_validator.py
python -m pytest tests/test_a092_validator.py tests/test_knowledge_claims.py tests/test_repository_tooling.py
python -m ruff check validators tests/test_a092_validator.py
python -m pyright validators
```

阶段二实现提交前的完整门禁结果：

```text
pytest：368 passed, 10 skipped
validate_repository：47 passed, 0 failed
ruff：All checks passed
pyright：0 errors, 0 warnings
```

冻结绑定已经生成：

```text
protocol_commit: dce82b0cf50d0bd709c8c4cc64550150fb22df1a
protocol_sha256: f99340820f23253cf4c35e9b2f210d865185266ae2bb2ca9a45e579cddacad97
patch_sha256: 8b94788be8a4bd1d48684f6610b4c0ff795c76644015ba78b2b88e9587db6ef1
validator_sha256: ad941d46d2eea4b1407b2a6d8b67bbfd1d34c322be5a3fe30e02f84704328700
```

其余评分表、Baseline/Treatment 配置、运行合同和题目角色哈希见 `protocols/a092/protocol_freeze.json`。冻结后 `protocol_deviation=false`，后续若改变核心规则必须记录偏差并重跑受影响实验。

## 4. 未执行事项

以下内容留给阶段三：正式模型运行、Gate 0–5 全产物、盲化评分、论文对比、Solution P0/Experiment Invalid 实际判定，以及 `regression_verified` 晋级决定。
