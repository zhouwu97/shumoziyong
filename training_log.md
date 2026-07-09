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
| 2026-07-02 | 2023-B 多波束测线问题官方泛化测试 | prompt_base_v1.0 + plugin_optimization_v1 + patch_A092_engineering_optimization + patch_A127_engineering_layout_optimization | 98 | 无 | T3 | 否，候选证据 | 作为第 1 道官方 T3 通过记录 |
| 2026-07-05 | 2024-C 农作物种植策略官方泛化测试 | prompt_base_v1.0 + plugin_optimization_v1 + patch_A092_engineering_optimization + patch_A127_engineering_layout_optimization | 96 | 无 | T3 | 否，候选证据 | 可作为第 2 道官方 T3 候选，等待后续链路验证 |
| 2026-07-08 | runtime_pack Gate 0 冒烟测试：2024-C 农作物种植策略 | export/cumcm_runtime_pack.md + gate_0_problem_diagnosis |  | 未触发代码/论文 | smoke | 否 | Gate 0 控制有效，仅记录运行包可控性 |
| 2026-07-08 | runtime_pack Gate 1 dry-run：2024-C 农作物种植策略 | export/cumcm_runtime_pack.md + gate_1_before_modeling |  | 未触发代码/论文/最终方案 | dry-run | 否 | Gate 1 能先核验字段、定义变量和约束；未进入 Gate 2 |
| 2026-07-08 | runtime_pack Gate 2 dry-run：2024-C 农作物种植策略 | export/cumcm_runtime_pack.md + gate_2_before_coding |  | 未触发完整代码/优化器/最终方案 | dry-run | 否 | Gate 2 能先设计数据结构、约束检查和基准方案；未进入完整代码实现 |
| 2026-07-08 | 2024-C 代码小样例验证 | runtime_pack Gate 2.5 + code mini-run |  | 未触发完整优化器/最终方案/论文 | mini-run | 否 | 读取、集合、约束检查和基准方案通过；不计入 stable |
| 2026-07-08 | 2024-C 简单优化器验证 | runtime_pack Gate 2.6 + bounded greedy local replacement |  | 未触发复杂优化器/全局最优声明/论文 | dry-run | 否 | 基准收益 16250142.79，改进收益 17276602.82，约束违规为 0；不计入 stable |
| 2026-07-08 | 2024-C 不确定性情景验证 | runtime_pack Gate 2.7 + scenario analysis |  | 未触发重新优化/最终答案/论文 | dry-run | 否 | base/pessimistic/optimistic/mixed 四情景均重新检查约束，违规为 0；不计入 stable |
| 2026-07-08 | 2024-C 结果报告生成 | runtime_pack Gate 3 + RESULTS_REPORT.md |  | 未触发论文正文/摘要/最终最优声明 | dry-run | 否 | 结果证据包可追溯，明确 smoke-test 边界和人工确认项；不计入 stable |
| 2026-07-08 | 2024-C 论文写作测试 | runtime_pack Gate 4 + draft_gate4.md |  | 未触发终稿验收/正式最优声明/stable 标记 | dry-run | 否 | Gate 4 paper draft dry-run pass；测试版论文受 RESULTS_REPORT.md 约束 |
| 2026-07-08 | 2024-C 终稿验收测试 | runtime_pack Gate 5 + FINAL_REVIEW_REPORT.md |  | pass；未触发重写论文/新增结果/stable 标记 | dry-run | 否 | 2024-C full smoke chain pass；只验证 smoke chain 论文验收，不计入 stable |
| 2026-07-08 | 2023-B Gate 0-2 跨题泛化测试 | export/cumcm_runtime_pack.md + engineering_optimization_runtime + gate_0/1/2 |  | pass；未触发代码/论文/最终测线方案 | cross-problem | 否 | 2023-B Gate 0-2 cross-problem generalization pass；可进入 Gate 2.5 小样例，仍不得标记 stable |
| 2026-07-08 | 2023-B Gate 2.5 代码小样例验证 | export/cumcm_runtime_pack.md + runtime_cross_2023B_gate0_2.md + code mini-run |  | pass；未触发最终测线方案/论文/完整优化器 | mini-run | 否 | 2023-B Gate 2.5 code mini-run pass；下一步只考虑 Gate 2.6 方向角粗网格搜索 |
| 2026-07-08 | 2023-B Gate 2.6 方向角粗网格搜索 | export/cumcm_runtime_pack.md + examples/2023B_gate2_5 + direction_grid_search |  | pass；未触发最终测线方案/论文/完整优化器/全局最优声明 | smoke | 否 | 2023-B Gate 2.6 direction grid search pass；下一步可进入 Gate 3 结果报告 |
| 2026-07-08 | 2023-B Gate 3 结果证据报告 | Gate 2.5/2.6 reports + RESULTS_REPORT_2023B.md |  | pass；未新增实验结果/未写论文/未输出最终测线方案 | dry-run | 否 | 2023-B Gate 3 results report pass；下一步可进入 Gate 4 论文草稿测试 |
| 2026-07-08 | 2023-B Gate 4 论文草稿测试 | RESULTS_REPORT_2023B.md + draft_gate4_2023B.md |  | pass；未编造新增数值/未输出最终测线方案/未声明最优方向 | dry-run | 否 | 2023-B Gate 4 paper draft dry-run pass；下一步可进入 Gate 5 终稿验收测试 |
| 2026-07-08 | 2023-B Gate 5 终稿验收测试 | draft_gate4_2023B.md + FINAL_REVIEW_REPORT_2023B.md |  | pass；未重写论文/未新增结果/未标 stable | dry-run | 否 | 2023-B full smoke chain pass；工程优化 runtime 升级为 candidate+，仍需新机制题验证后才考虑 stable candidate |
| 2026-07-08 | 2024-B Gate 0-2 第三类机制泛化测试 | official_materials/2024_B + export/cumcm_runtime_pack.md + engineering_optimization_runtime |  | pass；未触发代码/论文/最终生产决策方案 | cross-problem | 否，stable candidate 证据 | 2024-B Gate 0-2 third-mechanism generalization pass；工程优化 runtime 升级为 stable candidate，仍不得标记 stable |
| 2026-07-08 | B311 论文学习 | 2023_B311_学习卡片 + 知识卡片 + patch_B311_spatial_coverage_optimization |  | 未验证 | 论文学习 | 否 | 等待旧题闭环验证，不修改 base/plugin |
| 2026-07-09 | B311/B477 candidate patch 负控验证：2024-B 生产过程中的决策问题 | default runtime_pack(A092+A127) vs candidate runtime_pack(A092+A127+B311+B477) | 96/96 | 无；M1-M5均无 | T4 | 否，不升级 | candidate 包未误触发空间覆盖/路径搜索经验；无实质提分，B311/B477 保持 candidate，下一步做相似非同题验证 |

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

## 当前工程优化 runtime 状态

2024-C 农作物种植策略已完成 Gate 0-5 full smoke chain pass。2023-B 多波束测线问题已完成 Gate 0-5 full smoke chain pass。2024-B 生产过程中的决策问题已完成 Gate 0-2 third-mechanism generalization pass。三道题机制明显不同：2024-C 是多期农业资源配置和不确定性决策，2023-B 是空间覆盖、几何约束和测线布设优化，2024-B 是生产过程、质量检测、工序决策和成本收益权衡。当前状态为 engineering_optimization runtime stable candidate；该状态不是 stable，仍需更多机制题和正式求解质量验证。

## 稳定版本记录

| 题型 | 稳定版本 | 成熟度 | 通过旧题数量 | 最近测试日期 | 备注 |
|---|---|---|---:|---|---|
| 工程优化 | stable candidate，未 stable | L4 | 3 | 2026-07-08 | 2024-C 与 2023-B full smoke chain pass；2024-B Gate 0-2 第三类机制泛化通过；仍需更多机制题和正式求解质量验证 |
| 预测类 | 待创建 | L1 | 0 |  |  |
| 评价类 | 待创建 | L1 | 0 |  |  |
| 仿真类 | 待创建 | L1 | 0 |  |  |
