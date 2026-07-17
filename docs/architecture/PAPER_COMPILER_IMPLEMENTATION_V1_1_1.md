# 数学建模论文写作编译系统实施计划 v1.1.1

> 本文件冻结第一阶段施工接口。架构范围沿用 v1.1，不扩展全文编译或生产资格。

## 第一阶段目标

使用一个历史题、一个子问题、两个章节和四至六张表达卡片，验证：

```text
上游事实权威
→ 只读事实投影
→ 人工论证图
→ 结构化事实实现计划
→ 确定性渲染
→ 事实回填验证
→ A/B/C 探索性盲评
```

## 接口冻结表

| 接口 | 输入 | 输出 | 权威性 | 是否可人工修改 |
|---|---|---|---|---|
| Claim Map v2 | Formal Result、验证证据 | 语义 Claim | 上游权威 | 否 |
| Claim Binding | 结果 JSON、JSON Pointer、显示规则 | 数值与公式绑定 | 上游权威 | 否 |
| Fact Projection | Claim、Binding、公式与图表 | 写作事实视图 | 派生只读 | 否 |
| Argument Graph | Fact Projection | 论证节点与边 | 规划产物 | 第一阶段人工构建 |
| Realization Plan | Graph、卡片 | 文本段与事实引用 | 生成中间表示 | 否 |
| Renderer | Realization Plan、Projection | 带事实标记正文 | 确定性产物 | 否 |
| Human Edit | 正文 | 修改稿 | 人工产物 | 是，但必须重新验证 |
| Validator | 修改稿、Projection、Plan | 验证报告 | 准入依据 | 否 |

## 开工前置契约

1. 生成器不得直接生成数字、单位或公式，只能输出 `text` 与 `fact_ref` 段。
2. Claim Map 管理语义与证据，Claim Binding 管理来源与显示，Fact Projection 只负责按稳定键合并。
3. 数字豁免只能由受信解析器按文件哈希和字节范围产生；未识别数字默认按语义数字处理。
4. `attribution` 必须声明 `descriptive`、`mechanistic` 或 `causal`，并绑定相应证据等级与动词边界。
5. Candidate 模式允许 `task_adapted` 卡片；Production 模式只允许已确认资格的版本化卡片包。
6. 第一阶段盲评仅产生 `continue`、`revise` 或 `stop`，不得晋级 `production_ready`。
7. 卡片包身份同时绑定卡片 ID、仓库内路径、文件 SHA-256 和包内容 SHA-256；检索与渲染都必须重新校验。
8. 已创建的外部评阅文件不得被试点重建命令覆盖，AI 不得填写或签署评阅结果。

## 第一阶段重合检查协议

- 中文按字符级比较，不引入可变分词词典；英文统一转为小写。
- 移除空白、标点、数字和行内公式后计算。
- 字符 n-gram 取 `n=8`，重合率上限为 `0.35`。
- 最长连续重合上限为 `19` 个字符，高辨识度短语从 `16` 个字符起报告。
- 自动结果只用于筛查；人工原文复用复核保持 `pending` 时不得声称抄袭检查完成。

## 固定施工顺序

```text
锁定目标提交
→ 核对 Claim Map 与 Claim Binding
→ 定义事实实现协议
→ 建立只读事实投影
→ 冻结最小论证词表
→ 手工建立一个子问题论证图
→ 提取候选卡片
→ 编译两个章节
→ 运行故障注入
→ 生成 A/B/C
→ 外部探索性盲评
```

外部人工盲评和 PR 合并状态必须由真实人员或仓库状态确认，AI 不得代签。

## 自动状态作用域

`automated_status: passed` 只表示 `paper_compiler_v1_1_1_pilot` 范围通过，不代表仓库全绿。统一边界报告必须分别记录：

```text
pilot_orchestrator
paper_tests
repository_validator
full_test_suite
```

已知仓库失败只能作为带基准提交证据的 `known_preexisting` 异常保留，不能跳过或改写成通过。标准测试入口固定为 `python -m pytest`，不得混用指向其他 Python 环境的裸 `pytest.exe`。

## 探索性评审冻结

评审开始前生成 `review_freeze_manifest.json`，冻结 A/B/C、协议、评分 Schema、判定策略、卡片包、自动原文检查、资格边界和试点源码快照。工作树未提交时：

```text
pilot_commit_sha: null
working_tree_clean: false
source_snapshot_sha256: <实际快照摘要>
```

不得用基础提交冒充试点提交。评委 1、评委 2 和必要时的仲裁者使用不同排列；映射只保存在 `private/review_keys.json`，评委包中不得出现映射。

冻结后重复编排只能校验并复用材料。任一冻结文件哈希变化时必须 fail-closed；不得自动刷新冻结时间、覆盖人工评阅或替换 A/B/C。

人工评审顺序为：

```text
两名评委独立填写
→ 校验完整性
→ 完成人工原文复核
→ 必要时仲裁
→ 解盲并派生 continue / revise / stop
```

即使结论为 `continue`，也只能扩大试点或进入下一版研究，不能直接授予生产资格。
