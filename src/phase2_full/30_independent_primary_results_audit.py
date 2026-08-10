#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/30_independent_primary_results_audit.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Independently recompute key primary coefficients and contrast identities."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


class ColumnView:
    def __init__(self, base: np.ndarray, columns: list[int]) -> None:
        self.base = base
        self.columns = np.asarray(columns, dtype=np.int64)
        self.shape = (base.shape[0], len(columns))

    def __getitem__(self, key: Any) -> np.ndarray:
        rows, local_columns = key
        selected = self.columns[local_columns]
        return self.base[rows, :][:, selected]


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def chunks(n: int, size: int) -> Iterable[tuple[int, int]]:
    for start in range(0, n, size):
        yield start, min(n, start + size)


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    os.replace(temporary, path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_gate_binding(manifest: dict[str, Any]) -> None:
    """Independently fail closed on stale provider-v2 matrix bindings."""
    if (
        manifest.get("provider_measurement_version")
        != "provider_master_v2_full_name_race_v1"
    ):
        raise RuntimeError("Matrix provider measurement version is not v2")
    for path_field, hash_field in (
        ("provider_gate_path", "provider_gate_sha256"),
        ("cohort_gate_path", "cohort_gate_sha256"),
        ("gender_checkpoint_path", "gender_checkpoint_sha256"),
    ):
        path = Path(str(manifest.get(path_field, ""))).resolve()
        expected = str(manifest.get(hash_field, "")).lower()
        if (
            len(expected) != 64
            or not path.is_file()
            or sha256_file(path).lower() != expected
        ):
            raise RuntimeError(f"Stale or missing matrix gate: {path_field}")
        gate = json.loads(path.read_text(encoding="utf-8"))
        if gate.get("status") != "PASS":
            raise RuntimeError(f"Nonpassing matrix gate: {path}")


def crossproducts(
    x: np.ndarray, y: np.ndarray, row_chunk: int
) -> tuple[np.ndarray, np.ndarray]:
    xtx = np.zeros((x.shape[1], x.shape[1]), dtype=np.float64)
    xty = np.zeros((x.shape[1], y.shape[1]), dtype=np.float64)
    for start, stop in chunks(x.shape[0], row_chunk):
        xb = np.asarray(x[start:stop, :], dtype=np.float64)
        yb = np.asarray(y[start:stop, :], dtype=np.float64)
        xtx += xb.T @ xb
        xty += xb.T @ yb
    return xtx, xty


def candidate_columns(
    cohort: str,
    names: list[str],
    groups: list[str],
) -> dict[str, list[int]]:
    m1 = [
        index
        for index, group in enumerate(groups)
        if group
        in (
            "intercept",
            "exposure",
            "primary_interaction",
            "patient_visit",
            "patient_risk",
        )
    ]
    m2 = [
        index
        for index, group in enumerate(groups)
        if group
        not in (
            "intercept",
            "sensitivity_exposure",
            "sensitivity_interaction",
            "selection_only",
        )
        and not group.startswith("heterogeneity_")
        and group != "intersectional"
    ]
    absorbed_physician_main = (
        "physician_black_proxy"
        if cohort == "race"
        else "physician_female"
    )
    m3 = [
        index
        for index, (name, group) in enumerate(zip(names, groups))
        if group != "intercept"
        and group
        not in (
            "sensitivity_exposure",
            "sensitivity_interaction",
            "selection_only",
        )
        and not group.startswith("heterogeneity_")
        and group != "intersectional"
        and name != absorbed_physician_main
        and (
            group != "physician"
            or name
            in (
                "log1p_physician_quarter_volume",
                "physician_quarter_volume_missing",
            )
        )
    ]
    return {
        "m1_patient_adjusted": m1,
        "m2_fully_adjusted_facility_yq_clinical_fe": m2,
        "m3_physician_facility_yq_clinical_fe": m3,
    }


def audit_cohort(
    phase2: Path,
    matrix_root: Path,
    primary_scratch: Path,
    cohort: str,
    row_chunk: int,
    matrix_id: str | None = None,
    results_root: Path | None = None,
    scratch_id: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    resolved_matrix_id = matrix_id or cohort
    resolved_scratch_id = scratch_id or cohort
    resolved_results_root = results_root or (phase2 / "results" / "models")
    root = matrix_root / resolved_matrix_id
    manifest = json.loads(
        (root / "matrix_manifest.json").read_text(encoding="utf-8")
    )
    validate_gate_binding(manifest)
    n = int(manifest["n_rows"])
    spec = manifest["design_spec"]
    names = [item["name"] for item in spec]
    groups = [item["group"] for item in spec]
    outcome_names = list(manifest["outcomes"])
    primary_outcomes = list(manifest["primary_outcomes"])
    primary_indices = [
        outcome_names.index(name) for name in primary_outcomes
    ]
    raw = np.memmap(
        root / "raw_design.float64.mmap",
        dtype=np.float64,
        mode="r",
        shape=(n, len(names)),
    )
    outcomes = np.memmap(
        root / "model_outcomes.float64.mmap",
        dtype=np.float64,
        mode="r",
        shape=(n, len(outcome_names)),
    )
    raw_primary_y = ColumnView(outcomes, primary_indices)
    model_results = pd.read_csv(
        resolved_results_root
        / cohort
        / "primary_model_coefficients.csv"
    )
    specs = candidate_columns(cohort, names, groups)
    rows: list[dict[str, Any]] = []
    model_details: dict[str, Any] = {}
    interaction = (
        "race_interaction"
        if cohort == "race"
        else "sex_gender_interaction"
    )

    for model_id, columns in specs.items():
        diagnostic_path = (
            resolved_results_root
            / cohort
            / f"{model_id}_diagnostics.json"
        )
        diagnostic = json.loads(diagnostic_path.read_text(encoding="utf-8"))
        local_names = [names[index] for index in columns]
        kept_names = list(diagnostic["kept_columns"])
        kept_local = [local_names.index(name) for name in kept_names]
        if model_id == "m1_patient_adjusted":
            candidate_x: np.ndarray = ColumnView(raw, columns)
            y: np.ndarray = raw_primary_y
        else:
            folder = primary_scratch / resolved_scratch_id / model_id
            candidate_x = np.memmap(
                folder / "demeaned_design.float64.mmap",
                dtype=np.float64,
                mode="r",
                shape=(n, len(columns)),
            )
            all_y = np.memmap(
                folder / "demeaned_outcomes.float64.mmap",
                dtype=np.float64,
                mode="r",
                shape=(n, len(outcome_names)),
            )
            y = ColumnView(all_y, primary_indices)
        x = ColumnView(candidate_x, kept_local)
        xtx, xty = crossproducts(x, y, row_chunk)
        beta = np.linalg.solve(xtx, xty)
        saved = model_results.loc[
            (model_results["model_id"] == model_id)
            & model_results["outcome"].isin(primary_outcomes)
            & model_results["term"].isin(kept_names)
        ].copy()
        maximum_difference = 0.0
        comparisons = 0
        for outcome_offset, outcome in enumerate(primary_outcomes):
            block = saved.loc[saved["outcome"] == outcome].set_index("term")
            for term_offset, term in enumerate(kept_names):
                expected = float(beta[term_offset, outcome_offset])
                observed = float(block.loc[term, "estimate"])
                difference = abs(expected - observed)
                maximum_difference = max(maximum_difference, difference)
                comparisons += 1
        scale = max(
            1.0,
            float(np.max(np.abs(beta))),
        )
        coefficient_pass = maximum_difference <= 1e-8 * scale

        interaction_rows = saved.loc[saved["term"] == interaction]
        covariance_differences = []
        for _, saved_row in interaction_rows.iterrows():
            outcome = str(saved_row["outcome"])
            selected = diagnostic["selected_vcov"][outcome]
            order = selected["coefficient_order"]
            position = order.index(interaction)
            covariance = np.asarray(selected["covariance"], dtype=float)
            recomputed_se = math.sqrt(max(covariance[position, position], 0))
            covariance_differences.append(
                abs(recomputed_se - float(saved_row["clustered_standard_error"]))
            )
        maximum_se_difference = max(covariance_differences, default=0.0)
        covariance_pass = maximum_se_difference <= 1e-12
        rows.append(
            {
                "cohort": cohort,
                "matrix_id": resolved_matrix_id,
                "analysis_sample_policy": manifest.get(
                    "analysis_sample_policy", "legacy_unspecified"
                ),
                "eligibility_policy": manifest.get(
                    "eligibility_policy", "primary"
                ),
                "audit_check": f"{model_id}_coefficient_recomputation",
                "value": maximum_difference,
                "tolerance": 1e-8 * scale,
                "passed": coefficient_pass,
                "details": f"{comparisons} saved primary-outcome coefficients",
            }
        )
        rows.append(
            {
                "cohort": cohort,
                "matrix_id": resolved_matrix_id,
                "analysis_sample_policy": manifest.get(
                    "analysis_sample_policy", "legacy_unspecified"
                ),
                "eligibility_policy": manifest.get(
                    "eligibility_policy", "primary"
                ),
                "audit_check": f"{model_id}_saved_covariance_to_se",
                "value": maximum_se_difference,
                "tolerance": 1e-12,
                "passed": covariance_pass,
                "details": "interaction standard errors",
            }
        )
        model_details[model_id] = {
            "n": n,
            "kept_columns": len(kept_names),
            "maximum_absolute_coefficient_difference": maximum_difference,
            "maximum_absolute_standard_error_difference": maximum_se_difference,
            "coefficient_recomputation_passed": coefficient_pass,
            "covariance_reconciliation_passed": covariance_pass,
        }

    physician_term = (
        "physician_black_proxy"
        if cohort == "race"
        else "physician_female"
    )
    patient_term = (
        "patient_black" if cohort == "race" else "patient_female"
    )
    exposure_columns = [
        names.index(physician_term),
        names.index(patient_term),
        names.index(interaction),
    ]
    cell_counts = np.zeros(4, dtype=np.int64)
    cell_sums = np.zeros((4, len(primary_outcomes)), dtype=np.float64)
    saturated_xtx = np.zeros((4, 4), dtype=np.float64)
    saturated_xty = np.zeros((4, len(primary_outcomes)), dtype=np.float64)
    for start, stop in chunks(n, row_chunk):
        exposure = np.asarray(
            raw[start:stop, exposure_columns], dtype=np.float64
        )
        yb = np.asarray(raw_primary_y[start:stop, :], dtype=np.float64)
        physician = exposure[:, 0].astype(np.int64)
        patient = exposure[:, 1].astype(np.int64)
        cell = physician * 2 + patient
        for value in range(4):
            mask = cell == value
            cell_counts[value] += int(mask.sum())
            cell_sums[value] += yb[mask].sum(axis=0)
        saturated = np.column_stack(
            [np.ones(len(exposure)), exposure]
        )
        saturated_xtx += saturated.T @ saturated
        saturated_xty += saturated.T @ yb
    cell_means = cell_sums / cell_counts[:, None]
    # Code order is 00, 01, 10, 11. Requested contrast is 11 - 10 - 01 + 00.
    cell_contrast = (
        cell_means[3] - cell_means[2] - cell_means[1] + cell_means[0]
    )
    saturated_beta = np.linalg.solve(saturated_xtx, saturated_xty)
    identity_difference = float(
        np.max(np.abs(cell_contrast - saturated_beta[3]))
    )
    order_pass = identity_difference <= 1e-10
    rows.append(
        {
            "cohort": cohort,
            "matrix_id": resolved_matrix_id,
            "analysis_sample_policy": manifest.get(
                "analysis_sample_policy", "legacy_unspecified"
            ),
            "eligibility_policy": manifest.get(
                "eligibility_policy", "primary"
            ),
            "audit_check": "physician_first_four_cell_contrast_identity",
            "value": identity_difference,
            "tolerance": 1e-10,
            "passed": order_pass,
            "details": (
                "cell code 11 - 10 - 01 + 00 equals coefficient on "
                f"{interaction}"
            ),
        }
    )
    details = {
        "cohort": cohort,
        "matrix_id": resolved_matrix_id,
        "analysis_sample_policy": manifest.get(
            "analysis_sample_policy", "legacy_unspecified"
        ),
        "eligibility_policy": manifest.get(
            "eligibility_policy", "primary"
        ),
        "n_analysis_sample": n,
        "primary_outcomes": primary_outcomes,
        "model_details": model_details,
        "cell_code_order": ["00", "01", "10", "11"],
        "cell_counts": cell_counts.tolist(),
        "cell_means": {
            outcome: cell_means[:, offset].tolist()
            for offset, outcome in enumerate(primary_outcomes)
        },
        "four_cell_contrast": {
            outcome: float(cell_contrast[offset])
            for offset, outcome in enumerate(primary_outcomes)
        },
        "saturated_interaction": {
            outcome: float(saturated_beta[3, offset])
            for offset, outcome in enumerate(primary_outcomes)
        },
        "physician_patient_order_passed": order_pass,
    }
    return rows, details


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    parser.add_argument("--matrix-root", required=True, type=Path)
    parser.add_argument("--primary-scratch", required=True, type=Path)
    parser.add_argument("--row-chunk", type=int, default=333_333)
    args = parser.parse_args()
    phase2 = args.phase2.resolve()
    all_rows: list[dict[str, Any]] = []
    details: dict[str, Any] = {}
    for cohort in ("race", "sex_gender"):
        rows, payload = audit_cohort(
            phase2,
            args.matrix_root.resolve(),
            args.primary_scratch.resolve(),
            cohort,
            args.row_chunk,
        )
        all_rows.extend(rows)
        details[cohort] = payload
    table = pd.DataFrame(all_rows)
    qa = phase2 / "qa"
    table.to_csv(qa / "independent_primary_results_audit.csv", index=False)
    summary = {
        "created_utc": now_utc(),
        "checks": len(table),
        "passed_checks": int(table["passed"].sum()),
        "failed_checks": int((~table["passed"]).sum()),
        "all_passed": bool(table["passed"].all()),
        "independent_implementations": [
            "independent NumPy cross-products and linear solve",
            "direct four-cell aggregation",
            "stored covariance-to-reported-SE reconciliation",
        ],
        "details": details,
    }
    atomic_json(qa / "independent_primary_results_audit.json", summary)
    if not summary["all_passed"]:
        raise RuntimeError(
            f"Independent primary results audit failed: {summary}"
        )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
