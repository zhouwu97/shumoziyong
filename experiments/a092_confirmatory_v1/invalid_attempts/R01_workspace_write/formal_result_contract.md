# A092 确认性实验正式结果合同 v1

本合同对 Baseline 与 Treatment 完全相同，只定义可独立复算的最小数值接口，不包含评分权重、晋级门槛或 Treatment 预期改善点。

## 2024-C 全题

必须输出 `results/formal_result.json`：

```json
{
  "scenarios": [
    {
      "scenario_id": "q1_waste",
      "objective_reported": 0.0,
      "assignments": [
        {"year": 2024, "plot_id": "A1", "season": "单季", "crop_id": 1, "area_mu": 80.0}
      ]
    }
  ]
}
```

四个 `scenario_id` 固定为：`q1_waste`、`q1_discount`、`q2_frozen`、`q3_frozen`。每个场景必须覆盖 2024–2030 年，并使用官方地块、季次、作物编号和亩数。

冻结复算口径：

- 2023 预期销售量按附件 2 的实际种植面积乘对应亩产量汇总；销售价格取区间中点。
- `q1_waste` 超产收入为 0；`q1_discount` 超产按正常价格 50% 计。
- `q2_frozen` 与 `q3_frozen`：小麦、玉米销售量每年增长 7.5%；亩产按基准 95%；成本每年增长 5%；蔬菜价格每年增长 5%；羊肚菌价格每年下降 5%；其他食用菌每年下降 3%；其他边际量保持基准。
- `q3_frozen` 的相关性/风险结论必须另附模拟数据和证据；固定评价器只复算共同的期望利润边际口径。
- 必查约束：适宜性、各季地块容量、水浇地单季/双季占地冲突、相邻年份重茬、含 2023 基准在内的每个滚动三年豆类覆盖。

## 2023-B 问题一、二

必须输出 `results/formal_result.json`，包含：

```json
{
  "q1": {"depth_m": [], "coverage_width_m": [], "overlap_ratio": []},
  "q2": {"rows": [{"beta_deg": 0, "coverage_width_m": []}]}
}
```

数组顺序必须与题面表 1、表 2 一致。问题一、二没有方案优化目标，不得制造基线改进率、优化器或全局最优声明。

## 2016-C 全题

必须输出 `results/formal_result.json`：

```json
{
  "curve_checks": [
    {"curve_id": "20A", "actual_time": [], "predicted_time": [], "mre_reported": 0.0}
  ],
  "remaining_time_predictions": [
    {"case_id": "30A_9.8V", "remaining_minutes": 0.0}
  ]
}
```

`actual_time` 与 `predicted_time` 必须是用于 MRE 的同一批采样点。剩余时间必须非负并绑定模型/数据来源。本题是拟合预测题，不得进入完整工程优化链。
