# 工作目录自动执行指南

## 用户操作

```text
题目工作目录/
└─ problem/
   ├─ 题面.pdf
   ├─ 附件.xlsx
   └─ 输出模板.xlsx
```

用户不需要输入 CLI、Run ID、Profile 路径或 Gate 提示词。AI 使用
[固定入口](../entrypoints/AI_WORKSPACE_BOOTSTRAP.md)完成发现、预检、Bootstrap 和任务循环。

## 目录隔离

- `problem/`：原始材料，只读；
- `.shumo/engine/`：固定 commit 的 detached 引擎；
- `.shumo/env/`：独立环境；
- `.shumo/runs/`：Run 与证据；
- `project/`：本题代码、处理与图表；
- `handoffs/reviewer/package/`：Reviewer 唯一允许读取的固定哈希包；
- `final/`：最终论文、结果和验证交付。

工作区采用 `trusted_local` 信任模型。advisory 是行为提示，enforced 是编排器实际检查的解析后
路径根和命令白名单；这不是敌对环境安全沙箱。

## 离线与引擎锁定

正式比赛只使用已批准 tag、allowlisted commit 或本机已验证提交，不自动 fetch/pull。训练也在
初始化后锁定具体 SHA。依赖优先使用校验过的已有环境，其次使用 `.shumo/env` 和带哈希的
`requirements.lock`；缺失本地 wheel/cache 时进入人工确认或阻断，不修改系统 Python。

## Compatibility sidecar

既有冻结 Run 使用独立 sidecar 根目录，通过以下字段保持资格边界：

```json
{
  "orchestration_mode": "compatibility_sidecar",
  "qualification_eligible": false,
  "promotion_evidence": false,
  "original_run_unchanged": true
}
```

编排器记录冻结身份文件的 SHA-256；`check` 会检查漂移。sidecar 只能补充编排事实，不能修改
Runtime Pack、Run ID、Problem ID 或原转换历史。

## 恢复和幂等

`.shumo/locks/orchestrator.lock` 保证同一时刻只有一个 active attempt。Bootstrap 先写
`.shumo/attempts/<attempt_id>/`，校验后再原子提交；失败保留 `BLOCKER_REPORT.json`。
重复绑定同一 Run 返回既有 workspace，绑定不同 Run 则阻断。`resume` 清理原子写临时文件，
然后从 Run 转换事实重新生成 NEXT_TASK。
