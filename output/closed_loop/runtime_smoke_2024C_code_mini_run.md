# Runtime Pack 代码小样例测试记录：2024-C 农作物种植策略

测试日期：2026-07-08

## 测试对象

- `E:/AI/数模_runtime_test/2024C_test/rules/runtime_pack.md`
- `output/closed_loop/runtime_smoke_2024C_gate2.md`
- `E:/AI/数模_runtime_test/2024C_test/code/load_data.py`
- `E:/AI/数模_runtime_test/2024C_test/code/build_sets.py`
- `E:/AI/数模_runtime_test/2024C_test/code/check_constraints.py`
- `E:/AI/数模_runtime_test/2024C_test/code/baseline_plan.py`

## 检查项

| 检查项 | 结果 |
|---|---|
| 是否正确读取附件字段 | 通过 |
| 是否建立集合索引 | 通过 |
| 是否实现约束检查函数 | 通过 |
| 是否生成基准可行方案 | 通过 |
| 是否直接写完整优化器 | 未触发 |
| 是否运行遗传算法、粒子群、模拟退火 | 未触发 |
| 是否输出最终方案 | 未触发 |
| 是否写论文 | 未触发 |

## 运行结果

| 产物 | 结果 |
|---|---|
| `schema_summary.json` | 已生成，关键字段未缺失 |
| `land_index.csv` | 54 个地块 |
| `crop_index.csv` | 41 个有效作物 |
| `allowed_matrix.csv` | 1062 个可行地块-作物-季次组合 |
| `baseline_plan.csv` | 574 行基准方案 |
| `constraint_check_summary.json` | 面积容量、适宜性、三年豆类、连续重茬、最小面积违规数均为 0 |

## 中途发现的问题

1. 作物表存在空编号和说明行，初版集合构建失败；已在小样例脚本中改为只保留有效数字作物编号。
2. 初版基准方案混用了水浇地单季水稻和两季蔬菜模式，连续重茬检查暴露 48 条违规；已改为水浇地基准方案使用两季蔬菜模式。
3. 为避免伪通过，约束检查补充连续重茬检查。

## 结论

Gate 2.5 code mini-run pass。

本轮只验证读取、集合、约束和基准方案代码骨架，不验证最终优化器，不输出最终种植方案，不写论文，不计入 stable。
