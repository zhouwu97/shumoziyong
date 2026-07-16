# 官方材料清单_2024_D

## 来源

| 文件 | 来源 URL 或本地来源 | 获取时间 | 用途 | 是否官方 | 备注 |
|---|---|---|---|---|---|
| `2024_CUMCM_problems_official_cn.rar` | https://dxs.moe.gov.cn/zx/hd/sxjm/dwdxxsxjm/dwdxxsxjm-2024gjsbqgdxssxjmjs.shtml；直接下载地址 `https://univs-news-1256833609.file.myqcloud.com/123/upload/resources/file/2024zjhychn.rar` | 2026-07-17 复核 | 2024 高教社杯中文赛题总包 | 是 | 中国大学生在线页面注明经全国大学生数学建模竞赛组委会授权发布 |
| `problem/D题.pdf` | 从官方中文赛题总包的 D 题目录解出 | 2026-07-17 复核 | D 题官方题面 | 是 | 题名为“反潜航空深弹命中概率问题”，共 2 页 |

## 文件校验

| 文件 | SHA256 |
|---|---|
| `problem/D题.pdf` | `8F30BDB312715167CD4CEAF87604DFD12E688D802E32E310322057AEB9D66CB0` |

## 完整性检查

- 官方题面完整，包含单枚深弹无深度误差、含深度误差及九枚阵列投弹三个问题。
- 本题不含外部数据附件或结果模板，全部参数和几何条件均在题面中给出。
- 材料不含优秀论文、参考答案、题解或最终数值结果。
- 本地 PDF 作为只读材料由 `.gitignore` 隔离，版本库只保存本说明与机器可读哈希清单。

## PR-7 用途

- 用于 `competition_production_v1` 的全链路 `full_replay`，题型为概率建模、几何积分与随机优化。
- 运行必须重新建立三条结构不同的路线并由独立 Validator 复算，不得读取同题答案或历史论文。
- 本登记不代表回放已通过；能力生命周期只能由五题 Campaign 报告派生。
