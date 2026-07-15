"""汇总 nature-writing / nature-figure 产物并生成 v2.1 论文生产清单。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

from v21_contracts import validate_paper_production_manifest


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_ref(run_dir: Path, path_text: str) -> dict[str, str]:
    path = (run_dir / path_text).resolve()
    if not path.is_relative_to(run_dir.resolve()) or not path.is_file():
        raise ValueError(f"论文生产文件不在当前 Run 内或不存在：{path_text}")
    return {"path": path.relative_to(run_dir).as_posix(), "sha256": sha256_file(path)}


def build_manifest(
    run_dir: Path,
    *,
    one_sentence_argument: str,
    terminology_ledger: str,
    claim_map: str,
    manuscript: str,
    pdf: str,
    figure_fragments: list[str],
    missing_evidence_placeholders: list[str],
    status: str,
) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    run_manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    admission_path = run_dir / "paper_admission_report.json"
    admission = json.loads(admission_path.read_text(encoding="utf-8"))
    if admission.get("run_id") != run_manifest.get("run_id"):
        raise ValueError("Paper Admission 与当前 Run 身份不一致")
    paper_type = "submission_paper" if admission.get("submission_paper_allowed") is True else "technical_report"
    if paper_type == "technical_report" and status == "accepted":
        raise ValueError("未通过 Paper Admission 的 technical_report 不能标记 accepted")
    figures: list[Mapping[str, Any]] = []
    for fragment_text in figure_fragments:
        fragment_path = (run_dir / fragment_text).resolve()
        if not fragment_path.is_relative_to(run_dir) or not fragment_path.is_file():
            raise ValueError(f"图表 fragment 不存在：{fragment_text}")
        fragment = json.loads(fragment_path.read_text(encoding="utf-8"))
        if "qa_ref" not in fragment:
            raise ValueError(f"图表 fragment 缺少视觉 QA 引用：{fragment_text}")
        figures.append(fragment)
    value: dict[str, Any] = {
        "schema_version": "1.0.0",
        "artifact_type": "paper_production_manifest",
        "run_id": run_manifest["run_id"],
        "paper_type": paper_type,
        "paper_admission_ref": make_ref(run_dir, "paper_admission_report.json"),
        "one_sentence_argument": one_sentence_argument,
        "terminology_ledger_ref": make_ref(run_dir, terminology_ledger),
        "claim_map_ref": make_ref(run_dir, claim_map),
        "manuscript_ref": make_ref(run_dir, manuscript),
        "pdf_ref": make_ref(run_dir, pdf),
        "figure_backend": "python",
        "figures": figures,
        "matlab_evidence_refs": [
            make_ref(run_dir, "matlab_level_a_report.json"),
            make_ref(run_dir, "matlab_level_b_report.json"),
        ],
        "missing_evidence_placeholders": missing_evidence_placeholders,
        "status": status,
    }
    errors = validate_paper_production_manifest(value, run_dir=run_dir, admission=admission)
    if errors:
        raise ValueError("；".join(errors))
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 v2.1 论文生产清单")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--one-sentence-argument", required=True)
    parser.add_argument("--terminology-ledger", required=True)
    parser.add_argument("--claim-map", default="paper_claim_map.json")
    parser.add_argument("--manuscript", required=True)
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--figure-fragment", action="append", required=True)
    parser.add_argument("--missing-evidence", action="append", default=[])
    parser.add_argument("--status", choices=("candidate", "reviewed", "accepted"), default="candidate")
    parser.add_argument("--output", default="paper_production_manifest.json")
    args = parser.parse_args()
    run_dir = Path(args.run_dir)
    try:
        value = build_manifest(
            run_dir,
            one_sentence_argument=args.one_sentence_argument,
            terminology_ledger=args.terminology_ledger,
            claim_map=args.claim_map,
            manuscript=args.manuscript,
            pdf=args.pdf,
            figure_fragments=args.figure_fragment,
            missing_evidence_placeholders=args.missing_evidence,
            status=args.status,
        )
        output = run_dir / args.output
        output.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"[BLOCKED] {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    print(json.dumps(value, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
