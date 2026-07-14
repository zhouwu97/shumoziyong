# Codex A092 Treatment 诊断运行（2024-C）

本目录仅保存 2026-07-14 Codex Treatment 诊断运行的最小证据。该运行不属于 `A092-CONFIRMATORY-V4`，不与 Claude R01 Baseline 配对，也不计入 v4 的有效样本数或 A092 推广判断。

诊断结果显示：4/4 个目标函数可由冻结外部验证器复算，最大绝对误差为 `4.172325134277344e-7`；但硬约束门禁未通过，共有 5 个 `2023_to_2024_continuous_crop` 违规。因此候选被拒绝，所有定量声明权限均为 false，A092 不推广。

完整运行包仅保留在本地 `tmp/a092_codex_diagnostic_20260714/R02`。`diagnostic_manifest.json` 记录了完整包的规范树 SHA-256；规范化方式为：逐文件计算 SHA-256，按 POSIX 相对路径排序，形成 `sha256 + 两个空格 + 相对路径 + LF` 的 UTF-8 文本后再次计算 SHA-256。
