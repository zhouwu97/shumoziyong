# OpenCode + DeepSeek 2024-C Diagnostic Trial

## Purpose

This record captures a diagnostic run of the OpenCode execution chain with the official DeepSeek provider and the strict validator. It is not an A092 v4 run.

## Result

- The official DeepSeek execution chain completed normally.
- All four solution scenarios passed the implemented hard-constraint checks.
- Q1(1) and Q1(2) had absolute objective differences of 0.1164 yuan and 0.0505 yuan, exceeding the strict 1e-6 yuan threshold.
- Q2 and Q3 did not retain their effective perturbed parameters, so they cannot be independently recomputed.

The mathematical result is therefore not complete and is not promoted.

## Evidence Scope

This directory contains only the minimal diagnostic evidence:

- `strict_validation.json`: strict validation receipt.
- `strict_validation_diagnosis.json`: completed local root-cause diagnosis, bound by SHA-256 in the manifest.
- `trial_manifest.json`: execution metadata, non-counting status, and SHA-256 bindings to locally retained artifacts.

The complete local trial package, event stream, caches, source inputs, Excel exports, and provider configuration are not published here.

## Relationship To A092

This trial uses OpenCode with `deepseek/deepseek-v4-pro`, while A092 v4 freezes the Claude Code and Claude Opus controls. It does not create R01 or R02, does not modify A092 v4, and is not Baseline/Treatment evidence.

This record does not demonstrate that DeepSeek is better than Claude, and it does not establish whether A092 is valid or invalid.

## Follow-up

The completed diagnosis attributes Q1 to six-decimal decision serialization before the objective was independently recomputed; the four-decimal Excel export is an additional, larger loss. Q2/Q3 retain decisions but not the sampled effective parameters and selection evidence needed to reproduce their reported stochastic objectives. These are candidate-artifact defects, not evidence that A092 v4 must change.

Retain full-precision decisions and the Q2/Q3 effective parameters, then rerun the independent objective recomputation. Do not modify A092 v4 as part of that work.
