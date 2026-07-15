# 2021-C 只读审查报告示例

## 输入

- 论文源文件：由论文 AI 的 Handoff 提供
- Claim 绑定：由论文 AI 的 Handoff 提供
- PDF：由论文 AI 的 Handoff 提供

## 自动检查

| 检查 | 状态 | 报告 |
| --- | --- | --- |
| Claim 数字绑定 | 待运行 | `paper_claim_check.json` |
| 论文源文件 | 待运行 | `paper_source_check.json` |
| PDF 元数据 | 待运行 | `pdf_metadata_check.json` |
| 页面导出 | 待运行 | `rasterize_report.json` |

## 逐页视觉检查

待 Handoff 到达后按 `paper_checklists/cumcm_visual_acceptance.md` 执行。视觉结论不得由脚本自动标记为通过。

## 修复建议

仅记录建议，不自动修改论文、公式、图表或结果文件。
