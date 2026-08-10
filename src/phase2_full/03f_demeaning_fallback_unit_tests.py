#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/03f_demeaning_fallback_unit_tests.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Synthetic tests for the fail-closed HDFE numerical fallback policy."""

from __future__ import annotations

import argparse
import gc
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np


def load_module(path: Path) -> Any:
    name = "primary_hdfe_engine_under_fallback_test"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def atomic_json(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    args = parser.parse_args()
    phase2 = args.phase2.resolve()
    engine = load_module(phase2 / "scripts" / "08_estimate_primary_models.py")

    calls: list[dict[str, Any]] = []

    class FakeDemeaner:
        def __init__(
            self,
            *,
            fixef_maxiter: int,
            fixef_tol: float,
            backend: str,
        ) -> None:
            self.maxiter = fixef_maxiter
            self.tolerance = fixef_tol
            self.backend = backend

    def fake_dispatch(
        block: np.ndarray,
        fe: np.ndarray,
        weights: np.ndarray,
        demeaner: FakeDemeaner,
    ) -> tuple[np.ndarray, bool, dict[str, Any]]:
        calls.append(
            {
                "tolerance": demeaner.tolerance,
                "maxiter": demeaner.maxiter,
                "rows": len(block),
                "columns": block.shape[1],
            }
        )
        if demeaner.tolerance < 1e-6:
            return block.copy(), False, {"iterations": demeaner.maxiter}
        transformed = block - block.mean(axis=0, keepdims=True)
        return transformed, True, {"iterations": 7}

    original_demeaner = engine.MapDemeaner
    original_dispatch = engine.dispatch_demean
    engine.MapDemeaner = FakeDemeaner
    engine.dispatch_demean = fake_dispatch
    checks: list[dict[str, Any]] = []
    try:
        with tempfile.TemporaryDirectory(prefix="hdfe_fallback_test_") as temp:
            root = Path(temp)

            def mmap(name: str, values: np.ndarray) -> np.memmap:
                result = np.memmap(
                    root / name,
                    dtype=values.dtype,
                    mode="w+",
                    shape=values.shape,
                )
                result[:] = values
                result.flush()
                return result

            raw_values = np.arange(24, dtype=np.float64).reshape(12, 2)
            outcome_values = np.arange(12, dtype=np.float64)[:, None]
            fe_values = np.column_stack(
                (
                    np.repeat(np.arange(3), 4),
                    np.tile(np.arange(4), 3),
                    np.arange(12) % 2,
                )
            ).astype(np.uint64)
            raw = mmap("raw.float64.mmap", raw_values)
            outcomes = mmap("outcomes.float64.mmap", outcome_values)
            fe = mmap("fe.uint64.mmap", fe_values)
            folder = root / "demeaned"
            x, y, metadata = engine.residualize(
                raw,
                outcomes,
                fe,
                [0, 1],
                [0, 1],
                folder,
                1,
                1e-8,
                {"synthetic_binding": "v1"},
            )
            state_path = folder / "demeaning_state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            expected_attempt_keys = {"x_0_1", "x_1_2", "y_0_1"}
            first_call_pattern = [
                (item["tolerance"], item["maxiter"]) for item in calls
            ]
            checks.extend(
                [
                    {
                        "check_id": "strict_then_fallback_for_each_failed_block",
                        "passed": (
                            len(calls) == 6
                            and first_call_pattern
                            == [
                                (1e-8, 10_000),
                                (1e-6, 50_000),
                            ]
                            * 3
                        ),
                    },
                    {
                        "check_id": "state_records_all_fallback_blocks",
                        "passed": (
                            set(state["demeaning_attempts"])
                            == expected_attempt_keys
                            and set(metadata["fallback_blocks"])
                            == expected_attempt_keys
                            and all(
                                item["strict_status"] == "NONCONVERGED"
                                and item["fallback_status"] == "CONVERGED"
                                and item["fallback_used"] is True
                                for item in state[
                                    "demeaning_attempts"
                                ].values()
                            )
                        ),
                    },
                    {
                        "check_id": "fallback_output_written",
                        "passed": (
                            np.allclose(
                                np.asarray(x),
                                raw_values
                                - raw_values.mean(axis=0, keepdims=True),
                            )
                            and np.allclose(
                                np.asarray(y),
                                outcome_values
                                - outcome_values.mean(
                                    axis=0, keepdims=True
                                ),
                            )
                        ),
                    },
                ]
            )

            # Simulate a restart after a persisted strict failure. Completed
            # flags are cleared, but exact failure metadata and files remain.
            state["completed_local_columns"] = []
            state["completed_outcome_columns"] = []
            state["outcomes_completed"] = False
            state["convergence"] = {}
            atomic_json(state_path, state)
            calls.clear()
            expected_x = np.asarray(x).copy()
            expected_y = np.asarray(y).copy()
            del x, y
            gc.collect()
            x2, y2, metadata2 = engine.residualize(
                raw,
                outcomes,
                fe,
                [0, 1],
                [0, 1],
                folder,
                1,
                1e-8,
                {"synthetic_binding": "v1"},
            )
            resumed_state = json.loads(
                state_path.read_text(encoding="utf-8")
            )
            checks.append(
                {
                    "check_id": "restart_reuses_documented_strict_failure",
                    "passed": (
                        len(calls) == 3
                        and all(
                            item["tolerance"] == 1e-6
                            and item["maxiter"] == 50_000
                            for item in calls
                        )
                        and metadata2["fallback_used"] is True
                        and all(
                            item[
                                "strict_attempt_reused_from_checkpoint"
                            ]
                            is True
                            for item in resumed_state[
                                "demeaning_attempts"
                            ].values()
                        )
                        and np.allclose(np.asarray(x2), expected_x)
                        and np.allclose(np.asarray(y2), expected_y)
                    ),
                }
            )
            del x2, y2, raw, outcomes, fe
            gc.collect()
    finally:
        engine.MapDemeaner = original_demeaner
        engine.dispatch_demean = original_dispatch

    failures = [
        item["check_id"] for item in checks if not bool(item["passed"])
    ]
    payload = {
        "status": "PASS" if not failures else "FAIL",
        "test_id": "primary_hdfe_demeaning_fallback_unit_tests_v1",
        "checks": checks,
        "checks_passed": len(checks) - len(failures),
        "checks_total": len(checks),
        "failures": failures,
        "real_data_loaded": False,
        "result_values_read": False,
        "source_release_modified": False,
        "phase2_cohort_modified": False,
    }
    output = phase2 / "qa" / "demeaning_fallback_unit_tests.json"
    atomic_json(output, payload)
    print(
        json.dumps(
            {
                "status": payload["status"],
                "checks_passed": payload["checks_passed"],
                "checks_total": payload["checks_total"],
                "failures": failures,
                "real_result_values_emitted": False,
            },
            indent=2,
        )
    )
    if failures:
        raise SystemExit("Demeaning fallback unit tests failed")


if __name__ == "__main__":
    main()
