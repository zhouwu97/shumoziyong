function v21_level_a(input_path, output_path)
% 从官方 Excel 和最终种植面积独立重算四场景目标、约束与敏感性。
data = jsondecode(fileread(input_path));
if isfield(data, 'model_kind') && strcmp(char(data.model_kind), 'rgv_2018b')
    result.matlab_version = version;
    result.checks = rgv_2018b_checks(data, fileparts(input_path));
    write_json(output_path, result);
    return;
end
if isfield(data, 'model')
    result.matlab_version = version;
    result.checks = generic_linear_checks(data.model, data.tolerances);
    write_json(output_path, result);
    return;
end
run_dir = fileparts(input_path);
attachment1 = fullfile(run_dir, strrep(char(data.official_input_refs(1).path), '/', filesep));
attachment2 = fullfile(run_dir, strrep(char(data.official_input_refs(2).path), '/', filesep));
formal_path = fullfile(run_dir, strrep(char(data.python_result_ref.path), '/', filesep));
formal = jsondecode(fileread(formal_path));
model = load_official_model(attachment1, attachment2);

checks = empty_checks();
for index = 1:numel(data.scenario_contracts)
    contract = data.scenario_contracts(index);
    scenario = find_scenario(formal.scenarios, char(contract.scenario_id));
    factors = scenario_factors(char(contract.factor_kind));
    metrics = evaluate_assignments(model, scenario.assignments, factors, ...
        double(contract.sales_excess_alpha), 1.0);
    prefix = ['scenario.' char(contract.scenario_id) '.'];
    checks(end + 1) = numeric_check([prefix 'objective'], ...
        double(contract.python_objective), metrics.objective, double(data.tolerances.objective));
    checks(end + 1) = numeric_check([prefix 'max_constraint_violation'], ...
        double(contract.python_max_constraint_violation), metrics.max_constraint_violation, ...
        double(data.tolerances.constraint));
    checks(end + 1) = numeric_check([prefix 'assignment_count'], ...
        double(contract.python_assignment_count), double(numel(scenario.assignments)), 0.0);
    checks(end + 1) = numeric_check([prefix 'decision_sum_mu'], ...
        double(contract.python_decision_sum_mu), metrics.decision_sum_mu, ...
        double(data.tolerances.decision));
end

for index = 1:numel(data.sensitivity_contracts)
    contract = data.sensitivity_contracts(index);
    scenario = find_scenario(formal.scenarios, char(contract.scenario_id));
    scenario_contract = find_contract(data.scenario_contracts, char(contract.scenario_id));
    factors = scenario_factors(char(scenario_contract.factor_kind));
    metrics = evaluate_assignments(model, scenario.assignments, factors, ...
        double(scenario_contract.sales_excess_alpha), double(contract.multiplier));
    checks(end + 1) = numeric_check(['sensitivity.' char(contract.name)], ...
        double(contract.python_value), metrics.objective, double(data.tolerances.objective));
end

result.matlab_version = version;
result.checks = checks;
write_json(output_path, result);
end

function checks = rgv_2018b_checks(data, run_dir)
% 从冻结参数、最终排程和原子事件独立复算2018-B，不调用主求解器模块。
contract = data.rgv_contract;
parameters_path = resolve_run_path(run_dir, contract.parameters_ref.path);
schedules_path = resolve_run_path(run_dir, contract.schedules_ref.path);
events_path = resolve_run_path(run_dir, contract.events_ref.path);
parameters = jsondecode(fileread(parameters_path));
schedules = jsondecode(fileread(schedules_path));
events = read_gzip_json_lines(events_path);
checks = empty_checks();

for run_index = 1:numel(contract.run_contracts)
    run_contract = contract.run_contracts(run_index);
    run_key = char(run_contract.run_key);
    schedule = find_schedule_run(schedules.runs, run_key);
    run_events = filter_run_events(events, run_key);
    metrics = recompute_rgv_metrics(parameters, run_contract, schedule.parts, run_events);
    prefix = ['run.' run_key '.'];
    expected_objective = double(run_contract.python_objective(:));
    actual_objective = [metrics.completed; -metrics.n_wip; -metrics.cnc_waiting; -metrics.rgv_end];
    objective_names = {'N_clean', 'minus_N_WIP', 'minus_W_CNC', 'minus_T_RGV_end'};
    for layer = 1:4
        checks(end + 1) = numeric_check([prefix 'objective.' objective_names{layer}], ...
            expected_objective(layer), actual_objective(layer), double(data.tolerances.objective));
    end
    expected = run_contract.python_metrics;
    checks(end + 1) = numeric_check([prefix 'started_parts'], ...
        double(expected.started_parts), metrics.started, double(data.tolerances.statistic));
    checks(end + 1) = numeric_check([prefix 'scrapped_parts'], ...
        double(expected.scrapped_parts), metrics.scrapped, double(data.tolerances.statistic));
    checks(end + 1) = numeric_check([prefix 'unfinished_parts'], ...
        double(expected.unfinished_parts), metrics.unfinished, double(data.tolerances.statistic));
    checks(end + 1) = numeric_check([prefix 'rgv_busy_seconds'], ...
        double(expected.rgv_busy_seconds), metrics.rgv_busy, double(data.tolerances.statistic));
    checks(end + 1) = numeric_check([prefix 'rgv_wait_seconds'], ...
        double(expected.rgv_wait_seconds), metrics.rgv_wait, double(data.tolerances.statistic));
    checks(end + 1) = numeric_check([prefix 'cnc_processing_seconds'], ...
        double(expected.cnc_processing_seconds), metrics.cnc_processing, double(data.tolerances.statistic));
    checks(end + 1) = numeric_check([prefix 'rgv_utilization'], ...
        double(expected.rgv_utilization), metrics.rgv_utilization, double(data.tolerances.statistic));
    checks(end + 1) = numeric_check([prefix 'cnc_utilization'], ...
        double(expected.cnc_utilization), metrics.cnc_utilization, double(data.tolerances.statistic));
    checks(end + 1) = numeric_check([prefix 'post_shift_return_seconds'], ...
        double(expected.post_shift_return_seconds), metrics.post_shift_return, double(data.tolerances.statistic));
    checks(end + 1) = numeric_check([prefix 'action_count'], ...
        double(expected.action_count), metrics.action_count, double(data.tolerances.statistic));
    checks(end + 1) = numeric_check([prefix 'event_sequence_violation'], ...
        0.0, metrics.sequence_violation, double(data.tolerances.constraint));
    checks(end + 1) = numeric_check([prefix 'event_time_violation'], ...
        0.0, metrics.time_violation, double(data.tolerances.constraint));
    checks(end + 1) = numeric_check([prefix 'exclusive_resource_overlap_seconds'], ...
        0.0, metrics.resource_overlap, double(data.tolerances.constraint));
    checks(end + 1) = numeric_check([prefix 'official_duration_residual_seconds'], ...
        0.0, metrics.duration_residual, double(data.tolerances.constraint));
end
end

function metrics = recompute_rgv_metrics(parameters, contract, parts, events)
horizon = double(parameters.horizon_seconds);
completed = 0;
scrapped = 0;
for index = 1:numel(parts)
    clean_end = nullable_number(parts(index).clean_end_seconds);
    scrap_time = nullable_number(parts(index).scrapped_at_seconds);
    if ~isnan(clean_end) && clean_end <= horizon && isnan(scrap_time)
        completed = completed + 1;
    elseif ~isnan(scrap_time) && scrap_time <= horizon
        scrapped = scrapped + 1;
    end
end
started = numel(parts);
metrics.completed = completed;
metrics.scrapped = scrapped;
metrics.started = started;
metrics.unfinished = started - completed - scrapped;
metrics.n_wip = metrics.unfinished;
metrics.cnc_waiting = recompute_cnc_waiting(events, horizon);

metrics.rgv_end = 0.0;
metrics.rgv_busy = 0.0;
metrics.rgv_wait = 0.0;
metrics.cnc_processing = 0.0;
metrics.post_shift_return = 0.0;
metrics.sequence_violation = 0.0;
metrics.time_violation = 0.0;
action_ids = {};
for index = 1:numel(events)
    event = events{index};
    start_time = double(event.start_seconds);
    end_time = double(event.end_seconds);
    metrics.sequence_violation = metrics.sequence_violation + abs(double(event.sequence) - index);
    metrics.time_violation = metrics.time_violation + max(0.0, -start_time) + max(0.0, start_time - end_time);
    clipped = max(0.0, min(end_time, horizon) - min(start_time, horizon));
    event_type = char(event.event_type);
    if any(strcmp(event_type, {'rgv_move', 'rgv_service', 'rgv_clean', 'rgv_in_shift_return'}))
        metrics.rgv_end = max(metrics.rgv_end, min(end_time, horizon));
    end
    if any(strcmp(event_type, {'rgv_move', 'rgv_service', 'rgv_clean', 'rgv_in_shift_return'}))
        metrics.rgv_busy = metrics.rgv_busy + clipped;
    elseif strcmp(event_type, 'rgv_wait')
        metrics.rgv_wait = metrics.rgv_wait + clipped;
    elseif strcmp(event_type, 'cnc_processing')
        metrics.cnc_processing = metrics.cnc_processing + clipped;
    elseif strcmp(event_type, 'rgv_post_shift_return')
        metrics.post_shift_return = metrics.post_shift_return + max(0.0, end_time - start_time);
    end
    if strcmp(event_type, 'rgv_service') && ~isempty(event.action_id)
        action_ids{end + 1} = char(event.action_id); %#ok<AGROW>
    end
end
metrics.action_count = numel(unique(action_ids));
metrics.rgv_utilization = metrics.rgv_busy / horizon;
metrics.cnc_utilization = metrics.cnc_processing / (8.0 * horizon);
metrics.resource_overlap = maximum_resource_overlap(events);
metrics.duration_residual = official_duration_residual(parameters, contract, events);
end

function value = recompute_cnc_waiting(events, horizon)
% 每个 process_end 到下一次 ready 状态服务的间隔；班末未服务部分截断到H。
value = 0.0;
for index = 1:numel(events)
    event = events{index};
    if ~strcmp(char(event.event_type), 'cnc_process_end')
        continue;
    end
    ready_at = double(event.end_seconds);
    served_at = horizon;
    for candidate_index = 1:numel(events)
        candidate = events{candidate_index};
        if strcmp(char(candidate.event_type), 'cnc_service') && ...
                strcmp(char(candidate.resource_id), char(event.resource_id)) && ...
                double(candidate.start_seconds) >= ready_at && ...
                strcmp(nullable_text(candidate.state_before), 'ready')
            served_at = min(served_at, double(candidate.start_seconds));
        end
    end
    value = value + max(0.0, min(served_at, horizon) - ready_at);
end
end

function value = maximum_resource_overlap(events)
% 独占资源按物理资源分组，计算任意正时长区间的最大交叠秒数。
value = 0.0;
for first = 1:numel(events)
    a = events{first};
    if ~is_exclusive_interval(a)
        continue;
    end
    for second = (first + 1):numel(events)
        b = events{second};
        if ~is_exclusive_interval(b) || ...
                ~strcmp(char(a.resource_type), char(b.resource_type)) || ...
                ~strcmp(char(a.resource_id), char(b.resource_id))
            continue;
        end
        overlap = min(double(a.end_seconds), double(b.end_seconds)) - ...
            max(double(a.start_seconds), double(b.start_seconds));
        value = max(value, max(0.0, overlap));
    end
end
end

function accepted = is_exclusive_interval(event)
event_type = char(event.event_type);
accepted = double(event.end_seconds) > double(event.start_seconds) && ...
    (strcmp(char(event.resource_type), 'RGV') || ...
    (strcmp(char(event.resource_type), 'CNC') && ...
        any(strcmp(event_type, {'cnc_processing', 'cnc_service', 'cnc_repair'}))) || ...
    strcmp(char(event.resource_type), 'cleaning_slot'));
end

function value = official_duration_residual(parameters, contract, events)
% 只用冻结参数重建移动、服务、清洗和完整加工事件的应有时长。
group = json_index(parameters.parameter_groups, double(contract.parameter_group));
process_type = double(contract.process_type);
value = 0.0;
for index = 1:numel(events)
    event = events{index};
    event_type = char(event.event_type);
    actual = double(event.end_seconds) - double(event.start_seconds);
    expected = nan;
    if strcmp(event_type, 'rgv_move')
        distance = abs(double(event.payload.from_position) - double(event.payload.to_position));
        expected = double(json_index(group.move_seconds, distance));
    elseif strcmp(event_type, 'rgv_service')
        cnc_id = double(event.payload.cnc_id);
        if mod(cnc_id, 2) == 1
            expected = double(group.service_seconds.odd);
        else
            expected = double(group.service_seconds.even);
        end
    elseif any(strcmp(event_type, {'rgv_clean', 'cleaning_slot'}))
        expected = double(group.clean_seconds);
    elseif strcmp(event_type, 'cnc_processing') && strcmp(nullable_text(event.state_after), 'ready')
        if process_type == 1
            expected = double(group.one_stage_process_seconds);
        else
            expected = double(json_index(group.two_stage_process_seconds, double(event.stage)));
        end
    end
    if ~isnan(expected)
        value = max(value, abs(actual - expected));
    end
end
end

function value = json_index(container, key)
field_name = matlab.lang.makeValidName(char(string(key)));
if ~isfield(container, field_name)
    error('Missing JSON numeric key: %s', char(string(key)));
end
value = container.(field_name);
end

function path = resolve_run_path(run_dir, relative_path)
path = fullfile(run_dir, strrep(char(relative_path), '/', filesep));
end

function events = read_gzip_json_lines(path)
temporary = tempname;
mkdir(temporary);
cleanup = onCleanup(@() rmdir(temporary, 's')); %#ok<NASGU>
files = gunzip(path, temporary);
file_id = fopen(files{1}, 'r', 'n', 'UTF-8');
if file_id < 0
    error('Cannot open decompressed atomic events: %s', files{1});
end
file_cleanup = onCleanup(@() fclose(file_id)); %#ok<NASGU>
events = {};
while true
    line = fgetl(file_id);
    if ~ischar(line)
        break;
    end
    if ~isempty(strtrim(line))
        events{end + 1} = jsondecode(line); %#ok<AGROW>
    end
end
end

function selected = filter_run_events(events, run_key)
selected = {};
for index = 1:numel(events)
    if strcmp(char(events{index}.run_key), run_key)
        selected{end + 1} = events{index}; %#ok<AGROW>
    end
end
if isempty(selected)
    error('Missing atomic events for run: %s', run_key);
end
end

function value = find_schedule_run(runs, run_key)
for index = 1:numel(runs)
    if strcmp(char(runs(index).run_key), run_key)
        value = runs(index);
        return;
    end
end
error('Missing schedule for run: %s', run_key);
end

function value = nullable_number(raw)
if isempty(raw)
    value = nan;
else
    value = double(raw);
end
end

function value = nullable_text(raw)
if isempty(raw)
    value = '';
else
    value = char(raw);
end
end

function checks = generic_linear_checks(model, tolerances)
% 为通用运行器测试和非题目专属线性模型执行 Level A 独立复算。
x = double(model.decision_vector(:));
c = double(model.objective_coefficients(:));
objective = c' * x + double(model.objective_constant);
max_violation = 0.0;
for index = 1:numel(model.constraints)
    item = model.constraints(index);
    lhs = double(item.coefficients(:))' * x;
    max_violation = max(max_violation, linear_constraint_violation( ...
        lhs, char(item.sense), double(item.rhs)));
end
checks = empty_checks();
checks(end + 1) = numeric_check('objective_value', ...
    double(model.python_metrics.objective_value), objective, double(tolerances.objective));
checks(end + 1) = numeric_check('max_constraint_violation', ...
    double(model.python_metrics.max_constraint_violation), max_violation, ...
    double(tolerances.constraint));
checks(end + 1) = numeric_check('decision_sum', ...
    double(model.python_metrics.decision_sum), sum(x), double(tolerances.decision));
end

function value = linear_constraint_violation(lhs, sense, rhs)
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

function model = load_official_model(attachment1, attachment2)
land = readtable(attachment1, 'Sheet', '乡村的现有耕地', 'VariableNamingRule', 'preserve');
stats = readtable(attachment2, 'Sheet', '2023年统计的相关数据', 'VariableNamingRule', 'preserve');
plant = readtable(attachment2, 'Sheet', '2023年的农作物种植情况', 'VariableNamingRule', 'preserve');

valid_land = ~isnan(to_double(land.('地块面积/亩')));
land = land(valid_land, :);
valid_stats = ~isnan(to_double(stats.('作物编号')));
stats = stats(valid_stats, :);
plant_plot = string(plant.('种植地块'));
for index = 2:numel(plant_plot)
    if ismissing(plant_plot(index)) || strlength(strtrim(plant_plot(index))) == 0
        plant_plot(index) = plant_plot(index - 1);
    end
end
plant.('种植地块') = plant_plot;
valid_plant = ~isnan(to_double(plant.('作物编号')));
plant = plant(valid_plant, :);

model.land = land;
model.stats = stats;
model.plant = plant;
model.plot_names = string(land.('地块名称'));
model.plot_types = string(land.('地块类型'));
model.plot_areas = to_double(land.('地块面积/亩'));
model.bean_ids = [1:5, 17:19];
end

function factors = scenario_factors(kind)
factors.kind = kind;
end

function metrics = evaluate_assignments(model, assignments, factors, alpha, extra_cost_multiplier)
years = 2024:2030;
production = containers.Map('KeyType', 'char', 'ValueType', 'double');
cost_by_year = zeros(size(years));
decision_sum = 0.0;

for index = 1:numel(assignments)
    item = assignments(index);
    year = double(item.year);
    plot_name = string(item.plot_id);
    season = string(item.season);
    crop = double(item.crop_id);
    area = double(item.area_mu);
    decision_sum = decision_sum + area;
    plot_type = plot_type_for(model, plot_name);
    parameter = parameter_for(model, plot_type, season, crop);
    year_index = year - 2023;
    [demand_factor, yield_factor, cost_factor, price_factor] = ...
        factors_for(factors.kind, crop, year_index);
    key = key3(year, season, crop);
    production(key) = get_map(production, key) + area * parameter.yield * yield_factor;
    cost_by_year(year_index) = cost_by_year(year_index) + ...
        area * parameter.cost * cost_factor * extra_cost_multiplier;
end

revenue_by_year = zeros(size(years));
production_keys = keys(production);
for index = 1:numel(production_keys)
    key = production_keys{index};
    parts = split(string(key), '|');
    year = str2double(parts(1));
    season = parts(2);
    crop = str2double(parts(3));
    year_index = year - 2023;
    quantity = production(key);
    demand = demand_2023(model, season, crop);
    [demand_factor, ~, ~, price_factor] = factors_for(factors.kind, crop, year_index);
    demand = demand * demand_factor;
    price = first_allowed_price(model, season, crop) * price_factor;
    revenue_by_year(year_index) = revenue_by_year(year_index) + ...
        price * (min(quantity, demand) + alpha * max(0.0, quantity - demand));
end

metrics.objective = sum(revenue_by_year - cost_by_year);
metrics.decision_sum_mu = decision_sum;
metrics.max_constraint_violation = constraint_violation(model, assignments);
end

function value = constraint_violation(model, assignments)
value = 0.0;
years = 2024:2030;
seasons = ["单季", "第一季", "第二季"];
presence = containers.Map('KeyType', 'char', 'ValueType', 'logical');

for index = 1:numel(assignments)
    item = assignments(index);
    year = double(item.year);
    plot_name = string(item.plot_id);
    season = string(item.season);
    crop = double(item.crop_id);
    area = double(item.area_mu);
    plot_area = plot_area_for(model, plot_name);
    plot_type = plot_type_for(model, plot_name);
    if ~is_allowed(plot_type, season, crop)
        value = max(value, area);
    end
    minimum_area = 0.2 * plot_area;
    if contains(plot_type, "大棚")
        minimum_area = 0.3;
    end
    if area < minimum_area - 1e-5
        value = max(value, minimum_area - area);
    end
    if area > 1e-5
        presence(key4(year, plot_name, season, crop)) = true;
    end
end

for year = years
    for plot_index = 1:numel(model.plot_names)
        plot_name = model.plot_names(plot_index);
        plot_type = model.plot_types(plot_index);
        plot_area = model.plot_areas(plot_index);
        season_area = zeros(1, numel(seasons));
        for season_index = 1:numel(seasons)
            season = seasons(season_index);
            season_area(season_index) = assignment_sum(assignments, year, plot_name, season, []);
            value = max(value, max(0.0, season_area(season_index) - plot_area));
        end
        if plot_type == "水浇地" && season_area(1) > 1e-5 && (season_area(2) > 1e-5 || season_area(3) > 1e-5)
            value = max(value, min(season_area(1), season_area(2) + season_area(3)));
        end
    end
end

plant = model.plant;
for index = 1:height(plant)
    plot_name = string(plant.('种植地块')(index));
    season = string(plant.('种植季次')(index));
    crop = double(plant.('作物编号')(index));
    if has_key(presence, key4(2024, plot_name, season, crop))
        value = max(value, 1.0);
    end
end
for year = 2024:2029
    current_keys = keys(presence);
    for index = 1:numel(current_keys)
        parts = split(string(current_keys{index}), '|');
        if str2double(parts(1)) == year
            next_key = key4(year + 1, parts(2), parts(3), str2double(parts(4)));
            if has_key(presence, next_key)
                value = max(value, 1.0);
            end
        end
    end
end

for plot_index = 1:numel(model.plot_names)
    plot_name = model.plot_names(plot_index);
    plot_area = model.plot_areas(plot_index);
    previous_bean = 0.0;
    for index = 1:height(plant)
        if string(plant.('种植地块')(index)) == plot_name && ...
                any(double(plant.('作物编号')(index)) == model.bean_ids)
            previous_bean = previous_bean + double(plant.('种植面积/亩')(index));
        end
    end
    for start_year = 2023:2028
        total = 0.0;
        if start_year == 2023
            total = previous_bean;
        end
        for year = max(2024, start_year):(start_year + 2)
            for crop = model.bean_ids
                total = total + assignment_sum(assignments, year, plot_name, [], crop);
            end
        end
        value = max(value, max(0.0, plot_area - total));
    end
end

for year = years
    for season = seasons
        for crop = 1:41
            count = assignment_count(assignments, year, season, crop);
            value = max(value, max(0.0, count - 8));
        end
    end
end
end

function value = demand_2023(model, season, crop)
value = 0.0;
plant = model.plant;
for index = 1:height(plant)
    if string(plant.('种植季次')(index)) == season && double(plant.('作物编号')(index)) == crop
        plot_name = string(plant.('种植地块')(index));
        parameter = parameter_for(model, plot_type_for(model, plot_name), season, crop);
        value = value + double(plant.('种植面积/亩')(index)) * parameter.yield;
    end
end
end

function value = first_allowed_price(model, season, crop)
for index = 1:numel(model.plot_names)
    plot_type = model.plot_types(index);
    if is_allowed(plot_type, season, crop)
        parameter = parameter_for(model, plot_type, season, crop);
        value = parameter.price;
        return;
    end
end
error('No allowed price for season=%s crop=%d', season, crop);
end

function parameter = parameter_for(model, plot_type, season, crop)
stats = model.stats;
mask = string(stats.('地块类型')) == plot_type & ...
    string(stats.('种植季次')) == season & to_double(stats.('作物编号')) == crop;
if ~any(mask) && plot_type == "智慧大棚" && season == "第一季" && crop >= 17 && crop <= 34
    mask = string(stats.('地块类型')) == "普通大棚" & ...
        string(stats.('种植季次')) == "第一季" & to_double(stats.('作物编号')) == crop;
end
row = find(mask, 1, 'first');
if isempty(row)
    error('Missing parameter: %s %s %d', plot_type, season, crop);
end
parameter.yield = double(stats.('亩产量/斤')(row));
parameter.cost = double(stats.('种植成本/(元/亩)')(row));
parts = split(string(stats.('销售单价/(元/斤)')(row)), '-');
parameter.price = mean(str2double(parts));
end

function [demand_factor, yield_factor, cost_factor, price_factor] = factors_for(kind, crop, year_index)
demand_factor = 1.0;
yield_factor = 1.0;
cost_factor = 1.0;
price_factor = 1.0;
if strcmp(kind, 'q2_frozen') || strcmp(kind, 'q3_contract')
    yield_factor = 0.95;
    cost_factor = 1.05 ^ year_index;
    if crop == 6 || crop == 7
        demand_factor = 1.075 ^ year_index;
    end
    if crop >= 17 && crop <= 37
        price_factor = 1.05 ^ year_index;
    elseif crop == 41
        price_factor = 0.95 ^ year_index;
    elseif crop >= 38 && crop <= 40
        price_factor = 0.97 ^ year_index;
    end
end
end

function allowed = is_allowed(plot_type, season, crop)
if any(plot_type == ["平旱地", "梯田", "山坡地"])
    allowed = season == "单季" && crop >= 1 && crop <= 15;
elseif plot_type == "水浇地"
    allowed = (season == "单季" && crop == 16) || ...
        (season == "第一季" && crop >= 17 && crop <= 34) || ...
        (season == "第二季" && crop >= 35 && crop <= 37);
elseif plot_type == "普通大棚"
    allowed = (season == "第一季" && crop >= 17 && crop <= 34) || ...
        (season == "第二季" && crop >= 38 && crop <= 41);
elseif plot_type == "智慧大棚"
    allowed = any(season == ["第一季", "第二季"]) && crop >= 17 && crop <= 34;
else
    allowed = false;
end
end

function scenario = find_scenario(scenarios, scenario_id)
for index = 1:numel(scenarios)
    if strcmp(char(scenarios(index).scenario_id), scenario_id)
        scenario = scenarios(index);
        return;
    end
end
error('Missing scenario: %s', scenario_id);
end

function contract = find_contract(contracts, scenario_id)
for index = 1:numel(contracts)
    if strcmp(char(contracts(index).scenario_id), scenario_id)
        contract = contracts(index);
        return;
    end
end
error('Missing scenario contract: %s', scenario_id);
end

function value = plot_type_for(model, plot_name)
index = find(model.plot_names == plot_name, 1, 'first');
value = model.plot_types(index);
end

function value = plot_area_for(model, plot_name)
index = find(model.plot_names == plot_name, 1, 'first');
value = model.plot_areas(index);
end

function value = assignment_sum(assignments, year, plot_name, season, crop)
value = 0.0;
for index = 1:numel(assignments)
    item = assignments(index);
    matches = double(item.year) == year && string(item.plot_id) == plot_name;
    if ~isempty(season)
        matches = matches && string(item.season) == season;
    end
    if ~isempty(crop)
        matches = matches && double(item.crop_id) == crop;
    end
    if matches
        value = value + double(item.area_mu);
    end
end
end

function value = assignment_count(assignments, year, season, crop)
value = 0;
for index = 1:numel(assignments)
    item = assignments(index);
    if double(item.year) == year && string(item.season) == season && ...
            double(item.crop_id) == crop && double(item.area_mu) > 1e-5
        value = value + 1;
    end
end
end

function value = to_double(value)
if isnumeric(value)
    value = double(value);
else
    value = str2double(string(value));
end
end

function value = get_map(container, key)
if isKey(container, key)
    value = container(key);
else
    value = 0.0;
end
end

function present = has_key(container, key)
present = isKey(container, char(key));
end

function key = key3(year, season, crop)
key = char(string(year) + "|" + season + "|" + string(crop));
end

function key = key4(year, plot_name, season, crop)
key = char(string(year) + "|" + plot_name + "|" + season + "|" + string(crop));
end

function checks = empty_checks()
checks = struct('name', {}, 'python_value', {}, 'matlab_value', {}, ...
    'absolute_difference', {}, 'tolerance', {}, 'passed', {});
end

function item = numeric_check(name, python_value, matlab_value, tolerance)
difference = abs(python_value - matlab_value);
item = struct('name', name, 'python_value', python_value, ...
    'matlab_value', matlab_value, 'absolute_difference', difference, ...
    'tolerance', tolerance, 'passed', difference <= tolerance);
end

function write_json(output_path, value)
file_id = fopen(output_path, 'w', 'n', 'UTF-8');
if file_id < 0
    error('Cannot open output file: %s', output_path);
end
cleanup = onCleanup(@() fclose(file_id));
fwrite(file_id, jsonencode(value, PrettyPrint=true), 'char');
end
