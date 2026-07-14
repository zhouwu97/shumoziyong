# 双语言执行与交叉验证合同

## 1. 目的与边界

本合同用于证明同一数学建模结果由两种语言真实执行并完成独立交叉验证。它只定义通用证据结构和只读检查规则，不执行具体题目的求解程序，不生成 MATLAB 模型，也不接入 Gate、Schema、A092 或现有工作流。

比赛 Profile 可以通过 `required_languages` 声明必须执行的语言。当前示例要求：

| 语言 | 角色 | 含义 |
| --- | --- | --- |
| Python | `primary_solver` | 主求解器，产生候选结果 |
| MATLAB | `independent_reproducer` | 独立复现器，从共同原始输入重新计算 |

`required_languages` 中任一语言未真实执行时，双语言验证不得通过。仅存在源码、命令文件或输出文件不能替代运行证据。

双语言要求不是模板默认值。普通单语言项目可以声明：

```json
{
  "profile_id": "cumcm_python_only_v1",
  "required_languages": ["python"]
}
```

此时缺少 MATLAB 证据不会报错，也不要求交叉语言比较。只有 Profile 同时要求 Python 和 MATLAB 时，检查器才启用双语言验证合同。

## 2. 双语言执行证据

执行证据文件顶层包含：

```json
{
  "schema_version": "1.0.0",
  "evidence_id": "dual-language-run-001",
  "example_only": false,
  "profile": {
    "profile_id": "cumcm_python_matlab_v1",
    "required_languages": ["python", "matlab"],
    "language_roles": {
      "python": "primary_solver",
      "matlab": "independent_reproducer"
    }
  },
  "executions": {}
}
```

每个已执行语言必须记录：

- `status=executed`；
- `execution_observed=true`；
- 语言和运行时版本；
- Python 的 `dependencies` 或 MATLAB 的 `toolboxes`；
- 实际命令参数；
- 实际工作目录 `cwd`；
- 带时区的开始、结束时间；
- 退出码；
- stdout、stderr 的 SHA-256；
- 源码 Manifest 的路径和 SHA-256；
- 输入 Manifest 的路径和 SHA-256；
- 输出 Manifest 的路径和 SHA-256。

所有 SHA-256 均为 64 位小写十六进制。即使 stdout 或 stderr 为空，也必须记录空文件的真实 SHA-256。

### 2.1 MATLAB 独立性

MATLAB 执行记录必须包含：

```json
{
  "isolation": {
    "invokes_python": false,
    "reads_python_intermediates": false,
    "input_origin": "shared_official_inputs"
  }
}
```

检查器还会拒绝 MATLAB 命令中出现 Python 调用，并要求 Python 与 MATLAB 的输入 Manifest SHA 一致。该一致性表示二者读取同一组原始输入，不表示 MATLAB 可以读取 Python 的输出或预计算中间量。

源码 Manifest 应覆盖 MATLAB 入口脚本及其直接依赖。独立性最终仍需由源码审查或运行沙箱证明；本检查器只验证证据合同中是否明确记录并满足隔离声明。

### 2.2 环境阻塞

MATLAB 环境不存在时必须记录：

```json
{
  "status": "blocked_environment",
  "verification_status": "not_verified",
  "environment_blocker": {
    "reason": "MATLAB executable not found",
    "probe_command": ["matlab", "-batch", "version"],
    "observed_stderr_sha256": "..."
  }
}
```

该状态的检查结果为 `blocked_environment`，`passed=false`。不得补写虚假版本、退出码或输出 Manifest，也不得将未执行源码标记为 `verified`。

## 3. 交叉验证证据

交叉验证必须引用 Python 和 MATLAB 的输出 Manifest SHA，并比较以下四类内容：

1. 目标值：按绝对容差和相对容差比较；
2. 硬约束：两侧都必须满足，最大违反量不得超过容差；
3. 关键业务聚合量：例如供应商数量、总成本、总产量或库存下界；
4. 最优性状态：例如 `optimal`、`proven_optimal` 或明确限定的可行候选状态。

变量级结果可以采用两种比较模式：

- `exact`：变量 Manifest SHA 必须完全一致；
- `equivalent_optimum`：允许决策变量不同，但目标值、硬约束、关键业务聚合量和最优性状态必须一致。

`equivalent_optimum` 不能用于掩盖目标差异、不可行解或最优性声明强度不一致。

## 4. 检查器

```powershell
python scripts/paper/check_dual_language_evidence.py `
  --execution dual_language_execution.json `
  --validation cross_language_validation.json `
  --output dual_language_check.json
```

退出码：

- `0`：合同通过；
- `1`：证据缺失或不一致；
- `2`：环境阻塞，未验证通过。

检查器不会运行证据中的命令，不会导入求解器，也不会读取具体题目的决策变量文件。它只验证 JSON 证据的完整性、隔离声明和跨语言比较结果。

## 5. 禁止声明

- 未运行 MATLAB 时不得声明双语言验证通过；
- 只有 `.m` 文件或 MATLAB 输出文件时不得声明已执行；
- MATLAB 调用 Python 或读取 Python 中间量时不得声明独立复现；
- 只比较目标值、不比较硬约束和业务聚合量时不得声明交叉验证完成；
- `blocked_environment` 不得转换为 `passed`；
- 示例文件带有 `example_only=true`，不能作为真实执行证据提交。
