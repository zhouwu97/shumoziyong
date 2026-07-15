function v21_level_b(input_path, output_path)
% 对冻结合同中的小样例执行独立网格枚举求解，验证方向、约束和边界。
data = jsondecode(fileread(input_path));
examples = data.small_examples;
checks = struct('name', {}, 'python_value', {}, 'matlab_value', {}, ...
    'absolute_difference', {}, 'tolerance', {}, 'passed', {});

for case_index = 1:numel(examples)
    example = examples(case_index);
    if isfield(example, 'example_kind') && strcmp(char(example.example_kind), 'rgv_dynamic_one_stage')
        prefix = [char(example.case_id) '.'];
        objective_tolerance = double(data.tolerances.objective);
        best_value = solve_dynamic_one_stage(example, double(example.horizon_seconds));
        checks(end + 1) = numeric_check([prefix 'objective_value'], ...
            double(example.python_expected.objective_value), best_value, objective_tolerance);
        zero_value = solve_dynamic_one_stage(example, 0.0);
        checks(end + 1) = numeric_check([prefix 'zero_horizon_no_completion'], ...
            double(example.python_expected.zero_horizon_objective), zero_value, objective_tolerance);
        short_value = solve_dynamic_one_stage(example, double(example.service_seconds) - 1.0);
        checks(end + 1) = numeric_check([prefix 'service_boundary_no_completion'], ...
            0.0, short_value, objective_tolerance);
        extended_value = solve_dynamic_one_stage(example, double(example.horizon_seconds) + 1.0);
        checks(end + 1) = boolean_check([prefix 'horizon_extension_monotone'], ...
            true, extended_value >= best_value);
        continue;
    end
    [best_value, best_x, feasible_count] = solve_grid(example);
    prefix = [char(example.case_id) '.'];
    objective_tolerance = double(data.tolerances.objective);
    checks(end + 1) = numeric_check([prefix 'objective_value'], ...
        double(example.python_expected.objective_value), best_value, objective_tolerance);
    checks(end + 1) = boolean_check([prefix 'feasible_solution_found'], true, feasible_count > 0);

    expected_x = double(example.python_expected.decision_vector(:));
    vector_difference = max(abs(expected_x - best_x));
    checks(end + 1) = numeric_check([prefix 'decision_vector_max_difference'], ...
        0.0, vector_difference, double(data.tolerances.decision));

    boundary_checks = example.python_expected.boundary_checks;
    for boundary_index = 1:numel(boundary_checks)
        item = boundary_checks(boundary_index);
        lhs = double(item.coefficients(:))' * best_x;
        actual = constraint_violation(lhs, char(item.sense), double(item.rhs)) ...
            <= double(data.tolerances.constraint);
        checks(end + 1) = boolean_check([prefix 'boundary.' char(item.name)], ...
            logical(item.expected), actual);
    end
end

result.matlab_version = version;
result.checks = checks;
write_json(output_path, result);
end

function optimum = solve_dynamic_one_stage(example, horizon)
% 独立枚举缩小的一道工序时间状态；每次递归只允许一次 RGV 服务。
cnc_count = double(example.cnc_count);
service = double(example.service_seconds);
process = double(example.process_seconds);
clean = double(example.clean_seconds);
memo = containers.Map('KeyType', 'char', 'ValueType', 'double');
optimum = best(0.0, -ones(1, cnc_count));

    function value = best(time, ready_times)
        if time >= horizon
            value = 0.0;
            return;
        end
        key = sprintf('%.0f|', [time ready_times]);
        if isKey(memo, key)
            value = memo(key);
            return;
        end
        eligible = find(ready_times < 0 | ready_times <= time);
        if isempty(eligible)
            future = ready_times(ready_times > time);
            if isempty(future)
                value = 0.0;
            else
                value = best(min(future), ready_times);
            end
            memo(key) = value;
            return;
        end
        value = 0.0;
        for eligible_index = 1:numel(eligible)
            cnc_index = eligible(eligible_index);
            current_ready = ready_times(cnc_index);
            service_end = time + service;
            if service_end > horizon
                continue;
            end
            next_ready = ready_times;
            next_ready(cnc_index) = service_end + process;
            completed = double(current_ready >= 0 && service_end + clean <= horizon);
            next_time = service_end;
            if current_ready >= 0
                next_time = next_time + clean;
            end
            value = max(value, completed + best(next_time, next_ready));
        end
        memo(key) = value;
    end
end

function [best_value, best_x, feasible_count] = solve_grid(example)
variables = example.variables;
grid = cell(1, numel(variables));
for index = 1:numel(variables)
    grid{index} = double(variables(index).lower):double(variables(index).step):double(variables(index).upper);
end
mesh = cell(1, numel(grid));
[mesh{:}] = ndgrid(grid{:});
point_count = numel(mesh{1});
c = double(example.objective_coefficients(:));
constant = get_optional(example, 'objective_constant', 0.0);
direction = char(example.objective_direction);
best_value = inf;
if strcmp(direction, 'max')
    best_value = -inf;
end
best_x = nan(numel(grid), 1);
feasible_count = 0;

for point_index = 1:point_count
    x = zeros(numel(grid), 1);
    for variable_index = 1:numel(grid)
        x(variable_index) = mesh{variable_index}(point_index);
    end
    if ~is_feasible(x, example.constraints)
        continue;
    end
    feasible_count = feasible_count + 1;
    objective = c' * x + constant;
    if (strcmp(direction, 'min') && objective < best_value) || ...
            (strcmp(direction, 'max') && objective > best_value)
        best_value = objective;
        best_x = x;
    end
end
if feasible_count == 0
    error('Small example %s has no feasible grid point', char(example.case_id));
end
end

function feasible = is_feasible(x, constraints)
feasible = true;
for index = 1:numel(constraints)
    item = constraints(index);
    lhs = double(item.coefficients(:))' * x;
    if constraint_violation(lhs, char(item.sense), double(item.rhs)) > 1e-10
        feasible = false;
        return;
    end
end
end

function value = constraint_violation(lhs, sense, rhs)
switch sense
    case '<='
        value = max(0.0, lhs - rhs);
    case '>='
        value = max(0.0, rhs - lhs);
    case '=='
        value = abs(lhs - rhs);
    otherwise
        error('Unsupported constraint sense: %s', sense);
end
end

function item = numeric_check(name, python_value, matlab_value, tolerance)
difference = abs(python_value - matlab_value);
item = struct('name', name, 'python_value', python_value, ...
    'matlab_value', matlab_value, 'absolute_difference', difference, ...
    'tolerance', tolerance, 'passed', difference <= tolerance);
end

function item = boolean_check(name, python_value, matlab_value)
difference = double(logical(python_value) ~= logical(matlab_value));
item = struct('name', name, 'python_value', logical(python_value), ...
    'matlab_value', logical(matlab_value), 'absolute_difference', difference, ...
    'tolerance', 0.0, 'passed', difference == 0.0);
end

function value = get_optional(container, field_name, default_value)
if isfield(container, field_name)
    value = double(container.(field_name));
else
    value = default_value;
end
end

function write_json(output_path, value)
file_id = fopen(output_path, 'w', 'n', 'UTF-8');
if file_id < 0
    error('Cannot open output file: %s', output_path);
end
cleanup = onCleanup(@() fclose(file_id));
fwrite(file_id, jsonencode(value, PrettyPrint=true), 'char');
end
