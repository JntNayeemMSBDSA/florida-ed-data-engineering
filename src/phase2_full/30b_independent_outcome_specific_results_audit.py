#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/30b_independent_outcome_specific_results_audit.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Independently audit outcome-specific confirmatory primary models."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(16 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    os.replace(temporary, path)


def load_primary_auditor(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(
        "phase2_primary_auditor", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load primary auditor from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    parser.add_argument("--matrix-root", required=True, type=Path)
    parser.add_argument("--primary-scratch", required=True, type=Path)
    parser.add_argument("--row-chunk", type=int, default=333_333)
    args = parser.parse_args()

    phase2 = args.phase2.resolve()
    matrix_root = args.matrix_root.resolve()
    primary_scratch = args.primary_scratch.resolve()
    audit_module = load_primary_auditor(
        phase2 / "scripts" / "30_independent_primary_results_audit.py"
    )
    provider_gate_path = phase2 / "qa" / "pre_estimation_measurement_gate.json"
    cohort_gate_path = phase2 / "qa" / "cohort_validation_report.json"
    gender_checkpoint_path = (
        phase2 / "qa" / "provider_gender_measurement_checkpoint.json"
    )
    live_gate_hashes = {
        "provider_gate_sha256": sha256_file(provider_gate_path),
        "cohort_gate_sha256": sha256_file(cohort_gate_path),
        "gender_checkpoint_sha256": sha256_file(gender_checkpoint_path),
    }
    for path in (
        provider_gate_path,
        cohort_gate_path,
        gender_checkpoint_path,
    ):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("status") != "PASS":
            raise SystemExit(f"Required gate does not pass: {path}")

    target_specs = (
        (
            "los",
            "los_outcome",
            "los_hours_primary_0_168",
        ),
        (
            "charge",
            "charge_outcome",
            "total_charge_reported_real_2024",
        ),
    )
    all_rows: list[dict[str, Any]] = []
    details: dict[str, Any] = {}
    structural_checks: list[dict[str, Any]] = []
    for cohort in ("race", "sex_gender"):
        for short_id, sample_policy, outcome in target_specs:
            matrix_id = f"{cohort}__{short_id}"
            root = matrix_root / matrix_id
            manifest = json.loads(
                (root / "matrix_manifest.json").read_text(encoding="utf-8")
            )
            results_root = (
                phase2 / "results" / "outcome_specific_primary" / short_id
            )
            result_manifest_path = (
                results_root
                / cohort
                / "primary_models_manifest.json"
            )
            result_manifest = json.loads(
                result_manifest_path.read_text(encoding="utf-8")
            )
            expected = {
                "matrix_id": matrix_id,
                "analysis_sample_policy": sample_policy,
                "eligibility_policy": "primary",
                "primary_outcomes": [outcome],
                "outcomes": [outcome],
                "outcome_specific_confirmatory_sample": True,
                "outcome_specific_sample": True,
                "confirmatory_designated": True,
                "provider_measurement_version": (
                    "provider_master_v2_full_name_race_v1"
                ),
                **live_gate_hashes,
            }
            structural_pass = all(
                manifest.get(key) == value for key, value in expected.items()
            ) and all(
                result_manifest.get(key) == value
                for key, value in {
                    "matrix_id": matrix_id,
                    "analysis_sample_policy": sample_policy,
                    "eligibility_policy": "primary",
                    "outcome_specific_confirmatory_sample": True,
                    "outcome_specific_sample": True,
                    "confirmatory_designated": True,
                    "provider_measurement_version": (
                        "provider_master_v2_full_name_race_v1"
                    ),
                    **live_gate_hashes,
                }.items()
            )
            structural_checks.append(
                {
                    "cohort": cohort,
                    "outcome": outcome,
                    "matrix_id": matrix_id,
                    "audit_check": (
                        "outcome_specific_sample_and_live_gate_binding"
                    ),
                    "passed": bool(structural_pass),
                    "details": json.dumps(expected, sort_keys=True),
                }
            )
            rows, payload = audit_module.audit_cohort(
                phase2,
                matrix_root,
                primary_scratch / short_id,
                cohort,
                args.row_chunk,
                matrix_id=matrix_id,
                results_root=results_root,
                scratch_id=cohort,
            )
            for row in rows:
                row["confirmatory_outcome"] = outcome
            all_rows.extend(rows)
            details[f"{cohort}__{short_id}"] = payload

    table = pd.DataFrame([*structural_checks, *all_rows])
    table["passed"] = table["passed"].map(bool)
    qa = phase2 / "qa"
    csv_path = qa / "independent_outcome_specific_results_audit.csv"
    table.to_csv(csv_path, index=False)
    summary = {
        "created_utc": now_utc(),
        "audit_id": "outcome_specific_primary_results_audit_v1",
        "confirmatory_sample_policy": (
            "each outcome uses every exposure-eligible encounter with that "
            "outcome observed; the other confirmatory outcome is not required"
        ),
        "common_sample_models_are_robustness_only": True,
        "checks": len(table),
        "passed_checks": int(table["passed"].sum()),
        "failed_checks": int((~table["passed"]).sum()),
        "all_passed": bool(table["passed"].all()),
        "details": details,
        "artifacts": {
            "check_table": str(csv_path),
            "matrix_root": str(matrix_root),
            "results_root": str(
                phase2 / "results" / "outcome_specific_primary"
            ),
        },
    }
    atomic_json(
        qa / "independent_outcome_specific_results_audit.json",
        summary,
    )
    if not summary["all_passed"]:
        raise RuntimeError(
            "Outcome-specific confirmatory results audit failed"
        )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
