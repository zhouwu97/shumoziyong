# Milestone 2：Sandboxie 真实环境激活

## 合同边界

本阶段只验证 Sandboxie 运行环境，并将验证报告绑定到 Formal Result、Run Evidence
和 Seal。它不证明完整 Executor、双 Collector、空目录复现、
`engineering_optimization` Profile Qualification 或国奖竞争力。

环境激活必须由 `scripts/verify_sandboxie_environment.py` 生成报告，不接受在
`capability_evidence` 或 Environment Manifest 中手填状态。报告只有同时满足以下条件
才派生 `sandboxie_environment_verified=true` 和 `formal_result_eligible=true`：

1. Windows 版本与 Build 已记录；
2. `Start.exe`、`SbieSvc.exe`、`SbieDrv.sys` 的路径、版本、文件 SHA-256 和有效签名已绑定；
3. Sandboxie 服务与驱动均处于运行状态；
4. 修改配置前已通过 `SbieIni.exe` 导出逻辑配置备份；
5. 随机命名的临时验证箱能证明 `SbieDll.dll` 已注入；
6. 文件、目录、注册表、权限、子进程和三个网络端点共 12 项真实负控全部通过；
7. 至少两个不同 DNS 端点和两个不同 TCP 端点的宿主网络探针通过；
8. 验证箱进程、内容和配置均已删除，配置导出与修改前完全一致。

任何一项失败时，报告保持失败状态，Formal Result verifier 拒绝激活。

## 执行命令

```powershell
python scripts/verify_sandboxie_environment.py `
  --output tmp/sandboxie-m2/sandboxie_environment_report.json
```

报告旁会生成 `sandboxie_config_backup.txt`。将环境用于正式 Run 时，Collector 必须把
这两个文件复制到 Run 根目录，并由 `environment_manifest.json` 同时绑定报告文件哈希、
报告语义哈希和配置备份哈希。`build_run_evidence_manifest()` 会把二者加入 Evidence，
`finalize_run_evidence.py` 再把报告 ID、报告双哈希和配置备份哈希写入 Seal。

能力成熟度派生可显式消费已验证报告：

```powershell
python scripts/derive_capability_maturity.py `
  --evidence <capability-evidence.json> `
  --sandboxie-report tmp/sandboxie-m2/sandboxie_environment_report.json
```

环境报告只解除 Formal Result 的真实环境门禁。Capability 引用深验证尚未启用，
因此当前成熟度上限仍为 `foundation`。

## 安装与回滚口径

验证器只核验已存在的 Sandboxie 安装，不会静默下载、升级或卸载内核驱动。本机本轮为
既有 Sandboxie-Plus 安装，报告使用 `installation.origin=preexisting`；配置变更通过临时
箱和修改前导出实现可逆。本轮没有执行覆盖安装，因此不得声明安装器级回滚已经实测。

如目标机器缺少 Sandboxie，应先使用经批准且已校验 SHA-256/签名的安装器完成可逆安装，
记录安装来源和卸载入口，再运行本验证器。安装、升级、卸载或驱动重启不能由普通测试导入触发。

## 2026-07-12 实机证据

- 报告：`output/environment/sandboxie-m2/2026-07-12/sandboxie_environment_report.json`
- 报告 ID：`sandboxie-env-20260712T211811p0800-465d9145c3ee`
- 报告文件 SHA-256：`ba715681d0244dfa81493f686444abc127b40d988a34929473a0d2a1cdfbac5f`
- 配置备份 SHA-256：`5d67157d5b1b9a83449bfc853669ed700172f6951cb12c9b142e97e3952bd7d7`
- 平台：Windows 11 家庭版中文版，Build `26200`，64 位
- Sandboxie-Plus：`1.17.9`；`SbieSvc` 与 `SbieDrv` 均为 `Running`
- 结果：12/12 真实负控、DNS 3/3、TCP 3/3、组件签名、宿主文件/注册表基线和清理回滚全部通过

该报告证明本机 Sandboxie 环境满足本阶段合同。它不属于完整执行闭环，也不提升
Capability 成熟度上限；`foundation` 上限、Executor 未证明和 Profile 未资格化的边界保持不变。
