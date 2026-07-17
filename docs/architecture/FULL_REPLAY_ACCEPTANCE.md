# 完整官方旧题回放准入

`full_replay` 是运行上下文名称，不等于能力已经通过完整旧题回放。历史 PR-7 五题只产生
`integration_fixture_campaign_passed`。真正的 `full_replay_passed` 只能由
`scripts/validate_full_replay_acceptance.py` 派生。

每个回放 case 必须同时提供：

1. 完整官方题面、全部附件、官方输出模板及 SHA-256 闭包；
2. 原题全部子问题和逐题登记的完整输出文件；
3. 从决策变量重新计算目标函数、硬约束、单位、边界、附件、随机样本与种子的题目专用 Validator；
4. 题目到子问题、数学任务、模型公式、求解结果、图表和结论的论文语义映射；
5. 含题目专用变量表、推导、目标、约束、算法、检验、结果图、敏感性或误差分析及参考文献的完整 PDF。

候选程序的 `passed`、`feasible` 或有限数值不具有 Validator 权限。当前五题 Validator 均为
`scaffold_fail_closed`，所以当前完整回放晋级有意不可达。实现并冻结每题独立复算模块、把注册状态改为
`active`、完成真实回放后，才可能生成通过报告。
