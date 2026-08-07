# Sanitized portfolio copy of the validated production script.
# Original: outputs/florida_ed_full_build_20260724/scripts/build_physician_master.py
# Purchased/public reference roots and runtime output locations are environment-configured.

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


DATASET_ROOT = Path(os.environ.get("FL_ED_DATASET_ROOT", "private_data")).expanduser()
PROJECT_ROOT = Path(
    os.environ.get("FL_ED_PROJECT_ROOT", str(DATASET_ROOT.parent))
).expanduser()
DICTIONARY_ROOT = Path(
    os.environ.get("FL_ED_DICTIONARY_ROOT", str(PROJECT_ROOT / "Dictionary"))
).expanduser()
OUTPUT_DIR = Path(
    os.environ.get(
        "FL_ED_PHASE1_PROVIDER_OUTPUT",
        str(DATASET_ROOT / "outputs" / "florida_ed_standardization_20260724"),
    )
).expanduser()
TMP_DIR = Path(
    os.environ.get(
        "FL_ED_PHASE1_PROVIDER_SCRATCH",
        str(DATASET_ROOT / "tmp" / "florida_ed_standardization_20260724"),
    )
).expanduser()
PYDEPS_DIR = Path(
    os.environ.get("FL_ED_PYDEPS", str(TMP_DIR / "pydeps"))
).expanduser()

if PYDEPS_DIR.exists():
    sys.path.insert(0, str(PYDEPS_DIR))

import duckdb  # noqa: E402


NPPES_BASE = (
    DICTIONARY_ROOT
    / "Physician"
    / "_derived_master_decoder"
    / "nppes_base_minimal.parquet"
)
NPPES_FL_LICENSE = (
    DICTIONARY_ROOT
    / "Physician"
    / "_derived_master_decoder"
    / "nppes_fl_license_xwalk.parquet"
)
DOH_BEST = (
    DICTIONARY_ROOT
    / "Physician"
    / "_derived_master_decoder"
    / "doh_enrichment_best_per_npi.parquet"
)
DOH_PROFILE_GLOB = DICTIONARY_ROOT / "Physician" / "[0-9]*-P.txt"
CMS_DAC = DICTIONARY_ROOT / "Physician" / "DAC_NationalDownloadableFile.csv"
DOH_EDUCATION = DICTIONARY_ROOT / "Physician" / "education_fixed.txt"
DOH_CERTIFICATIONS = (
    DICTIONARY_ROOT / "Physician" / "tp_certifications_fixed.txt"
)
DOH_POSTGRAD = DICTIONARY_ROOT / "Physician" / "tp_prof_post_grad_fixed.txt"
DOH_STAFF = DICTIONARY_ROOT / "Physician" / "tp_staff_priv_fixed.txt"
DOH_OTHER_DEG = DICTIONARY_ROOT / "Physician" / "tp_other_health_dg_fixed.txt"
NUCC_TAXONOMY = DICTIONARY_ROOT / "Sample05Q1ED" / "nucc_taxonomy_250.csv"
CENSUS_SURNAMES = DICTIONARY_ROOT / "Demographic" / "Names_2010Census.csv"
SSA_NAMES_GLOB = DICTIONARY_ROOT / "Demographic" / "names_sex" / "yob*.txt"


def sql_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace("'", "''")


def check_sources() -> None:
    required = [
        NPPES_BASE,
        NPPES_FL_LICENSE,
        CMS_DAC,
        DOH_EDUCATION,
        DOH_CERTIFICATIONS,
        DOH_POSTGRAD,
        DOH_STAFF,
        DOH_OTHER_DEG,
        NUCC_TAXONOMY,
        CENSUS_SURNAMES,
    ]
    if not list(DOH_PROFILE_GLOB.parent.glob(DOH_PROFILE_GLOB.name)):
        missing.append(str(DOH_PROFILE_GLOB))
    missing = [str(path) for path in required if not path.exists()]
    if not list(SSA_NAMES_GLOB.parent.glob(SSA_NAMES_GLOB.name)):
        missing.append(str(SSA_NAMES_GLOB))
    if missing:
        raise FileNotFoundError("Missing required physician sources:\n" + "\n".join(missing))


def build_database(con: duckdb.DuckDBPyConnection) -> None:
    cms_path = sql_path(CMS_DAC)
    nppes_path = sql_path(NPPES_BASE)
    xwalk_path = sql_path(NPPES_FL_LICENSE)
    doh_profile_glob = sql_path(DOH_PROFILE_GLOB)
    taxonomy_path = sql_path(NUCC_TAXONOMY)
    census_path = sql_path(CENSUS_SURNAMES)
    ssa_glob = sql_path(SSA_NAMES_GLOB)

    print("1/9 Aggregating CMS Doctors and Clinicians data", flush=True)
    con.execute(
        f"""
        CREATE OR REPLACE TABLE cms_agg AS
        WITH src AS (
            SELECT
                trim(npi) AS npi,
                nullif(trim(provider_last_name), '') AS last_name,
                nullif(trim(provider_first_name), '') AS first_name,
                nullif(trim(provider_middle_name), '') AS middle_name,
                nullif(trim(suff), '') AS suffix,
                upper(nullif(trim(gndr), '')) AS gender,
                upper(nullif(trim(cred), '')) AS credential,
                nullif(trim(med_sch), '') AS medical_school,
                try_cast(nullif(trim(grd_yr), '') AS INTEGER) AS grad_year,
                nullif(trim(pri_spec), '') AS primary_specialty,
                nullif(trim(sec_spec_all), '') AS secondary_specialties,
                upper(nullif(trim(telehlth), '')) AS telehealth,
                nullif(trim(facility_name), '') AS group_practice_name,
                nullif(trim(org_pac_id), '') AS group_pac_id,
                try_cast(nullif(trim(num_org_mem), '') AS INTEGER) AS group_member_count,
                nullif(trim(citytown), '') AS city,
                upper(nullif(trim(state), '')) AS state,
                nullif(trim(zip_code), '') AS zip_code
            FROM read_csv(
                '{cms_path}',
                header = true,
                auto_detect = true,
                all_varchar = true,
                normalize_names = true,
                sample_size = 200000,
                ignore_errors = true,
                null_padding = true
            )
            WHERE regexp_full_match(trim(npi), '[0-9]{{10}}')
        )
        SELECT
            npi,
            mode(last_name) AS cms_last_name,
            mode(first_name) AS cms_first_name,
            mode(middle_name) AS cms_middle_name,
            mode(suffix) AS cms_suffix,
            mode(gender) FILTER (WHERE gender IN ('M', 'F', 'U')) AS cms_gender,
            string_agg(DISTINCT credential, ' | ' ORDER BY credential)
                FILTER (WHERE credential IS NOT NULL) AS cms_credentials,
            mode(medical_school) AS cms_medical_school,
            mode(grad_year) FILTER (
                WHERE grad_year BETWEEN 1900 AND year(current_date)
            ) AS cms_grad_year,
            count(DISTINCT grad_year) FILTER (
                WHERE grad_year BETWEEN 1900 AND year(current_date)
            ) AS cms_grad_year_distinct_count,
            mode(primary_specialty) AS cms_primary_specialty,
            string_agg(DISTINCT primary_specialty, ' | ' ORDER BY primary_specialty)
                FILTER (WHERE primary_specialty IS NOT NULL) AS cms_primary_specialty_values,
            string_agg(DISTINCT secondary_specialties, ' | ' ORDER BY secondary_specialties)
                FILTER (WHERE secondary_specialties IS NOT NULL) AS cms_secondary_specialties,
            max(CASE WHEN telehealth = 'Y' THEN 1 ELSE 0 END)::BOOLEAN
                AS cms_telehealth_flag,
            count(DISTINCT group_pac_id) FILTER (
                WHERE group_pac_id IS NOT NULL
            ) AS cms_group_practice_count,
            string_agg(DISTINCT group_practice_name, ' | ' ORDER BY group_practice_name)
                FILTER (WHERE group_practice_name IS NOT NULL) AS cms_group_practice_names,
            string_agg(DISTINCT group_pac_id, ' | ' ORDER BY group_pac_id)
                FILTER (WHERE group_pac_id IS NOT NULL) AS cms_group_pac_ids,
            max(group_member_count) AS cms_largest_group_member_count,
            string_agg(DISTINCT state, ' | ' ORDER BY state)
                FILTER (WHERE state IS NOT NULL) AS cms_practice_states,
            mode(city) AS cms_primary_city,
            mode(state) AS cms_primary_state,
            mode(zip_code) AS cms_primary_zip,
            count(*) AS cms_source_row_count
        FROM src
        GROUP BY npi
        """
    )

    print("2/9 Preparing NPPES clinician and Florida-license sources", flush=True)
    con.execute(
        f"""
        CREATE OR REPLACE TABLE fl_license_agg AS
        SELECT
            trim(NPI) AS npi,
            count(DISTINCT nullif(trim(license_number_norm), '')) AS fl_license_count,
            string_agg(
                DISTINCT nullif(trim(license_number_norm), ''),
                ' | ' ORDER BY nullif(trim(license_number_norm), '')
            ) FILTER (WHERE nullif(trim(license_number_norm), '') IS NOT NULL)
                AS fl_license_numbers,
            min(license_slot) AS first_license_slot
        FROM read_parquet('{xwalk_path}')
        WHERE regexp_full_match(trim(NPI), '[0-9]{{10}}')
        GROUP BY trim(NPI)
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TABLE base_npis AS
        SELECT npi FROM cms_agg
        UNION
        SELECT npi FROM fl_license_agg
        """
    )

    taxonomy_pairs = []
    taxonomy_codes = []
    taxonomy_ed_tests = []
    for i in range(1, 16):
        code = f'nullif(trim(n."Healthcare Provider Taxonomy Code_{i}"), \'\')'
        switch = f'upper(nullif(trim(n."Healthcare Provider Primary Taxonomy Switch_{i}"), \'\'))'
        taxonomy_pairs.append(f"CASE WHEN {switch} = 'Y' THEN {code} END")
        taxonomy_codes.append(code)
        taxonomy_ed_tests.append(f"{code} LIKE '207P%'")
    primary_taxonomy = "coalesce(" + ", ".join(taxonomy_pairs + taxonomy_codes) + ")"
    all_taxonomy = "concat_ws(' | ', " + ", ".join(taxonomy_codes) + ")"
    any_ed = " OR ".join(taxonomy_ed_tests)

    con.execute(
        f"""
        CREATE OR REPLACE TABLE nppes_selected AS
        SELECT
            trim(n.NPI) AS npi,
            trim(n."Entity Type Code") AS nppes_entity_type_code,
            nullif(trim(n."Provider Last Name (Legal Name)"), '') AS nppes_last_name,
            nullif(trim(n."Provider First Name"), '') AS nppes_first_name,
            nullif(trim(n."Provider Middle Name"), '') AS nppes_middle_name,
            nullif(trim(n."Provider Name Prefix Text"), '') AS nppes_prefix,
            nullif(trim(n."Provider Name Suffix Text"), '') AS nppes_suffix,
            nullif(trim(n."Provider Credential Text"), '') AS nppes_credential,
            upper(nullif(trim(n."Provider Sex Code"), '')) AS nppes_gender,
            nullif(trim(n."Provider Business Practice Location Address City Name"), '')
                AS nppes_practice_city,
            upper(nullif(trim(n."Provider Business Practice Location Address State Name"), ''))
                AS nppes_practice_state,
            nullif(trim(n."Provider Business Practice Location Address Postal Code"), '')
                AS nppes_practice_zip,
            nullif(trim(n.full_name_nppes), '') AS nppes_full_name,
            {primary_taxonomy} AS primary_taxonomy_code,
            nullif({all_taxonomy}, '') AS all_taxonomy_codes,
            ({any_ed}) AS nppes_any_ed_taxonomy_flag
        FROM read_parquet('{nppes_path}') n
        INNER JOIN base_npis b ON trim(n.NPI) = b.npi
        WHERE trim(n."Entity Type Code") = '1'
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TABLE taxonomy_decoder AS
        SELECT
            upper(trim(Code)) AS taxonomy_code,
            nullif(trim(Grouping), '') AS taxonomy_grouping,
            nullif(trim(Classification), '') AS taxonomy_classification,
            nullif(trim(Specialization), '') AS taxonomy_specialization,
            nullif(trim("Display Name"), '') AS taxonomy_display_name
        FROM read_csv(
            '{taxonomy_path}',
            header = true,
            auto_detect = true,
            all_varchar = true,
            normalize_names = false
        )
        """
    )

    print("3/9 Rebuilding Florida DOH education and affiliation enrichments", flush=True)
    doh_csv_options = """
        header = true,
        delim = '|',
        auto_detect = true,
        all_varchar = true,
        normalize_names = true,
        sample_size = 200000,
        ignore_errors = true,
        null_padding = true
    """
    con.execute(
        f"""
        CREATE OR REPLACE TABLE doh_education_agg AS
        WITH src AS (
            SELECT
                trim(lic_id) AS lic_id,
                nullif(trim(inst_nme), '') AS institution,
                nullif(trim(grad_dte), '') AS grad_date_text,
                try_strptime(nullif(trim(grad_dte), ''), '%m/%d/%Y') AS grad_date,
                nullif(trim(deg_cert_earn_cde), '') AS degree_code,
                nullif(trim(pgm_desc), '') AS program_description,
                nullif(trim(educ_mjr), '') AS education_major
            FROM read_csv('{sql_path(DOH_EDUCATION)}', {doh_csv_options})
            WHERE nullif(trim(lic_id), '') IS NOT NULL
        )
        SELECT
            lic_id,
            arg_max(institution, grad_date) FILTER (
                WHERE year(grad_date) BETWEEN 1900 AND year(current_date)
            ) AS doh_medical_school_selected,
            max(year(grad_date)) FILTER (
                WHERE year(grad_date) BETWEEN 1900 AND year(current_date)
            ) AS doh_grad_year_selected,
            string_agg(DISTINCT institution, ' | ' ORDER BY institution)
                FILTER (WHERE institution IS NOT NULL) AS doh_education_institutions,
            string_agg(DISTINCT grad_date_text, ' | ' ORDER BY grad_date_text)
                FILTER (WHERE grad_date_text IS NOT NULL) AS doh_grad_dates,
            string_agg(DISTINCT degree_code, ' | ' ORDER BY degree_code)
                FILTER (WHERE degree_code IS NOT NULL) AS doh_degree_codes,
            string_agg(DISTINCT program_description, ' | ' ORDER BY program_description)
                FILTER (WHERE program_description IS NOT NULL) AS doh_program_descriptions,
            string_agg(DISTINCT education_major, ' | ' ORDER BY education_major)
                FILTER (WHERE education_major IS NOT NULL) AS doh_education_majors,
            count(*) AS doh_education_row_count
        FROM src
        GROUP BY lic_id
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TABLE doh_certification_agg AS
        SELECT
            trim(lic_id) AS lic_id,
            string_agg(DISTINCT nullif(trim(specialty_brd), ''), ' | '
                ORDER BY nullif(trim(specialty_brd), ''))
                FILTER (WHERE nullif(trim(specialty_brd), '') IS NOT NULL)
                AS doh_certifying_boards,
            string_agg(DISTINCT nullif(trim(specialty_cert), ''), ' | '
                ORDER BY nullif(trim(specialty_cert), ''))
                FILTER (WHERE nullif(trim(specialty_cert), '') IS NOT NULL)
                AS doh_board_certifications,
            string_agg(DISTINCT nullif(trim(specialty_dte), ''), ' | '
                ORDER BY nullif(trim(specialty_dte), ''))
                FILTER (WHERE nullif(trim(specialty_dte), '') IS NOT NULL)
                AS doh_certification_dates,
            count(DISTINCT nullif(trim(specialty_cert), '')) AS doh_board_certification_count
        FROM read_csv('{sql_path(DOH_CERTIFICATIONS)}', {doh_csv_options})
        WHERE nullif(trim(lic_id), '') IS NOT NULL
        GROUP BY trim(lic_id)
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TABLE doh_postgrad_agg AS
        SELECT
            trim(lic_id) AS lic_id,
            string_agg(DISTINCT nullif(trim(program_spclty_ar), ''), ' | '
                ORDER BY nullif(trim(program_spclty_ar), ''))
                FILTER (WHERE nullif(trim(program_spclty_ar), '') IS NOT NULL)
                AS doh_postgrad_specialties,
            string_agg(DISTINCT nullif(trim(program_type), ''), ' | '
                ORDER BY nullif(trim(program_type), ''))
                FILTER (WHERE nullif(trim(program_type), '') IS NOT NULL)
                AS doh_postgrad_types,
            string_agg(DISTINCT nullif(trim(institute_name), ''), ' | '
                ORDER BY nullif(trim(institute_name), ''))
                FILTER (WHERE nullif(trim(institute_name), '') IS NOT NULL)
                AS doh_postgrad_institutions,
            count(*) AS doh_postgrad_row_count
        FROM read_csv('{sql_path(DOH_POSTGRAD)}', {doh_csv_options})
        WHERE nullif(trim(lic_id), '') IS NOT NULL
        GROUP BY trim(lic_id)
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TABLE doh_staff_agg AS
        SELECT
            trim(lic_id) AS lic_id,
            string_agg(DISTINCT nullif(trim(hospital_instit), ''), ' | '
                ORDER BY nullif(trim(hospital_instit), ''))
                FILTER (WHERE nullif(trim(hospital_instit), '') IS NOT NULL)
                AS doh_hospital_privileges,
            string_agg(DISTINCT upper(nullif(trim(state), '')), ' | '
                ORDER BY upper(nullif(trim(state), '')))
                FILTER (WHERE nullif(trim(state), '') IS NOT NULL)
                AS doh_hospital_privilege_states,
            count(DISTINCT nullif(trim(hospital_instit), ''))
                AS doh_hospital_privilege_count
        FROM read_csv('{sql_path(DOH_STAFF)}', {doh_csv_options})
        WHERE nullif(trim(lic_id), '') IS NOT NULL
        GROUP BY trim(lic_id)
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TABLE doh_other_degree_agg AS
        SELECT
            trim(lic_id) AS lic_id,
            string_agg(DISTINCT nullif(trim(degree_title), ''), ' | '
                ORDER BY nullif(trim(degree_title), ''))
                FILTER (WHERE nullif(trim(degree_title), '') IS NOT NULL)
                AS doh_other_degree_titles,
            string_agg(DISTINCT nullif(trim(school_name), ''), ' | '
                ORDER BY nullif(trim(school_name), ''))
                FILTER (WHERE nullif(trim(school_name), '') IS NOT NULL)
                AS doh_other_degree_schools,
            count(*) AS doh_other_degree_row_count
        FROM read_csv('{sql_path(DOH_OTHER_DEG)}', {doh_csv_options})
        WHERE nullif(trim(lic_id), '') IS NOT NULL
        GROUP BY trim(lic_id)
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TABLE doh_profile_raw AS
        WITH src AS (
            SELECT
                trim(pro_cde) AS pro_cde,
                nullif(trim(professionname), '') AS profession_name,
                trim(lic_id) AS lic_id,
                nullif(trim(expiredate), '') AS expire_date,
                nullif(trim(originaldate), '') AS original_date,
                upper(nullif(trim(rankcode), '')) AS rank_code,
                nullif(trim(licensenumber), '') AS license_number,
                nullif(trim(licensestatusdescription), '')
                    AS license_status_description,
                nullif(trim(licenseactivestatusdescription), '')
                    AS license_active_status_description,
                nullif(trim(lastname), '') AS last_name,
                nullif(trim(firstname), '') AS first_name,
                nullif(trim(middlename), '') AS middle_name,
                nullif(trim(namesuffix), '') AS name_suffix,
                nullif(trim(countydescription), '') AS county_description,
                nullif(trim(practicelocationaddresscity), '') AS practice_city,
                upper(nullif(trim(practicelocationaddressstate), ''))
                    AS practice_state,
                nullif(trim(practicelocationaddresszipcode), '') AS practice_zip,
                nullif(trim(birthyearrange), '') AS birth_year_range
            FROM read_csv(
                '{doh_profile_glob}',
                {doh_csv_options},
                union_by_name = true,
                filename = true
            )
            WHERE nullif(trim(lic_id), '') IS NOT NULL
        )
        SELECT
            *,
            rank_code || ':' ||
                coalesce(
                    nullif(ltrim(regexp_replace(license_number, '[^0-9]', '', 'g'), '0'), ''),
                    '0'
                ) AS license_join_key
        FROM src
        WHERE rank_code IS NOT NULL
          AND regexp_replace(coalesce(license_number, ''), '[^0-9]', '', 'g') <> ''
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TABLE doh_bridge AS
        WITH xwalk AS (
            SELECT
                trim(NPI) AS npi,
                nullif(trim(license_number_norm), '') AS license_number_norm,
                license_slot,
                regexp_replace(upper(coalesce(license_number_norm, '')), '[^A-Z]', '', 'g')
                    AS license_prefix,
                coalesce(
                    nullif(ltrim(
                        regexp_replace(coalesce(license_number_norm, ''), '[^0-9]', '', 'g'),
                        '0'
                    ), ''),
                    '0'
                ) AS license_digits
            FROM read_parquet('{xwalk_path}')
            WHERE regexp_full_match(trim(NPI), '[0-9]{{10}}')
        ),
        candidates AS (
            SELECT
                x.npi,
                p.lic_id,
                x.license_number_norm AS selected_license_number_norm,
                p.profession_name AS doh_profession_name,
                p.license_status_description AS doh_license_status,
                p.license_active_status_description AS doh_license_active_status,
                p.original_date AS doh_license_original_date,
                p.expire_date AS doh_license_expiration_date,
                p.county_description AS doh_practice_county,
                p.practice_city AS doh_practice_city,
                p.practice_state AS doh_practice_state,
                p.practice_zip AS doh_practice_zip,
                NULL::VARCHAR AS doh_year_began_practice,
                p.license_number AS doh_license_number,
                p.last_name AS doh_last_name,
                p.first_name AS doh_first_name,
                p.middle_name AS doh_middle_name,
                p.name_suffix AS doh_name_suffix,
                p.birth_year_range AS doh_birth_year_range,
                true AS doh_profile_match_flag,
                x.license_slot,
                row_number() OVER (
                    PARTITION BY x.npi
                    ORDER BY
                        CASE
                            WHEN upper(coalesce(p.license_active_status_description, '')) = 'ACTIVE'
                            THEN 1 ELSE 0
                        END DESC,
                        CASE
                            WHEN upper(coalesce(p.profession_name, '')) IN (
                                'MEDICAL DOCTOR', 'OSTEOPATHIC PHYSICIAN'
                            )
                            THEN 1 ELSE 0
                        END DESC,
                        x.license_slot,
                        p.lic_id
                ) AS rn
            FROM xwalk x
            INNER JOIN doh_profile_raw p
                ON x.license_prefix <> ''
               AND x.license_prefix || ':' || x.license_digits = p.license_join_key
        )
        SELECT * EXCLUDE (license_slot, rn)
        FROM candidates
        WHERE rn = 1
        """
    )

    print("4/9 Building surname-race and first-name gender reference tables", flush=True)
    con.execute(
        f"""
        CREATE OR REPLACE TABLE surname_race AS
        SELECT
            upper(regexp_replace(trim(_name), '[^A-Za-z]', '', 'g')) AS surname_key,
            try_cast(nullif(trim(pctwhite), '(S)') AS DOUBLE) / 100.0 AS prob_white,
            try_cast(nullif(trim(pctblack), '(S)') AS DOUBLE) / 100.0 AS prob_black,
            try_cast(nullif(trim(pctapi), '(S)') AS DOUBLE) / 100.0 AS prob_api,
            try_cast(nullif(trim(pctaian), '(S)') AS DOUBLE) / 100.0 AS prob_aian,
            try_cast(nullif(trim(pct2prace), '(S)') AS DOUBLE) / 100.0 AS prob_multiracial,
            try_cast(nullif(trim(pcthispanic), '(S)') AS DOUBLE) / 100.0 AS prob_hispanic
        FROM read_csv(
            '{census_path}',
            header = true,
            auto_detect = true,
            all_varchar = true,
            normalize_names = true
        )
        WHERE upper(trim(_name)) <> 'ALL OTHER NAMES'
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TABLE first_name_gender AS
        WITH src AS (
            SELECT
                upper(trim(name)) AS first_name_key,
                upper(trim(sex)) AS sex,
                try_cast(count AS BIGINT) AS name_count
            FROM read_csv(
                '{ssa_glob}',
                header = false,
                columns = {{'name':'VARCHAR', 'sex':'VARCHAR', 'count':'BIGINT'}},
                filename = true,
                ignore_errors = true
            )
        ),
        agg AS (
            SELECT
                first_name_key,
                sum(CASE WHEN sex = 'F' THEN name_count ELSE 0 END) AS female_count,
                sum(CASE WHEN sex = 'M' THEN name_count ELSE 0 END) AS male_count
            FROM src
            GROUP BY first_name_key
        )
        SELECT
            first_name_key,
            female_count,
            male_count,
            female_count::DOUBLE / nullif(female_count + male_count, 0)
                AS female_probability,
            male_count::DOUBLE / nullif(female_count + male_count, 0)
                AS male_probability,
            CASE
                WHEN female_count::DOUBLE / nullif(female_count + male_count, 0) >= 0.90
                    THEN 'Female'
                WHEN male_count::DOUBLE / nullif(female_count + male_count, 0) >= 0.90
                    THEN 'Male'
                ELSE 'Unknown/ambiguous'
            END AS imputed_gender
        FROM agg
        """
    )

    print("5/9 Building one-row-per-NPI master", flush=True)
    con.execute(
        """
        CREATE OR REPLACE TABLE physician_master_stage AS
        WITH joined AS (
            SELECT
                b.npi,
                n.nppes_entity_type_code,
                coalesce(n.nppes_last_name, c.cms_last_name, d.doh_last_name) AS last_name,
                coalesce(n.nppes_first_name, c.cms_first_name, d.doh_first_name) AS first_name,
                coalesce(n.nppes_middle_name, c.cms_middle_name, d.doh_middle_name) AS middle_name,
                coalesce(n.nppes_suffix, c.cms_suffix, d.doh_name_suffix) AS name_suffix,
                n.nppes_prefix AS name_prefix,
                coalesce(n.nppes_credential, c.cms_credentials) AS credentials,
                coalesce(
                    n.nppes_full_name,
                    trim(concat_ws(' ',
                        coalesce(n.nppes_first_name, c.cms_first_name, d.doh_first_name),
                        coalesce(n.nppes_middle_name, c.cms_middle_name, d.doh_middle_name),
                        coalesce(n.nppes_last_name, c.cms_last_name, d.doh_last_name),
                        coalesce(n.nppes_suffix, c.cms_suffix, d.doh_name_suffix)
                    ))
                ) AS full_name,
                n.nppes_gender,
                c.cms_gender,
                n.nppes_practice_city,
                n.nppes_practice_state,
                n.nppes_practice_zip,
                c.cms_primary_city,
                c.cms_primary_state,
                c.cms_primary_zip,
                d.doh_practice_city,
                d.doh_practice_state,
                d.doh_practice_zip,
                d.doh_practice_county,
                n.primary_taxonomy_code,
                n.all_taxonomy_codes,
                n.nppes_any_ed_taxonomy_flag,
                t.taxonomy_grouping,
                t.taxonomy_classification,
                t.taxonomy_specialization,
                t.taxonomy_display_name,
                c.cms_primary_specialty,
                c.cms_primary_specialty_values,
                c.cms_secondary_specialties,
                c.cms_telehealth_flag,
                c.cms_group_practice_count,
                c.cms_group_practice_names,
                c.cms_group_pac_ids,
                c.cms_largest_group_member_count,
                c.cms_practice_states,
                c.cms_source_row_count,
                c.cms_medical_school,
                c.cms_grad_year,
                c.cms_grad_year_distinct_count,
                f.fl_license_count,
                f.fl_license_numbers,
                d.lic_id AS selected_doh_lic_id,
                d.selected_license_number_norm,
                d.doh_profession_name,
                d.doh_license_status,
                d.doh_license_active_status,
                d.doh_license_original_date,
                d.doh_license_expiration_date,
                d.doh_year_began_practice,
                d.doh_license_number,
                d.doh_birth_year_range,
                d.doh_profile_match_flag,
                e.doh_medical_school_selected,
                e.doh_grad_year_selected,
                e.doh_education_institutions,
                e.doh_grad_dates,
                e.doh_degree_codes,
                e.doh_program_descriptions,
                e.doh_education_majors,
                e.doh_education_row_count,
                cert.doh_certifying_boards,
                cert.doh_board_certifications,
                cert.doh_certification_dates,
                cert.doh_board_certification_count,
                pg.doh_postgrad_specialties,
                pg.doh_postgrad_types,
                pg.doh_postgrad_institutions,
                pg.doh_postgrad_row_count,
                st.doh_hospital_privileges,
                st.doh_hospital_privilege_states,
                st.doh_hospital_privilege_count,
                od.doh_other_degree_titles,
                od.doh_other_degree_schools,
                od.doh_other_degree_row_count,
                fg.imputed_gender AS ssa_imputed_gender,
                fg.female_probability AS ssa_female_probability,
                fg.male_probability AS ssa_male_probability,
                sr.prob_white AS surname_prob_white,
                sr.prob_black AS surname_prob_black,
                sr.prob_api AS surname_prob_api,
                sr.prob_aian AS surname_prob_aian,
                sr.prob_multiracial AS surname_prob_multiracial,
                sr.prob_hispanic AS surname_prob_hispanic,
                c.npi IS NOT NULL AS is_cms_clinician,
                f.npi IS NOT NULL AS has_fl_license,
                n.npi IS NOT NULL AS has_nppes_individual_record,
                d.npi IS NOT NULL AS has_fl_doh_profile
            FROM base_npis b
            LEFT JOIN nppes_selected n ON b.npi = n.npi
            LEFT JOIN cms_agg c ON b.npi = c.npi
            LEFT JOIN fl_license_agg f ON b.npi = f.npi
            LEFT JOIN doh_bridge d ON b.npi = d.npi
            LEFT JOIN taxonomy_decoder t
                ON upper(n.primary_taxonomy_code) = t.taxonomy_code
            LEFT JOIN doh_education_agg e ON d.lic_id = e.lic_id
            LEFT JOIN doh_certification_agg cert ON d.lic_id = cert.lic_id
            LEFT JOIN doh_postgrad_agg pg ON d.lic_id = pg.lic_id
            LEFT JOIN doh_staff_agg st ON d.lic_id = st.lic_id
            LEFT JOIN doh_other_degree_agg od ON d.lic_id = od.lic_id
            LEFT JOIN first_name_gender fg
                ON upper(coalesce(n.nppes_first_name, c.cms_first_name, d.doh_first_name))
                    = fg.first_name_key
            LEFT JOIN surname_race sr
                ON upper(regexp_replace(
                    coalesce(n.nppes_last_name, c.cms_last_name, d.doh_last_name),
                    '[^A-Za-z]', '', 'g'
                )) = sr.surname_key
        )
        SELECT
            *,
            CASE
                WHEN nppes_gender = 'M' THEN 'Male'
                WHEN nppes_gender = 'F' THEN 'Female'
                WHEN cms_gender = 'M' THEN 'Male'
                WHEN cms_gender = 'F' THEN 'Female'
                WHEN ssa_imputed_gender IN ('Male', 'Female') THEN ssa_imputed_gender
                ELSE 'Unknown'
            END AS gender_category,
            CASE
                WHEN nppes_gender IN ('M', 'F') THEN 'NPPES'
                WHEN cms_gender IN ('M', 'F') THEN 'CMS Doctors and Clinicians'
                WHEN ssa_imputed_gender IN ('Male', 'Female')
                    THEN 'SSA first-name imputation (>=90% probability)'
                ELSE 'Unknown'
            END AS gender_source,
            CASE
                WHEN greatest(
                    coalesce(surname_prob_white, -1),
                    coalesce(surname_prob_black, -1),
                    coalesce(surname_prob_api, -1),
                    coalesce(surname_prob_aian, -1),
                    coalesce(surname_prob_multiracial, -1),
                    coalesce(surname_prob_hispanic, -1)
                ) < 0 THEN 'Unknown'
                WHEN coalesce(surname_prob_hispanic, -1) = greatest(
                    coalesce(surname_prob_white, -1),
                    coalesce(surname_prob_black, -1),
                    coalesce(surname_prob_api, -1),
                    coalesce(surname_prob_aian, -1),
                    coalesce(surname_prob_multiracial, -1),
                    coalesce(surname_prob_hispanic, -1)
                ) THEN 'Hispanic'
                WHEN coalesce(surname_prob_black, -1) = greatest(
                    coalesce(surname_prob_white, -1),
                    coalesce(surname_prob_black, -1),
                    coalesce(surname_prob_api, -1),
                    coalesce(surname_prob_aian, -1),
                    coalesce(surname_prob_multiracial, -1),
                    coalesce(surname_prob_hispanic, -1)
                ) THEN 'Non-Hispanic Black'
                WHEN coalesce(surname_prob_api, -1) = greatest(
                    coalesce(surname_prob_white, -1),
                    coalesce(surname_prob_black, -1),
                    coalesce(surname_prob_api, -1),
                    coalesce(surname_prob_aian, -1),
                    coalesce(surname_prob_multiracial, -1),
                    coalesce(surname_prob_hispanic, -1)
                ) THEN 'Non-Hispanic Asian/Pacific Islander'
                WHEN coalesce(surname_prob_aian, -1) = greatest(
                    coalesce(surname_prob_white, -1),
                    coalesce(surname_prob_black, -1),
                    coalesce(surname_prob_api, -1),
                    coalesce(surname_prob_aian, -1),
                    coalesce(surname_prob_multiracial, -1),
                    coalesce(surname_prob_hispanic, -1)
                ) THEN 'Non-Hispanic American Indian/Alaska Native'
                WHEN coalesce(surname_prob_multiracial, -1) = greatest(
                    coalesce(surname_prob_white, -1),
                    coalesce(surname_prob_black, -1),
                    coalesce(surname_prob_api, -1),
                    coalesce(surname_prob_aian, -1),
                    coalesce(surname_prob_multiracial, -1),
                    coalesce(surname_prob_hispanic, -1)
                ) THEN 'Non-Hispanic Multiracial'
                ELSE 'Non-Hispanic White'
            END AS surname_imputed_race_ethnicity,
            greatest(
                surname_prob_white,
                surname_prob_black,
                surname_prob_api,
                surname_prob_aian,
                surname_prob_multiracial,
                surname_prob_hispanic
            ) AS surname_imputation_max_probability,
            CASE
                WHEN surname_prob_white IS NULL
                    AND surname_prob_black IS NULL
                    AND surname_prob_api IS NULL
                    AND surname_prob_aian IS NULL
                    AND surname_prob_multiracial IS NULL
                    AND surname_prob_hispanic IS NULL
                    THEN 'Unknown'
                ELSE '2010 U.S. Census surname-only imputation'
            END AS race_ethnicity_source,
            coalesce(cms_medical_school, doh_medical_school_selected) AS medical_school_selected,
            CASE
                WHEN cms_medical_school IS NOT NULL THEN 'CMS Doctors and Clinicians'
                WHEN doh_medical_school_selected IS NOT NULL THEN 'Florida DOH education'
                ELSE 'Unknown'
            END AS medical_school_source,
            coalesce(cms_grad_year, doh_grad_year_selected) AS medical_school_grad_year,
            CASE
                WHEN cms_grad_year IS NOT NULL THEN 'CMS Doctors and Clinicians'
                WHEN doh_grad_year_selected IS NOT NULL THEN 'Florida DOH education'
                ELSE 'Unknown'
            END AS medical_school_grad_year_source,
            CASE
                WHEN coalesce(cms_grad_year, doh_grad_year_selected) BETWEEN 1900 AND 2005
                    THEN 2005 - coalesce(cms_grad_year, doh_grad_year_selected)
            END AS years_since_medical_school_2005,
            CASE
                WHEN coalesce(cms_grad_year, doh_grad_year_selected) BETWEEN 1900 AND 2024
                    THEN 2024 - coalesce(cms_grad_year, doh_grad_year_selected)
            END AS years_since_medical_school_2024,
            CASE
                WHEN coalesce(nppes_any_ed_taxonomy_flag, false)
                    OR upper(coalesce(cms_primary_specialty, '')) IN (
                        'EMERGENCY MEDICINE',
                        'PEDIATRIC EMERGENCY MEDICINE'
                    )
                    THEN true ELSE false
            END AS ed_specialist_flag,
            CASE
                WHEN coalesce(nppes_any_ed_taxonomy_flag, false) THEN 'NPPES taxonomy'
                WHEN upper(coalesce(cms_primary_specialty, '')) IN (
                    'EMERGENCY MEDICINE',
                    'PEDIATRIC EMERGENCY MEDICINE'
                ) THEN 'CMS primary specialty'
                ELSE 'No ED specialty found'
            END AS ed_specialist_source,
            CASE
                WHEN upper(coalesce(credentials, '')) SIMILAR TO '%(MD|M.D|DO|D.O)%'
                    OR upper(coalesce(doh_profession_name, '')) IN (
                        'MEDICAL DOCTOR',
                        'OSTEOPATHIC PHYSICIAN'
                    )
                    OR primary_taxonomy_code LIKE '207%'
                    OR primary_taxonomy_code LIKE '208%'
                    THEN true ELSE false
            END AS physician_md_do_flag,
            coalesce(doh_hospital_privilege_count, 0) > 0
                AS has_fl_doh_hospital_privilege,
            coalesce(cms_group_practice_count, 0) > 0
                AS has_cms_group_practice_affiliation,
            regexp_full_match(npi, '[0-9]{10}') AS npi_format_valid,
            CASE
                WHEN nppes_gender IN ('M', 'F')
                    AND cms_gender IN ('M', 'F')
                    AND nppes_gender <> cms_gender
                    THEN true ELSE false
            END AS gender_conflict_flag,
            coalesce(cms_grad_year_distinct_count, 0) > 1 AS cms_grad_year_conflict_flag,
            coalesce(fl_license_count, 0) > 1 AS multiple_fl_license_flag
        FROM joined
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TABLE physician_master AS
        SELECT * FROM physician_master_stage
        QUALIFY row_number() OVER (PARTITION BY npi ORDER BY npi) = 1
        """
    )

    print("6/9 Building normalized affiliation bridges", flush=True)
    con.execute(
        f"""
        CREATE OR REPLACE TABLE hospital_affiliations AS
        SELECT DISTINCT
            b.npi,
            'Florida DOH staff privileges' AS affiliation_source,
            nullif(trim(s.hospital_instit), '') AS affiliation_name,
            nullif(trim(s.city), '') AS affiliation_city,
            upper(nullif(trim(s.state), '')) AS affiliation_state,
            b.lic_id AS source_license_id
        FROM read_csv('{sql_path(DOH_STAFF)}', {doh_csv_options}) s
        INNER JOIN doh_bridge b ON trim(s.lic_id) = b.lic_id
        WHERE nullif(trim(s.hospital_instit), '') IS NOT NULL
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TABLE cms_group_affiliations AS
        SELECT DISTINCT
            trim(npi) AS npi,
            'CMS Doctors and Clinicians group practice' AS affiliation_source,
            nullif(trim(facility_name), '') AS group_practice_name,
            nullif(trim(org_pac_id), '') AS group_pac_id,
            try_cast(nullif(trim(num_org_mem), '') AS INTEGER) AS group_member_count,
            nullif(trim(citytown), '') AS affiliation_city,
            upper(nullif(trim(state), '')) AS affiliation_state,
            nullif(trim(zip_code), '') AS affiliation_zip
        FROM read_csv(
            '{cms_path}',
            header = true,
            auto_detect = true,
            all_varchar = true,
            normalize_names = true,
            sample_size = 200000,
            ignore_errors = true,
            null_padding = true
        )
        WHERE regexp_full_match(trim(npi), '[0-9]{{10}}')
          AND nullif(trim(org_pac_id), '') IS NOT NULL
        """
    )


def export_outputs(con: duckdb.DuckDBPyConnection) -> dict:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    master_path = sql_path(OUTPUT_DIR / "Florida_Physician_Master.parquet")
    hospital_path = sql_path(
        OUTPUT_DIR / "Florida_Physician_Hospital_Affiliations.parquet"
    )
    group_path = sql_path(
        OUTPUT_DIR / "Florida_Physician_Group_Practice_Affiliations.parquet"
    )

    print("7/9 Exporting Parquet deliverables", flush=True)
    con.execute(
        f"""
        COPY (
            SELECT * FROM physician_master ORDER BY npi
        ) TO '{master_path}' (
            FORMAT PARQUET,
            COMPRESSION ZSTD,
            OVERWRITE_OR_IGNORE true,
            ROW_GROUP_SIZE 100000
        )
        """
    )
    con.execute(
        f"""
        COPY (
            SELECT * FROM hospital_affiliations ORDER BY npi, affiliation_name
        ) TO '{hospital_path}' (
            FORMAT PARQUET,
            COMPRESSION ZSTD,
            OVERWRITE_OR_IGNORE true
        )
        """
    )
    con.execute(
        f"""
        COPY (
            SELECT * FROM cms_group_affiliations
            ORDER BY npi, group_pac_id, affiliation_state
        ) TO '{group_path}' (
            FORMAT PARQUET,
            COMPRESSION ZSTD,
            OVERWRITE_OR_IGNORE true,
            ROW_GROUP_SIZE 100000
        )
        """
    )

    print("8/9 Running source linkage and completeness QA", flush=True)
    metrics_sql = {
        "master_rows": "SELECT count(*) FROM physician_master",
        "distinct_npis": "SELECT count(DISTINCT npi) FROM physician_master",
        "duplicate_npis": """
            SELECT count(*) FROM (
                SELECT npi FROM physician_master GROUP BY npi HAVING count(*) > 1
            )
        """,
        "invalid_npi_format": """
            SELECT count(*) FROM physician_master WHERE NOT npi_format_valid
        """,
        "cms_clinicians": """
            SELECT count(*) FROM physician_master WHERE is_cms_clinician
        """,
        "fl_license_linked": """
            SELECT count(*) FROM physician_master WHERE has_fl_license
        """,
        "nppes_individual_linked": """
            SELECT count(*) FROM physician_master WHERE has_nppes_individual_record
        """,
        "fl_doh_profile_linked": """
            SELECT count(*) FROM physician_master WHERE has_fl_doh_profile
        """,
        "physician_md_do_flagged": """
            SELECT count(*) FROM physician_master WHERE physician_md_do_flag
        """,
        "ed_specialists_flagged": """
            SELECT count(*) FROM physician_master WHERE ed_specialist_flag
        """,
        "hospital_privilege_linked": """
            SELECT count(*) FROM physician_master WHERE has_fl_doh_hospital_privilege
        """,
        "group_practice_linked": """
            SELECT count(*) FROM physician_master WHERE has_cms_group_practice_affiliation
        """,
        "gender_nonmissing": """
            SELECT count(*) FROM physician_master
            WHERE gender_category IN ('Male', 'Female')
        """,
        "gender_imputed_ssa": """
            SELECT count(*) FROM physician_master
            WHERE gender_source LIKE 'SSA first-name%'
        """,
        "race_imputation_nonmissing": """
            SELECT count(*) FROM physician_master
            WHERE surname_imputed_race_ethnicity <> 'Unknown'
        """,
        "grad_year_nonmissing": """
            SELECT count(*) FROM physician_master
            WHERE medical_school_grad_year IS NOT NULL
        """,
        "gender_conflicts": """
            SELECT count(*) FROM physician_master WHERE gender_conflict_flag
        """,
        "cms_grad_year_conflicts": """
            SELECT count(*) FROM physician_master WHERE cms_grad_year_conflict_flag
        """,
        "multiple_fl_licenses": """
            SELECT count(*) FROM physician_master WHERE multiple_fl_license_flag
        """,
        "hospital_affiliation_rows": "SELECT count(*) FROM hospital_affiliations",
        "group_affiliation_rows": "SELECT count(*) FROM cms_group_affiliations",
    }
    metrics = {
        key: con.execute(query).fetchone()[0] for key, query in metrics_sql.items()
    }
    denominator = metrics["master_rows"] or 1
    for numerator_key in [
        "cms_clinicians",
        "fl_license_linked",
        "nppes_individual_linked",
        "fl_doh_profile_linked",
        "physician_md_do_flagged",
        "ed_specialists_flagged",
        "hospital_privilege_linked",
        "group_practice_linked",
        "gender_nonmissing",
        "gender_imputed_ssa",
        "race_imputation_nonmissing",
        "grad_year_nonmissing",
    ]:
        metrics[numerator_key + "_pct"] = round(
            100.0 * metrics[numerator_key] / denominator, 4
        )

    metrics["qa_passed"] = (
        metrics["master_rows"] == metrics["distinct_npis"]
        and metrics["duplicate_npis"] == 0
        and metrics["invalid_npi_format"] == 0
        and metrics["hospital_affiliation_rows"] > 0
    )
    metrics["source_snapshot"] = {
        "nppes": "NPPES Data Dissemination, February 2026 V2 (validated minimal extract)",
        "cms": "CMS Doctors and Clinicians national downloadable file (local snapshot)",
        "florida_doh": "Florida DOH MQA profile and supplemental public-use files (local snapshot)",
        "taxonomy": "NUCC Health Care Provider Taxonomy, local v25.0 decoder",
        "race_ethnicity": "2010 U.S. Census surname probabilities",
        "gender_fallback": "SSA baby names, 1880-2024",
    }
    metrics["design_notes"] = [
        "Master universe is the union of CMS Doctors and Clinicians NPIs and NPIs carrying a Florida license in the NPPES license slots.",
        "Only NPPES individual entity records (Entity Type Code 1) are used for personal attributes.",
        "Florida DOH supplemental education, certification, training, and hospital privilege records are linked through one deterministic best DOH license profile per NPI.",
        "CMS Facility Name is retained as a group-practice affiliation, not labeled as a hospital.",
        "Race/ethnicity is surname-only imputation and should not be treated as self-identified race/ethnicity.",
        "SSA first-name gender is used only when both NPPES and CMS gender are unavailable and the name probability is at least 90%.",
        "Years of experience for an encounter year should be computed as encounter_year minus medical_school_grad_year, constrained to nonnegative values.",
    ]

    qa_path = OUTPUT_DIR / "physician_master_qa.json"
    qa_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    field_rows = con.execute(
        """
        SELECT
            column_name,
            data_type,
            ordinal_position
        FROM information_schema.columns
        WHERE table_name = 'physician_master'
        ORDER BY ordinal_position
        """
    ).fetchall()
    fields = [
        {
            "field_name": row[0],
            "data_type": row[1],
            "ordinal_position": row[2],
        }
        for row in field_rows
    ]
    (OUTPUT_DIR / "physician_master_schema.json").write_text(
        json.dumps(fields, indent=2), encoding="utf-8"
    )
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a validated one-row-per-NPI physician/clinician master."
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=max(2, min(8, os.cpu_count() or 4)),
        help="DuckDB worker threads.",
    )
    args = parser.parse_args()

    check_sources()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    db_path = TMP_DIR / "physician_master.duckdb"
    con = duckdb.connect(str(db_path))
    con.execute(f"PRAGMA threads={args.threads}")
    con.execute("PRAGMA memory_limit='8GB'")
    con.execute("PRAGMA preserve_insertion_order=false")
    con.execute("PRAGMA temp_directory='" + sql_path(TMP_DIR / "duckdb_temp") + "'")

    build_database(con)
    metrics = export_outputs(con)
    print("9/9 Physician master build complete", flush=True)
    print(json.dumps(metrics, indent=2), flush=True)
    con.close()
    if not metrics["qa_passed"]:
        raise RuntimeError("Physician master failed uniqueness or NPI-format QA.")


if __name__ == "__main__":
    main()
