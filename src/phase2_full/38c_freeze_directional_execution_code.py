#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/38c_freeze_directional_execution_code.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Freeze the tested directional execution code before real-data fitting."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CODE_FILES = (
    "scripts/08_estimate_primary_models.py",
    "scripts/39_build_directional_outcome_matrix.py",
    "scripts/40_independent_directional_matrix_audit.py",
    "scripts/41_estimate_directional_models.py",
    "scripts/42_independent_directional_result_audit.py",
    "scripts/42b_directional_inference_engine_tests.py",
    "scripts/46b_directional_measurement_sensitivity_tests.py",
    "scripts/47_estimate_directional_measurement_sensitivities.py",
    "scripts/48_independent_directional_measurement_sensitivity_audit.py",
    "scripts/48b_aggregate_directional_measurement_sensitivity_audits.py",
    "scripts/43_apply_directional_multiplicity.py",
    "scripts/43b_independent_directional_family_audit.py",
    "scripts/44_compact_directional_intermediates.py",
    "scripts/RUN_DIRECTIONAL_DYADS_SAFE.ps1",
)


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(4 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    os.replace(temporary, path)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def file_record(phase2: Path, relative: str) -> dict[str, Any]:
    path = phase2 / relative
    if not path.is_file():
        raise SystemExit(f"Directional execution file missing: {path}")
    return {
        "path": relative,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    args = parser.parse_args()
    phase2 = args.phase2.resolve()
    implementation_path = (
        phase2
        / "documentation"
        / "Directional_Dyad_Model_Implementation_FROZEN.json"
    )
    implementation_gate_path = (
        phase2
        / "qa"
        / "directional_model_implementation_pre_estimation_gate.json"
    )
    definition_tests_path = (
        phase2 / "qa" / "directional_model_definition_tests.json"
    )
    inference_tests_path = (
        phase2 / "qa" / "directional_inference_engine_tests.json"
    )
    measurement_tests_path = (
        phase2 / "qa" / "directional_measurement_sensitivity_tests.json"
    )
    for path in (
        implementation_path,
        implementation_gate_path,
        definition_tests_path,
        inference_tests_path,
        measurement_tests_path,
    ):
        if not path.is_file():
            raise SystemExit(f"Directional execution prerequisite missing: {path}")
    implementation = load_json(implementation_path)
    implementation_gate = load_json(implementation_gate_path)
    definition_tests = load_json(definition_tests_path)
    inference_tests = load_json(inference_tests_path)
    measurement_tests = load_json(measurement_tests_path)
    if (
        implementation.get("status") != "FROZEN_ESTIMATE_BLIND_PASS"
        or implementation_gate.get("status") != "PASS"
        or definition_tests.get("status") != "PASS"
        or inference_tests.get("status") != "PASS"
        or measurement_tests.get("status") != "PASS"
    ):
        raise SystemExit("Directional execution prerequisite does not pass")
    result_root = phase2 / "results" / "directional_dyads" / "models"
    preexisting_result_files = (
        [
            path
            for path in result_root.rglob("*")
            if path.is_file()
            and path.name
            in {
                "directional_adjusted_predictions.csv",
                "directional_planned_contrasts.csv",
                "directional_estimation_manifest.json",
            }
        ]
        if result_root.is_dir()
        else []
    )
    if preexisting_result_files:
        raise SystemExit(
            "Cannot freeze execution code after real directional result files "
            "exist"
        )
    code_inventory = [file_record(phase2, value) for value in CODE_FILES]
    payload = {
        "status": "FROZEN_ESTIMATE_BLIND_PASS",
        "execution_version": "directional_execution_code_v1_20260726",
        "frozen_utc": now_utc(),
        "purpose": (
            "Bind the storage-safe outcome-specific matrix, audit, estimation, "
            "multiplicity, and compaction implementation to the already frozen "
            "scientific directional-dyad specification before real-data fit."
        ),
        "scientific_design_changed": False,
        "implementation_refinement": (
            "Outcome-specific sequential matrices and post-audit compaction "
            "implement the frozen storage/restart contract without changing "
            "samples, cells, covariates, fixed effects, estimands, clustering, "
            "or multiplicity families."
        ),
        "parent_implementation": {
            "path": "documentation/Directional_Dyad_Model_Implementation_FROZEN.json",
            "sha256": sha256_file(implementation_path),
        },
        "parent_implementation_gate": {
            "path": "qa/directional_model_implementation_pre_estimation_gate.json",
            "sha256": sha256_file(implementation_gate_path),
        },
        "definition_tests": {
            "path": "qa/directional_model_definition_tests.json",
            "sha256": sha256_file(definition_tests_path),
            "checks_passed": definition_tests["checks_passed"],
            "checks_total": definition_tests["checks_total"],
        },
        "inference_engine_tests": {
            "path": "qa/directional_inference_engine_tests.json",
            "sha256": sha256_file(inference_tests_path),
            "checks_passed": inference_tests["checks_passed"],
            "checks_total": inference_tests["checks_total"],
        },
        "measurement_sensitivity_tests": {
            "path": "qa/directional_measurement_sensitivity_tests.json",
            "sha256": sha256_file(measurement_tests_path),
            "checks_passed": measurement_tests["checks_passed"],
            "checks_total": measurement_tests["checks_total"],
        },
        "code_inventory": code_inventory,
        "execution_sequence": [
            "build outcome-specific matrix",
            "independent file/source/support/rank audit",
            "estimate U0/M2/M3 without printing values",
            "independent beta/covariance/prediction/contrast/bootstrap audit",
            "for the two primary outcomes, estimate and independently audit "
            "five-class prior, threshold, and 20-NPI-imputation race "
            "measurement sensitivities before compaction",
            "compact only after PASS",
            "aggregate all 99 result sets",
            "independently recompute frozen BH families",
        ],
        "expected_complete_grid": {
            "families": 3,
            "outcomes": 33,
            "audited_result_sets": 99,
            "gender_cells": 4,
            "race_cells": 25,
            "intersectional_cells": 100,
            "gender_contrasts": 6,
            "race_contrasts": 68,
            "intersectional_contrasts": 359,
            "measurement_sensitivity_result_sets": 4,
            "measurement_sensitivity_direct_modes_per_set": 9,
            "measurement_sensitivity_imputations_per_prior": 20,
            "measurement_sensitivity_priors": 2,
        },
        "real_directional_result_files_at_freeze": 0,
        "real_directional_values_read": False,
        "result_interpretation_authorized": False,
        "language_rule": (
            "Association language only. Physician race remains probabilistic, "
            "algorithm-inferred, not self-reported, and not BISG."
        ),
        "source_release_modified": False,
        "phase2_cohort_modified": False,
    }
    output = (
        phase2
        / "documentation"
        / "Directional_Dyad_Execution_Code_FROZEN.json"
    )
    atomic_json(output, payload)
    gate = {
        "status": "PASS",
        "created_utc": now_utc(),
        "execution_manifest": {
            "path": str(output.resolve()),
            "sha256": sha256_file(output),
            "bytes": output.stat().st_size,
        },
        "estimate_blind": True,
        "outcome_specific_matrix_construction_authorized": True,
        "model_estimation_authorized_after_independent_matrix_audit": True,
        "result_interpretation_authorized": False,
        "source_release_modified": False,
        "phase2_cohort_modified": False,
    }
    gate_path = phase2 / "qa" / "directional_execution_code_gate.json"
    atomic_json(gate_path, gate)
    print(
        json.dumps(
            {
                "status": "PASS",
                "execution_manifest": str(output),
                "execution_manifest_sha256": gate["execution_manifest"][
                    "sha256"
                ],
                "code_files_frozen": len(code_inventory),
                "real_directional_result_files_at_freeze": 0,
                "result_interpretation_authorized": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
