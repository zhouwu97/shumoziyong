function data = load_official_data(rootDir)
%LOAD_OFFICIAL_DATA 直接读取官方 Excel 并构造独立统计参数。
%   本函数不调用 Python，也不读取 Python 生成的中间统计结果。

attachment1 = fullfile(rootDir, "materials", "附件1 近5年402家供应商的相关数据.xlsx");
attachment2 = fullfile(rootDir, "materials", "附件2 近5年8家转运商的相关数据.xlsx");

orderTable = readtable(attachment1, "Sheet", "企业的订货量（m³）", ...
    "VariableNamingRule", "preserve");
supplyTable = readtable(attachment1, "Sheet", "供应商的供货量（m³）", ...
    "VariableNamingRule", "preserve");
lossTable = readtable(attachment2, "Sheet", "运输损耗率（%）", ...
    "VariableNamingRule", "preserve");

data.supplierIds = string(supplyTable{:, 1});
data.materialTypes = string(supplyTable{:, 2});
data.transporterIds = string(lossTable{:, 1});
data.orders = double(orderTable{:, 3:end});
data.supply = double(supplyTable{:, 3:end});
data.lossPercent = double(lossTable{:, 2:end});

assert(isequal(data.supplierIds, string(orderTable{:, 1})), ...
    "附件1两张工作表的供应商顺序不一致");
assert(isequal(size(data.orders), [402, 240]), "订货量维度不符合题面");
assert(isequal(size(data.supply), [402, 240]), "供货量维度不符合题面");
assert(isequal(size(data.lossPercent), [8, 240]), "损耗率维度不符合题面");

orderedWeeks = sum(data.orders > 0, 2);
positiveWeeks = sum(data.supply > 0, 2);
positiveMean = zeros(402, 1);
positiveCv = zeros(402, 1);
for i = 1:402
    values = data.supply(i, data.supply(i, :) > 0);
    if ~isempty(values)
        positiveMean(i) = mean(values);
        positiveCv(i) = std(values, 1) / positiveMean(i);
    end
end

data.serviceProbability = positiveWeeks ./ orderedWeeks;
data.regularCapacity = positiveMean .* data.serviceProbability;
totalOrder = sum(data.orders, 2);
totalSupply = sum(data.supply, 2);
data.fulfilmentRatio = totalSupply ./ totalOrder;
data.orderResponseRatio = min(data.fulfilmentRatio, 1);
data.stability = 1 ./ (1 + positiveCv);

data.lossMean = zeros(8, 1);
for j = 1:8
    values = data.lossPercent(j, data.lossPercent(j, :) > 0);
    data.lossMean(j) = mean(values) / 100;
end

data.rawPerProduct = zeros(402, 1);
data.unitCost = zeros(402, 1);
data.rawPerProduct(data.materialTypes == "A") = 0.60;
data.rawPerProduct(data.materialTypes == "B") = 0.66;
data.rawPerProduct(data.materialTypes == "C") = 0.72;
data.unitCost(data.materialTypes == "A") = 1.20;
data.unitCost(data.materialTypes == "B") = 1.10;
data.unitCost(data.materialTypes == "C") = 1.00;

data.productCapacity = data.regularCapacity ./ data.rawPerProduct;
data.demand = 28200.0;
data.transporterCapacity = 6000.0;
data.tolerance = 1e-6;
end
