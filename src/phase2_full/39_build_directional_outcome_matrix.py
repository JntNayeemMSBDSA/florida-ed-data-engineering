#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/39_build_directional_outcome_matrix.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Build one fail-closed, outcome-specific directional-dyad model matrix.

The builder never reads model estimates.  It materializes the exact primary
measurement basis, frozen baseline covariates, fixed-effect/cluster codes, and
one non-imputed outcome.  Builds are partition-restartable and hash-bound to
the frozen directional implementation and its prerequisite audits.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd


YEARS = tuple(range(2010, 2025))
QUARTERS = (1, 2, 3, 4)
FAMILIES = ("gender_dyads", "race_dyads", "intersectional_dyads")
RACE_LEVELS = ("White", "Black", "Hispanic", "Asian", "Other/multiracial")
SEX_LEVELS = ("Male", "Female")
PAYER_LEVELS = (
    "Commercial",
    "Medicaid",
    "Medicare",
    "Self-pay",
    "Non-payment/charity",
    "Other government",
    "Federal government",
    "Workers compensation",
    "Liability",
    "Other",
    "Unknown",
    "<MISSING>",
)
RURALITY_LEVELS = (
    "Metropolitan",
    "Micropolitan",
    "Small town/rural",
    "<MISSING>",
)
ARRIVAL_LEVELS = (
    "Morning",
    "Afternoon",
    "Evening",
    "Night",
    "Unknown",
    "<MISSING>",
)
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
CHARGE_COMPONENT_OUTCOMES = (
    "aneschgs_real_2024",
    "cardiochgs_real_2024",
    "erchgs_real_2024",
    "gastrochgs_real_2024",
    "labchgs_real_2024",
    "lithochgs_real_2024",
    "medchgs_real_2024",
    "obserchgs_real_2024",
    "oprmchgs_real_2024",
    "othchgs_real_2024",
    "pharmchgs_real_2024",
    "radchgs_real_2024",
    "recovchgs_real_2024",
    "traumachgs_real_2024",
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
ALL_OUTCOMES = (
    *PRIMARY_OUTCOMES,
    *RESOURCE_OUTCOMES,
    *DISPOSITION_OUTCOMES,
    *CHARGE_COMPONENT_OUTCOMES,
    *DISCRETION_OUTCOMES,
)
DERIVED_OUTCOME_SQL = {
    "higher_minus_lower_discretion_procedure_count": (
        "CAST(higher_discretion_procedure_count AS DOUBLE) - "
        "CAST(lower_discretion_procedure_count AS DOUBLE)"
    ),
    "any_higher_minus_any_lower_discretion_candidate": (
        "CAST(any_higher_discretion_candidate_flag AS DOUBLE) - "
        "CAST(any_lower_discretion_candidate_flag AS DOUBLE)"
    ),
}
ELIGIBILITY = {
    "gender_dyads": "directional_gender_eligible",
    "race_dyads": "directional_race_probability_eligible",
    "intersectional_dyads": "directional_intersectional_probability_eligible",
}
PROBABILITY_COLUMNS = {
    "White": "physician_race_proxy_prob_white",
    "Black": "physician_race_proxy_prob_black",
    "Hispanic": "physician_race_proxy_prob_hispanic",
    "Asian": "physician_race_proxy_prob_asian",
    "Other/multiracial": "physician_race_proxy_prob_other",
}


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def qpath(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace("'", "''")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(16 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    os.replace(temporary, path)


def normalize_string(series: pd.Series) -> pd.Series:
    return series.astype("string").fillna("<MISSING>")


def bool_value(series: pd.Series) -> np.ndarray:
    return series.fillna(False).astype(bool).to_numpy(dtype=np.float64)


def missing_flag(series: pd.Series) -> np.ndarray:
    return series.isna().to_numpy(dtype=np.float64)


def positive_part(values: np.ndarray, knot: float) -> np.ndarray:
    return np.maximum(values - knot, 0.0)


@dataclass
class IncrementalEncoder:
    mapping: dict[str, int] = field(default_factory=dict)

    def encode(self, series: pd.Series) -> np.ndarray:
        normalized = normalize_string(series)
        missing = sorted(set(normalized.unique()) - set(self.mapping))
        for value in missing:
            self.mapping[str(value)] = len(self.mapping)
        return normalized.map(self.mapping).to_numpy(dtype=np.uint64)


def outcome_expression(outcome: str) -> str:
    if outcome not in ALL_OUTCOMES:
        raise ValueError(f"Outcome is not frozen: {outcome}")
    return DERIVED_OUTCOME_SQL.get(outcome, outcome)


def outcome_family(outcome: str) -> str:
    for name, members in (
        ("primary", PRIMARY_OUTCOMES),
        ("resource", RESOURCE_OUTCOMES),
        ("disposition", DISPOSITION_OUTCOMES),
        ("charge_components", CHARGE_COMPONENT_OUTCOMES),
        ("clinical_discretion", DISCRETION_OUTCOMES),
    ):
        if outcome in members:
            return name
    raise ValueError(outcome)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_live_prerequisites(phase2: Path) -> dict[str, dict[str, Any]]:
    implementation_path = (
        phase2
        / "documentation"
        / "Directional_Dyad_Model_Implementation_FROZEN.json"
    )
    implementation_gate_path = (
        phase2
        / "qa"
        / "directional_model_implementation_pre_estimation_gate.json"
    )
    definition_tests_path = (
        phase2 / "qa" / "directional_model_definition_tests.json"
    )
    required = {
        "implementation": implementation_path,
        "implementation_gate": implementation_gate_path,
        "definition_tests": definition_tests_path,
        "base_manifest": (
            phase2
            / "analysis_data"
            / "directional_dyad_base"
            / "directional_dyad_base_manifest.json"
        ),
        "base_audit": (
            phase2 / "qa" / "independent_directional_dyad_base_audit.json"
        ),
        "support_manifest": (
            phase2
            / "results"
            / "directional_dyads"
            / "support"
            / "directional_support_manifest.json"
        ),
        "support_gate": phase2 / "qa" / "directional_cell_support_gate.json",
        "support_audit": (
            phase2 / "qa" / "independent_directional_cell_support_audit.json"
        ),
        "execution_manifest": (
            phase2
            / "documentation"
            / "Directional_Dyad_Execution_Code_FROZEN.json"
        ),
        "execution_gate": (
            phase2 / "qa" / "directional_execution_code_gate.json"
        ),
    }
    for label, path in required.items():
        if not path.is_file():
            raise SystemExit(f"Required directional prerequisite missing: {label}")
    implementation = load_json(implementation_path)
    implementation_gate = load_json(implementation_gate_path)
    definition_tests = load_json(definition_tests_path)
    execution_manifest = load_json(required["execution_manifest"])
    execution_gate = load_json(required["execution_gate"])
    if implementation.get("status") != "FROZEN_ESTIMATE_BLIND_PASS":
        raise SystemExit("Directional implementation is not frozen/pass")
    if (
        implementation_gate.get("status") != "PASS"
        or implementation_gate.get(
            "outcome_specific_matrix_construction_authorized"
        )
        is not True
        or implementation_gate.get("model_estimate_interpretation_authorized")
        is not False
    ):
        raise SystemExit("Directional implementation gate is not estimate-blind")
    if definition_tests.get("status") != "PASS":
        raise SystemExit("Directional definition tests do not pass")
    if (
        execution_manifest.get("status") != "FROZEN_ESTIMATE_BLIND_PASS"
        or execution_gate.get("status") != "PASS"
        or execution_gate.get("estimate_blind") is not True
        or execution_gate.get("result_interpretation_authorized") is not False
        or execution_gate.get("execution_manifest", {}).get("sha256")
        != sha256_file(required["execution_manifest"])
    ):
        raise SystemExit("Directional execution-code gate does not pass")
    for record in execution_manifest["code_inventory"]:
        path = phase2 / record["path"]
        if (
            not path.is_file()
            or path.stat().st_size != int(record["bytes"])
            or sha256_file(path) != record["sha256"]
        ):
            raise SystemExit(
                f"Frozen directional execution file changed: {record['path']}"
            )
    bindings = implementation["bindings"]
    binding_map = {
        "base_manifest": "directional_base_manifest",
        "base_audit": "directional_base_independent_audit",
        "support_manifest": "directional_support_manifest",
        "support_gate": "directional_support_gate",
        "support_audit": "directional_support_independent_audit",
    }
    for local_name, frozen_name in binding_map.items():
        actual = sha256_file(required[local_name])
        expected = bindings[frozen_name]["sha256"]
        if actual != expected:
            raise SystemExit(
                f"Frozen prerequisite hash mismatch: {local_name} "
                f"{actual} != {expected}"
            )
    for label in (
        "base_audit",
        "support_manifest",
        "support_gate",
        "support_audit",
    ):
        if load_json(required[label]).get("status") != "PASS":
            raise SystemExit(f"Live prerequisite no longer passes: {label}")
    return {
        name: {
            "path": str(path.resolve()),
            "sha256": sha256_file(path),
        }
        for name, path in required.items()
    }


def build_design_spec(
    family: str,
    cells: list[dict[str, Any]],
    elix_flags: list[str],
) -> list[dict[str, str]]:
    spec = [
        {
            "name": f"cell::{item['cell_id']}",
            "group": "directional_cell",
            "cell_id": item["cell_id"],
        }
        for item in cells
    ]

    def add(name: str, group: str) -> None:
        spec.append({"name": name, "group": group})

    for name in (
        "age",
        "age_gt18",
        "age_gt45",
        "age_gt65",
        "age_gt80",
        "age_missing",
    ):
        add(name, "patient_visit")
    if family == "race_dyads":
        add("patient_female", "patient_visit")
    elif family == "gender_dyads":
        for level in RACE_LEVELS[1:]:
            add(f"patient_race_ethnicity__{level}", "patient_visit")
    for level in PAYER_LEVELS[1:]:
        add(f"payer__{level}", "patient_visit")
    for level in RURALITY_LEVELS[1:]:
        add(f"patient_rurality__{level}", "patient_visit")
    for name in (
        "weekend",
        "weekend_missing",
        "off_hours",
        "off_hours_missing",
    ):
        add(name, "patient_visit")
    for level in ARRIVAL_LEVELS[1:]:
        add(f"arrival_band__{level}", "patient_visit")
    for flag in elix_flags:
        add(flag, "patient_risk")
    add("elixhauser_condition_count", "patient_risk")
    for name in (
        "physician_ed_specialist",
        "physician_ed_specialist_missing",
        "experience",
        "experience_gt10",
        "experience_gt20",
        "experience_gt30",
        "experience_missing",
        "log1p_physician_quarter_volume",
        "physician_quarter_volume_missing",
    ):
        add(name, "physician")
    return spec


def cell_matrix(
    frame: pd.DataFrame,
    family: str,
    cells: list[dict[str, Any]],
) -> np.ndarray:
    physician_gender = normalize_string(frame["physician_gender_category"])
    patient_sex = normalize_string(frame["patient_sex_category"])
    patient_race = normalize_string(frame["patient_race_ethnicity_5cat"])
    probabilities = {
        race: pd.to_numeric(frame[column], errors="coerce")
        .to_numpy(dtype=np.float64)
        for race, column in PROBABILITY_COLUMNS.items()
    }
    columns: list[np.ndarray] = []
    for cell in cells:
        if family == "gender_dyads":
            value = (
                physician_gender.eq(cell["physician_group"]).to_numpy()
                & patient_sex.eq(cell["patient_group"]).to_numpy()
            ).astype(np.float64)
        elif family == "race_dyads":
            value = probabilities[cell["physician_group"]] * (
                patient_race.eq(cell["patient_group"]).to_numpy(dtype=np.float64)
            )
        else:
            value = (
                probabilities[cell["physician_race"]]
                * physician_gender.eq(cell["physician_gender"]).to_numpy(
                    dtype=np.float64
                )
                * patient_race.eq(cell["patient_race"]).to_numpy(
                    dtype=np.float64
                )
                * patient_sex.eq(cell["patient_sex"]).to_numpy(
                    dtype=np.float64
                )
            )
        columns.append(value)
    matrix = np.column_stack(columns)
    if (
        not np.isfinite(matrix).all()
        or np.any(matrix < -1e-12)
        or np.any(matrix > 1 + 1e-12)
        or not np.allclose(matrix.sum(axis=1), 1.0, atol=1e-9, rtol=0)
    ):
        raise RuntimeError(f"Invalid or non-summing {family} cell basis")
    return matrix


def design_batch(
    frame: pd.DataFrame,
    family: str,
    cells: list[dict[str, Any]],
    elix_flags: list[str],
    age_median: float,
    experience_median: float,
    design_spec: list[dict[str, str]],
) -> np.ndarray:
    arrays: dict[str, np.ndarray] = {}
    cells_array = cell_matrix(frame, family, cells)
    for index, cell in enumerate(cells):
        arrays[f"cell::{cell['cell_id']}"] = cells_array[:, index]

    raw_age = pd.to_numeric(frame["age_years"], errors="coerce").to_numpy(
        dtype=np.float64
    )
    invalid_age = (~np.isfinite(raw_age)) | (raw_age < 0) | (raw_age > 120)
    age = raw_age.copy()
    age[invalid_age] = age_median
    arrays["age"] = age
    arrays["age_gt18"] = positive_part(age, 18)
    arrays["age_gt45"] = positive_part(age, 45)
    arrays["age_gt65"] = positive_part(age, 65)
    arrays["age_gt80"] = positive_part(age, 80)
    arrays["age_missing"] = invalid_age.astype(np.float64)

    if family == "race_dyads":
        arrays["patient_female"] = (
            normalize_string(frame["patient_sex_category"])
            .eq("Female")
            .to_numpy(dtype=np.float64)
        )
    elif family == "gender_dyads":
        patient_race = normalize_string(
            frame["patient_race_ethnicity_5cat"]
        ).to_numpy()
        for level in RACE_LEVELS[1:]:
            arrays[f"patient_race_ethnicity__{level}"] = (
                patient_race == level
            ).astype(np.float64)

    payer = normalize_string(frame["payer_group"]).to_numpy()
    for level in PAYER_LEVELS[1:]:
        arrays[f"payer__{level}"] = (payer == level).astype(np.float64)
    rurality = normalize_string(
        frame["patient_zip_rurality_3level"]
    ).to_numpy()
    for level in RURALITY_LEVELS[1:]:
        arrays[f"patient_rurality__{level}"] = (
            rurality == level
        ).astype(np.float64)
    arrays["weekend"] = bool_value(frame["weekend_flag"])
    arrays["weekend_missing"] = missing_flag(frame["weekend_flag"])
    arrays["off_hours"] = bool_value(frame["off_hours_flag"])
    arrays["off_hours_missing"] = missing_flag(frame["off_hours_flag"])
    arrival = normalize_string(frame["arrival_time_band"]).to_numpy()
    for level in ARRIVAL_LEVELS[1:]:
        arrays[f"arrival_band__{level}"] = (
            arrival == level
        ).astype(np.float64)

    for flag in elix_flags:
        arrays[flag] = (
            pd.to_numeric(frame[flag], errors="coerce")
            .fillna(0)
            .to_numpy(dtype=np.float64)
        )
    arrays["elixhauser_condition_count"] = (
        pd.to_numeric(frame["elixhauser_condition_count"], errors="coerce")
        .fillna(0)
        .to_numpy(dtype=np.float64)
    )

    specialist = frame["attending_ed_specialist_flag"]
    arrays["physician_ed_specialist"] = bool_value(specialist)
    arrays["physician_ed_specialist_missing"] = missing_flag(specialist)
    raw_experience = pd.to_numeric(
        frame["attending_years_since_medical_school"], errors="coerce"
    ).to_numpy(dtype=np.float64)
    invalid_experience = (
        (~np.isfinite(raw_experience))
        | (raw_experience < 0)
        | (raw_experience > 80)
    )
    experience = raw_experience.copy()
    experience[invalid_experience] = experience_median
    arrays["experience"] = experience
    arrays["experience_gt10"] = positive_part(experience, 10)
    arrays["experience_gt20"] = positive_part(experience, 20)
    arrays["experience_gt30"] = positive_part(experience, 30)
    arrays["experience_missing"] = invalid_experience.astype(np.float64)
    volume = pd.to_numeric(
        frame["attending_quarter_volume_all_ed"], errors="coerce"
    ).to_numpy(dtype=np.float64)
    invalid_volume = (~np.isfinite(volume)) | (volume < 0)
    volume[invalid_volume] = 0
    arrays["log1p_physician_quarter_volume"] = np.log1p(volume)
    arrays["physician_quarter_volume_missing"] = invalid_volume.astype(
        np.float64
    )

    matrix = np.column_stack([arrays[item["name"]] for item in design_spec])
    if not np.isfinite(matrix).all():
        raise RuntimeError("Non-finite directional design value")
    return matrix


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    parser.add_argument("--matrix-root", required=True, type=Path)
    parser.add_argument("--family", required=True, choices=FAMILIES)
    parser.add_argument("--outcome", required=True, choices=ALL_OUTCOMES)
    parser.add_argument("--threads", type=int, default=12)
    parser.add_argument("--memory-limit", default="24GB")
    parser.add_argument("--batch-size", type=int, default=200_000)
    parser.add_argument("--minimum-free-reserve-gb", type=float, default=80.0)
    parser.add_argument("--hash-large-files", action="store_true")
    args = parser.parse_args()

    phase2 = args.phase2.resolve()
    prerequisites = validate_live_prerequisites(phase2)
    implementation = load_json(Path(prerequisites["implementation"]["path"]))
    extension_path = (
        phase2
        / "documentation"
        / "Directional_Dyad_Analysis_Plan_Extension_FROZEN.json"
    )
    if sha256_file(extension_path) != implementation["parent_extension"]["sha256"]:
        raise SystemExit("Frozen directional extension hash mismatch")
    extension = load_json(extension_path)
    family_spec = extension["analysis_families"][args.family]
    cells = list(family_spec["cells"])
    cell_ids = [item["cell_id"] for item in cells]
    expected_cell_counts = {
        "gender_dyads": 4,
        "race_dyads": 25,
        "intersectional_dyads": 100,
    }
    if len(cells) != expected_cell_counts[args.family]:
        raise SystemExit("Frozen directional cell count changed")

    data_root = phase2 / "analysis_data" / "directional_dyad_base"
    output = (
        args.matrix_root.resolve() / args.family / args.outcome
    )
    output.mkdir(parents=True, exist_ok=True)
    duck_temp = output / "duckdb_temp"
    duck_temp.mkdir(parents=True, exist_ok=True)
    success_path = output / "_SUCCESS.json"
    builder_sha256 = sha256_file(Path(__file__).resolve())
    if success_path.is_file():
        existing = load_json(success_path)
        if (
            existing.get("status") == "PASS"
            and existing.get("family_id") == args.family
            and existing.get("outcome") == args.outcome
            and existing.get("matrix_builder_sha256") == builder_sha256
            and existing.get("implementation_sha256")
            == prerequisites["implementation"]["sha256"]
        ):
            print(success_path.read_text(encoding="utf-8"))
            return
        raise SystemExit(
            "Existing directional matrix is stale; preserve it and choose a "
            "new matrix root"
        )

    con = duckdb.connect()
    con.execute(f"SET threads={args.threads}")
    con.execute(f"SET memory_limit='{args.memory_limit}'")
    con.execute(f"SET temp_directory='{qpath(duck_temp)}'")
    con.execute("SET preserve_insertion_order=true")
    sample = (
        data_root
        / "visit_year=2010"
        / "visit_quarter=1"
        / "directional_dyad_base.parquet"
    )
    schema = con.execute(
        f"DESCRIBE SELECT * FROM read_parquet('{qpath(sample)}', "
        "hive_partitioning=false)"
    ).fetchall()
    schema_names = [row[0] for row in schema]
    elix_flags = sorted(
        name
        for name in schema_names
        if name.startswith("elix_") and name.endswith("_flag")
    )
    outcome_sql = outcome_expression(args.outcome)
    eligibility = ELIGIBILITY[args.family]
    design_spec = build_design_spec(args.family, cells, elix_flags)
    design_names = [item["name"] for item in design_spec]

    row_counts: list[dict[str, Any]] = []
    source_partitions: list[dict[str, Any]] = []
    for year in YEARS:
        for quarter in QUARTERS:
            part = (
                data_root
                / f"visit_year={year}"
                / f"visit_quarter={quarter}"
            )
            parquet = part / "directional_dyad_base.parquet"
            sidecar = part / "_SUCCESS.json"
            if not parquet.is_file() or not sidecar.is_file():
                raise SystemExit(f"Directional base partition missing: {year}Q{quarter}")
            sidecar_payload = load_json(sidecar)
            if sidecar_payload.get("status") != "PASS":
                raise SystemExit(f"Directional base partition not PASS: {year}Q{quarter}")
            values = con.execute(
                f"""
                SELECT
                    count(*) AS n,
                    avg(CAST(({outcome_sql}) AS DOUBLE)) AS outcome_mean,
                    min(CAST(({outcome_sql}) AS DOUBLE)) AS outcome_min,
                    max(CAST(({outcome_sql}) AS DOUBLE)) AS outcome_max
                FROM read_parquet('{qpath(parquet)}', hive_partitioning=false)
                WHERE {eligibility}
                  AND ({outcome_sql}) IS NOT NULL
                  AND isfinite(CAST(({outcome_sql}) AS DOUBLE))
                """
            ).fetchone()
            row_counts.append(
                {
                    "visit_year": year,
                    "visit_quarter": quarter,
                    "rows": int(values[0]),
                    "outcome_mean": (
                        float(values[1]) if values[1] is not None else None
                    ),
                    "outcome_min": (
                        float(values[2]) if values[2] is not None else None
                    ),
                    "outcome_max": (
                        float(values[3]) if values[3] is not None else None
                    ),
                }
            )
            source_partitions.append(
                {
                    "visit_year": year,
                    "visit_quarter": quarter,
                    "path": str(parquet.resolve()),
                    "bytes": parquet.stat().st_size,
                    "sha256": sidecar_payload.get("output_sha256"),
                    "success_sha256": sha256_file(sidecar),
                }
            )
    glob = data_root / "visit_year=*" / "visit_quarter=*" / "*.parquet"
    medians = con.execute(
        f"""
        SELECT
            quantile_cont(age_years, 0.5)
                FILTER (WHERE age_years BETWEEN 0 AND 120),
            quantile_cont(attending_years_since_medical_school, 0.5)
                FILTER (
                    WHERE attending_years_since_medical_school BETWEEN 0 AND 80
                )
        FROM read_parquet('{qpath(glob)}', hive_partitioning=false)
        WHERE {eligibility}
          AND ({outcome_sql}) IS NOT NULL
          AND isfinite(CAST(({outcome_sql}) AS DOUBLE))
        """
    ).fetchone()
    if medians[0] is None or medians[1] is None:
        raise RuntimeError("Outcome-specific covariate medians are undefined")
    age_median = float(medians[0])
    experience_median = float(medians[1])
    n_rows = sum(item["rows"] for item in row_counts)
    n_columns = len(design_spec)
    if n_rows <= 0:
        raise RuntimeError("No eligible rows for directional matrix")

    raw_bytes = n_rows * (8 * n_columns + 8 + 8 * 3 + 8 * 3 + 8)
    # One M2 and one M3 demeaning scratch may coexist until the independent
    # matrix/result checkpoint.  This conservative preflight prevents a
    # partially built matrix from exhausting the drive.
    scratch_bytes = n_rows * (2 * 8 * (n_columns + 1))
    free_bytes = shutil.disk_usage(output).free
    reserve_bytes = int(args.minimum_free_reserve_gb * 1024**3)
    preflight = {
        "created_utc": now_utc(),
        "family_id": args.family,
        "outcome": args.outcome,
        "n_rows": n_rows,
        "n_design_columns": n_columns,
        "raw_matrix_bytes": raw_bytes,
        "estimated_two_model_scratch_bytes": scratch_bytes,
        "estimated_peak_new_bytes": raw_bytes + scratch_bytes,
        "free_bytes": free_bytes,
        "minimum_reserve_bytes": reserve_bytes,
        "preflight_passed": (
            free_bytes >= raw_bytes + scratch_bytes + reserve_bytes
        ),
    }
    atomic_json(output / "storage_preflight.json", preflight)
    if not preflight["preflight_passed"]:
        raise RuntimeError(
            "Insufficient free disk for directional matrix and audit scratch"
        )

    matrix_path = output / "raw_design.float64.mmap"
    outcome_path = output / "outcome.float64.mmap"
    fe_path = output / "fe_codes.uint64.mmap"
    cluster_path = output / "cluster_codes.uint64.mmap"
    visit_hash_path = output / "visit_hash.uint64.mmap"
    state_path = output / "build_state.json"
    encoders_path = output / "encoders.json"
    encoders = {
        "physician": IncrementalEncoder(),
        "facility_yq": IncrementalEncoder(),
        "clinical": IncrementalEncoder(),
        "facility": IncrementalEncoder(),
        "physician_facility": IncrementalEncoder(),
    }
    files_required = (
        matrix_path,
        outcome_path,
        fe_path,
        cluster_path,
        visit_hash_path,
    )
    resumable = (
        state_path.is_file()
        and encoders_path.is_file()
        and all(path.is_file() for path in files_required)
    )
    if resumable:
        state = load_json(state_path)
        expected_binding = {
            "family_id": args.family,
            "outcome": args.outcome,
            "expected_rows": n_rows,
            "matrix_builder_sha256": builder_sha256,
            "implementation_sha256": prerequisites["implementation"]["sha256"],
        }
        for key, value in expected_binding.items():
            if state.get(key) != value:
                raise RuntimeError("Incompatible incomplete directional matrix")
        encoder_payload = load_json(encoders_path)
        for name, mapping in encoder_payload.items():
            encoders[name].mapping = {
                str(key): int(value) for key, value in mapping.items()
            }
        offset = int(state["offset"])
        completed = list(state["completed_partitions"])
        mode = "r+"
    else:
        offset = 0
        completed: list[str] = []
        mode = "w+"

    raw = np.memmap(
        matrix_path, dtype=np.float64, mode=mode, shape=(n_rows, n_columns)
    )
    outcome_values = np.memmap(
        outcome_path, dtype=np.float64, mode=mode, shape=(n_rows, 1)
    )
    fe_codes = np.memmap(
        fe_path, dtype=np.uint64, mode=mode, shape=(n_rows, 3)
    )
    cluster_codes = np.memmap(
        cluster_path, dtype=np.uint64, mode=mode, shape=(n_rows, 3)
    )
    visit_hashes = np.memmap(
        visit_hash_path, dtype=np.uint64, mode=mode, shape=(n_rows,)
    )

    common_columns = [
        "visit_key",
        "physician_gender_category",
        "patient_sex_category",
        "patient_race_ethnicity_5cat",
        *PROBABILITY_COLUMNS.values(),
        "age_years",
        "payer_group",
        "patient_zip_rurality_3level",
        "weekend_flag",
        "off_hours_flag",
        "arrival_time_band",
        "elixhauser_condition_count",
        "attending_ed_specialist_flag",
        "attending_years_since_medical_school",
        "attending_quarter_volume_all_ed",
        "attending_selected_npi",
        "facility_year_quarter_id",
        "principal_clinical_category",
        "facility_ahca_id",
        *elix_flags,
    ]
    select_columns = ", ".join(common_columns)

    for item in row_counts:
        year = item["visit_year"]
        quarter = item["visit_quarter"]
        expected = item["rows"]
        label = f"{year}Q{quarter}"
        if label in completed:
            continue
        if expected == 0:
            completed.append(label)
            continue
        parquet = (
            data_root
            / f"visit_year={year}"
            / f"visit_quarter={quarter}"
            / "directional_dyad_base.parquet"
        )
        query = f"""
            SELECT
                {select_columns},
                CAST(({outcome_sql}) AS DOUBLE) AS __outcome,
                hash(visit_key)::UBIGINT AS __visit_hash
            FROM read_parquet('{qpath(parquet)}', hive_partitioning=false)
            WHERE {eligibility}
              AND ({outcome_sql}) IS NOT NULL
              AND isfinite(CAST(({outcome_sql}) AS DOUBLE))
        """
        reader = con.execute(query).fetch_record_batch(
            rows_per_batch=args.batch_size
        )
        partition_written = 0
        for batch in reader:
            frame = batch.to_pandas()
            n = len(frame)
            stop = offset + n
            x = design_batch(
                frame,
                args.family,
                cells,
                elix_flags,
                age_median,
                experience_median,
                design_spec,
            )
            y = frame["__outcome"].to_numpy(dtype=np.float64)
            if not np.isfinite(y).all():
                raise RuntimeError(f"Non-finite outcome in {label}")
            raw[offset:stop, :] = x
            outcome_values[offset:stop, 0] = y
            physician = frame["attending_selected_npi"]
            facility = frame["facility_ahca_id"]
            physician_code = encoders["physician"].encode(physician)
            facility_code = encoders["facility"].encode(facility)
            fe_codes[offset:stop, 0] = physician_code
            fe_codes[offset:stop, 1] = encoders["facility_yq"].encode(
                frame["facility_year_quarter_id"]
            )
            fe_codes[offset:stop, 2] = encoders["clinical"].encode(
                frame["principal_clinical_category"]
            )
            cluster_codes[offset:stop, 0] = physician_code
            cluster_codes[offset:stop, 1] = facility_code
            physician_facility = (
                normalize_string(physician)
                + "|"
                + normalize_string(facility)
            )
            cluster_codes[offset:stop, 2] = encoders[
                "physician_facility"
            ].encode(physician_facility)
            visit_hashes[offset:stop] = frame["__visit_hash"].to_numpy(
                dtype=np.uint64
            )
            offset = stop
            partition_written += n
        if partition_written != expected:
            raise RuntimeError(
                f"{label}: wrote {partition_written}, expected {expected}"
            )
        completed.append(label)
        for mmap in (
            raw,
            outcome_values,
            fe_codes,
            cluster_codes,
            visit_hashes,
        ):
            mmap.flush()
        state = {
            "updated_utc": now_utc(),
            "family_id": args.family,
            "outcome": args.outcome,
            "expected_rows": n_rows,
            "matrix_builder_sha256": builder_sha256,
            "implementation_sha256": prerequisites["implementation"]["sha256"],
            "offset": offset,
            "completed_partitions": completed,
            "encoder_sizes": {
                name: len(encoder.mapping)
                for name, encoder in encoders.items()
            },
        }
        atomic_json(state_path, state)
        atomic_json(
            encoders_path,
            {name: encoder.mapping for name, encoder in encoders.items()},
        )
        print(
            f"{len(completed)}/60 {label}: wrote {partition_written:,}; "
            f"total={offset:,}",
            flush=True,
        )

    if offset != n_rows or len(completed) != 60:
        raise RuntimeError(
            f"Directional matrix incomplete: rows={offset}/{n_rows}, "
            f"partitions={len(completed)}/60"
        )
    for mmap in (
        raw,
        outcome_values,
        fe_codes,
        cluster_codes,
        visit_hashes,
    ):
        mmap.flush()
    del raw, outcome_values, fe_codes, cluster_codes, visit_hashes

    matrix_files = []
    for path in files_required:
        matrix_files.append(
            {
                "name": path.name,
                "bytes": path.stat().st_size,
                "sha256": (
                    sha256_file(path) if args.hash_large_files else None
                ),
            }
        )
    manifest = {
        "status": "PASS",
        "created_utc": now_utc(),
        "matrix_version": "directional_outcome_matrix_v1_20260726",
        "family_id": args.family,
        "analysis_tier": family_spec["tier"],
        "measurement_specification": (
            "recorded_gender_primary"
            if args.family == "gender_dyads"
            else "aamc_fl_prior_probability_weighted"
        ),
        "outcome": args.outcome,
        "outcome_family": outcome_family(args.outcome),
        "outcome_expression": outcome_sql,
        "outcome_sample_rule": (
            "Complete primary-measurement eligible outcome-specific sample; "
            "no outcome imputation."
        ),
        "eligibility_field": eligibility,
        "n_rows": n_rows,
        "n_design_columns": n_columns,
        "n_cell_columns": len(cells),
        "cell_ids": cell_ids,
        "design_spec": design_spec,
        "elixhauser_flags": elix_flags,
        "age_median_imputation": age_median,
        "age_spline_knots": [18, 45, 65, 80],
        "experience_median_imputation": experience_median,
        "experience_spline_knots": [10, 20, 30],
        "categorical_reference_levels": {
            "payer": PAYER_LEVELS[0],
            "patient_rurality": RURALITY_LEVELS[0],
            "arrival_time_band": ARRIVAL_LEVELS[0],
            "patient_race_ethnicity": RACE_LEVELS[0],
            "patient_sex": "Male",
        },
        "fe_code_order": [
            "attending_physician",
            "facility_by_year_quarter",
            "principal_clinical_category",
        ],
        "cluster_code_order": [
            "attending_physician",
            "facility",
            "attending_physician_by_facility_intersection",
        ],
        "partitions": row_counts,
        "source_partitions": source_partitions,
        "encoder_sizes": {
            name: len(encoder.mapping) for name, encoder in encoders.items()
        },
        "matrix_files": matrix_files,
        "matrix_builder_path": str(Path(__file__).resolve()),
        "matrix_builder_sha256": builder_sha256,
        "implementation_sha256": prerequisites["implementation"]["sha256"],
        "extension_sha256": sha256_file(extension_path),
        "prerequisites": prerequisites,
        "estimate_blind": True,
        "model_estimates_read": False,
        "source_release_modified": False,
        "phase2_cohort_modified": False,
    }
    manifest_path = output / "matrix_manifest.json"
    atomic_json(manifest_path, manifest)
    atomic_json(success_path, manifest)
    con.close()
    print(json.dumps(manifest, indent=2), flush=True)


if __name__ == "__main__":
    main()
