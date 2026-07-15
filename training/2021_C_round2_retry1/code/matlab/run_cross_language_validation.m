function run_cross_language_validation(rootDir)
%RUN_CROSS_LANGUAGE_VALIDATION 执行 MATLAB 独立复现并生成双语言对照工件。
%   优化阶段只读取官方 Excel；Python 结果仅在 MATLAB 求解结束后用于比较。

if nargin < 1
    here = fileparts(mfilename("fullpath"));
    rootDir = fileparts(fileparts(here));
end
addpath(fullfile(rootDir, "code", "matlab"));
resultsDir = fullfile(rootDir, "results");
startTime = datetime("now", "TimeZone", "local", "Format", "yyyy-MM-dd'T'HH:mm:ssXXX");
totalTimer = tic;

data = load_official_data(rootDir);
ranking = evaluate_suppliers(data);
p2 = solve_problem2(data);
p3 = solve_problem3(data);
p4 = solve_problem4(data);
v2 = validate_solution(data, p2, 2);
v3 = validate_solution(data, p3, 3);
v4 = validate_solution(data, p4, 4);

% 以下文件仅用于求解后的交叉语言对照，不参与 MATLAB 模型构造。
pySupplier = jsondecode(fileread(fullfile(resultsDir, "supplier_analysis.json")));
pyRank = jsondecode(fileread(fullfile(resultsDir, "rank_sensitivity.json")));
pyFormal = jsondecode(fileread(fullfile(resultsDir, "formal_result.json")));
pyConstraints = jsondecode(fileread(fullfile(resultsDir, "constraint_validation.json")));
pyP2 = get_problem(pyFormal.problems, 2);
pyP3 = get_problem(pyFormal.problems, 3);
pyP4 = get_problem(pyFormal.problems, 4);

scoreBySupplier = containers.Map(cellstr(data.supplierIds), num2cell(ranking.scores(:, 1)));
pyTop50Ids = strings(50, 1);
pyTop50Scores = zeros(50, 1);
for i = 1:50
    pyTop50Ids(i) = string(pySupplier.top50(i).supplier_id);
    pyTop50Scores(i) = pySupplier.top50(i).importance_score;
end
matlabScoresForPyTop50 = zeros(50, 1);
for i = 1:50
    matlabScoresForPyTop50(i) = scoreBySupplier(char(pyTop50Ids(i)));
end
scoreMaxError = max(abs(matlabScoresForPyTop50 - pyTop50Scores));

rankCaseNames = cellstr(ranking.caseNames);
sensitivityErrors = zeros(numel(rankCaseNames), 3);
for i = 1:numel(rankCaseNames)
    caseName = rankCaseNames{i};
    pyCase = pyRank.cases.(caseName);
    sensitivityErrors(i, 1) = abs(ranking.top10Overlap(i) - pyCase.top10_overlap_count_with_current);
    sensitivityErrors(i, 2) = abs(ranking.top50OverlapRate(i) - pyCase.top50_overlap_rate_with_current);
    sensitivityErrors(i, 3) = abs(ranking.spearman(i) - pyCase.spearman_rank_correlation_with_current);
end

metrics = strings(0, 1);
pythonValue = strings(0, 1);
matlabValue = strings(0, 1);
absoluteError = zeros(0, 1);
tolerance = zeros(0, 1);
passed = false(0, 1);

append_text("problem1_top10_exact", strjoin(string({pySupplier.top50(1:10).supplier_id}), ";"), ...
    strjoin(ranking.top10, ";"));
append_text("problem1_top50_exact", strjoin(pyTop50Ids, ";"), strjoin(ranking.top50, ";"));
append_numeric("problem1_top50_score_max_error", 0, scoreMaxError, 1e-9);
append_numeric("problem1_sensitivity_max_error", 0, max(sensitivityErrors, [], "all"), 1e-9);
append_numeric("problem2_minimum_supplier_count", pyP2.selected_supplier_count, p2.minimumSupplierCount, 0);
append_numeric("problem2_purchase_cost_24week", pyP2.objective.purchase_cost_relative, 24 * p2.purchaseCost, 1e-6);
append_numeric("problem2_transport_loss_24week", pyP2.objective.transport_loss_raw_m3, 24 * p2.transportLoss, 1e-6);
append_numeric("problem2_inventory_end", pyP2.weekly_inventory_end_m3, p2.inventory(end), 1e-6);
append_numeric("problem3_a_supply_24week", pyP3.objective.a_expected_supply_raw_m3, 24 * p3.aSupply, 1e-6);
pyB = pyP3.objective.total_expected_supply_raw_m3 - pyP3.objective.a_expected_supply_raw_m3 - pyP3.objective.c_expected_supply_raw_m3;
append_numeric("problem3_b_supply_24week", pyB, 24 * p3.bSupply, 1e-6);
append_numeric("problem3_c_supply_24week", pyP3.objective.c_expected_supply_raw_m3, 24 * p3.cSupply, 1e-6);
append_numeric("problem3_total_raw_24week", pyP3.objective.total_expected_supply_raw_m3, 24 * p3.totalRaw, 1e-6);
append_numeric("problem3_transport_loss_24week", pyP3.objective.transport_loss_raw_m3, 24 * p3.transportLoss, 1e-6);
append_numeric("problem4_maximum_weekly_capacity", pyP4.weekly_product_arrival_m3, p4.maximumWeeklyCapacity, 1e-6);
append_numeric("problem2_hard_violations", 0, v2.totalHardViolations, 0);
append_numeric("problem3_hard_violations", 0, v3.totalHardViolations, 0);
append_numeric("problem4_hard_violations", 0, v4.totalHardViolations, 0);
append_numeric("python_reported_hard_violations", pyConstraints.total_hard_violations, 0, 0);

comparisonTable = table(metrics, pythonValue, matlabValue, absoluteError, tolerance, passed, ...
    'VariableNames', {'metric', 'python_value', 'matlab_value', 'absolute_error', 'tolerance', 'passed'});
writetable(comparisonTable, fullfile(resultsDir, "cross_language_validation.csv"), ...
    "Encoding", "UTF-8");

numericMask = isfinite(absoluteError);
maximumError = max(absoluteError(numericMask));
payload.schema_version = "1.0";
payload.generated_at = string(datetime("now", "TimeZone", "local", "Format", "yyyy-MM-dd'T'HH:mm:ssXXX"));
payload.independence_statement = "MATLAB optimization reads only official Excel and locked constants; Python artifacts are loaded only after MATLAB solving for comparison.";
payload.tolerances.score = 1e-9;
payload.tolerances.continuous = 1e-6;
payload.overall_pass = all(passed);
payload.maximum_cross_language_error = maximumError;
payload.problem1.top10_exact = passed(metrics == "problem1_top10_exact");
payload.problem1.top50_exact = passed(metrics == "problem1_top50_exact");
payload.problem1.score_max_error = scoreMaxError;
payload.problem1.sensitivity_max_error = max(sensitivityErrors, [], "all");
payload.problem2.minimum_supplier_count = p2.minimumSupplierCount;
payload.problem2.purchase_cost_24week = 24 * p2.purchaseCost;
payload.problem2.transport_loss_24week = 24 * p2.transportLoss;
payload.problem2.exitflags = p2.exitflags;
payload.problem3.a_supply_24week = 24 * p3.aSupply;
payload.problem3.b_supply_24week = 24 * p3.bSupply;
payload.problem3.c_supply_24week = 24 * p3.cSupply;
payload.problem3.total_raw_24week = 24 * p3.totalRaw;
payload.problem3.transport_loss_24week = 24 * p3.transportLoss;
payload.problem3.exitflags = p3.exitflags;
payload.problem4.maximum_weekly_capacity = p4.maximumWeeklyCapacity;
payload.problem4.exitflag = p4.exitflag;
payload.constraints.problem2 = v2;
payload.constraints.problem3 = v3;
payload.constraints.problem4 = v4;
payload.comparisons = table2struct(comparisonTable);
write_json(fullfile(resultsDir, "cross_language_validation.json"), payload);

optimInfo = ver("optim");
record.schema_version = "1.0";
record.start_time = string(startTime);
record.end_time = string(datetime("now", "TimeZone", "local", "Format", "yyyy-MM-dd'T'HH:mm:ssXXX"));
record.runtime_seconds = toc(totalTimer);
record.matlab_version = version;
record.release = version("-release");
record.platform = computer;
record.optimization_toolbox_version = optimInfo.Version;
record.intlinprog_available = exist("intlinprog", "file") == 2;
record.linprog_available = exist("linprog", "file") == 2;
record.command = "matlab -batch ""addpath('code/matlab'); run_cross_language_validation(pwd)""";
record.exit_status = 0;
record.validation_pass = payload.overall_pass;
record.solvers.problem2 = "MATLAB intlinprog";
record.solvers.problem3 = "MATLAB linprog (HiGHS dual simplex)";
record.solvers.problem4 = "MATLAB linprog (HiGHS dual simplex)";
record.stage_runtimes.problem2_seconds = p2.runtimes;
record.stage_runtimes.problem3_seconds = p3.runtimes;
record.stage_runtimes.problem4_seconds = p4.runtime;
write_json(fullfile(resultsDir, "matlab_execution_record.json"), record);

fprintf("MATLAB cross-language validation pass=%d, max_error=%.12g\n", ...
    payload.overall_pass, payload.maximum_cross_language_error);

    function append_numeric(name, py, ml, tol)
        metrics(end + 1, 1) = name;
        pythonValue(end + 1, 1) = string(sprintf("%.15g", py));
        matlabValue(end + 1, 1) = string(sprintf("%.15g", ml));
        absoluteError(end + 1, 1) = abs(py - ml);
        tolerance(end + 1, 1) = tol;
        passed(end + 1, 1) = abs(py - ml) <= tol;
    end

    function append_text(name, py, ml)
        metrics(end + 1, 1) = name;
        pythonValue(end + 1, 1) = py;
        matlabValue(end + 1, 1) = ml;
        if py == ml
            absoluteError(end + 1, 1) = 0;
            passed(end + 1, 1) = true;
        else
            absoluteError(end + 1, 1) = Inf;
            passed(end + 1, 1) = false;
        end
        tolerance(end + 1, 1) = 0;
    end
end

function problem = get_problem(problems, number)
fields = fieldnames(problems);
target = string(number);
for i = 1:numel(fields)
    if endsWith(string(fields{i}), target)
        problem = problems.(fields{i});
        return;
    end
end
error("未找到问题 %d 的 Python 正式结果", number);
end

function write_json(path, value)
fid = fopen(path, "w", "n", "UTF-8");
cleanup = onCleanup(@() fclose(fid));
fprintf(fid, "%s\n", jsonencode(value, "PrettyPrint", true));
end
