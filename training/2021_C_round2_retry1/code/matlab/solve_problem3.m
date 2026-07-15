function result = solve_problem3(data)
%SOLVE_PROBLEM3 用 linprog 独立求解 C类、总原料、损耗三阶段 LP。

candidates = find(data.regularCapacity > data.tolerance);
model = build_flow_model(data, candidates, false);
A0 = [model.A; -model.productCoefficient'];
b0 = [model.b; -data.demand];
options = optimoptions("linprog", "Algorithm", "dual-simplex-highs", ...
    "Display", "off", "ConstraintTolerance", 1e-9, ...
    "OptimalityTolerance", 1e-9, "MaxIterations", 1e6);

candidateTypes = data.materialTypes(candidates);
cObjective = repelem(double(candidateTypes == "C"), model.m);
tic;
[xC, cValue, exitflagC, outputC] = linprog(cObjective, A0, b0, ...
    [], [], model.lb, model.ub, options);
runtimeC = toc;
assert(exitflagC > 0, "问题三 C 类最少阶段未得到最优解");

A1 = [A0; cObjective'];
b1 = [b0; cValue + data.tolerance];
tic;
[xRaw, rawValue, exitflagRaw, outputRaw] = linprog(model.rawCoefficient, ...
    A1, b1, [], [], model.lb, model.ub, options);
runtimeRaw = toc;
assert(exitflagRaw > 0, "问题三总原料最少阶段未得到最优解");

A2 = [A1; model.rawCoefficient'];
b2 = [b1; rawValue + data.tolerance];
tic;
[xLoss, lossValue, exitflagLoss, outputLoss] = linprog(model.lossCoefficient, ...
    A2, b2, [], [], model.lb, model.ub, options);
runtimeLoss = toc;
assert(exitflagLoss > 0, "问题三损耗最少阶段未得到最优解");

flow = reshape(xLoss, model.m, model.n)';
supply = sum(flow, 2);
result.candidates = candidates;
result.flow = flow;
result.expectedSupply = supply;
result.aSupply = sum(supply(candidateTypes == "A"));
result.bSupply = sum(supply(candidateTypes == "B"));
result.cSupply = sum(supply(candidateTypes == "C"));
result.totalRaw = sum(supply);
result.transportLoss = lossValue;
result.productArrival = model.productCoefficient' * xLoss;
result.exitflags = [exitflagC, exitflagRaw, exitflagLoss];
result.runtimes = [runtimeC, runtimeRaw, runtimeLoss];
result.outputs = {outputC, outputRaw, outputLoss};
end
