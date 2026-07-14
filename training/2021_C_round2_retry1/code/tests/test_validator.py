"""最小回归测试：对已经生成的原始解重新执行独立检查。"""

from __future__ import annotations

from common.common import RESULTS, load_official_data, read_json
from validator.independent_validator import check_all_constraints, run_fault_injections


def main() -> None:
    data = load_official_data()
    raw = read_json(RESULTS / "raw_solution.json")
    for part, solution in raw["problems"].items():
        report = check_all_constraints(solution, data)
        assert report["passed"], f"问题{part}约束复算失败: {report['total_hard_violations']}"
    fault = run_fault_injections(raw["problems"]["2"], data)
    assert fault["fault_injection_pass_rate"] == 1.0, "故障注入未达100%"
    print("validator regression passed")


if __name__ == "__main__":
    main()
