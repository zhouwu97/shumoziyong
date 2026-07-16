# Patch 实验指南

Patch 实验用于比较一个候选 Patch 是否在受控旧题回放中提供可复核改进。它不是正式比赛
运行，也不能仅凭一次 Treatment、一次求解器报告或一次自评提升 Patch 状态。

## Baseline 与 Treatment

Baseline 不加载待审 Patch：

```bash
python scripts/export_runtime_pack.py \
  --context full_replay \
  --profile engineering_optimization
```

Treatment 显式加载待审 Patch：

```bash
python scripts/export_runtime_pack.py \
  --context full_replay \
  --profile engineering_optimization \
  --candidate-patch A092
```

`--exclude-patch A127` 只排除已批准 Patch；它不会自动加载状态为 `review_ready` 的 A092，
因此不能作为 A092-only Treatment 的替代命令。

## 实验边界

- Baseline 与 Treatment 必须使用同一题目、材料、Profile、执行合同和明确记录的差异；
- 每次运行要保留 Runtime Pack manifest、材料冻结、环境/执行记录和独立验证结果；
- 无效 attempt、并发覆盖、缺失外部用量或缺失独立验证不得计入有效配对；
- 历史冻结协议和已封存记录不能原地改写；需要失效时使用明确 sidecar 或新运行；
- Patch 状态仅能通过政策、证据和独立检查派生，不由本指南或人工实验笔记直接修改。

完整 Gate 推进见[比赛执行指南](COMPETITION_GUIDE.md)，Patch 选择与 manifest 规则见
[Runtime Pack 指南](RUNTIME_PACK_GUIDE.md)。
