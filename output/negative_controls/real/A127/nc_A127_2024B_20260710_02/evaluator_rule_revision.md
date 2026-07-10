# 自动评估规则修订记录

首次自动评估中：

- treatment：pass
- baseline：fail

baseline 失败仅因 evaluator 要求未加载 Patch 的 reason 必须逐字包含“未加载”。

原始 AI 输出已经结构化记录：
- A127 enabled=false
- runtime manifest 的 patches 数组为空
- A127 被显式排除

因此本次失败属于自然语言固定词匹配造成的误判，不属于 Patch 误触发，也不属于实验输出篡改。

处理原则：
- 不修改原始 response.json
- 不重新生成 AI 输出
- 保存 evaluator v1.1.0 的失败结果
- 修复通用评估规则并增加回归测试
- 使用同一份原始 response.json 重新执行评估
