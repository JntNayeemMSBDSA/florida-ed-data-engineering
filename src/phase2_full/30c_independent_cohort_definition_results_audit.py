#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/30c_independent_cohort_definition_results_audit.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Independently audit adjusted linkage and race-semantics sensitivities."""

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
        "phase2_primary_auditor_for_cohort_sensitivity", path
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
    scratch_root = args.primary_scratch.resolve()
    auditor = load_primary_auditor(
        phase2 / "scripts" / "30_independent_primary_results_audit.py"
    )
    provider_gate_path = phase2 / "qa" / "pre_estimation_measurement_gate.json"
    cohort_gate_path = phase2 / "qa" / "cohort_validation_report.json"
    gender_checkpoint_path = (
        phase2 / "qa" / "provider_gender_measurement_checkpoint.json"
    )
    for gate_path in (
        provider_gate_path,
        cohort_gate_path,
        gender_checkpoint_path,
    ):
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        if gate.get("status") != "PASS":
            raise SystemExit(f"Required gate does not pass: {gate_path}")
    live_hashes = {
        "provider_gate_sha256": sha256_file(provider_gate_path),
        "cohort_gate_sha256": sha256_file(cohort_gate_path),
        "gender_checkpoint_sha256": sha256_file(gender_checkpoint_path),
    }

    variants = (
        (
            "direct_plus_unique_license_nh_t50",
            "race_direct_plus_unique_license_nh_t50",
        ),
        ("race_only_direct_t50", "race_only_direct_t50"),
    )
    outcomes = (
        ("los", "los_outcome", "los_hours_primary_0_168"),
        (
            "charge",
            "charge_outcome",
            "total_charge_reported_real_2024",
        ),
    )
    audit_rows: list[dict[str, Any]] = []
    structural_rows: list[dict[str, Any]] = []
    details: dict[str, Any] = {}
    for variant_id, eligibility_policy in variants:
        for outcome_id, sample_policy, outcome in outcomes:
            matrix_id = f"race__{variant_id}__{outcome_id}"
            matrix_manifest = json.loads(
                (
                    matrix_root / matrix_id / "matrix_manifest.json"
                ).read_text(encoding="utf-8")
            )
            results_root = (
                phase2
                / "results"
                / "cohort_definition_adjusted"
                / variant_id
                / outcome_id
            )
            result_manifest = json.loads(
                (
                    results_root
                    / "race"
                    / "primary_models_manifest.json"
                ).read_text(encoding="utf-8")
            )
            matrix_expected = {
                "matrix_id": matrix_id,
                "analysis_sample_policy": sample_policy,
                "eligibility_policy": eligibility_policy,
                "primary_outcomes": [outcome],
                "outcomes": [outcome],
                "outcome_specific_sample": True,
                "outcome_specific_confirmatory_sample": False,
                "confirmatory_designated": False,
                "provider_measurement_version": (
                    "provider_master_v2_full_name_race_v1"
                ),
                **live_hashes,
            }
            result_expected = {
                "matrix_id": matrix_id,
                "analysis_sample_policy": sample_policy,
                "eligibility_policy": eligibility_policy,
                "outcome_specific_sample": True,
                "outcome_specific_confirmatory_sample": False,
                "confirmatory_designated": False,
                "provider_measurement_version": (
                    "provider_master_v2_full_name_race_v1"
                ),
                **live_hashes,
            }
            structural_pass = all(
                matrix_manifest.get(key) == value
                for key, value in matrix_expected.items()
            ) and all(
                result_manifest.get(key) == value
                for key, value in result_expected.items()
            )
            structural_rows.append(
                {
                    "cohort": "race",
                    "variant_id": variant_id,
                    "outcome": outcome,
                    "matrix_id": matrix_id,
                    "audit_check": (
                        "cohort_definition_policy_and_live_gate_binding"
                    ),
                    "passed": bool(structural_pass),
                    "details": json.dumps(
                        {
                            "matrix_expected": matrix_expected,
                            "result_expected": result_expected,
                        },
                        sort_keys=True,
                    ),
                }
            )
            rows, payload = auditor.audit_cohort(
                phase2,
                matrix_root,
                scratch_root / variant_id / outcome_id,
                "race",
                args.row_chunk,
                matrix_id=matrix_id,
                results_root=results_root,
                scratch_id="race",
            )
            for row in rows:
                row["variant_id"] = variant_id
                row["sensitivity_outcome"] = outcome
            audit_rows.extend(rows)
            details[matrix_id] = payload

    table = pd.DataFrame([*structural_rows, *audit_rows])
    table["passed"] = table["passed"].map(bool)
    qa = phase2 / "qa"
    csv_path = (
        qa / "independent_cohort_definition_results_audit.csv"
    )
    table.to_csv(csv_path, index=False)
    summary = {
        "created_utc": now_utc(),
        "audit_id": "cohort_definition_adjusted_results_audit_v1",
        "confirmatory_status": "secondary sensitivity only",
        "sensitivity_variants": [item[0] for item in variants],
        "outcomes": [item[2] for item in outcomes],
        "checks": len(table),
        "passed_checks": int(table["passed"].sum()),
        "failed_checks": int((~table["passed"]).sum()),
        "all_passed": bool(table["passed"].all()),
        "details": details,
        "artifacts": {
            "check_table": str(csv_path),
            "matrix_root": str(matrix_root),
            "results_root": str(
                phase2 / "results" / "cohort_definition_adjusted"
            ),
        },
    }
    atomic_json(
        qa / "independent_cohort_definition_results_audit.json",
        summary,
    )
    if not summary["all_passed"]:
        raise RuntimeError(
            "Adjusted cohort-definition sensitivity audit failed"
        )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
