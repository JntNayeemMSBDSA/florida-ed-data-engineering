#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/40_independent_directional_matrix_audit.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Independently audit one directional outcome matrix before estimation.

This audit verifies live hashes, exact source/sample counts, file sizes and
hashes, cell-basis moments, outcome-specific support, FE/cluster encodings,
and full-sample M2/M3 design rank/contrast identification.  It performs no
coefficient estimation and never opens a directional result file.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import duckdb
import numpy as np
import pandas as pd


FAMILIES = ("gender_dyads", "race_dyads", "intersectional_dyads")
SUPPORT_THRESHOLDS = {
    "minimum_effective_visits": 1000,
    "minimum_effective_physicians": 30,
    "minimum_facilities": 20,
    "minimum_physician_clusters": 30,
    "minimum_facility_clusters": 20,
    "limited_effective_visits": 5000,
    "limited_effective_physicians": 50,
    "limited_facilities": 30,
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


def qpath(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace("'", "''")


def chunks(n: int, size: int) -> Iterable[tuple[int, int]]:
    for start in range(0, n, size):
        yield start, min(n, start + size)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_engine(phase2: Path) -> Any:
    path = phase2 / "scripts" / "08_estimate_primary_models.py"
    spec = importlib.util.spec_from_file_location(
        "phase2_hdfe_engine_for_directional_audit", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load validated HDFE engine")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def audit_demeaning_provenance(
    state_path: Path,
    metadata: dict[str, Any],
    *,
    n_rows: int,
    n_columns: int,
    n_outcomes: int,
    block_columns: int,
    checkpoint_binding: dict[str, Any],
) -> dict[str, Any]:
    """Validate the complete strict-before-fallback transformation record."""
    failures: list[str] = []
    if not state_path.is_file():
        return {
            "status": "FAIL",
            "failures": ["demeaning_state.json is missing"],
        }
    state = load_json(state_path)
    column_indices = list(state.get("column_indices", []))
    attempts = dict(state.get("demeaning_attempts", {}))
    convergence = dict(state.get("convergence", {}))
    expected_attempts: dict[str, list[int]] = {}
    for start in range(0, n_columns, block_columns):
        stop = min(n_columns, start + block_columns)
        expected_attempts[f"x_{start}_{stop}"] = list(range(start, stop))
    for start in range(0, n_outcomes, block_columns):
        stop = min(n_outcomes, start + block_columns)
        expected_attempts[f"y_{start}_{stop}"] = list(range(start, stop))

    if state.get("n_rows") != n_rows:
        failures.append("row count mismatch")
    if column_indices != list(range(n_columns)):
        failures.append("column-index contract changed")
    if state.get("completed_local_columns") != list(range(n_columns)):
        failures.append("design transformation incomplete")
    if state.get("completed_outcome_columns") != list(range(n_outcomes)):
        failures.append("outcome transformation incomplete")
    if state.get("outcomes_completed") is not True:
        failures.append("outcomes_completed is not true")
    if state.get("checkpoint_binding") != checkpoint_binding:
        failures.append("state checkpoint binding mismatch")
    if metadata.get("checkpoint_binding") != checkpoint_binding:
        failures.append("returned checkpoint binding mismatch")
    if set(attempts) != set(expected_attempts):
        failures.append("attempt grid incomplete or unexpected")
    if set(convergence) != set(expected_attempts) or not all(
        value is True for value in convergence.values()
    ):
        failures.append("convergence grid incomplete or false")

    numerical_policy = dict(state.get("numerical_policy", {}))
    if numerical_policy.get("strict") != {
        "tolerance": 1e-8,
        "maxiter": 10_000,
        "backend": "rust",
    }:
        failures.append("strict policy mismatch")
    if numerical_policy.get(
        "fallback_only_after_documented_strict_nonconvergence"
    ) != {
        "tolerance": 1e-6,
        "maxiter": 50_000,
        "backend": "rust",
    }:
        failures.append("fallback policy mismatch")
    if numerical_policy.get(
        "sample_formula_fixed_effects_and_columns_changed"
    ) is not False:
        failures.append("scientific specification change recorded")

    fallback_keys: list[str] = []
    for key, expected_source in expected_attempts.items():
        attempt = dict(attempts.get(key, {}))
        if attempt.get("source_columns") != expected_source:
            failures.append(f"{key}: source columns mismatch")
        if attempt.get("final_status") != "CONVERGED":
            failures.append(f"{key}: final status not CONVERGED")
        if attempt.get("fallback_used") is True:
            fallback_keys.append(key)
            if not (
                attempt.get("strict_status") == "NONCONVERGED"
                and attempt.get("strict_tolerance") == 1e-8
                and attempt.get("strict_maxiter") == 10_000
                and attempt.get("fallback_tolerance") == 1e-6
                and attempt.get("fallback_maxiter") == 50_000
                and attempt.get("fallback_status") == "CONVERGED"
                and attempt.get("final_method") == "fallback"
            ):
                failures.append(
                    f"{key}: fallback lacks a documented strict failure"
                )
        elif not (
            attempt.get("strict_status") == "CONVERGED"
            and attempt.get("strict_tolerance") == 1e-8
            and attempt.get("strict_maxiter") == 10_000
            and attempt.get("final_method") == "strict"
            and attempt.get("fallback_used") is False
        ):
            failures.append(f"{key}: strict completion metadata invalid")
    if set(metadata.get("fallback_blocks", [])) != set(fallback_keys):
        failures.append("returned fallback blocks do not match state")
    if metadata.get("fallback_used") is not bool(fallback_keys):
        failures.append("returned fallback-used flag does not match state")
    if metadata.get("converged") is not True:
        failures.append("returned demeaning metadata is not converged")
    return {
        "status": "PASS" if not failures else "FAIL",
        "state_path": str(state_path.resolve()),
        "state_sha256": sha256_file(state_path),
        "attempts": len(attempts),
        "expected_attempts": len(expected_attempts),
        "fallback_blocks": fallback_keys,
        "failures": failures,
        "coefficient_or_outcome_estimates_read": False,
    }


def matrix_file_specs(n: int, k: int) -> dict[str, int]:
    return {
        "raw_design.float64.mmap": n * k * 8,
        "outcome.float64.mmap": n * 8,
        "fe_codes.uint64.mmap": n * 3 * 8,
        "cluster_codes.uint64.mmap": n * 3 * 8,
        "visit_hash.uint64.mmap": n * 8,
    }


def contrast_vector(
    contrast: dict[str, Any],
    cell_lookup: dict[str, int],
    k: int,
) -> np.ndarray:
    value = np.zeros(k, dtype=np.float64)
    for term in contrast["linear_combination"]:
        value[cell_lookup[term["cell_id"]]] = float(term["weight"])
    return value


def rank_and_projector(xtx: np.ndarray) -> tuple[int, float, np.ndarray, float]:
    symmetric = (xtx + xtx.T) / 2
    eigenvalues, eigenvectors = np.linalg.eigh(symmetric)
    largest = max(float(eigenvalues[-1]), 1.0)
    tolerance = (
        max(symmetric.shape)
        * np.finfo(np.float64).eps
        * largest
        * 10.0
    )
    positive = eigenvalues > tolerance
    rank = int(positive.sum())
    if rank:
        basis = eigenvectors[:, positive]
        projector = basis @ basis.T
        condition = float(eigenvalues[positive].max() / eigenvalues[positive].min())
    else:
        projector = np.zeros_like(symmetric)
        condition = math.inf
    return rank, condition, projector, tolerance


def target_identified(target: np.ndarray, projector: np.ndarray) -> tuple[bool, float]:
    residual = target - projector @ target
    relative = float(
        np.linalg.norm(residual) / max(np.linalg.norm(target), 1.0)
    )
    return relative <= 1e-8, relative


def crossproduct_only(
    x: np.ndarray, row_chunk: int
) -> tuple[np.ndarray, np.ndarray]:
    k = x.shape[1]
    xtx = np.zeros((k, k), dtype=np.float64)
    norm2 = np.zeros(k, dtype=np.float64)
    for start, stop in chunks(x.shape[0], row_chunk):
        block = np.asarray(x[start:stop, :], dtype=np.float64)
        xtx += block.T @ block
        norm2 += np.einsum("ij,ij->j", block, block)
    return xtx, norm2


def source_cell_expressions(
    family: str, cells: list[dict[str, Any]]
) -> list[tuple[str, str, str]]:
    expressions = []
    for index, cell in enumerate(cells):
        alias = f"c{index:03d}"
        if family == "gender_dyads":
            weight = (
                "CAST(physician_gender_category = "
                f"'{cell['physician_group']}' AND patient_sex_category = "
                f"'{cell['patient_group']}' AS DOUBLE)"
            )
        elif family == "race_dyads":
            probability = PROBABILITY_COLUMNS[cell["physician_group"]]
            patient = cell["patient_group"].replace("'", "''")
            weight = (
                f"CAST({probability} AS DOUBLE) * "
                "CAST(patient_race_ethnicity_5cat = "
                f"'{patient}' AS DOUBLE)"
            )
        else:
            probability = PROBABILITY_COLUMNS[cell["physician_race"]]
            physician_gender = cell["physician_gender"].replace("'", "''")
            patient_race = cell["patient_race"].replace("'", "''")
            patient_sex = cell["patient_sex"].replace("'", "''")
            weight = (
                f"CAST({probability} AS DOUBLE) * "
                "CAST(physician_gender_category = "
                f"'{physician_gender}' AS DOUBLE) * "
                "CAST(patient_race_ethnicity_5cat = "
                f"'{patient_race}' AS DOUBLE) * "
                f"CAST(patient_sex_category = '{patient_sex}' AS DOUBLE)"
            )
        expressions.append((alias, weight, cell["cell_id"]))
    return expressions


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    parser.add_argument("--matrix-root", required=True, type=Path)
    parser.add_argument("--scratch-root", required=True, type=Path)
    parser.add_argument("--family", required=True, choices=FAMILIES)
    parser.add_argument("--outcome", required=True)
    parser.add_argument("--threads", type=int, default=12)
    parser.add_argument("--memory-limit", default="24GB")
    parser.add_argument("--row-chunk", type=int, default=100_000)
    parser.add_argument("--block-columns", type=int, default=4)
    parser.add_argument("--tolerance", type=float, default=1e-8)
    args = parser.parse_args()

    phase2 = args.phase2.resolve()
    matrix_dir = (
        args.matrix_root.resolve() / args.family / args.outcome
    )
    manifest_path = matrix_dir / "matrix_manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"Directional matrix manifest missing: {manifest_path}")
    manifest = load_json(manifest_path)
    if (
        manifest.get("status") != "PASS"
        or manifest.get("family_id") != args.family
        or manifest.get("outcome") != args.outcome
        or manifest.get("estimate_blind") is not True
        or manifest.get("model_estimates_read") is not False
    ):
        raise SystemExit("Directional matrix manifest is invalid or not estimate-blind")

    live_binding_checks: list[dict[str, Any]] = []
    for name, record in manifest["prerequisites"].items():
        path = Path(record["path"]).resolve()
        actual = sha256_file(path) if path.is_file() else ""
        passed = actual == record["sha256"]
        live_binding_checks.append(
            {
                "binding": name,
                "path": str(path),
                "expected_sha256": record["sha256"],
                "actual_sha256": actual,
                "passed": passed,
            }
        )
    builder_path = Path(manifest["matrix_builder_path"]).resolve()
    live_binding_checks.append(
        {
            "binding": "matrix_builder",
            "path": str(builder_path),
            "expected_sha256": manifest["matrix_builder_sha256"],
            "actual_sha256": (
                sha256_file(builder_path) if builder_path.is_file() else ""
            ),
            "passed": (
                builder_path.is_file()
                and sha256_file(builder_path)
                == manifest["matrix_builder_sha256"]
            ),
        }
    )
    if not all(item["passed"] for item in live_binding_checks):
        raise SystemExit("Directional matrix live binding check failed")

    n = int(manifest["n_rows"])
    k = int(manifest["n_design_columns"])
    q = int(manifest["n_cell_columns"])
    expected_files = matrix_file_specs(n, k)
    file_audit = []
    for name, expected_bytes in expected_files.items():
        path = matrix_dir / name
        passed = path.is_file() and path.stat().st_size == expected_bytes
        file_audit.append(
            {
                "name": name,
                "path": str(path),
                "expected_bytes": expected_bytes,
                "actual_bytes": path.stat().st_size if path.is_file() else None,
                "size_pass": passed,
                "sha256": sha256_file(path) if passed else "",
            }
        )
    if not all(item["size_pass"] for item in file_audit):
        raise SystemExit("Directional matrix file-size audit failed")

    raw = np.memmap(
        matrix_dir / "raw_design.float64.mmap",
        dtype=np.float64,
        mode="r",
        shape=(n, k),
    )
    outcome = np.memmap(
        matrix_dir / "outcome.float64.mmap",
        dtype=np.float64,
        mode="r",
        shape=(n, 1),
    )
    fe_codes = np.memmap(
        matrix_dir / "fe_codes.uint64.mmap",
        dtype=np.uint64,
        mode="r",
        shape=(n, 3),
    )
    clusters = np.memmap(
        matrix_dir / "cluster_codes.uint64.mmap",
        dtype=np.uint64,
        mode="r",
        shape=(n, 3),
    )
    visit_hash = np.memmap(
        matrix_dir / "visit_hash.uint64.mmap",
        dtype=np.uint64,
        mode="r",
        shape=(n,),
    )

    encoder_sizes = manifest["encoder_sizes"]
    n_physician = int(encoder_sizes["physician"])
    n_facility = int(encoder_sizes["facility"])
    cell_sum = np.zeros(q, dtype=np.float64)
    cell_sumsq = np.zeros(q, dtype=np.float64)
    cell_y_sum = np.zeros(q, dtype=np.float64)
    cell_y_sumsq = np.zeros(q, dtype=np.float64)
    physical_visits = np.zeros(q, dtype=np.int64)
    physician_max_weight = np.zeros((n_physician, q), dtype=np.float64)
    facility_seen = np.zeros((n_facility, q), dtype=bool)
    cell_sum_error_rows = 0
    bounds_error_rows = 0
    nonfinite_design_rows = 0
    nonfinite_outcome_rows = 0
    outcome_sum = 0.0
    outcome_sumsq = 0.0
    outcome_min = math.inf
    outcome_max = -math.inf
    visit_hash_xor = np.uint64(0)
    visit_hash_sum_mod64 = np.uint64(0)
    fe_cluster_physician_mismatch = 0
    for start, stop in chunks(n, args.row_chunk):
        xb = np.asarray(raw[start:stop, :], dtype=np.float64)
        cells = xb[:, :q]
        yb = np.asarray(outcome[start:stop, 0], dtype=np.float64)
        nonfinite_design_rows += int((~np.isfinite(xb).all(axis=1)).sum())
        nonfinite_outcome_rows += int((~np.isfinite(yb)).sum())
        row_sum = cells.sum(axis=1)
        cell_sum_error_rows += int(
            (~np.isclose(row_sum, 1.0, atol=1e-9, rtol=0)).sum()
        )
        bounds_error_rows += int(
            ((cells < -1e-12) | (cells > 1 + 1e-12)).any(axis=1).sum()
        )
        cell_sum += cells.sum(axis=0)
        cell_sumsq += np.einsum("ij,ij->j", cells, cells)
        cell_y_sum += cells.T @ yb
        cell_y_sumsq += cells.T @ np.square(yb)
        positive = cells > 1e-15
        physical_visits += positive.sum(axis=0)
        physician_codes = np.asarray(
            clusters[start:stop, 0], dtype=np.int64
        )
        facility_codes = np.asarray(
            clusters[start:stop, 1], dtype=np.int64
        )
        np.maximum.at(physician_max_weight, physician_codes, cells)
        np.logical_or.at(facility_seen, facility_codes, positive)
        outcome_sum += float(yb.sum())
        outcome_sumsq += float(yb @ yb)
        outcome_min = min(outcome_min, float(yb.min()))
        outcome_max = max(outcome_max, float(yb.max()))
        hashes = np.asarray(visit_hash[start:stop], dtype=np.uint64)
        visit_hash_xor = np.bitwise_xor(
            visit_hash_xor, np.bitwise_xor.reduce(hashes)
        )
        # Unsigned modular addition is intentional and documented.
        visit_hash_sum_mod64 = np.uint64(
            (
                int(visit_hash_sum_mod64)
                + int(hashes.sum(dtype=np.uint64))
            )
            & ((1 << 64) - 1)
        )
        fe_cluster_physician_mismatch += int(
            (
                np.asarray(fe_codes[start:stop, 0], dtype=np.uint64)
                != np.asarray(clusters[start:stop, 0], dtype=np.uint64)
            ).sum()
        )

    physician_positive = physician_max_weight > 1e-15
    physician_count = physician_positive.sum(axis=0)
    physician_mass = physician_max_weight.sum(axis=0)
    physician_sumsq = np.einsum(
        "ij,ij->j", physician_max_weight, physician_max_weight
    )
    facility_count = facility_seen.sum(axis=0)
    support_rows = []
    for index, cell_id in enumerate(manifest["cell_ids"]):
        effective_visits = (
            float(cell_sum[index] ** 2 / cell_sumsq[index])
            if cell_sumsq[index] > 0
            else 0.0
        )
        effective_physicians = (
            float(physician_mass[index] ** 2 / physician_sumsq[index])
            if physician_sumsq[index] > 0
            else 0.0
        )
        passes = (
            effective_visits >= SUPPORT_THRESHOLDS["minimum_effective_visits"]
            and effective_physicians
            >= SUPPORT_THRESHOLDS["minimum_effective_physicians"]
            and facility_count[index]
            >= SUPPORT_THRESHOLDS["minimum_facilities"]
            and physician_count[index]
            >= SUPPORT_THRESHOLDS["minimum_physician_clusters"]
            and facility_count[index]
            >= SUPPORT_THRESHOLDS["minimum_facility_clusters"]
        )
        limited = (
            effective_visits
            < SUPPORT_THRESHOLDS["limited_effective_visits"]
            or effective_physicians
            < SUPPORT_THRESHOLDS["limited_effective_physicians"]
            or facility_count[index]
            < SUPPORT_THRESHOLDS["limited_facilities"]
        )
        support_rows.append(
            {
                "family_id": args.family,
                "outcome": args.outcome,
                "cell_id": cell_id,
                "physical_visit_count": int(physical_visits[index]),
                "probability_weighted_visit_mass": float(cell_sum[index]),
                "sum_squared_visit_weights": float(cell_sumsq[index]),
                "kish_effective_visits": effective_visits,
                "unique_physicians": int(physician_count[index]),
                "probability_weighted_physician_mass": float(
                    physician_mass[index]
                ),
                "sum_squared_physician_weights": float(
                    physician_sumsq[index]
                ),
                "kish_effective_physicians": effective_physicians,
                "unique_facilities": int(facility_count[index]),
                "physician_clusters": int(physician_count[index]),
                "facility_clusters": int(facility_count[index]),
                "outcome_specific_support_status": (
                    "PASS" if passes else "NON_ESTIMABLE_SUPPORT"
                ),
                "limited_support_flag": bool(limited),
                "weighted_outcome_mean": (
                    float(cell_y_sum[index] / cell_sum[index])
                    if cell_sum[index] > 0
                    else math.nan
                ),
                "weighted_outcome_second_moment": (
                    float(cell_y_sumsq[index] / cell_sum[index])
                    if cell_sum[index] > 0
                    else math.nan
                ),
            }
        )
    support_frame = pd.DataFrame(support_rows)

    extension_path = (
        phase2
        / "documentation"
        / "Directional_Dyad_Analysis_Plan_Extension_FROZEN.json"
    )
    extension = load_json(extension_path)
    family_spec = extension["analysis_families"][args.family]
    cells_meta = list(family_spec["cells"])
    cell_lookup = {
        cell_id: index for index, cell_id in enumerate(manifest["cell_ids"])
    }
    if set(cell_lookup) != {item["cell_id"] for item in cells_meta}:
        raise SystemExit("Matrix cells do not match frozen extension")

    # Independently re-query exact source sample and cell-weight moments.
    duckdb_temp = args.scratch_root.resolve() / "duckdb"
    duckdb_temp.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(f"SET threads={args.threads}")
    con.execute(f"SET memory_limit='{args.memory_limit}'")
    con.execute(f"SET temp_directory='{qpath(duckdb_temp)}'")
    source_reconciliation = []
    offset = 0
    for part in manifest["partitions"]:
        rows = int(part["rows"])
        start, stop = offset, offset + rows
        yb = np.asarray(outcome[start:stop, 0], dtype=np.float64)
        matrix_mean = float(yb.mean()) if rows else None
        matrix_min = float(yb.min()) if rows else None
        matrix_max = float(yb.max()) if rows else None
        passed = (
            rows == stop - start
            and (
                rows == 0
                or (
                    math.isclose(
                        matrix_mean,
                        float(part["outcome_mean"]),
                        rel_tol=1e-11,
                        abs_tol=1e-9,
                    )
                    and math.isclose(
                        matrix_min,
                        float(part["outcome_min"]),
                        rel_tol=0,
                        abs_tol=1e-10,
                    )
                    and math.isclose(
                        matrix_max,
                        float(part["outcome_max"]),
                        rel_tol=0,
                        abs_tol=1e-10,
                    )
                )
            )
        )
        source_reconciliation.append(
            {
                "visit_year": part["visit_year"],
                "visit_quarter": part["visit_quarter"],
                "rows": rows,
                "matrix_outcome_mean": matrix_mean,
                "manifest_outcome_mean": part["outcome_mean"],
                "passed": passed,
            }
        )
        offset = stop
    expressions = source_cell_expressions(args.family, cells_meta)
    aggregates = ["count(*) AS n"]
    for alias, expression, _ in expressions:
        aggregates.extend(
            [
                f"sum({expression}) AS {alias}_sum",
                f"sum(({expression}) * ({expression})) AS {alias}_sumsq",
            ]
        )
    source_paths = [item["path"] for item in manifest["source_partitions"]]
    list_sql = "[" + ",".join(
        "'" + path.replace("\\", "/").replace("'", "''") + "'"
        for path in source_paths
    ) + "]"
    outcome_expression = manifest["outcome_expression"]
    source_values = con.execute(
        f"""
        SELECT {", ".join(aggregates)}
        FROM read_parquet({list_sql}, hive_partitioning=false)
        WHERE {manifest["eligibility_field"]}
          AND ({outcome_expression}) IS NOT NULL
          AND isfinite(CAST(({outcome_expression}) AS DOUBLE))
        """
    ).fetchone()
    source_cell_moment_errors = []
    if int(source_values[0]) != n:
        source_cell_moment_errors.append(
            f"source row count {source_values[0]} != matrix {n}"
        )
    cursor = 1
    for index, (_, _, cell_id) in enumerate(expressions):
        expected_sum = float(source_values[cursor])
        expected_sumsq = float(source_values[cursor + 1])
        cursor += 2
        if not math.isclose(
            expected_sum,
            float(cell_sum[index]),
            rel_tol=1e-11,
            abs_tol=1e-6,
        ):
            source_cell_moment_errors.append(f"{cell_id}: sum mismatch")
        if not math.isclose(
            expected_sumsq,
            float(cell_sumsq[index]),
            rel_tol=1e-11,
            abs_tol=1e-6,
        ):
            source_cell_moment_errors.append(f"{cell_id}: sumsq mismatch")
    con.close()

    engine = load_engine(phase2)
    scratch = args.scratch_root.resolve() / args.family / args.outcome
    scratch.mkdir(parents=True, exist_ok=True)
    checkpoint_binding = {
        "matrix_manifest_path": str(manifest_path.resolve()),
        "matrix_manifest_sha256": sha256_file(manifest_path),
        "matrix_files": {
            item["name"]: item["sha256"] for item in file_audit
        },
        "audit_script_sha256": sha256_file(Path(__file__).resolve()),
    }
    all_columns = list(range(k))
    design_names = [item["name"] for item in manifest["design_spec"]]
    cell_mean = cell_sum / n
    rank_audits = {}
    target_rows = []
    for model_id, fe_indices in (
        ("M2_DIRECTIONAL", [1, 2]),
        ("M3_WITHIN_PHYSICIAN", [0, 1, 2]),
    ):
        x_tilde, _, demeaning = engine.residualize(
            raw,
            outcome,
            fe_codes,
            all_columns,
            fe_indices,
            scratch / model_id,
            args.block_columns,
            args.tolerance,
            checkpoint_binding,
        )
        demeaning_policy_audit = audit_demeaning_provenance(
            scratch / model_id / "demeaning_state.json",
            demeaning,
            n_rows=n,
            n_columns=k,
            n_outcomes=1,
            block_columns=args.block_columns,
            checkpoint_binding=checkpoint_binding,
        )
        xtx, norm2 = crossproduct_only(x_tilde, args.row_chunk)
        rank, condition, projector, rank_tolerance = rank_and_projector(xtx)
        model_targets = []
        if model_id == "M2_DIRECTIONAL":
            for index, cell_id in enumerate(manifest["cell_ids"]):
                target = np.zeros(k, dtype=np.float64)
                target[:q] = -cell_mean
                target[index] += 1.0
                identified, error = target_identified(target, projector)
                model_targets.append(
                    {
                        "target_type": "adjusted_prediction",
                        "target_id": cell_id,
                        "identified": identified,
                        "rowspace_relative_error": error,
                    }
                )
        for contrast in family_spec["contrasts"]:
            target = contrast_vector(contrast, cell_lookup, k)
            identified, error = target_identified(target, projector)
            model_targets.append(
                {
                    "target_type": "planned_contrast",
                    "target_id": contrast["contrast_id"],
                    "contrast_family": contrast["contrast_family"],
                    "identified": identified,
                    "rowspace_relative_error": error,
                }
            )
        for item in model_targets:
            target_rows.append(
                {
                    "family_id": args.family,
                    "outcome": args.outcome,
                    "model_id": model_id,
                    **item,
                }
            )
        rank_audits[model_id] = {
            "n_rows": n,
            "n_columns": k,
            "rank": rank,
            "nullity": k - rank,
            "condition_number_positive_eigenspace": condition,
            "rank_tolerance": rank_tolerance,
            "zero_or_absorbed_column_count": int((norm2 <= 1e-12).sum()),
            "zero_or_absorbed_columns": [
                name
                for name, value in zip(design_names, norm2)
                if value <= 1e-12
            ],
            "demeaning": demeaning,
            "demeaning_policy_audit": demeaning_policy_audit,
            "targets_total": len(model_targets),
            "targets_identified": sum(
                bool(item["identified"]) for item in model_targets
            ),
        }
        del xtx, norm2, projector, x_tilde

    target_frame = pd.DataFrame(target_rows)
    m2_all_identified = bool(
        target_frame.loc[
            target_frame["model_id"].eq("M2_DIRECTIONAL"), "identified"
        ].all()
    )
    source_hash_checks = []
    for source in manifest["source_partitions"]:
        path = Path(source["path"])
        actual = sha256_file(path)
        source_hash_checks.append(
            {
                "visit_year": source["visit_year"],
                "visit_quarter": source["visit_quarter"],
                "path": str(path),
                "expected_sha256": source["sha256"],
                "actual_sha256": actual,
                "passed": actual == source["sha256"],
            }
        )

    qa_root = phase2 / "qa" / "directional_matrix_audits"
    qa_root.mkdir(parents=True, exist_ok=True)
    stem = f"{args.family}__{args.outcome}"
    support_path = qa_root / f"{stem}__outcome_support.csv"
    target_path = qa_root / f"{stem}__rank_targets.csv"
    support_frame.to_csv(support_path, index=False)
    target_frame.to_csv(target_path, index=False)
    failures = []
    if nonfinite_design_rows:
        failures.append("nonfinite_design")
    if nonfinite_outcome_rows:
        failures.append("nonfinite_outcome")
    if cell_sum_error_rows:
        failures.append("cell_sum")
    if bounds_error_rows:
        failures.append("cell_bounds")
    if fe_cluster_physician_mismatch:
        failures.append("physician_fe_cluster_mismatch")
    if not all(item["passed"] for item in source_reconciliation):
        failures.append("partition_reconciliation")
    if source_cell_moment_errors:
        failures.append("source_cell_moments")
    if not all(item["passed"] for item in source_hash_checks):
        failures.append("source_hash")
    if not m2_all_identified:
        failures.append("m2_target_identification")
    if not all(
        value["demeaning"]["converged"] for value in rank_audits.values()
    ):
        failures.append("demeaning_convergence")
    if not all(
        value["demeaning_policy_audit"]["status"] == "PASS"
        for value in rank_audits.values()
    ):
        failures.append("demeaning_policy_provenance")
    payload = {
        "audit_id": "independent_directional_matrix_audit_v1",
        "created_utc": now_utc(),
        "status": "PASS" if not failures else "FAIL",
        "family_id": args.family,
        "outcome": args.outcome,
        "matrix_manifest": {
            "path": str(manifest_path.resolve()),
            "sha256": sha256_file(manifest_path),
        },
        "live_binding_checks": live_binding_checks,
        "matrix_file_audit": file_audit,
        "source_partition_hash_checks": source_hash_checks,
        "source_partition_reconciliation": source_reconciliation,
        "source_cell_moment_errors": source_cell_moment_errors,
        "matrix_checks": {
            "n_rows": n,
            "n_columns": k,
            "n_cell_columns": q,
            "nonfinite_design_rows": nonfinite_design_rows,
            "nonfinite_outcome_rows": nonfinite_outcome_rows,
            "cell_sum_error_rows": cell_sum_error_rows,
            "cell_bounds_error_rows": bounds_error_rows,
            "physician_fe_cluster_mismatch": fe_cluster_physician_mismatch,
            "outcome_sum": outcome_sum,
            "outcome_sumsq": outcome_sumsq,
            "outcome_min": outcome_min,
            "outcome_max": outcome_max,
            "visit_hash_xor_uint64": int(visit_hash_xor),
            "visit_hash_sum_mod_uint64": int(visit_hash_sum_mod64),
        },
        "outcome_specific_support": {
            "path": str(support_path.resolve()),
            "sha256": sha256_file(support_path),
            "rows": len(support_frame),
            "cells_passing_support": int(
                support_frame["outcome_specific_support_status"]
                .eq("PASS")
                .sum()
            ),
        },
        "rank_and_identification": rank_audits,
        "rank_targets": {
            "path": str(target_path.resolve()),
            "sha256": sha256_file(target_path),
            "rows": len(target_frame),
            "m2_all_identified": m2_all_identified,
            "m3_identified_contrasts": int(
                target_frame.loc[
                    target_frame["model_id"].eq("M3_WITHIN_PHYSICIAN"),
                    "identified",
                ].sum()
            ),
        },
        "failures": failures,
        "coefficient_estimates_computed": False,
        "model_result_files_opened": False,
        "result_interpretation_authorized": False,
        "source_release_modified": False,
        "phase2_cohort_modified": False,
    }
    output_path = qa_root / f"{stem}.json"
    atomic_json(output_path, payload)
    print(json.dumps(payload, indent=2), flush=True)
    if payload["status"] != "PASS":
        raise SystemExit("Independent directional matrix audit failed")


if __name__ == "__main__":
    main()
