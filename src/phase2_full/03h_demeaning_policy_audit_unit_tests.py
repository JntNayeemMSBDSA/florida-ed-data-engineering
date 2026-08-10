#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/03h_demeaning_policy_audit_unit_tests.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Synthetic tests for the independent demeaning-provenance audit."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def load_module(path: Path) -> Any:
    name = "primary_matrix_auditor_under_synthetic_test"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def state_payload(
    *,
    fallback: bool = False,
    invalid_fallback: bool = False,
    incomplete: bool = False,
) -> dict[str, Any]:
    attempts: dict[str, dict[str, Any]] = {}
    expected = {
        "x_0_2": [1, 2],
        "y_0_2": [0, 1],
    }
    for key, source in expected.items():
        if fallback and key == "x_0_2":
            attempts[key] = {
                "source_columns": source,
                "strict_tolerance": 1e-8,
                "strict_maxiter": 10_000,
                "strict_status": (
                    "CONVERGED" if invalid_fallback else "NONCONVERGED"
                ),
                "fallback_tolerance": 1e-6,
                "fallback_maxiter": 50_000,
                "fallback_status": "CONVERGED",
                "final_method": "fallback",
                "fallback_used": True,
                "final_status": "CONVERGED",
            }
        else:
            attempts[key] = {
                "source_columns": source,
                "strict_tolerance": 1e-8,
                "strict_maxiter": 10_000,
                "strict_status": "CONVERGED",
                "final_method": "strict",
                "fallback_used": False,
                "final_status": "CONVERGED",
            }
    if incomplete:
        attempts.pop("y_0_2")
    return {
        "n_rows": 12,
        "column_indices": [1, 2],
        "fe_indices": [1, 2],
        "completed_local_columns": [0, 1],
        "completed_outcome_columns": ([] if incomplete else [0, 1]),
        "outcomes_completed": not incomplete,
        "convergence": {
            key: True for key in attempts
        },
        "demeaning_attempts": attempts,
        "numerical_policy": {
            "strict": {
                "tolerance": 1e-8,
                "maxiter": 10_000,
                "backend": "rust",
            },
            "fallback_only_after_documented_strict_nonconvergence": {
                "tolerance": 1e-6,
                "maxiter": 50_000,
                "backend": "rust",
            },
            "sample_formula_fixed_effects_and_columns_changed": False,
        },
        "checkpoint_binding": {"synthetic": "v1"},
    }


def write_case(
    root: Path,
    source_phase2: Path,
    *,
    fallback: bool = False,
    invalid_fallback: bool = False,
    incomplete: bool = False,
) -> tuple[Path, Path, Path, dict[str, Any], dict[str, Any]]:
    phase2 = root / "phase2"
    scratch = root / "scratch"
    results = root / "results"
    (phase2 / "scripts").mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        source_phase2 / "scripts" / "08_estimate_primary_models.py",
        phase2 / "scripts" / "08_estimate_primary_models.py",
    )
    engine_hash = sha256_file(
        phase2 / "scripts" / "08_estimate_primary_models.py"
    )
    matrix_manifest = {
        "n_rows": 12,
        "outcomes": ["outcome_a", "outcome_b"],
    }
    result_manifest = {
        "model_ids": [
            "m1_patient_adjusted",
            "m2_fully_adjusted_facility_yq_clinical_fe",
            "m3_physician_facility_yq_clinical_fe",
        ],
        "inference_engine_sha256": engine_hash,
    }
    for model_id in result_manifest["model_ids"][1:]:
        state = state_payload(
            fallback=fallback,
            invalid_fallback=invalid_fallback,
            incomplete=incomplete,
        )
        atomic_json(
            scratch / "synthetic" / model_id / "demeaning_state.json",
            state,
        )
        fallback_keys = [
            key
            for key, value in state["demeaning_attempts"].items()
            if value["fallback_used"]
        ]
        atomic_json(
            results / "race" / f"{model_id}_diagnostics.json",
            {
                "demeaning": {
                    "converged": not incomplete,
                    "block_columns": 4,
                    "fallback_used": bool(fallback_keys),
                    "fallback_blocks": fallback_keys,
                    "checkpoint_binding": {"synthetic": "v1"},
                }
            },
        )
    return (
        phase2,
        scratch,
        results,
        matrix_manifest,
        result_manifest,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    args = parser.parse_args()
    source_phase2 = args.phase2.resolve()
    auditor = load_module(
        source_phase2
        / "scripts"
        / "30e_checkpoint_primary_matrix_audit.py"
    )
    checks: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(
        prefix="demeaning_policy_audit_test_"
    ) as temporary:
        test_root = Path(temporary)
        cases = (
            ("strict_complete_passes", {}, True),
            ("documented_fallback_passes", {"fallback": True}, True),
            (
                "fallback_without_strict_failure_fails",
                {"fallback": True, "invalid_fallback": True},
                False,
            ),
            ("incomplete_grid_fails", {"incomplete": True}, False),
        )
        for index, (check_id, options, expected) in enumerate(cases):
            case_root = test_root / f"case_{index}"
            phase2, scratch, results, matrix, result = write_case(
                case_root, source_phase2, **options
            )
            passed, details = auditor.audit_demeaning_policy(
                phase2,
                scratch,
                "synthetic",
                results,
                "race",
                matrix,
                result,
                "synthetic_audit",
            )
            checks.append(
                {
                    "check_id": check_id,
                    "passed": passed is expected,
                    "expected_audit_pass": expected,
                    "observed_audit_pass": passed,
                    "observed_failures": details["failures"],
                }
            )
    failures = [
        item["check_id"] for item in checks if item["passed"] is not True
    ]
    payload = {
        "status": "PASS" if not failures else "FAIL",
        "test_id": "independent_demeaning_policy_audit_unit_tests_v1",
        "checks_passed": len(checks) - len(failures),
        "checks_total": len(checks),
        "checks": checks,
        "failures": failures,
        "synthetic_only": True,
        "real_data_loaded": False,
        "real_result_values_read": False,
        "source_release_modified": False,
        "phase2_cohort_modified": False,
    }
    output = source_phase2 / "qa" / "demeaning_policy_audit_unit_tests.json"
    atomic_json(output, payload)
    print(
        json.dumps(
            {
                "status": payload["status"],
                "checks_passed": payload["checks_passed"],
                "checks_total": payload["checks_total"],
                "failures": failures,
                "real_result_values_read": False,
            },
            indent=2,
        )
    )
    if failures:
        raise RuntimeError(f"Synthetic demeaning audit tests failed: {failures}")


if __name__ == "__main__":
    main()
