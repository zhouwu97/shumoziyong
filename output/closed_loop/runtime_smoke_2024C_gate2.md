# Runtime Pack Gate 2 编码前方案检查记录：2024-C 农作物种植策略

测试日期：2026-07-08

## 测试对象

- `E:/AI/数模_runtime_test/2024C_test/problem/C题_extracted_text.txt`
- `E:/AI/数模_runtime_test/2024C_test/problem/manifest.md`
- `E:/AI/数模_runtime_test/2024C_test/rules/runtime_pack.md`
- `output/closed_loop/runtime_smoke_2024C_gate1.md`
- `checklists/gate_2_before_coding.md`

## 测试边界

本轮只执行 Gate 2：编码前方案检查。

禁止：

1. 不写完整求解代码；
2. 不给最终种植方案；
3. 不写论文；
4. 不直接运行优化器。

## 1. 数据文件读取计划

| 输入文件 | 读取方式 | 输出中间表 | 用途 |
|---|---|---|---|
| `attachments/附件1.xlsx` | pandas 读取全部工作表 | `land_df`、`crop_df` | 地块、作物、适宜性和基础约束 |
| `attachments/附件2.xlsx` | pandas 读取全部工作表 | `planting_2023_df`、`stats_2023_df` | 2023 基准、产量、成本、价格参数 |
| `templates/result1_1.xlsx` | openpyxl 只读模板结构 | `template_map_1_1` | 问题 1 情形 1 输出映射 |
| `templates/result1_2.xlsx` | openpyxl 只读模板结构 | `template_map_1_2` | 问题 1 情形 2 输出映射 |
| `templates/result2.xlsx` | openpyxl 只读模板结构 | `template_map_2` | 问题 2 输出映射 |

## 2. Excel 字段映射表

| 源字段 | 标准字段 | 类型 | 清洗规则 |
|---|---|---|---|
| 地块名称 | `land_id` | 字符串 | 去空格，保持 A1/B1/普通大棚等原始编号 |
| 地块类型 | `land_type` | 类别 | 统一为平旱地、梯田、山坡地、水浇地、普通大棚、智慧大棚 |
| 地块面积/亩 | `area_mu` | 数值 | 转浮点，检查是否大于 0 |
| 作物编号 | `crop_id` | 整数 | 作为作物主键 |
| 作物名称 | `crop_name` | 字符串 | 去空格 |
| 作物类型 | `crop_type` | 类别/标签 | 提取粮食、蔬菜、食用菌、豆类等标签 |
| 种植耕地 | `allowed_land_raw` | 字符串 | 处理换行和空值继承，拆成适宜地块类型集合 |
| 种植地块 | `land_id` | 字符串 | 与地块表主键对齐 |
| 种植面积/亩 | `planted_area_mu` | 数值 | 与地块面积做容量校验 |
| 种植季次 | `season` | 类别 | 映射为单季、第一季、第二季 |
| 亩产量/斤 | `yield_jin_per_mu` | 数值 | 按作物、地块类型、季次建索引 |
| 种植成本/(元/亩) | `cost_yuan_per_mu` | 数值 | 按作物、地块类型、季次建索引 |
| 销售单价/(元/斤) | `price_range_yuan_per_jin` | 区间 | 拆为 `price_low`、`price_high`、`price_mid` |

## 3. 数据清洗规则

1. 向下填充附件 1 中作物适宜地块和说明字段的合并单元格语义。
2. 将价格区间字段拆成最低价、最高价和默认代表价。
3. 将作物类型拆为多标签，尤其标记豆类作物。
4. 将地块类型和作物适宜地块做标准枚举映射。
5. 解析模板中的年份工作表、作物列、地块行、第一季/第二季行区。
6. 对 2023 种植面积做地块容量 sanity check。
7. 检查统计参数是否覆盖所有允许的作物-地块类型-季次组合。

## 4. 集合与索引编码方案

- `L = {land_id}`：地块集合，以附件 1 地块名称为主键。
- `C = {crop_id}`：作物集合，以附件 1 作物编号为主键。
- `Y = {2024,...,2030}`：规划年份集合。
- `S = {single, season1, season2}`：季次集合，输出时映射回模板文字。
- `T = {land_type}`：地块类型集合。
- `K`：情景集合，问题 1 使用确定情景，问题 2/3 使用不确定情景。

索引表：

1. `land_index[land_id] -> {land_type, area_mu}`；
2. `crop_index[crop_id] -> {crop_name, crop_type, is_legume}`；
3. `allowed[(land_type, season, crop_id)] -> bool`；
4. `param[(crop_id, land_type, season)] -> yield/cost/price`；
5. `template_cell[(year, season, land_id, crop_name)] -> cell_ref`。

## 5. 决策变量编码方式

Gate 2 只设计编码，不写求解器。

- 连续变量：`x[(year, land_id, season, crop_id)]` 表示面积。
- 二进制变量：`z[(year, land_id, season, crop_id)]` 表示是否种植。
- 汇总变量：`prod[(year, crop_id)]`、`sold[(year, crop_id)]`、`waste[(year, crop_id)]`、`profit[year]`。
- 场景参数：`yield_factor[(year, crop_id, scenario)]`、`price_factor[(year, crop_id, scenario)]`、`demand_factor[(year, crop_id, scenario)]`。

编码原则：

1. 先生成可行组合索引，避免为明显非法组合建变量。
2. 变量命名必须可追溯到年份、地块、季次和作物。
3. 模板输出只接受面积变量，不直接输出收益或中间变量。

## 6. 约束检查函数设计

先写检查函数，再接优化器。

| 函数 | 输入 | 输出 | 检查内容 |
|---|---|---|---|
| `check_area_capacity(plan)` | 方案表、地块表 | 违规清单 | 每地块每季面积不超过容量 |
| `check_allowed_crop(plan)` | 方案表、适宜性矩阵 | 违规清单 | 作物、地块类型和季次是否合法 |
| `check_rotation(plan, planting_2023)` | 方案表、2023 基准 | 违规清单 | 连续重茬 |
| `check_legume_window(plan, planting_2023)` | 方案表、豆类标签 | 违规清单 | 三年内至少一次豆类 |
| `check_min_area(plan)` | 方案表、阈值 | 违规清单 | 单地块作物面积不宜过小 |
| `check_dispersion(plan)` | 方案表、分散度阈值 | 违规清单 | 同一作物种植地不宜太分散 |
| `check_template_coverage(plan)` | 方案表、模板映射 | 违规清单 | 结果能否填入模板 |
| `check_profit_inputs(plan)` | 方案表、参数表 | 缺失清单 | 产量、成本、价格和需求参数是否齐全 |

## 7. 基准可行方案生成方法

基准方案用于验证约束和结果，不追求最优。

1. 从 2023 种植情况出发，复制可行的地块-作物结构。
2. 对连续重茬冲突作物进行同类替换。
3. 对三年豆类约束缺口地块插入适宜豆类作物。
4. 对水浇地、大棚和智慧大棚按季次规则生成基础组合。
5. 每一步调用约束检查函数，直到得到一个可填模板的基础可行方案。
6. 计算基准利润，作为后续优化结果的最低对照线。

## 8. 优化算法候选与取舍

| 候选 | 优点 | 风险 | Gate 2 取舍 |
|---|---|---|---|
| 线性/混合整数规划 | 变量、目标、约束可解释，适合面积分配和逻辑约束 | 变量规模可能较大，部分管理便利性约束需线性化 | 首选候选，但 Gate 2 不直接求解 |
| 分阶段启发式 | 易得到可行解，适合先满足复杂农业规则 | 最优性证明弱 | 适合作为基准方案和降级路线 |
| 情景模拟 + 确定性优化 | 可处理问题 2/3 不确定性 | 需要明确情景生成和相关结构 | 作为 Gate 2 后续方案 |
| 遗传算法/粒子群 | 可处理非线性与复杂约束 | 容易绕开可解释约束，结果不稳定 | 暂不作为第一选择，除非 MIP/启发式失败 |

Gate 2 结论：先设计数据结构、约束检查和基准可行方案，不直接运行优化器。

## 9. 结果校验指标

1. 约束违规数为 0。
2. 所有模板单元格可追溯到 `x[(year, land, season, crop)]`。
3. 每年每作物产量、销量、滞销或折价量可复算。
4. 利润计算单位一致：亩、斤、元/亩、元/斤。
5. 优化方案利润不得低于基准可行方案，除非换取明确的风险下降。
6. 问题 2/3 结果需报告情景均值、波动和最坏情形表现。
7. 输出表不得包含负面积、非法作物、超面积或缺失模板项。

## 10. 是否允许进入代码实现阶段

结论：有条件允许进入代码小样例阶段，不允许直接写完整求解器。

允许的下一步：

1. 写数据读取和字段清洗模块；
2. 写模板映射解析模块；
3. 写约束检查函数；
4. 生成一个基准可行方案小样例；
5. 生成 `reports/GATE2_IMPLEMENTATION_PLAN.md`。

仍禁止：

1. 直接运行完整优化器；
2. 直接输出最终种植方案；
3. 直接进入论文写作。

## 11. 冒烟测试结论

Gate 2 dry-run 能先设计数据结构、字段映射、约束检查、基准方案和结果校验，没有直接写完整代码、没有直接运行优化器、没有给最终种植方案。

状态：记录为 Gate 2 dry-run pass，不计入 stable，仅说明编码前闸门有效。
