function result = evaluate_suppliers(data)
%EVALUATE_SUPPLIERS 独立计算四项指标、评分、排序和权重敏感性。

components = zeros(numel(data.supplierIds), 4);
components(:, 1) = minmax_scale(data.productCapacity);
components(:, 2) = minmax_scale(data.serviceProbability);
components(:, 3) = minmax_scale(data.stability);
components(:, 4) = minmax_scale(min(data.fulfilmentRatio, 1));

baseWeights = [0.50, 0.25, 0.15, 0.10];
caseNames = ["current", "equal", ...
    "capacity_minus_10pct", "capacity_plus_10pct", ...
    "service_minus_10pct", "service_plus_10pct", ...
    "stability_minus_10pct", "stability_plus_10pct", ...
    "fulfilment_minus_10pct", "fulfilment_plus_10pct"];
weights = zeros(10, 4);
weights(1, :) = baseWeights;
weights(2, :) = 0.25;
row = 3;
for changed = 1:4
    for factor = [0.90, 1.10]
        w = baseWeights;
        w(changed) = w(changed) * factor;
        weights(row, :) = w / sum(w);
        row = row + 1;
    end
end

scores = components * weights';
rankings = zeros(size(scores));
for c = 1:size(scores, 2)
    [~, order] = sortrows([-scores(:, c), (1:size(scores, 1))'], [1, 2]);
    rankings(:, c) = order;
end

result.components = components;
result.scores = scores;
result.rankings = rankings;
result.caseNames = caseNames;
result.weights = weights;
result.top10 = data.supplierIds(rankings(1:10, 1));
result.top50 = data.supplierIds(rankings(1:50, 1));

current10 = rankings(1:10, 1);
current50 = rankings(1:50, 1);
result.top10Overlap = zeros(10, 1);
result.top50OverlapRate = zeros(10, 1);
result.spearman = zeros(10, 1);
currentPositions = ranking_positions(rankings(:, 1));
for c = 1:10
    result.top10Overlap(c) = numel(intersect(current10, rankings(1:10, c)));
    result.top50OverlapRate(c) = numel(intersect(current50, rankings(1:50, c))) / 50;
    positions = ranking_positions(rankings(:, c));
    result.spearman(c) = corr(currentPositions, positions, "Type", "Spearman");
end
end

function scaled = minmax_scale(values)
span = max(values) - min(values);
if span <= 1e-6
    scaled = zeros(size(values));
else
    scaled = (values - min(values)) / span;
end
end

function positions = ranking_positions(order)
positions = zeros(size(order));
positions(order) = (1:numel(order))';
end
