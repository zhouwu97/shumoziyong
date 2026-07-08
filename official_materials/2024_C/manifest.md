# 官方材料清单_2024_C

## 来源

| 文件 | 来源 URL 或本地来源 | 获取时间 | 用途 | 是否官方 | 备注 |
|---|---|---|---|---|---|
| `raw/CUMCM2024Problems.zip` | https://www.mcm.edu.cn/html_cn/node/a0c1fb5c31d43551f08cd8ad16870444.html；直接下载地址 `https://www.mcm.edu.cn/upload_cn/node/725/pmkWxf8H9cfe9984c1a1a5b1263e5dd3b5596ed5.zip` | 2026-07-05 11:22:45 +08:00 | 2024 官方赛题总包 | 是 | 全国大学生数学建模竞赛官网“2024年高教社杯全国大学生数学建模竞赛赛题”页面附件 |
| `problem/C题.pdf` | 从 `raw/CUMCM2024Problems.zip` 解出 | 2026-07-05 11:22:45 +08:00 | 官方题面 | 是 | 题名为“农作物的种植策略”，1 页 |
| `problem/C题_extracted_text.txt` | 从 `problem/C题.pdf` 文本抽取 | 2026-07-05 11:22:45 +08:00 | 题面文本核验 | 是 | 仅用于总控诊断材料摘要，不含答案或解析 |
| `attachments/附件1.xlsx` | 从 `raw/CUMCM2024Problems.zip` 的 `C题/附件1.xlsx` 解出 | 2026-07-05 11:22:45 +08:00 | 耕地与作物基础数据 | 是 | 工作表：`乡村的现有耕地` 55x4，`乡村种植的农作物` 46x5 |
| `attachments/附件2.xlsx` | 从 `raw/CUMCM2024Problems.zip` 的 `C题/附件2.xlsx` 解出 | 2026-07-05 11:22:45 +08:00 | 2023 年种植与统计数据 | 是 | 工作表：`2023年的农作物种植情况` 88x6，`2023年统计的相关数据` 111x10 |
| `templates/result1_1.xlsx` | 从 `raw/CUMCM2024Problems.zip` 的 `C题/附件3/result1_1.xlsx` 解出 | 2026-07-05 11:22:45 +08:00 | 问题 1 情形 1 输出模板 | 是 | 2024-2030 共 7 张年度表 |
| `templates/result1_2.xlsx` | 从 `raw/CUMCM2024Problems.zip` 的 `C题/附件3/result1_2.xlsx` 解出 | 2026-07-05 11:22:45 +08:00 | 问题 1 情形 2 输出模板 | 是 | 2024-2030 共 7 张年度表 |
| `templates/result2.xlsx` | 从 `raw/CUMCM2024Problems.zip` 的 `C题/附件3/result2.xlsx` 解出 | 2026-07-05 11:22:45 +08:00 | 问题 2 输出模板 | 是 | 2024-2030 共 7 张年度表 |
| `templates/format2024.doc` | 从 `raw/CUMCM2024Problems.zip` 解出 | 2026-07-05 11:22:45 +08:00 | 论文格式规范 | 是 | 本轮只做总控诊断，不进入论文写作 |

## 文件校验

| 文件 | SHA256 |
|---|---|
| `attachments/附件1.xlsx` | `B799A137294A5C5497FED9667C5DFED6C967F1FB180316C5ADC8509CFA6F0932` |
| `attachments/附件2.xlsx` | `869081A3AB47D3BF8D0955106B622AAF0FD2C068FADA7948DA69B20EBF1D00CE` |
| `problem/C题_extracted_text.txt` | `94C0A7E2B508367B42A8139461C09E1799AA1D152FDAD0C6937F6CC9F7682AA3` |
| `problem/C题.pdf` | `C7B5E58BFF4189B8AFBA5505F7BFF7D4F08280FC291C51EF3F46134EBBF74F9A` |
| `raw/CUMCM2024Problems.zip` | `38D9EFFCEDE947354F9E9A9C2B4FC68947D83A77C2FF75737E9A662888158726` |
| `templates/format2024.doc` | `EC699BBE89E25CAD16CA907B305C6CC76112EC04083CFE56CA65FD7A26FBAAFE` |
| `templates/result1_1.xlsx` | `4F2484C0D70A5C4D047163F2EE6EF486949E813330466F46DEF4BD7D98AF06AF` |
| `templates/result1_2.xlsx` | `6166D43F5A64BF9D1657E80D4AEE7F10F54BB1A5695B81A28A0AC5E657297649` |
| `templates/result2.xlsx` | `6A1BA9FC28D14D0A4A795E5F0B7261FB6E32165517AFEE62BCD1931ABA5BEE8A` |

## 完整性检查

- 是否有官方题面：是，`problem/C题.pdf`。
- 是否有附件：是，`attachments/附件1.xlsx` 和 `attachments/附件2.xlsx`。
- 是否有结果模板：是，`templates/result1_1.xlsx`、`templates/result1_2.xlsx`、`templates/result2.xlsx`。
- 是否包含答案泄漏：否。材料来自官方赛题包，不含优秀论文、参考答案、解析或最终结果。
- 是否可作为 T3：是。该题与当前 A092/A127 patch 来源论文不同题，且不同于已有 2023-B T3 测试题；官方题面、必要附件和输出模板齐全。

## 风险判断

- M1：否。未使用优秀论文、获奖论文、题解、参考答案或含最终数值结果材料作为输入。
- M2：否。官方题面、附件和结果模板齐全。
- M3：否。2024-C 农作物种植策略与 A092/A127 的 2023-A 定日镜场不同题源，也不同于已有 2023-B 多波束测线同题源。
- M4：否。本轮只允许迁移评价函数先行、约束优化、简单方法优先、数据需求清单等抽象规则，不照搬任何同题论文。
- M5：否。题意、附件和输出要求均来自官方材料。

## 本轮用途

- 用作 `2024-C 农作物的种植策略` 官方 T3 泛化测试材料。
- 测试模块：总控诊断。
- 题型判断：资源配置 / 多期种植优化 / 不确定性决策 / 农业经营策略。
- 禁止事项：不写论文，不写代码，不给最终答案，不读取同题优秀论文、参考答案或解析。
