# 数模 AI 训练日志

## 使用规则

每次训练、旧题测试、失败复盘或提示词修改，只记录一行。训练日志只追踪事实，不写长篇分析；长篇分析放入 `reviews/failure_cards/`。

## 训练日志表

| 日期 | 论文/旧题 | 使用版本 | 测试模块 | 得分 | 失败标签 | 修改内容 | 是否稳定 |
|---|---|---|---|---:|---|---|---|
| 2026-07-01 | A092 | prompt_base_v1.0 + plugin_optimization_v1 + patch_A092_engineering_optimization | 初始化 |  |  | 建立 v3 MVP 训练系统 | 否 |
| 2026-07-02 | A127 | prompt_base_v1.0 + patch_A127_engineering_layout_optimization | 优秀论文学习 + patch 生成 | 90 | 无 | 生成学习卡片、知识卡片 JSON 和工程布局优化提示词补丁 | 否 |
| 2026-07-02 | 2023-A165 工程优化旧题材料受限测试 | prompt_base_v1.0 + plugin_optimization_v1 + patch_A092_engineering_optimization | 总控诊断 | 88 | 无，材料风险 M1 | 生成旧题测试记录、闭环摘要和重测任务；不修改正式提示词 | 否 |
| 2026-07-02 | 2023-A175 工程优化旧题同题泄漏冒烟测试 | prompt_base_v1.0 + plugin_optimization_v1 + patch_A092_engineering_optimization + patch_A127_engineering_layout_optimization(参考) | 总控诊断 | 90 | 无，材料风险 M1/M2/M3 | 生成旧题测试记录、闭环摘要和跨题泛化重测任务；不修改正式提示词 | 否 |
| 2026-07-02 | 2023-B226 多波束测线布设流程冒烟测试 | prompt_base_v1.0 + plugin_optimization_v1 + patch_A092_engineering_optimization + patch_A127_engineering_layout_optimization(参考) | 总控诊断 | 92 | 无，材料风险 M1/M2 | T0，优秀论文材料且缺官方题面/附件/模板，生成测试记录、闭环摘要和 T3 材料缺口重测任务；不修改正式提示词，不计入 stable | 否 |
| 2026-07-02 | 2023-B 多波束测线问题官方 T3 泛化测试 | prompt_base_v1.0 + plugin_optimization_v1 + patch_A092_engineering_optimization + patch_A127_engineering_layout_optimization(参考) | 总控诊断 | 98 | 无 | T3，官方题面/附件/result1/result2 模板齐全，生成 manifest、候选题排序、测试记录、闭环摘要和第二道 T3 重测任务；不修改正式提示词 | 否 |
| 2026-07-05 | 2024-C 农作物种植策略官方 T3 泛化测试 | prompt_base_v1.0 + plugin_optimization_v1 + patch_A092_engineering_optimization + patch_A127_engineering_layout_optimization(参考) | 总控诊断 | 96 | 无 | T3，官方题面/附件/result1_1/result1_2/result2 模板齐全；可作为第 2 道不同题号 T3 候选，需人工确认 stable；不修改正式提示词 | 否 |

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
| 工程优化 | 未稳定（候选待人工确认） | L4 | 2 | 2026-07-05 | 2023-B 与 2024-C 官方 T3 总控诊断通过 2 道；未获人工确认前不正式标记 stable |
| 预测类 | 待创建 | L1 | 0 |  |  |
| 评价类 | 待创建 | L1 | 0 |  |  |
| 仿真类 | 待创建 | L1 | 0 |  |  |
