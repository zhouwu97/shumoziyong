# 官方材料清单_2016_C

## 来源

| 文件 | 来源 URL 或本地来源 | 获取时间 | 用途 | 是否官方 | 备注 |
|---|---|---|---|---|---|
| `CUMCM2016Problems.rar` | https://www.mcm.edu.cn/html_cn/node/6d026d84bd785435f92e3079b4a87a2b.html；直接下载地址 `https://www.mcm.edu.cn/upload_cn/node/393/UxYMjfW4fd0a5cd7a21951b49232088d2af3f4e8.rar` | 2026-07-10 17:43:41 +08:00 | 2016 高教社杯中文赛题总包 | 是 | 全国大学生数学建模竞赛官网发布 |
| `CUMCM-2016C-Chinese.rar` | 从官方中文赛题总包解出 | 2026-07-10 17:43:41 +08:00 | C 题官方材料包 | 是 | 子归档只含 C 题题面和数据附件 |
| `problem/CUMCM2016-Problem-C-Chinese-version.docx` | 从 C 题官方材料包解出 | 2026-07-10 17:43:41 +08:00 | C 题官方题面 | 是 | 题名：电池剩余放电时间预测 |
| `problem/CUMCM2016-Problem-C-Chinese-version_extracted_text.txt` | 从官方 DOCX 提取并修复其可逆编码乱码 | 2026-07-10 17:43:41 +08:00 | 供 runtime 读取的题面文本 | 派生文件 | 原始 DOCX 保持不变；已核对题名、问题 1-3 和附件 1-2 引用 |
| `data/CUMCM2016-C-Appendix-Chinese.xlsx` | 从 C 题官方材料包解出 | 2026-07-10 17:43:41 +08:00 | 问题 1-3 的放电曲线和衰减状态数据 | 是 | 包含“附件1”“附件2”两个工作表，无公式错误 |

## 文件校验

| 文件 | SHA256 |
|---|---|
| `CUMCM2016Problems.rar` | `A20EAC15B174E79AC5491378DFEC5138C1F990D8F55D2BA037CADB69CB685DAD` |
| `CUMCM-2016C-Chinese.rar` | `2E014699C7610ABDD7F12D871D1A0DEFA322E7DDD4FB76D3B9DCF3ABEE613BDA` |
| `problem/CUMCM2016-Problem-C-Chinese-version.docx` | `19CD536E12E78A4270D621F977CEA37859EFAF7AF77526AE680BEC7B6993D440` |
| `problem/CUMCM2016-Problem-C-Chinese-version_extracted_text.txt` | `00A4F5A92722A5358DA5FFAEE0FDFFCB527C7EE80BC7B5EE67CF0E145D272969` |
| `data/CUMCM2016-C-Appendix-Chinese.xlsx` | `062583D35B471838D3F72353C898AB87E2A2407C9AD5579291AEC91A7124E0BF` |

## 完整性检查

- 是否有官方题面：是，原始格式为 DOCX。
- 是否有题面提取文本：是，仅修复官方 DOCX 中可逆的编码乱码，不增删题意。
- 是否有附件：是，单个 XLSX 中包含附件 1 和附件 2。
- 是否包含其他题目、整包压缩文件、参考论文或题解：否。
- 是否包含答案泄漏：否。
- 是否适合作为 A092 负控：是。题目只要求曲线拟合、回归预测、误差评估和剩余时间预测，不含工程方案、布局设计、设计变量或约束寻优。

## 本轮登记范围

运行时只登记以下三个文件：

1. `problem/CUMCM2016-Problem-C-Chinese-version.docx`
2. `problem/CUMCM2016-Problem-C-Chinese-version_extracted_text.txt`
3. `data/CUMCM2016-C-Appendix-Chinese.xlsx`

外层赛题总包和 C 题子归档只在系统临时目录中用于来源核验，不复制到仓库材料目录，也不进入 `problem_manifest.json`。
