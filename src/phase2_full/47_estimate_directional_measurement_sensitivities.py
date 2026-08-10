#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/47_estimate_directional_measurement_sensitivities.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Run five-class directional physician-race measurement sensitivities.

This script is intentionally restricted to the two frozen primary outcomes and
the race and race-plus-gender directional families.  It consumes an audited
probability-weighted directional matrix before that matrix is compacted.

The primary AAMC-Florida posterior-mixture result remains in script 41.  This
script adds:

* AAMC-Florida hard maximum-posterior classifications at .50/.70/.80/.90.
* National-prior posterior-mixture results.
* National-prior hard classifications at .50/.70/.80/.90.
* Twenty physician-level categorical imputations under each prior, with each
  NPI assigned once per imputation and held constant over all visits.

All modes retain the joint factorial model, frozen contrasts, M2 and M3 fixed
effects, and two-way physician/facility CRV1 inference.  Values are written to
files but never printed to stdout.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import importlib.util
import json
import math
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import duckdb
import numpy as np
import pandas as pd
from scipy.stats import t as student_t


FAMILIES = ("race_dyads", "intersectional_dyads")
OUTCOMES = (
    "los_hours_primary_0_168",
    "total_charge_reported_real_2024",
)
RACES = ("White", "Black", "Hispanic", "Asian", "Other/multiracial")
THRESHOLDS = (0.50, 0.70, 0.80, 0.90)
MODEL_FE = {
    "M2_DIRECTIONAL": [1, 2],
    "M3_WITHIN_PHYSICIAN": [0, 1, 2],
}
MIN_SUPPORT = {
    "effective_visits": 1000.0,
    "effective_physicians": 30.0,
    "facilities": 20,
    "physician_clusters": 30,
    "facility_clusters": 20,
}
LIMITED_SUPPORT = {
    "effective_visits": 5000.0,
    "effective_physicians": 50.0,
    "facilities": 30,
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
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    os.replace(temporary, path)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def chunks(n: int, size: int) -> Iterable[tuple[int, int]]:
    for start in range(0, n, size):
        yield start, min(n, start + size)


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def stable_uniform(seed: int, prior: str, imputation: int, npi: str) -> float:
    payload = f"{seed}|{prior}|{imputation}|{npi}".encode("utf-8")
    value = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")
    return (value + 0.5) / 2**64


def categorical_assignments(
    npis_by_code: list[str],
    probabilities: np.ndarray,
    seed: int,
    prior: str,
    imputation: int,
) -> np.ndarray:
    uniforms = np.fromiter(
        (
            stable_uniform(seed, prior, imputation, npi)
            for npi in npis_by_code
        ),
        dtype=np.float64,
        count=len(npis_by_code),
    )
    cumulative = np.cumsum(probabilities, axis=1)
    cumulative[:, -1] = 1.0
    assignment = (uniforms[:, None] > cumulative).sum(axis=1).astype(
        np.uint8
    )
    if not np.isin(assignment, np.arange(len(RACES))).all():
        raise RuntimeError("Invalid categorical physician-race assignment")
    return assignment


class CombinedMatrix:
    """Read-only virtual matrix joining sensitivity cells to base covariates."""

    def __init__(
        self,
        cells: np.ndarray,
        base: np.ndarray,
        base_covariate_start: int,
    ) -> None:
        self.cells = cells
        self.base = base
        self.start = base_covariate_start
        self.shape = (
            base.shape[0],
            cells.shape[1] + base.shape[1] - base_covariate_start,
        )

    def __getitem__(self, key: Any) -> np.ndarray:
        if not isinstance(key, tuple) or len(key) != 2:
            raise IndexError("CombinedMatrix requires two-dimensional indexing")
        rows, columns = key
        if columns != slice(None):
            raise IndexError("CombinedMatrix supports complete column slices only")
        return np.column_stack(
            (self.cells[rows, :], self.base[rows, self.start :])
        )


@dataclass
class ProbabilityLookup:
    npis_by_code: list[str]
    primary: np.ndarray
    national: np.ndarray
    source_path: Path
    source_sha256: str
    encoder_path: Path
    encoder_sha256: str


def probability_lookup(
    phase2: Path, encoder_path: Path
) -> ProbabilityLookup:
    encoders = load_json(encoder_path)
    physician = encoders["physician"]
    code_count = max(int(value) for value in physician.values()) + 1
    npis_by_code = [""] * code_count
    for npi, code in physician.items():
        code = int(code)
        if npis_by_code[code]:
            raise RuntimeError("Duplicate physician encoder code")
        npis_by_code[code] = str(npi)
    if any(not value for value in npis_by_code):
        raise RuntimeError("Physician encoder is not dense")
    code_frame = pd.DataFrame(
        {"npi": npis_by_code, "__code": np.arange(code_count, dtype=np.int64)}
    )
    race_path = phase2 / "analysis_data" / "dimensions" / "provider_race_proxy_v2.parquet"
    con = duckdb.connect()
    con.register("requested_npi", code_frame)
    lookup = con.execute(
        f"""
        SELECT
            r.__code,
            p.npi,
            p.fl_physician_prob_white,
            p.fl_physician_prob_black,
            p.fl_physician_prob_hispanic,
            p.fl_physician_prob_asian,
            p.fl_physician_prob_other,
            p.population_prob_white,
            p.population_prob_black,
            p.population_prob_hispanic,
            p.population_prob_asian,
            p.population_prob_other
        FROM requested_npi r
        LEFT JOIN read_parquet('{race_path.as_posix()}') p
          ON r.npi = p.npi
        ORDER BY r.__code
        """
    ).fetch_df()
    con.close()
    if (
        len(lookup) != code_count
        or lookup["npi"].isna().any()
        or not np.array_equal(
            lookup["__code"].to_numpy(dtype=np.int64),
            np.arange(code_count, dtype=np.int64),
        )
    ):
        raise RuntimeError("Provider race lookup did not cover every encoded NPI")
    primary = lookup.iloc[:, 2:7].to_numpy(dtype=np.float64)
    national = lookup.iloc[:, 7:12].to_numpy(dtype=np.float64)
    for name, values in (("primary", primary), ("national", national)):
        if (
            not np.isfinite(values).all()
            or np.any(values < 0)
            or np.any(values > 1)
            or not np.allclose(values.sum(axis=1), 1.0, atol=1e-10, rtol=0)
        ):
            raise RuntimeError(f"Invalid {name} physician probability lookup")
    return ProbabilityLookup(
        npis_by_code=npis_by_code,
        primary=primary,
        national=national,
        source_path=race_path.resolve(),
        source_sha256=sha256_file(race_path),
        encoder_path=encoder_path.resolve(),
        encoder_sha256=sha256_file(encoder_path),
    )


def context_map(
    cells: list[dict[str, Any]],
    family: str,
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    contexts: list[str] = []
    cell_context = []
    cell_race = []
    for cell in cells:
        if family == "race_dyads":
            context = f"patient={cell['patient_group']}"
            race = cell["physician_group"]
        else:
            context = (
                f"physician_gender={cell['physician_gender']}|"
                f"patient_race={cell['patient_race']}|"
                f"patient_sex={cell['patient_sex']}"
            )
            race = cell["physician_race"]
        if context not in contexts:
            contexts.append(context)
        cell_context.append(contexts.index(context))
        cell_race.append(RACES.index(race))
    lookup = np.full((len(contexts), len(RACES)), -1, dtype=np.int64)
    for index, (context, race) in enumerate(zip(cell_context, cell_race)):
        if lookup[context, race] != -1:
            raise RuntimeError("Duplicate context/race directional cell")
        lookup[context, race] = index
    if np.any(lookup < 0):
        raise RuntimeError("Incomplete five-race directional context")
    return (
        np.asarray(cell_context, dtype=np.int64),
        lookup,
        contexts,
    )


def derive_context(
    base_cells: np.ndarray,
    cell_context: np.ndarray,
    n_contexts: int,
) -> np.ndarray:
    mass = np.zeros((base_cells.shape[0], n_contexts), dtype=np.float64)
    for cell_index, context_index in enumerate(cell_context):
        mass[:, context_index] += base_cells[:, cell_index]
    context = np.argmax(mass, axis=1)
    selected = mass[np.arange(len(context)), context]
    if (
        not np.allclose(selected, 1.0, atol=1e-9, rtol=0)
        or not np.allclose(mass.sum(axis=1), 1.0, atol=1e-9, rtol=0)
    ):
        raise RuntimeError("Unable to recover directional row context")
    return context.astype(np.int64)


class SupportAccumulator:
    def __init__(self, physician_count: int, facility_count: int, q: int):
        self.q = q
        self.mass = np.zeros(q, dtype=np.float64)
        self.mass2 = np.zeros(q, dtype=np.float64)
        self.outcome_mass = np.zeros(q, dtype=np.float64)
        self.physician_mass = np.zeros(
            (physician_count, q), dtype=np.float64
        )
        self.facility_mass = np.zeros((facility_count, q), dtype=np.float64)

    def add(
        self,
        cell_indices: np.ndarray,
        weights: np.ndarray,
        physician_codes: np.ndarray,
        facility_codes: np.ndarray,
        outcomes: np.ndarray,
    ) -> None:
        q = self.q
        indices = cell_indices.reshape(-1)
        values = weights.reshape(-1)
        repeated_outcomes = np.repeat(outcomes, cell_indices.shape[1])
        repeated_physicians = np.repeat(
            physician_codes, cell_indices.shape[1]
        )
        repeated_facilities = np.repeat(
            facility_codes, cell_indices.shape[1]
        )
        self.mass += np.bincount(indices, weights=values, minlength=q)
        self.mass2 += np.bincount(
            indices, weights=np.square(values), minlength=q
        )
        self.outcome_mass += np.bincount(
            indices,
            weights=values * repeated_outcomes,
            minlength=q,
        )
        np.add.at(
            self.physician_mass.reshape(-1),
            repeated_physicians * q + indices,
            values,
        )
        np.add.at(
            self.facility_mass.reshape(-1),
            repeated_facilities * q + indices,
            values,
        )

    def frame(self, cell_ids: list[str]) -> pd.DataFrame:
        with np.errstate(divide="ignore", invalid="ignore"):
            effective_visits = np.divide(
                np.square(self.mass),
                self.mass2,
                out=np.zeros_like(self.mass),
                where=self.mass2 > 0,
            )
            physician_denom = np.square(self.physician_mass).sum(axis=0)
            effective_physicians = np.divide(
                np.square(self.mass),
                physician_denom,
                out=np.zeros_like(self.mass),
                where=physician_denom > 0,
            )
            weighted_mean = np.divide(
                self.outcome_mass,
                self.mass,
                out=np.full_like(self.mass, np.nan),
                where=self.mass > 0,
            )
        physicians = (self.physician_mass > 0).sum(axis=0)
        facilities = (self.facility_mass > 0).sum(axis=0)
        rows = []
        for index, cell_id in enumerate(cell_ids):
            passed = (
                effective_visits[index] >= MIN_SUPPORT["effective_visits"]
                and effective_physicians[index]
                >= MIN_SUPPORT["effective_physicians"]
                and facilities[index] >= MIN_SUPPORT["facilities"]
                and physicians[index] >= MIN_SUPPORT["physician_clusters"]
                and facilities[index] >= MIN_SUPPORT["facility_clusters"]
            )
            limited = (
                effective_visits[index] < LIMITED_SUPPORT["effective_visits"]
                or effective_physicians[index]
                < LIMITED_SUPPORT["effective_physicians"]
                or facilities[index] < LIMITED_SUPPORT["facilities"]
            )
            rows.append(
                {
                    "cell_id": cell_id,
                    "weighted_visit_mass": self.mass[index],
                    "kish_effective_visits": effective_visits[index],
                    "effective_physicians": effective_physicians[index],
                    "distinct_physicians_positive_mass": int(
                        physicians[index]
                    ),
                    "distinct_facilities_positive_mass": int(
                        facilities[index]
                    ),
                    "weighted_outcome_mean": weighted_mean[index],
                    "support_pass": bool(passed),
                    "limited_support_flag": bool(limited),
                    "support_status": (
                        "PASS"
                        if passed and not limited
                        else (
                            "LIMITED_SUPPORT"
                            if passed
                            else "NON_ESTIMABLE_SUPPORT"
                        )
                    ),
                }
            )
        return pd.DataFrame(rows)


def support_status(
    support: pd.DataFrame, cell_ids: list[str]
) -> tuple[bool, bool, str]:
    block = support.set_index("cell_id").loc[cell_ids]
    passed = bool(block["support_pass"].all())
    limited = bool(block["limited_support_flag"].any())
    return (
        passed,
        limited,
        (
            "NON_ESTIMABLE_SUPPORT"
            if not passed
            else ("LIMITED_SUPPORT" if limited else "PASS")
        ),
    )


def cell_indices_and_weights(
    context: np.ndarray,
    physician_codes: np.ndarray,
    context_race_to_cell: np.ndarray,
    probabilities: np.ndarray | None,
    assignment: np.ndarray | None,
) -> tuple[np.ndarray, np.ndarray]:
    if (probabilities is None) == (assignment is None):
        raise ValueError("Provide exactly one probability or assignment source")
    if probabilities is not None:
        indices = context_race_to_cell[
            context[:, None], np.arange(len(RACES))[None, :]
        ]
        weights = probabilities[physician_codes, :]
    else:
        assigned = assignment[physician_codes].astype(np.int64)
        indices = context_race_to_cell[context, assigned][:, None]
        weights = np.ones((len(context), 1), dtype=np.float64)
    return indices.astype(np.int64), weights.astype(np.float64)


def write_cells_with_support(
    path: Path,
    raw: np.memmap,
    outcome: np.memmap,
    clusters: np.memmap,
    cell_ids: list[str],
    cell_context: np.ndarray,
    context_race_to_cell: np.ndarray,
    probabilities: np.ndarray | None,
    assignment: np.ndarray | None,
    row_chunk: int,
) -> tuple[np.memmap, pd.DataFrame]:
    n, q = raw.shape[0], len(cell_ids)
    cells = np.memmap(path, dtype=np.float64, mode="w+", shape=(n, q))
    accumulator = SupportAccumulator(
        int(np.max(clusters[:, 0])) + 1,
        int(np.max(clusters[:, 1])) + 1,
        q,
    )
    for start, stop in chunks(n, row_chunk):
        context = derive_context(
            np.asarray(raw[start:stop, :q], dtype=np.float64),
            cell_context,
            len(context_race_to_cell),
        )
        physician = np.asarray(clusters[start:stop, 0], dtype=np.int64)
        facility = np.asarray(clusters[start:stop, 1], dtype=np.int64)
        indices, weights = cell_indices_and_weights(
            context,
            physician,
            context_race_to_cell,
            probabilities,
            assignment,
        )
        block = np.zeros((stop - start, q), dtype=np.float64)
        block[np.arange(stop - start)[:, None], indices] = weights
        if not np.allclose(block.sum(axis=1), 1.0, atol=1e-10, rtol=0):
            raise RuntimeError("Sensitivity cell rows do not sum to one")
        cells[start:stop, :] = block
        accumulator.add(
            indices,
            weights,
            physician,
            facility,
            np.asarray(outcome[start:stop, 0], dtype=np.float64),
        )
    cells.flush()
    return cells, accumulator.frame(cell_ids)


def build_hard_subset(
    folder: Path,
    raw: np.memmap,
    outcome: np.memmap,
    fe: np.memmap,
    clusters: np.memmap,
    visit_hashes: np.memmap,
    cell_ids: list[str],
    cell_context: np.ndarray,
    context_race_to_cell: np.ndarray,
    probabilities: np.ndarray,
    threshold: float,
    row_chunk: int,
) -> tuple[np.memmap, np.memmap, np.memmap, np.memmap, pd.DataFrame]:
    max_probability = probabilities.max(axis=1)
    assignments = probabilities.argmax(axis=1).astype(np.uint8)
    n_selected = 0
    for start, stop in chunks(raw.shape[0], row_chunk):
        physician = np.asarray(clusters[start:stop, 0], dtype=np.int64)
        n_selected += int((max_probability[physician] >= threshold).sum())
    if n_selected <= 0:
        raise RuntimeError("Hard-threshold sensitivity selected zero rows")
    folder.mkdir(parents=True, exist_ok=True)
    k, q = raw.shape[1], len(cell_ids)
    subset_raw = np.memmap(
        folder / "raw_design.float64.mmap",
        dtype=np.float64,
        mode="w+",
        shape=(n_selected, k),
    )
    subset_outcome = np.memmap(
        folder / "outcome.float64.mmap",
        dtype=np.float64,
        mode="w+",
        shape=(n_selected, 1),
    )
    subset_fe = np.memmap(
        folder / "fe_codes.uint64.mmap",
        dtype=np.uint64,
        mode="w+",
        shape=(n_selected, 3),
    )
    subset_clusters = np.memmap(
        folder / "cluster_codes.uint64.mmap",
        dtype=np.uint64,
        mode="w+",
        shape=(n_selected, 3),
    )
    subset_hash = np.memmap(
        folder / "visit_hashes.uint64.mmap",
        dtype=np.uint64,
        mode="w+",
        shape=(n_selected,),
    )
    accumulator = SupportAccumulator(
        int(np.max(clusters[:, 0])) + 1,
        int(np.max(clusters[:, 1])) + 1,
        q,
    )
    offset = 0
    for start, stop in chunks(raw.shape[0], row_chunk):
        physician_all = np.asarray(
            clusters[start:stop, 0], dtype=np.int64
        )
        selected = max_probability[physician_all] >= threshold
        if not selected.any():
            continue
        count = int(selected.sum())
        target = slice(offset, offset + count)
        raw_block = np.asarray(raw[start:stop, :], dtype=np.float64)[selected]
        context = derive_context(
            raw_block[:, :q],
            cell_context,
            len(context_race_to_cell),
        )
        physician = physician_all[selected]
        facility = np.asarray(
            clusters[start:stop, 1], dtype=np.int64
        )[selected]
        indices, weights = cell_indices_and_weights(
            context,
            physician,
            context_race_to_cell,
            None,
            assignments,
        )
        raw_block[:, :q] = 0.0
        raw_block[np.arange(count), indices[:, 0]] = 1.0
        subset_raw[target, :] = raw_block
        subset_outcome[target, :] = outcome[start:stop, :][selected]
        subset_fe[target, :] = fe[start:stop, :][selected]
        subset_clusters[target, :] = clusters[start:stop, :][selected]
        subset_hash[target] = visit_hashes[start:stop][selected]
        accumulator.add(
            indices,
            weights,
            physician,
            facility,
            np.asarray(subset_outcome[target, 0], dtype=np.float64),
        )
        offset += count
    if offset != n_selected:
        raise RuntimeError("Hard subset row-count mismatch")
    for item in (
        subset_raw,
        subset_outcome,
        subset_fe,
        subset_clusters,
        subset_hash,
    ):
        item.flush()
    return (
        subset_raw,
        subset_outcome,
        subset_fe,
        subset_clusters,
        accumulator.frame(cell_ids),
    )


def fit_targets(
    estimator: Any,
    fit: dict[str, Any],
    model_id: str,
    cell_ids: list[str],
    contrasts: list[dict[str, Any]],
    support: pd.DataFrame,
    cell_mean: np.ndarray,
    outcome_mean: float,
    measurement_id: str,
    family: str,
    outcome_name: str,
    imputation: int | None,
) -> list[dict[str, Any]]:
    q = len(cell_ids)
    k = len(fit["beta"])
    lookup = {value: index for index, value in enumerate(cell_ids)}
    df = int(fit["covariance_meta"]["minimum_cluster_df"])
    rows: list[dict[str, Any]] = []
    if model_id == "M2_DIRECTIONAL":
        for index, cell_id in enumerate(cell_ids):
            target = np.zeros(k, dtype=np.float64)
            target[:q] = -cell_mean
            target[index] += 1.0
            inference = estimator.infer_target(
                target,
                fit["beta"],
                fit["covariance"],
                fit["projector"],
                df,
                outcome_mean,
            )
            passed, limited, status = support_status(support, [cell_id])
            rows.append(
                {
                    "family_id": family,
                    "outcome": outcome_name,
                    "measurement_specification": measurement_id,
                    "imputation": imputation,
                    "model_id": model_id,
                    "target_type": "adjusted_prediction",
                    "target_id": cell_id,
                    "contrast_family": None,
                    **inference,
                    "support_pass": passed,
                    "limited_support_flag": limited,
                    "estimability_status": (
                        "NON_ESTIMABLE_IDENTIFICATION"
                        if not inference["identified"]
                        else (
                            "NON_ESTIMABLE_VARIANCE"
                            if not inference["variance_valid"]
                            else status
                        )
                    ),
                }
            )
    for contrast in contrasts:
        target = estimator.contrast_vector(contrast, lookup, k)
        inference = estimator.infer_target(
            target,
            fit["beta"],
            fit["covariance"],
            fit["projector"],
            df,
        )
        involved = [
            item["cell_id"]
            for item in contrast["linear_combination"]
            if float(item["weight"]) != 0
        ]
        passed, limited, status = support_status(support, involved)
        rows.append(
            {
                "family_id": family,
                "outcome": outcome_name,
                "measurement_specification": measurement_id,
                "imputation": imputation,
                "model_id": model_id,
                "target_type": "planned_contrast",
                "target_id": contrast["contrast_id"],
                "contrast_family": contrast["contrast_family"],
                **inference,
                "support_pass": passed,
                "limited_support_flag": limited,
                "estimability_status": (
                    "NON_ESTIMABLE_IDENTIFICATION"
                    if not inference["identified"]
                    else (
                        "NON_ESTIMABLE_VARIANCE"
                        if not inference["variance_valid"]
                        else status
                    )
                ),
            }
        )
    return rows


def save_fit(
    path: Path,
    fit: dict[str, Any],
    cell_mean: np.ndarray,
    outcome_mean: float,
) -> None:
    np.savez_compressed(
        path,
        beta=fit["beta"],
        covariance=fit["covariance"],
        projector=fit["projector"],
        cell_mean=cell_mean,
        outcome_mean=np.array([outcome_mean]),
        cluster_df=np.array(
            [fit["covariance_meta"]["minimum_cluster_df"]], dtype=np.int64
        ),
    )


def pool_mi(frame: pd.DataFrame, imputations: int) -> pd.DataFrame:
    rows = []
    keys = [
        "family_id",
        "outcome",
        "measurement_specification",
        "model_id",
        "target_type",
        "target_id",
        "contrast_family",
    ]
    for key, block in frame.groupby(keys, dropna=False):
        if (
            len(block) != imputations
            or block["imputation"].nunique() != imputations
            or not block["identified"].astype(bool).all()
            or not block["variance_valid"].astype(bool).all()
        ):
            rows.append(
                {
                    **dict(zip(keys, key)),
                    "imputations_expected": imputations,
                    "imputations_completed": len(block),
                    "estimate": math.nan,
                    "variance": math.nan,
                    "standard_error": math.nan,
                    "ci95_low": math.nan,
                    "ci95_high": math.nan,
                    "p_value_raw": math.nan,
                    "rubin_degrees_freedom": math.nan,
                    "within_imputation_variance": math.nan,
                    "between_imputation_variance": math.nan,
                    "estimability_status": "NON_ESTIMABLE_MI_COMPONENT",
                }
            )
            continue
        estimates = block["estimate"].to_numpy(dtype=np.float64)
        variances = block["variance"].to_numpy(dtype=np.float64)
        m = len(block)
        estimate = float(estimates.mean())
        within = float(variances.mean())
        between = float(estimates.var(ddof=1))
        total = within + (1.0 + 1.0 / m) * between
        se = math.sqrt(total) if total >= 0 else math.nan
        if between > 0 and within >= 0:
            df = (m - 1) * (
                1 + within / ((1 + 1 / m) * between)
            ) ** 2
        else:
            df = math.inf
        critical = (
            float(student_t.ppf(0.975, df))
            if math.isfinite(df)
            else 1.959963984540054
        )
        statistic = estimate / se if se > 0 else math.nan
        p_value = (
            float(
                2
                * student_t.sf(
                    abs(statistic), df if math.isfinite(df) else 1e12
                )
            )
            if math.isfinite(statistic)
            else math.nan
        )
        support_pass = bool(block["support_pass"].astype(bool).all())
        limited = bool(block["limited_support_flag"].astype(bool).any())
        rows.append(
            {
                **dict(zip(keys, key)),
                "imputations_expected": imputations,
                "imputations_completed": m,
                "estimate": estimate,
                "variance": total,
                "standard_error": se,
                "ci95_low": estimate - critical * se,
                "ci95_high": estimate + critical * se,
                "p_value_raw": p_value,
                "rubin_degrees_freedom": df,
                "within_imputation_variance": within,
                "between_imputation_variance": between,
                "support_pass_all_imputations": support_pass,
                "limited_support_any_imputation": limited,
                "estimability_status": (
                    "NON_ESTIMABLE_SUPPORT"
                    if not support_pass
                    else ("LIMITED_SUPPORT" if limited else "PASS")
                ),
            }
        )
    return pd.DataFrame(rows)


def verified_complete(path: Path, binding: dict[str, Any]) -> bool:
    if not path.is_file():
        return False
    payload = load_json(path)
    if payload.get("status") != "PASS":
        return False
    if payload.get("binding") != binding:
        return False
    for item in payload.get("files", []):
        file_path = Path(item["path"])
        if (
            not file_path.is_file()
            or file_path.stat().st_size != int(item["bytes"])
            or sha256_file(file_path) != item["sha256"]
        ):
            return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    parser.add_argument("--matrix-root", required=True, type=Path)
    parser.add_argument("--scratch-root", required=True, type=Path)
    parser.add_argument("--results-root", required=True, type=Path)
    parser.add_argument("--family", required=True, choices=FAMILIES)
    parser.add_argument("--outcome", required=True, choices=OUTCOMES)
    parser.add_argument("--imputations", type=int, default=20)
    parser.add_argument("--seed", type=int, default=20260726)
    parser.add_argument("--row-chunk", type=int, default=100_000)
    parser.add_argument("--block-columns", type=int, default=4)
    parser.add_argument("--tolerance", type=float, default=1e-8)
    args = parser.parse_args()
    if args.imputations != 20:
        raise SystemExit("Frozen directional MI count is exactly 20")

    phase2 = args.phase2.resolve()
    matrix_dir = (
        args.matrix_root.resolve() / args.family / args.outcome
    )
    main_scratch = (
        args.scratch_root.resolve() / args.family / args.outcome
    )
    output = (
        args.results_root.resolve() / args.family / args.outcome
    )
    output.mkdir(parents=True, exist_ok=True)
    variant_scratch = (
        args.scratch_root.resolve()
        / "measurement_sensitivities"
        / args.family
        / args.outcome
    )
    variant_scratch.mkdir(parents=True, exist_ok=True)

    execution_path = (
        phase2 / "documentation" / "Directional_Dyad_Execution_Code_FROZEN.json"
    )
    execution = load_json(execution_path)
    if execution.get("status") != "FROZEN_ESTIMATE_BLIND_PASS":
        raise SystemExit("Directional execution code gate is not frozen PASS")
    for item in execution["code_inventory"]:
        live = phase2 / item["path"]
        if not live.is_file() or sha256_file(live) != item["sha256"]:
            raise SystemExit(f"Directional execution code drift: {live}")
    matrix_manifest_path = matrix_dir / "matrix_manifest.json"
    matrix_audit_path = (
        phase2
        / "qa"
        / "directional_matrix_audits"
        / f"{args.family}__{args.outcome}.json"
    )
    result_audit_path = (
        phase2
        / "qa"
        / "directional_result_audits"
        / f"{args.family}__{args.outcome}.json"
    )
    for required in (
        matrix_manifest_path,
        matrix_audit_path,
        result_audit_path,
    ):
        if not required.is_file():
            raise SystemExit(f"Required audited directional artifact missing: {required}")
    matrix_manifest = load_json(matrix_manifest_path)
    matrix_audit = load_json(matrix_audit_path)
    result_audit = load_json(result_audit_path)
    if (
        matrix_manifest.get("status") != "PASS"
        or matrix_audit.get("status") != "PASS"
        or result_audit.get("status") != "PASS"
    ):
        raise SystemExit("Primary directional matrix/result audit is not PASS")

    extension_path = (
        phase2
        / "documentation"
        / "Directional_Dyad_Analysis_Plan_Extension_FROZEN.json"
    )
    extension = load_json(extension_path)
    family_spec = extension["analysis_families"][args.family]
    cells_spec = list(family_spec["cells"])
    contrasts = list(family_spec["contrasts"])
    cell_ids = list(matrix_manifest["cell_ids"])
    if cell_ids != [item["cell_id"] for item in cells_spec]:
        raise SystemExit("Directional cell order changed")
    q = len(cell_ids)
    n = int(matrix_manifest["n_rows"])
    k = int(matrix_manifest["n_design_columns"])
    cell_context, context_race_to_cell, contexts = context_map(
        cells_spec, args.family
    )
    if context_race_to_cell.size != q:
        raise SystemExit("Directional sensitivity context is incomplete")

    matrix_files = {
        item["name"]: item for item in matrix_manifest["matrix_files"]
    }
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
    fe = np.memmap(
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
    visit_hashes = np.memmap(
        matrix_dir / "visit_hashes.uint64.mmap",
        dtype=np.uint64,
        mode="r",
        shape=(n,),
    )
    lookup = probability_lookup(
        phase2, matrix_dir / "category_encoders.json"
    )
    estimator = load_module(
        phase2 / "scripts" / "41_estimate_directional_models.py",
        "directional_estimator_for_measurement_sensitivity",
    )
    engine = load_module(
        phase2 / "scripts" / "08_estimate_primary_models.py",
        "directional_demeaning_engine_for_measurement_sensitivity",
    )
    base_model_arrays = {}
    for model_id in MODEL_FE:
        folder = main_scratch / model_id
        state = load_json(folder / "demeaning_state.json")
        if (
            len(state.get("completed_local_columns", [])) != k
            or state.get("outcomes_completed") is not True
            or not all(state.get("convergence", {}).values())
        ):
            raise SystemExit(f"Base directional demeaning incomplete: {model_id}")
        base_model_arrays[model_id] = (
            np.memmap(
                folder / "demeaned_design.float64.mmap",
                dtype=np.float64,
                mode="r",
                shape=(n, k),
            ),
            np.memmap(
                folder / "demeaned_outcomes.float64.mmap",
                dtype=np.float64,
                mode="r",
                shape=(n, 1),
            ),
        )

    binding = {
        "family": args.family,
        "outcome": args.outcome,
        "matrix_manifest_sha256": sha256_file(matrix_manifest_path),
        "matrix_audit_sha256": sha256_file(matrix_audit_path),
        "primary_result_audit_sha256": sha256_file(result_audit_path),
        "execution_manifest_sha256": sha256_file(execution_path),
        "provider_race_proxy_path": str(lookup.source_path),
        "provider_race_proxy_sha256": lookup.source_sha256,
        "encoder_path": str(lookup.encoder_path),
        "encoder_sha256": lookup.encoder_sha256,
        "imputations": args.imputations,
        "seed": args.seed,
        "thresholds": list(THRESHOLDS),
    }
    completion_path = output / "measurement_sensitivity_manifest.json"
    if verified_complete(completion_path, binding):
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "family": args.family,
                    "outcome": args.outcome,
                    "reused": True,
                    "result_values_emitted": False,
                },
                indent=2,
            )
        )
        return
    if completion_path.exists():
        raise SystemExit("Stale measurement-sensitivity completion exists")

    direct_results: list[pd.DataFrame] = []
    mi_results: list[pd.DataFrame] = []
    support_frames: list[pd.DataFrame] = []
    fit_inventory: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    outcome_mean_full = float(np.asarray(outcome[:, 0]).mean())

    def fit_full_cells(
        measurement_id: str,
        cells_path: Path,
        support: pd.DataFrame,
        imputation: int | None,
    ) -> pd.DataFrame:
        sensitivity_cells = np.memmap(
            cells_path,
            dtype=np.float64,
            mode="r",
            shape=(n, q),
        )
        cell_mean = (
            support.set_index("cell_id")
            .loc[cell_ids, "weighted_visit_mass"]
            .to_numpy(dtype=np.float64)
            / n
        )
        rows = []
        mode_key = (
            measurement_id
            if imputation is None
            else f"{measurement_id}_{imputation:02d}"
        )
        mode_scratch = variant_scratch / mode_key
        for model_id, fe_indices in MODEL_FE.items():
            x_cells, _, demeaning = engine.residualize(
                sensitivity_cells,
                outcome,
                fe,
                list(range(q)),
                fe_indices,
                mode_scratch / model_id,
                args.block_columns,
                args.tolerance,
                {
                    **binding,
                    "measurement_id": measurement_id,
                    "imputation": imputation,
                    "cells_bytes": cells_path.stat().st_size,
                },
            )
            base_x, base_y = base_model_arrays[model_id]
            combined = CombinedMatrix(x_cells, base_x, q)
            fit = estimator.fit_model(
                model_id,
                combined,
                base_y,
                clusters,
                args.row_chunk,
            )
            rows.extend(
                fit_targets(
                    estimator,
                    fit,
                    model_id,
                    cell_ids,
                    contrasts,
                    support,
                    cell_mean,
                    outcome_mean_full,
                    measurement_id,
                    args.family,
                    args.outcome,
                    imputation,
                )
            )
            fit_path = output / f"{mode_key}__{model_id}__fit.npz"
            save_fit(fit_path, fit, cell_mean, outcome_mean_full)
            fit_inventory.append(
                {
                    "measurement_specification": measurement_id,
                    "imputation": imputation,
                    "model_id": model_id,
                    "path": str(fit_path.resolve()),
                    "bytes": fit_path.stat().st_size,
                    "sha256": sha256_file(fit_path),
                }
            )
            diagnostics.append(
                {
                    "measurement_specification": measurement_id,
                    "imputation": imputation,
                    "model_id": model_id,
                    "n": n,
                    "rank": fit["rank"],
                    "condition_number": fit["condition_number"],
                    "cluster_counts": json.dumps(
                        fit["covariance_meta"]["cluster_counts"],
                        sort_keys=True,
                    ),
                    "demeaning_converged": demeaning["converged"],
                    "finite_beta": bool(np.isfinite(fit["beta"]).all()),
                    "finite_covariance": bool(
                        np.isfinite(fit["covariance"]).all()
                    ),
                }
            )
            del x_cells, fit, combined
            gc.collect()
        return pd.DataFrame(rows)

    # Alternative-prior posterior mixture.
    national_folder = variant_scratch / "national_probability_weighted"
    national_folder.mkdir(parents=True, exist_ok=True)
    national_cells_path = national_folder / "cells.float64.mmap"
    national_cells, national_support = write_cells_with_support(
        national_cells_path,
        raw,
        outcome,
        clusters,
        cell_ids,
        cell_context,
        context_race_to_cell,
        lookup.national,
        None,
        args.row_chunk,
    )
    del national_cells
    national_support.insert(
        0, "measurement_specification", "national_probability_weighted"
    )
    support_frames.append(national_support)
    direct_results.append(
        fit_full_cells(
            "national_probability_weighted",
            national_cells_path,
            national_support,
            None,
        )
    )
    shutil.rmtree(national_folder)

    # Hard posterior classifications under both priors.
    for prior_name, probabilities in (
        ("aamc_fl", lookup.primary),
        ("national", lookup.national),
    ):
        for threshold in THRESHOLDS:
            measurement_id = (
                f"{prior_name}_hard_max_t{int(threshold * 100):02d}"
            )
            folder = variant_scratch / measurement_id
            (
                subset_raw,
                subset_outcome,
                subset_fe,
                subset_clusters,
                hard_support,
            ) = build_hard_subset(
                folder,
                raw,
                outcome,
                fe,
                clusters,
                visit_hashes,
                cell_ids,
                cell_context,
                context_race_to_cell,
                probabilities,
                threshold,
                args.row_chunk,
            )
            n_subset = subset_raw.shape[0]
            hard_support.insert(0, "measurement_specification", measurement_id)
            support_frames.append(hard_support)
            cell_mean = (
                hard_support.set_index("cell_id")
                .loc[cell_ids, "weighted_visit_mass"]
                .to_numpy(dtype=np.float64)
                / n_subset
            )
            outcome_mean = float(np.asarray(subset_outcome[:, 0]).mean())
            rows = []
            for model_id, fe_indices in MODEL_FE.items():
                x_tilde, y_tilde, demeaning = engine.residualize(
                    subset_raw,
                    subset_outcome,
                    subset_fe,
                    list(range(k)),
                    fe_indices,
                    folder / model_id,
                    args.block_columns,
                    args.tolerance,
                    {
                        **binding,
                        "measurement_id": measurement_id,
                        "threshold": threshold,
                        "selected_visit_hash_sum_mod64": int(
                            np.asarray(
                                np.memmap(
                                    folder / "visit_hashes.uint64.mmap",
                                    dtype=np.uint64,
                                    mode="r",
                                    shape=(n_subset,),
                                )
                            ).sum(dtype=np.uint64)
                        ),
                    },
                )
                fit = estimator.fit_model(
                    model_id,
                    x_tilde,
                    y_tilde,
                    subset_clusters,
                    args.row_chunk,
                )
                rows.extend(
                    fit_targets(
                        estimator,
                        fit,
                        model_id,
                        cell_ids,
                        contrasts,
                        hard_support,
                        cell_mean,
                        outcome_mean,
                        measurement_id,
                        args.family,
                        args.outcome,
                        None,
                    )
                )
                fit_path = output / f"{measurement_id}__{model_id}__fit.npz"
                save_fit(fit_path, fit, cell_mean, outcome_mean)
                fit_inventory.append(
                    {
                        "measurement_specification": measurement_id,
                        "imputation": None,
                        "model_id": model_id,
                        "path": str(fit_path.resolve()),
                        "bytes": fit_path.stat().st_size,
                        "sha256": sha256_file(fit_path),
                    }
                )
                diagnostics.append(
                    {
                        "measurement_specification": measurement_id,
                        "imputation": None,
                        "model_id": model_id,
                        "n": n_subset,
                        "rank": fit["rank"],
                        "condition_number": fit["condition_number"],
                        "cluster_counts": json.dumps(
                            fit["covariance_meta"]["cluster_counts"],
                            sort_keys=True,
                        ),
                        "demeaning_converged": demeaning["converged"],
                        "finite_beta": bool(np.isfinite(fit["beta"]).all()),
                        "finite_covariance": bool(
                            np.isfinite(fit["covariance"]).all()
                        ),
                    }
                )
                del x_tilde, y_tilde, fit
                gc.collect()
            direct_results.append(pd.DataFrame(rows))
            del (
                subset_raw,
                subset_outcome,
                subset_fe,
                subset_clusters,
            )
            gc.collect()
            shutil.rmtree(folder)

    # NPI-level multiple imputation under both priors.
    assignment_inventory = []
    for prior_name, probabilities in (
        ("aamc_fl", lookup.primary),
        ("national", lookup.national),
    ):
        for imputation in range(1, args.imputations + 1):
            measurement_id = f"{prior_name}_npi_mi"
            assignment = categorical_assignments(
                lookup.npis_by_code,
                probabilities,
                args.seed,
                prior_name,
                imputation,
            )
            assignment_sha256 = hashlib.sha256(
                assignment.tobytes()
            ).hexdigest()
            assignment_inventory.append(
                {
                    "prior": prior_name,
                    "imputation": imputation,
                    "assignment_sha256": assignment_sha256,
                    "encoded_npis": len(assignment),
                    "assignment_counts": {
                        race: int((assignment == index).sum())
                        for index, race in enumerate(RACES)
                    },
                }
            )
            folder = variant_scratch / f"{measurement_id}_{imputation:02d}"
            folder.mkdir(parents=True, exist_ok=True)
            cells_path = folder / "cells.float64.mmap"
            mi_cells, mi_support = write_cells_with_support(
                cells_path,
                raw,
                outcome,
                clusters,
                cell_ids,
                cell_context,
                context_race_to_cell,
                None,
                assignment,
                args.row_chunk,
            )
            del mi_cells
            mi_support.insert(0, "imputation", imputation)
            mi_support.insert(
                0, "measurement_specification", measurement_id
            )
            support_frames.append(mi_support)
            mi_results.append(
                fit_full_cells(
                    measurement_id,
                    cells_path,
                    mi_support,
                    imputation,
                )
            )
            shutil.rmtree(folder)
            del assignment
            gc.collect()

    direct_frame = pd.concat(direct_results, ignore_index=True)
    mi_frame = pd.concat(mi_results, ignore_index=True)
    pooled = pool_mi(mi_frame, args.imputations)
    support_frame = pd.concat(support_frames, ignore_index=True)
    diagnostics_frame = pd.DataFrame(diagnostics)

    direct_path = output / "measurement_sensitivity_direct_results.csv"
    mi_path = output / "measurement_sensitivity_mi_components.csv"
    pooled_path = output / "measurement_sensitivity_mi_pooled.csv"
    support_path = output / "measurement_sensitivity_cell_support.csv"
    diagnostics_path = output / "measurement_sensitivity_diagnostics.csv"
    assignment_path = output / "measurement_sensitivity_assignments.json"
    direct_frame.to_csv(direct_path, index=False)
    mi_frame.to_csv(mi_path, index=False)
    pooled.to_csv(pooled_path, index=False)
    support_frame.to_csv(support_path, index=False)
    diagnostics_frame.to_csv(diagnostics_path, index=False)
    atomic_json(
        assignment_path,
        {
            "seed": args.seed,
            "method": (
                "SHA-256 deterministic uniform by seed, prior, imputation, "
                "and NPI; one categorical draw per NPI held across visits."
            ),
            "probability_source_sha256": lookup.source_sha256,
            "assignments": assignment_inventory,
        },
    )
    files = []
    for path in (
        direct_path,
        mi_path,
        pooled_path,
        support_path,
        diagnostics_path,
        assignment_path,
    ):
        files.append(
            {
                "path": str(path.resolve()),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    files.extend(fit_inventory)
    payload = {
        "status": "PASS",
        "created_utc": now_utc(),
        "analysis_id": "directional_measurement_sensitivity_v1_20260726",
        "binding": binding,
        "family": args.family,
        "outcome": args.outcome,
        "primary_result_role": (
            "Supplemental measurement sensitivity; does not replace the "
            "AAMC-Florida posterior-mixture primary directional estimate."
        ),
        "physician_race_interpretation": (
            "Algorithm-inferred five-class analytical proxy; not "
            "self-reported identity and not BISG."
        ),
        "direct_measurement_specifications": [
            "national_probability_weighted",
            *[
                f"{prior}_hard_max_t{int(threshold * 100):02d}"
                for prior in ("aamc_fl", "national")
                for threshold in THRESHOLDS
            ],
        ],
        "mi_priors": ["aamc_fl", "national"],
        "imputations_per_prior": args.imputations,
        "model_ids": list(MODEL_FE),
        "support_thresholds": MIN_SUPPORT,
        "limited_support_thresholds": LIMITED_SUPPORT,
        "files": files,
        "source_release_modified": False,
        "phase2_cohort_modified": False,
        "result_interpretation_authorized": False,
        "independent_audit_required": True,
    }
    atomic_json(completion_path, payload)
    print(
        json.dumps(
            {
                "status": "PASS",
                "family": args.family,
                "outcome": args.outcome,
                "direct_specifications": len(
                    payload["direct_measurement_specifications"]
                ),
                "mi_priors": len(payload["mi_priors"]),
                "imputations_per_prior": args.imputations,
                "result_values_emitted": False,
                "independent_audit_required": True,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
