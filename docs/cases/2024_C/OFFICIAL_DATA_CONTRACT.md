# 2024-C 官方材料与数据合同

## 范围与边界

本合同只定义 2024-C《农作物的种植策略》的官方输入、字段语义、单位和材料身份。它不包含求解器、候选结果或比赛资格声明。

```yaml
problem_id: 2024-C
material_status: official_materials_hash_verified
proxy_data_used: false
fixture_solver_used: false
solver_started: false
qualification_claimed: false
```

官方材料来自 2024 年全国大学生数学建模竞赛官方赛题包。原始文件保留在本地受控目录，仓库只提交清单和合同。

## 材料身份

| 路径 | 用途 | 字节数 | SHA-256 |
| --- | --- | ---: | --- |
| `official_materials/2024_C/problem/C题.pdf` | 官方题面 | 558863 | `c7b5e58bff4189b8afba5505f7bff7d4f08280fc291c51ef3f46134ebbf74f9a` |
| `official_materials/2024_C/problem/C题_extracted_text.txt` | 题面文本核验副本 | 3900 | `94c0a7e2b508367b42a8139461c09e1799aa1d152fdad0c6937f6cc9f7682aa3` |
| `official_materials/2024_C/attachments/附件1.xlsx` | 地块和作物适宜性 | 17147 | `b799a137294a5c5497fed9667c5dfed6c967f1fb180316c5adc8509cfa6f0932` |
| `official_materials/2024_C/attachments/附件2.xlsx` | 2023 种植和统计数据 | 21976 | `869081a3ab47d3bf8d0955106b622aaf0fd2c068fada7948da69b20ebf1d00ce` |
| `official_materials/2024_C/templates/result1_1.xlsx` | Q1 情形 1 输出模板 | 81837 | `4f2484c0d70a5c4d047163f2ee6ef486949e813330466f46def4bd7d98af06af` |
| `official_materials/2024_C/templates/result1_2.xlsx` | Q1 情形 2 输出模板 | 81836 | `6166d43f5a64bf9d1657e80d4aee7f10f54bb1a5695b81a28a0ac5e657297649` |
| `official_materials/2024_C/templates/result2.xlsx` | Q2 输出模板 | 81836 | `6a1ba9fc28d14d0a4a795e5f0b7261fb6e32165517afee62bcd1931aba5bee8a` |
| `official_materials/2024_C/templates/format2024.doc` | 论文格式规范 | 69120 | `ec699bbe89e25cad16ca907b305c6cc76112ec04083cfe56ca65fd7a26fbaafe` |

官方 ZIP 原包的 SHA 为 `38d9effcede947354f9e9a9c2b4fc68947d83a77c2ff75737e9a662888158726`，仅用于来源追踪，不作为求解输入。

## 题面事实与单位

- 露天地块面积合计 1201 亩，类型为平旱地、梯田、山坡地和水浇地。
- 另有 16 个普通大棚和 4 个智慧大棚，每个 0.6 亩；附件 1 因此包含 54 个地块条目，总面积 1213 亩。
- 平旱地、梯田、山坡地每年一季；水浇地可一季水稻或两季蔬菜；普通大棚一季蔬菜加一季食用菌；智慧大棚两季蔬菜。
- 面积单位为亩；产量为斤；成本为元/亩；价格为元/斤；销售量由附件 2 的 2023 年种植记录汇总得到。
- 2024–2030 为七个年度，季次采用 `单季`、`第一季`、`第二季`，且单季作物写入输出模板第一季区域。

## 约束语义

必须在求解和 Validator 中显式处理：地块容量、作物—地块适宜性、季次规则、连续重茬禁止、三年内至少一次豆类、每季作物销售上限，以及题面要求的管理分散度和最小面积规则。题面没有给出管理阈值的数值时，不能擅自把经验阈值当成官方参数，必须在模型合同中单独声明并做敏感性分析。

