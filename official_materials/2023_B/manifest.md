# 官方材料清单_2023_B

## 来源

| 文件 | 来源 URL 或本地来源 | 获取时间 | 用途 | 是否官方 | 备注 |
|---|---|---|---|---|---|
| `2023_CUMCM_problems_official_univs.rar` | https://dxs.moe.gov.cn/zx/a/hd_sxjm_sthb/230523/1840580.shtml；直接下载地址 `https://univs-news-1256833609.file.myqcloud.com/52Kw7CxOBXSKw/2%40Q%40dFHtlmYSo.rar` | 2026-07-02 22:18:49 +08:00 | 官方赛题总包 | 是 | 中国大学生在线页面注明“全国大学生数学建模竞赛组委会授权发布2023高教社杯全国大学生数学建模竞赛赛题” |
| `raw/B题.rar` | 从官方赛题总包解出 | 2026-07-02 22:19:00 +08:00 | B 题官方材料包 | 是 | 包内含题面、附件和结果模板 |
| `problem/B题.pdf` | 从 `raw/B题.rar` 解出 | 2026-07-02 22:19:00 +08:00 | 官方题面 | 是 | 3 页，文本抽取约 2161 字 |
| `attachments/附件.xlsx` | 从 `raw/B题.rar` 解出 | 2026-07-02 22:19:00 +08:00 | 问题 4 海水深度数据 | 是 | 1 个工作表，253 行 x 203 列 |
| `templates/result1.xlsx` | 从 `raw/B题.rar` 解出 | 2026-07-02 22:19:00 +08:00 | 问题 1 输出模板 | 是 | 题面要求保存到 `result1.xlsx` |
| `templates/result2.xlsx` | 从 `raw/B题.rar` 解出 | 2026-07-02 22:19:00 +08:00 | 问题 2 输出模板 | 是 | 题面要求保存到 `result2.xlsx` |
| `templates/format2023.doc` | 从官方赛题总包解出 | 2026-07-02 22:19:00 +08:00 | 论文格式规范 | 是 | 本轮只做总控诊断，不进入论文写作 |

## 文件校验

| 文件 | SHA256 |
|---|---|
| `2023_CUMCM_problems_official_univs.rar` | `37B1010672ADCF35831E798264CC69DB616027F2287CFEAE3C4EE6DAF03AE4E6` |
| `raw/B题.rar` | `1DFC6819EFEDB2D8C349276EF503DD1CEEEE7A7EE2E15996B4CED37DC058D374` |
| `problem/B题.pdf` | `E709E066139EA0A4BB64AA7E56EA097725A1F2B4E5161FC8C7E50C48BE079396` |
| `attachments/附件.xlsx` | `5F92DEE1AF5906869BD7DCA45D73B90090BB971D882BEB7D8461C6B563EEE40A` |
| `templates/result1.xlsx` | `9A86F9F4B9755447BDA0AB9C3D8F4123561A0BFA735EDE7D0C08B1C457AE83BD` |
| `templates/result2.xlsx` | `426941A7DA69DA8694D73BE68BA82B976AF675F57618154F4B4FC11D19F6DBD8` |
| `templates/format2023.doc` | `1D5C03591148D155BB1D5BB0A305661BFAFF29C3102595446CFCC06CEB4E82EC` |

## 完整性检查

- 是否有官方题面：是，`problem/B题.pdf`。
- 是否有附件：是，`attachments/附件.xlsx`。
- 是否有结果模板：是，`templates/result1.xlsx`、`templates/result2.xlsx`，题面还给出问题 3 和问题 4 的输出指标要求。
- 是否包含答案泄漏：否。材料来自官方赛题包，不含优秀论文、参考答案或解析。
- 是否可作为 T3：是。该题与当前 A092/A127 patch 来源论文不同题，官方题面、附件和模板齐全。

## 风险判断

- M1：否。未使用优秀论文、获奖论文、题解、参考答案或含最终数值结果材料作为输入。
- M2：否。官方题面、附件和结果模板齐全。
- M3：否。2023-B 多波束测线问题与 A092/A127 的 2023-A 定日镜场不同题源。
- M4：否。本轮只允许迁移评价函数先行、约束优化、简单方法优先等抽象规则，不照搬 B226 优秀论文或 A092/A127 具体机制。
- M5：否。题意、附件和输出要求均来自官方材料。

## 本轮用途

- 用作 `2023-B 多波束测线问题` 官方 T3 泛化测试材料。
- 测试模块：总控诊断。
- 禁止事项：不写论文，不写代码，不给最终答案，不读取同题优秀论文、参考答案或解析。
