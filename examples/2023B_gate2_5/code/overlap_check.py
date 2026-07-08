from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OverlapResult:
    spacing_m: float
    reference_width_m: float
    overlap_rate: float
    status: str

    @property
    def overlap_percent(self) -> float:
        return self.overlap_rate * 100.0


def overlap_rate(spacing_m: float, coverage_width_m: float) -> float:
    if coverage_width_m <= 0:
        raise ValueError("覆盖宽度必须为正值")
    if spacing_m < 0:
        raise ValueError("测线间距不能为负")
    return 1.0 - spacing_m / coverage_width_m


def check_overlap_interval(
    spacing_m: float,
    coverage_width_m: float,
    lower: float = 0.10,
    upper: float = 0.20,
) -> OverlapResult:
    rate = overlap_rate(spacing_m, coverage_width_m)
    if rate < 0:
        status = "漏测"
    elif lower <= rate <= upper:
        status = "通过"
    elif rate < lower:
        status = "重叠不足"
    else:
        status = "重叠过高"
    return OverlapResult(
        spacing_m=spacing_m,
        reference_width_m=coverage_width_m,
        overlap_rate=rate,
        status=status,
    )


def pairwise_overlap_checks(spacings_m: list[float], widths_m: list[float]) -> list[OverlapResult]:
    if len(spacings_m) != len(widths_m):
        raise ValueError("间距数量必须与参考覆盖宽度数量一致")
    return [
        check_overlap_interval(spacing_m=spacing, coverage_width_m=width)
        for spacing, width in zip(spacings_m, widths_m)
    ]


def main() -> None:
    result = check_overlap_interval(spacing_m=300.0, coverage_width_m=360.0)
    print(f"overlap_percent: {result.overlap_percent:.2f}")
    print(f"status: {result.status}")


if __name__ == "__main__":
    main()
