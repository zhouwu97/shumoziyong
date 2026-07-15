# 独立检查器设计

`code/validator/independent_validator.py` 不导入 `solver`。输入仅为官方附件、本轮假设、`raw_solution.json`和输出附件A/B；它重算供应商指标、成本、损耗、接收量、产品等价量和库存。

函数覆盖：`recompute_supplier_metrics`、`recompute_objective`、`check_supplier_selection`、`check_order_nonnegative`、`check_supplier_capacity`、`check_material_conversion`、`check_weekly_production_requirement`、`check_inventory_balance`、`check_initial_inventory`、`check_terminal_inventory`、`check_transporter_capacity`、`check_supplier_transporter_assignment`、`check_transport_loss`、`check_arrival_quantity`、`check_order_transport_consistency`、`check_excel_output_consistency`、`check_units_and_aggregation`、`check_all_constraints`。

问题3/4的分运数作为软指标报告；问题2为硬约束。故障注入在真实问题2输出上篡改14类错误，必须全部被定向检查发现。
