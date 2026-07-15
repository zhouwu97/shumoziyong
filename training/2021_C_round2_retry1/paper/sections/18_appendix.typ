#import "../style.typ": three-line-table, source-note

= 附录

#heading(level: 2, outlined: false)[附录 A：Python 文件清单]

正式 Python 工件共 14 个源文件、4,151 行。表 13 按职责列出文件；论文只嵌入核心求解文件，完整程序随可复现材料提供。

#three-line-table(
  [表 13 #h(0.6em) Python 源文件与职责],
  (2.5fr, 2.8fr),
  ([文件], [职责]),
  (
    [`code/common/common.py`], [官方数据读取、锁定参数与序列化],
    [`code/solver/optimization.py`], [问题二 MILP；问题三、四 LP 正式求解],
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

#heading(level: 2, outlined: false)[附录 B：Python 核心源码]

=== B.1 数据读取与预处理

#source-note[文件：`code/common/common.py`、`code/analysis/artifacts.py`；作用：读取官方 Excel、统一量纲并生成数据审计；输入：附件 1、附件 2 与空白结果模板；输出：标准化数组、材料清单和数据质量工件。]

=== B.2 供应商评价与流程入口

#source-note[文件：`code/run_training.py`；作用：组织供应商评价、问题二至四求解、敏感性分析和结果导出；输入：标准化官方数据与锁定假设；输出：正式结果、验证工件、结果工作簿 A/B 和派生图。]

=== B.3 问题二至四优化模块

#source-note[文件：`code/solver/optimization.py`；作用：使用 SciPy `milp`/HiGHS 构造供应能力、转运能力、单承运商、需求和词典序锁定约束；问题二为 MILP，问题三、四为连续 LP。输入：供应商能力、损耗率、需求与模型参数；输出：问题二至四决策变量、目标值和求解状态。以下保留该核心模块完整源码。]

#raw(read("../../code/solver/optimization.py"), block: true)

=== B.4 独立复算

#source-note[文件：`code/validator/independent_validator.py`；作用：不导入求解器地复算目标值、硬约束和 Excel 回填；输入：正式决策结果与官方数据；输出：约束、目标、模板一致性和故障注入报告。]

#heading(level: 2, outlined: false)[附录 C：MATLAB 文件清单]

MATLAB 独立复现共 8 个源文件、606 行。所有优化模块直接读取 `load_official_data.m` 生成的官方数据统计量，不调用 Python。

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

#heading(level: 2, outlined: false)[附录 D：MATLAB 核心源码]

以下完整列出三个求解函数和硬约束检查函数；数据加载、矩阵构造与总入口保存在同目录的可复现材料中。

=== D.1 问题二 `intlinprog`

#source-note[文件：`solve_problem2.m`；作用：独立完成最小基数、采购成本和运输损耗三阶段 MILP；输入：`load_official_data.m` 产生的官方数据结构；输出：供应商选择、运输流、目标值、库存和退出状态。]

#raw(read("../../code/matlab/solve_problem2.m"), block: true)

=== D.2 问题三 `linprog`

#source-note[文件：`solve_problem3.m`；作用：独立完成少 C、少总原料和少损耗三阶段 LP；输入：官方数据结构；输出：连续运输流、原料结构、库存和退出状态。]

#raw(read("../../code/matlab/solve_problem3.m"), block: true)

=== D.3 问题四 `linprog`

#source-note[文件：`solve_problem4.m`；作用：独立最大化可持续周产能；输入：供应与转运能力、损耗率和原料换算系数；输出：最大周产能、运输流、库存和退出状态。]

#raw(read("../../code/matlab/solve_problem4.m"), block: true)

=== D.4 独立硬约束检查

#source-note[文件：`validate_solution.m`；作用：复核非负性、供应能力、流量平衡、转运能力、到货、生产需求和库存；输入：MATLAB 独立解与官方数据；输出：逐类违反数、最大违反量和业务聚合量。]

#raw(read("../../code/matlab/validate_solution.m"), block: true)

#heading(level: 2, outlined: false)[附录 E：Python-MATLAB 结果交叉验证]

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
    [24 周采购成本], [491125.620530536], [491125.620530303], [$2.32 times 10^(-7)$],
    [24 周运输损耗/m³], [2470.51643049995], [2470.51643050434], [$4.39 times 10^(-9)$],
    [期末库存/m³], [56400.0000003206], [56400], [$3.21 times 10^(-7)$],
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

评分容差预设为 $10^(-9)$，连续量绝对误差容差预设为 $10^(-6)$。表 15、16 所有项目均通过，最大跨语言误差为 $3.20607796311 times 10^(-7)$。离散模型没有用逐单元决策相等作为通过条件，而是要求供应商数量、目标值、最优性状态和硬约束一致。

#heading(level: 2, outlined: false)[附录 F：复现环境与运行命令]

#three-line-table(
  [表 17 #h(0.6em) 双语言复现环境],
  (1.6fr, 3.7fr),
  ([项目], [记录]),
  (
    [Python], [SciPy 1.17.0；HiGHS；正式入口 `python code/run_training.py`],
    [Python 源码], [14 个文件，4,151 行],
    [MATLAB], [24.1.0.2537033（R2024a），PCWIN64],
    [Optimization Toolbox], [24.1；`intlinprog` 与 `linprog` 可用],
    [MATLAB 源码], [8 个文件，606 行],
    [MATLAB 命令], [`matlab -batch "addpath('code/matlab'); run_cross_language_validation(pwd)"`],
    [MATLAB 退出状态], [0],
    [MATLAB 总运行时间], [27.2286188 s],
    [问题二阶段时间], [0.6372922 / 4.8924499 / 16.6143945 s],
    [问题三阶段时间], [0.0991937 / 0.0762684 / 0.0205662 s],
    [问题四时间], [0.0216611 s],
  ),
  alignments: (left, left),
  font-size: 8.2pt,
)

#source-note[运行记录、逐项对照表和完整源文件分别保存在机器可读 JSON、CSV 与代码目录中。论文附录保留核心源码，不包含临时调试代码或本地绝对路径。]
