#!/usr/bin/env python3
# Sanitized portfolio copy of the validated production script.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/15_linkage_selection_audit.py
# All private roots and temporary locations are command-line parameters.

"""Audit provider-v2 linkage selection on the complete 2010-2024 fact universe."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def qpath(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace("'", "''")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    parser.add_argument("--release", required=True, type=Path)
    parser.add_argument("--temp", required=True, type=Path)
    parser.add_argument("--threads", type=int, default=12)
    parser.add_argument("--memory-limit", default="24GB")
    args = parser.parse_args()

    phase2 = args.phase2.resolve()
    release = args.release.resolve()
    args.temp.mkdir(parents=True, exist_ok=True)
    output = phase2 / "results" / "linkage"
    qa = phase2 / "qa"
    output.mkdir(parents=True, exist_ok=True)
    qa.mkdir(parents=True, exist_ok=True)
    gate_path = qa / "pre_estimation_measurement_gate.json"
    if not gate_path.exists():
        raise SystemExit(
            "Provider-v2 pre-estimation gate is missing; linkage audit is blocked"
        )
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    if gate.get("status") != "PASS":
        raise SystemExit(
            "Provider-v2 pre-estimation gate did not authorize downstream work"
        )
    fact_glob = (
        release
        / "fact_ed_visits"
        / "visit_year=*"
        / "visit_quarter=*"
        / "ed_visits.parquet"
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
    for required in (provider_master, race_proxy):
        if not required.exists():
            raise FileNotFoundError(required)

    con = duckdb.connect()
    con.execute(f"SET threads={args.threads}")
    con.execute(f"SET memory_limit='{args.memory_limit}'")
    con.execute(f"SET temp_directory='{qpath(args.temp)}'")
    con.execute("SET preserve_insertion_order=false")
    con.execute(
        f"""
        CREATE OR REPLACE VIEW provider_master_v2 AS
        SELECT * FROM read_parquet('{qpath(provider_master)}')
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE VIEW provider_race_proxy_v2 AS
        SELECT * FROM read_parquet('{qpath(race_proxy)}')
        """
    )
    source = f"read_parquet('{qpath(fact_glob)}', hive_partitioning=false)"
    base = f"""
        SELECT
            f.*,
            f.race_category AS patient_race_category,
            f.ethnicity_category AS patient_ethnicity_category,
            f.sex_category AS patient_sex_category,
            p.npi IS NOT NULL AS provider_master_v2_match,
            p.provider_entity_category_v2,
            p.clinician_type_v2,
            p.physician_md_do_flag_v2,
            (f.attending_selection_method = 'direct_validated_npi')
                AS direct_npi_link,
            (
                f.attending_selection_method = 'direct_validated_npi'
                AND p.provider_entity_category_v2 = 'Individual'
                AND coalesce(p.physician_md_do_flag_v2, false)
            ) AS direct_matched_md_do,
            (
                f.attending_selection_method IN (
                    'direct_validated_npi', 'unique_fl_license_crosswalk'
                )
                AND p.provider_entity_category_v2 = 'Individual'
                AND coalesce(p.physician_md_do_flag_v2, false)
            ) AS any_resolved_matched_md_do,
            (
                f.attending_selection_method = 'direct_validated_npi'
                AND p.provider_entity_category_v2 = 'Individual'
                AND coalesce(p.physician_md_do_flag_v2, false)
                AND r.race_proxy_primary_five_class_label
                    IN ('Black', 'White')
                AND coalesce(r.last_match_flag, false)
                AND coalesce(r.first_match_flag, false)
            ) AS direct_race_proxy_available,
            (
                f.attending_selection_method = 'direct_validated_npi'
                AND p.provider_entity_category_v2 = 'Individual'
                AND coalesce(p.physician_md_do_flag_v2, false)
                AND p.gender_category_v2 IN ('Female', 'Male')
            ) AS direct_gender_available
        FROM {source} AS f
        LEFT JOIN provider_master_v2 AS p
          ON f.attending_selected_npi = p.npi
        LEFT JOIN provider_race_proxy_v2 AS r
          ON f.attending_selected_npi = r.npi
        WHERE f.visit_year BETWEEN 2010 AND 2024
    """
    stage = con.execute(
        f"""
        WITH base AS ({base})
        SELECT
            visit_year,
            count(*) AS all_ed_visits,
            sum(attending_selected_npi IS NOT NULL)
                AS resolved_attending_identifier,
            sum(direct_npi_link) AS direct_npi_link,
            sum(attending_selection_method = 'unique_fl_license_crosswalk')
                AS unique_license_link,
            sum(provider_master_v2_match)
                AS provider_master_v2_match,
            sum(direct_matched_md_do) AS direct_matched_md_do,
            sum(any_resolved_matched_md_do) AS any_resolved_matched_md_do,
            sum(direct_race_proxy_available) AS direct_race_proxy_available,
            sum(direct_gender_available) AS direct_gender_available
        FROM base
        GROUP BY visit_year
        ORDER BY visit_year
        """
    ).fetchdf()
    for column in stage.columns[2:]:
        stage[f"{column}_percent"] = 100 * stage[column] / stage["all_ed_visits"]
    stage.to_csv(output / "linkage_flow_by_year.csv", index=False)

    stratifiers = [
        "patient_race_category",
        "patient_ethnicity_category",
        "patient_sex_category",
        "payer_group",
        "patient_zip_rurality_3level",
        "principal_clinical_category",
        "facility_ahca_id",
    ]
    unions = []
    for variable in stratifiers:
        unions.append(
            f"""
            SELECT
                '{variable}' AS stratifier,
                coalesce(cast({variable} AS VARCHAR), '<MISSING>') AS category,
                count(*) AS all_visits,
                sum(direct_npi_link) AS direct_npi_links,
                100.0 * avg(direct_npi_link::DOUBLE)
                    AS direct_npi_link_percent,
                sum(direct_matched_md_do) AS direct_matched_md_do_visits,
                100.0 * avg(direct_matched_md_do::DOUBLE)
                    AS direct_matched_md_do_percent,
                sum(direct_race_proxy_available) AS direct_race_proxy_visits,
                100.0 * avg(direct_race_proxy_available::DOUBLE)
                    AS direct_race_proxy_percent,
                sum(direct_gender_available) AS direct_gender_visits,
                100.0 * avg(direct_gender_available::DOUBLE)
                    AS direct_gender_percent
            FROM base
            GROUP BY {variable}
            """
        )
    stratified = con.execute(
        f"WITH base AS ({base}) "
        + " UNION ALL ".join(unions)
        + " ORDER BY stratifier, all_visits DESC"
    ).fetchdf()
    stratified.to_csv(output / "linkage_rates_by_stratum.csv", index=False)

    continuous = [
        "age_years",
        "elixhauser_condition_count",
        "length_of_stay_days",
        "total_charge_reported",
        "procedure_count_analysis",
    ]
    continuous_union = []
    for variable in continuous:
        continuous_union.append(
            f"""
            SELECT
                '{variable}' AS variable,
                direct_matched_md_do AS linked_group,
                count({variable}) AS nonmissing_n,
                avg(cast({variable} AS DOUBLE)) AS mean,
                stddev_samp(cast({variable} AS DOUBLE)) AS sd,
                quantile_cont(cast({variable} AS DOUBLE), 0.5) AS median
            FROM base
            GROUP BY direct_matched_md_do
            """
        )
    continuous_frame = con.execute(
        f"WITH base AS ({base}) "
        + " UNION ALL ".join(continuous_union)
        + " ORDER BY variable, linked_group"
    ).fetchdf()
    continuous_frame.to_csv(
        output / "linked_unlinked_continuous_profile.csv", index=False
    )

    smd_rows = []
    for variable, block in continuous_frame.groupby("variable"):
        block = block.set_index("linked_group")
        if True not in block.index or False not in block.index:
            continue
        linked = block.loc[True]
        unlinked = block.loc[False]
        pooled_sd = (
            (float(linked["sd"]) ** 2 + float(unlinked["sd"]) ** 2) / 2
        ) ** 0.5
        smd_rows.append(
            {
                "variable": variable,
                "linked_mean": linked["mean"],
                "unlinked_mean": unlinked["mean"],
                "standardized_mean_difference": (
                    (linked["mean"] - unlinked["mean"]) / pooled_sd
                    if pooled_sd > 0
                    else None
                ),
                "linked_n": linked["nonmissing_n"],
                "unlinked_n": unlinked["nonmissing_n"],
            }
        )
    pd.DataFrame(smd_rows).to_csv(
        output / "linked_unlinked_standardized_differences.csv", index=False
    )

    facility_time = con.execute(
        f"""
        WITH base AS ({base})
        SELECT
            visit_year,
            visit_quarter,
            facility_ahca_id,
            count(*) AS all_visits,
            sum(direct_matched_md_do) AS direct_matched_md_do_visits,
            avg(direct_matched_md_do::DOUBLE) AS direct_matched_md_do_rate,
            avg(direct_race_proxy_available::DOUBLE)
                AS direct_race_proxy_rate,
            avg(direct_gender_available::DOUBLE)
                AS direct_gender_rate
        FROM base
        GROUP BY visit_year, visit_quarter, facility_ahca_id
        ORDER BY visit_year, visit_quarter, facility_ahca_id
        """
    ).fetchdf()
    facility_time.to_parquet(
        phase2
        / "analysis_data"
        / "dimensions"
        / "facility_quarter_linkage_rates.parquet",
        index=False,
    )
    facility_time.describe(percentiles=[0.01, 0.05, 0.5, 0.95, 0.99]).to_csv(
        output / "facility_quarter_linkage_rate_distribution.csv"
    )
    con.close()

    total = stage["all_ed_visits"].sum()
    direct_md = stage["direct_matched_md_do"].sum()
    direct_race = stage["direct_race_proxy_available"].sum()
    direct_gender = stage["direct_gender_available"].sum()
    report = {
        "created_utc": now_utc(),
        "status": "PASS",
        "all_ed_visits_2010_2024": int(total),
        "direct_matched_md_do_visits": int(direct_md),
        "direct_matched_md_do_percent": float(100 * direct_md / total),
        "direct_race_proxy_available_visits": int(direct_race),
        "direct_race_proxy_available_percent": float(100 * direct_race / total),
        "direct_gender_available_visits": int(direct_gender),
        "direct_gender_available_percent": float(100 * direct_gender / total),
        "selection_assessment": (
            "Linkage and attribute availability vary by year, facility, and "
            "patient/clinical strata; primary results must be interpreted for "
            "the linked physician-observed population."
        ),
        "inverse_probability_weighting_decision": (
            "Not used as a primary correction. Physician concordance exposure "
            "is structurally unobserved when linkage or physician attributes "
            "are absent, and facility-demographic linkage propensities cannot "
            "establish missing-at-random identification. Facility-quarter "
            "linkage rates are saved for descriptive and sensitivity use."
        ),
        "ipw_justified": False,
        "provider_measurement_version": (
            "provider_master_v2_full_name_race_v1"
        ),
        "pre_estimation_gate": str(gate_path),
        "pre_estimation_gate_status": gate["status"],
        "phase1_physician_fields_used": False,
        "source_release_modified": False,
    }
    (qa / "linkage_selection_audit.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
