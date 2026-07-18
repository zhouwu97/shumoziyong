# 2024-C Q2 不确定性模型合同

## 1. 合同状态与边界

本合同冻结 Q2 的不确定性语义，供后续 Solver、Formal Result 和独立 Validator 共同使用。它不声明 Solver 已完成、不产生 `result2.xlsx`，也不覆盖 Q3 的相关性、替代性或互补性模型。

```yaml
problem_id: 2024-C
subproblem_id: Q2
contract_id: 2024c-q2-uncertainty-v1
status: model_contract_draft_review_pending
proxy_data_used: false
qualification_claimed: false
```

## 2. 决策与硬约束

决策是一个 2024--2030 年的**非自适应**种植方案 `x[p,t,s,c]`。方案在不观察未来随机参数的情况下确定；所有情景使用同一组面积。Q2 沿用 Q1 的地块容量、作物适宜性、季次制度、实际相邻季重茬、三年豆类窗口和管理性最小活动面积约束。Q2 不把随机参数写入硬约束，也不允许通过改变情景中的方案掩盖约束违规。

产量超过该情景销售量的部分按 Q1 的“滞销、收入为 0”口径处理。该口径是保守的 Q2 风险基线；折价口径仍属于 Q1 的独立情景，不与 Q2 混合。

## 3. 随机参数与来源

所有不确定量均以 2023 年附件 2 的对应值为基准。除特别注明外，年度因子在其声明的采样键之间相互独立；不共享市场或天气冲击。Q2 不使用相关矩阵，相关性只在 Q3 合同中定义。生成值必须为有限数；销售量允许基准值为 0，但不允许负数，成本、亩产量和价格必须为正数。合同不对非法输入静默截断，Validator 必须拒绝非法基准数据。

| 参数 | 作物类别 | 年度生成规则 | 采样键与备注 |
| --- | --- | --- | --- |
| 预期销售量 | 小麦、玉米 | `S[t] = S[t-1] * (1 + U(0.05, 0.10))` | `(crop_id, season, year)`；增长率每年重新采样 |
| 预期销售量 | 其他作物 | `S[t] = S[t-1] * (1 + U(-0.05, 0.05))` | `(crop_id, season, year)`；变化每年重新采样 |
| 亩产量 | 全部作物 | `Y[t] = Y[2023] * U(0.90, 1.10)` | `(crop_id, year)`；同一作物年度因子对兼容地块和季次共享，不建模地块级天气差异 |
| 种植成本 | 全部作物 | `C[t] = C[t-1] * (1 + U(0.045, 0.055))` | `(land_type, season, crop_id, year)`；“平均年增长 5%”的区间化解释 |
| 销售价格 | 粮食类 | `P[t] = P[2023]` | `(crop_id, season)`；题面“基本稳定”按不变处理 |
| 销售价格 | 蔬菜类 | `P[t] = P[t-1] * (1 + U(0.045, 0.055))` | `(crop_id, season, year)`；增长率每年重新采样 |
| 销售价格 | 食用菌（羊肚菌除外） | `P[t] = P[t-1] * (1 - U(0.01, 0.05))` | `(crop_id, season, year)`；降幅每年重新采样 |
| 销售价格 | 羊肚菌 | `P[t] = P[t-1] * 0.95` | `(crop_id, season, year)`；题面明确每年下降 5% |

`U(a,b)` 为包含端点的连续均匀分布。类别映射必须来自附件 1 的官方作物字典，不得按作物编号范围猜测；无法映射时 Validator 必须失败。

## 4. 情景、随机种子与重复实验

使用锁定在 `requirements.lock` 中的 NumPy `2.4.4`、`numpy.random.Generator(PCG64)` 和 `SeedSequence(entropy=seed, spawn_key=(2024, 3, 2))`。每个 seed 的子流按固定参数顺序 `sales, yield, cost, price` 生成；每个子流按年份升序、官方作物编号升序及表中声明的采样键排序。情景按 `scenario_0000` 至 `scenario_0255` 编号，JSON Manifest 使用 UTF-8、`sort_keys=true` 和紧凑分隔符计算 SHA-256。

优化情景和评估情景严格分离：`optimization_seed_groups=[20240724,20240725,20240726]`，`evaluation_seed_groups=[20240727,20240728]`，每个 seed 生成 256 个情景。Solver 只能消费优化组的 768 个情景；评估组的 512 个情景在方案冻结后才生成或读取，不能参与决策选择、参数调优或敏感性选择。两组 seed 必须不相交，Validator 必须检查这一点。256 是每组的预设计算预算，不是充分性证明。

Formal Result 必须保存：合同版本、NumPy 版本、位生成器、SeedSequence 规则、优化/评估 seed 列表、情景数量、规范化情景 Manifest SHA-256、每个情景参数摘要或其 SHA-256、方案 SHA-256 以及运行日志。Validator 必须按相同规则重新生成两组情景并逐项复算，禁止接受手工填写的均值或区间。

在 Q2 Solver 启动前，必须先冻结真实 Q1 基线：Q1 Candidate assignments、Q1 Formal Result SHA-256、Q1 Validator report SHA-256、`q1_waste` 与 `q1_discount` 两个目标值。当前基线状态为 `pending_real_q1_result`；不得在 Q2 中临时构造或口头引用 Q1 方案。Q2 方案和 Q1 基线必须在同一组评估情景上配对复算。

## 5. 风险目标与报告统计

情景利润为：

`profit_s(x) = 销售收入_s(x) - 种植成本_s(x)`。

多年利润定义为 2024--2030 各年利润的**未折现总和**。以损失 `loss_s(x) = -profit_s(x)` 定义 `CVaR_0.90(loss)`，采用有限样本的标准上尾平均：将损失从大到小排序，取最差 `ceil(0.10 * N)` 个情景的平均值。优化组 `N=768`，故尾部为 77 个情景；评估组 `N=512`，故尾部为 52 个情景。多组 seed 之间等权，所有情景同权。

主种植方案最大化：

`mean(profit_s) - 0.25 * CVaR_0.90(loss_s)`。

`0.25` 是本合同的风险厌恶系数，不是官方题面参数，必须在结果中显式标注，并至少以 `0`、`0.25`、`0.50` 做敏感性重算。所有报告至少包含均值、标准差、P05、P50、P95、最坏情景利润、CVaR，以及评估组中 Q1 基线的对应统计量和配对差异。

情景预算必须按同一规范化顺序做 `64 → 128 → 256 → 512` 收敛检查。每个预算至少记录期望利润相对变化、CVaR 相对变化、方案面积结构变化和 seed 组间方差；在 256 未达到预设稳定阈值（均值变化不超过 2%、CVaR 变化不超过 5%、面积结构相对 L1 变化不超过 5%）时，不得声称情景数量充分，只能报告为预算不足或未收敛。

## 6. Validator 复算边界

Q2 Validator 必须独立读取官方附件和本合同，校验：

1. 合同身份、参数类别映射、NumPy/PCG64/SeedSequence 身份、优化/评估 seed、情景数量和情景编号；
2. 每个情景的销量、亩产、成本、价格因子、采样键、规范化 Manifest SHA-256 及非负/有限性；
3. 方案面积、Q1 全部硬约束和非负有限性；
4. 每个情景的产量、销售收入、成本、利润和超产处理；
5. 均值、分位数、最坏情景、CVaR 和风险目标；
6. Q1 基线使用同一情景集的比较结果；
7. `result2.xlsx` 的文件身份、模板版式、单元格与 Formal Result 方案的一致性。
8. 优化/评估情景互不相交，以及 64→512 收敛检查和 Q1 基线冻结状态。

Validator 不运行候选 Solver，不把 `status`、`objective_reported` 或人工统计值当作真值；任一情景、哈希、约束或统计量不一致即失败。Q2 在独立 Workbook Validator 和 Formal Result 全部通过前，不得登记为完成或生产就绪。

## 7. 退出条件

```yaml
q2_uncertainty_model_complete: false
q2_reproducible: false
q2_validator_complete: false
q2_official_excel_complete: false
```

只有完成 Solver、五组重复实验、独立 Validator、`result2.xlsx` 反向读取和 Q1 配对比较后，才可将上述状态更新为 `true`。
