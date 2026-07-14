#import "../style.typ": three-line-table, source-note

= 附录

== 附录 A：Python 文件清单

正式 Python 工件共 14 个源文件、3,532 行。表 13 按职责列出文件；论文只嵌入核心求解文件，完整程序随可复现材料提供。

#three-line-table(
  [表 13 #h(0.6em) Python 源文件与职责],
  (2.5fr, 2.8fr),
  ([文件], [职责]),
  (
    [`code/common/common.py`], [官方数据读取、锁定参数与序列化],
    [`code/solver/optimization.py`], [问题二至四 MILP/LP 正式求解],
    [`code/validator/independent_validator.py`], [目标与硬约束独立复算],
    [`code/analysis/artifacts.py`], [数据审计、评分和附件回填],
    [`code/analysis/generate_paper_assets.py`], [论文源数据与旧图工件],
    [`code/analysis/generate_typst_paper_figures.py`], [8 幅黑白 Typst 论文图],
    [`code/analysis/build_paper_docx.py`], [旧 DOCX 生成器，仅作历史工件],
    [`code/final_human_audit.py`], [权重、语义和人工审计证据],
    [`code/run_training.py`], [正式训练流程入口],
    [`code/tests/test_validator.py`], [验证器单元测试],
    [`code/common/__init__.py`], [公共包入口],
    [`code/solver/__init__.py`], [求解器包入口],
    [`code/validator/__init__.py`], [验证器包入口],
    [`code/analysis/__init__.py`], [分析包入口],
  ),
  alignments: (left, left),
  font-size: 8.5pt,
)

== 附录 B：Python 核心源码

以下为正式求解模块 `optimization.py` 的完整源码。它使用 SciPy `milp` 接口调用 HiGHS，构造供应能力、转运能力、单承运商、需求和词典序锁定约束；正文全部锁定结果由该模块产生。

#raw(read("../../code/solver/optimization.py"), block: true)

== 附录 C：MATLAB 文件清单

MATLAB 独立复现共 8 个源文件、552 行。所有优化模块直接读取 `load_official_data.m` 生成的官方数据统计量，不调用 Python。

#three-line-table(
  [表 14 #h(0.6em) MATLAB 源文件与职责],
  (2.6fr, 2.7fr),
  ([文件], [职责]),
  (
    [`load_official_data.m`], [独立读取官方 Excel 与构造参数],
    [`evaluate_suppliers.m`], [四指标评分、排序和权重敏感性],
    [`build_flow_model.m`], [单周线性流模型公共矩阵],
    [`solve_problem2.m`], [`intlinprog` 最小基数与两阶段 MILP],
    [`solve_problem3.m`], [`linprog` 三阶段词典序 LP],
    [`solve_problem4.m`], [`linprog` 最大产能 LP],
    [`validate_solution.m`], [供应、运输、到货、库存约束复核],
    [`run_cross_language_validation.m`], [运行、对照、JSON/CSV 输出],
  ),
  alignments: (left, left),
  font-size: 8.5pt,
)

== 附录 D：MATLAB 核心源码

以下完整列出三个求解函数和硬约束检查函数；数据加载、矩阵构造与总入口保存在同目录的可复现材料中。

=== D.1 问题二 `intlinprog`

#raw(read("../../code/matlab/solve_problem2.m"), block: true)

=== D.2 问题三 `linprog`

#raw(read("../../code/matlab/solve_problem3.m"), block: true)

=== D.3 问题四 `linprog`

#raw(read("../../code/matlab/solve_problem4.m"), block: true)

=== D.4 独立硬约束检查

#raw(read("../../code/matlab/validate_solution.m"), block: true)

== 附录 E：Python-MATLAB 结果交叉验证

#three-line-table(
  [表 15 #h(0.6em) 双语言评价与问题二对照],
  (1.7fr, 1.3fr, 1.3fr, 1.1fr),
  ([比较项], [Python], [MATLAB], [绝对误差]),
  (
    [前 10 排名], [完全一致], [完全一致], [0],
    [前 50 排名], [完全一致], [完全一致], [0],
    [前 50 得分最大误差], [-], [-], [$1.11 times 10^(-16)$],
    [权重敏感性最大误差], [-], [-], [$4.44 times 10^(-16)$],
    [最少供应商数], [26], [26], [0],
    [24 周采购成本], [491125.620530304], [491125.620530303], [$1.16 times 10^(-10)$],
    [24 周运输损耗/m³], [2470.51643050435], [2470.51643050435], [$6.82 times 10^(-12)$],
    [期末库存/m³], [56400], [56400], [0],
  ),
  alignments: (left, right, right, right),
  font-size: 7.9pt,
)

#three-line-table(
  [表 16 #h(0.6em) 双语言问题三、四与约束对照],
  (1.7fr, 1.35fr, 1.35fr, 1.05fr),
  ([比较项], [Python], [MATLAB], [绝对误差]),
  (
    [问题三 A 类/24 周], [207057.104839661], [207057.104839661], [0],
    [问题三 B 类/24 周], [157616.966600894], [157616.966600894], [0],
    [问题三 C 类/24 周], [69507.8406208139], [69507.8406208138], [$1.60 times 10^(-10)$],
    [问题三总原料/24 周], [434181.912061369], [434181.912061369], [$1.16 times 10^(-10)$],
    [问题三损耗/24 周], [2399.75288136428], [2399.75288136428], [$9.09 times 10^(-13)$],
    [问题四周产能], [33335.925461873], [33335.925461873], [$2.18 times 10^(-11)$],
    [问题二至四硬约束], [0], [0], [0],
  ),
  alignments: (left, right, right, right),
  font-size: 7.8pt,
)

评分容差预设为 $10^(-9)$，连续量绝对误差容差预设为 $10^(-6)$。表 15、16 所有项目均通过，最大跨语言误差为 $1.60071067512 times 10^(-10)$。离散模型没有用逐单元决策相等作为通过条件，而是要求供应商数量、目标值、最优性状态和硬约束一致。

== 附录 F：复现环境与运行命令

#three-line-table(
  [表 17 #h(0.6em) 双语言复现环境],
  (1.6fr, 3.7fr),
  ([项目], [记录]),
  (
    [Python], [SciPy 1.17.0；HiGHS；正式入口 `python code/run_training.py`],
    [Python 源码], [14 个文件，3,532 行],
    [MATLAB], [24.1.0.2537033（R2024a），PCWIN64],
    [Optimization Toolbox], [24.1；`intlinprog` 与 `linprog` 可用],
    [MATLAB 源码], [8 个文件，552 行],
    [MATLAB 命令], [`matlab -batch "addpath('code/matlab'); run_cross_language_validation(pwd)"`],
    [MATLAB 退出状态], [0],
    [MATLAB 总运行时间], [14.7648263 s],
    [问题二阶段时间], [0.2512820 / 4.5075268 / 2.6169680 s],
    [问题三阶段时间], [0.1103179 / 0.0792188 / 0.0312026 s],
    [问题四时间], [0.0234103 s],
  ),
  alignments: (left, left),
  font-size: 8.2pt,
)

#source-note[运行记录、逐项对照表和完整源文件分别保存在机器可读 JSON、CSV 与代码目录中。论文附录保留核心源码，不包含临时调试代码或本地绝对路径。]
