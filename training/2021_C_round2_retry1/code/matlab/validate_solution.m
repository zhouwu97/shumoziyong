function validation = validate_solution(data, result, problemNumber)
%VALIDATE_SOLUTION 独立复核 MATLAB 决策的供应、运输、损耗和库存约束。

tol = data.tolerance;
candidates = result.candidates(:);
flow = result.flow;
supply = sum(flow, 2);
carrierLoad = sum(flow, 1);
arrivalRaw = sum(flow .* (1 - data.lossMean'), 2);
arrivalProduct = sum(arrivalRaw ./ data.rawPerProduct(candidates));

checks = struct();
checks.nonnegative = sum(flow(:) < -tol);
checks.supplierCapacity = sum(supply > data.regularCapacity(candidates) + tol);
checks.flowSupplyBalance = sum(abs(supply - result.expectedSupply) > tol);
checks.transporterCapacity = sum(carrierLoad > data.transporterCapacity + tol);
checks.arrivalConsistency = double(abs(arrivalProduct - result.productArrival) > tol);

if problemNumber == 2
    checks.singleCarrier = sum(sum(flow > tol, 2) > 1);
    checks.productionDemand = double(arrivalProduct < data.demand - tol);
    inventory = 2 * data.demand;
    inventoryViolations = 0;
    for t = 1:24
        inventory = inventory + arrivalProduct - data.demand;
        inventoryViolations = inventoryViolations + double(inventory < 2 * data.demand - tol);
    end
    checks.inventory = inventoryViolations;
elseif problemNumber == 3
    checks.singleCarrier = 0;
    checks.productionDemand = double(arrivalProduct < data.demand - tol);
    checks.inventory = 0;
else
    checks.singleCarrier = 0;
    checks.productionDemand = 0;
    checks.inventory = 0;
end

values = struct2array(checks);
validation.checks = checks;
validation.totalHardViolations = sum(values);
validation.arrivalProduct = arrivalProduct;
validation.carrierLoad = carrierLoad;
validation.maxViolationMagnitude = max([0; ...
    -min(flow(:)); ...
    max(supply - data.regularCapacity(candidates)); ...
    max(carrierLoad' - data.transporterCapacity)]);
end
