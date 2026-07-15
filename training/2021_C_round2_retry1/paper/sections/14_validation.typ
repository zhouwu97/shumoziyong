#import "../style.typ": three-line-table, source-note
#import "../style.typ": locked

= 独立复算与约束验证

== 验证设计

Python 正式求解采用 SciPy/HiGHS 的 MILP/LP 接口 [8-11]。独立检查器不导入求解器模块，只读取官方材料、锁定参数、原始决策变量和输出表，重新计算供应能力、订单响应、运输损耗、到货换算、库存与目标值。这样降低了“求解器与验证器共享同一错误公式”的风险。

#three-line-table(
  [表 12 #h(0.6em) 正式结果验证摘要],
  (1.7fr, 1fr, 1fr, 1fr, 1.4fr),
  ([验证项目], [问题二], [问题三], [问题四], [结论]),
  (
    [独立约束检查次数], [135,961], [136,240], [136,337], [全部通过],
    [硬约束违约数], [0], [0], [0], [通过],
    [目标复算绝对误差], [0], [0], [0], [通过],
    [Excel 决策单元回读], [#locked.template_cells_checked.display], [#locked.template_cells_checked.display], [#locked.template_cells_checked.display], [最大误差 0],
    [故障注入], [合并 #locked.fault_injection_total.display 项], [合并 #locked.fault_injection_total.display 项], [合并 #locked.fault_injection_total.display 项], [#locked.fault_injection_passed.display/#locked.fault_injection_total.display 检出],
  ),
  alignments: (left, right, right, right, center),
  font-size: 8.45pt,
)

问题二相对采购成本复算为 491,125.620530，问题三 24 周 C 类原料复算为 69,507.840621 m³，问题四 24 周产品等价到货复算为 800,062.211085 m³，均与报告值零误差。结果工作簿 A、B 回读逐格比较正式决策与写入值；LibreOffice 重算后无公式错误或空缓存。14 项故障覆盖负订货、能力超限、库存守恒篡改、转运超载、多承运商、损耗和目标篡改等，全部由预期检查器拒绝。

== Python 与 MATLAB 交叉验证

本文以 Python/HiGHS 作为正式优化实现，并使用 MATLAB 对供应商评价、词典序规划、目标值和硬约束进行独立复现。两种实现的主要目标值和聚合决策在预设容差内一致。MATLAB 直接读取官方 Excel，采用 `intlinprog` 求解问题二、`linprog` 求解问题三和问题四；它不调用 Python，也不把 Python 中间结果作为优化输入。前 10、前 50 排名完全一致，评分最大误差为 $1.11 times 10^(-16)$，全部连续量的最大跨语言误差为 $3.21 times 10^(-7)$，低于 $10^(-6)$ 验收阈值；两端硬约束违约均为 0。具体版本、命令和退出状态见附录 E、F。

#source-note[验证回答的是“决策是否满足本文定义的模型”，不证明历史期望能力会在未来逐周实现，也不替代对价格、仓容和供应中断概率的现场核验。]
