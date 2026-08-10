#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/48_independent_directional_measurement_sensitivity_audit.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Independent fail-closed audit of one directional race sensitivity set."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
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
MODELS = ("M2_DIRECTIONAL", "M3_WITHIN_PHYSICIAN")


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


def strict_bool(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    text = str(value).strip().lower()
    if text not in ("true", "false"):
        raise ValueError(f"Invalid Boolean value: {value}")
    return text == "true"


def close(actual: Any, expected: Any) -> bool:
    try:
        left = float(actual)
        right = float(expected)
    except (TypeError, ValueError):
        return False
    if math.isnan(left) and math.isnan(right):
        return True
    return math.isclose(left, right, rel_tol=2e-10, abs_tol=2e-11)


def stable_uniform(seed: int, prior: str, imputation: int, npi: str) -> float:
    payload = f"{seed}|{prior}|{imputation}|{npi}".encode("utf-8")
    value = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")
    return (value + 0.5) / 2**64


def independent_assignments(
    npis: list[str],
    probabilities: np.ndarray,
    seed: int,
    prior: str,
    imputation: int,
) -> np.ndarray:
    uniforms = np.array(
        [
            stable_uniform(seed, prior, imputation, npi)
            for npi in npis
        ],
        dtype=np.float64,
    )
    cumulative = np.cumsum(probabilities, axis=1)
    cumulative[:, -1] = 1.0
    return (uniforms[:, None] > cumulative).sum(axis=1).astype(np.uint8)


def provider_probabilities(
    source_path: Path, encoder_path: Path
) -> tuple[list[str], np.ndarray, np.ndarray]:
    physician = load_json(encoder_path)["physician"]
    count = max(int(value) for value in physician.values()) + 1
    npis = [""] * count
    for npi, code in physician.items():
        npis[int(code)] = str(npi)
    if any(not value for value in npis):
        raise RuntimeError("Physician encoder is not dense")
    requested = pd.DataFrame(
        {"npi": npis, "code": np.arange(count, dtype=np.int64)}
    )
    con = duckdb.connect()
    con.register("requested", requested)
    frame = con.execute(
        f"""
        SELECT
            r.code,
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
        FROM requested r
        LEFT JOIN read_parquet('{source_path.as_posix()}') p
          ON r.npi = p.npi
        ORDER BY r.code
        """
    ).fetch_df()
    con.close()
    if len(frame) != count or frame.isna().any().any():
        raise RuntimeError("Independent provider probability lookup failed")
    primary = frame.iloc[:, 1:6].to_numpy(dtype=np.float64)
    national = frame.iloc[:, 6:11].to_numpy(dtype=np.float64)
    return npis, primary, national


def target_vector(
    target_type: str,
    target_id: str,
    model_id: str,
    cell_ids: list[str],
    contrasts: dict[str, dict[str, Any]],
    cell_mean: np.ndarray,
    k: int,
) -> tuple[np.ndarray, bool]:
    q = len(cell_ids)
    lookup = {value: index for index, value in enumerate(cell_ids)}
    target = np.zeros(k, dtype=np.float64)
    is_prediction = target_type == "adjusted_prediction"
    if is_prediction:
        if model_id != "M2_DIRECTIONAL" or target_id not in lookup:
            raise RuntimeError("Invalid adjusted-prediction target")
        target[:q] = -cell_mean
        target[lookup[target_id]] += 1.0
    else:
        contrast = contrasts[target_id]
        for term in contrast["linear_combination"]:
            target[lookup[term["cell_id"]]] = float(term["weight"])
    return target, is_prediction


def infer(
    target: np.ndarray,
    beta: np.ndarray,
    covariance: np.ndarray,
    projector: np.ndarray,
    df: int,
    anchor: float,
) -> dict[str, Any]:
    residual = target - projector @ target
    row_error = float(
        np.linalg.norm(residual) / max(np.linalg.norm(target), 1.0)
    )
    identified = row_error <= 1e-8
    estimate = float(anchor + target @ beta)
    variance = float(target @ covariance @ target)
    valid = math.isfinite(variance) and variance >= -1e-12
    se = math.sqrt(max(variance, 0.0)) if valid else math.nan
    statistic = (
        estimate / se
        if identified and se > 0 and math.isfinite(se) and df > 0
        else math.nan
    )
    p_value = (
        float(2 * student_t.sf(abs(statistic), df))
        if math.isfinite(statistic)
        else math.nan
    )
    critical = float(student_t.ppf(0.975, df)) if df > 0 else math.nan
    return {
        "estimate": estimate,
        "variance": max(variance, 0.0) if valid else variance,
        "standard_error": se,
        "ci95_low": estimate - critical * se,
        "ci95_high": estimate + critical * se,
        "p_value_raw": p_value,
        "identified": identified,
        "variance_valid": valid,
        "rowspace_relative_error": row_error,
        "cluster_df": df,
    }


def audit_fit_rows(
    fit_item: dict[str, Any],
    frame: pd.DataFrame,
    cell_ids: list[str],
    contrasts: dict[str, dict[str, Any]],
) -> list[str]:
    mismatches = []
    path = Path(fit_item["path"])
    loaded = np.load(path)
    beta = loaded["beta"]
    covariance = loaded["covariance"]
    projector = loaded["projector"]
    cell_mean = loaded["cell_mean"]
    outcome_mean = float(loaded["outcome_mean"][0])
    df = int(loaded["cluster_df"][0])
    measurement = fit_item["measurement_specification"]
    imputation = fit_item.get("imputation")
    model_id = fit_item["model_id"]
    selected = frame.loc[
        frame["measurement_specification"].eq(measurement)
        & frame["model_id"].eq(model_id)
    ].copy()
    if imputation is None:
        selected = selected.loc[selected["imputation"].isna()]
    else:
        selected = selected.loc[
            pd.to_numeric(selected["imputation"], errors="coerce").eq(
                int(imputation)
            )
        ]
    expected_rows = len(contrasts) + (
        len(cell_ids) if model_id == "M2_DIRECTIONAL" else 0
    )
    if len(selected) != expected_rows:
        return [f"{measurement}/{imputation}/{model_id}:row_count"]
    for row in selected.to_dict("records"):
        target, prediction = target_vector(
            row["target_type"],
            row["target_id"],
            model_id,
            cell_ids,
            contrasts,
            cell_mean,
            len(beta),
        )
        expected = infer(
            target,
            beta,
            covariance,
            projector,
            df,
            outcome_mean if prediction else 0.0,
        )
        for column in (
            "estimate",
            "variance",
            "standard_error",
            "ci95_low",
            "ci95_high",
            "p_value_raw",
            "rowspace_relative_error",
            "cluster_df",
        ):
            if not close(row[column], expected[column]):
                mismatches.append(
                    f"{measurement}/{imputation}/{model_id}/"
                    f"{row['target_id']}:{column}"
                )
        for column in ("identified", "variance_valid"):
            if strict_bool(row[column]) != expected[column]:
                mismatches.append(
                    f"{measurement}/{imputation}/{model_id}/"
                    f"{row['target_id']}:{column}"
                )
    return mismatches


def independent_pool(components: pd.DataFrame) -> pd.DataFrame:
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
    for key, block in components.groupby(keys, dropna=False):
        estimates = block["estimate"].to_numpy(dtype=np.float64)
        variances = block["variance"].to_numpy(dtype=np.float64)
        m = len(block)
        estimate = float(estimates.mean())
        within = float(variances.mean())
        between = float(estimates.var(ddof=1))
        total = within + (1 + 1 / m) * between
        se = math.sqrt(total)
        if between > 0:
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
        rows.append(
            {
                **dict(zip(keys, key)),
                "estimate": estimate,
                "variance": total,
                "standard_error": se,
                "ci95_low": estimate - critical * se,
                "ci95_high": estimate + critical * se,
                "p_value_raw": p_value,
                "rubin_degrees_freedom": df,
                "within_imputation_variance": within,
                "between_imputation_variance": between,
                "imputations_completed": m,
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    parser.add_argument("--matrix-root", required=True, type=Path)
    parser.add_argument("--results-root", required=True, type=Path)
    parser.add_argument("--family", required=True, choices=FAMILIES)
    parser.add_argument("--outcome", required=True, choices=OUTCOMES)
    parser.add_argument("--row-chunk", type=int, default=137_777)
    args = parser.parse_args()

    phase2 = args.phase2.resolve()
    matrix_dir = (
        args.matrix_root.resolve() / args.family / args.outcome
    )
    output = (
        args.results_root.resolve() / args.family / args.outcome
    )
    manifest_path = output / "measurement_sensitivity_manifest.json"
    if not manifest_path.is_file():
        raise SystemExit("Measurement-sensitivity manifest missing")
    manifest = load_json(manifest_path)
    if manifest.get("status") != "PASS":
        raise SystemExit("Measurement-sensitivity manifest is not PASS")
    binding = manifest["binding"]

    execution_path = (
        phase2 / "documentation" / "Directional_Dyad_Execution_Code_FROZEN.json"
    )
    execution = load_json(execution_path)
    live_code = []
    for item in execution["code_inventory"]:
        path = phase2 / item["path"]
        live_code.append(
            path.is_file() and sha256_file(path) == item["sha256"]
        )
    matrix_manifest_path = matrix_dir / "matrix_manifest.json"
    matrix_audit_path = (
        phase2
        / "qa"
        / "directional_matrix_audits"
        / f"{args.family}__{args.outcome}.json"
    )
    primary_audit_path = (
        phase2
        / "qa"
        / "directional_result_audits"
        / f"{args.family}__{args.outcome}.json"
    )
    binding_valid = (
        binding["family"] == args.family
        and binding["outcome"] == args.outcome
        and binding["matrix_manifest_sha256"]
        == sha256_file(matrix_manifest_path)
        and binding["matrix_audit_sha256"] == sha256_file(matrix_audit_path)
        and binding["primary_result_audit_sha256"]
        == sha256_file(primary_audit_path)
        and binding["execution_manifest_sha256"] == sha256_file(execution_path)
        and Path(binding["provider_race_proxy_path"]).is_file()
        and binding["provider_race_proxy_sha256"]
        == sha256_file(Path(binding["provider_race_proxy_path"]))
        and Path(binding["encoder_path"]).resolve()
        == (matrix_dir / "category_encoders.json").resolve()
        and binding["encoder_sha256"]
        == sha256_file(Path(binding["encoder_path"]))
        and binding["imputations"] == 20
        and binding["seed"] == 20260726
        and binding["thresholds"] == list(THRESHOLDS)
    )

    file_checks = []
    fit_items = []
    for item in manifest["files"]:
        path = Path(item["path"])
        passed = (
            path.is_file()
            and path.stat().st_size == int(item["bytes"])
            and sha256_file(path) == item["sha256"]
        )
        file_checks.append({"path": str(path), "passed": passed})
        if path.suffix == ".npz":
            fit_items.append(item)

    extension = load_json(
        phase2
        / "documentation"
        / "Directional_Dyad_Analysis_Plan_Extension_FROZEN.json"
    )
    family_spec = extension["analysis_families"][args.family]
    cell_ids = [item["cell_id"] for item in family_spec["cells"]]
    contrasts = {
        item["contrast_id"]: item for item in family_spec["contrasts"]
    }
    q, c = len(cell_ids), len(contrasts)
    per_imputation = q + 2 * c
    expected_direct_specs = {
        "national_probability_weighted",
        *{
            f"{prior}_hard_max_t{int(threshold * 100):02d}"
            for prior in ("aamc_fl", "national")
            for threshold in THRESHOLDS
        },
    }

    direct = pd.read_csv(
        output / "measurement_sensitivity_direct_results.csv"
    )
    components = pd.read_csv(
        output / "measurement_sensitivity_mi_components.csv"
    )
    pooled = pd.read_csv(
        output / "measurement_sensitivity_mi_pooled.csv"
    )
    support = pd.read_csv(
        output / "measurement_sensitivity_cell_support.csv"
    )
    diagnostics = pd.read_csv(
        output / "measurement_sensitivity_diagnostics.csv"
    )
    assignments = load_json(
        output / "measurement_sensitivity_assignments.json"
    )

    direct_grid_valid = (
        set(direct["measurement_specification"]) == expected_direct_specs
        and len(direct) == len(expected_direct_specs) * per_imputation
        and not direct.duplicated(
            [
                "measurement_specification",
                "model_id",
                "target_type",
                "target_id",
            ]
        ).any()
    )
    mi_specs = {"aamc_fl_npi_mi", "national_npi_mi"}
    component_grid_valid = (
        set(components["measurement_specification"]) == mi_specs
        and len(components) == 2 * 20 * per_imputation
        and components["imputation"].nunique() == 20
        and not components.duplicated(
            [
                "measurement_specification",
                "imputation",
                "model_id",
                "target_type",
                "target_id",
            ]
        ).any()
    )
    pooled_grid_valid = (
        set(pooled["measurement_specification"]) == mi_specs
        and len(pooled) == 2 * per_imputation
        and not pooled.duplicated(
            [
                "measurement_specification",
                "model_id",
                "target_type",
                "target_id",
            ]
        ).any()
    )
    expected_support_rows = (1 + 8 + 40) * q
    support_grid_valid = (
        len(support) == expected_support_rows
        and support["cell_id"].isin(cell_ids).all()
        and pd.to_numeric(
            support["weighted_visit_mass"], errors="coerce"
        ).notna().all()
        and (
            pd.to_numeric(
                support["weighted_visit_mass"], errors="coerce"
            )
            >= 0
        ).all()
    )
    support_rule_mismatches = []
    for row in support.to_dict("records"):
        passed = (
            float(row["kish_effective_visits"]) >= 1000
            and float(row["effective_physicians"]) >= 30
            and int(row["distinct_facilities_positive_mass"]) >= 20
            and int(row["distinct_physicians_positive_mass"]) >= 30
        )
        limited = (
            float(row["kish_effective_visits"]) < 5000
            or float(row["effective_physicians"]) < 50
            or int(row["distinct_facilities_positive_mass"]) < 30
        )
        status = (
            "NON_ESTIMABLE_SUPPORT"
            if not passed
            else ("LIMITED_SUPPORT" if limited else "PASS")
        )
        if (
            strict_bool(row["support_pass"]) != passed
            or strict_bool(row["limited_support_flag"]) != limited
            or row["support_status"] != status
        ):
            support_rule_mismatches.append(
                f"{row['measurement_specification']}/"
                f"{row.get('imputation')}/{row['cell_id']}"
            )
    diagnostics_grid_valid = (
        len(diagnostics) == (9 + 40) * 2
        and diagnostics["model_id"].isin(MODELS).all()
        and diagnostics["demeaning_converged"].map(strict_bool).all()
        and diagnostics["finite_beta"].map(strict_bool).all()
        and diagnostics["finite_covariance"].map(strict_bool).all()
    )
    fit_grid_valid = len(fit_items) == (9 + 40) * 2

    fit_mismatches = []
    for item in fit_items:
        frame = (
            components
            if item.get("imputation") is not None
            else direct
        )
        fit_mismatches.extend(
            audit_fit_rows(item, frame, cell_ids, contrasts)
        )

    result_support_mismatches = []
    for result_frame in (direct, components):
        for row in result_frame.to_dict("records"):
            support_block = support.loc[
                support["measurement_specification"].eq(
                    row["measurement_specification"]
                )
            ]
            row_imputation = pd.to_numeric(
                pd.Series([row.get("imputation")]), errors="coerce"
            ).iloc[0]
            if pd.isna(row_imputation):
                support_block = support_block.loc[
                    support_block["imputation"].isna()
                ]
            else:
                support_block = support_block.loc[
                    pd.to_numeric(
                        support_block["imputation"], errors="coerce"
                    ).eq(int(row_imputation))
                ]
            if row["target_type"] == "adjusted_prediction":
                involved = [row["target_id"]]
            else:
                involved = [
                    item["cell_id"]
                    for item in contrasts[row["target_id"]][
                        "linear_combination"
                    ]
                    if float(item["weight"]) != 0
                ]
            selected = support_block.set_index("cell_id").loc[involved]
            passed = bool(selected["support_pass"].map(strict_bool).all())
            limited = bool(
                selected["limited_support_flag"].map(strict_bool).any()
            )
            status = (
                "NON_ESTIMABLE_IDENTIFICATION"
                if not strict_bool(row["identified"])
                else (
                    "NON_ESTIMABLE_VARIANCE"
                    if not strict_bool(row["variance_valid"])
                    else (
                        "NON_ESTIMABLE_SUPPORT"
                        if not passed
                        else ("LIMITED_SUPPORT" if limited else "PASS")
                    )
                )
            )
            if (
                strict_bool(row["support_pass"]) != passed
                or strict_bool(row["limited_support_flag"]) != limited
                or row["estimability_status"] != status
            ):
                result_support_mismatches.append(
                    f"{row['measurement_specification']}/"
                    f"{row.get('imputation')}/{row['model_id']}/"
                    f"{row['target_id']}"
                )

    independently_pooled = independent_pool(components)
    pool_mismatches = []
    pool_keys = [
        "family_id",
        "outcome",
        "measurement_specification",
        "model_id",
        "target_type",
        "target_id",
    ]
    merged = pooled.merge(
        independently_pooled,
        on=pool_keys,
        suffixes=("_actual", "_expected"),
        validate="one_to_one",
    )
    if len(merged) != len(pooled):
        pool_mismatches.append("pooled_key_grid")
    for row in merged.to_dict("records"):
        for column in (
            "estimate",
            "variance",
            "standard_error",
            "ci95_low",
            "ci95_high",
            "p_value_raw",
            "rubin_degrees_freedom",
            "within_imputation_variance",
            "between_imputation_variance",
            "imputations_completed",
        ):
            if not close(
                row[f"{column}_actual"], row[f"{column}_expected"]
            ):
                pool_mismatches.append(
                    f"{row['measurement_specification']}/"
                    f"{row['model_id']}/{row['target_id']}:{column}"
                )

    source_path = Path(manifest["binding"].get(
        "provider_race_proxy_path",
        phase2 / "analysis_data" / "dimensions" / "provider_race_proxy_v2.parquet",
    ))
    encoder_path = matrix_dir / "category_encoders.json"
    npis, primary_probs, national_probs = provider_probabilities(
        source_path, encoder_path
    )
    assignment_mismatches = []
    assignment_rows = assignments["assignments"]
    if len(assignment_rows) != 40:
        assignment_mismatches.append("assignment_count")
    for item in assignment_rows:
        prior = item["prior"]
        probabilities = (
            primary_probs if prior == "aamc_fl" else national_probs
        )
        draw = independent_assignments(
            npis,
            probabilities,
            assignments["seed"],
            prior,
            int(item["imputation"]),
        )
        if hashlib.sha256(draw.tobytes()).hexdigest() != item[
            "assignment_sha256"
        ]:
            assignment_mismatches.append(
                f"{prior}/{item['imputation']}:hash"
            )
        expected_counts = {
            race: int((draw == index).sum())
            for index, race in enumerate(RACES)
        }
        if expected_counts != item["assignment_counts"]:
            assignment_mismatches.append(
                f"{prior}/{item['imputation']}:counts"
            )

    matrix_manifest = load_json(matrix_manifest_path)
    n = int(matrix_manifest["n_rows"])
    clusters = np.memmap(
        matrix_dir / "cluster_codes.uint64.mmap",
        dtype=np.uint64,
        mode="r",
        shape=(n, 3),
    )
    expected_n = {"national_probability_weighted": n}
    for prior, probabilities in (
        ("aamc_fl", primary_probs),
        ("national", national_probs),
    ):
        maxima = probabilities.max(axis=1)
        counts = {threshold: 0 for threshold in THRESHOLDS}
        for start, stop in chunks(n, args.row_chunk):
            physician = np.asarray(
                clusters[start:stop, 0], dtype=np.int64
            )
            row_maxima = maxima[physician]
            for threshold in THRESHOLDS:
                counts[threshold] += int(
                    (row_maxima >= threshold).sum()
                )
        for threshold, count in counts.items():
            expected_n[
                f"{prior}_hard_max_t{int(threshold * 100):02d}"
            ] = count
    sample_size_mismatches = []
    for measurement, expected in expected_n.items():
        observed = diagnostics.loc[
            diagnostics["measurement_specification"].eq(measurement), "n"
        ]
        if (
            len(observed) != 2
            or not observed.astype(int).eq(int(expected)).all()
        ):
            sample_size_mismatches.append(measurement)
    mi_diagnostics = diagnostics.loc[
        diagnostics["measurement_specification"].isin(mi_specs)
    ]
    if len(mi_diagnostics) != 80 or not mi_diagnostics["n"].astype(
        int
    ).eq(n).all():
        sample_size_mismatches.append("multiple_imputation_full_sample")

    support_mass_mismatches = []
    support_group_columns = ["measurement_specification"]
    if "imputation" in support:
        support_group_columns.append("imputation")
    for key, block in support.groupby(support_group_columns, dropna=False):
        measurement = key[0] if isinstance(key, tuple) else key
        expected = expected_n.get(measurement, n)
        if not math.isclose(
            float(block["weighted_visit_mass"].sum()),
            float(expected),
            rel_tol=1e-10,
            abs_tol=1e-5,
        ):
            support_mass_mismatches.append(str(key))

    checks = [
        ("execution_code_live", all(live_code)),
        ("binding_live", binding_valid),
        ("file_hashes", all(item["passed"] for item in file_checks)),
        ("direct_grid", direct_grid_valid),
        ("mi_component_grid", component_grid_valid),
        ("mi_pooled_grid", pooled_grid_valid),
        ("support_grid", support_grid_valid),
        ("support_rules_recomputed", not support_rule_mismatches),
        ("diagnostic_grid", diagnostics_grid_valid),
        ("fit_grid", fit_grid_valid),
        ("all_targets_recomputed", not fit_mismatches),
        ("result_support_status_recomputed", not result_support_mismatches),
        ("rubin_pooling_recomputed", not pool_mismatches),
        ("npi_assignments_recomputed", not assignment_mismatches),
        ("hard_sample_sizes_recomputed", not sample_size_mismatches),
        ("cell_mass_reconciles", not support_mass_mismatches),
        (
            "measurement_language",
            "Algorithm-inferred" in manifest["physician_race_interpretation"]
            and "not BISG" in manifest["physician_race_interpretation"],
        ),
    ]
    failures = [name for name, passed in checks if not passed]
    payload = {
        "audit_id": (
            "independent_directional_measurement_sensitivity_audit_v1"
        ),
        "created_utc": now_utc(),
        "status": "PASS" if not failures else "FAIL",
        "family": args.family,
        "outcome": args.outcome,
        "checks": [
            {"check_id": name, "passed": bool(passed)}
            for name, passed in checks
        ],
        "checks_passed": sum(bool(value) for _, value in checks),
        "checks_total": len(checks),
        "failures": failures,
        "fit_mismatches": fit_mismatches,
        "support_rule_mismatches": support_rule_mismatches,
        "result_support_mismatches": result_support_mismatches,
        "pool_mismatches": pool_mismatches,
        "assignment_mismatches": assignment_mismatches,
        "sample_size_mismatches": sample_size_mismatches,
        "support_mass_mismatches": support_mass_mismatches,
        "result_values_emitted": False,
        "result_interpretation_authorized": not failures,
        "source_release_modified": False,
        "phase2_cohort_modified": False,
    }
    audit_path = (
        phase2
        / "qa"
        / "directional_measurement_sensitivity_audits"
        / f"{args.family}__{args.outcome}.json"
    )
    atomic_json(audit_path, payload)
    print(
        json.dumps(
            {
                "status": payload["status"],
                "family": args.family,
                "outcome": args.outcome,
                "checks_passed": payload["checks_passed"],
                "checks_total": payload["checks_total"],
                "failures": failures,
                "result_values_emitted": False,
            },
            indent=2,
        )
    )
    if failures:
        raise SystemExit("Directional measurement-sensitivity audit failed")


if __name__ == "__main__":
    main()
