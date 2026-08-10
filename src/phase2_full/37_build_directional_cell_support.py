#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/37_build_directional_cell_support.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Build pre-model support and estimability tables for directional dyads.

The tables contain no treatment-outcome estimates.  They quantify the frozen
gender, five-class race, and intersectional cell support before outcome-specific
model matrices are created.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb


RACE_CLASSES = (
    ("White", "white"),
    ("Black", "black"),
    ("Hispanic", "hispanic"),
    ("Asian", "asian"),
    ("Other/multiracial", "other"),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(16 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def qpath(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace("'", "''")


def quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)


def atomic_csv(
    path: Path,
    rows: list[dict[str, Any]],
    fields: list[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with tmp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, path)


def require_pass(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("status") != "PASS":
        raise RuntimeError(f"Required gate is not PASS: {path}")
    return value


def kish(sum_weight: float, sum_weight_sq: float) -> float:
    if sum_weight_sq <= 0:
        return 0.0
    return float(sum_weight * sum_weight / sum_weight_sq)


def support_status(
    effective_visits: float,
    effective_physicians: float,
    facilities: int,
    physician_clusters: int,
    facility_clusters: int,
    thresholds: dict[str, Any],
) -> tuple[str, bool]:
    non_estimable = (
        effective_visits
        < thresholds[
            "minimum_visits_or_probability_weighted_effective_visits"
        ]
        or effective_physicians
        < thresholds[
            "minimum_unique_physicians_or_kish_effective_physicians"
        ]
        or facilities < thresholds["minimum_facilities"]
        or physician_clusters < thresholds["minimum_physician_clusters"]
        or facility_clusters < thresholds["minimum_facility_clusters"]
    )
    if non_estimable:
        return "NON_ESTIMABLE_PREMODEL_SUPPORT", False
    limited = (
        effective_visits < 5000
        or effective_physicians < 50
        or facilities < 30
    )
    if limited:
        return "LIMITED_SUPPORT", True
    return "PASS", True


def cell_id(
    family: str,
    physician_group: str,
    patient_group: str,
    physician_gender: str = "",
    patient_sex: str = "",
) -> str:
    if family == "gender_dyads":
        return (
            f"physician={physician_gender}|patient={patient_sex}"
        )
    if family == "race_dyads":
        return (
            f"physician={physician_group}|patient={patient_group}"
        )
    return (
        f"physician_race={physician_group}|"
        f"physician_gender={physician_gender}|"
        f"patient_race={patient_group}|patient_sex={patient_sex}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--memory-limit", default="20GB")
    parser.add_argument("--temp", required=True, type=Path)
    args = parser.parse_args()

    phase2 = args.phase2.resolve()
    temp = args.temp.resolve()
    temp.mkdir(parents=True, exist_ok=True)
    base_root = phase2 / "analysis_data" / "directional_dyad_base"
    base_manifest_path = base_root / "directional_dyad_base_manifest.json"
    base_audit_path = (
        phase2 / "qa" / "independent_directional_dyad_base_audit.json"
    )
    extension_path = (
        phase2
        / "documentation"
        / "Directional_Dyad_Analysis_Plan_Extension_FROZEN.json"
    )
    extension_gate_path = (
        phase2
        / "qa"
        / "directional_dyad_extension_pre_estimation_gate.json"
    )
    provider_gate_path = (
        phase2 / "qa" / "pre_estimation_measurement_gate.json"
    )
    cohort_gate_path = phase2 / "qa" / "cohort_validation_report.json"

    base_manifest = require_pass(base_manifest_path)
    base_audit = require_pass(base_audit_path)
    extension_gate = require_pass(extension_gate_path)
    provider_gate = require_pass(provider_gate_path)
    cohort_gate = require_pass(cohort_gate_path)
    extension = json.loads(extension_path.read_text(encoding="utf-8"))
    if extension.get("status") != "FROZEN_ESTIMATE_BLIND_PASS":
        raise RuntimeError("Directional extension is not frozen and passing.")
    if extension_gate["frozen_manifest"]["sha256"] != sha256(extension_path):
        raise RuntimeError("Directional extension hash is stale.")

    bindings = {
        "directional_base_manifest_sha256": sha256(base_manifest_path),
        "directional_base_independent_audit_sha256": sha256(base_audit_path),
        "extension_manifest_sha256": sha256(extension_path),
        "extension_gate_sha256": sha256(extension_gate_path),
        "provider_gate_sha256": sha256(provider_gate_path),
        "cohort_gate_sha256": sha256(cohort_gate_path),
    }
    thresholds = extension["support_and_estimability"]["primary_2010_2024"]

    parquet_glob = (
        base_root
        / "visit_year=*"
        / "visit_quarter=*"
        / "directional_dyad_base.parquet"
    )
    base_sql = (
        "read_parquet("
        f"{quote(qpath(parquet_glob))}, "
        "hive_partitioning=false, union_by_name=true)"
    )
    con = duckdb.connect()
    con.execute(f"SET threads={int(args.threads)}")
    con.execute(f"SET memory_limit={quote(args.memory_limit)}")
    con.execute(f"SET temp_directory={quote(qpath(temp))}")
    con.execute("SET preserve_insertion_order=false")

    rows: list[dict[str, Any]] = []
    weight_constant_errors = 0

    gender_result = con.execute(
        f"""
        SELECT
          physician_gender_category,
          patient_sex_category,
          count(*) AS visits,
          count(DISTINCT attending_selected_npi) AS physicians,
          count(DISTINCT facility_ahca_id) AS facilities
        FROM {base_sql}
        WHERE directional_gender_eligible
        GROUP BY 1, 2
        """
    ).fetchall()
    gender_map = {
        (str(r[0]), str(r[1])): r for r in gender_result
    }
    for spec in extension["analysis_families"]["gender_dyads"]["cells"]:
        physician = spec["physician_group"]
        patient = spec["patient_group"]
        value = gender_map.get((physician, patient))
        visits = int(value[2]) if value else 0
        physicians = int(value[3]) if value else 0
        facilities = int(value[4]) if value else 0
        status, estimable = support_status(
            float(visits),
            float(physicians),
            facilities,
            physicians,
            facilities,
            thresholds,
        )
        rows.append(
            {
                "family_id": "gender_dyads",
                "analysis_tier": (
                    extension["analysis_families"]["gender_dyads"]["tier"]
                ),
                "measurement_specification": "recorded_gender_primary",
                "cell_id": spec["cell_id"],
                "physician_race_group": "",
                "physician_gender_group": physician,
                "patient_race_group": "",
                "patient_sex_group": patient,
                "physical_visit_count": visits,
                "probability_weighted_visit_mass": float(visits),
                "sum_squared_weights_visits": float(visits),
                "kish_effective_visits": float(visits),
                "unique_physicians": physicians,
                "probability_weighted_physician_mass": float(physicians),
                "sum_squared_weights_physicians": float(physicians),
                "kish_effective_physicians": float(physicians),
                "unique_facilities": facilities,
                "physician_clusters": physicians,
                "facility_clusters": facilities,
                "premodel_support_status": status,
                "premodel_support_estimable": estimable,
                "outcome_specific_support_status": (
                    "PENDING_OUTCOME_SPECIFIC_MATRIX"
                ),
            }
        )

    for physician_display, suffix in RACE_CLASSES:
        weight = f"physician_race_proxy_prob_{suffix}"
        race_result = con.execute(
            f"""
            SELECT
              patient_race_ethnicity_5cat,
              count(*) AS visits,
              sum({weight}) AS sum_weight,
              sum({weight} * {weight}) AS sum_weight_sq,
              count(DISTINCT attending_selected_npi) AS physicians,
              count(DISTINCT facility_ahca_id) AS facilities
            FROM {base_sql}
            WHERE directional_race_probability_eligible
              AND {weight} IS NOT NULL
              AND {weight} > 0
            GROUP BY 1
            """
        ).fetchall()
        race_map = {str(r[0]): r for r in race_result}
        race_provider = con.execute(
            f"""
            WITH per_npi AS (
              SELECT
                patient_race_ethnicity_5cat,
                attending_selected_npi,
                min({weight}) AS min_weight,
                max({weight}) AS max_weight
              FROM {base_sql}
              WHERE directional_race_probability_eligible
                AND {weight} IS NOT NULL
                AND {weight} > 0
              GROUP BY 1, 2
            )
            SELECT
              patient_race_ethnicity_5cat,
              sum(max_weight) AS sum_weight,
              sum(max_weight * max_weight) AS sum_weight_sq,
              count(*) FILTER (
                WHERE abs(max_weight - min_weight) > 1e-12
              ) AS weight_errors
            FROM per_npi
            GROUP BY 1
            """
        ).fetchall()
        race_provider_map = {str(r[0]): r for r in race_provider}
        for patient_display, _ in RACE_CLASSES:
            value = race_map.get(patient_display)
            provider_value = race_provider_map.get(patient_display)
            visits = int(value[1]) if value else 0
            sum_w = float(value[2]) if value and value[2] is not None else 0.0
            sum_w2 = (
                float(value[3]) if value and value[3] is not None else 0.0
            )
            physicians = int(value[4]) if value else 0
            facilities = int(value[5]) if value else 0
            physician_mass = (
                float(provider_value[1])
                if provider_value and provider_value[1] is not None
                else 0.0
            )
            physician_mass_sq = (
                float(provider_value[2])
                if provider_value and provider_value[2] is not None
                else 0.0
            )
            if provider_value:
                weight_constant_errors += int(provider_value[3])
            eff_visits = kish(sum_w, sum_w2)
            eff_physicians = kish(physician_mass, physician_mass_sq)
            status, estimable = support_status(
                eff_visits,
                eff_physicians,
                facilities,
                physicians,
                facilities,
                thresholds,
            )
            rows.append(
                {
                    "family_id": "race_dyads",
                    "analysis_tier": (
                        extension["analysis_families"]["race_dyads"]["tier"]
                    ),
                    "measurement_specification": (
                        "aamc_fl_prior_probability_weighted"
                    ),
                    "cell_id": cell_id(
                        "race_dyads",
                        physician_display,
                        patient_display,
                    ),
                    "physician_race_group": physician_display,
                    "physician_gender_group": "",
                    "patient_race_group": patient_display,
                    "patient_sex_group": "",
                    "physical_visit_count": visits,
                    "probability_weighted_visit_mass": sum_w,
                    "sum_squared_weights_visits": sum_w2,
                    "kish_effective_visits": eff_visits,
                    "unique_physicians": physicians,
                    "probability_weighted_physician_mass": physician_mass,
                    "sum_squared_weights_physicians": physician_mass_sq,
                    "kish_effective_physicians": eff_physicians,
                    "unique_facilities": facilities,
                    "physician_clusters": physicians,
                    "facility_clusters": facilities,
                    "premodel_support_status": status,
                    "premodel_support_estimable": estimable,
                    "outcome_specific_support_status": (
                        "PENDING_OUTCOME_SPECIFIC_MATRIX"
                    ),
                }
            )

        inter_result = con.execute(
            f"""
            SELECT
              physician_gender_category,
              patient_sex_category,
              patient_race_ethnicity_5cat,
              count(*) AS visits,
              sum({weight}) AS sum_weight,
              sum({weight} * {weight}) AS sum_weight_sq,
              count(DISTINCT attending_selected_npi) AS physicians,
              count(DISTINCT facility_ahca_id) AS facilities
            FROM {base_sql}
            WHERE directional_intersectional_probability_eligible
              AND {weight} IS NOT NULL
              AND {weight} > 0
            GROUP BY 1, 2, 3
            """
        ).fetchall()
        inter_map = {
            (str(r[0]), str(r[1]), str(r[2])): r for r in inter_result
        }
        inter_provider = con.execute(
            f"""
            WITH per_npi AS (
              SELECT
                physician_gender_category,
                patient_sex_category,
                patient_race_ethnicity_5cat,
                attending_selected_npi,
                min({weight}) AS min_weight,
                max({weight}) AS max_weight
              FROM {base_sql}
              WHERE directional_intersectional_probability_eligible
                AND {weight} IS NOT NULL
                AND {weight} > 0
              GROUP BY 1, 2, 3, 4
            )
            SELECT
              physician_gender_category,
              patient_sex_category,
              patient_race_ethnicity_5cat,
              sum(max_weight) AS sum_weight,
              sum(max_weight * max_weight) AS sum_weight_sq,
              count(*) FILTER (
                WHERE abs(max_weight - min_weight) > 1e-12
              ) AS weight_errors
            FROM per_npi
            GROUP BY 1, 2, 3
            """
        ).fetchall()
        inter_provider_map = {
            (str(r[0]), str(r[1]), str(r[2])): r
            for r in inter_provider
        }
        for physician_gender in ("Male", "Female"):
            for patient_sex in ("Male", "Female"):
                for patient_display, _ in RACE_CLASSES:
                    key = (
                        physician_gender,
                        patient_sex,
                        patient_display,
                    )
                    value = inter_map.get(key)
                    provider_value = inter_provider_map.get(key)
                    visits = int(value[3]) if value else 0
                    sum_w = (
                        float(value[4])
                        if value and value[4] is not None
                        else 0.0
                    )
                    sum_w2 = (
                        float(value[5])
                        if value and value[5] is not None
                        else 0.0
                    )
                    physicians = int(value[6]) if value else 0
                    facilities = int(value[7]) if value else 0
                    physician_mass = (
                        float(provider_value[3])
                        if provider_value and provider_value[3] is not None
                        else 0.0
                    )
                    physician_mass_sq = (
                        float(provider_value[4])
                        if provider_value and provider_value[4] is not None
                        else 0.0
                    )
                    if provider_value:
                        weight_constant_errors += int(provider_value[5])
                    eff_visits = kish(sum_w, sum_w2)
                    eff_physicians = kish(
                        physician_mass, physician_mass_sq
                    )
                    status, estimable = support_status(
                        eff_visits,
                        eff_physicians,
                        facilities,
                        physicians,
                        facilities,
                        thresholds,
                    )
                    rows.append(
                        {
                            "family_id": "intersectional_dyads",
                            "analysis_tier": (
                                extension["analysis_families"][
                                    "intersectional_dyads"
                                ]["tier"]
                            ),
                            "measurement_specification": (
                                "aamc_fl_prior_probability_weighted_"
                                "recorded_gender"
                            ),
                            "cell_id": cell_id(
                                "intersectional_dyads",
                                physician_display,
                                patient_display,
                                physician_gender,
                                patient_sex,
                            ),
                            "physician_race_group": physician_display,
                            "physician_gender_group": physician_gender,
                            "patient_race_group": patient_display,
                            "patient_sex_group": patient_sex,
                            "physical_visit_count": visits,
                            "probability_weighted_visit_mass": sum_w,
                            "sum_squared_weights_visits": sum_w2,
                            "kish_effective_visits": eff_visits,
                            "unique_physicians": physicians,
                            "probability_weighted_physician_mass": (
                                physician_mass
                            ),
                            "sum_squared_weights_physicians": (
                                physician_mass_sq
                            ),
                            "kish_effective_physicians": eff_physicians,
                            "unique_facilities": facilities,
                            "physician_clusters": physicians,
                            "facility_clusters": facilities,
                            "premodel_support_status": status,
                            "premodel_support_estimable": estimable,
                            "outcome_specific_support_status": (
                                "PENDING_OUTCOME_SPECIFIC_MATRIX"
                            ),
                        }
                    )
    con.close()

    expected_cells = {
        family: {cell["cell_id"] for cell in spec["cells"]}
        for family, spec in extension["analysis_families"].items()
    }
    observed_cells = {
        family: {
            row["cell_id"] for row in rows if row["family_id"] == family
        }
        for family in expected_cells
    }
    cell_sets_match = expected_cells == observed_cells

    support_by_cell = {
        (row["family_id"], row["cell_id"]): row for row in rows
    }
    contrast_rows: list[dict[str, Any]] = []
    for family, spec in extension["analysis_families"].items():
        for contrast in spec["contrasts"]:
            nonzero_cells = [
                part["cell_id"]
                for part in contrast["linear_combination"]
                if float(part["weight"]) != 0.0
            ]
            cells = [
                support_by_cell.get((family, item))
                for item in nonzero_cells
            ]
            missing_cells = [
                item
                for item, value in zip(nonzero_cells, cells)
                if value is None
            ]
            usable = [value for value in cells if value is not None]
            all_pass = bool(usable) and not missing_cells and all(
                bool(value["premodel_support_estimable"])
                for value in usable
            )
            contrast_rows.append(
                {
                    "family_id": family,
                    "contrast_id": contrast["contrast_id"],
                    "contrast_family": contrast["contrast_family"],
                    "direction": contrast["direction"],
                    "analysis_tier": spec["tier"],
                    "nonzero_cell_count": len(nonzero_cells),
                    "missing_cell_ids": ";".join(missing_cells),
                    "minimum_kish_effective_visits": (
                        min(
                            float(value["kish_effective_visits"])
                            for value in usable
                        )
                        if usable
                        else 0.0
                    ),
                    "minimum_kish_effective_physicians": (
                        min(
                            float(value["kish_effective_physicians"])
                            for value in usable
                        )
                        if usable
                        else 0.0
                    ),
                    "minimum_facilities": (
                        min(int(value["unique_facilities"]) for value in usable)
                        if usable
                        else 0
                    ),
                    "premodel_support_status": (
                        "PREMODEL_SUPPORT_PASS"
                        if all_pass
                        else "NON_ESTIMABLE_PREMODEL_SUPPORT"
                    ),
                    "final_estimability_status": (
                        "PENDING_OUTCOME_MATRIX_RANK_AND_COVARIANCE"
                    ),
                }
            )

    result_root = (
        phase2 / "results" / "directional_dyads" / "support"
    )
    cell_path = result_root / "directional_cell_support_primary.csv"
    contrast_path = (
        result_root / "directional_contrast_premodel_support.csv"
    )
    cell_fields = list(rows[0])
    contrast_fields = list(contrast_rows[0])
    atomic_csv(cell_path, rows, cell_fields)
    atomic_csv(contrast_path, contrast_rows, contrast_fields)

    family_counts = {
        family: sum(row["family_id"] == family for row in rows)
        for family in expected_cells
    }
    family_estimable = {
        family: sum(
            row["family_id"] == family
            and bool(row["premodel_support_estimable"])
            for row in rows
        )
        for family in expected_cells
    }
    manifest = {
        "status": (
            "PASS"
            if (
                cell_sets_match
                and weight_constant_errors == 0
                and family_counts
                == {
                    "gender_dyads": 4,
                    "race_dyads": 25,
                    "intersectional_dyads": 100,
                }
            )
            else "FAIL"
        ),
        "created_utc": utc_now(),
        "build_spec_version": "directional_cell_support_v1_20260726",
        "scope": (
            "Outcome-independent primary measurement cell support and "
            "pre-model contrast support. Outcome-specific support, matrix rank, "
            "cluster support, covariance, and final estimability remain pending."
        ),
        "period": "2010-2024",
        "measurement": (
            "Recorded physician gender for gender cells; AAMC-Florida-prior "
            "physician-race posterior probabilities for race/intersectional cells."
        ),
        "support_thresholds": thresholds,
        "bindings": bindings,
        "expected_cells": {
            family: len(cells) for family, cells in expected_cells.items()
        },
        "observed_cells": family_counts,
        "premodel_estimable_cells": family_estimable,
        "planned_contrasts": len(contrast_rows),
        "premodel_support_passing_contrasts": sum(
            row["premodel_support_status"] == "PREMODEL_SUPPORT_PASS"
            for row in contrast_rows
        ),
        "physician_probability_weight_constant_errors": (
            weight_constant_errors
        ),
        "outcome_specific_support_pending": True,
        "cell_support": {
            "path": str(cell_path),
            "sha256": sha256(cell_path),
            "rows": len(rows),
        },
        "contrast_support": {
            "path": str(contrast_path),
            "sha256": sha256(contrast_path),
            "rows": len(contrast_rows),
        },
        "source_release_modified": False,
        "phase2_cohort_modified": False,
    }
    manifest_path = result_root / "directional_support_manifest.json"
    atomic_json(manifest_path, manifest)
    gate_path = phase2 / "qa" / "directional_cell_support_gate.json"
    gate = {
        "status": manifest["status"],
        "created_utc": utc_now(),
        "manifest_path": str(manifest_path),
        "manifest_sha256": sha256(manifest_path),
        "cell_sets_match_frozen_extension": cell_sets_match,
        "physician_probability_weight_constant_errors": (
            weight_constant_errors
        ),
        "outcome_specific_matrix_authorized": manifest["status"] == "PASS",
        "result_interpretation_authorized": False,
        "reason": (
            "This gate authorizes outcome-specific matrix construction only. "
            "It does not authorize reading or interpreting model estimates."
        ),
    }
    atomic_json(gate_path, gate)
    print(json.dumps(manifest, indent=2), flush=True)
    if manifest["status"] != "PASS":
        raise RuntimeError(f"Directional support build failed: {gate_path}")


if __name__ == "__main__":
    main()
