# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/04b_build_physician_race_proxy_v2.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Build an audited Bayesian full-name physician race/ethnicity proxy.

The proxy uses the public first-, middle-, and surname likelihood dictionaries
distributed with wru v2.0.0.  It is a name-only Bayesian proxy and is NOT
labelled BISG because no residential geography is available.  Two priors are
retained:

* primary: Florida active-physician prior derived from the AAMC 2021 State
  Physician Workforce Data Report (2020 counts, normalized to five classes);
* sensitivity: the national 2020 population prior used by wru v2.0.0.

All posterior probabilities and match diagnostics are retained.  Hard labels
are convenience sensitivity measures, never treated as observed race.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RACES = ("white", "black", "hispanic", "asian", "other")
RACE_PROXY_BUILD_SPEC_VERSION = (
    "wru_full_name_provider_master_cms_current_20260626_v1"
)
WRU_SUFFIX = {
    "white": "whi",
    "black": "bla",
    "hispanic": "his",
    "asian": "asi",
    "other": "oth",
}
DISPLAY = {
    "white": "White",
    "black": "Black",
    "hispanic": "Hispanic",
    "asian": "Asian",
    "other": "Other/multiracial",
}

# predict_race_new() 2020 national marginal in wru v2.0.0.
POPULATION_PRIOR = {
    "white": 0.5783619,
    "black": 0.1205021,
    "hispanic": 0.1872988,
    "asian": 0.06106737,
    "other": 0.05276981,
}

# AAMC 2021 report, Florida active physicians in 2020:
# White 29,395; Black 3,451; Hispanic 9,309; Asian 8,524;
# AIAN 188 + NHPI 74 + Other 1,697 = 1,959.  The AAMC categories are
# "alone or in combination"; they are normalized here to a five-class prior.
AAMC_FL_COUNTS = {
    "white": 29_395,
    "black": 3_451,
    "hispanic": 9_309,
    "asian": 8_524,
    "other": 1_959,
}
AAMC_TOTAL_INCLUDED = sum(AAMC_FL_COUNTS.values())
FL_PHYSICIAN_PRIOR = {
    key: value / AAMC_TOTAL_INCLUDED
    for key, value in AAMC_FL_COUNTS.items()
}


def qpath(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace("'", "''")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=False, default=str) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def sha256_file(path: Path, block_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(block_size), b""):
            digest.update(block)
    return digest.hexdigest()


def parquet_valid(con: Any, path: Path) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        con.execute(
            f"SELECT count(*) FROM read_parquet('{qpath(path)}')"
        ).fetchone()
        return True
    except Exception:
        return False


def copy_parquet(con: Any, query: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".partial")
    if temporary.exists():
        temporary.unlink()
    con.execute(
        f"""
        COPY ({query}) TO '{qpath(temporary)}' (
            FORMAT PARQUET,
            COMPRESSION ZSTD,
            ROW_GROUP_SIZE 100000
        )
        """
    )
    if not parquet_valid(con, temporary):
        raise RuntimeError(f"Invalid staged parquet output: {temporary}")
    os.replace(temporary, destination)


def copy_csv(con: Any, query: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".partial")
    if temporary.exists():
        temporary.unlink()
    con.execute(
        f"""
        COPY ({query}) TO '{qpath(temporary)}' (
            FORMAT CSV,
            HEADER TRUE
        )
        """
    )
    if not temporary.exists() or temporary.stat().st_size == 0:
        raise RuntimeError(f"Invalid staged CSV output: {temporary}")
    os.replace(temporary, destination)


def read_rds_frame(pyreadr: Any, path: Path) -> Any:
    result = pyreadr.read_r(str(path))
    if len(result) != 1:
        raise RuntimeError(f"Expected one object in {path}; found {len(result)}")
    return next(iter(result.values()))


def score_expression(prior: dict[str, float], race: str) -> str:
    suffix = WRU_SUFFIX[race]
    pieces = [f"ln({prior[race]:.17g})"]
    for name_type in ("last", "first", "middle"):
        pieces.append(
            "CASE WHEN "
            f"{name_type}_match_flag "
            "THEN ln(greatest("
            f"coalesce(c_{suffix}_{name_type}, 0.0), 1e-300"
            ")) ELSE 0.0 END"
        )
    return " + ".join(pieces)


def posterior_columns(prefix: str) -> str:
    return ",\n".join(
        f"""
        CASE WHEN race_proxy_name_model_applicable_flag
             THEN exp({prefix}_log_{race} - {prefix}_log_max)
                  / nullif({prefix}_denominator, 0)
        END AS {prefix}_prob_{race}
        """.strip()
        for race in RACES
    )


def label_case(prefix: str) -> str:
    values = ", ".join(f"{prefix}_prob_{race}" for race in RACES)
    branches = "\n".join(
        f"""
        WHEN {prefix}_prob_{race} = greatest({values})
            THEN '{DISPLAY[race]}'
        """.strip()
        for race in RACES
    )
    return f"CASE\n{branches}\nEND"


def entropy_expression(prefix: str) -> str:
    terms = [
        (
            f"CASE WHEN {prefix}_prob_{race} > 0 "
            f"THEN -{prefix}_prob_{race} * ln({prefix}_prob_{race}) "
            "ELSE 0 END"
        )
        for race in RACES
    ]
    return "(" + " + ".join(terms) + f") / ln({len(RACES)}.0)"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    parser.add_argument("--temp", required=True, type=Path)
    parser.add_argument("--threads", type=int, default=12)
    parser.add_argument("--memory-limit", default="24GB")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    phase2 = args.phase2.resolve()
    temp = args.temp.resolve()
    dimensions = phase2 / "analysis_data" / "dimensions"
    qa_root = phase2 / "qa"
    source_root = phase2 / "external_sources" / "physician_race"
    wru_root = source_root / "wru_v2.0.0"
    provider_master = dimensions / "provider_master_v2.parquet"
    output = dimensions / "provider_race_proxy_v2.parquet"
    success = dimensions / "provider_race_proxy_v2_SUCCESS.json"

    if success.exists() and not args.force:
        payload = json.loads(success.read_text(encoding="utf-8"))
        if (
            payload.get("qa_passed")
            and payload.get("build_spec_version")
            == RACE_PROXY_BUILD_SPEC_VERSION
            and output.exists()
            and payload.get("provider_master_sha256")
            == sha256_file(provider_master)
        ):
            print(success.read_text(encoding="utf-8"), flush=True)
            return

    pydeps = phase2.parents[1] / "tmp" / phase2.name / "pydeps"
    if pydeps.exists():
        sys.path.insert(0, str(pydeps))
    import duckdb  # noqa: PLC0415
    import pyreadr  # noqa: PLC0415

    dictionaries = {
        "last": wru_root / "wru-data-last_c.rds",
        "first": wru_root / "wru-data-first_c.rds",
        "middle": wru_root / "wru-data-mid_c.rds",
        "census_last": wru_root / "wru-data-census_last_c.rds",
    }
    aamc_pdf = source_root / "AAMC_2021_State_Physician_Workforce_Data_Report.pdf"
    missing = [
        str(path)
        for path in (provider_master, *dictionaries.values(), aamc_pdf)
        if not path.exists()
    ]
    if missing:
        raise FileNotFoundError(
            "Missing physician-race inputs:\n" + "\n".join(missing)
        )
    provider_master_sha256 = sha256_file(provider_master)

    temp.mkdir(parents=True, exist_ok=True)
    duck_temp = temp / "duckdb_temp"
    duck_temp.mkdir(parents=True, exist_ok=True)
    dimensions.mkdir(parents=True, exist_ok=True)
    qa_root.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    con.execute(f"SET threads={max(1, args.threads)}")
    con.execute(f"SET memory_limit='{args.memory_limit}'")
    con.execute(f"SET temp_directory='{qpath(duck_temp)}'")
    con.execute("SET preserve_insertion_order=false")

    print("1/7 Loading official wru v2.0.0 name likelihoods", flush=True)
    frames = {
        name_type: read_rds_frame(pyreadr, path)
        for name_type, path in dictionaries.items()
        if name_type != "census_last"
    }
    for name_type, frame in frames.items():
        con.register(f"{name_type}_dictionary_frame", frame)
        suffix = name_type if name_type != "middle" else "middle"
        name_col = (
            "last_name"
            if name_type == "last"
            else "first_name"
            if name_type == "first"
            else "middle_name"
        )
        select_probs = ", ".join(
            f"try_cast(c_{WRU_SUFFIX[race]}_{suffix} AS DOUBLE) "
            f"AS c_{WRU_SUFFIX[race]}"
            for race in RACES
        )
        con.execute(
            f"""
            CREATE OR REPLACE TEMP TABLE dict_{name_type} AS
            SELECT
                upper(trim({name_col})) AS name_key,
                {select_probs}
            FROM {name_type}_dictionary_frame
            WHERE nullif(trim({name_col}), '') IS NOT NULL
            QUALIFY row_number() OVER (
                PARTITION BY upper(trim({name_col}))
                ORDER BY upper(trim({name_col}))
            ) = 1
            """
        )

    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE name_dictionary AS
        SELECT 'last'::VARCHAR AS name_type, * FROM dict_last
        UNION ALL
        SELECT 'first'::VARCHAR, * FROM dict_first
        UNION ALL
        SELECT 'middle'::VARCHAR, * FROM dict_middle
        """
    )
    likelihood_checks = con.execute(
        """
        SELECT
            name_type,
            count(*) AS names,
            sum(c_whi) AS sum_white,
            sum(c_bla) AS sum_black,
            sum(c_his) AS sum_hispanic,
            sum(c_asi) AS sum_asian,
            sum(c_oth) AS sum_other,
            count(*) FILTER (
                WHERE least(c_whi, c_bla, c_his, c_asi, c_oth) < 0
                   OR greatest(c_whi, c_bla, c_his, c_asi, c_oth) > 1
            ) AS out_of_bounds_rows
        FROM name_dictionary
        GROUP BY name_type
        ORDER BY name_type
        """
    ).fetchall()
    bad_likelihood_rows = sum(int(row[7]) for row in likelihood_checks)
    if bad_likelihood_rows:
        raise RuntimeError(
            f"Name dictionaries contain {bad_likelihood_rows} invalid rows"
        )

    con.execute(
        f"""
        CREATE OR REPLACE VIEW provider_master AS
        SELECT * FROM read_parquet('{qpath(provider_master)}')
        """
    )
    print("2/7 Applying the documented wru name-cleaning cascade", flush=True)
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE provider_name_long AS
        SELECT
            npi,
            provider_entity_category_v2,
            ed_observed_flag,
            physician_md_do_flag_v2,
            ed_attending_visit_count,
            'last'::VARCHAR AS name_type,
            nullif(upper(trim(last_name_v2)), '') AS raw_name
        FROM provider_master
        UNION ALL
        SELECT
            npi,
            provider_entity_category_v2,
            ed_observed_flag,
            physician_md_do_flag_v2,
            ed_attending_visit_count,
            'first'::VARCHAR,
            nullif(upper(trim(first_name_v2)), '')
        FROM provider_master
        UNION ALL
        SELECT
            npi,
            provider_entity_category_v2,
            ed_observed_flag,
            physician_md_do_flag_v2,
            ed_attending_visit_count,
            'middle'::VARCHAR,
            nullif(upper(trim(middle_name_v2)), '')
        FROM provider_master
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE name_candidates AS
        WITH base AS (
            SELECT
                *,
                nullif(
                    trim(regexp_replace(raw_name, '[^A-Z0-9 ]', '', 'g')),
                    ''
                ) AS punctuation_removed,
                regexp_replace(
                    coalesce(
                        nullif(
                            trim(
                                regexp_replace(
                                    raw_name,
                                    '[^A-Z0-9 ]',
                                    '',
                                    'g'
                                )
                            ),
                            ''
                        ),
                        ''
                    ),
                    ' ',
                    '',
                    'g'
                ) AS spaces_removed,
                regexp_replace(
                    coalesce(raw_name, ''),
                    '[- ]+',
                    ' ',
                    'g'
                ) AS tokenized
            FROM provider_name_long
        ),
        candidates AS (
            SELECT *, 1::UTINYINT AS match_priority,
                   'raw uppercase'::VARCHAR AS cleaning_method,
                   raw_name AS candidate
            FROM base
            UNION ALL
            SELECT *, 2::UTINYINT, 'punctuation removed',
                   punctuation_removed
            FROM base
            UNION ALL
            SELECT *, 3::UTINYINT, 'spaces removed',
                   nullif(spaces_removed, '')
            FROM base
            UNION ALL
            SELECT
                *,
                4::UTINYINT,
                'surname suffix removed',
                CASE
                    WHEN name_type <> 'last' THEN NULL
                    WHEN length(spaces_removed) >= 7
                     AND right(spaces_removed, 2) = 'SR'
                        THEN left(
                            spaces_removed,
                            length(spaces_removed) - 2
                        )
                    ELSE nullif(
                        regexp_replace(
                            spaces_removed,
                            '(JUNIOR|SENIOR|THIRD|III|JR|II|IV)$',
                            ''
                        ),
                        ''
                    )
                END
            FROM base
            UNION ALL
            SELECT *, 5::UTINYINT, 'first compound-name token',
                   nullif(split_part(tokenized, ' ', 1), '')
            FROM base
            UNION ALL
            SELECT *, 6::UTINYINT, 'second compound-name token',
                   nullif(split_part(tokenized, ' ', 2), '')
            FROM base
        )
        SELECT DISTINCT
            npi,
            name_type,
            raw_name,
            match_priority,
            cleaning_method,
            candidate
        FROM candidates
        WHERE candidate IS NOT NULL
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE name_matches AS
        SELECT
            c.npi,
            c.name_type,
            c.raw_name,
            c.candidate AS matched_name,
            c.match_priority,
            c.cleaning_method,
            d.c_whi,
            d.c_bla,
            d.c_his,
            d.c_asi,
            d.c_oth
        FROM name_candidates c
        INNER JOIN name_dictionary d
          ON c.name_type = d.name_type
         AND c.candidate = d.name_key
        QUALIFY row_number() OVER (
            PARTITION BY c.npi, c.name_type
            ORDER BY c.match_priority, c.candidate
        ) = 1
        """
    )

    print("3/7 Computing five-class posteriors under both priors", flush=True)
    component_select: list[str] = []
    for name_type in ("last", "first", "middle"):
        component_select.extend(
            [
                (
                    f"max(raw_name) FILTER (WHERE name_type = '{name_type}') "
                    f"AS {name_type}_name_raw"
                ),
                (
                    f"max(matched_name) FILTER (WHERE name_type = '{name_type}') "
                    f"AS {name_type}_name_matched"
                ),
                (
                    "max(cleaning_method) FILTER "
                    f"(WHERE name_type = '{name_type}') "
                    f"AS {name_type}_name_cleaning_method"
                ),
                (
                    "max(match_priority) FILTER "
                    f"(WHERE name_type = '{name_type}') "
                    f"AS {name_type}_name_match_priority"
                ),
            ]
        )
        for race in RACES:
            suffix = WRU_SUFFIX[race]
            component_select.append(
                f"max(c_{suffix}) FILTER "
                f"(WHERE name_type = '{name_type}') "
                f"AS c_{suffix}_{name_type}"
            )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE matched_components AS
        SELECT
            npi,
            {", ".join(component_select)}
        FROM name_matches
        GROUP BY npi
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE race_components AS
        SELECT
            p.npi,
            p.provider_entity_category_v2,
            p.ed_observed_flag,
            p.physician_md_do_flag_v2,
            p.ed_attending_visit_count,
            p.last_name_v2,
            p.first_name_v2,
            p.middle_name_v2,
            p.surname_prob_white AS phase1_surname_prob_white,
            p.surname_prob_black AS phase1_surname_prob_black,
            p.surname_prob_hispanic AS phase1_surname_prob_hispanic,
            p.surname_prob_api AS phase1_surname_prob_asian_pi,
            p.surname_prob_aian AS phase1_surname_prob_aian,
            p.surname_prob_multiracial AS phase1_surname_prob_multiracial,
            m.* EXCLUDE (npi),
            m.last_name_matched IS NOT NULL AS last_match_flag,
            m.first_name_matched IS NOT NULL AS first_match_flag,
            m.middle_name_matched IS NOT NULL AS middle_match_flag,
            (
                p.provider_entity_category_v2 = 'Individual'
                AND (
                    m.last_name_matched IS NOT NULL
                    OR m.first_name_matched IS NOT NULL
                    OR m.middle_name_matched IS NOT NULL
                )
            ) AS race_proxy_name_model_applicable_flag,
            (
                (m.last_name_matched IS NOT NULL)::INTEGER
                + (m.first_name_matched IS NOT NULL)::INTEGER
                + (m.middle_name_matched IS NOT NULL)::INTEGER
            )::UTINYINT AS matched_name_component_count
        FROM provider_master p
        LEFT JOIN matched_components m ON p.npi = m.npi
        """
    )
    population_scores = ",\n".join(
        f"{score_expression(POPULATION_PRIOR, race)} "
        f"AS population_log_{race}"
        for race in RACES
    )
    physician_scores = ",\n".join(
        f"{score_expression(FL_PHYSICIAN_PRIOR, race)} "
        f"AS fl_physician_log_{race}"
        for race in RACES
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE race_log_scores AS
        SELECT
            *,
            {population_scores},
            {physician_scores},
            (
                (last_match_flag AND (
                    coalesce(c_whi_last, 0) = 0
                    OR coalesce(c_bla_last, 0) = 0
                    OR coalesce(c_his_last, 0) = 0
                    OR coalesce(c_asi_last, 0) = 0
                    OR coalesce(c_oth_last, 0) = 0
                ))
                OR (first_match_flag AND (
                    coalesce(c_whi_first, 0) = 0
                    OR coalesce(c_bla_first, 0) = 0
                    OR coalesce(c_his_first, 0) = 0
                    OR coalesce(c_asi_first, 0) = 0
                    OR coalesce(c_oth_first, 0) = 0
                ))
                OR (middle_match_flag AND (
                    coalesce(c_whi_middle, 0) = 0
                    OR coalesce(c_bla_middle, 0) = 0
                    OR coalesce(c_his_middle, 0) = 0
                    OR coalesce(c_asi_middle, 0) = 0
                    OR coalesce(c_oth_middle, 0) = 0
                ))
            ) AS numerical_likelihood_floor_applied_flag
        FROM race_components
        """
    )
    for prefix in ("population", "fl_physician"):
        logs = ", ".join(f"{prefix}_log_{race}" for race in RACES)
        exponentials = " + ".join(
            f"exp({prefix}_log_{race} - {prefix}_log_max)"
            for race in RACES
        )
        con.execute(
            f"""
            CREATE OR REPLACE TEMP TABLE race_scores_{prefix} AS
            SELECT
                *,
                greatest({logs}) AS {prefix}_log_max
            FROM race_log_scores
            """
        )
        con.execute(
            f"""
            CREATE OR REPLACE TEMP TABLE race_denominator_{prefix} AS
            SELECT
                *,
                {exponentials} AS {prefix}_denominator
            FROM race_scores_{prefix}
            """
        )
        con.execute(
            f"""
            CREATE OR REPLACE TEMP TABLE race_posterior_{prefix} AS
            SELECT
                *,
                {posterior_columns(prefix)}
            FROM race_denominator_{prefix}
            """
        )

    # Both posterior tables start from the same component table.  Join only
    # the sensitivity posterior columns back to the primary table.
    pop_cols = ", ".join(
        f"pop.population_prob_{race}" for race in RACES
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE race_posteriors AS
        SELECT
            fl.*,
            {pop_cols}
        FROM race_posterior_fl_physician fl
        INNER JOIN race_posterior_population pop USING (npi)
        """
    )
    fl_label = label_case("fl_physician")
    population_label = label_case("population")
    fl_probs = ", ".join(f"fl_physician_prob_{race}" for race in RACES)
    population_probs = ", ".join(
        f"population_prob_{race}" for race in RACES
    )
    max_prior_difference = ", ".join(
        f"abs(fl_physician_prob_{race} - population_prob_{race})"
        for race in RACES
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE provider_race_proxy_v2_stage AS
        SELECT
            *,
            '{AAMC_TOTAL_INCLUDED}'::INTEGER
                AS fl_physician_prior_included_count,
            'AAMC Florida active physicians, 2020; alone-or-in-combination '
            'categories normalized to five classes'
                AS fl_physician_prior_source,
            'wru v2.0.0 predict_race_new 2020 national race marginal'
                AS population_prior_source,
            'wru_name_likelihoods_aamc_fl_physician_prior_v1'
                AS race_proxy_primary_method_id,
            'Bayesian full-name proxy without residential geography; not BISG'
                AS race_proxy_method_label,
            {fl_label} AS race_proxy_primary_five_class_label,
            greatest({fl_probs})
                AS race_proxy_primary_max_probability,
            fl_physician_prob_black + fl_physician_prob_white
                AS race_proxy_primary_black_white_mass,
            fl_physician_prob_black
                / nullif(
                    fl_physician_prob_black + fl_physician_prob_white,
                    0
                ) AS race_proxy_primary_prob_black_conditional_bw,
            CASE
                WHEN fl_physician_prob_black >= fl_physician_prob_white
                    THEN 'Black'
                ELSE 'White'
            END AS race_proxy_primary_black_white_label,
            {entropy_expression("fl_physician")}
                AS race_proxy_primary_normalized_entropy,
            {population_label} AS race_proxy_population_five_class_label,
            greatest({population_probs})
                AS race_proxy_population_max_probability,
            population_prob_black + population_prob_white
                AS race_proxy_population_black_white_mass,
            population_prob_black
                / nullif(population_prob_black + population_prob_white, 0)
                AS race_proxy_population_prob_black_conditional_bw,
            {entropy_expression("population")}
                AS race_proxy_population_normalized_entropy,
            greatest({max_prior_difference})
                AS race_proxy_max_probability_difference_between_priors,
            ({fl_label}) <> ({population_label})
                AS race_proxy_label_disagrees_between_priors_flag,
            CASE
                WHEN provider_entity_category_v2 <> 'Individual'
                    THEN 'not_applicable_nonindividual_entity'
                WHEN last_match_flag AND first_match_flag AND middle_match_flag
                    THEN 'last_first_middle_matched'
                WHEN last_match_flag AND first_match_flag
                    THEN 'last_first_matched_middle_unavailable_or_unmatched'
                WHEN last_match_flag
                    THEN 'surname_only_match'
                WHEN first_match_flag OR middle_match_flag
                    THEN 'given_name_only_match'
                ELSE 'no_name_dictionary_match'
            END AS race_proxy_name_match_pattern,
            (
                provider_entity_category_v2 = 'Individual'
                AND physician_md_do_flag_v2
                AND last_match_flag
                AND first_match_flag
                AND ({fl_label}) IN ('Black', 'White')
                AND greatest({fl_probs}) >= 0.50
            ) AS race_proxy_primary_eligible_t50_flag,
            (
                provider_entity_category_v2 = 'Individual'
                AND physician_md_do_flag_v2
                AND last_match_flag
                AND first_match_flag
                AND ({fl_label}) IN ('Black', 'White')
                AND greatest({fl_probs}) >= 0.70
            ) AS race_proxy_primary_eligible_t70_flag,
            (
                provider_entity_category_v2 = 'Individual'
                AND physician_md_do_flag_v2
                AND last_match_flag
                AND first_match_flag
                AND ({fl_label}) IN ('Black', 'White')
                AND greatest({fl_probs}) >= 0.80
            ) AS race_proxy_primary_eligible_t80_flag,
            (
                provider_entity_category_v2 = 'Individual'
                AND physician_md_do_flag_v2
                AND last_match_flag
                AND first_match_flag
                AND ({fl_label}) IN ('Black', 'White')
                AND greatest({fl_probs}) >= 0.90
            ) AS race_proxy_primary_eligible_t90_flag,
            'Algorithm-inferred analytical proxy; not self-identified race '
            'and not suitable for individual-level reporting'
                AS race_proxy_interpretation_limit,
            TIMESTAMP '2026-07-26 00:00:00'
                AS race_proxy_v2_build_date
        FROM race_posteriors
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE provider_race_proxy_v2 AS
        SELECT *
        FROM provider_race_proxy_v2_stage
        QUALIFY row_number() OVER (PARTITION BY npi ORDER BY npi) = 1
        """
    )

    print("4/7 Exporting the one-row-per-NPI probability file", flush=True)
    copy_parquet(
        con,
        "SELECT * FROM provider_race_proxy_v2 ORDER BY npi",
        output,
    )

    print("5/7 Writing name-match and prior-sensitivity QA", flush=True)
    copy_csv(
        con,
        """
        SELECT
            race_proxy_name_match_pattern,
            ed_observed_flag,
            physician_md_do_flag_v2,
            count(*)::UBIGINT AS distinct_npis,
            sum(ed_attending_visit_count)::UBIGINT AS attending_visits,
            avg(race_proxy_primary_max_probability)
                AS mean_primary_max_probability,
            avg(race_proxy_primary_normalized_entropy)
                AS mean_primary_normalized_entropy
        FROM provider_race_proxy_v2
        GROUP BY ALL
        ORDER BY ed_observed_flag DESC, physician_md_do_flag_v2 DESC,
                 race_proxy_name_match_pattern
        """,
        qa_root / "provider_race_proxy_v2_name_match_coverage.csv",
    )
    copy_csv(
        con,
        """
        SELECT
            race_proxy_primary_five_class_label AS primary_label,
            race_proxy_population_five_class_label AS population_prior_label,
            count(*)::UBIGINT AS distinct_npis,
            sum(ed_attending_visit_count)::UBIGINT AS attending_visits,
            avg(race_proxy_primary_max_probability)
                AS mean_primary_max_probability,
            avg(race_proxy_max_probability_difference_between_priors)
                AS mean_max_probability_difference
        FROM provider_race_proxy_v2
        WHERE ed_observed_flag
          AND physician_md_do_flag_v2
          AND last_match_flag
          AND first_match_flag
        GROUP BY ALL
        ORDER BY primary_label, population_prior_label
        """,
        qa_root / "provider_race_proxy_v2_prior_sensitivity.csv",
    )
    copy_csv(
        con,
        f"""
        SELECT * FROM (
            VALUES
                ('white', {AAMC_FL_COUNTS['white']},
                 {FL_PHYSICIAN_PRIOR['white']:.17g}),
                ('black', {AAMC_FL_COUNTS['black']},
                 {FL_PHYSICIAN_PRIOR['black']:.17g}),
                ('hispanic', {AAMC_FL_COUNTS['hispanic']},
                 {FL_PHYSICIAN_PRIOR['hispanic']:.17g}),
                ('asian', {AAMC_FL_COUNTS['asian']},
                 {FL_PHYSICIAN_PRIOR['asian']:.17g}),
                ('other', {AAMC_FL_COUNTS['other']},
                 {FL_PHYSICIAN_PRIOR['other']:.17g})
        ) AS t(race_class, aamc_count, normalized_prior)
        """,
        qa_root / "provider_race_proxy_v2_primary_prior.csv",
    )

    master_rows = int(
        con.execute("SELECT count(*) FROM provider_master").fetchone()[0]
    )
    output_rows = int(
        con.execute(
            "SELECT count(*) FROM provider_race_proxy_v2"
        ).fetchone()[0]
    )
    duplicate_npis = int(
        con.execute(
            """
            SELECT count(*) FROM (
                SELECT npi
                FROM provider_race_proxy_v2
                GROUP BY npi
                HAVING count(*) > 1
            )
            """
        ).fetchone()[0]
    )
    probability_error = con.execute(
        """
        SELECT
            max(abs(
                fl_physician_prob_white
                + fl_physician_prob_black
                + fl_physician_prob_hispanic
                + fl_physician_prob_asian
                + fl_physician_prob_other
                - 1.0
            )),
            max(abs(
                population_prob_white
                + population_prob_black
                + population_prob_hispanic
                + population_prob_asian
                + population_prob_other
                - 1.0
            )),
            count(*) FILTER (
                WHERE least(
                    fl_physician_prob_white,
                    fl_physician_prob_black,
                    fl_physician_prob_hispanic,
                    fl_physician_prob_asian,
                    fl_physician_prob_other,
                    population_prob_white,
                    population_prob_black,
                    population_prob_hispanic,
                    population_prob_asian,
                    population_prob_other
                ) < 0
                   OR greatest(
                    fl_physician_prob_white,
                    fl_physician_prob_black,
                    fl_physician_prob_hispanic,
                    fl_physician_prob_asian,
                    fl_physician_prob_other,
                    population_prob_white,
                    population_prob_black,
                    population_prob_hispanic,
                    population_prob_asian,
                    population_prob_other
                ) > 1
            )
        FROM provider_race_proxy_v2
        WHERE race_proxy_name_model_applicable_flag
        """
    ).fetchone()
    ed_md_do_stats = con.execute(
        """
        SELECT
            count(*) AS npis,
            count(*) FILTER (
                WHERE last_match_flag AND first_match_flag
            ) AS last_first_matched_npis,
            count(*) FILTER (
                WHERE race_proxy_primary_eligible_t50_flag
            ) AS eligible_t50_npis,
            count(*) FILTER (
                WHERE race_proxy_primary_eligible_t70_flag
            ) AS eligible_t70_npis,
            sum(ed_attending_visit_count) AS attending_visits,
            sum(ed_attending_visit_count) FILTER (
                WHERE last_match_flag AND first_match_flag
            ) AS last_first_matched_attending_visits,
            sum(ed_attending_visit_count) FILTER (
                WHERE race_proxy_primary_eligible_t50_flag
            ) AS eligible_t50_attending_visits,
            sum(ed_attending_visit_count) FILTER (
                WHERE race_proxy_primary_eligible_t70_flag
            ) AS eligible_t70_attending_visits
        FROM provider_race_proxy_v2
        WHERE ed_observed_flag AND physician_md_do_flag_v2
        """
    ).fetchone()
    prior_disagreement = con.execute(
        """
        SELECT
            count(*) FILTER (
                WHERE race_proxy_label_disagrees_between_priors_flag
            ),
            avg(race_proxy_max_probability_difference_between_priors)
        FROM provider_race_proxy_v2
        WHERE ed_observed_flag
          AND physician_md_do_flag_v2
          AND last_match_flag
          AND first_match_flag
        """
    ).fetchone()

    metrics = {
        "master_rows": master_rows,
        "race_proxy_rows": output_rows,
        "duplicate_npis": duplicate_npis,
        "max_primary_probability_sum_error": float(
            probability_error[0] or 0
        ),
        "max_population_probability_sum_error": float(
            probability_error[1] or 0
        ),
        "out_of_bounds_probability_rows": int(probability_error[2]),
        "ed_observed_md_do_npis": int(ed_md_do_stats[0]),
        "ed_observed_md_do_last_first_matched_npis": int(ed_md_do_stats[1]),
        "ed_observed_md_do_eligible_t50_npis": int(ed_md_do_stats[2]),
        "ed_observed_md_do_eligible_t70_npis": int(ed_md_do_stats[3]),
        "ed_observed_md_do_attending_visits": int(ed_md_do_stats[4] or 0),
        "ed_observed_md_do_last_first_matched_attending_visits": int(
            ed_md_do_stats[5] or 0
        ),
        "ed_observed_md_do_eligible_t50_attending_visits": int(
            ed_md_do_stats[6] or 0
        ),
        "ed_observed_md_do_eligible_t70_attending_visits": int(
            ed_md_do_stats[7] or 0
        ),
        "prior_label_disagreement_npis": int(prior_disagreement[0] or 0),
        "mean_max_probability_difference_between_priors": float(
            prior_disagreement[1] or 0
        ),
        "likelihood_dictionary_checks": [
            {
                "name_type": row[0],
                "names": int(row[1]),
                "sum_white": float(row[2]),
                "sum_black": float(row[3]),
                "sum_hispanic": float(row[4]),
                "sum_asian": float(row[5]),
                "sum_other": float(row[6]),
                "out_of_bounds_rows": int(row[7]),
            }
            for row in likelihood_checks
        ],
        "primary_prior": FL_PHYSICIAN_PRIOR,
        "population_prior_sensitivity": POPULATION_PRIOR,
        "primary_method_id": (
            "wru_name_likelihoods_aamc_fl_physician_prior_v1"
        ),
        "method_label": (
            "Bayesian full-name proxy without residential geography; not BISG"
        ),
        "interpretation": (
            "Algorithm-inferred probabilities, not self-identified physician "
            "race/ethnicity."
        ),
        "completed_utc": utc_now(),
    }
    metrics["qa_passed"] = (
        master_rows == output_rows
        and duplicate_npis == 0
        and metrics["max_primary_probability_sum_error"] <= 1e-10
        and metrics["max_population_probability_sum_error"] <= 1e-10
        and metrics["out_of_bounds_probability_rows"] == 0
        and metrics["ed_observed_md_do_last_first_matched_npis"] > 0
    )
    metrics["build_spec_version"] = RACE_PROXY_BUILD_SPEC_VERSION
    metrics["provider_master_sha256"] = provider_master_sha256
    atomic_json(qa_root / "provider_race_proxy_v2_qa.json", metrics)

    schema_rows = con.execute(
        "DESCRIBE SELECT * FROM provider_race_proxy_v2"
    ).fetchall()
    atomic_json(
        dimensions / "provider_race_proxy_v2_schema.json",
        {
            "dataset": "provider_race_proxy_v2.parquet",
            "grain": "one row per provider_master_v2 NPI",
            "column_count": len(schema_rows),
            "columns": [
                {
                    "name": row[0],
                    "duckdb_type": row[1],
                    "nullable": row[2],
                }
                for row in schema_rows
            ],
            "primary_method": metrics["primary_method_id"],
            "interpretation_limit": metrics["interpretation"],
        },
    )

    print("6/7 Capturing race-proxy source provenance", flush=True)
    manifest_sources: dict[str, Any] = {}
    for label, path in dictionaries.items():
        stat = path.stat()
        manifest_sources[label] = {
            "path": str(path.resolve()),
            "bytes": stat.st_size,
            "sha256": sha256_file(path),
        }
    manifest_sources["aamc_report"] = {
        "path": str(aamc_pdf.resolve()),
        "bytes": aamc_pdf.stat().st_size,
        "sha256": sha256_file(aamc_pdf),
        "url": (
            "https://store.aamc.org/downloadable/download/link/id/"
            "MC4wNjY0MDkwMCAxNzAwNDk0MzA5MjA5ODI2Nzg5ODQ3NTE0MzA%2C/"
        ),
        "extracted_florida_2020_counts": AAMC_FL_COUNTS,
        "category_warning": (
            "AAMC reports race/ethnicity alone or in combination, so categories "
            "are not strictly mutually exclusive. Counts were normalized to "
            "form a transparent five-class target-population prior and are "
            "tested against the wru national prior."
        ),
    }
    atomic_json(
        qa_root / "provider_race_proxy_v2_source_manifest.json",
        {
            "created_utc": utc_now(),
            "build_spec_version": RACE_PROXY_BUILD_SPEC_VERSION,
            "provider_master": {
                "path": str(provider_master.resolve()),
                "bytes": provider_master.stat().st_size,
                "sha256": provider_master_sha256,
            },
            "wru_release": "v2.0.0",
            "wru_repository": "https://github.com/kosukeimai/wru",
            "method": metrics["method_label"],
            "sources": manifest_sources,
            "probability_formula": (
                "posterior_r proportional to prior_r multiplied by each "
                "available matched P(name component | race); unmatched "
                "components contribute a neutral factor of one; a 1e-300 "
                "computational floor is used for exact zero likelihoods."
            ),
            "not_used_as_residential_geography": (
                "NPPES practice ZIP is a business address and was not used in "
                "the primary name-only model."
            ),
        },
    )

    print("7/7 Finalizing physician race proxy v2", flush=True)
    if not metrics["qa_passed"]:
        raise RuntimeError(
            "Provider race proxy v2 failed QA; see "
            "provider_race_proxy_v2_qa.json"
        )
    success_payload = {
        "qa_passed": True,
        "build_spec_version": RACE_PROXY_BUILD_SPEC_VERSION,
        "provider_master_sha256": provider_master_sha256,
        "completed_utc": utc_now(),
        "output": str(output),
        "metrics": metrics,
    }
    atomic_json(success, success_payload)
    print(json.dumps(success_payload, indent=2), flush=True)


if __name__ == "__main__":
    main()
