#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/17_historical_sensitivity_analysis.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Analyze the gated 2005-2008 provider-v2 race sensitivity separately."""

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
import numpy as np
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
PAIRS = ["black_black", "black_white", "white_black", "white_white"]
WEIGHTS = np.array([1.0, -1.0, -1.0, 1.0])
SPECIFICATIONS = (
    "primary_prior_t50",
    "primary_prior_t70",
    "primary_prior_t80",
    "primary_prior_t90",
    "population_prior_t50",
    "primary_probability_bw",
)


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
    output = phase2 / "results" / "historical_provider_v2_sensitivity"
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
    primary_t50_source = (
        f"(SELECT * FROM {source} "
        "WHERE historical_race_concordance_eligible_t50_flag)"
    )

    counts = con.execute(
        f"""
        SELECT
            visit_year,
            race_pair_category,
            count(*) AS visits,
            count(DISTINCT attending_selected_npi) AS physicians,
            count(DISTINCT facility_ahca_id) AS facilities
        FROM {primary_t50_source}
        GROUP BY visit_year, race_pair_category
        ORDER BY visit_year, race_pair_category
        """
    ).fetchdf()
    counts.to_csv(
        output / "historical_primary_t50_pair_counts_by_year.csv",
        index=False,
    )

    descriptive_parts = []
    for outcome in OUTCOMES:
        numeric_outcome = f"cast({outcome} AS DOUBLE)"
        descriptive_parts.append(
            f"""
            SELECT
                '{outcome}' AS outcome,
                race_pair_category,
                count({outcome}) AS nonmissing_n,
                avg({numeric_outcome}) AS mean,
                stddev_samp({numeric_outcome}) AS sd,
                quantile_cont({numeric_outcome}, 0.5) AS median,
                quantile_cont({numeric_outcome}, 0.25) AS p25,
                quantile_cont({numeric_outcome}, 0.75) AS p75
            FROM {primary_t50_source}
            GROUP BY race_pair_category
            """
        )
    descriptive = con.execute(
        " UNION ALL ".join(descriptive_parts)
        + " ORDER BY outcome, race_pair_category"
    ).fetchdf()
    descriptive.to_csv(
        output / "historical_primary_t50_pair_descriptive_statistics.csv",
        index=False,
    )
    contrast_rows: list[dict[str, Any]] = []
    for outcome, block in descriptive.groupby("outcome"):
        block = block.set_index("race_pair_category").reindex(PAIRS)
        means = block["mean"].to_numpy(float)
        n = block["nonmissing_n"].to_numpy(float)
        sd = block["sd"].to_numpy(float)
        estimate = float(WEIGHTS @ means)
        se = float(np.sqrt(np.sum(sd**2 / n)))
        contrast_rows.append(
            {
                "race_specification": "primary_prior_t50",
                "outcome": outcome,
                "contrast": (
                    "black_black - black_white - white_black + white_white"
                ),
                "estimate": estimate,
                "unclustered_descriptive_se": se,
                "ci95_low": estimate - 1.95996398454 * se,
                "ci95_high": estimate + 1.95996398454 * se,
            }
        )
    pd.DataFrame(contrast_rows).to_csv(
        output / "historical_primary_t50_unadjusted_contrasts.csv",
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
            patient_black_flag,
            patient_sex_category,
            physician_race_proxy_primary_label,
            physician_race_population_label,
            physician_race_proxy_prob_black_conditional_bw,
            physician_race_proxy_black_white_mass,
            physician_race_population_prob_black_conditional_bw,
            physician_race_population_black_white_mass,
            historical_race_concordance_eligible_t50_flag,
            historical_race_concordance_eligible_t70_flag,
            historical_race_concordance_eligible_t80_flag,
            historical_race_concordance_eligible_t90_flag,
            historical_race_population_prior_eligible_t50_flag,
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
        FROM {source}
        WHERE historical_patient_bw_defined_flag
          AND provider_v2_md_do_eligible_flag
          AND physician_race_last_match_flag
          AND physician_race_first_match_flag
        """
    ).fetchdf()
    con.close()

    age = pd.to_numeric(frame["age_years"], errors="coerce")
    frame["age_missing"] = age.isna().astype(float)
    frame["age"] = age.fillna(age.median()).clip(0, 120)
    frame["age_gt18"] = (frame["age"] - 18).clip(lower=0)
    frame["age_gt45"] = (frame["age"] - 45).clip(lower=0)
    frame["age_gt65"] = (frame["age"] - 65).clip(lower=0)
    frame["age_gt80"] = (frame["age"] - 80).clip(lower=0)
    frame["patient_black_flag"] = frame["patient_black_flag"].astype(float)
    frame["patient_female"] = (
        frame["patient_sex_category"] == "Female"
    ).astype(float)
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
    dummies = pd.get_dummies(
        frame[["payer_group", "patient_zip_rurality_3level"]].fillna(
            "<MISSING>"
        ),
        prefix=["payer", "rurality"],
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
    adjustment_terms = [
        "physician_black_exposure",
        "patient_black_flag",
        "race_interaction",
        "age",
        "age_gt18",
        "age_gt45",
        "age_gt65",
        "age_gt80",
        "age_missing",
        "patient_female",
        "weekend",
        "off_hours",
        "elixhauser_condition_count",
        *elix_flags,
        "ed_specialist",
        "experience",
        "experience_missing",
        *dummies.columns.tolist(),
    ]
    rhs = " + ".join(adjustment_terms)

    specification_masks = {
        "primary_prior_t50": frame[
            "historical_race_concordance_eligible_t50_flag"
        ].fillna(False),
        "primary_prior_t70": frame[
            "historical_race_concordance_eligible_t70_flag"
        ].fillna(False),
        "primary_prior_t80": frame[
            "historical_race_concordance_eligible_t80_flag"
        ].fillna(False),
        "primary_prior_t90": frame[
            "historical_race_concordance_eligible_t90_flag"
        ].fillna(False),
        "population_prior_t50": frame[
            "historical_race_population_prior_eligible_t50_flag"
        ].fillna(False),
        "primary_probability_bw": (
            pd.to_numeric(
                frame["physician_race_proxy_prob_black_conditional_bw"],
                errors="coerce",
            ).notna()
            & (
                pd.to_numeric(
                    frame["physician_race_proxy_black_white_mass"],
                    errors="coerce",
                )
                > 0
            )
        ),
    }
    count_rows: list[dict[str, Any]] = []
    model_rows: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    isolated_root = args.temp / "isolated_race_models"
    input_root = isolated_root / "inputs"
    job_root = isolated_root / "jobs"
    result_root = isolated_root / "results"
    input_root.mkdir(parents=True, exist_ok=True)
    job_root.mkdir(parents=True, exist_ok=True)
    result_root.mkdir(parents=True, exist_ok=True)
    jobs: list[dict[str, Any]] = []
    frame_rows = len(frame)
    for specification in SPECIFICATIONS:
        block = frame.loc[specification_masks[specification]].copy()
        if specification == "population_prior_t50":
            block["physician_black_exposure"] = (
                block["physician_race_population_label"] == "Black"
            ).astype(float)
            exposure_definition = (
                "hard label from official wru national 2020 prior at max "
                "probability >= 0.50"
            )
        elif specification == "primary_probability_bw":
            block["physician_black_exposure"] = pd.to_numeric(
                block["physician_race_proxy_prob_black_conditional_bw"],
                errors="coerce",
            )
            exposure_definition = (
                "continuous conditional Black probability among Black/White "
                "using the Florida physician prior; no hard threshold"
            )
        else:
            block["physician_black_exposure"] = (
                block["physician_race_proxy_primary_label"] == "Black"
            ).astype(float)
            exposure_definition = (
                "hard label from Florida physician prior at the named "
                "maximum-probability threshold"
            )
        block["race_interaction"] = (
            block["patient_black_flag"]
            * block["physician_black_exposure"]
        )
        for year, year_block in block.groupby("visit_year"):
            count_rows.append(
                {
                    "race_specification": specification,
                    "visit_year": int(year),
                    "visits": len(year_block),
                    "physicians": int(
                        year_block["attending_selected_npi"].nunique()
                    ),
                    "facilities": int(
                        year_block["facility_ahca_id"].nunique()
                    ),
                    "exposure_definition": exposure_definition,
                }
            )
        input_path = input_root / f"{specification}.parquet"
        temporary_input = input_path.with_suffix(".parquet.tmp")
        block.to_parquet(temporary_input, index=False)
        temporary_input.replace(input_path)
        input_sha256 = sha256_file(input_path)
        for outcome in OUTCOMES:
            model_id = (
                f"historical_2005_2008_{specification}_{outcome}_adjusted"
            )
            job_token = f"job_{len(jobs) + 1:03d}"
            job = {
                "model_id": model_id,
                "specification_id": specification,
                "input_parquet": str(input_path),
                "input_sha256": input_sha256,
                "output_json": str(result_root / f"{job_token}.json"),
                "outcome": outcome,
                "terms": adjustment_terms,
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
                "interaction_term": "race_interaction",
                "contrast": (
                    "patient Black x physician Black label/probability"
                ),
                "result_dimensions": {
                    "race_specification": specification,
                    "exposure_definition": exposure_definition,
                },
                "diagnostic_dimensions": {
                    "race_specification": specification,
                },
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

    pd.DataFrame(count_rows).to_csv(
        output / "historical_race_specification_counts_by_year.csv",
        index=False,
    )
    preparation_manifest = {
        "created_utc": now_utc(),
        "status": "PASS",
        "analysis": "race",
        "frame_rows": frame_rows,
        "elixhauser_indicator_count": len(elix_flags),
        "pre_estimation_gate": str(gate_path),
        "pre_estimation_gate_status": gate["status"],
        "job_paths": [str(job["job_path"]) for job in jobs],
        "jobs_expected": len(SPECIFICATIONS) * len(OUTCOMES),
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
    del specification_masks
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
                    "race_specification": job["specification_id"],
                    "status": "failed",
                    "n": None,
                    "worker_isolated_process": True,
                    "error": (
                        "Isolated worker exited without an atomic result; "
                        f"return_code={completed.returncode}"
                    ),
                }
            )

    pd.DataFrame(count_rows).to_csv(
        output / "historical_race_specification_counts_by_year.csv",
        index=False,
    )
    pd.DataFrame(model_rows).to_csv(
        output / "historical_adjusted_race_sensitivities.csv",
        index=False,
    )
    pd.DataFrame(diagnostics).to_csv(
        qa / "historical_provider_v2_race_model_diagnostics.csv",
        index=False,
    )
    expected_models = len(SPECIFICATIONS) * len(OUTCOMES)
    converged = sum(item["status"] == "converged" for item in diagnostics)
    status = (
        "PASS"
        if len(diagnostics) == expected_models and converged == expected_models
        else "FAIL"
    )
    manifest = {
        "created_utc": now_utc(),
        "status": status,
        "analysis_id": "historical_provider_v2_race_sensitivities_v1",
        "rows_in_name_matched_historical_bw_frame": frame_rows,
        "race_specifications": list(SPECIFICATIONS),
        "outcomes": OUTCOMES,
        "models_expected": expected_models,
        "models_converged": converged,
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
        "limitations": [
            "Historical combined race/ethnicity source codes.",
            "Unique Florida-license linkage rather than direct source NPI.",
            "Day-level LOS only because discharge hour is unavailable.",
            (
                "Current provider attributes do not establish historical "
                "employment, affiliation, privilege, specialty, or identity."
            ),
            (
                "Name probabilities are algorithmic proxies without "
                "residential geography, not BISG or self-identified race."
            ),
        ],
    }
    manifest_path = output / "historical_analysis_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    methods = f"""# Historical 2005-2008 race-concordance sensitivity

This analysis is separately estimated after the 16-quarter provider-v2
historical gate passes. It is not pooled with the 2010-2024 primary cohort.

The patient contrast uses historical combined race/ethnicity code 3 versus
code 4. Physician measurement uses the provider-v2 full-name probability
model. Prespecified sensitivities include Florida-physician-prior hard labels
at 0.50, 0.70, 0.80, and 0.90 maximum-probability thresholds; a hard label
using the official wru national 2020 prior at 0.50; and a continuous
conditional Black probability among Black/White under the Florida physician
prior.

All models use facility-year-quarter and principal clinical-category fixed
effects with two-way physician/facility clustered standard errors. Adjustment
includes all available Elixhauser-condition indicators and the condition
count. Compatible historical outcomes are day-level LOS, CPI-adjusted reported
charges, procedure count, any procedure, routine discharge, transfer, and ED
mortality. Hourly LOS is structurally unavailable and is not imputed.

The physician race measure is a name-based analytical probability without
residential geography. It is not BISG and not self-identified race.

Gate: `{gate_path}`
"""
    (
        documentation / "Historical_Race_Concordance_Sensitivity.md"
    ).write_text(methods, encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    if status != "PASS":
        raise SystemExit("One or more required historical race models failed")


if __name__ == "__main__":
    main()
