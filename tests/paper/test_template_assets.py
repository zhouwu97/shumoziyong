from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_profile_is_black_white_three_line_typst() -> None:
    profile = json.loads(
        (ROOT / "paper_profiles" / "cumcm_academic_v1.json").read_text(encoding="utf-8")
    )

    assert profile["engine"] == "typst"
    assert profile["margins_cm"] == {"top": 2.5, "bottom": 2.5, "left": 2.5, "right": 2.5}
    assert profile["colors"]["colored_heading_allowed"] is False
    assert profile["colors"]["table_fill_allowed"] is False
    assert profile["table_style"] == "three_line"
    assert len(profile["font_candidates"]["serif"]) >= 3


def test_template_contains_required_components_without_decorative_styles() -> None:
    template = ROOT / "paper_templates" / "cumcm_typst"
    combined = "\n".join(
        path.read_text(encoding="utf-8") for path in template.rglob("*.typ")
    ).lower()

    assert "three-line-table" in combined
    assert "math.equation(numbering:" in combined
    assert "supplement: [图]" in combined
    assert "supplement: [表]" in combined
    assert "gradient" not in combined
    assert "shadow" not in combined


def test_template_declares_renderer_binding_and_protected_assets() -> None:
    template = json.loads(
        (ROOT / "paper_templates" / "cumcm_typst" / "template.json").read_text(
            encoding="utf-8"
        )
    )

    assert template["template_id"] == "cumcm_typst_academic_v1"
    assert template["renderer_id"] == "typst"
    assert set(template["protected_files"]) == {"components.typ", "style.typ"}
