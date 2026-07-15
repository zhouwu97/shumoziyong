function result = solve_problem2(data)
%SOLVE_PROBLEM2 在全部供应商上独立求解基数、成本和损耗三阶段 MILP。

candidates = find(data.regularCapacity > data.tolerance);
model = build_flow_model(data, candidates, true);
flowIdx = 1:model.flowCount;
assignIdx = model.flowCount + (1:model.flowCount);
A0 = [model.A; sparse(1, flowIdx, -model.productCoefficient, 1, numel(model.lb))];
b0 = [model.b; -data.demand];

% 第一阶段直接在完整运输模型中最小化启用供应商数。
fSelection = zeros(numel(model.lb), 1);
fSelection(assignIdx) = 1;
selectionOptions = optimoptions("intlinprog", "Display", "off", ...
    "RelativeGapTolerance", 0, "AbsoluteGapTolerance", 1e-9, ...
    "ConstraintTolerance", 1e-9, "MaxTime", 300);
tic;
[z, minimumCount, exitflagSelection, outputSelection] = intlinprog( ...
    fSelection, model.intcon, A0, b0, [], [], model.lb, model.ub, selectionOptions);
selectionRuntime = toc;
assert(exitflagSelection > 0, "问题二最小供应商模型未得到最优解");

% 后续阶段只锁定最小基数值，不固定具体供应商名单。
selectionRow = sparse(1, assignIdx, 1, 1, numel(model.lb));
A1 = [A0; selectionRow; -selectionRow];
b1 = [b0; round(minimumCount); -round(minimumCount)];
costObjective = [model.costCoefficient; zeros(numel(model.lb) - model.flowCount, 1)];
lossObjective = [model.lossCoefficient; zeros(numel(model.lb) - model.flowCount, 1)];
options = optimoptions("intlinprog", "Display", "off", ...
    "RelativeGapTolerance", 0, "AbsoluteGapTolerance", 1e-9, ...
    "ConstraintTolerance", 1e-9, "MaxTime", 300);

tic;
[xCost, costValue, exitflagCost, outputCost] = intlinprog(costObjective, ...
    model.intcon, A1, b1, [], [], model.lb, model.ub, options);
runtimeCost = toc;
assert(exitflagCost > 0, "问题二采购成本阶段未得到最优解");

costRow = sparse(1, flowIdx, model.costCoefficient, 1, numel(model.lb));
A2 = [A1; costRow];
b2 = [b1; costValue + data.tolerance];
tic;
[xLoss, lossValue, exitflagLoss, outputLoss] = intlinprog(lossObjective, ...
    model.intcon, A2, b2, [], [], model.lb, model.ub, options);
runtimeLoss = toc;
assert(exitflagLoss > 0, "问题二运输损耗阶段未得到最优解");

flow = reshape(xLoss(1:model.flowCount), model.m, model.n)';
result.minimumSupplierCount = round(minimumCount);
assignment = reshape(xLoss(assignIdx), model.m, model.n)';
result.selectionVector = sum(assignment, 2);
result.candidates = candidates;
result.flow = flow;
result.expectedSupply = sum(flow, 2);
result.productArrival = model.productCoefficient' * xLoss(1:model.flowCount);
result.purchaseCost = model.costCoefficient' * xLoss(1:model.flowCount);
result.transportLoss = lossValue;
result.inventory = 2 * data.demand * ones(25, 1);
result.exitflags = [exitflagSelection, exitflagCost, exitflagLoss];
result.runtimes = [selectionRuntime, runtimeCost, runtimeLoss];
result.outputs = {outputSelection, outputCost, outputLoss};
end
