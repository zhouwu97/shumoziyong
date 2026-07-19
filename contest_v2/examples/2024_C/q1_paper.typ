#import "../../paper/generated/results.typ": *
= 问题一：确定性种植规划

令所有参数取 2023 年基准值，分别令 $alpha=0$ 与 $alpha=0.5$ 求解统一模型。两种机制的七年利润为 #q1-waste-profit 和 #q1-discount-profit，所有容量、适宜性、轮作与豆类窗口的最大约束超限为 #q1-max-constraint-violation。

#figure(image("figures/scenario_profit.png", width: 70%), caption: [超产浪费与超产半价销售的七年利润。])

#figure(image("figures/yearly_profit.png", width: 80%), caption: [两种销售机制的年度利润。])

两种机制最终选择了完全相同的种植面积配置，因此正式面积表内容及文件哈希相同。半价机制的利润增加完全来自同一产量中超出销量上限部分由零收入改为半价收入，不能表述为“半价销售改变了配置”。主要作物累计面积也因此重合。

#figure(image("figures/crop_area.png", width: 80%), caption: [两种销售机制下主要作物七年累计面积；两组柱形重合。])

#figure(image("figures/resource_usage.png", width: 80%), caption: [浪费机制方案的季次归一化容量占用率。水浇地和大棚以地块面积乘可用季次数为分母。])

两个 MILP 的单次时限均为 60 秒，目标相对 gap 为 1%。候选经两种销售函数交叉评价后，记录的最大源 MIP gap 为 #q1-max-mip-gap。该 gap 支持“时限内高质量可行方案”的表述，但不构成跨目标方案的全局最优证明。
