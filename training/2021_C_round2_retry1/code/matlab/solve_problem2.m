function result = solve_problem2(data)
%SOLVE_PROBLEM2 用 intlinprog 独立求解最小基数及两阶段正式 MILP。

bestLoss = min(data.lossMean);
ability = data.regularCapacity .* (1 - bestLoss) ./ data.rawPerProduct;

% 先用 402 个二元变量直接求最小供应商数。
fSelection = ones(numel(ability), 1);
ASelection = -ability';
bSelection = -data.demand;
selectionOptions = optimoptions("intlinprog", "Display", "off", ...
    "RelativeGapTolerance", 0, "AbsoluteGapTolerance", 1e-9, ...
    "ConstraintTolerance", 1e-9, "MaxTime", 300);
tic;
[z, minimumCount, exitflagSelection, outputSelection] = intlinprog( ...
    fSelection, 1:numel(ability), ASelection, bSelection, [], [], ...
    zeros(numel(ability), 1), ones(numel(ability), 1), selectionOptions);
selectionRuntime = toc;
assert(exitflagSelection > 0, "问题二最小供应商模型未得到最优解");

% 固定能力降序的最小基数集合，复现正式模型的确定性候选口径。
[~, order] = sortrows([-ability, (1:numel(ability))'], [1, 2]);
candidates = order(1:round(minimumCount));
assert(sum(ability(candidates)) >= data.demand - data.tolerance, ...
    "最小基数候选集合不能覆盖需求");

model = build_flow_model(data, candidates, true);
flowIdx = 1:model.flowCount;
A0 = [model.A; sparse(1, flowIdx, -model.productCoefficient, 1, numel(model.lb))];
b0 = [model.b; -data.demand];
costObjective = [model.costCoefficient; zeros(numel(model.lb) - model.flowCount, 1)];
lossObjective = [model.lossCoefficient; zeros(numel(model.lb) - model.flowCount, 1)];
options = optimoptions("intlinprog", "Display", "off", ...
    "RelativeGapTolerance", 0, "AbsoluteGapTolerance", 1e-9, ...
    "ConstraintTolerance", 1e-9, "MaxTime", 300);

tic;
[xCost, costValue, exitflagCost, outputCost] = intlinprog(costObjective, ...
    model.intcon, A0, b0, [], [], model.lb, model.ub, options);
runtimeCost = toc;
assert(exitflagCost > 0, "问题二采购成本阶段未得到最优解");

costRow = sparse(1, flowIdx, model.costCoefficient, 1, numel(model.lb));
A1 = [A0; costRow];
b1 = [b0; costValue + data.tolerance];
tic;
[xLoss, lossValue, exitflagLoss, outputLoss] = intlinprog(lossObjective, ...
    model.intcon, A1, b1, [], [], model.lb, model.ub, options);
runtimeLoss = toc;
assert(exitflagLoss > 0, "问题二运输损耗阶段未得到最优解");

flow = reshape(xLoss(1:model.flowCount), model.m, model.n)';
result.minimumSupplierCount = round(minimumCount);
result.selectionVector = z;
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
