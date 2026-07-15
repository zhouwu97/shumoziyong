# 图表规划合同

## 目的

图表规划用于在写作前说明每张图为什么存在、数据从哪里来、支持哪个结论。它是只读 Handoff，不负责生成或重画真实数值图。

## 顶层结构

```json
{
  "schema_version": "1.0.0",
  "paper_id": "2021_C",
  "figures": []
}
```

每个 `figures` 条目必须包含：

| 字段 | 类型 | 规则 |
| --- | --- | --- |
| `figure_id` | string | 论文内唯一，建议使用 `fig_q2_inventory` 形式 |
| `source_artifact` | string | 相对项目根目录的真实结果或图示源文件 |
| `source_sha256` | string | 64 位小写 SHA-256，源文件变化后必须更新 |
| `target_section` | string | 图计划放入的章节 ID |
| `purpose` | string | 该图需要回答的明确问题 |
| `claim_ids` | array[string] | 图直接支持的 Claim ID，可为空但必须解释 |
| `caption` | string | 论文图题，不在图内重复写大标题 |
| `figure_type` | string | `data` 或 `conceptual` |
| `conceptual` | boolean | 概念图必须为 `true`，数据图必须为 `false` |
| `color_allowed` | boolean | 是否允许使用颜色 |
| `grayscale_distinguishable` | boolean | 打印为灰度后是否仍可区分 |

## 约束

- `figure_type=data` 时，`source_artifact` 必须指向真实结果、绘图数据或可复现绘图脚本，且 `conceptual=false`。
- `figure_type=conceptual` 时，必须设置 `conceptual=true`，不得暗示图中包含真实计算结果。
- 数据图不得由 Writer 根据正文中的几个数值重新绘制。
- 图内不放与论文图题重复的大标题。
- 不生成没有论证目的、只为增加数量的流程图。
- 同类图的颜色、线型、字体和单位应一致；使用颜色时仍需保证灰度可区分。

## 变更规则

源文件内容变化、图支持的 Claim 变化或舍入口径变化时，必须更新规划并重新计算 SHA。只改图题但不改变数据时，也应保留审查记录。
