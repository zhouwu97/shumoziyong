from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "paper"))

from check_narrative import build_narrative_report  # noqa: E402
from external_precheck import snapshot_body  # noqa: E402


BINDING = {
    "run_id": "narrative-fixture",
    "problem_id": "2024-C",
    "profile": "engineering_optimization",
    "runtime_version": "1.0.0",
    "runtime_pack_sha256": "2" * 64,
}
TEXTS = {
    "thesis": "本文建立多阶段优化模型，在全部硬约束下获得稳定且可执行的种植方案。",
    "core_contributions": "核心贡献是把轮作、地块容量和销售上限统一纳入优化约束。",
    "model_choice_reason": "选择混合整数规划是因为决策离散且业务约束可以被精确表达。",
    "result_insights": "结果表明基准情景下的资源瓶颈集中在水浇地而不是普通大棚。",
    "action_recommendations": "建议优先调整水浇地品类组合，并保留百分之十的需求扰动余量。",
    "limitations": "模型局限在于需求分布来自历史样本，极端市场冲击仍需情景重算。",
}


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _prepare(tmp_path: Path) -> tuple[Path, Path, dict[str, object], dict[str, object]]:
    paper_root = tmp_path / "paper"
    paper_root.mkdir()
    (paper_root / "main.typ").write_text(
        "= 摘要\n\n" + "\n\n".join(TEXTS.values()) + "\n",
        encoding="utf-8",
    )
    claim_map = {
        "schema_version": "1.0.0",
        "artifact_type": "paper_claim_map",
        **BINDING,
        "claims": [
            {
                "claim_id": "C001",
                "claim": "正式结果支持论文叙事。",
                "result_refs": ["result_report.json#/conclusions/0"],
                "evidence_refs": ["formal_result.json"],
            }
        ],
    }
    claim_map_path = tmp_path / "paper_claim_map.json"
    _write_json(claim_map_path, claim_map)
    narrative = {
        "schema_version": "paper_narrative_input_v1",
        **{
            name: [{"text": text, "evidence_refs": ["C001"]}]
            for name, text in TEXTS.items()
        },
    }
    return paper_root, claim_map_path, claim_map, narrative


def _build(
    paper_root: Path,
    claim_map_path: Path,
    claim_map: dict[str, object],
    narrative: dict[str, object],
) -> dict[str, object]:
    return build_narrative_report(
        paper_root=paper_root,
        narrative_input=narrative,
        claim_map=claim_map,
        claim_map_path=claim_map_path,
        binding=BINDING,
    )


def test_complete_narrative_passes_and_binds_real_evidence_hashes(tmp_path: Path) -> None:
    paper_root, claim_map_path, claim_map, narrative = _prepare(tmp_path)

    report = _build(paper_root, claim_map_path, claim_map, narrative)

    assert report["status"] == "passed"
    assert report["submission_allowed"] is True
    assert report["technical_report_allowed"] is True
    assert report["claim_map_sha256"] == hashlib.sha256(claim_map_path.read_bytes()).hexdigest()
    assert report["paper_body_sha256"] == snapshot_body(paper_root)["sha256"]


def test_missing_element_returns_failed_technical_report_status(tmp_path: Path) -> None:
    paper_root, claim_map_path, claim_map, narrative = _prepare(tmp_path)
    narrative["limitations"] = []

    report = _build(paper_root, claim_map_path, claim_map, narrative)

    assert report["status"] == "failed"
    assert report["submission_allowed"] is False
    assert report["technical_report_allowed"] is True
    assert report["checks"]["contract_complete"]["status"] == "failed"


def test_more_than_two_core_contributions_fails_contract(tmp_path: Path) -> None:
    paper_root, claim_map_path, claim_map, narrative = _prepare(tmp_path)
    contribution = narrative["core_contributions"][0]
    narrative["core_contributions"] = [copy.deepcopy(contribution) for _ in range(3)]

    report = _build(paper_root, claim_map_path, claim_map, narrative)

    assert report["checks"]["contract_complete"]["status"] == "failed"
    assert report["submission_allowed"] is False


def test_more_than_one_thesis_returns_failed_report_instead_of_schema_error(
    tmp_path: Path,
) -> None:
    paper_root, claim_map_path, claim_map, narrative = _prepare(tmp_path)
    thesis = narrative["thesis"][0]
    narrative["thesis"] = [copy.deepcopy(thesis), copy.deepcopy(thesis)]

    report = _build(paper_root, claim_map_path, claim_map, narrative)

    assert report["status"] == "failed"
    assert report["checks"]["contract_complete"]["status"] == "failed"


def test_text_absent_from_body_fails_presence(tmp_path: Path) -> None:
    paper_root, claim_map_path, claim_map, narrative = _prepare(tmp_path)
    narrative["result_insights"][0]["text"] = "该条洞察没有写入论文正文，因此不能进入提交稿。"

    report = _build(paper_root, claim_map_path, claim_map, narrative)

    assert report["checks"]["text_presence"]["status"] == "failed"


def test_empty_or_unknown_claim_ids_fail_binding(tmp_path: Path) -> None:
    paper_root, claim_map_path, claim_map, narrative = _prepare(tmp_path)
    narrative["thesis"][0]["evidence_refs"] = []
    narrative["limitations"][0]["evidence_refs"] = ["C999"]

    report = _build(paper_root, claim_map_path, claim_map, narrative)

    assert report["checks"]["claim_binding"]["status"] == "failed"
    assert len(report["checks"]["claim_binding"]["issues"]) == 2


def test_forbidden_terms_internal_paths_and_hashes_fail_scan(tmp_path: Path) -> None:
    paper_root, claim_map_path, claim_map, narrative = _prepare(tmp_path)
    with (paper_root / "main.typ").open("a", encoding="utf-8") as handle:
        handle.write("Gate 4 的 runtime_contracts/ 记录为 " + "a" * 64 + "。\n")

    report = _build(paper_root, claim_map_path, claim_map, narrative)

    assert report["forbidden_scan"]["status"] == "failed"
    assert {hit["kind"] for hit in report["forbidden_scan"]["hits"]} == {
        "forbidden_term",
        "hash",
    }


def test_narrative_check_never_mutates_paper_source(tmp_path: Path) -> None:
    paper_root, claim_map_path, claim_map, narrative = _prepare(tmp_path)
    source = paper_root / "main.typ"
    before = source.read_bytes()

    _build(paper_root, claim_map_path, claim_map, narrative)

    assert source.read_bytes() == before
