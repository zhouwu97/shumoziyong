function model = build_flow_model(data, candidates, enforceSingleCarrier)
%BUILD_FLOW_MODEL 构造单周供应、转运、损耗与产品等价线性模型。

n = numel(candidates);
m = numel(data.transporterIds);
flowCount = n * m;
if enforceSingleCarrier
    variableCount = 2 * flowCount;
else
    variableCount = flowCount;
end

capacities = data.regularCapacity(candidates);
rawPerProduct = data.rawPerProduct(candidates);
unitCost = data.unitCost(candidates);

supplierRows = n;
carrierRows = m;
assignmentRows = enforceSingleCarrier * (n + flowCount);
rowCount = supplierRows + carrierRows + assignmentRows;
A = spalloc(rowCount, variableCount, flowCount * 4 + n * m);
b = zeros(rowCount, 1);
row = 0;

for i = 1:n
    row = row + 1;
    idx = flow_indices(i, m);
    A(row, idx) = 1;
    b(row) = capacities(i);
end
for j = 1:m
    row = row + 1;
    idx = j:m:flowCount;
    A(row, idx) = 1;
    b(row) = data.transporterCapacity;
end

if enforceSingleCarrier
    for i = 1:n
        row = row + 1;
        idx = flowCount + flow_indices(i, m);
        A(row, idx) = 1;
        b(row) = 1;
    end
    for i = 1:n
        for j = 1:m
            row = row + 1;
            xIndex = (i - 1) * m + j;
            yIndex = flowCount + xIndex;
            A(row, xIndex) = 1;
            A(row, yIndex) = -capacities(i);
            b(row) = 0;
        end
    end
end

productCoefficient = zeros(flowCount, 1);
lossCoefficient = zeros(flowCount, 1);
costCoefficient = zeros(flowCount, 1);
for i = 1:n
    for j = 1:m
        idx = (i - 1) * m + j;
        productCoefficient(idx) = (1 - data.lossMean(j)) / rawPerProduct(i);
        lossCoefficient(idx) = data.lossMean(j);
        costCoefficient(idx) = unitCost(i);
    end
end

model.A = A;
model.b = b;
model.lb = zeros(variableCount, 1);
model.ub = inf(variableCount, 1);
for i = 1:n
    model.ub(flow_indices(i, m)) = capacities(i);
end
if enforceSingleCarrier
    model.ub(flowCount + (1:flowCount)) = 1;
    model.intcon = flowCount + (1:flowCount);
else
    model.intcon = [];
end
model.flowCount = flowCount;
model.productCoefficient = productCoefficient;
model.lossCoefficient = lossCoefficient;
model.costCoefficient = costCoefficient;
model.rawCoefficient = ones(flowCount, 1);
model.candidates = candidates(:);
model.n = n;
model.m = m;
end

function idx = flow_indices(i, m)
idx = (i - 1) * m + (1:m);
end
