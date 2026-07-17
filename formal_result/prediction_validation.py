"""Prediction Formal Result 的患者级拆分和指标重算。"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping

from .domain_contracts import DomainContract
from .errors import FormalResultVerificationError


def _as_number(value: object, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise FormalResultVerificationError(f"{label} 必须是有限数值")
    result = float(value)
    if result != result or result in {float("inf"), float("-inf")}:
        raise FormalResultVerificationError(f"{label} 必须是有限数值")
    return result


def _average_precision(labels: list[int], scores: list[float]) -> float:
    positives = sum(labels)
    if positives == 0:
        raise FormalResultVerificationError("prediction_result 无正类样本，无法复算 PR-AUC")
    ordered = sorted(zip(scores, labels, strict=True), key=lambda item: item[0], reverse=True)
    true_positives = 0
    precision_sum = 0.0
    for rank, (_score, label) in enumerate(ordered, start=1):
        if label == 1:
            true_positives += 1
            precision_sum += true_positives / rank
    return precision_sum / positives


def _roc_auc(labels: list[int], scores: list[float]) -> float:
    positives = sum(labels)
    negatives = len(labels) - positives
    if positives == 0 or negatives == 0:
        raise FormalResultVerificationError("prediction_result 缺少正类或负类，无法复算 ROC-AUC")
    wins = 0.0
    for positive_score in (score for score, label in zip(scores, labels, strict=True) if label == 1):
        for negative_score in (score for score, label in zip(scores, labels, strict=True) if label == 0):
            if positive_score > negative_score:
                wins += 1.0
            elif positive_score == negative_score:
                wins += 0.5
    return wins / (positives * negatives)


def _recompute_metrics(labels: list[int], scores: list[float], threshold: float) -> dict[str, float]:
    predicted = [int(score >= threshold) for score in scores]
    true_positives = sum(prediction == 1 and label == 1 for prediction, label in zip(predicted, labels, strict=True))
    false_positives = sum(prediction == 1 and label == 0 for prediction, label in zip(predicted, labels, strict=True))
    positives = sum(labels)
    return {
        "brier": sum((score - label) ** 2 for score, label in zip(scores, labels, strict=True)) / len(labels),
        "pr_auc": _average_precision(labels, scores),
        "roc_auc": _roc_auc(labels, scores),
        "recall": true_positives / positives,
        "precision": true_positives / (true_positives + false_positives) if true_positives + false_positives else 0.0,
        "positive_rate": positives / len(labels),
    }


def recompute_prediction_metrics(
    result_payload: Mapping[str, Any],
) -> dict[str, dict[str, float]]:
    assignments = result_payload["split_assignments"]
    assignment_by_sample: dict[str, tuple[str, str]] = {}
    groups_by_split: dict[str, set[str]] = defaultdict(set)
    for item in assignments:
        sample_id = str(item["sample_id"])
        if sample_id in assignment_by_sample:
            raise FormalResultVerificationError(f"split_assignments.sample_id 重复：{sample_id}")
        group_id = str(item["group_id"])
        split = str(item["split"])
        assignment_by_sample[sample_id] = (group_id, split)
        groups_by_split[split].add(group_id)
    training_groups = groups_by_split["train"]
    evaluation_groups = groups_by_split["validation"] | groups_by_split["test"]
    overlap = training_groups & evaluation_groups
    if overlap:
        raise FormalResultVerificationError(f"患者级拆分存在训练/评估重叠：{sorted(overlap)}")
    for audit in result_payload["fit_audits"]:
        if audit["fit_scope"] != "training_only":
            raise FormalResultVerificationError(
                f"预处理阶段 {audit['stage']} 未限定为 training_only"
            )

    metrics_by_task: dict[str, dict[str, float]] = {}
    for task in result_payload["tasks"]:
        task_id = str(task["task_id"])
        labels: list[int] = []
        scores: list[float] = []
        seen_samples: set[str] = set()
        for prediction in task["predictions"]:
            sample_id = str(prediction["sample_id"])
            if sample_id in seen_samples:
                raise FormalResultVerificationError(
                    f"任务 {task_id} prediction.sample_id 重复：{sample_id}"
                )
            seen_samples.add(sample_id)
            assignment = assignment_by_sample.get(sample_id)
            if assignment is None:
                raise FormalResultVerificationError(
                    f"任务 {task_id} 的预测样本未进入冻结拆分：{sample_id}"
                )
            if assignment[1] not in {"validation", "test"}:
                raise FormalResultVerificationError(
                    f"任务 {task_id} 把训练样本计入评估：{sample_id}"
                )
            label = prediction["y_true"]
            if label not in {0, 1}:
                raise FormalResultVerificationError(f"任务 {task_id} y_true 必须是 0 或 1")
            labels.append(int(label))
            score = _as_number(prediction["y_score"], f"任务 {task_id} y_score")
            if not 0.0 <= score <= 1.0:
                raise FormalResultVerificationError(f"任务 {task_id} y_score 必须位于 [0, 1]")
            scores.append(score)
        metrics_by_task[task_id] = _recompute_metrics(
            labels,
            scores,
            _as_number(task["threshold"], f"任务 {task_id} threshold"),
        )
    return metrics_by_task


def verify_prediction_domain_contract(
    domain: Mapping[str, Any],
    descriptors: list[dict[str, Any]],
    values: Mapping[str, dict[str, Any]],
    contract: DomainContract,
) -> None:
    """复算 prediction 核心证据，不信任自报 passed 或指标值。"""
    descriptor_by_path = {item["path"]: item for item in descriptors}
    schema_bindings = {
        "prediction_result.json": "formal_result_prediction_result.schema.json",
        "prediction_validation.json": "formal_result_prediction_validation.schema.json",
        "prediction_reproducibility_certificate.json": (
            "formal_result_prediction_certificate.schema.json"
        ),
        "negative_tests.json": "formal_result_prediction_negative_tests.schema.json",
    }
    for path, expected_schema in schema_bindings.items():
        if descriptor_by_path[path].get("schema") != expected_schema:
            raise FormalResultVerificationError(
                f"{path} 的 descriptor.schema 未绑定 {expected_schema}"
            )
    if set(domain["output_file_set"]) != set(contract.output_file_set):
        raise FormalResultVerificationError("Prediction Domain Manifest output_file_set 非法")

    result = values["prediction_result.json"]
    validation = values["prediction_validation.json"]
    certificate = values["prediction_reproducibility_certificate.json"]
    negative = values["negative_tests.json"]
    statuses = (
        result["status"],
        validation["status"],
        certificate["status"],
        negative["status"],
    )
    if statuses == (
        "execution_pending",
        "execution_pending",
        "execution_pending",
        "execution_pending",
    ):
        if any(
            value["payload"] != {"execution_pending": True}
            for value in (result, validation, certificate, negative)
        ):
            raise FormalResultVerificationError(
                "Prediction 候选的 execution_pending 载荷非法"
            )
        return
    if statuses != ("collected", "passed", "passed", "passed"):
        raise FormalResultVerificationError("Prediction 核心工件状态未原子推进")
    recomputed = recompute_prediction_metrics(result["payload"])
    reported_tasks = {item["task_id"]: item for item in validation["payload"]["tasks"]}
    if set(recomputed) != set(reported_tasks):
        raise FormalResultVerificationError("prediction_validation 的任务集合与 prediction_result 不一致")
    required_metrics = set(domain["required_metrics"])
    tolerance = float(domain["metric_tolerance"])
    for task_id, metrics in recomputed.items():
        reported = reported_tasks[task_id]
        if reported["status"] != "passed":
            raise FormalResultVerificationError(f"任务 {task_id} 的 prediction_validation 未通过")
        reported_metrics = reported["metrics"]
        if not required_metrics.issubset(reported_metrics):
            raise FormalResultVerificationError(f"任务 {task_id} 缺少必需预测指标")
        for metric_name, reported_value in reported_metrics.items():
            if metric_name not in metrics:
                raise FormalResultVerificationError(
                    f"任务 {task_id} 声明了不可复算指标：{metric_name}"
                )
            if abs(_as_number(reported_value, metric_name) - metrics[metric_name]) > tolerance:
                raise FormalResultVerificationError(
                    f"任务 {task_id} 的 {metric_name} 与逐样本复算结果不一致"
                )
    split_check = validation["payload"]["patient_split_check"]
    if split_check["status"] != "passed" or split_check["overlap_group_count"] != 0:
        raise FormalResultVerificationError("prediction_validation 患者级拆分检查未通过")
    if any(item["status"] != "passed" for item in validation["payload"]["fit_scope_checks"]):
        raise FormalResultVerificationError("prediction_validation 训练折预处理检查未通过")
    payload = certificate["payload"]
    if (
        payload["claim_scope"] != "held_out_predictive_performance"
        or payload["preprocessing_scope"] != "training_only"
        or payload["screening_only"] is not True
        or payload["causal_claims_supported"] is not False
    ):
        raise FormalResultVerificationError("Prediction 证书的结论边界非法")
