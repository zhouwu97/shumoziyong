"""从已验证结果生成论文图；不参与求解或修改任何数值证据。"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
FIGURES = ROOT / "figures"


def save_all(fig: plt.Figure, stem: str) -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    for suffix in ("png", "svg", "pdf"):
        fig.savefig(FIGURES / f"{stem}.{suffix}", dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main() -> None:
    objectives = json.loads((RESULTS / "objective_validation.json").read_text(encoding="utf-8"))["cases"]
    labels = ["Q1-unsold", "Q1-50%", "Q2-robust", "Q3-correlated"]
    values = [objectives[key]["recomputed_objective"] / 1e6 for key in ("q1_unsold", "q1_discount50", "q2", "q3")]
    fig, ax = plt.subplots(figsize=(8.2, 4.8), constrained_layout=True)
    bars = ax.bar(labels, values, color=["#4C78A8", "#72B7B2", "#F58518", "#E45756"], edgecolor="#333333")
    ax.set_ylabel("Recomputed objective (million yuan)")
    ax.set_title("Four scenario objectives from raw decision variables")
    ax.grid(axis="y", alpha=0.25)
    for bar, value in zip(bars, values, strict=True):
        ax.text(bar.get_x() + bar.get_width() / 2, value, f"{value:.2f}", ha="center", va="bottom", fontsize=9)
    save_all(fig, "figure_1_objective_recomputation")

    q2_values = pd.read_csv(RESULTS / "q3" / "q2_on_independent_samples.csv")["objective"] / 1e6
    q3_values = pd.read_csv(RESULTS / "q3" / "q3_on_independent_samples.csv")["objective"] / 1e6
    fig, ax = plt.subplots(figsize=(7.2, 4.8), constrained_layout=True)
    box = ax.boxplot([q2_values, q3_values], tick_labels=["Q2 plan", "Q3 plan"], patch_artist=True)
    for patch, color in zip(box["boxes"], ["#4C78A8", "#E45756"], strict=True):
        patch.set_facecolor(color)
        patch.set_alpha(0.75)
    ax.set_ylabel("Objective on independent correlated samples (million yuan)")
    ax.set_title("Independent Q3-scenario comparison (n=256)")
    ax.grid(axis="y", alpha=0.25)
    save_all(fig, "figure_2_independent_risk_comparison")

    validation = json.loads((RESULTS / "constraint_validation.json").read_text(encoding="utf-8"))
    columns = list(next(iter(validation.values()))["violation_counts"].keys())
    matrix = np.array([[validation[case]["violation_counts"][column] for column in columns] for case in validation])
    fig, ax = plt.subplots(figsize=(10, 3.8), constrained_layout=True)
    image = ax.imshow(matrix, cmap="cividis", vmin=0, vmax=1, aspect="auto")
    ax.set_xticks(range(len(columns)), [column.replace("_", "\n") for column in columns], fontsize=8)
    ax.set_yticks(range(len(validation)), list(validation.keys()))
    for row in range(matrix.shape[0]):
        for column in range(matrix.shape[1]):
            ax.text(column, row, str(matrix[row, column]), ha="center", va="center", color="white", fontsize=9)
    ax.set_title("Independent hard-constraint violation counts")
    fig.colorbar(image, ax=ax, label="Violation count")
    save_all(fig, "figure_3_constraint_validation")


if __name__ == "__main__":
    main()
