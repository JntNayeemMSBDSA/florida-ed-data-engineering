#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/34_freeze_directional_dyad_extension.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Audit and freeze the post-descriptive directional-dyad SAP extension.

This script is deliberately estimate-blind.  It inspects file inventories,
schemas, manifests, hashes, and timestamps, but never reads or prints a model
coefficient.  It fails closed when a required Phase 2 field or binding is
missing.  The immutable Phase 1 encounter release is read only.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pyarrow.parquet as pq


YEARS = tuple(range(2010, 2025))
QUARTERS = (1, 2, 3, 4)
PHYSICIAN_RACES = (
    "White",
    "Black",
    "Hispanic",
    "Asian",
    "Other/multiracial",
)
PATIENT_RACES = (
    "White",
    "Black",
    "Hispanic",
    "Asian",
    "Other/multiracial",
)
GENDERS = ("Male", "Female")

REQUEST_CHECKPOINT_NAME = (
    "Directional_Dyad_Extension_Request_Checkpoint_20260726T195543Z.json"
)
EXTENSION_VERSION = "directional_dyad_extension_v1_20260726"

CORE_REQUIRED_FIELDS = {
    "visit_year",
    "visit_quarter",
    "visit_key",
    "facility_ahca_id",
    "facility_year_quarter_id",
    "principal_clinical_category",
    "patient_sex_category",
    "patient_race_category",
    "patient_ethnicity_category",
    "age_years",
    "payer_group",
    "patient_zip_rurality_3level",
    "weekend_flag",
    "off_hours_flag",
    "arrival_time_band",
    "attending_selected_npi",
    "physician_linkage_method",
    "attending_ed_specialist_flag",
    "attending_years_since_medical_school",
    "attending_quarter_volume_all_ed",
    "physician_gender_category",
    "physician_gender_source",
    "physician_race_proxy_primary_label",
    "physician_race_proxy_prob_white",
    "physician_race_proxy_prob_black",
    "physician_race_proxy_prob_hispanic",
    "physician_race_proxy_prob_asian",
    "physician_race_proxy_prob_other",
    "physician_race_population_prob_white",
    "physician_race_population_prob_black",
    "physician_race_population_prob_hispanic",
    "physician_race_population_prob_asian",
    "physician_race_population_prob_other",
    "physician_race_imputation_confidence",
    "provider_measurement_version",
    "physician_md_do_flag",
    "los_hours_primary_0_168",
    "length_of_stay_days",
    "total_charge_reported",
    "total_charge_reported_real_2024",
    "total_charge_real_2024",
    "component_charge_sum_real_2024",
    "procedure_count_analysis",
    "any_procedure_flag",
    "high_procedure_flag",
    "routine_discharge_flag",
    "transfer_flag",
    "hospice_flag",
    "mortality_flag",
    "left_discontinued_care_flag",
    "em_acuity_proxy_level",
    "em_critical_care_flag",
}

RISK_REQUIRED_FIELDS = {
    "visit_key",
}

CHARGE_REQUIRED_FIELDS = {
    "visit_key",
    "pharmchgs_real_2024",
    "medchgs_real_2024",
    "labchgs_real_2024",
    "radchgs_real_2024",
    "cardiochgs_real_2024",
    "oprmchgs_real_2024",
    "aneschgs_real_2024",
    "recovchgs_real_2024",
    "erchgs_real_2024",
    "traumachgs_real_2024",
    "obserchgs_real_2024",
    "gastrochgs_real_2024",
    "lithochgs_real_2024",
    "othchgs_real_2024",
}

PRIMARY_OUTCOMES = (
    "los_hours_primary_0_168",
    "total_charge_reported_real_2024",
)
RESOURCE_OUTCOMES = (
    "procedure_count_analysis",
    "any_procedure_flag",
    "high_procedure_flag",
    "em_acuity_proxy_level",
    "em_critical_care_flag",
)
DISPOSITION_OUTCOMES = (
    "routine_discharge_flag",
    "transfer_flag",
    "hospice_flag",
    "mortality_flag",
    "left_discontinued_care_flag",
)
CHARGE_COMPONENT_OUTCOMES = tuple(
    sorted(CHARGE_REQUIRED_FIELDS - {"visit_key"})
)
DISCRETION_OUTCOMES = (
    "higher_discretion_procedure_count",
    "lower_discretion_procedure_count",
    "ambiguous_discretion_procedure_count",
    "any_higher_discretion_candidate_flag",
    "any_lower_discretion_candidate_flag",
    "higher_minus_lower_discretion_procedure_count",
    "any_higher_minus_any_lower_discretion_candidate",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def atomic_json(path: Path, payload: Any) -> None:
    atomic_text(
        path,
        json.dumps(payload, indent=2, sort_keys=False, default=str) + "\n",
    )


def rel(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def evidence(path: Path, root: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": rel(path, root),
        "bytes": stat.st_size,
        "modified_utc": datetime.fromtimestamp(
            stat.st_mtime, timezone.utc
        ).isoformat(),
        "sha256": sha256(path),
    }


def parquet_fields(path: Path) -> set[str]:
    return set(pq.ParquetFile(path).schema_arrow.names)


def pair_cell(physician: str, patient: str) -> dict[str, str]:
    return {
        "cell_id": f"physician={physician}|patient={patient}",
        "physician_group": physician,
        "patient_group": patient,
    }


def intersectional_cell(
    physician_race: str,
    physician_gender: str,
    patient_race: str,
    patient_sex: str,
) -> dict[str, str]:
    return {
        "cell_id": (
            f"physician_race={physician_race}|"
            f"physician_gender={physician_gender}|"
            f"patient_race={patient_race}|patient_sex={patient_sex}"
        ),
        "physician_race": physician_race,
        "physician_gender": physician_gender,
        "patient_race": patient_race,
        "patient_sex": patient_sex,
    }


def contrast(
    contrast_id: str,
    family: str,
    positive: str,
    negative: str,
    estimand: str,
) -> dict[str, Any]:
    return {
        "contrast_id": contrast_id,
        "contrast_family": family,
        "linear_combination": [
            {"cell_id": positive, "weight": 1.0},
            {"cell_id": negative, "weight": -1.0},
        ],
        "direction": f"{positive} minus {negative}",
        "estimand": estimand,
    }


def build_gender_plan() -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    cells = [
        pair_cell(physician, patient)
        for physician in GENDERS
        for patient in GENDERS
    ]
    cell_ids = [item["cell_id"] for item in cells]
    contrasts: list[dict[str, Any]] = []
    for left, right in itertools.combinations(cell_ids, 2):
        contrasts.append(
            contrast(
                f"gender_pair_{len(contrasts) + 1:02d}",
                "gender_all_six_pairwise",
                left,
                right,
                "Adjusted directional difference between two recorded "
                "physician-gender by recorded-patient-sex cells.",
            )
        )
    return cells, contrasts


def build_race_plan() -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    cells = [
        pair_cell(physician, patient)
        for physician in PHYSICIAN_RACES
        for patient in PATIENT_RACES
    ]
    reference = pair_cell("White", "White")["cell_id"]
    contrasts: list[dict[str, Any]] = []

    for item in cells:
        if item["cell_id"] != reference:
            contrasts.append(
                contrast(
                    f"race_vs_reference_{len(contrasts) + 1:02d}",
                    "race_cell_vs_white_white",
                    item["cell_id"],
                    reference,
                    "Adjusted dyad-cell difference versus White-physician "
                    "proxy and recorded non-Hispanic White patient.",
                )
            )

    for patient in PATIENT_RACES:
        white_physician = pair_cell("White", patient)["cell_id"]
        for physician in PHYSICIAN_RACES[1:]:
            contrasts.append(
                contrast(
                    f"race_within_patient_{physician}_{patient}",
                    "race_physician_simple_effect_within_patient",
                    pair_cell(physician, patient)["cell_id"],
                    white_physician,
                    "Adjusted physician-proxy-group difference holding "
                    "recorded patient race/ethnicity fixed.",
                )
            )

    for physician in PHYSICIAN_RACES:
        white_patient = pair_cell(physician, "White")["cell_id"]
        for patient in PATIENT_RACES[1:]:
            contrasts.append(
                contrast(
                    f"race_within_physician_{physician}_{patient}",
                    "race_patient_simple_effect_within_physician",
                    pair_cell(physician, patient)["cell_id"],
                    white_patient,
                    "Adjusted recorded-patient-group difference holding "
                    "physician proxy group fixed.",
                )
            )

    for race in PHYSICIAN_RACES[1:]:
        contrasts.append(
            {
                "contrast_id": f"race_interaction_did_{race}_vs_White",
                "contrast_family": "race_white_referent_interaction_did",
                "linear_combination": [
                    {
                        "cell_id": pair_cell(race, race)["cell_id"],
                        "weight": 1.0,
                    },
                    {
                        "cell_id": pair_cell(race, "White")["cell_id"],
                        "weight": -1.0,
                    },
                    {
                        "cell_id": pair_cell("White", race)["cell_id"],
                        "weight": -1.0,
                    },
                    {"cell_id": reference, "weight": 1.0},
                ],
                "direction": (
                    f"({race} physician-proxy: {race} minus White patient) "
                    f"minus (White physician-proxy: {race} minus White patient)"
                ),
                "estimand": "White-referent directional interaction "
                "difference-in-differences; not a causal effect.",
            }
        )
    return cells, contrasts


def build_intersectional_plan() -> tuple[
    list[dict[str, str]], list[dict[str, Any]]
]:
    cells = [
        intersectional_cell(pr, pg, rr, ps)
        for pr in PHYSICIAN_RACES
        for pg in GENDERS
        for rr in PATIENT_RACES
        for ps in GENDERS
    ]
    lookup = {
        (
            item["physician_race"],
            item["physician_gender"],
            item["patient_race"],
            item["patient_sex"],
        ): item["cell_id"]
        for item in cells
    }
    reference = lookup[("White", "Male", "White", "Male")]
    contrasts: list[dict[str, Any]] = []

    for item in cells:
        if item["cell_id"] != reference:
            contrasts.append(
                contrast(
                    f"intersectional_vs_reference_{len(contrasts) + 1:03d}",
                    "intersectional_cell_vs_reference",
                    item["cell_id"],
                    reference,
                    "Adjusted intersectional cell difference versus White "
                    "male physician-proxy and recorded non-Hispanic White "
                    "male patient.",
                )
            )

    for pr in PHYSICIAN_RACES:
        for rr in PATIENT_RACES:
            for ps in GENDERS:
                contrasts.append(
                    contrast(
                        f"physician_gender_within_{pr}_{rr}_{ps}",
                        "intersectional_physician_gender_simple_effect",
                        lookup[(pr, "Female", rr, ps)],
                        lookup[(pr, "Male", rr, ps)],
                        "Recorded female-minus-male physician-gender "
                        "difference within physician race-proxy and patient "
                        "race/ethnicity-plus-sex.",
                    )
                )

    for pr in PHYSICIAN_RACES:
        for pg in GENDERS:
            for rr in PATIENT_RACES:
                contrasts.append(
                    contrast(
                        f"patient_sex_within_{pr}_{pg}_{rr}",
                        "intersectional_patient_sex_simple_effect",
                        lookup[(pr, pg, rr, "Female")],
                        lookup[(pr, pg, rr, "Male")],
                        "Recorded female-minus-male patient-sex difference "
                        "within physician race-proxy-plus-gender and patient "
                        "race/ethnicity.",
                    )
                )

    for pg in GENDERS:
        for rr in PATIENT_RACES:
            for ps in GENDERS:
                for pr in PHYSICIAN_RACES[1:]:
                    contrasts.append(
                        contrast(
                            f"physician_race_{pr}_within_{pg}_{rr}_{ps}",
                            "intersectional_physician_race_simple_effect",
                            lookup[(pr, pg, rr, ps)],
                            lookup[("White", pg, rr, ps)],
                            "Physician race-proxy difference versus White "
                            "holding physician gender and recorded patient "
                            "race/ethnicity-plus-sex fixed.",
                        )
                    )

    for pr in PHYSICIAN_RACES:
        for pg in GENDERS:
            for ps in GENDERS:
                for rr in PATIENT_RACES[1:]:
                    contrasts.append(
                        contrast(
                            f"patient_race_{rr}_within_{pr}_{pg}_{ps}",
                            "intersectional_patient_race_simple_effect",
                            lookup[(pr, pg, rr, ps)],
                            lookup[(pr, pg, "White", ps)],
                            "Recorded patient race/ethnicity difference versus "
                            "non-Hispanic White holding physician "
                            "race-proxy-plus-gender and patient sex fixed.",
                        )
                    )
    return cells, contrasts


def validate_partitions(
    phase2: Path,
) -> tuple[list[dict[str, Any]], set[str], set[str], set[str]]:
    root = (
        phase2
        / "analysis_data"
        / "concordance_visit_data_provider_v2"
    )
    partition_audit: list[dict[str, Any]] = []
    common_core: set[str] | None = None
    common_risk: set[str] | None = None
    common_charge: set[str] | None = None

    for year in YEARS:
        for quarter in QUARTERS:
            part = root / f"visit_year={year}" / f"visit_quarter={quarter}"
            success = part / "_SUCCESS.json"
            core = part / "concordance_visit_core.parquet"
            risk = part / "concordance_elixhauser_flags.parquet"
            charge = part / "concordance_charge_components.parquet"
            for path in (success, core, risk, charge):
                if not path.is_file():
                    raise RuntimeError(f"Missing required partition file: {path}")

            manifest = json.loads(success.read_text(encoding="utf-8"))
            if manifest.get("build_spec_version") != (
                "provider_v2_cms_current_cohort_v1"
            ):
                raise RuntimeError(f"Unexpected cohort build spec: {success}")
            if not manifest.get("reconciliation_passed"):
                raise RuntimeError(f"Partition not reconciled: {success}")
            if manifest.get("source_release_modified") is not False:
                raise RuntimeError(f"Phase 1 mutation invariant failed: {success}")

            file_map = {
                item["name"]: item for item in manifest.get("files", [])
            }
            for path in (core, risk, charge):
                item = file_map.get(path.name)
                if item is None:
                    raise RuntimeError(
                        f"Manifest omits {path.name}: {success}"
                    )
                if int(item["bytes"]) != path.stat().st_size:
                    raise RuntimeError(f"Size mismatch: {path}")
                if item["sha256"] != sha256(path):
                    raise RuntimeError(f"Hash mismatch: {path}")

            core_fields = parquet_fields(core)
            risk_fields = parquet_fields(risk)
            charge_fields = parquet_fields(charge)
            missing_core = sorted(CORE_REQUIRED_FIELDS - core_fields)
            missing_risk = sorted(RISK_REQUIRED_FIELDS - risk_fields)
            missing_charge = sorted(CHARGE_REQUIRED_FIELDS - charge_fields)
            elixhauser_flag_count = sum(
                name.startswith("elix_") and name.endswith("_flag")
                for name in risk_fields
            )
            if (
                missing_core
                or missing_risk
                or missing_charge
                or elixhauser_flag_count < 20
            ):
                raise RuntimeError(
                    f"Required fields absent in {year} Q{quarter}: "
                    f"core={missing_core}; risk={missing_risk}; "
                    f"charge={missing_charge}; "
                    f"elixhauser_flag_count={elixhauser_flag_count}"
                )

            common_core = (
                core_fields
                if common_core is None
                else common_core & core_fields
            )
            common_risk = (
                risk_fields
                if common_risk is None
                else common_risk & risk_fields
            )
            common_charge = (
                charge_fields
                if common_charge is None
                else common_charge & charge_fields
            )
            partition_audit.append(
                {
                    "visit_year": year,
                    "visit_quarter": quarter,
                    "cohort_rows": int(manifest["cohort_rows"]),
                    "manifest_sha256": sha256(success),
                    "core_sha256": file_map[core.name]["sha256"],
                    "risk_sha256": file_map[risk.name]["sha256"],
                    "charge_sha256": file_map[charge.name]["sha256"],
                    "provider_master_sha256": manifest[
                        "provider_master_sha256"
                    ],
                    "provider_race_proxy_sha256": manifest[
                        "provider_race_proxy_sha256"
                    ],
                    "status": "PASS",
                }
            )

    provider_hashes = {
        item["provider_master_sha256"] for item in partition_audit
    }
    race_hashes = {
        item["provider_race_proxy_sha256"] for item in partition_audit
    }
    if len(provider_hashes) != 1 or len(race_hashes) != 1:
        raise RuntimeError("Provider measurement hashes vary across partitions")
    return (
        partition_audit,
        common_core or set(),
        common_risk or set(),
        common_charge or set(),
    )


def append_deviation_log(phase2: Path, frozen_utc: str) -> None:
    path = phase2 / "documentation" / "SAP_deviation_log.csv"
    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    if not fieldnames:
        raise RuntimeError(f"Deviation log has no header: {path}")
    if any(row.get("deviation_id") == "DEV-012" for row in rows):
        return

    template = {name: "" for name in fieldnames}
    values = {
        "deviation_id": "DEV-012",
        "date_utc": frozen_utc,
        "analysis_stage": (
            "post-primary-period descriptive/unadjusted generation; "
            "pre-adjusted-primary-period matrix and estimation"
        ),
        "planned_specification": (
            "The original SAP prespecified binary Black/White and binary "
            "sex/gender four-cell interactions plus a conditional exploratory "
            "binary intersectional analysis; it did not prespecify the full "
            "five-class or 100-cell directional extension."
        ),
        "implemented_change": (
            "Added directional gender, five-class race, and expanded "
            "intersectional dyad analysis families after primary-period "
            "descriptive/unadjusted outputs existed but before adjusted "
            "primary-period model matrices or estimates existed. Retain all "
            "cells; use joint factorial models, adjusted predictions or "
            "marginal contrasts, probability-weighted physician race, "
            "physician-level multiple imputation, hard-threshold/prior "
            "sensitivities, support gates, and separate BH families."
        ),
        "reason": (
            "Investigator-requested directional characterization that retains "
            "all estimable physician-by-patient cells and probability-aware "
            "physician race measurement. Pre-existing binary components retain "
            "their original status; new non-intersectional directional work "
            "is secondary and expanded intersectional work exploratory."
        ),
        "anticipated_direction": (
            "Unknown. Relevant primary-period descriptive/unadjusted and "
            "historical outputs existed before this request, so the extension "
            "is not labelled wholly prespecified. No coefficient, confidence "
            "interval, or p-value was read by the freeze script when cells, "
            "contrasts, support thresholds, models, and multiplicity families "
            "were frozen."
        ),
        "status": (
            "accepted_post_descriptive_pre_adjusted_primary_results_extension"
        ),
    }
    for key, value in values.items():
        if key in template:
            template[key] = value
    rows.append(template)
    temporary = path.with_suffix(".csv.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    args = parser.parse_args()
    phase2 = args.phase2.resolve()
    frozen_utc = utc_now()

    request_path = (
        phase2 / "documentation" / REQUEST_CHECKPOINT_NAME
    )
    measurement_gate = phase2 / "qa" / "pre_estimation_measurement_gate.json"
    cohort_gate = phase2 / "qa" / "cohort_validation_report.json"
    historical_gate = (
        phase2 / "qa" / "historical_provider_v2_pre_estimation_gate.json"
    )
    sap = phase2 / "documentation" / "Statistical_Analysis_Plan.md"
    implementation = (
        phase2
        / "documentation"
        / "Primary_Model_Implementation_Specification.md"
    )
    source_registry = phase2 / "external_sources" / "source_registry.csv"
    cohort_build_manifest = (
        phase2 / "analysis_data" / "cohort_build_manifest.json"
    )
    provider_master = (
        phase2 / "analysis_data" / "dimensions" / "provider_master_v2.parquet"
    )
    race_proxy = (
        phase2
        / "analysis_data"
        / "dimensions"
        / "provider_race_proxy_v2.parquet"
    )
    script_assessments = {
        "06_descriptive_analysis.py": (
            "Contains primary-period descriptive and unadjusted binary "
            "Black/White race and binary sex/gender four-cell summaries. "
            "These predate this extension and are preserved."
        ),
        "07_prepare_primary_model_matrix.py": (
            "Builds validated binary Black/White race and binary "
            "sex/gender matrices, including Black-probability sensitivities "
            "and a 16-cell binary intersectional design. It does not contain "
            "the requested five-class directional or 100-cell expanded "
            "intersectional design."
        ),
        "08_estimate_primary_models.py": (
            "Implements the frozen HDFE/CRV1 estimation engine and selected "
            "covariance blocks. It can be reused, but new target matrices and "
            "contrast extraction are required."
        ),
        "16_apply_multiple_testing.py": (
            "Protects the original two-outcome Holm confirmatory family. New "
            "secondary/exploratory directional BH families must be added "
            "without changing that family."
        ),
        "17_historical_sensitivity_analysis.py": (
            "Historical race analysis is binary Black/White and remains a "
            "separate sensitivity. Expanded historical directional analyses "
            "require separate compatible-variable matrices."
        ),
        "17b_historical_sex_gender_sensitivity.py": (
            "Historical binary sex/gender analysis is separate and reusable "
            "for the four gender cells."
        ),
        "18_race_threshold_probability_sensitivities.py": (
            "Implements Black/White probability and threshold sensitivity "
            "logic only; it does not satisfy the five-class directional "
            "request."
        ),
        "21_intersectional_analysis.py": (
            "Implements an exploratory binary-race 16-cell descriptive table "
            "and a single four-way coefficient. It does not provide the "
            "requested 100 directional cells, adjusted predictions, planned "
            "contrasts, or complete cell estimability diagnostics."
        ),
        "23_race_proxy_multiple_imputation.py": (
            "Implements physician-level multiple imputation for the existing "
            "binary race contrast. Its NPI-level draw and Rubin-pooling "
            "principles should be reused for five-class directional models."
        ),
        "30_independent_primary_results_audit.py": (
            "Existing independent primary audit is preserved; the extension "
            "requires an additional fail-closed independent auditor."
        ),
        "31_independent_historical_results_audit.py": (
            "Existing historical audit is preserved; any new historical "
            "directional result requires a separate extension binding."
        ),
    }
    script_paths = {
        name: phase2 / "scripts" / name for name in script_assessments
    }
    required_evidence = (
        request_path,
        measurement_gate,
        cohort_gate,
        historical_gate,
        sap,
        implementation,
        source_registry,
        cohort_build_manifest,
        provider_master,
        race_proxy,
        *script_paths.values(),
    )
    for path in required_evidence:
        if not path.is_file():
            raise RuntimeError(f"Required evidence missing: {path}")

    request = json.loads(request_path.read_text(encoding="utf-8"))
    if request.get("checkpoint_status") != (
        "QUEUED_PENDING_FULL_AUDIT_AND_FREEZE"
    ):
        raise RuntimeError("Unexpected request-checkpoint status")
    for gate_path in (measurement_gate, cohort_gate, historical_gate):
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        status = gate.get("status", gate.get("overall_status"))
        if status != "PASS":
            raise RuntimeError(f"Gate is not PASS: {gate_path}")

    (
        partition_audit,
        common_core,
        common_risk,
        common_charge,
    ) = validate_partitions(phase2)
    if len(partition_audit) != 60:
        raise RuntimeError("Expected exactly 60 primary-period partitions")

    provider_hash = sha256(provider_master)
    race_hash = sha256(race_proxy)
    if {item["provider_master_sha256"] for item in partition_audit} != {
        provider_hash
    }:
        raise RuntimeError("Live provider master is not partition-bound")
    if {item["provider_race_proxy_sha256"] for item in partition_audit} != {
        race_hash
    }:
        raise RuntimeError("Live race proxy is not partition-bound")

    result_root = phase2 / "results"
    existing_results = [
        evidence(path, phase2)
        for path in sorted(result_root.rglob("*"))
        if path.is_file()
    ]
    adjusted_primary_markers = (
        "primary_model_coefficients",
        "primary_results_manifest",
        "outcome_specific_primary",
        "common_primary_results",
    )
    adjusted_primary_results = [
        item
        for item in existing_results
        if any(
            marker in item["path"].lower()
            for marker in adjusted_primary_markers
        )
    ]
    matrix_manifests = list(
        (phase2 / "analysis_data").rglob("matrix_manifest.json")
    )
    if adjusted_primary_results or matrix_manifests:
        raise RuntimeError(
            "Adjusted primary-period results or matrices existed at freeze; "
            "manual timing-classification review is required."
        )

    gender_cells, gender_contrasts = build_gender_plan()
    race_cells, race_contrasts = build_race_plan()
    intersectional_cells, intersectional_contrasts = (
        build_intersectional_plan()
    )
    if (len(gender_cells), len(gender_contrasts)) != (4, 6):
        raise RuntimeError("Gender plan cardinality error")
    if (len(race_cells), len(race_contrasts)) != (25, 68):
        raise RuntimeError("Race plan cardinality error")
    if (
        len(intersectional_cells),
        len(intersectional_contrasts),
    ) != (100, 359):
        raise RuntimeError("Intersectional plan cardinality error")

    patient_mapping = {
        "Hispanic": (
            "patient_ethnicity_category == 'Hispanic or Latino', regardless "
            "of recorded race"
        ),
        "White": (
            "patient_ethnicity_category == 'Not Hispanic or Latino' AND "
            "patient_race_category == 'White'"
        ),
        "Black": (
            "patient_ethnicity_category == 'Not Hispanic or Latino' AND "
            "patient_race_category == 'Black or African American'"
        ),
        "Asian": (
            "patient_ethnicity_category == 'Not Hispanic or Latino' AND "
            "patient_race_category == 'Asian'"
        ),
        "Other/multiracial": (
            "patient_ethnicity_category == 'Not Hispanic or Latino' AND "
            "patient_race_category IN ('American Indian or Alaska Native', "
            "'Native Hawaiian or Other Pacific Islander', 'Other')"
        ),
        "excluded": (
            "Unknown patient ethnicity; Unknown patient race; or any category "
            "that cannot be assigned without overriding the recorded fields"
        ),
    }

    support = {
        "primary_2010_2024": {
            "minimum_visits_or_probability_weighted_effective_visits": 1000,
            "minimum_unique_physicians_or_kish_effective_physicians": 30,
            "minimum_facilities": 20,
            "minimum_physician_clusters": 30,
            "minimum_facility_clusters": 20,
            "limited_support_flag": (
                "visits/effective visits < 5000 OR physicians/effective "
                "physicians < 50 OR facilities < 30"
            ),
        },
        "historical_2005_2008": {
            "minimum_visits_or_probability_weighted_effective_visits": 250,
            "minimum_unique_physicians_or_kish_effective_physicians": 20,
            "minimum_facilities": 15,
            "minimum_physician_clusters": 20,
            "minimum_facility_clusters": 15,
            "limited_support_flag": (
                "visits/effective visits < 1000 OR physicians/effective "
                "physicians < 30 OR facilities < 20"
            ),
        },
        "contrast_rule": (
            "Every nonzero-weight cell must meet its period threshold; the "
            "contrast vector must be identified, its variance finite and "
            "nonnegative, and both clustering dimensions must meet the "
            "threshold. Otherwise mark NON_ESTIMABLE and retain the cell."
        ),
        "sparse_group_rule": (
            "Never merge a sparse race, ethnicity, sex, or gender cell. "
            "Report counts and mark LIMITED_SUPPORT or NON_ESTIMABLE."
        ),
    }

    model_sequence = [
        {
            "model_id": "U0",
            "description": (
                "Unadjusted saturated directional cell means and frozen "
                "linear contrasts on each outcome-specific eligible sample."
            ),
            "fixed_effects": [],
            "covariates": [],
            "inference": (
                "Two-way CRV1 by attending NPI and facility when support "
                "permits; raw cell summaries are always retained."
            ),
        },
        {
            "model_id": "M2_DIRECTIONAL",
            "description": (
                "Joint factorial linear model or linear probability model "
                "with standardized adjusted cell predictions and marginal "
                "linear contrasts."
            ),
            "fixed_effects": [
                "facility_by_year_quarter",
                "principal_clinical_category",
            ],
            "covariates": [
                "age spline and missing flag",
                "payer group",
                "patient ZIP rurality",
                "weekend/off-hours/arrival-time band",
                "Elixhauser indicators and count",
                "physician ED-specialist status",
                "physician-experience spline and missing flag",
                "log physician-quarter ED volume and missing flag",
                "recorded patient sex in non-intersectional race models",
                "compatible recorded patient race/ethnicity in gender models",
            ],
            "inference": (
                "Two-way physician/facility CRV1; facility wild-score "
                "bootstrap sensitivity for frozen primary-outcome directional "
                "contrasts selected before fitting."
            ),
        },
        {
            "model_id": "M3_WITHIN_PHYSICIAN",
            "description": (
                "Within-physician sensitivity with physician, "
                "facility-by-year-quarter, and principal-clinical-category "
                "fixed effects. Time-invariant physician-group main effects "
                "are absorbed; report only identified within-physician patient "
                "simple effects and interaction differences."
            ),
            "fixed_effects": [
                "attending_npi",
                "facility_by_year_quarter",
                "principal_clinical_category",
            ],
            "covariates": "same baseline covariates as M2_DIRECTIONAL",
            "inference": "Two-way physician/facility CRV1",
        },
    ]

    multiplicity = {
        "method": "Benjamini-Hochberg false-discovery-rate adjustment",
        "confirmatory_family_unchanged": (
            "The original confirmatory family remains exactly the two frozen "
            "Black/White M2 interaction contrasts for outcome-specific LOS "
            "and reported real-charge samples, with Holm adjustment. No new "
            "directional contrast is added to or relabelled as confirmatory."
        ),
        "directional_families": [
            {
                "family_id": "gender_directional_primary_outcomes",
                "members": "6 planned contrasts x 2 frozen primary outcomes",
                "tier": "secondary extension except originally frozen "
                "four-cell interaction remains originally prespecified",
            },
            {
                "family_id": "race_directional_primary_outcomes",
                "members": "68 planned contrasts x 2 frozen primary outcomes",
                "tier": "secondary extension except originally frozen "
                "Black/White four-cell interaction remains originally "
                "prespecified",
            },
            {
                "family_id": "intersectional_directional_primary_outcomes",
                "members": (
                    "359 planned contrasts x 2 frozen primary outcomes"
                ),
                "tier": "exploratory extension",
            },
            {
                "family_id": "directional_resource_outcomes",
                "members": "separate by gender/race/intersectional family",
                "tier": "secondary for gender/race; exploratory "
                "intersectional",
            },
            {
                "family_id": "directional_disposition_outcomes",
                "members": "separate by gender/race/intersectional family",
                "tier": "secondary for gender/race; exploratory "
                "intersectional",
            },
            {
                "family_id": "directional_charge_components",
                "members": "separate by gender/race/intersectional family",
                "tier": "secondary for gender/race; exploratory "
                "intersectional",
            },
            {
                "family_id": "directional_discretion_outcomes",
                "members": "separate by gender/race/intersectional family",
                "tier": "exploratory pending clinician review",
            },
        ],
        "reporting": (
            "Every result row retains raw p-value, BH q-value, 95% "
            "confidence interval, family ID, tier, outcome sample, and "
            "estimability status. No finding is selected by q-value."
        ),
    }

    manifest = {
        "status": "FROZEN_ESTIMATE_BLIND_PASS",
        "extension_version": EXTENSION_VERSION,
        "frozen_utc": frozen_utc,
        "request_checkpoint": evidence(request_path, phase2),
        "timing_and_classification": {
            "extension_timing": (
                "post-primary-period-descriptive/unadjusted-results and "
                "post-some-historical-results; pre-adjusted-primary-period "
                "matrix and estimation"
            ),
            "adjusted_primary_period_result_files_at_freeze": 0,
            "adjusted_primary_period_matrix_manifests_at_freeze": 0,
            "coefficient_values_read_by_freeze_script": False,
            "classification": {
                "preexisting_binary_gender_four_cell_and_interaction": (
                    "originally prespecified"
                ),
                "preexisting_binary_black_white_four_cell_and_interaction": (
                    "originally prespecified"
                ),
                "new_gender_predictions_and_directional_contrasts": (
                    "secondary analysis-plan extension"
                ),
                "new_five_class_race_directional_family": (
                    "secondary analysis-plan extension"
                ),
                "preexisting_conditional_binary_intersectional_analysis": (
                    "originally prespecified exploratory"
                ),
                "new_expanded_intersectional_directional_family": (
                    "exploratory analysis-plan extension"
                ),
            },
        },
        "periods": {
            "primary": {
                "years": [2010, 2024],
                "partitions": 60,
                "role": "primary period",
            },
            "historical": {
                "years": [2005, 2008],
                "partitions": 16,
                "role": "separate historical replication/sensitivity only",
                "restrictions": (
                    "Use only outcomes/covariates marked comparable by the "
                    "historical comparability matrix. Never use or impute "
                    "hourly LOS. Never pool automatically with 2010-2024."
                ),
            },
            "ami_greenwood": (
                "Remains a separate ED-only extension and is not pooled into "
                "the directional dyad families."
            ),
        },
        "measurement_definitions": {
            "physician_race": (
                "Five-class Bayesian full-name wru v2.0.0 dictionary proxy "
                "without residential geography; algorithm-inferred, "
                "probabilistic, not self-reported and not BISG."
            ),
            "physician_race_primary_prior": (
                "AAMC 2020 Florida active-physician five-class prior."
            ),
            "physician_race_primary_directional_representation": (
                "Probability-weighted posterior-mixture factorial model plus "
                "20 physician-level multiple imputations drawn once per NPI "
                "and held fixed across that physician's visits."
            ),
            "physician_race_sensitivities": [
                "hard maximum-posterior classification at t50",
                "hard thresholds t70, t80, and t90",
                "wru 2020 national population prior probability model",
                "wru national-prior hard classifications",
                "physician-level multiple imputation under alternative prior",
            ],
            "patient_race_ethnicity_mapping": patient_mapping,
            "physician_gender": (
                "Recorded NPPES/CMS binary administrative category only for "
                "primary directional analyses; conflicts retained and "
                "flagged. SSA-inferred gender is sensitivity-only."
            ),
            "patient_sex": (
                "Recorded administrative Female/Male category; not gender "
                "identity. Unknown is retained in QA but ineligible for the "
                "binary directional model."
            ),
        },
        "analysis_families": {
            "gender_dyads": {
                "tier": "secondary extension with explicitly identified "
                "originally prespecified components",
                "cells": gender_cells,
                "contrasts": gender_contrasts,
                "reference_cell": pair_cell("Male", "Male")["cell_id"],
            },
            "race_dyads": {
                "tier": "secondary extension with explicitly identified "
                "originally prespecified Black/White components",
                "cells": race_cells,
                "contrasts": race_contrasts,
                "reference_cell": pair_cell("White", "White")["cell_id"],
            },
            "intersectional_dyads": {
                "tier": "exploratory extension",
                "cells": intersectional_cells,
                "contrasts": intersectional_contrasts,
                "reference_cell": intersectional_cell(
                    "White", "Male", "White", "Male"
                )["cell_id"],
            },
        },
        "outcome_families": {
            "frozen_primary_outcome_definitions_secondary_directional_use": (
                list(PRIMARY_OUTCOMES)
            ),
            "resource": list(RESOURCE_OUTCOMES),
            "disposition": list(DISPOSITION_OUTCOMES),
            "charge_components": list(CHARGE_COMPONENT_OUTCOMES),
            "clinical_discretion_exploratory": list(DISCRETION_OUTCOMES),
            "outcome_sample_rule": (
                "Each outcome uses its complete eligible outcome-specific "
                "sample. No outcome is imputed. Primary-period hourly LOS and "
                "reported real charges retain their frozen definitions."
            ),
        },
        "model_sequence": model_sequence,
        "support_and_estimability": support,
        "multiplicity": multiplicity,
        "required_tables_per_family": [
            "unadjusted outcome summaries",
            "standardized adjusted predictions or estimable marginal effects",
            "all frozen directional contrasts",
            "95% confidence intervals",
            "raw p-values and multiplicity-adjusted q-values",
            "visits/effective visits by cell and outcome",
            "physicians/effective physicians by cell and outcome",
            "facilities and both cluster counts",
            "outcome availability",
            "estimability and limited-support reason",
        ],
        "binding": {
            "provider_master_v2": evidence(provider_master, phase2),
            "provider_race_proxy_v2": evidence(race_proxy, phase2),
            "cohort_build_manifest": evidence(cohort_build_manifest, phase2),
            "provider_measurement_gate": evidence(
                measurement_gate, phase2
            ),
            "cohort_validation_gate": evidence(cohort_gate, phase2),
            "historical_measurement_gate": evidence(
                historical_gate, phase2
            ),
            "source_registry": evidence(source_registry, phase2),
            "original_sap": evidence(sap, phase2),
            "original_implementation_specification": evidence(
                implementation, phase2
            ),
            "partition_manifest_count": len(partition_audit),
            "partition_manifest_hashes": [
                {
                    "visit_year": item["visit_year"],
                    "visit_quarter": item["visit_quarter"],
                    "manifest_sha256": item["manifest_sha256"],
                    "core_sha256": item["core_sha256"],
                    "risk_sha256": item["risk_sha256"],
                    "charge_sha256": item["charge_sha256"],
                }
                for item in partition_audit
            ],
        },
        "field_audit": {
            "required_core_fields": sorted(CORE_REQUIRED_FIELDS),
            "required_risk_fields": sorted(RISK_REQUIRED_FIELDS),
            "required_charge_fields": sorted(CHARGE_REQUIRED_FIELDS),
            "common_core_field_count": len(common_core),
            "common_risk_field_count": len(common_risk),
            "common_charge_field_count": len(common_charge),
            "required_fields_present_in_all_60_partitions": True,
            "phase2_cohort_rebuild_required": False,
            "phase1_rebuild_required": False,
        },
        "analysis_script_audit": [
            {
                **evidence(path, phase2),
                "assessment": script_assessments[name],
            }
            for name, path in script_paths.items()
        ],
        "preexisting_results_inventory": {
            "files": existing_results,
            "interpretation": (
                "Inventory and hashes only. The freeze script did not parse "
                "a coefficient, confidence interval, or p-value."
            ),
        },
        "language_rule": (
            "Use association language only. Do not label any directional "
            "estimate an impact, causal effect, discrimination, concordance "
            "mechanism, or proof of clinician behavior."
        ),
        "fail_closed_rule": (
            "A matrix or result is invalid unless it reproduces the exact "
            "extension-manifest hash and every provider, cohort, measurement "
            "gate, source-registry, partition, and input-matrix hash stored "
            "here. Independent validation is required before viewing or "
            "reporting estimates."
        ),
    }

    documentation = phase2 / "documentation"
    qa = phase2 / "qa"
    manifest_path = (
        documentation
        / "Directional_Dyad_Analysis_Plan_Extension_FROZEN.json"
    )
    markdown_path = (
        documentation / "Directional_Dyad_Analysis_Plan_Extension.md"
    )
    partition_path = qa / "directional_dyad_partition_schema_audit.json"

    atomic_json(partition_path, {
        "status": "PASS",
        "created_utc": frozen_utc,
        "extension_version": EXTENSION_VERSION,
        "partitions_expected": 60,
        "partitions_passed": len(partition_audit),
        "required_fields_present_in_all_partitions": True,
        "phase2_cohort_rebuild_required": False,
        "partitions": partition_audit,
    })
    atomic_json(manifest_path, manifest)
    manifest_hash = sha256(manifest_path)
    markdown = f"""# Directional Dyad Analysis-Plan Extension

**Frozen:** {frozen_utc}  
**Version:** `{EXTENSION_VERSION}`  
**Manifest SHA-256:** `{manifest_hash}`  
**Gate:** `FROZEN_ESTIMATE_BLIND_PASS`

## Timing and status

This extension was frozen after primary-period descriptive and unadjusted
outputs and some historical inferential outputs existed, but before any
adjusted primary-period model matrix or adjusted primary-period result existed.
The freeze audit inspected file names, timestamps, schemas, manifests, and
hashes only; it did not read coefficient values.

The binary Black/White four-cell race model, the binary four-cell
recorded-sex/physician-gender model, and their interaction contrasts retain
their genuinely original SAP status. New adjusted directional cell
predictions and contrasts are secondary. The expanded five-class race family
is secondary. The expanded race-plus-gender intersectional family is
exploratory. The entire extension must not be called originally prespecified.

## Data reuse decision

All required fields are present in all 60 validated provider-v2 cohort
partitions. Phase 2 cohort rebuilding is unnecessary. Phase 1 remains
immutable. New hash-bound derived matrices will be built from the validated
2010-2024 provider-v2 partitions. The 2005-2008 cohort remains separate and
may use only historically comparable variables; hourly LOS is structurally
unavailable and will not be imputed.

## Families

- Gender: 4 directional cells and 6 frozen pairwise contrasts.
- Race: 25 five-class cells and 68 frozen directional contrasts.
- Intersectional: 100 race-plus-gender by race-plus-sex cells and 359 frozen
  axis-aligned/reference contrasts.

All cells remain visible. Sparse cells are never merged; they are labelled
`LIMITED_SUPPORT` or `NON_ESTIMABLE` under the exact thresholds in the JSON
manifest.

## Measurement

Physician race is a five-class Bayesian full-name probability proxy using the
official `wru` v2.0.0 name dictionaries and no geography. It is not BISG,
self-reported race, or an identity measure. Primary directional race results
require both posterior-mixture probability models and 20 physician-level
multiple imputations. Hard classifications, confidence thresholds, and the
national population prior are sensitivities.

Physician gender uses recorded NPPES/CMS administrative categories in the
primary analysis. Recorded patient sex is not gender identity. Patient
race/ethnicity uses the compatible five-class mapping frozen in the JSON
manifest.

## Estimation and reporting

One joint factorial model is used per family and outcome/sample specification;
the analysis will not fit hundreds of disconnected cell regressions. Results
include unadjusted cell summaries, standardized adjusted predictions or
identified marginal effects, all frozen directional contrasts, 95% confidence
intervals, raw p-values, BH q-values, cell/cluster support, and explicit
estimability status. The original two-outcome Holm confirmatory family is not
expanded.

All estimates are observational associations.
"""
    atomic_text(markdown_path, markdown)
    append_deviation_log(phase2, frozen_utc)

    checkpoint = {
        "status": "PASS",
        "created_utc": utc_now(),
        "extension_version": EXTENSION_VERSION,
        "frozen_manifest": evidence(manifest_path, phase2),
        "documentation": evidence(markdown_path, phase2),
        "partition_schema_audit": evidence(partition_path, phase2),
        "deviation_log": evidence(
            phase2 / "documentation" / "SAP_deviation_log.csv", phase2
        ),
        "gender_cells": len(gender_cells),
        "gender_contrasts": len(gender_contrasts),
        "race_cells": len(race_cells),
        "race_contrasts": len(race_contrasts),
        "intersectional_cells": len(intersectional_cells),
        "intersectional_contrasts": len(intersectional_contrasts),
        "phase1_modified": False,
        "phase2_cohort_rebuild_required": False,
        "estimation_authorized": True,
    }
    atomic_json(
        qa / "directional_dyad_extension_pre_estimation_gate.json",
        checkpoint,
    )
    print(json.dumps(checkpoint, indent=2))


if __name__ == "__main__":
    main()
