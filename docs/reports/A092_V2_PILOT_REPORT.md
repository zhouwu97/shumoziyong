# A092 v2 外部验证门槛 Pilot 报告

日期：2026-07-13

Pilot：`A092-V2-PILOT-20260713`

结论：七个预注册场景全部被正确分类，A092 v2 已能区分外部 Validator 自身失效与候选方案失效，并在目标或硬约束未同时通过时阻断论文定量结论；最优性强结论还需要单独的证明证据。本 Pilot 只用于规则校准，不属于正控、边界或负控证据，A092 继续保持 `review_ready`。

## 1. 校准来源

第一轮确认性实验暴露了两类不同问题：

- 2023-B v1 外部适配器遗漏水深的方向投影，导致四次运行出现固定约 `705.584056` 的系统偏差。
- 2024-C v1 外部适配器遗漏合并单元格前向填充；修正后 R02 目标通过，但多个场景仍有实际相邻季次重茬。

因此，“候选自检通过”“外部目标复算通过”和“全部硬约束通过”必须是三个独立事实，外部 Validator 自身也必须先通过数据与手算 Pilot。

## 2. 新增机器门槛

数据契约审计固定检查：

1. 输入文件 SHA256；
2. 合并单元格、缺失值和单位换算；
3. 派生聚合键；
4. 时间槽实际顺序与历史边界状态；
5. 2–3 个手算 fixture。

外部 Validator 证明固定记录 adapter、contract、input、solution 与候选评价器 SHA256。外部适配器和候选评价器哈希相同时，直接判实现不独立。

## 3. 故障注入结果

| 场景 | 预期实验判定 | 预期候选判定 | 结果 |
|---|---|---|---|
| 候选自检通过、外部目标失败 | valid | rejected | 通过 |
| 外部适配器手算 fixture 失败 | invalid | rejected | 通过 |
| 目标通过、硬约束失败 | valid | rejected | 通过 |
| 同一实现冒充独立验证 | invalid | rejected | 通过 |
| 缺少聚合键预处理审计 | invalid | rejected | 通过 |
| 目标与约束通过但无最优性证明 | valid | accepted，阻断强最优性 | 通过 |
| 全部门槛通过 | valid | accepted | 通过 |

所有 rejected 场景均阻断目标值、改进率和最优性强结论。目标与约束通过但没有最优性证明时，只开放目标值和改进率；三道门全部通过的正例才开放强最优性 Claim。

## 4. 产物

- Pilot 结果：`examples/a092_phase2_pilot_v2/pilot_result.json`
- 数据契约：`examples/a092_phase2_pilot_v2/artifacts/a092/data_contract_audit.json`
- 外部证明：`examples/a092_phase2_pilot_v2/artifacts/a092/external_validator_attestation.json`
- 判定实现：`validators/common/external_validation.py`
- Pilot 外部适配器：`validators/pilot_case/external_adapter_v2.py`

## 5. 晋级限制

本 Pilot 不证明 A092 能提高比赛题得分，也不补足第一轮无效配对。`A092-CONFIRMATORY-V2` 已在 `protocols/a092_v2/a092_confirmatory_v2.json` 冻结，状态为 `frozen_pre_execution`，尚未启动任何确认性 Run。在新实验形成有效正控、边界和负控配对前，A092 不得进入 `regression_verified`。
