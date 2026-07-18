"""2024-C Q2-A 情景母池生成与确定性 Manifest。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping

import numpy as np

from .data_model import YEARS, ProblemData


CONTRACT_ID = "2024c-q2-uncertainty-v1"
GENERATOR_VERSION = "2024c-q2-scenario-generator-v1"


@dataclass(frozen=True)
class ScenarioKeyCatalog:
    """情景参数的规范键顺序和 2023 官方基准值。"""

    sales_keys: tuple[tuple[int, str, int], ...]
    sales_base: tuple[float, ...]
    sales_rules: tuple[str, ...]
    yield_keys: tuple[tuple[int, int], ...]
    cost_keys: tuple[tuple[str, str, int, int], ...]
    cost_base: tuple[float, ...]
    price_keys: tuple[tuple[int, str, int], ...]
    price_base: tuple[float, ...]
    price_rules: tuple[str, ...]


def _canonical_bytes(value: object) -> bytes:
    """按 Q2 合同生成无尾换行的规范 JSON 字节。"""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_path(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _crop_rule(data: ProblemData, crop_id: int, *, price: bool) -> str:
    crop = data.crops[crop_id]
    name = crop.name
    crop_type = crop.crop_type
    if price:
        if "羊肚菌" in name:
            return "morel_fixed_decline"
        if "蔬菜" in crop_type:
            return "vegetable_growth"
        if "食用菌" in crop_type or "菌" in crop_type:
            return "mushroom_decline"
        if "粮食" in crop_type or "小麦" in name or "玉米" in name:
            return "stable"
    elif "小麦" in name or "玉米" in name:
        return "wheat_corn_growth"
    else:
        return "other_change"
    raise ValueError(f"官方作物无法映射 Q2 随机规则：crop_id={crop_id}, type={crop_type!r}")


def build_key_catalog(data: ProblemData) -> ScenarioKeyCatalog:
    """从官方作物字典和统计表构造规范采样键。"""

    eligible: set[tuple[int, str]] = set()
    cost_pairs: set[tuple[str, str, int]] = set()
    for plot_type in sorted({plot.plot_type for plot in data.plots.values()}):
        for season in data.seasons(plot_type):
            for crop_id in data.eligible_crops(plot_type, season):
                eligible.add((crop_id, season))
                cost_pairs.add((plot_type, season, crop_id))

    sales_keys = tuple(
        (crop_id, season, year)
        for year in YEARS
        for crop_id, season in sorted(eligible)
    )
    sales_base = tuple(data.expected_sales_2023.get((crop_id, season), 0.0) for crop_id, season, _ in sales_keys)
    sales_rules = tuple(_crop_rule(data, crop_id, price=False) for crop_id, _, _ in sales_keys)

    yield_keys = tuple((crop_id, year) for year in YEARS for crop_id in sorted(data.crops))

    cost_keys = tuple(
        (plot_type, season, crop_id, year)
        for year in YEARS
        for plot_type, season, crop_id in sorted(cost_pairs, key=lambda item: (item[2], item[0], item[1]))
    )
    cost_base = tuple(
        data.stat(crop_id, plot_type, season).cost_yuan_per_mu
        for plot_type, season, crop_id, _ in cost_keys
    )

    price_keys = sales_keys
    price_base = []
    price_rules = []
    for crop_id, season, _ in price_keys:
        matching = [
            data.stat(crop_id, plot_type, season).price_mid_yuan_per_jin
            for plot_type in sorted({plot.plot_type for plot in data.plots.values()})
            if crop_id in data.eligible_crops(plot_type, season)
        ]
        if not matching:
            raise ValueError(f"官方作物缺少销售价格基准：crop_id={crop_id}, season={season}")
        if any(abs(value - matching[0]) > 1e-9 for value in matching[1:]):
            raise ValueError(f"同一销售组价格基准不一致：crop_id={crop_id}, season={season}")
        price_base.append(matching[0])
        price_rules.append(_crop_rule(data, crop_id, price=True))

    return ScenarioKeyCatalog(
        sales_keys=sales_keys,
        sales_base=tuple(float(value) for value in sales_base),
        sales_rules=sales_rules,
        yield_keys=yield_keys,
        cost_keys=cost_keys,
        cost_base=tuple(float(value) for value in cost_base),
        price_keys=price_keys,
        price_base=tuple(float(value) for value in price_base),
        price_rules=tuple(price_rules),
    )


def _catalog_manifest(catalog: ScenarioKeyCatalog) -> dict[str, Any]:
    return {
        "sales": {
            "keys": [
                {"crop_id": crop_id, "season": season, "year": year}
                for crop_id, season, year in catalog.sales_keys
            ],
            "base_demand_jin": list(catalog.sales_base),
            "rules": list(catalog.sales_rules),
        },
        "yield": {
            "keys": [
                {"crop_id": crop_id, "year": year} for crop_id, year in catalog.yield_keys
            ],
        },
        "cost": {
            "keys": [
                {"plot_type": plot_type, "season": season, "crop_id": crop_id, "year": year}
                for plot_type, season, crop_id, year in catalog.cost_keys
            ],
            "base_cost_yuan_per_mu": list(catalog.cost_base),
        },
        "price": {
            "keys": [
                {"crop_id": crop_id, "season": season, "year": year}
                for crop_id, season, year in catalog.price_keys
            ],
            "base_price_yuan_per_jin": list(catalog.price_base),
            "rules": list(catalog.price_rules),
        },
    }


def _rngs(seed: int) -> tuple[np.random.Generator, ...]:
    sequence = np.random.SeedSequence(entropy=seed, spawn_key=(2024, 3, 2))
    return tuple(np.random.Generator(np.random.PCG64(child)) for child in sequence.spawn(4))


def _uniform(rng: np.random.Generator, low: float, high: float) -> float:
    value = float(rng.uniform(low, high))
    if not np.isfinite(value):
        raise ValueError("情景抽样产生非有限值")
    return value


def iter_scenario_payloads(
    catalog: ScenarioKeyCatalog,
    contract: Mapping[str, Any],
    phase: str,
    seed: int,
    pool_size: int | None = None,
) -> Iterator[dict[str, Any]]:
    """按固定子流顺序逐个生成一个 seed 的情景母池。"""

    random = contract["random"]
    if np.__version__ != random["numpy_version"]:
        raise ValueError(
            f"NumPy 版本与 Q2 合同不一致：expected={random['numpy_version']}, actual={np.__version__}"
        )
    if random["bit_generator"] != "PCG64" or random["uniform_interval"] != "[low, high)":
        raise ValueError("Q2 随机合同身份不匹配")
    expected_pool = int(random["scenario_pool_per_seed"])
    pool_size = expected_pool if pool_size is None else pool_size
    if not 0 < pool_size <= expected_pool:
        raise ValueError(f"情景母池长度必须在 1..{expected_pool} 内：{pool_size}")
    if phase not in {"opt", "eval"}:
        raise ValueError(f"未知情景阶段：{phase}")

    sales_rng, yield_rng, cost_rng, price_rng = _rngs(seed)
    params = contract["uncertain_parameters"]
    for scenario_index in range(pool_size):
        sales_growth: list[float] = []
        for crop_id, _, _ in catalog.sales_keys:
            rule = catalog.sales_rules[len(sales_growth)]
            limits = params["sales_wheat_corn_growth" if rule == "wheat_corn_growth" else "sales_other_change"]
            sales_growth.append(_uniform(sales_rng, float(limits["low"]), float(limits["high"])))

        yield_limits = params["yield_factor"]
        yield_factor = [
            _uniform(yield_rng, float(yield_limits["low"]), float(yield_limits["high"]))
            for _ in catalog.yield_keys
        ]

        cost_growth: list[float] = []
        limits = params["cost_growth"]
        for _ in catalog.cost_keys:
            cost_growth.append(_uniform(cost_rng, float(limits["low"]), float(limits["high"])))

        price_growth: list[float] = []
        for rule in catalog.price_rules:
            if rule == "stable":
                price_growth.append(0.0)
            elif rule == "vegetable_growth":
                limits = params["vegetable_price_growth"]
                price_growth.append(_uniform(price_rng, float(limits["low"]), float(limits["high"])))
            elif rule == "mushroom_decline":
                limits = params["mushroom_price_decline"]
                price_growth.append(_uniform(price_rng, float(limits["low"]), float(limits["high"])))
            elif rule == "morel_fixed_decline":
                price_growth.append(float(params["morel_price_decline"]["value"]))
            else:
                raise ValueError(f"未知价格规则：{rule}")

        yield {
            "schema_version": "1.0.0",
            "phase": phase,
            "seed": seed,
            "scenario_index": scenario_index,
            "scenario_id": f"{phase}_seed_{seed}_scenario_{scenario_index:04d}",
            "sales_growth": sales_growth,
            "yield_factor": yield_factor,
            "cost_growth": cost_growth,
            "price_growth": price_growth,
        }


def _scenario_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    payload_bytes = _canonical_bytes(payload)
    summary: dict[str, Any] = {
        "phase": payload["phase"],
        "seed": payload["seed"],
        "scenario_index": payload["scenario_index"],
        "scenario_id": payload["scenario_id"],
        "parameter_sha256": sha256_bytes(payload_bytes),
        "parameter_counts": {
            name: len(payload[name]) for name in ("sales_growth", "yield_factor", "cost_growth", "price_growth")
        },
    }
    for name in ("sales_growth", "yield_factor", "cost_growth", "price_growth"):
        values = [float(value) for value in payload[name]]
        summary[f"{name}_min"] = min(values) if values else None
        summary[f"{name}_max"] = max(values) if values else None
    return summary


def generate_manifest_for_catalog(
    catalog: ScenarioKeyCatalog,
    contract: Mapping[str, Any],
    *,
    q1_baseline_manifest_sha256: str,
    material_manifest_sha256: str,
    q2_model_contract_sha256: str,
    scenario_generator_module_sha256: str,
    pool_size: int | None = None,
) -> dict[str, Any]:
    """生成不含时间戳的可复现 Q2-A Scenario Manifest。"""

    random = contract["random"]
    pool_size = int(random["scenario_pool_per_seed"] if pool_size is None else pool_size)
    opt_seeds = [int(seed) for seed in random["optimization_seed_groups"]]
    eval_seeds = [int(seed) for seed in random["evaluation_seed_groups"]]
    if set(opt_seeds) & set(eval_seeds):
        raise ValueError("优化和评估 seed 必须互不相交")

    scenarios: list[dict[str, Any]] = []
    for phase, seeds in (("opt", opt_seeds), ("eval", eval_seeds)):
        for seed in seeds:
            scenarios.extend(
                _scenario_summary(payload)
                for payload in iter_scenario_payloads(catalog, contract, phase, seed, pool_size)
            )

    expected_count = (len(opt_seeds) + len(eval_seeds)) * pool_size
    if len(scenarios) != expected_count:
        raise AssertionError("情景总数与 seed/母池公式不一致")
    ids = [item["scenario_id"] for item in scenarios]
    if len(ids) != len(set(ids)):
        raise AssertionError("情景 ID 不唯一")

    manifest: dict[str, Any] = {
        "schema_version": "1.0.0",
        "artifact_type": "2024c_q2_scenario_manifest",
        "generator_version": GENERATOR_VERSION,
        "contract_id": contract["contract_id"],
        "problem_id": "2024-C",
        "subproblem_id": "Q2",
        "status": "scenario_pool_frozen_solver_pending",
        "q1_baseline_manifest_sha256": q1_baseline_manifest_sha256,
        "q1_baseline_status": contract["q1_baseline"]["status"],
        "paired_baseline_scenario_id": contract["q1_baseline"]["paired_baseline_scenario_id"],
        "material_manifest_sha256": material_manifest_sha256,
        "q2_model_contract_sha256": q2_model_contract_sha256,
        "scenario_generator_module_sha256": scenario_generator_module_sha256,
        "random_identity": {
            "numpy_version": random["numpy_version"],
            "bit_generator": random["bit_generator"],
            "seed_sequence": random["seed_sequence"],
            "optimization_seed_groups": opt_seeds,
            "evaluation_seed_groups": eval_seeds,
            "scenario_pool_per_seed": pool_size,
            "scenario_identity": random["scenario_identity"],
            "canonical_json": random["scenario_manifest"]["canonical_json"],
        },
        "key_catalog": _catalog_manifest(catalog),
        "scenario_count": expected_count,
        "scenarios": scenarios,
        "q2_solver_started": False,
        "q2_validator_started": False,
        "production_ready": False,
    }
    manifest["manifest_sha256"] = sha256_bytes(_canonical_bytes(manifest))
    return manifest


def write_manifest(manifest: Mapping[str, Any], path: Path) -> str:
    """写入合同规定的无尾换行 JSON，并返回 Manifest SHA。"""

    payload = dict(manifest)
    declared = payload.pop("manifest_sha256", None)
    digest = sha256_bytes(_canonical_bytes(payload))
    if declared is not None and declared != digest:
        raise ValueError("Scenario Manifest 已有 SHA 与内容不一致")
    payload["manifest_sha256"] = digest
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical_bytes(payload))
    return digest


def validate_manifest(
    manifest: Mapping[str, Any],
    contract: Mapping[str, Any],
    catalog: ScenarioKeyCatalog,
) -> None:
    """重新生成并逐项验证五组情景、参数摘要和 Manifest 自身 SHA。"""

    copy = dict(manifest)
    declared = copy.pop("manifest_sha256", None)
    if not isinstance(declared, str) or declared != sha256_bytes(_canonical_bytes(copy)):
        raise ValueError("Scenario Manifest SHA 校验失败")
    random = contract["random"]
    expected_random_identity = {
        "numpy_version": random["numpy_version"],
        "bit_generator": random["bit_generator"],
        "seed_sequence": random["seed_sequence"],
        "optimization_seed_groups": [int(seed) for seed in random["optimization_seed_groups"]],
        "evaluation_seed_groups": [int(seed) for seed in random["evaluation_seed_groups"]],
        "scenario_pool_per_seed": int(random["scenario_pool_per_seed"]),
        "scenario_identity": random["scenario_identity"],
        "canonical_json": random["scenario_manifest"]["canonical_json"],
    }
    if manifest["random_identity"] != expected_random_identity:
        raise ValueError("Scenario Manifest random_identity 与合同不一致")
    if manifest["key_catalog"] != _catalog_manifest(catalog):
        raise ValueError("Scenario Manifest key_catalog 与官方数据不一致")
    if manifest["q1_baseline_status"] != contract["q1_baseline"]["status"]:
        raise ValueError("Scenario Manifest Q1 baseline 状态与合同不一致")
    if manifest["paired_baseline_scenario_id"] != contract["q1_baseline"]["paired_baseline_scenario_id"]:
        raise ValueError("Scenario Manifest 配对基线场景与合同不一致")
    pool = int(random["scenario_pool_per_seed"])
    expected_seeds = {
        "opt": {int(seed) for seed in random["optimization_seed_groups"]},
        "eval": {int(seed) for seed in random["evaluation_seed_groups"]},
    }
    if expected_seeds["opt"] & expected_seeds["eval"]:
        raise ValueError("优化和评估 seed 必须互不相交")
    expected_count = sum(len(seeds) for seeds in expected_seeds.values()) * pool
    if manifest["scenario_count"] != expected_count:
        raise ValueError("Scenario Manifest 情景总数错误")
    scenarios = manifest["scenarios"]
    actual: dict[tuple[str, int, int], Mapping[str, Any]] = {}
    for item in scenarios:
        phase = item["phase"]
        seed = int(item["seed"])
        index = int(item["scenario_index"])
        if phase not in expected_seeds or seed not in expected_seeds[phase]:
            raise ValueError("Scenario Manifest 使用了合同之外的 phase 或 seed")
        if not 0 <= index < pool:
            raise ValueError("Scenario Manifest 情景索引越界")
        key = (phase, seed, index)
        if key in actual:
            raise ValueError("Scenario Manifest 情景身份重复")
        expected_id = f"{phase}_seed_{seed}_scenario_{index:04d}"
        if item["scenario_id"] != expected_id:
            raise ValueError("Scenario Manifest 情景 ID 与复合身份不一致")
        actual[key] = item

    expected_keys = {
        (phase, seed, index)
        for phase, seeds in expected_seeds.items()
        for seed in seeds
        for index in range(pool)
    }
    if set(actual) != expected_keys:
        raise ValueError("Scenario Manifest 未完整覆盖合同规定的五组 0..511 情景")

    # 用同一合同和键目录重放每个情景，防止仅重算顶层 Manifest SHA 的伪造。
    for phase, seeds in expected_seeds.items():
        for seed in sorted(seeds):
            for payload in iter_scenario_payloads(catalog, contract, phase, seed, pool):
                key = (phase, seed, int(payload["scenario_index"]))
                expected_summary = _scenario_summary(payload)
                item = actual[key]
                for field in (
                    "parameter_sha256",
                    "parameter_counts",
                    "sales_growth_min",
                    "sales_growth_max",
                    "yield_factor_min",
                    "yield_factor_max",
                    "cost_growth_min",
                    "cost_growth_max",
                    "price_growth_min",
                    "price_growth_max",
                ):
                    if item[field] != expected_summary[field]:
                        raise ValueError(f"情景参数重放不一致：{key} field={field}")
