"""Question Slice：每个子问题的最小交接契约。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


QUESTION_ID = re.compile(r"q[1-9][0-9]*$")
ALLOWED_STATUS = {"draft", "complete", "failed", "blocked"}


def _relative_path(value: str, field: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or value.startswith(("/", "\\")):
        raise ValueError(f"{field} 必须是 Run 内相对路径：{value}")
    return path.as_posix()


@dataclass(frozen=True)
class QuestionSlice:
    question_id: str
    title: str
    status: str
    objective: str
    source_artifacts: tuple[str, ...]
    outputs: tuple[str, ...]
    ledger_keys: tuple[str, ...]
    verification: str
    limitations: tuple[str, ...]
    version: str = "2.0"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "QuestionSlice":
        required = {
            "version",
            "question_id",
            "title",
            "status",
            "objective",
            "source_artifacts",
            "outputs",
            "ledger_keys",
            "verification",
            "limitations",
        }
        missing = sorted(required - data.keys())
        extra = sorted(data.keys() - required)
        if missing:
            raise ValueError(f"Question Slice 缺少字段：{missing}")
        if extra:
            raise ValueError(f"Question Slice 含未知字段：{extra}")
        question_id = str(data["question_id"])
        if not QUESTION_ID.fullmatch(question_id):
            raise ValueError(f"非法 question_id：{question_id}")
        status = str(data["status"])
        if status not in ALLOWED_STATUS:
            raise ValueError(f"非法 status：{status}")
        ledger_keys = tuple(str(item) for item in data["ledger_keys"])
        if len(ledger_keys) != len(set(ledger_keys)):
            raise ValueError("Question Slice 的 ledger_keys 不得重复")
        return cls(
            version=str(data["version"]),
            question_id=question_id,
            title=str(data["title"]).strip(),
            status=status,
            objective=str(data["objective"]).strip(),
            source_artifacts=tuple(_relative_path(str(item), "source_artifacts") for item in data["source_artifacts"]),
            outputs=tuple(_relative_path(str(item), "outputs") for item in data["outputs"]),
            ledger_keys=ledger_keys,
            verification=str(data["verification"]).strip(),
            limitations=tuple(str(item).strip() for item in data["limitations"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "question_id": self.question_id,
            "title": self.title,
            "status": self.status,
            "objective": self.objective,
            "source_artifacts": list(self.source_artifacts),
            "outputs": list(self.outputs),
            "ledger_keys": list(self.ledger_keys),
            "verification": self.verification,
            "limitations": list(self.limitations),
        }

    def validate_files(self, run_dir: Path) -> list[str]:
        missing = []
        for relative in (*self.source_artifacts, *self.outputs):
            if not (run_dir / relative).is_file():
                missing.append(relative)
        return missing


def load_question_slice(path: Path) -> QuestionSlice:
    return QuestionSlice.from_dict(json.loads(path.read_text(encoding="utf-8")))


def write_question_slice(path: Path, value: QuestionSlice) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
