# 无效负控运行

本组确实由两个独立 Codex 任务生成，但初始化时未正确设置 `$files`，
导致 problem_manifest.json 收录整个 2024 材料目录，包括其他题目及附件。

由于运行提示允许读取 problem_manifest 中列出的所有文件，本组无法证明材料隔离，
不得用于 A127 晋级证据。

结论：
- 模型行为仅供参考；
- evidence_validity 保持 pending；
- eligible_for_promotion 保持 false；
- 不写入 patch_negative_control_matrix.json。
