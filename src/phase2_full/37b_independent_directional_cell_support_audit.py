#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/37b_independent_directional_cell_support_audit.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Independently audit all directional pre-model cell-support records."""

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


RACES = (
    ("White", "white"),
    ("Black", "black"),
    ("Hispanic", "hispanic"),
    ("Asian", "asian"),
    ("Other/multiracial", "other"),
)
NUMERIC_FIELDS = (
    "physical_visit_count",
    "probability_weighted_visit_mass",
    "sum_squared_weights_visits",
    "kish_effective_visits",
    "unique_physicians",
    "probability_weighted_physician_mass",
    "sum_squared_weights_physicians",
    "kish_effective_physicians",
    "unique_facilities",
    "physician_clusters",
    "facility_clusters",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(16 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def qpath(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace("'", "''")


def quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n",
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
    with tmp.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, path)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(path)
    return value


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def kish(sum_w: float, sum_w2: float) -> float:
    return 0.0 if sum_w2 <= 0 else sum_w * sum_w / sum_w2


def close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-6)


def expected_status(
    effective_visits: float,
    effective_physicians: float,
    facilities: int,
    physicians: int,
    thresholds: dict[str, Any],
) -> tuple[str, bool]:
    fail = (
        effective_visits
        < thresholds[
            "minimum_visits_or_probability_weighted_effective_visits"
        ]
        or effective_physicians
        < thresholds[
            "minimum_unique_physicians_or_kish_effective_physicians"
        ]
        or facilities < thresholds["minimum_facilities"]
        or physicians < thresholds["minimum_physician_clusters"]
        or facilities < thresholds["minimum_facility_clusters"]
    )
    if fail:
        return "NON_ESTIMABLE_PREMODEL_SUPPORT", False
    if (
        effective_visits < 5000
        or effective_physicians < 50
        or facilities < 30
    ):
        return "LIMITED_SUPPORT", True
    return "PASS", True


def prob_support(
    con: duckdb.DuckDBPyConnection,
    base_sql: str,
    weight: str,
    intersectional: bool,
) -> tuple[dict[tuple[str, ...], dict[str, float]], int]:
    if intersectional:
        groups = (
            "physician_gender_category, patient_sex_category, "
            "patient_race_ethnicity_5cat"
        )
        eligibility = "directional_intersectional_probability_eligible"
    else:
        groups = "patient_race_ethnicity_5cat"
        eligibility = "directional_race_probability_eligible"
    result = con.execute(
        f"""
        SELECT
          {groups},
          count(*) AS visits,
          sum({weight}) AS sw,
          sum({weight} * {weight}) AS sw2,
          count(DISTINCT attending_selected_npi) AS physicians,
          count(DISTINCT facility_ahca_id) AS facilities
        FROM {base_sql}
        WHERE {eligibility}
          AND {weight} IS NOT NULL
          AND {weight} > 0
        GROUP BY {groups}
        """
    ).fetchall()
    provider = con.execute(
        f"""
        WITH p AS (
          SELECT
            {groups},
            attending_selected_npi,
            min({weight}) AS min_w,
            max({weight}) AS max_w
          FROM {base_sql}
          WHERE {eligibility}
            AND {weight} IS NOT NULL
            AND {weight} > 0
          GROUP BY {groups}, attending_selected_npi
        )
        SELECT
          {groups},
          sum(max_w) AS sw,
          sum(max_w * max_w) AS sw2,
          count(*) FILTER (WHERE abs(max_w - min_w) > 1e-12)
            AS errors
        FROM p
        GROUP BY {groups}
        """
    ).fetchall()
    key_count = 3 if intersectional else 1
    providers = {
        tuple(str(v) for v in row[:key_count]): row
        for row in provider
    }
    support: dict[tuple[str, ...], dict[str, float]] = {}
    errors = 0
    for row in result:
        key = tuple(str(v) for v in row[:key_count])
        offset = key_count
        p = providers[key]
        p_sw = float(p[key_count])
        p_sw2 = float(p[key_count + 1])
        errors += int(p[key_count + 2])
        sw = float(row[offset + 1])
        sw2 = float(row[offset + 2])
        physicians = int(row[offset + 3])
        facilities = int(row[offset + 4])
        support[key] = {
            "physical_visit_count": int(row[offset]),
            "probability_weighted_visit_mass": sw,
            "sum_squared_weights_visits": sw2,
            "kish_effective_visits": kish(sw, sw2),
            "unique_physicians": physicians,
            "probability_weighted_physician_mass": p_sw,
            "sum_squared_weights_physicians": p_sw2,
            "kish_effective_physicians": kish(p_sw, p_sw2),
            "unique_facilities": facilities,
            "physician_clusters": physicians,
            "facility_clusters": facilities,
        }
    return support, errors


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
    result_root = phase2 / "results" / "directional_dyads" / "support"
    cell_path = result_root / "directional_cell_support_primary.csv"
    contrast_path = result_root / "directional_contrast_premodel_support.csv"
    manifest_path = result_root / "directional_support_manifest.json"
    gate_path = phase2 / "qa" / "directional_cell_support_gate.json"
    base_audit_path = (
        phase2 / "qa" / "independent_directional_dyad_base_audit.json"
    )
    extension_path = (
        phase2
        / "documentation"
        / "Directional_Dyad_Analysis_Plan_Extension_FROZEN.json"
    )
    for path in (
        cell_path,
        contrast_path,
        manifest_path,
        gate_path,
        base_audit_path,
        extension_path,
    ):
        if not path.is_file():
            raise FileNotFoundError(path)
    manifest = load_json(manifest_path)
    gate = load_json(gate_path)
    base_audit = load_json(base_audit_path)
    extension = load_json(extension_path)
    if (
        manifest.get("status") != "PASS"
        or gate.get("status") != "PASS"
        or base_audit.get("status") != "PASS"
        or extension.get("status") != "FROZEN_ESTIMATE_BLIND_PASS"
    ):
        raise RuntimeError("Required support inputs are not passing.")
    if (
        manifest["cell_support"]["sha256"] != sha256(cell_path)
        or manifest["contrast_support"]["sha256"] != sha256(contrast_path)
        or gate["manifest_sha256"] != sha256(manifest_path)
        or manifest["bindings"][
            "directional_base_independent_audit_sha256"
        ]
        != sha256(base_audit_path)
        or manifest["bindings"]["extension_manifest_sha256"]
        != sha256(extension_path)
    ):
        raise RuntimeError("Support hash binding failed.")

    actual_rows = load_csv(cell_path)
    actual = {
        (row["family_id"], row["cell_id"]): row for row in actual_rows
    }
    expected_ids = {
        (family, cell["cell_id"])
        for family, spec in extension["analysis_families"].items()
        for cell in spec["cells"]
    }
    duplicate_count = len(actual_rows) - len(actual)
    id_set_pass = set(actual) == expected_ids
    thresholds = extension["support_and_estimability"]["primary_2010_2024"]

    base_root = phase2 / "analysis_data" / "directional_dyad_base"
    glob = (
        base_root
        / "visit_year=*"
        / "visit_quarter=*"
        / "directional_dyad_base.parquet"
    )
    base_sql = (
        "read_parquet("
        f"{quote(qpath(glob))}, "
        "hive_partitioning=false, union_by_name=true)"
    )
    con = duckdb.connect()
    con.execute(f"SET threads={int(args.threads)}")
    con.execute(f"SET memory_limit={quote(args.memory_limit)}")
    con.execute(f"SET temp_directory={quote(qpath(temp))}")
    con.execute("SET preserve_insertion_order=false")

    expected: dict[tuple[str, str], dict[str, float]] = {}
    gender = con.execute(
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
    gender_raw = {(str(r[0]), str(r[1])): r for r in gender}
    for cell in extension["analysis_families"]["gender_dyads"]["cells"]:
        key = (cell["physician_group"], cell["patient_group"])
        value = gender_raw.get(key, (None, None, 0, 0, 0))
        visits, physicians, facilities = map(int, value[2:5])
        expected[("gender_dyads", cell["cell_id"])] = {
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
        }

    weight_errors = 0
    for physician, suffix in RACES:
        race_values, errors = prob_support(
            con,
            base_sql,
            f"physician_race_proxy_prob_{suffix}",
            False,
        )
        weight_errors += errors
        for cell in extension["analysis_families"]["race_dyads"]["cells"]:
            if cell["physician_group"] != physician:
                continue
            metrics = race_values.get((cell["patient_group"],))
            if metrics is None:
                metrics = {name: 0.0 for name in NUMERIC_FIELDS}
            expected[("race_dyads", cell["cell_id"])] = metrics

        inter_values, errors = prob_support(
            con,
            base_sql,
            f"physician_race_proxy_prob_{suffix}",
            True,
        )
        weight_errors += errors
        for cell in extension["analysis_families"][
            "intersectional_dyads"
        ]["cells"]:
            if cell["physician_race"] != physician:
                continue
            key = (
                cell["physician_gender"],
                cell["patient_sex"],
                cell["patient_race"],
            )
            metrics = inter_values.get(key)
            if metrics is None:
                metrics = {name: 0.0 for name in NUMERIC_FIELDS}
            expected[("intersectional_dyads", cell["cell_id"])] = metrics
    con.close()

    audits: list[dict[str, Any]] = []
    for key in sorted(expected):
        row = actual.get(key)
        metrics = expected[key]
        mismatches: list[str] = []
        if row is None:
            mismatches.append("missing_cell")
        else:
            for name in NUMERIC_FIELDS:
                if not close(float(row[name]), float(metrics[name])):
                    mismatches.append(name)
            status, estimable = expected_status(
                float(metrics["kish_effective_visits"]),
                float(metrics["kish_effective_physicians"]),
                int(metrics["unique_facilities"]),
                int(metrics["unique_physicians"]),
                thresholds,
            )
            if row["premodel_support_status"] != status:
                mismatches.append("premodel_support_status")
            actual_bool = row["premodel_support_estimable"].lower() == "true"
            if actual_bool != estimable:
                mismatches.append("premodel_support_estimable")
            if (
                row["outcome_specific_support_status"]
                != "PENDING_OUTCOME_SPECIFIC_MATRIX"
            ):
                mismatches.append("outcome_specific_support_status")
        audits.append(
            {
                "family_id": key[0],
                "cell_id": key[1],
                "status": "PASS" if not mismatches else "FAIL",
                "mismatched_fields": ";".join(mismatches),
            }
        )

    contrasts = load_csv(contrast_path)
    expected_contrasts = {
        (family, contrast["contrast_id"]): contrast
        for family, spec in extension["analysis_families"].items()
        for contrast in spec["contrasts"]
    }
    actual_contrasts = {
        (row["family_id"], row["contrast_id"]): row for row in contrasts
    }
    contrast_id_pass = (
        len(contrasts) == len(actual_contrasts)
        and set(actual_contrasts) == set(expected_contrasts)
    )
    contrast_errors: list[dict[str, str]] = []
    for key, spec in expected_contrasts.items():
        row = actual_contrasts.get(key)
        nonzero = [
            part["cell_id"]
            for part in spec["linear_combination"]
            if float(part["weight"]) != 0
        ]
        cell_rows = [actual[(key[0], cell)] for cell in nonzero]
        all_supported = all(
            value["premodel_support_estimable"].lower() == "true"
            for value in cell_rows
        )
        expected_pre = (
            "PREMODEL_SUPPORT_PASS"
            if all_supported
            else "NON_ESTIMABLE_PREMODEL_SUPPORT"
        )
        errors = []
        if row is None:
            errors.append("missing")
        else:
            if row["premodel_support_status"] != expected_pre:
                errors.append("premodel_support_status")
            if (
                row["final_estimability_status"]
                != "PENDING_OUTCOME_MATRIX_RANK_AND_COVARIANCE"
            ):
                errors.append("final_estimability_status")
            if int(row["nonzero_cell_count"]) != len(nonzero):
                errors.append("nonzero_cell_count")
        if errors:
            contrast_errors.append(
                {
                    "family_id": key[0],
                    "contrast_id": key[1],
                    "errors": ";".join(errors),
                }
            )

    cell_csv = phase2 / "qa" / "independent_directional_cell_support_audit.csv"
    atomic_csv(
        cell_csv,
        audits,
        ["family_id", "cell_id", "status", "mismatched_fields"],
    )
    checks = [
        {
            "check_id": "support_manifest_and_gate_pass",
            "passed": True,
            "evidence": sha256(manifest_path),
        },
        {
            "check_id": "all_129_frozen_cells_exactly_present",
            "passed": id_set_pass and duplicate_count == 0,
            "evidence": {
                "actual_rows": len(actual_rows),
                "unique_rows": len(actual),
                "expected": len(expected_ids),
            },
        },
        {
            "check_id": "all_cell_support_values_independently_recomputed",
            "passed": all(row["status"] == "PASS" for row in audits),
            "evidence": {
                "passed": sum(row["status"] == "PASS" for row in audits),
                "total": len(audits),
            },
        },
        {
            "check_id": "physician_probability_constant_within_npi",
            "passed": weight_errors == 0,
            "evidence": weight_errors,
        },
        {
            "check_id": "all_frozen_contrasts_exactly_present",
            "passed": contrast_id_pass,
            "evidence": {
                "actual": len(actual_contrasts),
                "expected": len(expected_contrasts),
            },
        },
        {
            "check_id": "contrast_premodel_support_status_recomputed",
            "passed": not contrast_errors,
            "evidence": contrast_errors,
        },
        {
            "check_id": "outcome_and_result_interpretation_remain_gated",
            "passed": (
                manifest.get("outcome_specific_support_pending") is True
                and gate.get("result_interpretation_authorized") is False
            ),
            "evidence": {
                "outcome_specific_support_pending": manifest.get(
                    "outcome_specific_support_pending"
                ),
                "result_interpretation_authorized": gate.get(
                    "result_interpretation_authorized"
                ),
            },
        },
    ]
    status = "PASS" if all(c["passed"] for c in checks) else "FAIL"
    payload = {
        "audit_id": "independent_directional_cell_support_audit_v1",
        "created_utc": utc_now(),
        "status": status,
        "checks_passed": sum(c["passed"] for c in checks),
        "checks_total": len(checks),
        "checks": checks,
        "cell_audit_csv": {
            "path": str(cell_csv),
            "sha256": sha256(cell_csv),
            "rows": len(audits),
        },
        "support_manifest_sha256": sha256(manifest_path),
        "directional_base_audit_sha256": sha256(base_audit_path),
        "extension_manifest_sha256": sha256(extension_path),
        "source_release_modified": False,
        "phase2_cohort_modified": False,
    }
    output = (
        phase2 / "qa" / "independent_directional_cell_support_audit.json"
    )
    atomic_json(output, payload)
    print(json.dumps(payload, indent=2), flush=True)
    if status != "PASS":
        raise RuntimeError(f"Directional support audit failed: {output}")


if __name__ == "__main__":
    main()
