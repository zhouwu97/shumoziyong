#import "../style.typ": locked

= 问题四：模型预测最大周产能

== 目标函数与动态库存下界

问题四使用所有具有常规期望供货上限的供应商，保留 @eq-supply-cap、@eq-carrier-cap、@eq-received 和 @eq-arrival 的能力、运输、损耗与换算关系，并将周产能 $D$ 作为决策变量：

$
  max_(x,D) D,
  quad D = sum_(i,j) frac(x_(i j)(1 - ell_j), q_(k(i))).
$ <eq-capacity-objective>

24 周库存下界随产能同步变化：

$
  I_0 = 2D,
  quad I_t = I_(t-1) + A_t - D,
  quad I_t >= 2D.
$ <eq-capacity-inventory>

@eq-capacity-objective 最大化稳定周流量，@eq-capacity-inventory 用于排除一次性初始库存释放带来的产能高估。平稳方案满足 $A_t=D$，库存维持在 $2D$。若仍固定使用基准安全库存 #locked.initial_inventory.display m³，会低估产能提高后的缓冲需求。因此，该目标对应企业已提前建立 $2D$ 安全库存时的确定性稳态上界；从现有库存实施还需安排过渡期。

该模型为连续 LP。上界由供应商历史期望能力、各转运商 6,000 m³/周容量、预测损耗率和三类原料换算系数共同决定。
