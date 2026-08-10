#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/43b_independent_directional_family_audit.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Independently audit directional aggregation and frozen BH calculations."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


FAMILIES = ("gender_dyads", "race_dyads", "intersectional_dyads")
EXPECTED_OUTCOMES = 33
EXPECTED_CONTRASTS = {
    "gender_dyads": 6,
    "race_dyads": 68,
    "intersectional_dyads": 359,
}
EXPECTED_CELLS = {
    "gender_dyads": 4,
    "race_dyads": 25,
    "intersectional_dyads": 100,
}
AUDIT_NAMES = {
    "gender_dyads": "independent_directional_gender_results_audit.json",
    "race_dyads": "independent_directional_race_results_audit.json",
    "intersectional_dyads": (
        "independent_directional_intersectional_results_audit.json"
    ),
}


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(4 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    os.replace(temporary, path)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def independent_bh(values: np.ndarray) -> np.ndarray:
    order = np.lexsort((np.arange(len(values)), values))
    sorted_values = values[order]
    raw = sorted_values * len(values) / np.arange(1, len(values) + 1)
    monotone = np.minimum.accumulate(raw[::-1])[::-1]
    output = np.empty_like(monotone)
    output[order] = np.clip(monotone, 0, 1)
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    args = parser.parse_args()
    phase2 = args.phase2.resolve()
    final_root = phase2 / "results" / "directional_dyads" / "final"
    manifest_path = final_root / "directional_multiplicity_manifest.json"
    if not manifest_path.is_file():
        raise SystemExit("Directional multiplicity manifest missing")
    manifest = load_json(manifest_path)
    if (
        manifest.get("status")
        != "AGGREGATION_COMPLETE_INDEPENDENT_AUDIT_PENDING"
        or manifest.get("source_result_sets") != 99
        or manifest.get("original_confirmatory_holm_family_modified") is not False
        or manifest.get("result_interpretation_authorized") is not False
    ):
        raise SystemExit("Directional multiplicity manifest gate failed")
    source_checks = []
    for source in manifest["sources"]:
        checks = []
        for path_key, hash_key in (
            ("result_audit_path", "result_audit_sha256"),
            ("result_manifest_path", "result_manifest_sha256"),
            ("contrast_path", "contrast_sha256"),
            ("prediction_path", "prediction_sha256"),
            ("unadjusted_path", "unadjusted_sha256"),
        ):
            path = Path(source[path_key])
            actual = sha256_file(path) if path.is_file() else ""
            checks.append(actual == source[hash_key])
        audit = load_json(Path(source["result_audit_path"]))
        passed = all(checks) and audit.get("status") == "PASS"
        source_checks.append(
            {
                "family_id": source["family_id"],
                "outcome": source["outcome"],
                "passed": passed,
            }
        )
    if not all(item["passed"] for item in source_checks):
        raise SystemExit("Directional aggregate source hash/audit failure")

    output_lookup = {
        Path(item["path"]).name: item for item in manifest["outputs"]
    }
    contrast_path = (
        final_root / "directional_planned_contrasts_with_multiplicity.csv"
    )
    prediction_path = final_root / "directional_adjusted_predictions.csv"
    unadjusted_path = final_root / "directional_unadjusted_cell_summaries.csv"
    output_hash_checks = []
    for path in (contrast_path, prediction_path, unadjusted_path):
        record = output_lookup[path.name]
        actual = sha256_file(path)
        output_hash_checks.append(
            {
                "path": str(path),
                "expected_sha256": record["sha256"],
                "actual_sha256": actual,
                "passed": actual == record["sha256"],
            }
        )
    contrasts = pd.read_csv(contrast_path)
    predictions = pd.read_csv(prediction_path)
    unadjusted = pd.read_csv(unadjusted_path)

    bh_mismatches = []
    estimable = contrasts["multiplicity_status"].eq(
        "BH_ADJUSTED_WITHIN_FROZEN_FAMILY"
    )
    for family_id, block in contrasts.loc[estimable].groupby(
        "multiplicity_family_id", sort=True
    ):
        values = block["p_value_raw"].to_numpy(dtype=np.float64)
        expected = independent_bh(values)
        actual = block["q_value_bh"].to_numpy(dtype=np.float64)
        if not np.allclose(expected, actual, rtol=1e-12, atol=1e-14):
            bh_mismatches.append(family_id)
        if np.any(actual + 1e-14 < values):
            bh_mismatches.append(f"{family_id}:q_below_p")
    excluded = ~estimable
    if (
        pd.to_numeric(
            contrasts.loc[excluded, "q_value_bh"], errors="coerce"
        )
        .notna()
        .any()
    ):
        bh_mismatches.append("excluded_rows_have_q_values")

    family_payloads = {}
    overall_failures = []
    for family in FAMILIES:
        family_contrasts = contrasts.loc[
            contrasts["family_id"].eq(family)
        ]
        family_predictions = predictions.loc[
            predictions["family_id"].eq(family)
        ]
        family_unadjusted = unadjusted.loc[
            unadjusted["family_id"].eq(family)
        ]
        source_count = sum(
            item["family_id"] == family for item in source_checks
        )
        expected_contrast_rows = (
            EXPECTED_OUTCOMES * EXPECTED_CONTRASTS[family] * 3
        )
        expected_prediction_rows = (
            EXPECTED_OUTCOMES * EXPECTED_CELLS[family] * 2
        )
        expected_unadjusted_rows = (
            EXPECTED_OUTCOMES * EXPECTED_CELLS[family]
        )
        failures = []
        if source_count != EXPECTED_OUTCOMES:
            failures.append("source_outcome_count")
        if len(family_contrasts) != expected_contrast_rows:
            failures.append("contrast_row_count")
        if len(family_predictions) != expected_prediction_rows:
            failures.append("prediction_row_count")
        if len(family_unadjusted) != expected_unadjusted_rows:
            failures.append("unadjusted_row_count")
        family_bh_mismatches = [
            value
            for value in bh_mismatches
            if value.startswith(family)
        ]
        if family_bh_mismatches:
            failures.append("bh_recomputation")
        finite_estimable = ~family_contrasts[
            "estimability_status"
        ].astype(str).str.startswith("NON_ESTIMABLE")
        numeric = family_contrasts.loc[
            finite_estimable,
            [
                "estimate",
                "standard_error",
                "ci95_low",
                "ci95_high",
                "p_value_raw",
                "q_value_bh",
            ],
        ].to_numpy(dtype=np.float64)
        nonfinite_rows = int((~np.isfinite(numeric)).any(axis=1).sum())
        if nonfinite_rows:
            failures.append("nonfinite_estimable_rows")
        payload = {
            "audit_id": f"independent_{family}_results_audit_v1",
            "created_utc": now_utc(),
            "status": "PASS" if not failures else "FAIL",
            "family_id": family,
            "source_outcomes_audited": source_count,
            "expected_outcomes": EXPECTED_OUTCOMES,
            "contrast_rows": len(family_contrasts),
            "prediction_rows": len(family_predictions),
            "unadjusted_rows": len(family_unadjusted),
            "expected_contrast_rows": expected_contrast_rows,
            "expected_prediction_rows": expected_prediction_rows,
            "expected_unadjusted_rows": expected_unadjusted_rows,
            "multiplicity_families": int(
                family_contrasts["multiplicity_family_id"].nunique()
            ),
            "bh_recomputation_mismatches": family_bh_mismatches,
            "nonfinite_estimable_rows": nonfinite_rows,
            "multiplicity_manifest_sha256": sha256_file(manifest_path),
            "final_contrast_sha256": sha256_file(contrast_path),
            "final_prediction_sha256": sha256_file(prediction_path),
            "final_unadjusted_sha256": sha256_file(unadjusted_path),
            "failures": failures,
            "association_language_required": True,
            "physician_race_algorithm_inferred": family != "gender_dyads",
            "physician_race_is_bisg": False,
            "directional_result_interpretation_authorized": not failures,
            "full_project_report_finalization_authorized": False,
            "source_release_modified": False,
            "phase2_cohort_modified": False,
        }
        output = phase2 / "qa" / AUDIT_NAMES[family]
        atomic_json(output, payload)
        family_payloads[family] = {
            "status": payload["status"],
            "audit_path": str(output),
            "audit_sha256": sha256_file(output),
        }
        if failures:
            overall_failures.append(family)

    overall = {
        "audit_id": "independent_directional_family_aggregate_audit_v1",
        "created_utc": now_utc(),
        "status": "PASS" if not overall_failures and not bh_mismatches else "FAIL",
        "source_result_sets": len(source_checks),
        "source_checks_passed": sum(item["passed"] for item in source_checks),
        "output_hash_checks": output_hash_checks,
        "bh_recomputation_mismatches": bh_mismatches,
        "families": family_payloads,
        "failures": overall_failures,
        "result_values_emitted_to_stdout": False,
        "full_project_report_finalization_authorized": False,
    }
    overall_path = (
        phase2 / "qa" / "independent_directional_family_aggregate_audit.json"
    )
    atomic_json(overall_path, overall)
    print(
        json.dumps(
            {
                "status": overall["status"],
                "source_result_sets": len(source_checks),
                "families": {
                    key: value["status"]
                    for key, value in family_payloads.items()
                },
                "bh_mismatch_count": len(bh_mismatches),
                "result_values_emitted": False,
            },
            indent=2,
        )
    )
    if overall["status"] != "PASS":
        raise SystemExit("Independent directional family audit failed")


if __name__ == "__main__":
    main()
