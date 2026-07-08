# 数模 AI 训练日志

## 使用规则

每次训练、旧题测试、失败复盘或提示词修改，只记录事实。长篇分析放入 `reviews/failure_cards/`，闭环过程放入 `output/closed_loop/`。

## 训练日志表

| 日期 | 任务 | 使用版本 | 得分 | 失败标签 | 材料等级 | 是否计入 stable | 下一步 |
|---|---|---|---:|---|---|---|---|
| 2026-07-01 | A092 初始化 | prompt_base_v1.0 + plugin_optimization_v1 + patch_A092_engineering_optimization |  |  |  | 否 | 建立 v3 MVP 训练系统 |
| 2026-07-02 | A127 论文学习 | prompt_base_v1.0 + patch_A127_engineering_layout_optimization | 90 | 无 | 论文学习 | 否 | 已生成学习卡片、知识卡片 JSON 和 patch |
| 2026-07-02 | 2023-A165 工程优化旧题材料受限测试 | prompt_base_v1.0 + plugin_optimization_v1 + patch_A092_engineering_optimization | 88 | 无，M1 | T0/T1 | 否 | 保留测试记录，换官方材料重测 |
| 2026-07-02 | 2023-A175 工程优化旧题同题泄漏冒烟测试 | prompt_base_v1.0 + plugin_optimization_v1 + patch_A092_engineering_optimization + patch_A127_engineering_layout_optimization | 90 | 无，M1/M2/M3 | T0/T1 | 否 | 保留测试记录，换跨题官方材料重测 |
| 2026-07-02 | 2023-B226 多波束测线布设流程冒烟测试 | prompt_base_v1.0 + plugin_optimization_v1 + patch_A092_engineering_optimization + patch_A127_engineering_layout_optimization | 92 | 无，M1/M2 | T0 | 否 | 补官方题面、附件和模板后重测 |
| 2026-07-02 | 2023-B 多波束测线问题官方泛化测试 | prompt_base_v1.0 + plugin_optimization_v1 + patch_A092_engineering_optimization + patch_A127_engineering_layout_optimization | 98 | 无 | T3 | 是 | 作为第 1 道官方 T3 通过记录 |
| 2026-07-05 | 2024-C 农作物种植策略官方泛化测试 | prompt_base_v1.0 + plugin_optimization_v1 + patch_A092_engineering_optimization + patch_A127_engineering_layout_optimization | 96 | 无 | T3 | 是 | 可作为第 2 道官方 T3 候选，等待人工确认 stable |
| 2026-07-08 | runtime_pack Gate 0 冒烟测试：2024-C 农作物种植策略 | export/cumcm_runtime_pack.md + gate_0_problem_diagnosis |  | 未触发代码/论文 | smoke | 否 | Gate 0 控制有效，仅记录运行包可控性 |
| 2026-07-08 | runtime_pack Gate 1 dry-run：2024-C 农作物种植策略 | export/cumcm_runtime_pack.md + gate_1_before_modeling |  | 未触发代码/论文/最终方案 | dry-run | 否 | Gate 1 能先核验字段、定义变量和约束；未进入 Gate 2 |
| 2026-07-08 | runtime_pack Gate 2 dry-run：2024-C 农作物种植策略 | export/cumcm_runtime_pack.md + gate_2_before_coding |  | 未触发完整代码/优化器/最终方案 | dry-run | 否 | Gate 2 能先设计数据结构、约束检查和基准方案；未进入完整代码实现 |
| 2026-07-08 | 2024-C 代码小样例验证 | runtime_pack Gate 2.5 + code mini-run |  | 未触发完整优化器/最终方案/论文 | mini-run | 否 | 读取、集合、约束检查和基准方案通过；不计入 stable |

## 标签统计

| 标签 | 出现次数 | 最近一次出现 | 主要原因 | 下一步动作 |
|---|---:|---|---|---|
| P1 | 0 |  |  |  |
| P2 | 0 |  |  |  |
| P3 | 0 |  |  |  |
| P4 | 0 |  |  |  |
| P5 | 0 |  |  |  |
| P6 | 0 |  |  |  |
| P7 | 0 |  |  |  |
| P8 | 0 |  |  |  |
| P9 | 0 |  |  |  |
| P10 | 0 |  |  |  |

## 稳定版本记录

| 题型 | 稳定版本 | 成熟度 | 通过旧题数量 | 最近测试日期 | 备注 |
|---|---|---|---:|---|---|
| 工程优化 | 未稳定，候选待人工确认 | L4 | 2 | 2026-07-05 | 2023-B 与 2024-C 官方 T3 总控诊断通过；未获人工确认前不正式标记 stable |
| 预测类 | 待创建 | L1 | 0 |  |  |
| 评价类 | 待创建 | L1 | 0 |  |  |
| 仿真类 | 待创建 | L1 | 0 |  |  |
