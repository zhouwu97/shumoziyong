# 模板注册与选择合同

`runtime_contracts/template_source_manifest_v1.json` 是固定提交 `be9c59c1` 中论文模板的本仓提取清单，
仅包含来源路径、逐文件哈希、入口和引擎元数据，不包含上游模板正文。`.vendor/mathmodelagent/` 始终是忽略且
只读的 Source Asset，不进入 Runtime Pack，也不注册为 Agent 能力。

## 注册与校验

同步上游后，可确定性重建并核对清单：

```powershell
python scripts/upstream/sync_mathmodelagent.py
python scripts/paper/template_registry.py generate
python scripts/paper/template_registry.py validate --verify-source
```

普通 CI 不依赖 `.vendor`：注册表的 17 个逻辑键、34 套模板、路径闭包、文件大小和 SHA-256 会与已提交的
`upstream/mathmodelagent.sha256.json` 交叉验证。发布资格流程可增加 `--verify-source`，逐文件核对本地 Source Asset。

## 选择优先级

选择顺序固定为：Runtime Profile 明确绑定 > 当前 Run 明确选择 > 赛事/语言默认 > 上游语言默认。未知的显式
Profile 或 Run 选择失败即关闭，不得静默落到其他赛事模板。每个逻辑键默认使用 Typst，回退 XeLaTeX，并记录
`upstream_default_overridden=true`；只有实际选中上游默认键且显式使用其 XeLaTeX 默认时该字段为 `false`。

Windows 执行参数由 `runtime_contracts/template_overlay_v1.json` 提供。覆盖层只定义路径、可执行文件候选和命令，
不改写模板正文；物化前必须完成来源闭包校验，然后复制到 Run 的独立论文目录。
