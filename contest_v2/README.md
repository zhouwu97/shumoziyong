# Contest Production v2

`contest_v2` 是面向数学建模比赛的轻量生产链，权威关系为：

```text
result.json → verification.json → result_ledger.json
            → paper/generated/results.typ → submission.pdf
```

公开命令只有：

```powershell
python scripts/contest.py init <run-dir> --contest-id <id> --questions q1 q2 q3
python scripts/contest.py status <run-dir>
python scripts/contest.py verify <run-dir> --mode contest_standard
python scripts/contest.py package <run-dir>
```

安装为可编辑包后也可直接使用 `contest` 命令。完整架构边界见 `docs/CONTEST_V2_ARCHITECTURE.md`。

## 2024-C packaging smoke

`contest_v2.migrate_2024c` 读取历史 Run，只验证包装能力：

```powershell
python -m contest_v2.migrate_2024c --source-run ../runs/2024C_v21_full_replay_20260715 --target-run runs/2024C-packaging-smoke
python scripts/contest.py verify runs/2024C-packaging-smoke
python scripts/contest.py package runs/2024C-packaging-smoke
```

成功标识只能写作 `PACKAGING_SMOKE_PASS`。它不代表官方材料到模型与结果的真实生产试点，更不代表资格认证或奖项水平。
