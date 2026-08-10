#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/17b_historical_sex_gender_sensitivity.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Estimate gated all-diagnosis 2005-2008 sex/gender sensitivities."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import pyfixest as pf


OUTCOMES = [
    "length_of_stay_days",
    "total_charge_reported_real_2024",
    "procedure_count_analysis",
    "any_procedure_flag",
    "routine_discharge_flag",
    "transfer_flag",
    "mortality_flag",
]


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def qpath(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace("'", "''")


def safe_float(value: Any) -> float:
    return float(value) if value is not None else math.nan


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
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    parser.add_argument("--temp", required=True, type=Path)
    parser.add_argument("--threads", type=int, default=12)
    parser.add_argument("--memory-limit", default="24GB")
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()

    phase2 = args.phase2.resolve()
    args.temp.mkdir(parents=True, exist_ok=True)
    gate_path = phase2 / "qa" / "historical_provider_v2_pre_estimation_gate.json"
    if not gate_path.exists():
        raise SystemExit(
            "Historical provider-v2 gate is missing; estimation is blocked"
        )
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    if (
        gate.get("status") != "PASS"
        or gate.get("historical_estimation_authorized") is not True
        or gate.get("reconciled_partitions") != 16
        or gate.get("hourly_los_errors") != 0
    ):
        raise SystemExit(
            "Historical provider-v2 gate did not authorize estimation"
        )

    historical_glob = (
        phase2
        / "analysis_data"
        / "historical_provider_v2"
        / "visit_year=*"
        / "visit_quarter=*"
        / "historical_provider_v2_core.parquet"
    )
    output = (
        phase2 / "results" / "historical_provider_v2_sex_gender_sensitivity"
    )
    qa = phase2 / "qa"
    documentation = phase2 / "documentation"
    output.mkdir(parents=True, exist_ok=True)
    qa.mkdir(parents=True, exist_ok=True)
    documentation.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    con.execute(f"SET threads={args.threads}")
    con.execute(f"SET memory_limit='{args.memory_limit}'")
    con.execute(f"SET temp_directory='{qpath(args.temp)}'")
    source = f"read_parquet('{qpath(historical_glob)}', hive_partitioning=false)"
    elix_flags = sorted(
        row[0]
        for row in con.execute(
            f"DESCRIBE SELECT * FROM {source}"
        ).fetchall()
        if row[0].startswith("elix_") and row[0].endswith("_flag")
    )
    eligible = (
        f"(SELECT * FROM {source} "
        "WHERE sex_gender_historical_eligible_flag)"
    )

    counts = con.execute(
        f"""
        SELECT
            visit_year,
            sex_gender_pair_category,
            count(*) AS visits,
            count(DISTINCT attending_selected_npi) AS physicians,
            count(DISTINCT facility_ahca_id) AS facilities
        FROM {eligible}
        GROUP BY visit_year, sex_gender_pair_category
        ORDER BY visit_year, sex_gender_pair_category
        """
    ).fetchdf()
    counts.to_csv(
        output / "historical_sex_gender_pair_counts_by_year.csv",
        index=False,
    )
    descriptive_parts = []
    for outcome in OUTCOMES:
        numeric_outcome = f"cast({outcome} AS DOUBLE)"
        descriptive_parts.append(
            f"""
            SELECT
                '{outcome}' AS outcome,
                sex_gender_pair_category,
                count({outcome}) AS nonmissing_n,
                avg({numeric_outcome}) AS mean,
                stddev_samp({numeric_outcome}) AS sd,
                quantile_cont({numeric_outcome}, 0.5) AS median,
                quantile_cont({numeric_outcome}, 0.25) AS p25,
                quantile_cont({numeric_outcome}, 0.75) AS p75
            FROM {eligible}
            GROUP BY sex_gender_pair_category
            """
        )
    descriptive = con.execute(
        " UNION ALL ".join(descriptive_parts)
        + " ORDER BY outcome, sex_gender_pair_category"
    ).fetchdf()
    descriptive.to_csv(
        output / "historical_sex_gender_pair_descriptive_statistics.csv",
        index=False,
    )

    frame = con.execute(
        f"""
        SELECT
            visit_year,
            visit_quarter,
            facility_ahca_id,
            facility_year_quarter_id,
            attending_selected_npi,
            principal_clinical_category,
            historical_patient_group,
            historical_race_ethnicity_code,
            patient_sex_category,
            physician_gender_category,
            physician_gender_source,
            physician_gender_source_conflict_flag,
            age_years,
            payer_group,
            patient_zip_rurality_3level,
            weekend_flag,
            off_hours_flag,
            elixhauser_condition_count,
            {", ".join(elix_flags)},
            attending_ed_specialist_flag,
            attending_years_since_medical_school,
            {", ".join(OUTCOMES)}
        FROM {eligible}
        """
    ).fetchdf()
    con.close()

    frame["physician_female"] = (
        frame["physician_gender_category"] == "Female"
    ).astype(float)
    frame["patient_female"] = (
        frame["patient_sex_category"] == "Female"
    ).astype(float)
    frame["sex_gender_interaction"] = (
        frame["physician_female"] * frame["patient_female"]
    )
    age = pd.to_numeric(frame["age_years"], errors="coerce")
    frame["age_missing"] = age.isna().astype(float)
    frame["age"] = age.fillna(age.median()).clip(0, 120)
    frame["age_gt18"] = (frame["age"] - 18).clip(lower=0)
    frame["age_gt45"] = (frame["age"] - 45).clip(lower=0)
    frame["age_gt65"] = (frame["age"] - 65).clip(lower=0)
    frame["age_gt80"] = (frame["age"] - 80).clip(lower=0)
    frame["weekend"] = frame["weekend_flag"].fillna(False).astype(float)
    frame["off_hours"] = frame["off_hours_flag"].fillna(False).astype(float)
    frame["ed_specialist"] = (
        frame["attending_ed_specialist_flag"].fillna(False).astype(float)
    )
    experience = pd.to_numeric(
        frame["attending_years_since_medical_school"], errors="coerce"
    ).where(lambda values: values.between(0, 80))
    frame["experience_missing"] = experience.isna().astype(float)
    frame["experience"] = experience.fillna(experience.median())
    frame["historical_patient_group_model"] = frame[
        "historical_patient_group"
    ].fillna(
        frame["historical_race_ethnicity_code"].fillna("<MISSING>").map(
            lambda value: f"historical_code_{value}"
        )
    )
    dummies = pd.get_dummies(
        frame[
            [
                "payer_group",
                "patient_zip_rurality_3level",
                "historical_patient_group_model",
            ]
        ].fillna("<MISSING>"),
        prefix=["payer", "rurality", "patient_group"],
        drop_first=True,
        dtype=float,
    )
    dummies.columns = [
        "".join(
            character if character.isalnum() else "_"
            for character in name
        )
        for name in dummies.columns
    ]
    frame = pd.concat([frame, dummies], axis=1)
    for flag in elix_flags:
        frame[flag] = (
            pd.to_numeric(frame[flag], errors="coerce")
            .fillna(0)
            .astype(float)
        )
    terms = [
        "physician_female",
        "patient_female",
        "sex_gender_interaction",
        "age",
        "age_gt18",
        "age_gt45",
        "age_gt65",
        "age_gt80",
        "age_missing",
        "weekend",
        "off_hours",
        "elixhauser_condition_count",
        *elix_flags,
        "ed_specialist",
        "experience",
        "experience_missing",
        *dummies.columns.tolist(),
    ]
    rhs = " + ".join(terms)

    model_rows: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    frame_rows = len(frame)
    recorded_source_conflict_visits = int(
        frame["physician_gender_source_conflict_flag"]
        .fillna(False)
        .astype(bool)
        .sum()
    )
    sample_variants = {
        "recorded_sources": pd.Series(True, index=frame.index),
        "recorded_sources_no_nppes_cms_conflict": (
            ~frame["physician_gender_source_conflict_flag"]
            .fillna(False)
            .astype(bool)
        ),
    }
    sample_ids = list(sample_variants)
    isolated_root = args.temp / "isolated_sex_gender_models"
    input_root = isolated_root / "inputs"
    job_root = isolated_root / "jobs"
    result_root = isolated_root / "results"
    input_root.mkdir(parents=True, exist_ok=True)
    job_root.mkdir(parents=True, exist_ok=True)
    result_root.mkdir(parents=True, exist_ok=True)
    jobs: list[dict[str, Any]] = []
    for sample_id, sample_mask in sample_variants.items():
        block = frame.loc[sample_mask].copy()
        input_path = input_root / f"{sample_id}.parquet"
        temporary_input = input_path.with_suffix(".parquet.tmp")
        block.to_parquet(temporary_input, index=False)
        temporary_input.replace(input_path)
        input_sha256 = sha256_file(input_path)
        for outcome in OUTCOMES:
            model_id = (
                f"historical_2005_2008_sex_gender_{sample_id}_"
                f"{outcome}_adjusted"
            )
            job_token = f"job_{len(jobs) + 1:03d}"
            job = {
                "model_id": model_id,
                "specification_id": sample_id,
                "input_parquet": str(input_path),
                "input_sha256": input_sha256,
                "output_json": str(result_root / f"{job_token}.json"),
                "outcome": outcome,
                "terms": terms,
                "fixed_effects": (
                    "facility_year_quarter_id + "
                    "principal_clinical_category"
                ),
                "fixed_effect_columns": [
                    "facility_year_quarter_id",
                    "principal_clinical_category",
                ],
                "cluster": (
                    "attending_selected_npi + facility_ahca_id"
                ),
                "cluster_columns": [
                    "attending_selected_npi",
                    "facility_ahca_id",
                ],
                "interaction_term": "sex_gender_interaction",
                "contrast": (
                    "female_patient:female_physician interaction"
                ),
                "result_dimensions": {"sample_id": sample_id},
                "diagnostic_dimensions": {"sample_id": sample_id},
                "diagnostic_distinct_columns": {
                    "physicians": "attending_selected_npi",
                    "facilities": "facility_ahca_id",
                },
            }
            job_path = job_root / f"{job_token}.json"
            atomic_json(job_path, job)
            jobs.append({"job_path": job_path, **job})
        del block
        gc.collect()

    preparation_manifest = {
        "created_utc": now_utc(),
        "status": "PASS",
        "analysis": "sex_gender",
        "frame_rows": frame_rows,
        "recorded_source_conflict_visits": (
            recorded_source_conflict_visits
        ),
        "elixhauser_indicator_count": len(elix_flags),
        "pre_estimation_gate": str(gate_path),
        "pre_estimation_gate_status": gate["status"],
        "sample_variants": sample_ids,
        "job_paths": [str(job["job_path"]) for job in jobs],
        "jobs_expected": len(OUTCOMES) * len(sample_ids),
        "jobs_prepared": len(jobs),
        "input_hashes": {
            job["specification_id"]: job["input_sha256"]
            for job in jobs
        },
    }
    atomic_json(
        isolated_root / "preparation_manifest.json",
        preparation_manifest,
    )
    if args.prepare_only:
        print(json.dumps(preparation_manifest, indent=2))
        return

    del frame
    del sample_variants
    del dummies
    gc.collect()

    worker = Path(__file__).with_name("historical_hdfe_isolated_worker.py")
    for job in jobs:
        completed = subprocess.run(
            [sys.executable, str(worker), "--job", str(job["job_path"])],
            check=False,
        )
        result_path = Path(job["output_json"])
        if result_path.exists():
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            if payload.get("result") is not None:
                model_rows.append(payload["result"])
            diagnostics.append(payload["diagnostic"])
        else:
            diagnostics.append(
                {
                    "model_id": job["model_id"],
                    "sample_id": job["specification_id"],
                    "status": "failed",
                    "n": None,
                    "worker_isolated_process": True,
                    "error": (
                        "Isolated worker exited without an atomic result; "
                        f"return_code={completed.returncode}"
                    ),
                }
            )

    pd.DataFrame(model_rows).to_csv(
        output / "historical_sex_gender_adjusted_interactions.csv",
        index=False,
    )
    pd.DataFrame(diagnostics).to_csv(
        qa / "historical_provider_v2_sex_gender_model_diagnostics.csv",
        index=False,
    )
    converged = sum(item["status"] == "converged" for item in diagnostics)
    status = (
        "PASS"
        if len(diagnostics) == len(OUTCOMES) * len(sample_ids)
        and converged == len(OUTCOMES) * len(sample_ids)
        else "FAIL"
    )
    manifest = {
        "created_utc": now_utc(),
        "status": status,
        "analysis_id": (
            "historical_provider_v2_sex_gender_sensitivity_v1"
        ),
        "rows": frame_rows,
        "outcomes": OUTCOMES,
        "models_expected": len(OUTCOMES) * len(sample_ids),
        "models_converged": converged,
        "sample_variants": sample_ids,
        "recorded_source_conflict_visits": (
            recorded_source_conflict_visits
        ),
        "worker_isolation": (
            "One hash-bound parquet input and one fresh OS process per "
            "model; no sample or covariate reduction."
        ),
        "models_using_demeaning_fallback": sum(
            bool(item.get("demeaning_fallback_used"))
            for item in diagnostics
            if item["status"] == "converged"
        ),
        "elixhauser_indicator_count": len(elix_flags),
        "separate_analysis": True,
        "never_pooled_with_primary": True,
        "provider_measurement_version": (
            "provider_master_v2_full_name_race_v1"
        ),
        "pre_estimation_gate": str(gate_path),
        "pre_estimation_gate_status": gate["status"],
        "hourly_los_used": False,
        "los_outcome": "length_of_stay_days",
        "terminology": (
            "recorded patient sex-physician gender concordance; not gender identity"
        ),
        "limitations": [
            "Unique Florida-license linkage rather than direct source NPI.",
            "Day-level LOS only because discharge hour is unavailable.",
            (
                "Current provider attributes do not establish historical "
                "employment, affiliation, privilege, specialty, or identity."
            ),
        ],
    }
    (
        output / "historical_sex_gender_analysis_manifest.json"
    ).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    methods = f"""# Historical 2005-2008 sex/gender sensitivity

This all-diagnosis sensitivity is estimated separately from both the
2010-2024 primary cohort and the historical AMI/Greenwood extension. It uses
the provider-v2 unique-license-linked individual MD/DO cohort with recorded
patient sex and physician gender categories of Female or Male from NPPES/CMS.
SSA first-name-imputed physician gender is not eligible. A second exact model
variant excludes NPIs whose recorded NPPES and CMS categories disagree.

Models include facility-year-quarter and principal clinical-category fixed
effects, two-way physician/facility clustered standard errors, age splines,
historical patient-group categories, payer, rurality, weekend, off-hours,
all available Elixhauser-condition indicators and the condition count,
ED-specialist status, and experience.

The terminology is recorded patient sex-physician gender concordance. These
administrative/provider fields are not interpreted as gender identity.
Compatible outcomes include day-level LOS, CPI-adjusted charges, procedures,
routine discharge, transfer, and ED mortality. Hourly LOS is structurally
unavailable and is not imputed.

Gate: `{gate_path}`
"""
    (
        documentation / "Historical_Sex_Gender_Sensitivity.md"
    ).write_text(methods, encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    if status != "PASS":
        raise SystemExit(
            "One or more required historical sex/gender models failed"
        )


if __name__ == "__main__":
    main()
