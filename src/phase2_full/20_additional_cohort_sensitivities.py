#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/20_additional_cohort_sensitivities.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Generate exact full-data cohort-definition and alternate-role sensitivities."""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd


PAIRS = ["black_black", "black_white", "white_black", "white_white"]
WEIGHTS = np.array([1.0, -1.0, -1.0, 1.0])
OUTCOMES = [
    "los_hours_primary_0_168",
    "total_charge_reported_real_2024",
    "procedure_count_analysis",
    "any_procedure_flag",
    "routine_discharge_flag",
    "mortality_flag",
]


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def qpath(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace("'", "''")


def contrasts(summary: pd.DataFrame, cohort_column: str) -> pd.DataFrame:
    rows = []
    for (cohort, outcome), block in summary.groupby([cohort_column, "outcome"]):
        block = block.set_index("race_pair_category").reindex(PAIRS)
        if block["mean"].isna().any():
            continue
        means = block["mean"].to_numpy(float)
        counts = block["nonmissing_n"].to_numpy(float)
        sds = block["sd"].to_numpy(float)
        estimate = float(WEIGHTS @ means)
        se = float(np.sqrt(np.sum(sds**2 / counts)))
        rows.append(
            {
                cohort_column: cohort,
                "outcome": outcome,
                "contrast": (
                    "black_black - black_white - white_black + white_white"
                ),
                "estimate": estimate,
                "unclustered_descriptive_se": se,
                "ci95_low": estimate - 1.95996398454 * se,
                "ci95_high": estimate + 1.95996398454 * se,
                "n": int(counts.sum()),
            }
        )
    return pd.DataFrame(rows)


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
    output = phase2 / "results" / "cohort_sensitivities"
    output.mkdir(parents=True, exist_ok=True)
    gate_path = phase2 / "qa" / "pre_estimation_measurement_gate.json"
    if not gate_path.exists():
        raise SystemExit(
            "Provider-v2 pre-estimation gate is missing; sensitivities are blocked"
        )
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    if gate.get("status") != "PASS":
        raise SystemExit(
            "Provider-v2 pre-estimation gate did not authorize sensitivities"
        )
    core_glob = (
        phase2
        / "analysis_data"
        / "concordance_visit_data_provider_v2"
        / "visit_year=*"
        / "visit_quarter=*"
        / "concordance_visit_core.parquet"
    )
    fact_glob = (
        release
        / "fact_ed_visits"
        / "visit_year=*"
        / "visit_quarter=*"
        / "ed_visits.parquet"
    )
    cpi = (
        phase2
        / "external_sources"
        / "bls_cpi_quarterly_factors_to_2024.csv"
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
    core = f"read_parquet('{qpath(core_glob)}', hive_partitioning=false)"

    cohort_sql = """
        CASE
            WHEN race_primary_eligible_t50_flag = 1
                THEN 'primary_direct_nh_t50'
        END
    """
    filters = {
        "primary_direct_nh_t50": (
            "race_primary_eligible_t50_flag = 1"
        ),
        "direct_plus_unique_license_nh_t50": (
            "race_pair_defined_nh_flag = 1 "
            "AND physician_linkage_method IN "
            "('direct_validated_npi','unique_fl_license_crosswalk') "
            "AND physician_race_imputation_confidence >= 0.50"
        ),
        "race_only_direct_t50": (
            "race_pair_defined_race_only_flag = 1 "
            "AND physician_linkage_method = 'direct_validated_npi' "
            "AND physician_race_imputation_confidence >= 0.50"
        ),
        "primary_min_physician_quarter_volume_50": (
            "race_primary_eligible_t50_flag = 1 "
            "AND attending_quarter_volume_all_ed >= 50"
        ),
        "primary_min_physician_quarter_volume_100": (
            "race_primary_eligible_t50_flag = 1 "
            "AND attending_quarter_volume_all_ed >= 100"
        ),
        "primary_min_physician_quarter_volume_250": (
            "race_primary_eligible_t50_flag = 1 "
            "AND attending_quarter_volume_all_ed >= 250"
        ),
    }
    parts = []
    for cohort_id, condition in filters.items():
        pair_expression = (
            "race_pair_category"
            if cohort_id != "race_only_direct_t50"
            else """
                CASE
                    WHEN physician_race_proxy_primary_label = 'Black'
                     AND patient_race_category = 'Black or African American'
                        THEN 'black_black'
                    WHEN physician_race_proxy_primary_label = 'Black'
                     AND patient_race_category = 'White'
                        THEN 'black_white'
                    WHEN physician_race_proxy_primary_label = 'White'
                     AND patient_race_category = 'Black or African American'
                        THEN 'white_black'
                    WHEN physician_race_proxy_primary_label = 'White'
                     AND patient_race_category = 'White'
                        THEN 'white_white'
                END
            """
        )
        for outcome in OUTCOMES:
            parts.append(
                f"""
                SELECT
                    '{cohort_id}' AS cohort_definition,
                    {pair_expression} AS race_pair_category,
                    '{outcome}' AS outcome,
                    count({outcome}) AS nonmissing_n,
                    avg(cast({outcome} AS DOUBLE)) AS mean,
                    stddev_samp(cast({outcome} AS DOUBLE)) AS sd
                FROM {core}
                WHERE {condition}
                GROUP BY {pair_expression}
                """
            )
    summary = con.execute(
        " UNION ALL ".join(parts)
        + " ORDER BY cohort_definition, outcome, race_pair_category"
    ).fetchdf()
    summary.to_csv(output / "cohort_definition_pair_means.csv", index=False)
    contrasts(summary, "cohort_definition").to_csv(
        output / "cohort_definition_unadjusted_contrasts.csv", index=False
    )

    con.execute(
        f"""
        CREATE OR REPLACE VIEW cpi AS
        SELECT
            year::INTEGER AS visit_year,
            quarter::INTEGER AS visit_quarter,
            series_id,
            factor_to_2024_dollars
        FROM read_csv_auto('{qpath(cpi)}', header=true)
        """
    )
    role_parts = []
    role_outcome_parts = []
    role_fields = {
        "operating_performing": {
            "npi": "operating_performing_selected_npi",
            "selection": "operating_performing_selection_method",
        },
        "other_practitioner": {
            "npi": "other_practitioner_selected_npi",
            "selection": "other_practitioner_selection_method",
        },
    }
    role_outcome_expressions = {
        "los_hours_primary_0_168": """
            CASE
                WHEN arrival_hour BETWEEN 0 AND 23
                 AND try_cast(ed_discharge_hour_raw AS INTEGER) BETWEEN 0 AND 23
                 AND 24.0 * length_of_stay_days
                     + try_cast(ed_discharge_hour_raw AS INTEGER)
                     - arrival_hour BETWEEN 0 AND 168
                THEN 24.0 * length_of_stay_days
                     + try_cast(ed_discharge_hour_raw AS INTEGER)
                     - arrival_hour
            END
        """,
        "total_charge_reported_real_2024": """
            CASE WHEN total_charge_reported >= 0
                 THEN total_charge_reported * c.factor_to_2024_dollars
            END
        """,
        "procedure_count_analysis": (
            "cast(procedure_count_analysis AS DOUBLE)"
        ),
        "any_procedure_flag": "cast(any_procedure_flag AS DOUBLE)",
        "routine_discharge_flag": "cast(routine_discharge_flag AS DOUBLE)",
        "mortality_flag": "cast(mortality_flag AS DOUBLE)",
    }
    for role, fields in role_fields.items():
        pair = f"""
            CASE
                WHEN r.race_proxy_primary_five_class_label = 'Black'
                 AND race_category = 'Black or African American'
                    THEN 'black_black'
                WHEN r.race_proxy_primary_five_class_label = 'Black'
                 AND race_category = 'White'
                    THEN 'black_white'
                WHEN r.race_proxy_primary_five_class_label = 'White'
                 AND race_category = 'Black or African American'
                    THEN 'white_black'
                WHEN r.race_proxy_primary_five_class_label = 'White'
                 AND race_category = 'White'
                    THEN 'white_white'
            END
        """
        role_parts.append(
            f"""
            SELECT
                '{role}' AS physician_role,
                {pair} AS race_pair_category,
                count(*) AS visits,
                count(DISTINCT {fields['npi']}) AS physicians,
                avg(
                    CASE
                        WHEN arrival_hour BETWEEN 0 AND 23
                         AND try_cast(ed_discharge_hour_raw AS INTEGER)
                                BETWEEN 0 AND 23
                         AND 24.0 * length_of_stay_days
                             + try_cast(ed_discharge_hour_raw AS INTEGER)
                             - arrival_hour BETWEEN 0 AND 168
                        THEN 24.0 * length_of_stay_days
                             + try_cast(ed_discharge_hour_raw AS INTEGER)
                             - arrival_hour
                    END
                ) AS los_hours_primary_mean,
                avg(
                    CASE WHEN total_charge_reported >= 0
                         THEN total_charge_reported * c.factor_to_2024_dollars
                    END
                ) AS real_reported_charge_mean,
                avg(any_procedure_flag::DOUBLE) AS any_procedure_rate,
                avg(routine_discharge_flag::DOUBLE) AS routine_discharge_rate,
                avg(mortality_flag::DOUBLE) AS mortality_rate
            FROM read_parquet(
                '{qpath(fact_glob)}', hive_partitioning=false
            ) f
            LEFT JOIN cpi c
              ON f.visit_year = c.visit_year
             AND f.visit_quarter = c.visit_quarter
             AND c.series_id = 'CUUR0000SA0'
            LEFT JOIN provider_master_v2 p
              ON f.{fields['npi']} = p.npi
            LEFT JOIN provider_race_proxy_v2 r
              ON f.{fields['npi']} = r.npi
            WHERE f.visit_year BETWEEN 2010 AND 2024
              AND {fields['selection']} = 'direct_validated_npi'
              AND p.provider_entity_category_v2 = 'Individual'
              AND p.physician_md_do_flag_v2
              AND ethnicity_category = 'Not Hispanic or Latino'
              AND race_category IN ('Black or African American', 'White')
              AND r.race_proxy_primary_five_class_label IN ('Black', 'White')
              AND r.last_match_flag
              AND r.first_match_flag
              AND r.race_proxy_primary_max_probability >= 0.50
            GROUP BY {pair}
            """
        )
        outcome_values = ", ".join(
            f"('{outcome}', cast(({expression}) AS DOUBLE))"
            for outcome, expression in role_outcome_expressions.items()
        )
        role_outcome_parts.append(
            f"""
            SELECT
                '{role}' AS physician_role,
                {pair} AS race_pair_category,
                v.outcome,
                count(*) AS visits,
                count(DISTINCT {fields['npi']}) AS physicians,
                count(v.outcome_value) AS nonmissing_n,
                avg(v.outcome_value) AS mean,
                stddev_samp(v.outcome_value) AS sd
            FROM read_parquet(
                '{qpath(fact_glob)}', hive_partitioning=false
            ) f
            LEFT JOIN cpi c
              ON f.visit_year = c.visit_year
             AND f.visit_quarter = c.visit_quarter
             AND c.series_id = 'CUUR0000SA0'
            LEFT JOIN provider_master_v2 p
              ON f.{fields['npi']} = p.npi
            LEFT JOIN provider_race_proxy_v2 r
              ON f.{fields['npi']} = r.npi
            CROSS JOIN LATERAL (
                VALUES {outcome_values}
            ) v(outcome, outcome_value)
            WHERE f.visit_year BETWEEN 2010 AND 2024
              AND {fields['selection']} = 'direct_validated_npi'
              AND p.provider_entity_category_v2 = 'Individual'
              AND p.physician_md_do_flag_v2
              AND ethnicity_category = 'Not Hispanic or Latino'
              AND race_category IN ('Black or African American', 'White')
              AND r.race_proxy_primary_five_class_label IN ('Black', 'White')
              AND r.last_match_flag
              AND r.first_match_flag
              AND r.race_proxy_primary_max_probability >= 0.50
            GROUP BY {pair}, v.outcome
            """
        )
    alternate_roles = con.execute(
        " UNION ALL ".join(role_parts)
        + " ORDER BY physician_role, race_pair_category"
    ).fetchdf()
    alternate_roles.to_csv(
        output / "alternate_physician_role_pair_summary.csv", index=False
    )
    alternate_role_outcomes = con.execute(
        " UNION ALL ".join(role_outcome_parts)
        + " ORDER BY physician_role, outcome, race_pair_category"
    ).fetchdf()
    alternate_role_outcomes.to_csv(
        output / "alternate_physician_role_outcome_pair_means.csv",
        index=False,
    )
    contrasts(alternate_role_outcomes, "physician_role").to_csv(
        output / "alternate_physician_role_unadjusted_contrasts.csv",
        index=False,
    )
    con.close()
    manifest = {
        "created_utc": now_utc(),
        "status": "PASS",
        "cohort_definitions": list(filters),
        "alternate_roles": list(role_fields),
        "alternate_role_limitations": (
            "Operating/performing and other-practitioner roles are not "
            "interchangeable with the attending role and are descriptive "
            "sensitivities only. Provider master v2 entity/MD/DO rules and "
            "full-name race proxy v2 at the 0.50 threshold are applied by "
            "joining each role-specific selected NPI."
        ),
        "provider_measurement_version": (
            "provider_master_v2_full_name_race_v1"
        ),
        "pre_estimation_gate": str(gate_path),
        "pre_estimation_gate_status": gate["status"],
        "phase1_physician_fields_used_for_alternate_roles": False,
        "adjusted_primary_models_elsewhere": True,
    }
    (output / "additional_cohort_sensitivities_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
