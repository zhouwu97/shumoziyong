# 2024-C Q2-A 情景生成器

Q2-A 只生成不确定性情景和 Scenario Manifest，不运行 Solver、Validator，也不生成 `result2.xlsx`。

生成器读取 Q2 冻结合同、官方附件和已冻结的 Q1 baseline Manifest，使用：

- `numpy==2.4.4`、`Generator(PCG64)`；
- `SeedSequence(entropy=seed, spawn_key=(2024, 3, 2))`；
- `sales`、`yield`、`cost`、`price` 四个固定子流；
- 3 个优化 seed 与 2 个评估 seed，每个 seed 生成 512 个母池情景；
- `(phase, seed, scenario_index)` 作为情景主键；
- 规范 JSON 的 SHA-256 作为每个情景和整个 Manifest 的身份。

默认运行：

```powershell
python scripts/generate_2024c_q2_scenarios.py
```

输出为 `formal_result/cases/2024_C/q2/q2_scenario_manifest.json`。官方母池 Manifest 已提交并冻结，当前 SHA 为：

```text
2f92a830007b96ce2aa760612175ef3b9ea465da4eb325c6012fdd636db3334d
```

Manifest 保存官方基准参数键目录、每个情景的参数摘要与 SHA，不保存 Solver 结果；后续 Solver 必须按同一合同重新生成，并由 `validate_manifest(manifest, contract, catalog)` 逐项重放核对后才能消费这些情景。官方 CI 会重新生成 Manifest 并与仓库文件逐字节比较。

Manifest 中明确保持：

```yaml
status: scenario_pool_frozen_solver_pending
q2_solver_started: false
q2_validator_started: false
production_ready: false
```

`64/128/256/512` 收敛检查只能从同一 512 母池取规范化前缀，不得重新抽样。Q2-A 完成不代表 Q2 求解完成，也不改变资格和完整旧题闭环状态。
