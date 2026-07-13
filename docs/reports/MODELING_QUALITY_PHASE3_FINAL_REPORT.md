# 数学建模质量计划阶段三最终报告

日期：2026-07-13

实验：`a092_confirmatory_v1`

最终决定：`A092.status = review_ready`，不晋级 `regression_verified`

## 1. 执行结论

计划中的阶段二已经完成 A092 七项行为、Validator v0、故障注入 Pilot、题目角色、评分门槛和确认性协议冻结；阶段三随后按冻结顺序启动正式 Baseline/Treatment。

阶段三没有得到可晋级证据：

- 正控首对 R01/R02 均出现 Solution P0，Treatment 的四个场景全部未通过独立目标复算，按冻结筛查规则跳过 R03/R04；
- 边界题两对 R05–R08 全部未通过冻结解析适配器，最大绝对差均约为 `705.584`；
- 负控基线 R09 的 MRE 独立复算通过且语义上正确关闭工程优化，但同一会话发生不同脚本版本并发覆盖，判为 Experiment Invalid；
- 负控 Treatment R10 在模型工作开始前触发 Codex 用量上限，判为 Experiment Invalid；
- 没有干净有效配对可用于晋级，盲化评分未执行。硬门槛已经失败，因此缺少盲评分不会改变“不晋级”决定，但意味着本轮不能作为完整效应量实验。

阶段完成标准允许“失败但诚实”的结果。本轮没有为了得到成功晋级而修改 Validator、容差、题目角色或晋级阈值。

## 2. 正式配置与协议偏差

最终成功启动的运行统一使用：

- 模型：`gpt-5.6-sol`；
- reasoning effort：`high`；
- 采样：Codex CLI 模型默认值；
- 权限：隔离复制材料目录中的 `danger-full-access`；
- Web：关闭；
- 人工反馈：关闭；
- 单次上限：3600 秒；
- Baseline：base + optimization plugin；
- Treatment：base + optimization plugin + A092。

正式运行前记录了四项偏差：CLI 不支持冻结温度字段、原冻结包遗漏正式题适配器、遗漏统一执行提示、`workspace-write` 在忽略用户配置时表现为只读。每项均在受影响的成功 Treatment 前记录，并重新冻结最终配置。第一次只读 R01 尝试保存在 `invalid_attempts/R01_workspace_write`，未计入正式结果。

## 3. 运行结果

| Run | 角色 | Arm | 执行状态 | 独立验证 | 分类 |
|---|---|---|---|---|---|
| R01 | 正控第 1 对 | Baseline | 完成 | 4/4 场景失败 | Solution P0 |
| R02 | 正控第 1 对 | Treatment | 完成 | 4/4 场景失败 | Solution P0 |
| R03 | 正控第 2 对 | Treatment | 跳过 | 不适用 | 冻结筛查停止 |
| R04 | 正控第 2 对 | Baseline | 跳过 | 不适用 | 冻结筛查停止 |
| R05 | 边界第 1 对 | Treatment | 完成 | 失败，最大差 705.584056 | Solution P0 |
| R06 | 边界第 1 对 | Baseline | 完成 | 失败，最大差 705.584056 | Solution P0 |
| R07 | 边界第 2 对 | Baseline | 完成 | 失败，最大差 705.584056 | Solution P0 |
| R08 | 边界第 2 对 | Treatment | 完成 | 失败，最大差 705.584056 | Solution P0 |
| R09 | 负控第 1 对 | Baseline | 完成 | 数值通过，语义安全 | Experiment Invalid：并发覆盖 |
| R10 | 负控第 1 对 | Treatment | 启动失败 | 未运行 | Experiment Invalid：用量上限 |

所有已完成运行的跨运行引用扫描均通过，没有发现读取其他 run、实验归档、补丁库或协议目录的证据。

### 3.1 正控

R01 与 R02 都生成了 Gate 0–5、求解代码、正式 JSON、论文和图表，但仓库侧适配器重算后：

- 四个场景的 `objective_reported` 与 `objective_recomputed` 均显著不一致；
- R01/R02 的部分场景还存在连续种植等关键约束违约；
- Treatment 自检产物更完整，但没有转化为数学正确性。

因此 Treatment 不能判优，且触发“停止该题进一步重复”。

### 3.2 边界题

四次运行都能主动关闭目标优化、约束优化和敏感性模块，没有为了补齐 A092 产物虚构工程优化路线，这是语义上的正面信号。

但四次正式结果均未通过冻结解析适配器。偏差高度稳定，提示适配器和模型对 2023-B 的测线方向、深度符号或 `beta` 定义可能存在系统性口径冲突。由于 Treatment 已经开始，本轮没有事后修改适配器；下一版预注册前必须先以题面和官方口径复核该公式。

### 3.3 负控

R09 的九条曲线 MRE 均可逐点复算，剩余时间为非负有限值，并明确输出：

```text
engineering_optimization_applicable = false
optimality_claim_allowed = unverified_candidate
```

这说明基线负控的数学和语义结果本身可用。但执行器的短命令超时留下孤立子进程，模型随后修改脚本并启动新版本，多个进程先后覆盖正式结果、图和清单。即使最终文件通过复算，也不能把这条执行链当作干净实验。

R10 的事件流在模型工作前返回用量上限，`usage` 为空，没有任何 Gate 或模型产物。它不是 Solution P0，而是外部条件导致的 Experiment Invalid。

## 4. 盲化评分状态

盲化数学包和论文包没有进入独立评分：

1. 正控 Treatment 已先触发 Solution P0；
2. 边界两对均没有独立数值通过；
3. 负控没有完成干净 Treatment；
4. 可用的独立 Codex 评审通道已触发额度上限。

本报告不以非盲人工分数替代预注册盲评。由于总体晋级条件要求正控、边界、负控同时通过且无未处理 Experiment Invalid，当前硬失败已足以决定继续 `review_ready`。

## 5. 晋级门槛判定

| 条件 | 结果 |
|---|---|
| 正控无 Solution P0 | 失败 |
| 正控至少两对且方向一致 | 失败，第二对按规则跳过 |
| 边界至少两对且独立验证不下降 | 失败，四次独立验证均失败 |
| 负控无 Experiment Invalid | 失败 |
| 无未处理 Experiment Invalid | 失败 |
| 增益来自可检查、可重复行为 | 未证明 |
| 建议晋级 | 否 |

`prompt_patches/patch_index.json` 中 A092 保持 `review_ready`，没有写入 `regression_verified`。

## 6. 交付物

- `experiments/a092_confirmatory_v1/aggregate_results.json`：聚合判定；
- `experiments/a092_confirmatory_v1/experiment_manifest_private.json`：私有 Arm 映射、运行元数据哈希和分类；
- `experiments/a092_confirmatory_v1/evidence_snapshots.json`：已完成运行的独立验证、隔离审计和元数据快照；
- `experiments/a092_confirmatory_v1/blind_scoring_status.json`：盲评未执行及其影响；
- `experiments/a092_confirmatory_v1/invalid_attempts/R10_usage_limit/attempt_summary.json`：R10 失败证据；
- `scripts/run_a092_stage3.py`：冻结运行器；
- `scripts/validate_a092_formal_run.py`：独立验证与隔离审计入口；
- `scripts/build_a092_stage3_summary.py`：可重复聚合入口；
- 本机忽略目录 `experiments/a092_confirmatory_v1/runs/`：R01、R02、R05–R09 原始运行归档；
- 本机忽略目录 `tmp/a092_confirmatory_v1/R10/`：R10 原始失败事件流。

原始运行包含大型样本、图表和执行事件，因此按仓库既有 `.gitignore` 保留在本机；提交版本保存关键证据快照和哈希。

## 7. 下一轮建议

1. 先修复执行器超时后孤立子进程问题：外壳超时时必须终止完整进程树，禁止并发覆盖同一 run 产物。
2. 在新的 Treatment 前，以题面方向定义复核 2023-B 解析适配器，并用小型手算点和故障注入重新 Pilot。
3. 修订 A092：把“自检已通过”与“冻结外部适配器已通过”分离，外部失败必须阻止强结论。
4. 额度恢复后不要只补跑 R10 并直接晋级；应根据适配器/执行器是否改变，选择完整重跑冻结版本或发布新的预注册版本。
5. 新一轮完成干净有效配对后，再生成匿名 X/Y 包并独立盲评。

## 8. 最终状态

```json
{
  "patch_id": "A092",
  "status": "review_ready",
  "promotion_conditions_met": false,
  "decision": "do_not_promote"
}
```

## 9. 仓库验证

阶段三收尾后的验证结果：

```text
python -m pytest -q
374 passed, 10 skipped

python scripts/validate_repository.py
47 passed, 0 failed

python -m ruff check .
All checks passed

python -m pyright
0 errors, 0 warnings, 0 informations
```
