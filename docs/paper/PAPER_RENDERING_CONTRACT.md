# 提交论文渲染合同

## 目的

本合同区分比赛提交论文与内部技术报告。它只约束 `submission_paper` 的来源、模板和渲染证据，不把具体渲染技术设为全局黑名单，也不建立新的工作流状态。

## 文档类型

### submission_paper

比赛提交论文必须同时满足以下条件：

1. 声明并保存批准的 `profile_id` 快照；
2. 声明 `template_id`、`renderer_id` 和实际 renderer 版本；
3. `profile_id` 中的 `approved_renderers` 必须包含该 renderer/template 组合；
4. 保存论文源文件清单、模板清单、编译记录和输出 PDF 哈希；
5. 通过受控 Humanizer 差分检查、源码检查、编译检查和 PDF 逐页视觉验收；
6. 任何批准模板缺失、renderer 未批准、编译失败或证据缺失都必须阻断 submission rendering，不得静默退回其他样式。

### technical_report

内部审计、Formal Result、Sandboxie 与复现说明属于 `technical_report`。它们可以使用独立样式或 ReportLab，不受 submission 模板绑定约束，也不得冒充比赛提交论文。

## Renderer 规则

是否允许某个 renderer 只由当前 Profile 的 `approved_renderers` 决定。ReportLab、Typst、LaTeX 或其他实现均不作技术黑名单；某 Profile 明确批准的 renderer/template 组合可以用于该 Profile 的 submission paper，未批准的组合必须失败。

## 失败边界

批准模板缺失只阻断 Gate 4 的 submission rendering。Gate 0—3、Formal Result 与 technical report 可以继续；失败不得回写或改变已确认的建模结果。

## Attestation 最小证据

成功渲染必须生成 `paper_render_attestation.json`，至少记录文档类型、Profile、模板、renderer 及版本、源文件清单哈希、Profile 快照哈希、模板清单哈希、输出 PDF 哈希和 `compiled=true`。Attestation 证明渲染来源绑定，不证明论文内容正确，也不替代 Gate 5 独立 Reviewer。
