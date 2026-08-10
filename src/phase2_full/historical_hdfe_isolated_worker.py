# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/historical_hdfe_isolated_worker.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Fit one historical HDFE model in an OS-isolated process.

The parent historical analysis scripts prepare hash-bound parquet inputs and
launch this worker sequentially.  Process exit guarantees that native/Rust
allocations are returned to the operating system before the next large model.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pyfixest as pf


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_float(value: Any) -> float:
    return float(value) if value is not None else math.nan


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(path)


def fit_with_numerical_fallback(
    *,
    formula: str,
    data: pd.DataFrame,
    vcov: dict[str, str],
) -> tuple[Any, dict[str, Any]]:
    attempts = (
        {
            "fixef_tol": 1e-8,
            "fixef_maxiter": 10_000,
            "demeaning_fallback_used": False,
        },
        {
            "fixef_tol": 1e-6,
            "fixef_maxiter": 50_000,
            "demeaning_fallback_used": True,
        },
    )
    first_error: str | None = None
    for attempt_number, attempt in enumerate(attempts, start=1):
        try:
            fit = pf.feols(
                formula,
                data=data,
                vcov=vcov,
                copy_data=False,
                store_data=False,
                demeaner=pf.MapDemeaner(
                    fixef_tol=attempt["fixef_tol"],
                    fixef_maxiter=attempt["fixef_maxiter"],
                    backend="rust",
                ),
                lean=True,
            )
            return fit, {
                **attempt,
                "demeaning_attempt_number": attempt_number,
                "initial_demeaning_error": first_error,
            }
        except ValueError as error:
            if attempt_number == 1 and "Demeaning failed" in str(error):
                first_error = repr(error)
                continue
            raise
    raise RuntimeError("Unreachable demeaning fallback state")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True, type=Path)
    args = parser.parse_args()

    job = json.loads(args.job.read_text(encoding="utf-8"))
    input_path = Path(job["input_parquet"])
    output_path = Path(job["output_json"])
    outcome = job["outcome"]
    terms = list(job["terms"])
    fixed_effects = job["fixed_effects"]
    cluster = job["cluster"]
    interaction_term = job["interaction_term"]

    required_columns = list(
        dict.fromkeys(
            [
                outcome,
                *terms,
                *job["fixed_effect_columns"],
                *job["cluster_columns"],
            ]
        )
    )
    frame = pd.read_parquet(input_path, columns=required_columns)
    frame = frame.loc[frame[outcome].notna()].copy()
    frame[outcome] = frame[outcome].astype(float)

    diagnostic: dict[str, Any] = {
        "model_id": job["model_id"],
        "specification_id": job["specification_id"],
        "status": "failed",
        "n": len(frame),
        "input_parquet": str(input_path),
        "input_sha256": job["input_sha256"],
        "worker_isolated_process": True,
        **job.get("diagnostic_dimensions", {}),
    }
    for output_name, column_name in job.get(
        "diagnostic_distinct_columns", {}
    ).items():
        diagnostic[output_name] = int(frame[column_name].nunique())
    try:
        fit, numerical = fit_with_numerical_fallback(
            formula=(
                f"{outcome} ~ {' + '.join(terms)} | {fixed_effects}"
            ),
            data=frame,
            vcov={"CRV1": cluster},
        )
        interval = fit.confint().loc[interaction_term]
        result = {
            "model_id": job["model_id"],
            "specification_id": job["specification_id"],
            "outcome": outcome,
            "term": interaction_term,
            "contrast": job["contrast"],
            "estimate": safe_float(fit.coef().get(interaction_term)),
            "standard_error": safe_float(fit.se().get(interaction_term)),
            "ci95_low": safe_float(interval.iloc[0]),
            "ci95_high": safe_float(interval.iloc[1]),
            "p_value": safe_float(fit.pvalue().get(interaction_term)),
            "n": len(frame),
            "input_sha256": job["input_sha256"],
            "worker_isolated_process": True,
            **job.get("result_dimensions", {}),
            **numerical,
        }
        diagnostic.update(
            {
                "status": "converged",
                **numerical,
            }
        )
        payload = {
            "created_utc": now_utc(),
            "status": "PASS",
            "job": job,
            "result": result,
            "diagnostic": diagnostic,
        }
        atomic_json(output_path, payload)
        print(
            json.dumps(
                {
                    "model_id": job["model_id"],
                    "status": "PASS",
                    "n": len(frame),
                    **numerical,
                }
            )
        )
    except Exception as error:
        diagnostic["error"] = repr(error)
        atomic_json(
            output_path,
            {
                "created_utc": now_utc(),
                "status": "FAIL",
                "job": job,
                "result": None,
                "diagnostic": diagnostic,
            },
        )
        raise


if __name__ == "__main__":
    main()
