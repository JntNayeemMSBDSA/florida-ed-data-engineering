#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/43_apply_directional_multiplicity.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Aggregate audited directional results and apply frozen BH families."""

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
OUTCOMES = (
    "los_hours_primary_0_168",
    "total_charge_reported_real_2024",
    "procedure_count_analysis",
    "any_procedure_flag",
    "high_procedure_flag",
    "em_acuity_proxy_level",
    "em_critical_care_flag",
    "routine_discharge_flag",
    "transfer_flag",
    "hospice_flag",
    "mortality_flag",
    "left_discontinued_care_flag",
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
    "higher_discretion_procedure_count",
    "lower_discretion_procedure_count",
    "ambiguous_discretion_procedure_count",
    "any_higher_discretion_candidate_flag",
    "any_lower_discretion_candidate_flag",
    "higher_minus_lower_discretion_procedure_count",
    "any_higher_minus_any_lower_discretion_candidate",
)


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


def bh_adjust(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64)
    order = np.argsort(values, kind="mergesort")
    ranked = values[order]
    adjusted = ranked * len(ranked) / np.arange(1, len(ranked) + 1)
    adjusted = np.minimum.accumulate(adjusted[::-1])[::-1]
    result = np.empty_like(adjusted)
    result[order] = np.minimum(adjusted, 1.0)
    return result


def multiplicity_family(row: pd.Series) -> str:
    family = row["family_id"]
    model = row["model_id"]
    outcome_family = row["outcome_family"]
    if model == "M2_DIRECTIONAL":
        if outcome_family == "primary":
            return f"{family}__m2_primary_two_outcomes"
        return f"{family}__m2_{outcome_family}"
    if model == "M3_WITHIN_PHYSICIAN":
        return f"{family}__m3_sensitivity_{outcome_family}"
    return f"{family}__u0_descriptive_{outcome_family}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    parser.add_argument("--results-root", required=True, type=Path)
    args = parser.parse_args()
    phase2 = args.phase2.resolve()
    results_root = args.results_root.resolve()
    final_root = phase2 / "results" / "directional_dyads" / "final"
    final_root.mkdir(parents=True, exist_ok=True)

    source_records = []
    contrasts = []
    predictions = []
    unadjusted = []
    for family in FAMILIES:
        for outcome in OUTCOMES:
            audit_path = (
                phase2
                / "qa"
                / "directional_result_audits"
                / f"{family}__{outcome}.json"
            )
            result_dir = results_root / family / outcome
            manifest_path = result_dir / "directional_estimation_manifest.json"
            if not audit_path.is_file() or not manifest_path.is_file():
                raise SystemExit(
                    f"Directional result/audit missing: {family} {outcome}"
                )
            audit = load_json(audit_path)
            manifest = load_json(manifest_path)
            if (
                audit.get("status") != "PASS"
                or audit.get("result_manifest_sha256")
                != sha256_file(manifest_path)
                or audit.get("multiplicity_status")
                != "PENDING_FAMILY_AGGREGATION"
            ):
                raise SystemExit(
                    f"Directional result not ready for multiplicity: "
                    f"{family} {outcome}"
                )
            contrast_path = result_dir / "directional_planned_contrasts.csv"
            prediction_path = result_dir / "directional_adjusted_predictions.csv"
            unadjusted_path = (
                result_dir / "directional_unadjusted_cell_summaries.csv"
            )
            contrasts.append(pd.read_csv(contrast_path))
            predictions.append(pd.read_csv(prediction_path))
            unadjusted.append(pd.read_csv(unadjusted_path))
            source_records.append(
                {
                    "family_id": family,
                    "outcome": outcome,
                    "result_audit_path": str(audit_path),
                    "result_audit_sha256": sha256_file(audit_path),
                    "result_manifest_path": str(manifest_path),
                    "result_manifest_sha256": sha256_file(manifest_path),
                    "contrast_path": str(contrast_path),
                    "contrast_sha256": sha256_file(contrast_path),
                    "prediction_path": str(prediction_path),
                    "prediction_sha256": sha256_file(prediction_path),
                    "unadjusted_path": str(unadjusted_path),
                    "unadjusted_sha256": sha256_file(unadjusted_path),
                }
            )
    contrast_frame = pd.concat(contrasts, ignore_index=True)
    prediction_frame = pd.concat(predictions, ignore_index=True)
    unadjusted_frame = pd.concat(unadjusted, ignore_index=True)
    contrast_frame["multiplicity_family_id"] = contrast_frame.apply(
        multiplicity_family, axis=1
    )
    contrast_frame["q_value_bh"] = np.nan
    contrast_frame["multiplicity_status"] = (
        "EXCLUDED_NON_ESTIMABLE_OR_NONFINITE"
    )
    estimable = (
        ~contrast_frame["estimability_status"]
        .astype(str)
        .str.startswith("NON_ESTIMABLE")
        & np.isfinite(
            pd.to_numeric(
                contrast_frame["p_value_raw"], errors="coerce"
            ).to_numpy(dtype=np.float64)
        )
    )
    for family_id, indices in contrast_frame.loc[estimable].groupby(
        "multiplicity_family_id"
    ).groups.items():
        index = np.asarray(list(indices), dtype=np.int64)
        values = contrast_frame.loc[index, "p_value_raw"].to_numpy(
            dtype=np.float64
        )
        contrast_frame.loc[index, "q_value_bh"] = bh_adjust(values)
        contrast_frame.loc[index, "multiplicity_status"] = (
            "BH_ADJUSTED_WITHIN_FROZEN_FAMILY"
        )

    contrast_path = (
        final_root / "directional_planned_contrasts_with_multiplicity.csv"
    )
    prediction_path = final_root / "directional_adjusted_predictions.csv"
    unadjusted_path = final_root / "directional_unadjusted_cell_summaries.csv"
    contrast_frame.to_csv(contrast_path, index=False)
    prediction_frame.to_csv(prediction_path, index=False)
    unadjusted_frame.to_csv(unadjusted_path, index=False)
    outputs = []
    for path, rows in (
        (contrast_path, len(contrast_frame)),
        (prediction_path, len(prediction_frame)),
        (unadjusted_path, len(unadjusted_frame)),
    ):
        outputs.append(
            {
                "path": str(path),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "rows": rows,
            }
        )
    multiplicity_summary = (
        contrast_frame.groupby(
            ["family_id", "model_id", "multiplicity_family_id"],
            dropna=False,
        )
        .agg(
            rows=("contrast_id", "size"),
            estimable_rows=(
                "multiplicity_status",
                lambda x: int(
                    (x == "BH_ADJUSTED_WITHIN_FROZEN_FAMILY").sum()
                ),
            ),
        )
        .reset_index()
    )
    summary_path = final_root / "directional_multiplicity_family_counts.csv"
    multiplicity_summary.to_csv(summary_path, index=False)
    outputs.append(
        {
            "path": str(summary_path),
            "bytes": summary_path.stat().st_size,
            "sha256": sha256_file(summary_path),
            "rows": len(multiplicity_summary),
        }
    )
    manifest = {
        "status": "AGGREGATION_COMPLETE_INDEPENDENT_AUDIT_PENDING",
        "created_utc": now_utc(),
        "aggregation_version": "directional_multiplicity_v1_20260726",
        "source_result_sets": len(source_records),
        "families": list(FAMILIES),
        "outcomes": list(OUTCOMES),
        "contrast_rows": len(contrast_frame),
        "prediction_rows": len(prediction_frame),
        "unadjusted_rows": len(unadjusted_frame),
        "bh_family_count": int(
            contrast_frame["multiplicity_family_id"].nunique()
        ),
        "bh_rule": (
            "Benjamini-Hochberg within frozen family, model tier, and "
            "outcome-family grouping; the two primary outcomes are pooled "
            "within each directional M2 family as frozen."
        ),
        "original_confirmatory_holm_family_modified": False,
        "sources": source_records,
        "outputs": outputs,
        "aggregator_path": str(Path(__file__).resolve()),
        "aggregator_sha256": sha256_file(Path(__file__).resolve()),
        "independent_audit_status": "PENDING",
        "result_interpretation_authorized": False,
        "source_release_modified": False,
        "phase2_cohort_modified": False,
    }
    manifest_path = final_root / "directional_multiplicity_manifest.json"
    atomic_json(manifest_path, manifest)
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "source_result_sets": len(source_records),
                "contrast_rows": len(contrast_frame),
                "bh_family_count": manifest["bh_family_count"],
                "result_values_emitted": False,
                "result_interpretation_authorized": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
