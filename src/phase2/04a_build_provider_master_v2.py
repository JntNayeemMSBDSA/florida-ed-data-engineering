# Sanitized portfolio copy of the validated production script.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/04a_build_provider_master_v2.py
# All private inputs, outputs, and scratch locations are command-line parameters.

"""Build the encounter-universe provider master used by Phase 2.

This script does not modify the immutable Phase 1 release.  It expands the
Phase 1 provider universe to every checksum-validated NPI observed in any
Florida ED practitioner role, attaches the current NPPES snapshot, refreshes
CMS Doctors and Clinicians attributes plus facility affiliations from the
June 26, 2026 files while retaining legacy CMS/Florida DOH enrichments, and
constructs encounter-year provider volume and observed facility-affiliation
files.

Current NPPES/CMS/DOH attributes are deliberately labelled cross-sectional.
Neither CMS public-reporting facility affiliation nor Florida DOH privilege
data are assumed to represent encounter-year employment. Only ED-observed
provider/facility/year relationships are treated as encounter-year activity.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROVIDER_MASTER_BUILD_SPEC_VERSION = "provider_master_v2_cms_current_20260626_v1"
CMS_CURRENT_GENDER_SOURCE = (
    "CMS Doctors and Clinicians June 2026 current snapshot"
)


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


def sha256_file(path: Path, block_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(block_size), b""):
            digest.update(block)
    return digest.hexdigest()


def valid_npi(value: object) -> bool:
    if value is None:
        return False
    text = re.sub(r"\D", "", str(value))
    if len(text) != 10 or text == "9999999999":
        return False
    digits = [int(char) for char in "80840" + text]
    total = sum(digits[-1::-2])
    for digit in digits[-2::-2]:
        total += sum(divmod(2 * digit, 10))
    return total % 10 == 0


def source_record(path: Path, hash_file: bool) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "bytes": stat.st_size,
        "modified_utc": datetime.fromtimestamp(
            stat.st_mtime, timezone.utc
        ).isoformat(),
        "sha256": sha256_file(path) if hash_file else None,
        "hash_status": "computed" if hash_file else "not_computed",
    }


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


def parquet_nonempty(con: Any, path: Path) -> bool:
    if not parquet_valid(con, path):
        return False
    try:
        return bool(
            con.execute(
                f"SELECT count(*) > 0 FROM read_parquet('{qpath(path)}')"
            ).fetchone()[0]
        )
    except Exception:
        return False


def copy_parquet(
    con: Any,
    query: str,
    destination: Path,
    *,
    row_group_size: int = 100_000,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".partial")
    if temporary.exists():
        temporary.unlink()
    con.execute(
        f"""
        COPY ({query}) TO '{qpath(temporary)}' (
            FORMAT PARQUET,
            COMPRESSION ZSTD,
            ROW_GROUP_SIZE {row_group_size}
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    parser.add_argument("--release", required=True, type=Path)
    parser.add_argument("--dictionary-root", required=True, type=Path)
    parser.add_argument("--temp", required=True, type=Path)
    parser.add_argument("--threads", type=int, default=12)
    parser.add_argument("--memory-limit", default="24GB")
    parser.add_argument("--hash-large-sources", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--rebuild-final-from-cache",
        action="store_true",
        help="Rebuild final master/QA while reusing validated scan caches.",
    )
    args = parser.parse_args()

    phase2 = args.phase2.resolve()
    release = args.release.resolve()
    dictionary = args.dictionary_root.resolve()
    temp = args.temp.resolve()
    dimensions = phase2 / "analysis_data" / "dimensions"
    qa_root = phase2 / "qa"
    docs_root = phase2 / "documentation"
    success = dimensions / "provider_master_v2_SUCCESS.json"
    master_out = dimensions / "provider_master_v2.parquet"
    year_out = dimensions / "provider_year_v2.parquet"
    facility_year_out = dimensions / "provider_facility_year_v2.parquet"

    if (
        success.exists()
        and not args.force
        and not args.rebuild_final_from_cache
    ):
        payload = json.loads(success.read_text(encoding="utf-8"))
        required = (master_out, year_out, facility_year_out)
        if (
            payload.get("qa_passed")
            and payload.get("build_spec_version")
            == PROVIDER_MASTER_BUILD_SPEC_VERSION
            and all(path.exists() for path in required)
        ):
            print(success.read_text(encoding="utf-8"), flush=True)
            return

    pydeps = phase2.parents[1] / "tmp" / phase2.name / "pydeps"
    if pydeps.exists():
        sys.path.insert(0, str(pydeps))
    import duckdb  # noqa: PLC0415

    phase1_master = release / "dimensions" / "physician_master.parquet"
    fact_glob = (
        release
        / "fact_ed_visits"
        / "visit_year=*"
        / "visit_quarter=*"
        / "ed_visits.parquet"
    )
    nppes_minimal = (
        dictionary
        / "Physician"
        / "_derived_master_decoder"
        / "nppes_base_minimal.parquet"
    )
    nppes_dir = (
        dictionary
        / "Physician"
        / "NPPES_Data_Dissemination_February_2026_V2"
    )
    nppes_candidates = sorted(
        path
        for path in nppes_dir.glob("npidata_pfile_*.csv")
        if "fileheader" not in path.name.lower()
    )
    taxonomy = dictionary / "Sample05Q1ED" / "nucc_taxonomy_250.csv"
    cms_current_root = (
        dictionary / "Physician" / "theme_doctors-clinicians_current"
    )
    cms_current = cms_current_root / "DAC_NationalDownloadableFile.csv"
    cms_facility_affiliation = (
        cms_current_root / "Facility_Affiliation.csv"
    )
    cms_current_manifest = cms_current_root / "manifest.json"
    required_sources = (
        phase1_master,
        nppes_minimal,
        taxonomy,
        cms_current,
        cms_facility_affiliation,
        cms_current_manifest,
    )
    missing = [str(path) for path in required_sources if not path.exists()]
    if not nppes_candidates:
        missing.append(str(nppes_dir / "npidata_pfile_*.csv"))
    if missing:
        raise FileNotFoundError("Missing provider inputs:\n" + "\n".join(missing))
    nppes_full = nppes_candidates[-1]

    dimensions.mkdir(parents=True, exist_ok=True)
    qa_root.mkdir(parents=True, exist_ok=True)
    docs_root.mkdir(parents=True, exist_ok=True)
    temp.mkdir(parents=True, exist_ok=True)
    duck_temp = temp / "duckdb_temp"
    duck_temp.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    con.create_function(
        "npi_checksum_valid",
        valid_npi,
        ["VARCHAR"],
        "BOOLEAN",
        null_handling="special",
    )
    con.execute(f"SET threads={max(1, args.threads)}")
    con.execute(f"SET memory_limit='{args.memory_limit}'")
    con.execute(f"SET temp_directory='{qpath(duck_temp)}'")
    con.execute("SET preserve_insertion_order=false")

    role_cache = temp / "provider_quarter_facility_role.parquet"
    if args.force or not parquet_nonempty(con, role_cache):
        print("1/8 Aggregating all ED-observed provider roles", flush=True)
        copy_parquet(
            con,
            f"""
            WITH role_events AS (
                SELECT
                    visit_year::INTEGER AS visit_year,
                    visit_quarter::UTINYINT AS visit_quarter,
                    nullif(trim(attending_selected_npi), '') AS npi,
                    'attending'::VARCHAR AS provider_role,
                    attending_selection_method::VARCHAR AS selection_method,
                    facility_ahca_id::VARCHAR AS facility_ahca_id
                FROM read_parquet(
                    '{qpath(fact_glob)}',
                    hive_partitioning=false,
                    union_by_name=true
                )
                WHERE attending_selected_npi IS NOT NULL
                UNION ALL
                SELECT
                    visit_year::INTEGER,
                    visit_quarter::UTINYINT,
                    nullif(trim(operating_performing_selected_npi), ''),
                    'operating_performing'::VARCHAR,
                    operating_performing_selection_method::VARCHAR,
                    facility_ahca_id::VARCHAR
                FROM read_parquet(
                    '{qpath(fact_glob)}',
                    hive_partitioning=false,
                    union_by_name=true
                )
                WHERE operating_performing_selected_npi IS NOT NULL
                UNION ALL
                SELECT
                    visit_year::INTEGER,
                    visit_quarter::UTINYINT,
                    nullif(trim(other_practitioner_selected_npi), ''),
                    'other_practitioner'::VARCHAR,
                    other_practitioner_selection_method::VARCHAR,
                    facility_ahca_id::VARCHAR
                FROM read_parquet(
                    '{qpath(fact_glob)}',
                    hive_partitioning=false,
                    union_by_name=true
                )
                WHERE other_practitioner_selected_npi IS NOT NULL
            )
            SELECT
                visit_year,
                visit_quarter,
                npi,
                provider_role,
                selection_method,
                facility_ahca_id,
                count(*)::UBIGINT AS ed_visit_count
            FROM role_events
            WHERE regexp_full_match(npi, '[0-9]{{10}}')
            GROUP BY ALL
            ORDER BY visit_year, visit_quarter, npi, provider_role,
                     facility_ahca_id
            """,
            role_cache,
        )
    else:
        print("1/8 Reusing validated provider-role cache", flush=True)

    con.execute(
        f"""
        CREATE OR REPLACE VIEW provider_qfr AS
        SELECT * FROM read_parquet('{qpath(role_cache)}')
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE provider_summary AS
        SELECT
            npi,
            sum(ed_visit_count)::UBIGINT AS ed_selected_role_visit_count,
            sum(ed_visit_count) FILTER (
                WHERE provider_role = 'attending'
            )::UBIGINT AS ed_attending_visit_count,
            sum(ed_visit_count) FILTER (
                WHERE provider_role = 'operating_performing'
            )::UBIGINT AS ed_operating_performing_visit_count,
            sum(ed_visit_count) FILTER (
                WHERE provider_role = 'other_practitioner'
            )::UBIGINT AS ed_other_practitioner_visit_count,
            sum(ed_visit_count) FILTER (
                WHERE selection_method = 'direct_validated_npi'
            )::UBIGINT AS ed_direct_validated_npi_visit_count,
            sum(ed_visit_count) FILTER (
                WHERE selection_method = 'unique_fl_license_crosswalk'
            )::UBIGINT AS ed_license_crosswalk_visit_count,
            min(visit_year)::INTEGER AS ed_first_observed_year,
            min_by(visit_quarter, visit_year * 10 + visit_quarter)::UTINYINT
                AS ed_first_observed_quarter,
            max(visit_year)::INTEGER AS ed_last_observed_year,
            max_by(visit_quarter, visit_year * 10 + visit_quarter)::UTINYINT
                AS ed_last_observed_quarter,
            count(DISTINCT visit_year)::USMALLINT
                AS ed_distinct_observed_years,
            count(DISTINCT facility_ahca_id) FILTER (
                WHERE facility_ahca_id IS NOT NULL
            )::UINTEGER AS ed_distinct_facilities_all_years,
            bool_or(provider_role = 'attending') AS observed_as_attending_flag,
            bool_or(provider_role = 'operating_performing')
                AS observed_as_operating_performing_flag,
            bool_or(provider_role = 'other_practitioner')
                AS observed_as_other_practitioner_flag
        FROM provider_qfr
        GROUP BY npi
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE VIEW phase1_master AS
        SELECT * FROM read_parquet('{qpath(phase1_master)}')
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE master_universe AS
        SELECT npi FROM phase1_master
        UNION
        SELECT npi FROM provider_summary
        """
    )

    taxonomy_pairs: list[str] = []
    taxonomy_codes: list[str] = []
    taxonomy_ed_tests: list[str] = []
    for index in range(1, 16):
        code = (
            f'nullif(trim(n."Healthcare Provider Taxonomy Code_{index}"), \'\')'
        )
        switch = (
            "upper(nullif(trim("
            f'n."Healthcare Provider Primary Taxonomy Switch_{index}"'
            "), ''))"
        )
        taxonomy_pairs.append(f"CASE WHEN {switch} = 'Y' THEN {code} END")
        taxonomy_codes.append(code)
        taxonomy_ed_tests.append(f"{code} LIKE '207P%'")
    primary_taxonomy = (
        "coalesce(" + ", ".join(taxonomy_pairs + taxonomy_codes) + ")"
    )
    all_taxonomies = (
        "nullif(concat_ws(' | ', " + ", ".join(taxonomy_codes) + "), '')"
    )
    any_ed_taxonomy = " OR ".join(taxonomy_ed_tests)

    print("2/8 Joining the current NPPES identity/taxonomy snapshot", flush=True)
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE nppes_current AS
        SELECT
            trim(n.NPI) AS npi,
            nullif(trim(n."Entity Type Code"), '') AS entity_type_code,
            nullif(trim(n."Provider Last Name (Legal Name)"), '') AS last_name,
            nullif(trim(n."Provider First Name"), '') AS first_name,
            nullif(trim(n."Provider Middle Name"), '') AS middle_name,
            nullif(trim(n."Provider Name Prefix Text"), '') AS name_prefix,
            nullif(trim(n."Provider Name Suffix Text"), '') AS name_suffix,
            nullif(trim(n."Provider Credential Text"), '') AS credentials,
            upper(nullif(trim(n."Provider Sex Code"), '')) AS sex_code,
            nullif(
                trim(
                    n."Provider Business Practice Location Address City Name"
                ),
                ''
            ) AS practice_city,
            upper(
                nullif(
                    trim(
                        n."Provider Business Practice Location Address State Name"
                    ),
                    ''
                )
            ) AS practice_state,
            nullif(
                trim(
                    n."Provider Business Practice Location Address Postal Code"
                ),
                ''
            ) AS practice_zip,
            nullif(trim(n.full_name_nppes), '') AS full_name,
            {primary_taxonomy} AS primary_taxonomy_code,
            {all_taxonomies} AS all_taxonomy_codes,
            ({any_ed_taxonomy}) AS any_ed_taxonomy_flag
        FROM read_parquet('{qpath(nppes_minimal)}') n
        INNER JOIN master_universe u ON trim(n.NPI) = u.npi
        QUALIFY row_number() OVER (
            PARTITION BY trim(n.NPI)
            ORDER BY trim(n."Entity Type Code")
        ) = 1
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE taxonomy_decoder AS
        SELECT
            upper(trim(Code)) AS taxonomy_code,
            nullif(trim(Grouping), '') AS taxonomy_grouping,
            nullif(trim(Classification), '') AS taxonomy_classification,
            nullif(trim(Specialization), '') AS taxonomy_specialization,
            nullif(trim("Display Name"), '') AS taxonomy_display_name
        FROM read_csv(
            '{qpath(taxonomy)}',
            header=true,
            auto_detect=true,
            all_varchar=true,
            normalize_names=false
        )
        """
    )

    lifecycle_cache = temp / "nppes_lifecycle_target.parquet"
    if args.force or not parquet_nonempty(con, lifecycle_cache):
        print(
            "3/8 Extracting NPPES enumeration and deactivation metadata "
            "from the full February 2026 snapshot",
            flush=True,
        )
        copy_parquet(
            con,
            f"""
            SELECT
                trim(n."NPI") AS npi,
                nullif(trim(n."Entity Type Code"), '') AS entity_type_code,
                nullif(trim(n."Replacement NPI"), '') AS replacement_npi,
                nullif(
                    trim(n."Provider Organization Name (Legal Business Name)"),
                    ''
                ) AS organization_name,
                nullif(trim(n."Provider Enumeration Date"), '')
                    AS enumeration_date_raw,
                nullif(trim(n."Last Update Date"), '')
                    AS last_update_date_raw,
                nullif(trim(n."NPI Deactivation Reason Code"), '')
                    AS deactivation_reason_code,
                nullif(trim(n."NPI Deactivation Date"), '')
                    AS deactivation_date_raw,
                nullif(trim(n."NPI Reactivation Date"), '')
                    AS reactivation_date_raw
            FROM read_csv(
                '{qpath(nppes_full)}',
                header=true,
                auto_detect=true,
                all_varchar=true,
                sample_size=200000,
                ignore_errors=true,
                null_padding=true,
                parallel=true,
                max_line_size=10000000
            ) n
            INNER JOIN master_universe u ON trim(n."NPI") = u.npi
            QUALIFY row_number() OVER (
                PARTITION BY trim(n."NPI")
                ORDER BY try_strptime(
                    nullif(trim(n."Last Update Date"), ''),
                    '%m/%d/%Y'
                ) DESC NULLS LAST
            ) = 1
            """,
            lifecycle_cache,
        )
    else:
        print("3/8 Reusing validated NPPES lifecycle cache", flush=True)
    con.execute(
        f"""
        CREATE OR REPLACE VIEW nppes_lifecycle AS
        SELECT
            *,
            try_strptime(enumeration_date_raw, '%m/%d/%Y')::DATE
                AS enumeration_date,
            try_strptime(last_update_date_raw, '%m/%d/%Y')::DATE
                AS last_update_date,
            try_strptime(deactivation_date_raw, '%m/%d/%Y')::DATE
                AS deactivation_date,
            try_strptime(reactivation_date_raw, '%m/%d/%Y')::DATE
                AS reactivation_date
        FROM read_parquet('{qpath(lifecycle_cache)}')
        """
    )

    cms_provider_cache = (
        temp / "cms_current_provider_20260626_v1.parquet"
    )
    if args.force or not parquet_nonempty(con, cms_provider_cache):
        print(
            "4/10 Extracting current CMS clinician attributes for the "
            "ED-observed NPI universe",
            flush=True,
        )
        copy_parquet(
            con,
            f"""
            WITH cms_raw AS (
                SELECT
                    trim(c.NPI) AS npi,
                    upper(nullif(trim(c.gndr), '')) AS gender_code,
                    nullif(trim(c.pri_spec), '') AS primary_specialty,
                    nullif(
                        concat_ws(
                            ' | ',
                            nullif(trim(c.sec_spec_1), ''),
                            nullif(trim(c.sec_spec_2), ''),
                            nullif(trim(c.sec_spec_3), ''),
                            nullif(trim(c.sec_spec_4), ''),
                            nullif(trim(c.sec_spec_all), '')
                        ),
                        ''
                    ) AS secondary_specialties,
                    nullif(trim(c.Med_sch), '') AS medical_school,
                    try_cast(nullif(trim(c.Grd_yr), '') AS INTEGER)
                        AS grad_year,
                    upper(nullif(trim(c.Telehlth), '')) = 'Y'
                        AS telehealth_flag,
                    nullif(trim(c."Facility Name"), '')
                        AS group_practice_name,
                    nullif(trim(c.org_pac_id), '') AS group_pac_id,
                    try_cast(
                        nullif(trim(c.num_org_mem), '') AS INTEGER
                    ) AS group_member_count,
                    upper(nullif(trim(c.State), '')) AS practice_state
                FROM read_csv(
                    '{qpath(cms_current)}',
                    header=true,
                    auto_detect=true,
                    all_varchar=true,
                    sample_size=10000,
                    ignore_errors=true,
                    null_padding=true,
                    parallel=true,
                    max_line_size=10000000
                ) c
                INNER JOIN provider_summary s
                  ON trim(c.NPI) = s.npi
            ),
            primary_counts AS (
                SELECT npi, primary_specialty AS value, count(*) AS n
                FROM cms_raw
                WHERE primary_specialty IS NOT NULL
                GROUP BY npi, primary_specialty
            ),
            primary_ranked AS (
                SELECT
                    npi,
                    value,
                    row_number() OVER (
                        PARTITION BY npi ORDER BY n DESC, value ASC
                    ) AS rank_number
                FROM primary_counts
            ),
            school_counts AS (
                SELECT npi, medical_school AS value, count(*) AS n
                FROM cms_raw
                WHERE medical_school IS NOT NULL
                GROUP BY npi, medical_school
            ),
            school_ranked AS (
                SELECT
                    npi,
                    value,
                    row_number() OVER (
                        PARTITION BY npi ORDER BY n DESC, value ASC
                    ) AS rank_number
                FROM school_counts
            ),
            grad_counts AS (
                SELECT npi, grad_year AS value, count(*) AS n
                FROM cms_raw
                WHERE grad_year BETWEEN 1900 AND 2026
                GROUP BY npi, grad_year
            ),
            grad_ranked AS (
                SELECT
                    npi,
                    value,
                    row_number() OVER (
                        PARTITION BY npi ORDER BY n DESC, value ASC
                    ) AS rank_number
                FROM grad_counts
            ),
            cms_aggregated AS (
                SELECT
                    npi,
                    count(*)::UBIGINT AS cms_source_row_count_v2,
                    count(DISTINCT gender_code) FILTER (
                        WHERE gender_code IN ('M', 'F')
                    )::UINTEGER AS cms_gender_distinct_count_v2,
                    string_agg(
                        DISTINCT gender_code,
                        ' | ' ORDER BY gender_code
                    ) FILTER (
                        WHERE gender_code IN ('M', 'F')
                    ) AS cms_gender_values_v2,
                    CASE
                        WHEN count(DISTINCT gender_code) FILTER (
                            WHERE gender_code IN ('M', 'F')
                        ) = 1
                        THEN CASE max(gender_code)
                            WHEN 'M' THEN 'Male'
                            WHEN 'F' THEN 'Female'
                        END
                    END AS cms_gender_v2,
                    string_agg(
                        DISTINCT primary_specialty,
                        ' | ' ORDER BY primary_specialty
                    ) FILTER (
                        WHERE primary_specialty IS NOT NULL
                    ) AS cms_primary_specialty_values_v2,
                    count(DISTINCT primary_specialty) FILTER (
                        WHERE primary_specialty IS NOT NULL
                    )::UINTEGER
                        AS cms_primary_specialty_distinct_count_v2,
                    string_agg(
                        DISTINCT secondary_specialties,
                        ' | ' ORDER BY secondary_specialties
                    ) FILTER (
                        WHERE secondary_specialties IS NOT NULL
                    ) AS cms_secondary_specialties_v2,
                    bool_or(coalesce(telehealth_flag, false))
                        AS cms_telehealth_flag_v2,
                    count(DISTINCT group_pac_id) FILTER (
                        WHERE group_pac_id IS NOT NULL
                    )::UINTEGER AS cms_group_practice_count_v2,
                    string_agg(
                        DISTINCT group_practice_name,
                        ' | ' ORDER BY group_practice_name
                    ) FILTER (
                        WHERE group_practice_name IS NOT NULL
                    ) AS cms_group_practice_names_v2,
                    string_agg(
                        DISTINCT group_pac_id,
                        ' | ' ORDER BY group_pac_id
                    ) FILTER (
                        WHERE group_pac_id IS NOT NULL
                    ) AS cms_group_pac_ids_v2,
                    max(group_member_count)
                        AS cms_largest_group_member_count_v2,
                    string_agg(
                        DISTINCT practice_state,
                        ' | ' ORDER BY practice_state
                    ) FILTER (
                        WHERE practice_state IS NOT NULL
                    ) AS cms_practice_states_v2,
                    string_agg(
                        DISTINCT medical_school,
                        ' | ' ORDER BY medical_school
                    ) FILTER (
                        WHERE medical_school IS NOT NULL
                    ) AS cms_medical_school_values_v2,
                    count(DISTINCT medical_school) FILTER (
                        WHERE medical_school IS NOT NULL
                    )::UINTEGER AS cms_medical_school_distinct_count_v2,
                    string_agg(
                        DISTINCT cast(grad_year AS VARCHAR),
                        ' | ' ORDER BY cast(grad_year AS VARCHAR)
                    ) FILTER (
                        WHERE grad_year BETWEEN 1900 AND 2026
                    ) AS cms_grad_year_values_v2,
                    count(DISTINCT grad_year) FILTER (
                        WHERE grad_year BETWEEN 1900 AND 2026
                    )::UINTEGER AS cms_grad_year_distinct_count_v2
                FROM cms_raw
                GROUP BY npi
            )
            SELECT
                a.*,
                p.value AS cms_primary_specialty_v2,
                m.value AS cms_medical_school_v2,
                g.value AS cms_grad_year_v2
            FROM cms_aggregated a
            LEFT JOIN primary_ranked p
              ON a.npi = p.npi AND p.rank_number = 1
            LEFT JOIN school_ranked m
              ON a.npi = m.npi AND m.rank_number = 1
            LEFT JOIN grad_ranked g
              ON a.npi = g.npi AND g.rank_number = 1
            ORDER BY a.npi
            """,
            cms_provider_cache,
        )
    else:
        print(
            "4/10 Reusing validated current CMS clinician cache",
            flush=True,
        )
    con.execute(
        f"""
        CREATE OR REPLACE VIEW cms_current_provider AS
        SELECT * FROM read_parquet('{qpath(cms_provider_cache)}')
        """
    )

    cms_facility_cache = (
        temp / "cms_current_facility_affiliation_20260626_v1.parquet"
    )
    if args.force or not parquet_nonempty(con, cms_facility_cache):
        print(
            "5/10 Extracting current CMS facility affiliations for the "
            "ED-observed NPI universe",
            flush=True,
        )
        copy_parquet(
            con,
            f"""
            WITH affiliation_raw AS (
                SELECT
                    trim(c.NPI) AS npi,
                    nullif(trim(c.facility_type), '') AS facility_type,
                    nullif(
                        trim(
                            c."Facility Affiliations Certification Number"
                        ),
                        ''
                    ) AS certification_number,
                    nullif(
                        trim(c."Facility Type Certification Number"),
                        ''
                    ) AS facility_type_certification_number
                FROM read_csv(
                    '{qpath(cms_facility_affiliation)}',
                    header=true,
                    auto_detect=true,
                    all_varchar=true,
                    sample_size=10000,
                    ignore_errors=true,
                    null_padding=true,
                    parallel=true,
                    max_line_size=10000000
                ) c
                INNER JOIN provider_summary s
                  ON trim(c.NPI) = s.npi
            )
            SELECT
                npi,
                count(*)::UBIGINT
                    AS cms_facility_affiliation_row_count_v2,
                count(DISTINCT certification_number) FILTER (
                    WHERE certification_number IS NOT NULL
                )::UINTEGER
                    AS cms_facility_certification_count_v2,
                string_agg(
                    DISTINCT certification_number,
                    ' | ' ORDER BY certification_number
                ) FILTER (
                    WHERE certification_number IS NOT NULL
                ) AS cms_facility_certification_numbers_v2,
                string_agg(
                    DISTINCT facility_type,
                    ' | ' ORDER BY facility_type
                ) FILTER (
                    WHERE facility_type IS NOT NULL
                ) AS cms_facility_types_v2,
                count(
                    DISTINCT facility_type_certification_number
                ) FILTER (
                    WHERE facility_type_certification_number IS NOT NULL
                )::UINTEGER
                    AS cms_facility_type_certification_count_v2,
                string_agg(
                    DISTINCT facility_type_certification_number,
                    ' | ' ORDER BY facility_type_certification_number
                ) FILTER (
                    WHERE facility_type_certification_number IS NOT NULL
                ) AS cms_facility_type_certification_numbers_v2
            FROM affiliation_raw
            GROUP BY npi
            ORDER BY npi
            """,
            cms_facility_cache,
        )
    else:
        print(
            "5/10 Reusing validated current CMS facility-affiliation cache",
            flush=True,
        )
    con.execute(
        f"""
        CREATE OR REPLACE VIEW cms_current_facility_affiliation AS
        SELECT * FROM read_parquet('{qpath(cms_facility_cache)}')
        """
    )

    print("6/10 Building one-row-per-NPI provider master v2", flush=True)
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE provider_master_v2_stage AS
        SELECT
            u.npi,
            p.* EXCLUDE (npi),
            c.* EXCLUDE (npi),
            a.* EXCLUDE (npi),
            coalesce(
                n.entity_type_code,
                l.entity_type_code,
                nullif(p.nppes_entity_type_code, '')
            ) AS nppes_entity_type_code_v2,
            CASE
                WHEN coalesce(
                    n.entity_type_code,
                    l.entity_type_code,
                    nullif(p.nppes_entity_type_code, '')
                ) = '1' THEN 'Individual'
                WHEN coalesce(
                    n.entity_type_code,
                    l.entity_type_code,
                    nullif(p.nppes_entity_type_code, '')
                ) = '2' THEN 'Organization'
                ELSE 'Not found in current NPPES snapshot'
            END AS provider_entity_category_v2,
            coalesce(n.last_name, nullif(p.last_name, ''))
                AS last_name_v2,
            coalesce(n.first_name, nullif(p.first_name, ''))
                AS first_name_v2,
            coalesce(n.middle_name, nullif(p.middle_name, ''))
                AS middle_name_v2,
            coalesce(n.name_prefix, nullif(p.name_prefix, ''))
                AS name_prefix_v2,
            coalesce(n.name_suffix, nullif(p.name_suffix, ''))
                AS name_suffix_v2,
            coalesce(n.credentials, nullif(p.credentials, ''))
                AS credentials_v2,
            coalesce(
                n.full_name,
                nullif(p.full_name, ''),
                l.organization_name
            ) AS provider_name_v2,
            CASE
                WHEN coalesce(
                    n.entity_type_code,
                    l.entity_type_code,
                    nullif(p.nppes_entity_type_code, '')
                ) <> '1' THEN 'Unknown'
                WHEN n.sex_code = 'M' THEN 'Male'
                WHEN n.sex_code = 'F' THEN 'Female'
                WHEN c.cms_gender_v2 IN ('Male', 'Female')
                    THEN c.cms_gender_v2
                WHEN p.gender_category IN ('Male', 'Female')
                 AND p.gender_source IN (
                    'NPPES',
                    'CMS Doctors and Clinicians'
                 )
                    THEN p.gender_category
                WHEN p.gender_category IN ('Male', 'Female')
                 AND p.gender_source =
                    'SSA first-name imputation (>=90% probability)'
                    THEN p.gender_category
                ELSE 'Unknown'
            END AS gender_category_v2,
            CASE
                WHEN coalesce(
                    n.entity_type_code,
                    l.entity_type_code,
                    nullif(p.nppes_entity_type_code, '')
                ) <> '1' THEN 'Unknown'
                WHEN n.sex_code IN ('M', 'F')
                    THEN 'NPPES February 2026 current snapshot'
                WHEN c.cms_gender_v2 IN ('Male', 'Female')
                    THEN 'CMS Doctors and Clinicians June 2026 current snapshot'
                WHEN p.gender_category IN ('Male', 'Female')
                 AND p.gender_source IN (
                    'NPPES',
                    'CMS Doctors and Clinicians'
                 )
                    THEN p.gender_source
                WHEN p.gender_category IN ('Male', 'Female')
                 AND p.gender_source =
                    'SSA first-name imputation (>=90% probability)'
                    THEN p.gender_source
                ELSE 'Unknown'
            END AS gender_source_v2,
            CASE
                WHEN n.sex_code IN ('M', 'F')
                 AND c.cms_gender_v2 IN ('Male', 'Female')
                    THEN CASE n.sex_code
                        WHEN 'M' THEN 'Male'
                        WHEN 'F' THEN 'Female'
                    END <> c.cms_gender_v2
                ELSE coalesce(p.gender_conflict_flag, false)
            END AS gender_conflict_flag_v2,
            coalesce(
                n.primary_taxonomy_code,
                nullif(p.primary_taxonomy_code, '')
            ) AS primary_taxonomy_code_v2,
            coalesce(
                n.all_taxonomy_codes,
                nullif(p.all_taxonomy_codes, '')
            ) AS all_taxonomy_codes_v2,
            coalesce(
                t.taxonomy_grouping,
                nullif(p.taxonomy_grouping, '')
            ) AS taxonomy_grouping_v2,
            coalesce(
                t.taxonomy_classification,
                nullif(p.taxonomy_classification, '')
            ) AS taxonomy_classification_v2,
            coalesce(
                t.taxonomy_specialization,
                nullif(p.taxonomy_specialization, '')
            ) AS taxonomy_specialization_v2,
            coalesce(
                t.taxonomy_display_name,
                nullif(p.taxonomy_display_name, '')
            ) AS taxonomy_display_name_v2,
            coalesce(
                nullif(p.nppes_practice_city, ''),
                n.practice_city
            ) AS nppes_practice_city_v2,
            coalesce(
                nullif(p.nppes_practice_state, ''),
                n.practice_state
            ) AS nppes_practice_state_v2,
            coalesce(
                nullif(p.nppes_practice_zip, ''),
                n.practice_zip
            ) AS nppes_practice_zip_v2,
            (
                coalesce(n.any_ed_taxonomy_flag, false)
                OR upper(coalesce(c.cms_primary_specialty_v2, '')) IN (
                    'EMERGENCY MEDICINE',
                    'PEDIATRIC EMERGENCY MEDICINE'
                )
                OR coalesce(p.ed_specialist_flag, false)
                OR upper(coalesce(p.cms_primary_specialty, '')) IN (
                    'EMERGENCY MEDICINE',
                    'PEDIATRIC EMERGENCY MEDICINE'
                )
            ) AS ed_specialist_flag_v2,
            CASE
                WHEN coalesce(n.any_ed_taxonomy_flag, false)
                    THEN 'NPPES February 2026 taxonomy'
                WHEN upper(coalesce(c.cms_primary_specialty_v2, '')) IN (
                    'EMERGENCY MEDICINE',
                    'PEDIATRIC EMERGENCY MEDICINE'
                ) THEN 'CMS Doctors and Clinicians June 2026 primary specialty'
                WHEN coalesce(p.ed_specialist_flag, false)
                    THEN p.ed_specialist_source
                ELSE 'No ED specialty found in linked public sources'
            END AS ed_specialist_source_v2,
            (
                coalesce(
                    n.entity_type_code,
                    l.entity_type_code,
                    nullif(p.nppes_entity_type_code, '')
                ) = '1'
                AND (
                    coalesce(
                        n.primary_taxonomy_code,
                        nullif(p.primary_taxonomy_code, ''),
                        ''
                    ) LIKE '207%'
                    OR coalesce(
                        n.primary_taxonomy_code,
                        nullif(p.primary_taxonomy_code, ''),
                        ''
                    ) LIKE '208%'
                    OR coalesce(p.physician_md_do_flag, false)
                    OR regexp_matches(
                        upper(
                            coalesce(
                                n.credentials,
                                nullif(p.credentials, ''),
                                ''
                            )
                        ),
                        '(^|[^A-Z])(MD|M[.]D[.]?|DO|D[.]O[.]?)'
                        '([^A-Z]|$)'
                    )
                )
            ) AS physician_md_do_flag_v2,
            coalesce(
                c.cms_medical_school_v2,
                p.cms_medical_school,
                p.doh_medical_school_selected,
                p.medical_school_selected
            ) AS medical_school_selected_v2,
            CASE
                WHEN c.cms_medical_school_v2 IS NOT NULL
                    THEN 'CMS Doctors and Clinicians June 2026 current snapshot'
                WHEN p.cms_medical_school IS NOT NULL
                    THEN 'CMS Doctors and Clinicians legacy Phase 1 source'
                WHEN p.doh_medical_school_selected IS NOT NULL
                    THEN 'Florida DOH education'
                WHEN p.medical_school_selected IS NOT NULL
                    THEN p.medical_school_source
                ELSE 'Unknown'
            END AS medical_school_source_v2,
            coalesce(
                c.cms_grad_year_v2,
                p.cms_grad_year,
                p.doh_grad_year_selected,
                p.medical_school_grad_year
            )::INTEGER AS medical_school_grad_year_v2,
            CASE
                WHEN c.cms_grad_year_v2 IS NOT NULL
                    THEN 'CMS Doctors and Clinicians June 2026 current snapshot'
                WHEN p.cms_grad_year IS NOT NULL
                    THEN 'CMS Doctors and Clinicians legacy Phase 1 source'
                WHEN p.doh_grad_year_selected IS NOT NULL
                    THEN 'Florida DOH education'
                WHEN p.medical_school_grad_year IS NOT NULL
                    THEN p.medical_school_grad_year_source
                ELSE 'Unknown'
            END AS medical_school_grad_year_source_v2,
            c.npi IS NOT NULL AS cms_current_snapshot_match_flag,
            a.npi IS NOT NULL
                AS has_cms_current_facility_affiliation_v2,
            coalesce(c.cms_group_practice_count_v2, 0) > 0
                AS has_cms_group_practice_affiliation_v2,
            (
                a.npi IS NOT NULL
                OR coalesce(p.has_fl_doh_hospital_privilege, false)
            ) AS has_any_current_hospital_affiliation_v2,
            l.replacement_npi AS nppes_replacement_npi,
            l.enumeration_date AS nppes_enumeration_date,
            l.last_update_date AS nppes_last_update_date,
            l.deactivation_reason_code AS nppes_deactivation_reason_code,
            l.deactivation_date AS nppes_deactivation_date,
            l.reactivation_date AS nppes_reactivation_date,
            CASE
                WHEN l.npi IS NULL THEN NULL
                WHEN l.deactivation_date IS NULL THEN true
                WHEN l.reactivation_date IS NOT NULL
                 AND l.reactivation_date >= l.deactivation_date THEN true
                ELSE false
            END AS nppes_active_at_february_2026_snapshot_flag,
            p.npi IS NOT NULL AS phase1_master_match_flag,
            n.npi IS NOT NULL OR l.npi IS NOT NULL
                AS nppes_current_snapshot_match_flag,
            s.npi IS NOT NULL AS ed_observed_flag,
            coalesce(s.ed_selected_role_visit_count, 0)::UBIGINT
                AS ed_selected_role_visit_count,
            coalesce(s.ed_attending_visit_count, 0)::UBIGINT
                AS ed_attending_visit_count,
            coalesce(s.ed_operating_performing_visit_count, 0)::UBIGINT
                AS ed_operating_performing_visit_count,
            coalesce(s.ed_other_practitioner_visit_count, 0)::UBIGINT
                AS ed_other_practitioner_visit_count,
            coalesce(s.ed_direct_validated_npi_visit_count, 0)::UBIGINT
                AS ed_direct_validated_npi_visit_count,
            coalesce(s.ed_license_crosswalk_visit_count, 0)::UBIGINT
                AS ed_license_crosswalk_visit_count,
            s.ed_first_observed_year,
            s.ed_first_observed_quarter,
            s.ed_last_observed_year,
            s.ed_last_observed_quarter,
            s.ed_distinct_observed_years,
            s.ed_distinct_facilities_all_years,
            coalesce(s.observed_as_attending_flag, false)
                AS observed_as_attending_flag,
            coalesce(s.observed_as_operating_performing_flag, false)
                AS observed_as_operating_performing_flag,
            coalesce(s.observed_as_other_practitioner_flag, false)
                AS observed_as_other_practitioner_flag,
            npi_checksum_valid(u.npi) AS npi_checksum_valid_v2,
            CASE
                WHEN p.npi IS NOT NULL THEN 'Phase 1 enriched master record'
                WHEN n.npi IS NOT NULL OR l.npi IS NOT NULL
                    THEN 'ED-observed NPI added from current NPPES snapshot'
                WHEN s.npi IS NOT NULL
                    THEN 'ED-observed validated NPI absent from current NPPES snapshot'
                ELSE 'Phase 1 record without current NPPES match'
            END AS provider_master_v2_record_status,
            'NPPES/CMS/Florida DOH attributes are current-source snapshots; '
            'they are not assumed to be encounter-year values.'
                AS current_attribute_temporal_scope,
            'Provider-facility-year links derived from Florida ED encounters '
            'are encounter-year observed affiliations.'
                AS observed_affiliation_temporal_scope,
            TIMESTAMP '2026-07-26 00:00:00'
                AS provider_master_v2_build_date,
            'provider_master_v2_cms_current_20260626_v1'
                AS provider_master_v2_build_spec_version
        FROM master_universe u
        LEFT JOIN phase1_master p ON u.npi = p.npi
        LEFT JOIN provider_summary s ON u.npi = s.npi
        LEFT JOIN nppes_current n ON u.npi = n.npi
        LEFT JOIN nppes_lifecycle l ON u.npi = l.npi
        LEFT JOIN cms_current_provider c ON u.npi = c.npi
        LEFT JOIN cms_current_facility_affiliation a ON u.npi = a.npi
        LEFT JOIN taxonomy_decoder t
          ON upper(
                coalesce(
                    n.primary_taxonomy_code,
                    nullif(p.primary_taxonomy_code, '')
                )
             ) = t.taxonomy_code
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE provider_master_v2 AS
        SELECT
            *,
            CASE
                WHEN provider_entity_category_v2 = 'Organization'
                    THEN 'Organization NPI'
                WHEN provider_entity_category_v2 <>
                    'Individual'
                    THEN 'NPI absent from current individual snapshot'
                WHEN physician_md_do_flag_v2
                    THEN 'MD/DO physician'
                WHEN primary_taxonomy_code_v2 LIKE '363L%'
                  OR regexp_matches(
                        upper(coalesce(credentials_v2, '')),
                        '(^|[^A-Z])(NP|APRN|ARNP|FNP|DNP)([^A-Z]|$)'
                    )
                    THEN 'Nurse practitioner'
                WHEN primary_taxonomy_code_v2 LIKE '363A%'
                  OR regexp_matches(
                        upper(coalesce(credentials_v2, '')),
                        '(^|[^A-Z])(PA|PA-C|PAC)([^A-Z]|$)'
                    )
                    THEN 'Physician assistant'
                WHEN primary_taxonomy_code_v2 = '367500000X'
                    THEN 'Certified registered nurse anesthetist'
                WHEN primary_taxonomy_code_v2 LIKE '364S%'
                    THEN 'Clinical nurse specialist'
                WHEN primary_taxonomy_code_v2 LIKE '163W%'
                    THEN 'Registered nurse'
                WHEN primary_taxonomy_code_v2 LIKE '1835%'
                    THEN 'Pharmacist'
                WHEN primary_taxonomy_code_v2 LIKE '103T%'
                    THEN 'Psychologist'
                WHEN primary_taxonomy_code_v2 LIKE '1041%'
                    THEN 'Social worker'
                ELSE 'Other individual provider'
            END AS clinician_type_v2
        FROM provider_master_v2_stage
        QUALIFY row_number() OVER (PARTITION BY npi ORDER BY npi) = 1
        """
    )
    copy_parquet(
        con,
        "SELECT * FROM provider_master_v2 ORDER BY npi",
        master_out,
    )

    print(
        "7/10 Building encounter-year provider volume and affiliation panels",
        flush=True,
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE provider_facility_year_role AS
        SELECT
            npi,
            visit_year,
            provider_role,
            facility_ahca_id,
            sum(ed_visit_count)::UBIGINT AS ed_visit_count,
            sum(ed_visit_count) FILTER (
                WHERE selection_method = 'direct_validated_npi'
            )::UBIGINT AS direct_validated_npi_visit_count,
            sum(ed_visit_count) FILTER (
                WHERE selection_method = 'unique_fl_license_crosswalk'
            )::UBIGINT AS license_crosswalk_visit_count,
            string_agg(
                DISTINCT selection_method,
                ' | '
                ORDER BY selection_method
            ) AS linkage_methods
        FROM provider_qfr
        GROUP BY npi, visit_year, provider_role, facility_ahca_id
        """
    )
    copy_parquet(
        con,
        """
        SELECT
            *,
            'Observed in Florida ED encounter records for this calendar year'
                AS affiliation_evidence,
            'Encounter-year observed; not proof of employment or medical-staff '
            'membership outside the observed visits'
                AS interpretation_limit
        FROM provider_facility_year_role
        ORDER BY npi, visit_year, provider_role, facility_ahca_id
        """,
        facility_year_out,
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE provider_year_base AS
        SELECT
            npi,
            visit_year,
            sum(ed_visit_count)::UBIGINT AS ed_selected_role_visit_count,
            sum(ed_visit_count) FILTER (
                WHERE provider_role = 'attending'
            )::UBIGINT AS ed_attending_visit_count,
            sum(ed_visit_count) FILTER (
                WHERE provider_role = 'operating_performing'
            )::UBIGINT AS ed_operating_performing_visit_count,
            sum(ed_visit_count) FILTER (
                WHERE provider_role = 'other_practitioner'
            )::UBIGINT AS ed_other_practitioner_visit_count,
            count(DISTINCT facility_ahca_id) FILTER (
                WHERE facility_ahca_id IS NOT NULL
                 AND provider_role = 'attending'
            )::UINTEGER AS attending_distinct_ed_facilities,
            sum(ed_visit_count) FILTER (
                WHERE selection_method = 'direct_validated_npi'
            )::UBIGINT AS direct_validated_npi_visit_count,
            sum(ed_visit_count) FILTER (
                WHERE selection_method = 'unique_fl_license_crosswalk'
            )::UBIGINT AS license_crosswalk_visit_count
        FROM provider_qfr
        GROUP BY npi, visit_year
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE attending_primary_facility AS
        WITH ranked AS (
            SELECT
                npi,
                visit_year,
                facility_ahca_id,
                ed_visit_count,
                row_number() OVER (
                    PARTITION BY npi, visit_year
                    ORDER BY ed_visit_count DESC, facility_ahca_id
                ) AS rank_number,
                sum(ed_visit_count) OVER (
                    PARTITION BY npi, visit_year
                ) AS attending_year_visits
            FROM provider_facility_year_role
            WHERE provider_role = 'attending'
              AND facility_ahca_id IS NOT NULL
        )
        SELECT
            npi,
            visit_year,
            facility_ahca_id AS primary_ed_facility_ahca_id_by_visits,
            ed_visit_count AS primary_ed_facility_visit_count,
            ed_visit_count::DOUBLE
                / nullif(attending_year_visits, 0)
                AS primary_ed_facility_visit_share
        FROM ranked
        WHERE rank_number = 1
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE provider_year_v2 AS
        SELECT
            y.*,
            a.primary_ed_facility_ahca_id_by_visits,
            a.primary_ed_facility_visit_count,
            a.primary_ed_facility_visit_share,
            m.gender_category_v2,
            m.gender_source_v2,
            m.primary_taxonomy_code_v2,
            m.taxonomy_display_name_v2,
            coalesce(
                m.cms_primary_specialty_v2,
                m.cms_primary_specialty
            ) AS cms_primary_specialty_v2,
            m.ed_specialist_flag_v2,
            m.physician_md_do_flag_v2,
            m.medical_school_selected_v2,
            m.medical_school_source_v2,
            m.medical_school_grad_year_v2,
            m.medical_school_grad_year_source_v2,
            CASE
                WHEN m.medical_school_grad_year_v2
                        BETWEEN 1900 AND y.visit_year
                 AND y.visit_year - m.medical_school_grad_year_v2
                        BETWEEN 0 AND 80
                    THEN y.visit_year - m.medical_school_grad_year_v2
            END AS years_since_medical_school_in_encounter_year,
            m.has_cms_group_practice_affiliation_v2,
            m.cms_group_practice_count_v2,
            m.has_cms_current_facility_affiliation_v2,
            m.cms_facility_certification_count_v2,
            m.has_any_current_hospital_affiliation_v2,
            m.nppes_enumeration_date,
            CASE
                WHEN m.nppes_enumeration_date IS NULL THEN NULL
                ELSE m.nppes_enumeration_date
                    <= make_date(y.visit_year, 12, 31)
            END AS nppes_enumerated_by_encounter_year_end_flag,
            'Experience is encounter year minus linked graduation year; '
            'specialty, gender, and practice address are current-source '
            'snapshots unless separately dated.'
                AS provider_year_temporal_note
        FROM provider_year_base y
        LEFT JOIN attending_primary_facility a
          ON y.npi = a.npi
         AND y.visit_year = a.visit_year
        INNER JOIN provider_master_v2 m ON y.npi = m.npi
        """
    )
    copy_parquet(
        con,
        "SELECT * FROM provider_year_v2 ORDER BY npi, visit_year",
        year_out,
    )

    print("8/10 Writing provider coverage QA", flush=True)
    coverage_csv = qa_root / "provider_master_v2_coverage_by_year_role.csv"
    copy_csv(
        con,
        """
        SELECT
            q.visit_year,
            q.provider_role,
            q.selection_method,
            sum(q.ed_visit_count)::UBIGINT AS visits,
            count(DISTINCT q.npi)::UBIGINT AS distinct_npis,
            sum(q.ed_visit_count) FILTER (
                WHERE m.phase1_master_match_flag
            )::UBIGINT AS visits_matched_phase1_master,
            sum(q.ed_visit_count) FILTER (
                WHERE m.nppes_current_snapshot_match_flag
            )::UBIGINT AS visits_matched_current_nppes,
            sum(q.ed_visit_count) FILTER (
                WHERE m.provider_entity_category_v2 = 'Individual'
            )::UBIGINT AS visits_linked_individual_entity,
            sum(q.ed_visit_count) FILTER (
                WHERE m.physician_md_do_flag_v2
            )::UBIGINT AS visits_linked_md_do,
            sum(q.ed_visit_count) FILTER (
                WHERE m.gender_category_v2 IN ('Male', 'Female')
            )::UBIGINT AS visits_with_provider_gender,
            100.0 * sum(q.ed_visit_count) FILTER (
                WHERE m.phase1_master_match_flag
            ) / nullif(sum(q.ed_visit_count), 0)
                AS phase1_visit_coverage_pct,
            100.0 * sum(q.ed_visit_count) FILTER (
                WHERE m.nppes_current_snapshot_match_flag
            ) / nullif(sum(q.ed_visit_count), 0)
                AS nppes_visit_coverage_pct
        FROM provider_qfr q
        INNER JOIN provider_master_v2 m ON q.npi = m.npi
        GROUP BY q.visit_year, q.provider_role, q.selection_method
        ORDER BY q.visit_year, q.provider_role, q.selection_method
        """,
        coverage_csv,
    )
    copy_csv(
        con,
        """
        SELECT
            q.visit_year,
            q.provider_role,
            q.selection_method AS linkage_method,
            m.provider_entity_category_v2,
            m.clinician_type_v2,
            count(DISTINCT q.npi)::UBIGINT AS unique_npis,
            sum(q.ed_visit_count)::UBIGINT AS visits,
            count(DISTINCT q.npi) FILTER (
                WHERE m.cms_current_snapshot_match_flag
            )::UBIGINT AS unique_npis_matched_current_cms,
            sum(q.ed_visit_count) FILTER (
                WHERE m.cms_current_snapshot_match_flag
            )::UBIGINT AS visits_matched_current_cms,
            count(DISTINCT q.npi) FILTER (
                WHERE m.has_cms_current_facility_affiliation_v2
            )::UBIGINT AS unique_npis_with_cms_facility_affiliation,
            sum(q.ed_visit_count) FILTER (
                WHERE m.has_cms_current_facility_affiliation_v2
            )::UBIGINT AS visits_with_cms_facility_affiliation,
            count(DISTINCT q.npi) FILTER (
                WHERE m.gender_category_v2 IN ('Male', 'Female')
            )::UBIGINT AS unique_npis_with_gender,
            sum(q.ed_visit_count) FILTER (
                WHERE m.gender_category_v2 IN ('Male', 'Female')
            )::UBIGINT AS visits_with_gender
        FROM provider_qfr q
        INNER JOIN provider_master_v2 m ON q.npi = m.npi
        GROUP BY
            q.visit_year,
            q.provider_role,
            q.selection_method,
            m.provider_entity_category_v2,
            m.clinician_type_v2
        ORDER BY
            q.visit_year,
            q.provider_role,
            q.selection_method,
            m.provider_entity_category_v2,
            m.clinician_type_v2
        """,
        qa_root
        / (
            "provider_master_v2_coverage_by_year_role_linkage_"
            "entity_clinician.csv"
        ),
    )
    copy_csv(
        con,
        """
        SELECT
            CASE
                WHEN phase1_master_match_flag
                    THEN 'Phase 1 enriched master'
                WHEN nppes_current_snapshot_match_flag
                    THEN 'Added from current NPPES'
                ELSE 'ED-observed NPI absent from current NPPES'
            END AS source_status,
            provider_entity_category_v2,
            count(*)::UBIGINT AS distinct_npis,
            sum(ed_selected_role_visit_count)::UBIGINT AS selected_role_visits,
            sum(ed_attending_visit_count)::UBIGINT AS attending_visits,
            count(*) FILTER (
                WHERE gender_category_v2 IN ('Male', 'Female')
            )::UBIGINT AS npis_with_gender,
            count(*) FILTER (
                WHERE medical_school_grad_year_v2 IS NOT NULL
            )::UBIGINT AS npis_with_graduation_year,
            count(*) FILTER (
                WHERE cms_current_snapshot_match_flag
            )::UBIGINT AS npis_matched_current_cms,
            count(*) FILTER (
                WHERE has_cms_current_facility_affiliation_v2
            )::UBIGINT AS npis_with_current_cms_facility_affiliation,
            count(*) FILTER (
                WHERE primary_taxonomy_code_v2 IS NOT NULL
            )::UBIGINT AS npis_with_taxonomy,
            count(*) FILTER (
                WHERE physician_md_do_flag_v2
            )::UBIGINT AS md_do_npis
        FROM provider_master_v2
        WHERE ed_observed_flag
        GROUP BY source_status, provider_entity_category_v2
        ORDER BY source_status, provider_entity_category_v2
        """,
        qa_root / "provider_master_v2_source_coverage.csv",
    )
    copy_csv(
        con,
        """
        SELECT
            CASE
                WHEN physician_md_do_flag_v2 THEN 'MD/DO physician'
                ELSE clinician_type_v2
            END AS clinician_group,
            count(*)::UBIGINT AS ed_observed_unique_npis,
            sum(ed_attending_visit_count)::UBIGINT AS attending_visits,
            count(*) FILTER (
                WHERE is_cms_clinician
            )::UBIGINT AS phase1_legacy_cms_unique_npis,
            count(*) FILTER (
                WHERE cms_current_snapshot_match_flag
            )::UBIGINT AS current_cms_unique_npis,
            count(*) FILTER (
                WHERE cms_current_snapshot_match_flag
                  AND NOT coalesce(is_cms_clinician, false)
            )::UBIGINT AS newly_current_cms_covered_unique_npis,
            sum(ed_attending_visit_count) FILTER (
                WHERE cms_current_snapshot_match_flag
                  AND NOT coalesce(is_cms_clinician, false)
            )::UBIGINT AS newly_current_cms_covered_attending_visits,
            count(*) FILTER (
                WHERE cms_gender_v2 IN ('Male', 'Female')
                  AND (
                    cms_gender IS NULL
                    OR cms_gender NOT IN ('M', 'F')
                  )
            )::UBIGINT AS current_cms_gender_newly_filled_unique_npis,
            sum(ed_attending_visit_count) FILTER (
                WHERE cms_gender_v2 IN ('Male', 'Female')
                  AND (
                    cms_gender IS NULL
                    OR cms_gender NOT IN ('M', 'F')
                  )
            )::UBIGINT AS current_cms_gender_newly_filled_attending_visits,
            count(*) FILTER (
                WHERE cms_gender_v2 IN ('Male', 'Female')
                  AND cms_gender IN ('M', 'F')
                  AND cms_gender_v2 <> CASE cms_gender
                    WHEN 'M' THEN 'Male'
                    WHEN 'F' THEN 'Female'
                  END
            )::UBIGINT AS current_vs_legacy_cms_gender_changed_unique_npis,
            sum(ed_attending_visit_count) FILTER (
                WHERE cms_gender_v2 IN ('Male', 'Female')
                  AND cms_gender IN ('M', 'F')
                  AND cms_gender_v2 <> CASE cms_gender
                    WHEN 'M' THEN 'Male'
                    WHEN 'F' THEN 'Female'
                  END
            )::UBIGINT AS current_vs_legacy_cms_gender_changed_attending_visits,
            count(*) FILTER (
                WHERE cms_primary_specialty_v2 IS NOT NULL
                  AND cms_primary_specialty IS NULL
            )::UBIGINT AS current_cms_specialty_newly_filled_unique_npis,
            count(*) FILTER (
                WHERE cms_medical_school_v2 IS NOT NULL
                  AND cms_medical_school IS NULL
            )::UBIGINT AS current_cms_school_newly_filled_unique_npis,
            count(*) FILTER (
                WHERE cms_grad_year_v2 IS NOT NULL
                  AND cms_grad_year IS NULL
            )::UBIGINT AS current_cms_grad_year_newly_filled_unique_npis,
            count(*) FILTER (
                WHERE has_cms_current_facility_affiliation_v2
            )::UBIGINT AS current_cms_facility_affiliation_unique_npis,
            sum(ed_attending_visit_count) FILTER (
                WHERE has_cms_current_facility_affiliation_v2
            )::UBIGINT AS current_cms_facility_affiliation_attending_visits
        FROM provider_master_v2
        WHERE ed_observed_flag
        GROUP BY clinician_group
        ORDER BY clinician_group
        """,
        qa_root / "provider_master_v2_current_vs_legacy_cms.csv",
    )

    metrics = {
        "master_rows": int(
            con.execute("SELECT count(*) FROM provider_master_v2").fetchone()[0]
        ),
        "distinct_npis": int(
            con.execute(
                "SELECT count(DISTINCT npi) FROM provider_master_v2"
            ).fetchone()[0]
        ),
        "duplicate_npis": int(
            con.execute(
                """
                SELECT count(*) FROM (
                    SELECT npi
                    FROM provider_master_v2
                    GROUP BY npi
                    HAVING count(*) > 1
                )
                """
            ).fetchone()[0]
        ),
        "phase1_master_rows": int(
            con.execute("SELECT count(*) FROM phase1_master").fetchone()[0]
        ),
        "ed_observed_distinct_npis": int(
            con.execute("SELECT count(*) FROM provider_summary").fetchone()[0]
        ),
        "ed_observed_npis_missing_phase1": int(
            con.execute(
                """
                SELECT count(*)
                FROM provider_master_v2
                WHERE ed_observed_flag AND NOT phase1_master_match_flag
                """
            ).fetchone()[0]
        ),
        "ed_observed_npis_missing_current_nppes": int(
            con.execute(
                """
                SELECT count(*)
                FROM provider_master_v2
                WHERE ed_observed_flag
                  AND NOT nppes_current_snapshot_match_flag
                """
            ).fetchone()[0]
        ),
        "ed_observed_npis_absent_master_v2": int(
            con.execute(
                """
                SELECT count(*)
                FROM provider_summary s
                LEFT JOIN provider_master_v2 m ON s.npi = m.npi
                WHERE m.npi IS NULL
                """
            ).fetchone()[0]
        ),
        "ed_observed_invalid_checksum_npis": int(
            con.execute(
                """
                SELECT count(*)
                FROM provider_master_v2
                WHERE ed_observed_flag AND NOT npi_checksum_valid_v2
                """
            ).fetchone()[0]
        ),
        "ed_selected_role_visits": int(
            con.execute(
                "SELECT sum(ed_visit_count) FROM provider_qfr"
            ).fetchone()[0]
        ),
        "ed_observed_individual_npis": int(
            con.execute(
                """
                SELECT count(*)
                FROM provider_master_v2
                WHERE ed_observed_flag
                  AND provider_entity_category_v2 = 'Individual'
                """
            ).fetchone()[0]
        ),
        "ed_observed_md_do_npis": int(
            con.execute(
                """
                SELECT count(*)
                FROM provider_master_v2
                WHERE ed_observed_flag AND physician_md_do_flag_v2
                """
            ).fetchone()[0]
        ),
        "ed_observed_npis_matched_current_cms": int(
            con.execute(
                """
                SELECT count(*)
                FROM provider_master_v2
                WHERE ed_observed_flag
                  AND cms_current_snapshot_match_flag
                """
            ).fetchone()[0]
        ),
        "ed_observed_npis_with_current_cms_facility_affiliation": int(
            con.execute(
                """
                SELECT count(*)
                FROM provider_master_v2
                WHERE ed_observed_flag
                  AND has_cms_current_facility_affiliation_v2
                """
            ).fetchone()[0]
        ),
        "ed_observed_md_do_npis_with_current_cms_facility_affiliation": int(
            con.execute(
                """
                SELECT count(*)
                FROM provider_master_v2
                WHERE ed_observed_flag
                  AND physician_md_do_flag_v2
                  AND has_cms_current_facility_affiliation_v2
                """
            ).fetchone()[0]
        ),
        "ed_attending_visits_with_current_cms_facility_affiliation": int(
            con.execute(
                """
                SELECT sum(q.ed_visit_count)
                FROM provider_qfr q
                INNER JOIN provider_master_v2 m ON q.npi = m.npi
                WHERE q.provider_role = 'attending'
                  AND m.has_cms_current_facility_affiliation_v2
                """
            ).fetchone()[0]
            or 0
        ),
        "ed_md_do_attending_visits_with_current_cms_facility_affiliation": int(
            con.execute(
                """
                SELECT sum(q.ed_visit_count)
                FROM provider_qfr q
                INNER JOIN provider_master_v2 m ON q.npi = m.npi
                WHERE q.provider_role = 'attending'
                  AND m.physician_md_do_flag_v2
                  AND m.has_cms_current_facility_affiliation_v2
                """
            ).fetchone()[0]
            or 0
        ),
        "cms_current_provider_cache_rows": int(
            con.execute(
                "SELECT count(*) FROM cms_current_provider"
            ).fetchone()[0]
        ),
        "cms_current_facility_affiliation_cache_rows": int(
            con.execute(
                "SELECT count(*) FROM cms_current_facility_affiliation"
            ).fetchone()[0]
        ),
        "provider_year_rows": int(
            con.execute("SELECT count(*) FROM provider_year_v2").fetchone()[0]
        ),
        "provider_facility_year_role_rows": int(
            con.execute(
                "SELECT count(*) FROM provider_facility_year_role"
            ).fetchone()[0]
        ),
    }
    metrics["qa_passed"] = (
        metrics["master_rows"] == metrics["distinct_npis"]
        and metrics["duplicate_npis"] == 0
        and metrics["ed_observed_npis_absent_master_v2"] == 0
        and metrics["ed_observed_invalid_checksum_npis"] == 0
        and metrics["ed_selected_role_visits"] > 0
        and metrics["cms_current_provider_cache_rows"] > 0
        and metrics[
            "cms_current_facility_affiliation_cache_rows"
        ] > 0
    )
    metrics["build_spec_version"] = PROVIDER_MASTER_BUILD_SPEC_VERSION
    metrics["build_completed_utc"] = utc_now()
    metrics["temporal_interpretation"] = {
        "encounter_year_valid": [
            "ED provider role",
            "ED visit volume",
            "ED-observed provider-facility relationship",
            "experience calculated from encounter year and graduation year",
        ],
        "cross_sectional_not_assumed_historical": [
            "NPPES name, taxonomy, gender, and practice address",
            "CMS specialty, group, school, and graduation fields",
            "Florida DOH profile, license, education, certification, and privileges",
        ],
    }
    atomic_json(qa_root / "provider_master_v2_qa.json", metrics)

    schema_rows = con.execute(
        "DESCRIBE SELECT * FROM provider_master_v2"
    ).fetchall()
    schema_payload = {
        "dataset": "provider_master_v2.parquet",
        "grain": "one row per NPI in Phase 1 master union all ED-observed selected NPIs",
        "column_count": len(schema_rows),
        "columns": [
            {
                "name": row[0],
                "duckdb_type": row[1],
                "nullable": row[2],
                "key": "primary key" if row[0] == "npi" else None,
            }
            for row in schema_rows
        ],
        "temporal_warning": (
            "Current NPPES/CMS/DOH attributes are cross-sectional and must not "
            "be interpreted as encounter-year values. Use provider_year_v2 and "
            "provider_facility_year_v2 for encounter-year observation fields."
        ),
    }
    atomic_json(
        dimensions / "provider_master_v2_schema.json",
        schema_payload,
    )

    print("9/10 Capturing source provenance", flush=True)
    source_manifest = {
        "created_utc": utc_now(),
        "purpose": "Phase 2 encounter-universe provider master v2",
        "build_spec_version": PROVIDER_MASTER_BUILD_SPEC_VERSION,
        "sources": {
            "phase1_physician_master": source_record(phase1_master, True),
            "nppes_minimal_extract": source_record(nppes_minimal, True),
            "nppes_full_february_2026": source_record(
                nppes_full, args.hash_large_sources
            ),
            "cms_doctors_clinicians_national_downloadable_2026_06_26": (
                source_record(cms_current, True)
            ),
            "cms_doctors_clinicians_facility_affiliation_2026_06_26": (
                source_record(cms_facility_affiliation, True)
            ),
            "cms_doctors_clinicians_local_manifest": source_record(
                cms_current_manifest, True
            ),
            "nucc_taxonomy": source_record(taxonomy, True),
        },
        "phase1_release_preserved": True,
        "notes": [
            "Legacy CMS and Florida DOH fields are retained from the immutable Phase 1 physician master.",
            "Current CMS clinician and facility-affiliation fields are refreshed directly from the June 26, 2026 CMS files and use explicit _v2 names.",
            "Current CMS facility affiliation is cross-sectional public-reporting evidence; it is not assumed to be an encounter-year employment relationship.",
            "Every selected NPI observed in attending, operating/performing, or other-practitioner ED roles is included by construction.",
            "NPPES practice location is a business-practice address and is not a residential address.",
        ],
    }
    atomic_json(
        qa_root / "provider_master_v2_source_manifest.json",
        source_manifest,
    )

    print("10/10 Finalizing provider master v2", flush=True)
    if not metrics["qa_passed"]:
        raise RuntimeError(
            "Provider master v2 failed QA; see provider_master_v2_qa.json"
        )
    success_payload = {
        "qa_passed": True,
        "build_spec_version": PROVIDER_MASTER_BUILD_SPEC_VERSION,
        "completed_utc": utc_now(),
        "outputs": {
            "provider_master_v2": str(master_out),
            "provider_year_v2": str(year_out),
            "provider_facility_year_v2": str(facility_year_out),
        },
        "metrics": metrics,
    }
    atomic_json(success, success_payload)
    print(json.dumps(success_payload, indent=2), flush=True)


if __name__ == "__main__":
    main()
