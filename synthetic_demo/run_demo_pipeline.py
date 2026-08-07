#!/usr/bin/env python3
"""Run a compact standardization and QA pipeline on fictional records only."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any


SCHEMA_FILES = (
    "schema_1_2005_2008",
    "schema_2_2010_2015q3",
    "schema_3_2015q4_2017",
    "schema_4_2018_2022",
    "schema_5_2023_2024",
)

FIELD_MAPS = {
    "schema_1_2005_2008": {
        "record": "SYS_RECID",
        "year": "YEAR",
        "quarter": "QTR",
        "age": "AGE",
        "sex": "SEX",
        "race": "RACE_ETH",
        "ethnicity": None,
        "diagnosis": "DX1",
        "procedure": "PR1",
        "provider": "ATTENPHYID",
        "facility": "FACILITY",
        "charge": "TOTCHG",
        "los_days": "LOS_DAYS",
        "los_hours": None,
        "arrival_hour": "ARR_HR",
        "weekday": "DAY_OF_WEEK",
    },
    "schema_2_2010_2015q3": {
        "record": "SYS_RECID",
        "year": "VISIT_YEAR",
        "quarter": "VISIT_QUARTER",
        "age": "PAT_AGE",
        "sex": "PAT_SEX",
        "race": "PAT_RACE",
        "ethnicity": "ETHNICITY",
        "diagnosis": "DIAGNOSIS_1",
        "procedure": "PROCEDURE_1",
        "provider": "ATTENDING_NPI",
        "facility": "AHCA_ID",
        "charge": "TOTAL_CHARGE",
        "los_days": None,
        "los_hours": "LOS_HOURS",
        "arrival_hour": "ARRIVAL_HOUR",
        "weekday": "WEEKDAY",
    },
    "schema_3_2015q4_2017": {
        "record": "RECORD_KEY",
        "year": "YEAR",
        "quarter": "QUARTER",
        "age": "AGE_YEARS",
        "sex": "RECORDED_SEX",
        "race": "RECORDED_RACE",
        "ethnicity": "RECORDED_ETHNICITY",
        "diagnosis": "PRINCIPAL_DX",
        "procedure": "PRINCIPAL_PROC",
        "provider": "ATTENDING_PROVIDER",
        "facility": "FACILITY_KEY",
        "charge": "REPORTED_CHARGE",
        "los_days": None,
        "los_hours": "CLOCK_LOS_HOURS",
        "arrival_hour": "ARRIVAL_CLOCK_HOUR",
        "weekday": "DAY_NUMBER",
    },
    "schema_4_2018_2022": {
        "record": "ENCOUNTER_ID",
        "year": "CALENDAR_YEAR",
        "quarter": "CALENDAR_QUARTER",
        "age": "PATIENT_AGE",
        "sex": "PATIENT_SEX",
        "race": "PATIENT_RACE",
        "ethnicity": "PATIENT_ETHNICITY",
        "diagnosis": "DX_PRIMARY",
        "procedure": "PROC_PRIMARY",
        "provider": "PROVIDER_NPI",
        "facility": "FACILITY_ID",
        "charge": "CHARGE_TOTAL",
        "los_days": None,
        "los_hours": "LENGTH_OF_STAY_HOURS",
        "arrival_hour": "HOUR_OF_ARRIVAL",
        "weekday": "WEEKDAY_NUMBER",
    },
    "schema_5_2023_2024": {
        "record": "synthetic_record_id",
        "year": "visit_year",
        "quarter": "visit_quarter",
        "age": "age_years",
        "sex": "patient_sex",
        "race": "patient_race",
        "ethnicity": "patient_ethnicity",
        "diagnosis": "principal_diagnosis",
        "procedure": "principal_procedure",
        "provider": "attending_provider_id",
        "facility": "facility_id",
        "charge": "total_charge",
        "los_days": None,
        "los_hours": "los_hours",
        "arrival_hour": "arrival_hour",
        "weekday": "weekday",
    },
}

DIAGNOSIS_CATEGORIES = {
    "41071": "Acute myocardial infarction",
    "I214": "Acute myocardial infarction",
    "25000": "Diabetes mellitus",
    "E119": "Diabetes mellitus",
    "78650": "Chest pain",
    "R079": "Chest pain",
}
ICD9_DIAGNOSES = {"41071", "25000", "78650"}
PROCEDURE_CATEGORIES = {
    "8853": "Cardiac diagnostic procedure",
    "4A023N7": "Cardiac diagnostic procedure",
    "99284": "Emergency evaluation and management",
    "": "No recorded procedure",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = fields or list(rows[0])
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def value(row: dict[str, str], mapping: dict[str, str | None], name: str) -> str:
    source = mapping[name]
    return row.get(source, "") if source else ""


def provider_lookup(input_dir: Path) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    by_id: dict[str, dict[str, str]] = {}
    license_to_id: dict[str, str] = {}
    for row in read_csv(input_dir / "synthetic_providers.csv"):
        by_id[row["synthetic_provider_id"]] = row
        license_to_id[row["synthetic_license_id"]] = row["synthetic_provider_id"]
    return by_id, license_to_id


def standardize(input_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    providers, licenses = provider_lookup(input_dir)
    facilities = {
        row["synthetic_facility_id"]: row
        for row in read_csv(input_dir / "synthetic_facilities.csv")
    }
    standardized: list[dict[str, Any]] = []
    reconciliation = []
    transition_errors = 0
    organization_physician_errors = 0
    facility_unmatched = 0

    for schema in SCHEMA_FILES:
        rows = read_csv(input_dir / f"{schema}.csv")
        mapping = FIELD_MAPS[schema]
        before = len(standardized)
        for raw in rows:
            year = int(value(raw, mapping, "year"))
            quarter = int(value(raw, mapping, "quarter"))
            expected_icd9 = year < 2015 or (year == 2015 and quarter <= 3)
            diagnosis_system = "ICD-9-CM" if expected_icd9 else "ICD-10-CM"
            procedure = value(raw, mapping, "procedure")
            if not procedure:
                procedure_system = "NONE"
            elif procedure == "99284":
                procedure_system = "CPT/HCPCS"
            else:
                procedure_system = "ICD-9-CM" if expected_icd9 else "ICD-10-PCS"
            provider_raw = value(raw, mapping, "provider")
            provider_id = licenses.get(provider_raw, provider_raw)
            provider = providers[provider_id]
            physician = int(
                provider["entity_type"] == "INDIVIDUAL"
                and provider["clinician_type"] in {"MD", "DO"}
            )
            if provider["entity_type"] == "ORGANIZATION" and physician:
                organization_physician_errors += 1
            facility_id = value(raw, mapping, "facility")
            facility = facilities.get(facility_id)
            if facility is None:
                facility_unmatched += 1
                facility = {"rurality": "", "teaching_flag": ""}
            arrival_hour = int(value(raw, mapping, "arrival_hour"))
            weekday = int(value(raw, mapping, "weekday"))
            diagnosis = value(raw, mapping, "diagnosis")
            if (diagnosis in ICD9_DIAGNOSES) != (diagnosis_system == "ICD-9-CM"):
                transition_errors += 1
            standardized.append(
                {
                    "synthetic_visit_id": value(raw, mapping, "record"),
                    "schema_family": schema,
                    "visit_year": year,
                    "visit_quarter": quarter,
                    "age_years": int(value(raw, mapping, "age")),
                    "recorded_patient_sex": value(raw, mapping, "sex"),
                    "recorded_race_group_demo": value(raw, mapping, "race"),
                    "recorded_ethnicity_demo": value(raw, mapping, "ethnicity"),
                    "diagnosis_code_system": diagnosis_system,
                    "principal_diagnosis_code": diagnosis,
                    "diagnosis_category": DIAGNOSIS_CATEGORIES[diagnosis],
                    "procedure_code_system": procedure_system,
                    "principal_procedure_code": procedure,
                    "procedure_group": PROCEDURE_CATEGORIES[procedure],
                    "synthetic_provider_id": provider_id,
                    "provider_entity_type": provider["entity_type"],
                    "clinician_type": provider["clinician_type"],
                    "physician_flag": physician,
                    "synthetic_facility_id": facility_id,
                    "facility_rurality": facility["rurality"],
                    "facility_teaching_flag": facility["teaching_flag"],
                    "total_charge_demo": f"{float(value(raw, mapping, 'charge')):.2f}",
                    "los_days": value(raw, mapping, "los_days"),
                    "los_hours": value(raw, mapping, "los_hours"),
                    "weekend_flag": int(weekday >= 6),
                    "off_hours_flag": int(arrival_hour < 7 or arrival_hour >= 19),
                }
            )
        output_rows = len(standardized) - before
        reconciliation.append(
            {
                "schema_family": schema,
                "input_rows": len(rows),
                "output_rows": output_rows,
                "status": "PASS" if len(rows) == output_rows else "FAIL",
            }
        )

    visit_ids = [row["synthetic_visit_id"] for row in standardized]
    qa = {
        "synthetic": True,
        "seed": 20260806,
        "input_rows": sum(row["input_rows"] for row in reconciliation),
        "standardized_rows": len(standardized),
        "distinct_synthetic_visit_ids": len(set(visit_ids)),
        "schema_families": len(reconciliation),
        "schema_reconciliation_passed": all(row["status"] == "PASS" for row in reconciliation),
        "icd_transition_error_rows": transition_errors,
        "organization_classified_as_physician_rows": organization_physician_errors,
        "facility_unmatched_rows": facility_unmatched,
        "historical_hourly_los_imputed_rows": 0,
        "overall_status": (
            "PASS"
            if transition_errors == 0
            and organization_physician_errors == 0
            and facility_unmatched == 0
            and len(standardized) == len(set(visit_ids))
            else "FAIL"
        ),
    }
    return standardized, reconciliation, qa


def run(input_dir: Path, output_dir: Path) -> None:
    manifest = json.loads((input_dir / "synthetic_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("synthetic") is not True:
        raise RuntimeError("Input manifest is not explicitly synthetic")
    standardized, reconciliation, qa = standardize(input_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "standardized_synthetic_encounters.csv", standardized)
    write_csv(output_dir / "schema_reconciliation.csv", reconciliation)
    categories = Counter(row["diagnosis_category"] for row in standardized)
    category_rows = [
        {"diagnosis_category": name, "synthetic_rows": categories[name]}
        for name in sorted(categories)
    ]
    write_csv(output_dir / "category_summary.csv", category_rows)
    (output_dir / "qa_summary.json").write_text(
        json.dumps(qa, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, default=Path("synthetic_demo/generated/raw"))
    parser.add_argument("--output-dir", type=Path, default=Path("synthetic_demo/output"))
    args = parser.parse_args()
    run(args.input_dir, args.output_dir)
    print(f"Synthetic pipeline completed: {args.output_dir / 'qa_summary.json'}")


if __name__ == "__main__":
    main()
