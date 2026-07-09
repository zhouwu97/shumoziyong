# 工程优化运行配置

适用题型：

- 工程优化；
- 空间布局；
- 资源配置；
- 路径规划；
- 排班调度；
- 参数优化；
- 方案选择；
- 设计变量优化。

本运行配置必须加载：

1. `prompt_base/prompt_base_v1.0.md`
2. `prompt_plugins/plugin_optimization_v1.md`
3. `prompt_patches/patch_index.json` 中 `runtime_profiles` 包含 `engineering_optimization`，且状态为 `verified_candidate` 或 `stable` 的 patch
4. `checklists/gate_0_problem_diagnosis.md`
5. `checklists/gate_1_before_modeling.md`
6. `checklists/gate_2_before_coding.md`
7. `checklists/gate_3_before_writing.md`
8. `checklists/gate_4_final_review.md`

当前默认导入的工程优化 patch：

1. `prompt_patches/patch_A092_engineering_optimization.md`
2. `prompt_patches/patch_A127_engineering_layout_optimization.md`

`candidate` patch 只允许在旧题闭环测试中显式启用，不进入默认比赛运行包。

硬规则：

1. 先建立评价函数，再转化为优化问题。
2. 先说清楚现实问题到数学问题的转化。
3. 每个优化问题必须写出：
   - 优化对象；
   - 优化目标；
   - 决策变量；
   - 目标函数；
   - 约束条件；
   - 输入数据；
   - 输出方案。
4. 高维变量必须考虑降维：
   - 分区；
   - 分层；
   - 规则化；
   - 参数化；
   - 固定结构后优化参数。
5. 使用智能优化算法前必须说明：
   - 为什么简单方法不可行；
   - 搜索空间多大；
   - 编码方式是什么；
   - 适应度函数是什么；
   - 约束如何处理；
   - 如何重复运行验证稳定性。
6. 结果必须包含：
   - 基准方案；
   - 优化方案；
   - 提升幅度；
   - 约束满足情况；
   - 敏感性分析；
   - 图表解释。

禁止：

1. 只给算法，不给目标函数。
2. 只给结果，不给约束满足情况。
3. 把规则化布局当成必然最优。
4. 用遗传算法、粒子群、模拟退火替代工程机制分析。
5. 照搬 A092/A127 的定日镜公式、同心圆布局、光学效率公式和具体数值。

进入 MathModelAgent 的执行约束：

1. 第一轮只允许生成总控诊断和需要人工确认的路线。
2. 人工确认建模路线后，才允许调用代码和图表阶段。
3. 代码结果必须写入 `results/`，图表必须写入 `figures/`。
4. 论文阶段只能引用 `reports/RESULTS_REPORT.md` 和 `figures/` 中已经确认的结果。
