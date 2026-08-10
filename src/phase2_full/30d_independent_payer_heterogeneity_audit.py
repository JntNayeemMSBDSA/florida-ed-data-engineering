#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/30d_independent_payer_heterogeneity_audit.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Independently recompute saturated payer-heterogeneity coefficients."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


PAYER_LEVELS = (
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


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "missing"


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


class ColumnView:
    def __init__(self, base: Any, columns: list[int]) -> None:
        self.base = base
        self.columns = np.asarray(columns, dtype=np.int64)
        self.shape = (base.shape[0], len(columns))

    def __getitem__(self, key: Any) -> np.ndarray:
        rows, local_columns = key
        selected = self.columns[local_columns]
        return self.base[rows, :][:, selected]


class CombinedMatrix:
    def __init__(self, left: Any, right: Any) -> None:
        self.left = left
        self.right = right
        self.left_k = left.shape[1]
        self.shape = (left.shape[0], left.shape[1] + right.shape[1])

    def __getitem__(self, key: Any) -> np.ndarray:
        rows, columns = key
        logical = np.arange(self.shape[1])[columns]
        blocks: list[np.ndarray] = []
        for column in np.atleast_1d(logical):
            if column < self.left_k:
                blocks.append(np.asarray(self.left[rows, int(column)]))
            else:
                blocks.append(
                    np.asarray(
                        self.right[rows, int(column - self.left_k)]
                    )
                )
        result = np.column_stack(blocks)
        return result[:, 0] if np.isscalar(logical) else result


def crossproducts(
    x: Any, y: Any, row_chunk: int
) -> tuple[np.ndarray, np.ndarray]:
    xtx = np.zeros((x.shape[1], x.shape[1]), dtype=np.float64)
    xty = np.zeros((x.shape[1], y.shape[1]), dtype=np.float64)
    for start, stop in chunks(x.shape[0], row_chunk):
        xb = np.asarray(x[start:stop, :], dtype=np.float64)
        yb = np.asarray(y[start:stop, :], dtype=np.float64)
        xtx += xb.T @ xb
        xty += xb.T @ yb
    return xtx, xty


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    parser.add_argument("--matrix-root", required=True, type=Path)
    parser.add_argument("--primary-scratch", required=True, type=Path)
    parser.add_argument("--payer-scratch", required=True, type=Path)
    parser.add_argument("--row-chunk", type=int, default=333_333)
    args = parser.parse_args()

    phase2 = args.phase2.resolve()
    payer_results = phase2 / "results" / "payer_category_heterogeneity"
    payer_manifest = json.loads(
        (
            payer_results / "payer_category_heterogeneity_manifest.json"
        ).read_text(encoding="utf-8")
    )
    if payer_manifest.get("status") != "PASS":
        raise SystemExit("Payer heterogeneity manifest does not pass")

    root = args.matrix_root.resolve() / "race"
    manifest = json.loads(
        (root / "matrix_manifest.json").read_text(encoding="utf-8")
    )
    validate_gate_binding(manifest)
    n = int(manifest["n_rows"])
    names = [item["name"] for item in manifest["design_spec"]]
    groups = [item["group"] for item in manifest["design_spec"]]
    all_outcomes = list(manifest["outcomes"])
    primary_outcomes = list(manifest["primary_outcomes"])
    outcome_indices = [
        all_outcomes.index(name) for name in primary_outcomes
    ]
    base_columns = [
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
    base_names = [names[index] for index in base_columns]
    payer_names: list[str] = []
    payer_targets: list[str] = []
    for payer in PAYER_LEVELS:
        identifier = slug(payer)
        local = [
            f"payer_{identifier}_x_physician_black",
            f"payer_{identifier}_x_patient_black",
            f"payer_{identifier}_x_race_interaction",
        ]
        payer_names.extend(local)
        payer_targets.append(local[-1])
    combined_names = [*base_names, *payer_names]

    base_folder = (
        args.primary_scratch.resolve()
        / "race"
        / "m2_fully_adjusted_facility_yq_clinical_fe"
    )
    base_x = np.memmap(
        base_folder / "demeaned_design.float64.mmap",
        dtype=np.float64,
        mode="r",
        shape=(n, len(base_columns)),
    )
    base_y_all = np.memmap(
        base_folder / "demeaned_outcomes.float64.mmap",
        dtype=np.float64,
        mode="r",
        shape=(n, len(all_outcomes)),
    )
    y = ColumnView(base_y_all, outcome_indices)
    payer_x = np.memmap(
        args.payer_scratch.resolve()
        / "saturated_payer_interactions"
        / "demeaned_payer_interactions.float64.mmap",
        dtype=np.float64,
        mode="r",
        shape=(n, len(payer_names)),
    )
    combined = CombinedMatrix(base_x, payer_x)
    diagnostic_path = (
        payer_results
        / "m2_saturated_payer_category_heterogeneity_diagnostics.json"
    )
    diagnostic = json.loads(diagnostic_path.read_text(encoding="utf-8"))
    kept_names = list(diagnostic["kept_columns"])
    kept_indices = [combined_names.index(name) for name in kept_names]
    x = ColumnView(combined, kept_indices)
    xtx, xty = crossproducts(x, y, args.row_chunk)
    beta = np.linalg.solve(xtx, xty)

    saved = pd.read_csv(
        payer_results / "payer_category_heterogeneity_coefficients.csv"
    )
    target_names = ["race_interaction", *payer_targets]
    maximum_coefficient_difference = 0.0
    comparisons = 0
    for outcome_offset, outcome in enumerate(primary_outcomes):
        saved_outcome = saved.loc[saved["outcome"] == outcome].set_index("term")
        for target in target_names:
            if target not in kept_names:
                raise RuntimeError(f"Expected target was not identified: {target}")
            expected = float(beta[kept_names.index(target), outcome_offset])
            observed = float(saved_outcome.loc[target, "estimate"])
            maximum_coefficient_difference = max(
                maximum_coefficient_difference,
                abs(expected - observed),
            )
            comparisons += 1
    scale = max(1.0, float(np.max(np.abs(beta))))
    coefficient_pass = maximum_coefficient_difference <= 1e-8 * scale

    maximum_se_difference = 0.0
    se_comparisons = 0
    for outcome in primary_outcomes:
        selected = diagnostic["selected_vcov"][outcome]
        order = list(selected["coefficient_order"])
        covariance = np.asarray(selected["covariance"], dtype=float)
        saved_outcome = saved.loc[saved["outcome"] == outcome].set_index("term")
        for target in target_names:
            position = order.index(target)
            recomputed = math.sqrt(
                max(float(covariance[position, position]), 0.0)
            )
            observed = float(
                saved_outcome.loc[target, "clustered_standard_error"]
            )
            maximum_se_difference = max(
                maximum_se_difference, abs(recomputed - observed)
            )
            se_comparisons += 1
    se_pass = maximum_se_difference <= 1e-12
    target_table = saved.loc[
        saved["term"].isin(payer_targets)
    ].copy()
    numeric_targets = target_table[
        [
            "estimate",
            "clustered_standard_error",
            "ci95_low",
            "ci95_high",
            "p_value",
            "n",
        ]
    ].apply(pd.to_numeric, errors="coerce")
    structure_pass = bool(
        len(target_table) == len(PAYER_LEVELS) * len(primary_outcomes)
        and set(target_table["payer_reference_category"]) == {"Commercial"}
        and np.isfinite(numeric_targets.to_numpy(dtype=float)).all()
    )
    checks = pd.DataFrame(
        [
            {
                "audit_check": "independent_coefficient_recomputation",
                "passed": coefficient_pass,
                "value": maximum_coefficient_difference,
                "tolerance": 1e-8 * scale,
                "comparisons": comparisons,
            },
            {
                "audit_check": "stored_covariance_to_reported_se",
                "passed": se_pass,
                "value": maximum_se_difference,
                "tolerance": 1e-12,
                "comparisons": se_comparisons,
            },
            {
                "audit_check": "jointly_saturated_target_structure",
                "passed": structure_pass,
                "value": len(target_table),
                "tolerance": len(PAYER_LEVELS) * len(primary_outcomes),
                "comparisons": len(target_table),
            },
        ]
    )
    qa = phase2 / "qa"
    checks_path = qa / "independent_payer_heterogeneity_audit.csv"
    checks.to_csv(checks_path, index=False)
    summary = {
        "created_utc": now_utc(),
        "audit_id": "independent_payer_heterogeneity_audit_v1",
        "all_passed": bool(checks["passed"].all()),
        "checks": len(checks),
        "passed_checks": int(checks["passed"].sum()),
        "failed_checks": int((~checks["passed"]).sum()),
        "payer_reference_category": "Commercial",
        "payer_categories": list(PAYER_LEVELS),
        "outcomes": primary_outcomes,
        "independent_methods": [
            "fresh NumPy cross-products and linear solve",
            "stored covariance diagonal-to-SE reconciliation",
            "independent target/reference structure check",
        ],
        "artifacts": {"check_table": str(checks_path)},
    }
    atomic_json(qa / "independent_payer_heterogeneity_audit.json", summary)
    if not summary["all_passed"]:
        raise RuntimeError("Independent payer heterogeneity audit failed")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
