# 2023-B 求解前冻结规格

本目录是 2023 年国赛 B 题的 Gate A-C 建模合同，不是正式 Solver Run，也不构成比赛资格证据。
材料已暴露，固定证据模式为 `reference_exposed_reconstruction`；最高用途仅限单题技术闭环候选。

执行入口：

```powershell
python scripts/validate_modeling_gates.py --case-dir problems/2023_B
```

任何 Bundle 输入变更都必须重新执行 `--freeze`，并使引用旧 Bundle 的 Solver Run 失效。
