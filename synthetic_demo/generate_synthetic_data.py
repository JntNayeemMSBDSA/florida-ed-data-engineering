#!/usr/bin/env python3
"""Generate clearly fictional inputs for the public demonstration pipeline."""

from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path
from typing import Any


SEED = 20260806
TOTAL_ROWS = 800
ROWS_PER_SCHEMA = TOTAL_ROWS // 5

SCHEMA_PERIODS = {
    "schema_1_2005_2008": [(2005, 1), (2006, 2), (2007, 3), (2008, 4)],
    "schema_2_2010_2015q3": [(2010, 1), (2013, 2), (2015, 3)],
    "schema_3_2015q4_2017": [(2015, 4), (2016, 2), (2017, 4)],
    "schema_4_2018_2022": [(2018, 1), (2020, 3), (2022, 4)],
    "schema_5_2023_2024": [(2023, 2), (2024, 4)],
}

ICD9_DIAGNOSES = ["41071", "25000", "78650"]
ICD10_DIAGNOSES = ["I214", "E119", "R079"]
ICD9_PROCEDURES = ["8853", "", "99284"]
ICD10_PROCEDURES = ["4A023N7", "", "99284"]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def provider_rows() -> list[dict[str, Any]]:
    types = ["MD", "DO", "NP", "PA", "OTHER_INDIVIDUAL", "ORGANIZATION"]
    rows = []
    for index in range(1, 49):
        clinician_type = types[(index - 1) % len(types)]
        organization = clinician_type == "ORGANIZATION"
        rows.append(
            {
                "synthetic_provider_id": f"SYN-NPI-{index:04d}",
                "synthetic_license_id": f"SYN-LIC-{index:04d}",
                "fictional_name": (
                    f"Fictional Care Group {index:02d}"
                    if organization
                    else f"Demo Clinician {index:02d}"
                ),
                "entity_type": "ORGANIZATION" if organization else "INDIVIDUAL",
                "clinician_type": clinician_type,
                "recorded_gender": "" if organization else ("Female" if index % 2 else "Male"),
                "experience_years_demo": "" if organization else 2 + (index * 3) % 34,
            }
        )
    return rows


def facility_rows() -> list[dict[str, Any]]:
    rows = []
    for index in range(1, 9):
        rows.append(
            {
                "synthetic_facility_id": f"SYN-FAC-{index:02d}",
                "fictional_facility_name": f"Demo Regional Emergency Center {index:02d}",
                "rurality": "Rural" if index in {3, 7} else "Urban",
                "teaching_flag": 1 if index in {1, 4} else 0,
                "trauma_capability_demo": "Enhanced" if index in {1, 2, 4} else "Standard",
            }
        )
    return rows


def base_values(rng: random.Random, row_number: int, schema: str) -> dict[str, Any]:
    year, quarter = rng.choice(SCHEMA_PERIODS[schema])
    provider_index = rng.randint(1, 48)
    facility_index = rng.randint(1, 8)
    is_icd9 = year < 2015 or (year == 2015 and quarter <= 3)
    return {
        "record": f"SYN-REC-{row_number:06d}",
        "year": year,
        "quarter": quarter,
        "age": rng.randint(18, 92),
        "sex": rng.choice(["F", "M"]),
        "race": rng.choice(["BLACK", "WHITE", "HISPANIC", "ASIAN", "OTHER"]),
        "ethnicity": rng.choice(["HISPANIC", "NOT_HISPANIC", "UNKNOWN"]),
        "diagnosis": rng.choice(ICD9_DIAGNOSES if is_icd9 else ICD10_DIAGNOSES),
        "procedure": rng.choice(ICD9_PROCEDURES if is_icd9 else ICD10_PROCEDURES),
        "provider": f"SYN-NPI-{provider_index:04d}",
        "license": f"SYN-LIC-{provider_index:04d}",
        "facility": f"SYN-FAC-{facility_index:02d}",
        "charge": f"{rng.uniform(180.0, 9800.0):.2f}",
        "los_hours": rng.randint(1, 30),
        "los_days": rng.randint(0, 3),
        "arrival_hour": rng.randint(0, 23),
        "weekday": rng.randint(1, 7),
    }


def format_schema(schema: str, value: dict[str, Any]) -> dict[str, Any]:
    if schema == "schema_1_2005_2008":
        return {
            "SYS_RECID": value["record"],
            "YEAR": value["year"],
            "QTR": value["quarter"],
            "AGE": value["age"],
            "SEX": value["sex"],
            "RACE_ETH": value["race"],
            "DX1": value["diagnosis"],
            "PR1": value["procedure"],
            "ATTENPHYID": value["license"],
            "FACILITY": value["facility"],
            "TOTCHG": value["charge"],
            "LOS_DAYS": value["los_days"],
            "ARR_HR": value["arrival_hour"],
            "DAY_OF_WEEK": value["weekday"],
        }
    if schema == "schema_2_2010_2015q3":
        return {
            "SYS_RECID": value["record"],
            "VISIT_YEAR": value["year"],
            "VISIT_QUARTER": value["quarter"],
            "PAT_AGE": value["age"],
            "PAT_SEX": value["sex"],
            "PAT_RACE": value["race"],
            "ETHNICITY": value["ethnicity"],
            "DIAGNOSIS_1": value["diagnosis"],
            "PROCEDURE_1": value["procedure"],
            "ATTENDING_NPI": value["provider"],
            "AHCA_ID": value["facility"],
            "TOTAL_CHARGE": value["charge"],
            "LOS_HOURS": value["los_hours"],
            "ARRIVAL_HOUR": value["arrival_hour"],
            "WEEKDAY": value["weekday"],
        }
    if schema == "schema_3_2015q4_2017":
        return {
            "RECORD_KEY": value["record"],
            "YEAR": value["year"],
            "QUARTER": value["quarter"],
            "AGE_YEARS": value["age"],
            "RECORDED_SEX": value["sex"],
            "RECORDED_RACE": value["race"],
            "RECORDED_ETHNICITY": value["ethnicity"],
            "PRINCIPAL_DX": value["diagnosis"],
            "PRINCIPAL_PROC": value["procedure"],
            "ATTENDING_PROVIDER": value["provider"],
            "FACILITY_KEY": value["facility"],
            "REPORTED_CHARGE": value["charge"],
            "CLOCK_LOS_HOURS": value["los_hours"],
            "ARRIVAL_CLOCK_HOUR": value["arrival_hour"],
            "DAY_NUMBER": value["weekday"],
        }
    if schema == "schema_4_2018_2022":
        return {
            "ENCOUNTER_ID": value["record"],
            "CALENDAR_YEAR": value["year"],
            "CALENDAR_QUARTER": value["quarter"],
            "PATIENT_AGE": value["age"],
            "PATIENT_SEX": value["sex"],
            "PATIENT_RACE": value["race"],
            "PATIENT_ETHNICITY": value["ethnicity"],
            "DX_PRIMARY": value["diagnosis"],
            "PROC_PRIMARY": value["procedure"],
            "PROVIDER_NPI": value["provider"],
            "FACILITY_ID": value["facility"],
            "CHARGE_TOTAL": value["charge"],
            "LENGTH_OF_STAY_HOURS": value["los_hours"],
            "HOUR_OF_ARRIVAL": value["arrival_hour"],
            "WEEKDAY_NUMBER": value["weekday"],
        }
    return {
        "synthetic_record_id": value["record"],
        "visit_year": value["year"],
        "visit_quarter": value["quarter"],
        "age_years": value["age"],
        "patient_sex": value["sex"],
        "patient_race": value["race"],
        "patient_ethnicity": value["ethnicity"],
        "principal_diagnosis": value["diagnosis"],
        "principal_procedure": value["procedure"],
        "attending_provider_id": value["provider"],
        "facility_id": value["facility"],
        "total_charge": value["charge"],
        "los_hours": value["los_hours"],
        "arrival_hour": value["arrival_hour"],
        "weekday": value["weekday"],
    }


def generate(output_dir: Path, seed: int = SEED) -> None:
    rng = random.Random(seed)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "synthetic_providers.csv", provider_rows())
    write_csv(output_dir / "synthetic_facilities.csv", facility_rows())
    row_number = 0
    for schema in SCHEMA_PERIODS:
        rows = []
        for _ in range(ROWS_PER_SCHEMA):
            row_number += 1
            rows.append(format_schema(schema, base_values(rng, row_number, schema)))
        write_csv(output_dir / f"{schema}.csv", rows)
    manifest = {
        "synthetic": True,
        "seed": seed,
        "encounter_rows": row_number,
        "schema_families": list(SCHEMA_PERIODS),
        "provider_ids_are_fictional": True,
        "facility_names_are_fictional": True,
    }
    (output_dir / "synthetic_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir", type=Path, default=Path("synthetic_demo/generated/raw")
    )
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()
    generate(args.output_dir, args.seed)
    print(f"Generated {TOTAL_ROWS} fictional encounter rows in {args.output_dir}")


if __name__ == "__main__":
    main()
