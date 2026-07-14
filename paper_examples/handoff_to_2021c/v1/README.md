# 2021-C 只读能力包 v1

本目录只向论文 Writer 提供模板示例、样式说明、检查命令和修复建议，不覆盖论文文件。

## 可用组件

- 模板：`paper_templates/cumcm_typst/`
- 样式：`paper_profiles/cumcm_academic_v1.json`
- Claim 合同示例：`paper_examples/claim_bindings.example.json`
- 图表规划示例：`paper_examples/figure_plan.example.json`
- 视觉清单：`paper_checklists/cumcm_visual_acceptance.md`

## 环境

- Typst：建议 `0.15.0` 或更高版本；Windows 可运行 `winget install Typst.Typst`。
- PDF 页面导出：优先使用 `pdftoppm`，不可用时回退到 PyMuPDF。
- PDF 元数据与空白页检查：需要 PyMuPDF；图片尺寸记录可选用 Pillow。

## 建议检查命令

```powershell
python scripts/paper/check_claim_bindings.py --bindings <claim_bindings.json> --paper <main.typ> --project-root <项目根目录> --output <paper_claim_check.json>
python scripts/paper/check_paper_source.py --main <main.typ> --output <paper_source_check.json>
python scripts/paper/check_pdf_metadata.py <paper.pdf> --pages-dir <页面 PNG 目录> --output <pdf_metadata_check.json>
python scripts/paper/rasterize_pdf.py <paper.pdf> <页面 PNG 目录> --output <rasterize_report.json>
```

检查器只生成报告。数字冲突、公式问题和图片问题必须回到原始结果或论文源文件人工修复。
