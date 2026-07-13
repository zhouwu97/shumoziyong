# M3A Trusted-Local 执行威胁模型

## 适用范围

M3A 用于可信操作者在本机运行项目自身生成或人工审核过的数学建模代码。执行资格表示：

> 在 `trusted_local` 合同下，代码、输入、执行参数、原始输出和 Formal Result 之间的证据链已经闭合。

它不是面向陌生用户提交任意代码的在线判题沙箱，也不提供对本机管理员级攻击者的安全边界。

## 信任假设

- 操作者可信；
- 候选代码由本项目生成或已由操作者审核；
- 操作系统、Python、Sandboxie 和机器签名密钥属于可信本机环境；
- 不防御拥有本机管理员权限的恶意攻击者；
- 不要求宿主文件系统全局默认拒绝读取。

## M3A 旨在防止

- Git HEAD 不明确、工作区或暂存区存在意外漂移；
- 未跟踪代码混入执行现场；
- 代码或输入在物化前后发生增删改；
- symlink、junction 或 hardlink 绕过精确 Manifest；
- 实际 argv、工作目录、seed 或环境变量偏离 Execution Spec；
- 结果文件集合被增加、删除或替换；
- 旧执行记录通过 Challenge 重放到新 Run；
- raw output 与 Formal Result 的固定派生合同断链；
- 清理查询失败被误报为清理成功。

## M3A 不旨在防止

- 可信操作者主动伪造证据或滥用机器签名密钥；
- 本机管理员级攻击；
- 已审核候选代码恶意搜索整个宿主文件系统；
- 操作系统、Sandboxie 内核或 Python Runtime 被攻破；
- 所有仓库外文件均不可读。

## 资格条件

`formal_result_eligible=true` 要求以下条件全部成立：

- `execution_trust_model=trusted_local`；
- Git HEAD 固定，工作区、暂存区和未跟踪文件状态干净；
- Code/Input Manifest 精确覆盖且执行前后 SHA 不变；
- Execution Spec、Sandboxie 执行标记、Challenge 和 Output Manifest 验证通过；
- Python SHA 与 `requirements.lock` SHA 已记录；
- 四项 targeted host-read controls 通过；
- 受信 Collector 源码、固定派生合同和 Formal core digest 验证通过；
- 机器签名和清理恢复检查通过。

以下字段只描述边界，不参与 trusted-local 资格：

```text
privacy_mode_available
default_deny_host_reads_verified
```

免费版 Sandboxie 的正常记录应明确表示：

```text
targeted_host_read_controls_passed = true
default_deny_host_reads_verified = false
```

这不能被表述为“所有未声明宿主文件均不可读”。
