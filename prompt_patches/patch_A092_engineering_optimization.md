# patch_A092_engineering_optimization

- 类型：论文经验增量补丁
- 来源论文：2023 年高教社杯 A092《定日镜场的优化设计》
- 适用题型：存在现实机制、固定评价器和可验证约束的工程优化题
- 依赖：`prompt_base_v1.0.md` + `plugin_optimization_v1.md`
- 状态：`review_ready`
- 进入 base：否

## 职责边界

`plugin_optimization_v1` 已负责目标、变量、约束、简单方法优先、算法质疑、降维、基线和敏感性计划。本补丁只增加七项可机器检查的结果可靠性行为，不推荐具体算法，不复述通用优化定义。

不满足固定评价器或工程优化链时，可以逐项关闭；关闭模块必须输出 `status=not_applicable`、原因及其对核心结论的影响，禁止为补齐文件虚构内容。

## 七条增量行为

### A092-R1 机制损失链

对适用题输出“输入 → 转换过程 → 中间状态 → 损失项 → 有效输出”，说明关键量含义、单位和题面或现实来源。不存在可信机制链时关闭本项。

机器产物：`artifacts/a092/mechanism_chain.json`。

### A092-R2 固定方案评价器

优化前实现 `evaluate_solution(solution, problem_data)`。基线、候选、最终方案、目标复算和关键约束必须共用同一口径；结果出现后不得改评价器。

机器产物：`artifacts/a092/evaluation_definition.json`。

### A092-R3 简单可复算基线

复杂搜索前至少计算一个规则、均匀、经验、粗网格、简化规划或随机可行基线，并保存方法、变量、目标与可行性。

机器产物：`artifacts/a092/baseline_result.json`。

### A092-R4 目标独立复算

不得直接把求解器内部目标写入论文；同时输出 `objective_reported`、`objective_recomputed` 和 `objective_difference`。改进率按冻结协议计算，baseline 接近零时只报告绝对改进。

机器产物：`artifacts/a092/validator_result.json`。

### A092-R5 关键约束独立检查

`solver_status=success` 不能代替可行性。将不等式写为 `g_i(x)<=0`、等式写为 `h_j(x)=0`，按冻结的绝对或缩放相对容差输出残差、违反量和满足状态；同时检查变量边界与整数性。

机器产物：`artifacts/a092/validator_result.json`。

### A092-R6 按适用性执行敏感性

只扰动预注册且能解释的关键参数。分类由目标相对变化、方案结构变化和结论反转共同派生；边界题可部分开启，负控题不得强行开启。关闭时说明原因与结论影响。

默认阈值：目标变化绝对值不超过 5% 且结构不变为 `stable`；5%–15% 或局部结构变化为 `moderately_sensitive`；超过 15%、结构改变或结论反转为 `highly_sensitive`。

机器产物：`artifacts/a092/sensitivity_results.json`。

### A092-R7 最优性降级与证据绑定

最优性只允许从验证证据派生：严格证明、合法求解器证书、完整有限空间穷举、启发式搜索、局部求解或仅改进可行解分别对应不同等级。启发式普通 `success` 不得写成全局最优。论文定量结论必须绑定结果字段、Validator 记录及图表/表格位置。

机器产物：`artifacts/a092/optimality_claim.json`、`artifacts/a092/claim_map.json`。

## 启用与关闭

完整启用需要同时存在：可计算评价器、真实设计变量、现实约束、方案改进任务和可独立复算结果。仅有拟合、预测、分类、解释或纯计算任务时，不进入完整工程优化链；仍可只启用与题目确实相关的复算或证据绑定模块。

以下内容不得迁移：定日镜公式、同心圆布局、蒙特卡洛截断效率、论文具体数值与代码结构。
