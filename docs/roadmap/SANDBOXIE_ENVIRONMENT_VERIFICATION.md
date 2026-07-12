# Milestone 2：Sandboxie 真实环境激活

## 合同边界

本阶段只验证 Sandboxie 运行环境，并将验证报告绑定到 Formal Result、Run Evidence
和 Seal。它不证明完整 Executor、双 Collector、空目录复现、
`engineering_optimization` Profile Qualification 或国奖竞争力。

环境观察必须由 `scripts/verify_sandboxie_environment.py` 生成机器签名证明，不接受在
`capability_evidence` 或 Environment Manifest 中手填状态。Fixture 只能测试 Schema，
永远不能派生环境资格。只有以下条件同时满足，才派生
`sandboxie_environment_verified=true`：

1. Windows 版本与 Build 已记录；
2. `Start.exe`、`SbieSvc.exe`、`SbieDrv.sys` 的路径、版本、文件 SHA-256 和有效签名已绑定；
3. Sandboxie 服务与驱动均处于运行状态；
4. 修改配置前已通过 `SbieIni.exe` 导出逻辑配置备份；
5. 随机命名的临时验证箱能证明 `SbieDll.dll` 已注入；
6. 文件、目录、注册表、权限、子进程和三个网络端点共 12 项真实负控全部通过；
7. 至少两个不同 DNS 端点和两个不同 TCP 端点的宿主网络探针通过；
8. 每项负控绑定探针 SHA、命令摘要、实际目标、起止时间和 stdout/stderr 哈希；
9. terminate/delete 返回码、箱进程前后集合和真实内容目录共同证明清理完成；
10. 公开报告和原始私有报告的 SHA、生成器提交、环境指纹与有效期由不可导出机器私钥签名。

任何一项失败时，报告保持失败状态。Milestone 2 只证明环境，不证明任何 Formal Result
实际在该环境中执行，因此状态固定为：

```text
sandboxie_environment_observed = true
sandboxie_environment_verified = true
formal_result_executed_in_verified_environment = false
formal_result_eligible = false
```

`formal_result_eligible=true` 必须等待 Milestone 3 的 Run 专属执行 Attestation。

## 执行命令

```powershell
python scripts/verify_sandboxie_environment.py `
  --output output/environment/sandboxie-m2/2026-07-12/sandboxie_environment_report.json `
  --private-output tmp/private-sandboxie-evidence/sandboxie_environment_report.raw.json `
  --attestation-output output/environment/sandboxie-m2/2026-07-12/sandboxie_environment_attestation.json `
  --machine-key-id sandboxie-host-d08131d0397a11c0 `
  --certificate-thumbprint d08131d0397a11c0d2d4151f9c68ede76cad57fa
```

原始报告只保存在被忽略的 `tmp/`，Attestation 记录其 SHA-256。仓库公开保存脱敏报告、
配置备份和机器签名 Attestation；用户名和临时路径替换为 `%USERPROFILE%`、`%TEMP%`、
`%PROGRAMFILES%` 和 `%USERNAME%`。公钥注册在
`policies/trusted_environment_registry.json`，私钥不可导出且不进入仓库。

将环境证据绑定到 Run 时，`environment_manifest.json` 必须同时绑定报告和 Attestation。
`build_run_evidence_manifest()` 把三份公开证据加入 Evidence，Seal 再绑定报告双哈希、
Attestation 双哈希、原始报告 SHA、环境指纹、机器密钥 ID 和配置备份 SHA。

能力成熟度派生可显式消费已验证报告：

```powershell
python scripts/derive_capability_maturity.py `
  --evidence <capability-evidence.json> `
  --sandboxie-report tmp/sandboxie-m2/sandboxie_environment_report.json
```

环境报告只完成 Sandboxie 环境验证，不解除 Run 实际执行门禁。Capability 引用深验证
尚未启用，因此当前成熟度上限仍为 `foundation`。

## 安装与回滚口径

验证器只核验已存在的 Sandboxie 安装，不会静默下载、升级或卸载内核驱动。本机本轮为
既有 Sandboxie-Plus 安装，报告使用 `installation.origin=preexisting`；配置变更通过临时
箱和修改前导出实现可逆。本轮没有执行覆盖安装，因此不得声明安装器级回滚已经实测。

如目标机器缺少 Sandboxie，应先使用经批准且已校验 SHA-256/签名的安装器完成可逆安装，
记录安装来源和卸载入口，再运行本验证器。安装、升级、卸载或驱动重启不能由普通测试导入触发。

## 2026-07-12 实机证据

- 报告：`output/environment/sandboxie-m2/2026-07-12/sandboxie_environment_report.json`
- Attestation：`output/environment/sandboxie-m2/2026-07-12/sandboxie_environment_attestation.json`
- 报告 ID：`sandboxie-env-20260712T225758p0800-94ec485ad9fb`
- 脱敏报告 SHA-256：`5d7791cb5439a75921cb561c804540f82bd94a044fce2747db4f480c0162821a`
- Attestation SHA-256：`e3cad47e7b77304daf958fd55ec07ecbcfdb036aabc929f78fa87407eead333a`
- 原始私有报告 SHA-256：`c69dd5a368842edb80feedf08506464699f330d59bc29368a83b88d5fa69f83a`
- 配置备份 SHA-256：`5d67157d5b1b9a83449bfc853669ed700172f6951cb12c9b142e97e3952bd7d7`
- 生成器提交：`5e2acfc86950d2b4785bf4d718f1b0bbe5ad35c3`
- 机器密钥：`sandboxie-host-d08131d0397a11c0`
- 平台：Windows 11 家庭版中文版，Build `26200`，64 位
- Sandboxie-Plus：`1.17.9`；`SbieSvc` 与 `SbieDrv` 均为 `Running`
- 结果：12/12 真实负控、DNS 3/3、TCP 3/3、组件签名、宿主文件/注册表基线和清理回滚全部通过

机器签名证明本机 Sandboxie 环境在报告时间窗口满足本阶段合同。它不属于 Run 实际执行
闭环，不授予 Formal Result eligibility，也不提升 Capability 成熟度上限；`foundation`
上限、Executor 未证明和 Profile 未资格化的边界保持不变。
