"""2024 年国赛 C 题完整官方闭环实现。"""

from .data_loader import load_problem_data, resolve_material_root
from .data_model import ProblemData

__all__ = ["ProblemData", "load_problem_data", "resolve_material_root"]

