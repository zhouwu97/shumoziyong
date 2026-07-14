# 2024-C 模型定义（公开合同对齐版）

令 `x_{p,c,t,s}>=0` 为种植面积，`z_{p,c,t,s}` 为活动二元变量，`m_{p,t}` 为水浇地单季水稻/两季蔬菜模式，`q_{c,t,s}>=0` 为作物--季次正常销售量。面积为连续变量，`z,m` 为二元变量。

目标是最大化正常销售收入、超额销售收入（仅 Q1 半价方案取 50%）减种植成本，并以 `0.01 sum(z)` 作二级并列排序。设 `R_{c,t,s}=sum_p Y_{c,l(p),s}x_{p,c,t,s}`，则 `q<=R`、`q<=D_{c,t,s}`；正式目标由导出的 `x` 独立重算，不采用求解器目标值。

| 约束 | 数学口径 | 实现 | 独立检查 |
| --- | --- | --- | --- |
| C01 容量 | `sum_c x_{p,c,t,s}<=A_p` | `build_model.py` | `check_land_capacity` |
| C02 适种/水浇地 | 不适配 `x=0`；水稻与两季蔬菜模式互斥 | `eligible_crops`、模式变量 | `check_crop_land_compatibility`、`check_water_mode` |
| C03 重茬 | 相邻合同季次同作物 `z_i+z_j<=1` | `_adjacent_pairs`、历史边界行 | `check_continuous_crop`、`check_2023_to_2024_boundary` |
| C04 豆类 | 每地块每滚动三年窗口豆类面积 `>=A_p` | 六个窗口下界 | `check_three_year_legume_windows` |
| C05 销售 | `q_{c,t,s}<=R_{c,t,s},D_{c,t,s}` | 跨地块类型销售组 | `recompute_objective`、`check_sales_limit` |
| C06 非负/离散 | `x,q>=0;z,m∈{0,1}` | 下界与 integrality | `check_integrality_and_nonnegative` |

Q1 使用 2023 基线参数。`q2_frozen`、`q3_frozen` 使用公开冻结代表参数；随机 Q2/Q3 只作为补充实验。SciPy/HiGHS 每场景 30 秒，得到可验证可行解，不声明全局最优。
