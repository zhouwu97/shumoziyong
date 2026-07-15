function render_validation_plot(spec_path, output_dir)
%RENDER_VALIDATION_PLOT 独立复算 CSV 统计量并生成 MATLAB 验证图。
% 验证图只用于交叉核验，不替换 Python 生成的最终投稿图。

spec = jsondecode(fileread(spec_path));
spec_dir = fileparts(spec_path);
source_path = fullfile(spec_dir, strrep(spec.source_data.path, '/', filesep));
data = readtable(source_path, 'VariableNamingRule', 'preserve');
series = spec.chart.series;
x = data.(spec.chart.x_column);

fig = figure('Visible', 'off', 'Color', 'white', ...
    'Units', 'centimeters', ...
    'Position', [1, 1, spec.chart.width_mm / 10, spec.chart.height_mm / 10]);
ax = axes(fig);
hold(ax, 'on');

if strcmp(spec.chart.type, 'grouped_bar')
    values = zeros(height(data), numel(series));
    for index = 1:numel(series)
        values(:, index) = data.(series(index).column);
    end
    bars = bar(ax, x, values, 'grouped');
    for index = 1:numel(series)
        bars(index).FaceColor = hex_to_rgb(series(index).color);
        bars(index).DisplayName = series(index).label;
    end
else
    for index = 1:numel(series)
        y = data.(series(index).column);
        color = hex_to_rgb(series(index).color);
        if strcmp(spec.chart.type, 'line')
            plot(ax, x, y, ...
                'DisplayName', series(index).label, ...
                'Color', color, ...
                'LineStyle', series(index).line_style, ...
                'Marker', series(index).marker, ...
                'LineWidth', 1.2);
        else
            scatter(ax, x, y, 20, color, series(index).marker, ...
                'DisplayName', series(index).label);
        end
    end
end

xlabel(ax, spec.chart.x_label);
ylabel(ax, spec.chart.y_label);
grid(ax, 'on');
legend(ax, 'Location', 'best', 'Box', 'off');
ax.Box = 'off';
ax.FontName = 'Arial';
ax.FontSize = 7;

if ~isfolder(output_dir)
    mkdir(output_dir);
end
stem = spec.export.output_stem;
png_name = [stem, '_matlab_validation.png'];
fig_name = [stem, '_matlab_validation.fig'];
exportgraphics(fig, fullfile(output_dir, png_name), 'Resolution', 180);
savefig(fig, fullfile(output_dir, fig_name));
close(fig);

statistics = repmat(struct( ...
    'column', '', 'count', 0, 'min', 0, 'max', 0, 'mean', 0, 'std', 0), ...
    numel(series), 1);
for index = 1:numel(series)
    values = data.(series(index).column);
    statistics(index).column = series(index).column;
    statistics(index).count = numel(values);
    statistics(index).min = min(values);
    statistics(index).max = max(values);
    statistics(index).mean = mean(values);
    statistics(index).std = std(values, 1);
end

report = struct();
report.schema_version = '1.0.0';
report.source_data_sha256 = sha256_file(source_path);
report.statistics = statistics;
report.outputs = {png_name, fig_name};

report_path = fullfile(output_dir, 'matlab_validation.json');
handle = fopen(report_path, 'w', 'n', 'UTF-8');
if handle < 0
    error('无法写入 MATLAB 验证报告：%s', report_path);
end
cleanup = onCleanup(@() fclose(handle));
fwrite(handle, jsonencode(report, 'PrettyPrint', true), 'char');
end


function rgb = hex_to_rgb(value)
value = char(value);
if startsWith(value, '#')
    value = value(2:end);
end
rgb = [hex2dec(value(1:2)), hex2dec(value(3:4)), hex2dec(value(5:6))] / 255;
end


function value = sha256_file(path)
handle = fopen(path, 'rb');
if handle < 0
    error('无法读取源数据：%s', path);
end
cleanup = onCleanup(@() fclose(handle));
bytes = fread(handle, Inf, '*uint8');
engine = javaMethod('getInstance', 'java.security.MessageDigest', 'SHA-256');
engine.update(bytes);
digest = typecast(engine.digest(), 'uint8');
value = lower(reshape(dec2hex(digest, 2).', 1, []));
end
