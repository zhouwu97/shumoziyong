# Runtime Pack 指南

Runtime Pack 将 base、Profile、适用 Patch 和工作流规则导出为可复现的执行输入，同时以
manifest 记录源文件、版本、选择结果和 SHA-256。它是执行器的规则输入，不是正式结果。

## 选择上下文与 Profile

| 使用场景 | `--context` | Profile 选择 |
|---|---|---|
| 新题比赛或模拟赛 | `new_problem` | 默认保守的 `general`，经 Gate 0 确认后可 Fork 专项 Profile |
| 完整旧题回放 | `full_replay` | 显式指定与题型匹配的专项 Profile |
| 轻量提示词回归 | `prompt_regression` | 仅测试提示词行为，不产生 Gate 或晋级证据 |

例如，导出工程优化旧题的标准运行包：

```bash
python scripts/export_runtime_pack.py --context full_replay --profile engineering_optimization
python scripts/check_runtime_manifest.py
```

默认输出为：

```text
export/cumcm_runtime_pack.md
export/cumcm_runtime_pack.manifest.json
```

运行包应复制到执行工作目录的 `rules/runtime_pack.md`。执行器第一轮只能读取题面和规则，
输出总控诊断与人工确认项；不得自动跨越 Gate。

## Patch 选择规则

默认正式包只自动选择同时满足以下条件的 Patch：

1. `patch_index.json` 记录为 `regression_verified` 或 `competition_evidenced`；
2. Patch 声明支持当前 Profile；
3. 当前导出上下文允许该 Patch。

`review_ready` Patch 不会自动进入正式包。旧题实验可显式加入一个待审 Patch：

```bash
python scripts/export_runtime_pack.py \
  --context full_replay \
  --profile engineering_optimization \
  --candidate-patch B311
```

候选 Patch 必须存在于索引、仍为 `review_ready`，并支持指定 Profile。更详细的 Baseline /
Treatment 隔离规则见[Patch 实验指南](PATCH_EXPERIMENT_GUIDE.md)。

## 检查与可追溯性

- 运行前检查 manifest 的上下文、Profile、Patch 集合与源文件哈希；
- 将 manifest 与 Run 一同冻结，后续不得以覆盖方式更新；
- Profile 成熟度由政策和证据现场派生，不能靠导出时手填；
- Runtime Pack 的存在不证明候选结果正确，仍须经过 Collector 和 Validator。

新题的材料计划、Run 初始化和 Gate 推进见[比赛执行指南](COMPETITION_GUIDE.md)。
