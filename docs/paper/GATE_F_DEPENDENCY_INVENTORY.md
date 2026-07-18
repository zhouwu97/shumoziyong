# Gate F 依赖差异清单

本清单用于从 `codex/trusted-competition-hardening` 基线拆分 Gate F。它把低耦合核心、生产接线和 Run/资格接线分开，禁止通过一次性 cherry-pick 隐式引入运行时依赖。

## A：核心引擎，可独立审查

| 路径 | 类型 | 依赖 | 目标 PR |
| --- | --- | --- | --- |
| `paper_content_contracts/generic_submission_v1.yaml` | 通用合同 | YAML、合同解析器 | PR A |
| `paper_content_contracts/2025_C_prediction_nipt_v1.yaml` | 题目合同 | 父合同解析 | PR A |
| `schemas/paper_content_delta_report.schema.json` | Schema | JSON Schema | PR A |
| `schemas/paper_evidence_role_registry.schema.json` | Schema | JSON Schema | PR A |
| `schemas/paper_substantive_completeness_report.schema.json` | Schema | JSON Schema | PR A |
| `schemas/paper_gate_f_status.schema.json` | Schema | JSON Schema | PR A |
| `schemas/paper_internal_content_repair_candidate.schema.json` | Schema | JSON Schema | PR A |
| `scripts/paper/paper_content_quality.py` | 引擎 | 合同、Registry、文件系统 | PR A |
| `scripts/paper/gate_f_status.py` | 状态派生 | F2 报告、F3 引用 | PR A |
| `tests/paper/test_paper_content_quality.py` | 纯单元测试 | A 层文件 | PR A |

## B：论文生产接线，需要目标基线手工适配

| 路径/能力 | 当前依赖 | 目标 PR |
| --- | --- | --- |
| `scripts/paper/build_gate4_pipeline.py` | Gate 4 状态、Candidate Manifest、渲染和 Formal Result | PR B |
| Candidate 创建与不可变指针 | `review_pipeline.py`、Candidate Schema、history | PR B |
| 最终人工交接阻断 | `run_workflow.py` handoff、Gate 5 v2 | PR B |
| Gate G eligibility | Gate F 状态与 Gate 5 聚合 | PR B |

## C：Run/资格接线，必须逐字段合并

| 字段/能力 | 当前依赖 | 目标 PR |
| --- | --- | --- |
| 合同 ID、解析版本、源文件 SHA、合并 SHA | `run_manifest.json` 初始化 | PR B |
| `legacy_paper_content_policy` | 历史 Run 识别与 fail-closed | PR B |
| 合同文件复制与 Runtime Pack 冻结 | Run 初始化流程 | PR B |
| Gate 5 / Gate G 资格状态 | 资格边界、人工审核历史 | PR B |

## D：真实 Pilot，不属于功能 PR

| 证据 | 要求 | 目标 PR |
| --- | --- | --- |
| 七页旧 Candidate 负例 | Candidate、PDF、Formal Result、Claim Map 可现场复验 | PR C |
| F2 Fail -> Pass | 新 Formal Result、Validator、Claim Map、Candidate | PR C |
| GitHub Actions | pytest、仓库校验、Ruff 的远端记录 | PR B/C |

## 当前结论

trusted 基线可以承载 A 层核心引擎；B/C 层不能通过盲目 cherry-pick 接入，必须在采用最终 Candidate/Gate 5 版本后逐项手工接线。
