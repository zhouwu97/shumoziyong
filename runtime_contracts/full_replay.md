# 旧题完整回放运行契约

本运行包用于已完成材料登记的旧题完整回放。执行代理只能依据已编译的运行包和冻结材料工作，不得继续读取仓库中的相对路径、历史提示词或未编译文件。

1. 旧题回放必须完成 Gate 0-5、自动评估、人工审核和失败复盘，才能形成训练审查或控制实验材料。
2. 轻量 `prompt_regression` 只能验证提示词行为，不能冒充本完整回放，也不能产生 Gate 0-5 证据。
3. Patch 晋级必须遵守显式 Policy，并基于真实、可复核的对照证据；运行包本身不授予晋级资格。
4. Candidate Patch 和 Patch 排除仅可用于已获 Policy 许可的旧题对照实验，绝不用于正式比赛。
5. 材料、运行包、运行身份、Gate 产物、Evidence Manifest 或 Seal 不一致时立即停止。

## Review-ready Competition Production

当运行包显式包含 `competition_production_v1` 时，Gate 路由固定为：Gate 0 → advisory-only Adapter →
Gate 1 `model_route_v3` → Gate 2 三个隔离子 Run → Gate 3 三份 Formal Result、比较、可执行性与风险证据 →
`score_v3`。该链只用于旧题 `full_replay` 审查，不得据此进入新题默认包。
