from __future__ import annotations


class ValidatorNotReady(RuntimeError):
    """题目专用公式和附件复算尚未实现时必须失败关闭。"""


def validate_case(_case_root: object, _evidence: object) -> dict[str, object]:
    raise ValidatorNotReady("题目专用 Validator 尚未完成，禁止使用候选自报结果")
