#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/38_freeze_directional_model_implementation.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Freeze the estimate-blind directional model implementation contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(16 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)


def require_status(path: Path, status: str = "PASS") -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("status") != status:
        raise RuntimeError(f"Required artifact is not {status}: {path}")
    return value


def file_record(phase2: Path, path: Path) -> dict[str, Any]:
    return {
        "path": path.resolve().relative_to(phase2.resolve()).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    args = parser.parse_args()
    phase2 = args.phase2.resolve()

    extension_path = (
        phase2
        / "documentation"
        / "Directional_Dyad_Analysis_Plan_Extension_FROZEN.json"
    )
    implementation_doc = (
        phase2
        / "documentation"
        / "Directional_Dyad_Model_Implementation_Specification.md"
    )
    base_manifest_path = (
        phase2
        / "analysis_data"
        / "directional_dyad_base"
        / "directional_dyad_base_manifest.json"
    )
    base_audit_path = (
        phase2 / "qa" / "independent_directional_dyad_base_audit.json"
    )
    support_manifest_path = (
        phase2
        / "results"
        / "directional_dyads"
        / "support"
        / "directional_support_manifest.json"
    )
    support_gate_path = phase2 / "qa" / "directional_cell_support_gate.json"
    support_audit_path = (
        phase2 / "qa" / "independent_directional_cell_support_audit.json"
    )
    provider_gate_path = (
        phase2 / "qa" / "pre_estimation_measurement_gate.json"
    )
    cohort_gate_path = phase2 / "qa" / "cohort_validation_report.json"
    extension_gate_path = (
        phase2
        / "qa"
        / "directional_dyad_extension_pre_estimation_gate.json"
    )
    for path in (
        extension_path,
        implementation_doc,
        base_manifest_path,
        base_audit_path,
        support_manifest_path,
        support_gate_path,
        support_audit_path,
        provider_gate_path,
        cohort_gate_path,
        extension_gate_path,
    ):
        if not path.is_file():
            raise FileNotFoundError(path)
    extension = require_status(
        extension_path, "FROZEN_ESTIMATE_BLIND_PASS"
    )
    require_status(base_manifest_path)
    require_status(base_audit_path)
    require_status(support_manifest_path)
    support_gate = require_status(support_gate_path)
    require_status(support_audit_path)
    require_status(provider_gate_path)
    require_status(cohort_gate_path)
    extension_gate = require_status(extension_gate_path)
    if (
        not support_gate.get("outcome_specific_matrix_authorized")
        or support_gate.get("result_interpretation_authorized") is not False
        or not extension_gate.get("estimation_authorized")
    ):
        raise RuntimeError("Directional matrix construction is not authorized.")

    result_root = phase2 / "results" / "directional_dyads"
    preexisting_adjusted_results = [
        path
        for path in result_root.rglob("*")
        if path.is_file()
        and "support" not in path.parts
        and path.suffix.lower() in {".csv", ".parquet", ".json"}
    ]
    if preexisting_adjusted_results:
        raise RuntimeError(
            "Directional adjusted results already exist before implementation "
            f"freeze: {preexisting_adjusted_results}"
        )

    scripts = [
        phase2 / "scripts" / name
        for name in (
            "07_prepare_primary_model_matrix.py",
            "08_estimate_primary_models.py",
            "09_validate_hdfe_engine.py",
            "16_apply_multiple_testing.py",
            "23_race_proxy_multiple_imputation.py",
            "30e_checkpoint_primary_matrix_audit.py",
            "35_build_directional_dyad_base.py",
            "35b_independent_directional_dyad_base_audit.py",
            "37_build_directional_cell_support.py",
            "37b_independent_directional_cell_support_audit.py",
            "38_freeze_directional_model_implementation.py",
        )
    ]
    for path in scripts:
        if not path.is_file():
            raise FileNotFoundError(path)

    payload = {
        "status": "FROZEN_ESTIMATE_BLIND_PASS",
        "implementation_version": (
            "directional_dyad_model_implementation_v1_20260726"
        ),
        "frozen_utc": utc_now(),
        "coefficient_or_outcome_estimates_read_by_freeze_script": False,
        "preexisting_directional_adjusted_result_files": 0,
        "postfreeze_schema_compatibility_correction": {
            "script": "scripts/16_apply_multiple_testing.py",
            "scope": (
                "Accept the already-audited historical AMI field name "
                "cohort_definition as a schema alias for definition when "
                "constructing its unchanged BH multiplicity-family label."
            ),
            "scientific_specification_changed": False,
            "sample_outcome_estimator_contrast_or_multiplicity_changed": False,
            "timing": (
                "Detected by static header review while the non-directional "
                "common-primary race M2 computation was still running and "
                "before any real directional result file existed."
            ),
            "result_values_read_to_make_correction": False,
        },
        "parent_extension": file_record(phase2, extension_path),
        "implementation_document": file_record(
            phase2, implementation_doc
        ),
        "bindings": {
            "directional_base_manifest": file_record(
                phase2, base_manifest_path
            ),
            "directional_base_independent_audit": file_record(
                phase2, base_audit_path
            ),
            "directional_support_manifest": file_record(
                phase2, support_manifest_path
            ),
            "directional_support_gate": file_record(
                phase2, support_gate_path
            ),
            "directional_support_independent_audit": file_record(
                phase2, support_audit_path
            ),
            "provider_measurement_gate": file_record(
                phase2, provider_gate_path
            ),
            "cohort_validation_gate": file_record(
                phase2, cohort_gate_path
            ),
            "directional_extension_gate": file_record(
                phase2, extension_gate_path
            ),
        },
        "cell_encodings": {
            "gender": (
                "Four mutually exclusive recorded physician-gender by "
                "recorded patient-sex indicators."
            ),
            "race": (
                "X[r,p] = posterior_physician_race[r] * "
                "I(recorded_patient_group=p); 25 columns sum to one."
            ),
            "intersectional": (
                "X[r,g,p,s] = posterior_physician_race[r] * "
                "I(recorded_physician_gender=g) * "
                "I(recorded_patient_group=p) * "
                "I(recorded_patient_sex=s); 100 columns sum to one."
            ),
            "primary_race_prior": (
                "AAMC 2020 Florida active-physician five-class prior"
            ),
            "hard_and_prior_sensitivities": extension[
                "measurement_definitions"
            ]["physician_race_sensitivities"],
            "multiple_imputation": (
                "20 draws at NPI level; one race draw per NPI per "
                "imputation, fixed across all visits."
            ),
        },
        "outcomes": extension["outcome_families"],
        "outcome_sample_rule": (
            "Complete outcome-specific eligible sample; no outcome imputation."
        ),
        "model_sequence": extension["model_sequence"],
        "covariate_contract": {
            "age": [
                "age",
                "positive_part(age-18)",
                "positive_part(age-45)",
                "positive_part(age-65)",
                "positive_part(age-80)",
                "age_missing",
            ],
            "patient_visit": [
                "payer categorical",
                "patient ZIP rurality categorical",
                "weekend and missing",
                "off-hours and missing",
                "arrival-time band categorical",
            ],
            "risk": [
                "all validated Elixhauser flags",
                "Elixhauser condition count",
            ],
            "physician": [
                "ED specialist and missing",
                "experience",
                "positive_part(experience-10)",
                "positive_part(experience-20)",
                "positive_part(experience-30)",
                "experience missing",
                "log1p physician-quarter ED volume",
                "physician-quarter volume missing",
            ],
            "family_specific": {
                "race": "recorded patient sex covariates",
                "gender": "compatible recorded patient race/ethnicity covariates",
                "intersectional": (
                    "no duplicate patient race or sex main-effect covariates "
                    "outside the saturated 100-cell basis"
                ),
            },
        },
        "fixed_effects": {
            "M2_DIRECTIONAL": [
                "facility_by_year_quarter",
                "principal_clinical_category",
            ],
            "M3_WITHIN_PHYSICIAN": [
                "attending_npi",
                "facility_by_year_quarter",
                "principal_clinical_category",
            ],
        },
        "inference": {
            "primary_covariance": (
                "Two-way CRV1 by attending NPI and facility"
            ),
            "bootstrap": (
                "Facility wild-score bootstrap, 9,999 draws, for frozen "
                "primary-outcome directional contrasts selected pre-fit."
            ),
            "confidence_level": 0.95,
            "nonfinite_policy": "Fail closed and mark NON_ESTIMABLE.",
        },
        "adjusted_prediction": {
            "M2_formula": (
                "mean(y) + (target_cell - mean_observed_cell_composition)'beta"
            ),
            "variance": (
                "(target_cell - mean_observed_cell_composition)' V "
                "(target_cell - mean_observed_cell_composition)"
            ),
            "reason": (
                "The saturated cell basis sums to one and its common level is "
                "absorbed by fixed effects; the anchored formula is invariant "
                "to the arbitrary absorbed coefficient level."
            ),
            "M3_policy": (
                "Report only identified within-physician simple effects and "
                "interaction differences, not absolute physician-group cells."
            ),
        },
        "support_and_estimability": extension[
            "support_and_estimability"
        ],
        "multiplicity": extension["multiplicity"],
        "storage_and_restart": {
            "matrix_scope": (
                "Outcome-specific, or grouped only for exactly identical "
                "availability masks."
            ),
            "estimation_precision": "float64",
            "lower_precision_policy": (
                "Prohibited unless independently benchmarked and logged before "
                "use; never used for final cross-products/covariance."
            ),
            "writes": "Atomic, restartable, hash-bound.",
            "compaction": (
                "Only after independent matrix/result checkpoint passes."
            ),
        },
        "required_preinterpretation_audits": [
            "directional definition unit tests",
            "outcome-specific matrix/hash/support/rank audit",
            "numerical and convergence audit",
            "selected covariance and contrast audit",
            "multiplicity audit",
            "gender directional results audit",
            "race directional results audit",
            "intersectional directional results audit",
        ],
        "code_inventory": [file_record(phase2, path) for path in scripts],
        "language_rule": extension["language_rule"],
        "fail_closed_rule": extension["fail_closed_rule"],
        "source_release_modified": False,
        "phase2_cohort_modified": False,
    }
    frozen_path = (
        phase2
        / "documentation"
        / "Directional_Dyad_Model_Implementation_FROZEN.json"
    )
    atomic_json(frozen_path, payload)
    gate = {
        "status": "PASS",
        "created_utc": utc_now(),
        "implementation_manifest": file_record(phase2, frozen_path),
        "estimate_blind": True,
        "outcome_specific_matrix_construction_authorized": True,
        "model_estimate_interpretation_authorized": False,
        "reason": (
            "Matrices may be built and models may run under the frozen "
            "contract, but estimates remain unreadable until independent "
            "result-family audits pass."
        ),
        "source_release_modified": False,
        "phase2_cohort_modified": False,
    }
    gate_path = (
        phase2 / "qa" / "directional_model_implementation_pre_estimation_gate.json"
    )
    atomic_json(gate_path, gate)
    print(
        json.dumps(
            {
                "status": "PASS",
                "implementation_manifest": str(frozen_path),
                "implementation_sha256": sha256(frozen_path),
                "matrix_construction_authorized": True,
                "result_interpretation_authorized": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
