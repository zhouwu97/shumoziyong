from __future__ import annotations

from dataclasses import dataclass
from math import ceil

from geometry_model import flat_coverage_width
from load_2023B_data import NM_TO_M
from overlap_check import check_overlap_interval


@dataclass(frozen=True)
class SurveyLine:
    line_id: int
    direction_deg: float
    offset_m: float
    length_m: float


@dataclass(frozen=True)
class BaselineResult:
    sea_width_m: float
    sea_height_m: float
    spacing_m: float
    reference_width_m: float
    target_overlap: float
    lines: list[SurveyLine]

    @property
    def total_length_m(self) -> float:
        return sum(line.length_m for line in self.lines)

    def summary(self) -> dict:
        checks = [
            check_overlap_interval(self.spacing_m, self.reference_width_m).status
            for _ in self.lines[1:]
        ]
        return {
            "line_count": len(self.lines),
            "spacing_m": self.spacing_m,
            "reference_width_m": self.reference_width_m,
            "total_length_m": self.total_length_m,
            "overlap_status_counts": {status: checks.count(status) for status in sorted(set(checks))},
        }


def generate_parallel_baseline(
    sea_width_nm: float,
    sea_height_nm: float,
    depth_m: float,
    beam_angle_deg: float = 120.0,
    target_overlap: float = 0.15,
    direction_deg: float = 0.0,
) -> BaselineResult:
    # 小样例基线：固定南北向平行测线，以平坦海底覆盖宽度生成等间距线。
    sea_width_m = sea_width_nm * NM_TO_M
    sea_height_m = sea_height_nm * NM_TO_M
    width_m = flat_coverage_width(depth_m, beam_angle_deg)
    spacing_m = width_m * (1.0 - target_overlap)
    line_count = max(1, ceil(sea_width_m / spacing_m) + 1)
    start_offset = -sea_width_m / 2.0

    lines = [
        SurveyLine(
            line_id=i + 1,
            direction_deg=direction_deg,
            offset_m=start_offset + i * spacing_m,
            length_m=sea_height_m,
        )
        for i in range(line_count)
    ]
    return BaselineResult(
        sea_width_m=sea_width_m,
        sea_height_m=sea_height_m,
        spacing_m=spacing_m,
        reference_width_m=width_m,
        target_overlap=target_overlap,
        lines=lines,
    )


def main() -> None:
    baseline = generate_parallel_baseline(sea_width_nm=4.0, sea_height_nm=5.0, depth_m=50.0)
    print(baseline.summary())


if __name__ == "__main__":
    main()
