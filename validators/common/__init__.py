"""A092 Validator v0 的通用薄壳。"""

from .claim_level import derive_optimality_claim
from .improvement import compare_with_baseline
from .residuals import check_constraints
from .validator import validate_solution

__all__ = [
    "check_constraints",
    "compare_with_baseline",
    "derive_optimality_claim",
    "validate_solution",
]

