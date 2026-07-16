# 三路线竞争合同 v3

## 目的

v3 把“候选模型列表”升级为可执行的路线竞争：每个子问题必须同时冻结机制假设、基线、主路线和结构不同备选，
三条路线在后续阶段独立执行后才能比较。路线比较、可执行性和风险报告都不是 Formal Result 的替代品。

## 证据关系

```text
model_route_v3
  -> 三条独立执行与各自 Formal Result
  -> route_comparison_result_v1
  -> operability_contract/report_v1
  -> risk_decision_contract/report_v1
  -> Gate 3 独立 Validator 裁决是否可进入论文
```

`blocking` 业务约束必须由每条路线显式承接。连续解、取整解、修复解或降级方案发生变化后，必须重新执行
可执行性检查。数据泄漏、遗漏硬约束、不可行方案和无理由风险降级均采用 fail-closed。

## 兼容边界

- `schemas/model_route_v2.schema.json` 的固定 SHA-256 为
  `729a33a49d25e35ccc25df581695bc160cafa35799591384ff2c682c35df7f9c`，本升级不修改该文件。
- 版本分派同时识别 v2 与 v3，不根据文件名猜测合同。
- v3 生命周期为 `review_ready`，目前只允许显式 `full_replay`；`new_problem` 仍使用既有默认链路。
- PR-2A 建立合同和分派；PR-2B 已通过父竞争 Run + 三个隔离子 Run 接入 Executor、Collector Formal
  Result 与独立 Gate 3 Validator，详见 `COMPETITION_ROUTE_V3_RUNTIME.md`。
- 新 Runtime 仍未编译进默认 Profile；Profile 与 Gate 路由激活留给 PR-4。
