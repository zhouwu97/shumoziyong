function result = solve_problem4(data)
%SOLVE_PROBLEM4 用 linprog 独立最大化损耗后产品等价周到货量。

candidates = find(data.regularCapacity > data.tolerance);
model = build_flow_model(data, candidates, false);
options = optimoptions("linprog", "Algorithm", "dual-simplex-highs", ...
    "Display", "off", "ConstraintTolerance", 1e-9, ...
    "OptimalityTolerance", 1e-9, "MaxIterations", 1e6);
tic;
[x, objective, exitflag, output] = linprog(-model.productCoefficient, ...
    model.A, model.b, [], [], model.lb, model.ub, options);
runtime = toc;
assert(exitflag > 0, "问题四最大产能模型未得到最优解");

flow = reshape(x, model.m, model.n)';
supply = sum(flow, 2);
candidateTypes = data.materialTypes(candidates);
result.candidates = candidates;
result.flow = flow;
result.expectedSupply = supply;
result.aSupply = sum(supply(candidateTypes == "A"));
result.bSupply = sum(supply(candidateTypes == "B"));
result.cSupply = sum(supply(candidateTypes == "C"));
result.totalRaw = sum(supply);
result.transportLoss = model.lossCoefficient' * x;
result.maximumWeeklyCapacity = -objective;
result.productArrival = -objective;
result.exitflag = exitflag;
result.runtime = runtime;
result.output = output;
end
