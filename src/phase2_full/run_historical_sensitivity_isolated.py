# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/run_historical_sensitivity_isolated.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Prepare, run, and aggregate historical sensitivities with OS isolation."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


RACE_OUTCOMES = [
    "length_of_stay_days",
    "total_charge_reported_real_2024",
    "procedure_count_analysis",
    "any_procedure_flag",
    "routine_discharge_flag",
    "transfer_flag",
    "mortality_flag",
]
RACE_SPECIFICATIONS = [
    "primary_prior_t50",
    "primary_prior_t70",
    "primary_prior_t80",
    "primary_prior_t90",
    "population_prior_t50",
    "primary_probability_bw",
]
SEX_GENDER_SAMPLES = [
    "recorded_sources",
    "recorded_sources_no_nppes_cms_conflict",
]


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(path)


def result_is_reusable(result_path: Path, job: dict[str, Any]) -> bool:
    if not result_path.exists():
        return False
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        bound_job = payload.get("job", {})
        return bool(
            payload.get("status") == "PASS"
            and payload.get("diagnostic", {}).get("status") == "converged"
            and bound_job.get("model_id") == job.get("model_id")
            and bound_job.get("input_sha256") == job.get("input_sha256")
            and bound_job.get("outcome") == job.get("outcome")
            and bound_job.get("terms") == job.get("terms")
            and bound_job.get("fixed_effects") == job.get("fixed_effects")
            and bound_job.get("cluster") == job.get("cluster")
        )
    except Exception:
        return False


def run_preparer(
    *,
    script: Path,
    phase2: Path,
    temp: Path,
    threads: int,
    memory_limit: str,
) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--phase2",
            str(phase2),
            "--temp",
            str(temp),
            "--threads",
            str(threads),
            "--memory-limit",
            memory_limit,
            "--prepare-only",
        ],
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Historical preparation failed with code {completed.returncode}"
        )


def run_jobs(
    *,
    preparation: dict[str, Any],
    worker: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    results: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    result_files: list[dict[str, Any]] = []
    for job_path_text in preparation["job_paths"]:
        job_path = Path(job_path_text)
        job = json.loads(job_path.read_text(encoding="utf-8"))
        result_path = Path(job["output_json"])
        reused = result_is_reusable(result_path, job)
        return_code = 0
        if not reused:
            completed = subprocess.run(
                [sys.executable, str(worker), "--job", str(job_path)],
                check=False,
            )
            return_code = completed.returncode
        if result_path.exists():
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            if payload.get("result") is not None:
                results.append(payload["result"])
            diagnostic = payload.get(
                "diagnostic",
                {
                    "model_id": job["model_id"],
                    "status": "failed",
                    "error": "Missing diagnostic in isolated result",
                },
            )
            diagnostic["isolated_result_reused"] = reused
            diagnostic["worker_return_code"] = return_code
            diagnostics.append(diagnostic)
            result_files.append(
                {
                    "model_id": job["model_id"],
                    "path": str(result_path),
                    "sha256": sha256_file(result_path),
                    "reused": reused,
                }
            )
        else:
            diagnostics.append(
                {
                    "model_id": job["model_id"],
                    "specification_id": job["specification_id"],
                    "status": "failed",
                    "n": None,
                    "worker_isolated_process": True,
                    "worker_return_code": return_code,
                    "error": "Worker exited without an atomic result file",
                }
            )
    return results, diagnostics, result_files


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--analysis",
        required=True,
        choices=("race", "sex_gender"),
    )
    parser.add_argument("--phase2", required=True, type=Path)
    parser.add_argument("--temp", required=True, type=Path)
    parser.add_argument("--threads", type=int, default=12)
    parser.add_argument("--memory-limit", default="24GB")
    args = parser.parse_args()

    phase2 = args.phase2.resolve()
    temp = args.temp.resolve()
    temp.mkdir(parents=True, exist_ok=True)
    scripts = Path(__file__).resolve().parent
    worker = scripts / "historical_hdfe_isolated_worker.py"

    if args.analysis == "race":
        preparer = scripts / "17_historical_sensitivity_analysis.py"
        isolated_root = temp / "isolated_race_models"
        expected = len(RACE_SPECIFICATIONS) * len(RACE_OUTCOMES)
    else:
        preparer = scripts / "17b_historical_sex_gender_sensitivity.py"
        isolated_root = temp / "isolated_sex_gender_models"
        expected = len(SEX_GENDER_SAMPLES) * len(RACE_OUTCOMES)

    run_preparer(
        script=preparer,
        phase2=phase2,
        temp=temp,
        threads=args.threads,
        memory_limit=args.memory_limit,
    )
    preparation_path = isolated_root / "preparation_manifest.json"
    preparation = json.loads(
        preparation_path.read_text(encoding="utf-8")
    )
    if (
        preparation.get("status") != "PASS"
        or preparation.get("jobs_expected") != expected
        or preparation.get("jobs_prepared") != expected
        or len(preparation.get("job_paths", [])) != expected
    ):
        raise RuntimeError("Historical isolated preparation manifest failed")

    model_rows, diagnostics, result_files = run_jobs(
        preparation=preparation,
        worker=worker,
    )
    converged = sum(
        item.get("status") == "converged" for item in diagnostics
    )
    status = (
        "PASS"
        if len(diagnostics) == expected
        and len(model_rows) == expected
        and converged == expected
        else "FAIL"
    )
    qa = phase2 / "qa"
    documentation = phase2 / "documentation"

    if args.analysis == "race":
        output = phase2 / "results" / "historical_provider_v2_sensitivity"
        output.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(model_rows).to_csv(
            output / "historical_adjusted_race_sensitivities.csv",
            index=False,
        )
        pd.DataFrame(diagnostics).to_csv(
            qa / "historical_provider_v2_race_model_diagnostics.csv",
            index=False,
        )
        manifest = {
            "created_utc": now_utc(),
            "status": status,
            "analysis_id": "historical_provider_v2_race_sensitivities_v1",
            "rows_in_name_matched_historical_bw_frame": preparation[
                "frame_rows"
            ],
            "race_specifications": RACE_SPECIFICATIONS,
            "outcomes": RACE_OUTCOMES,
            "models_expected": expected,
            "models_converged": converged,
            "elixhauser_indicator_count": preparation[
                "elixhauser_indicator_count"
            ],
            "worker_isolation": (
                "Preparation exits before sequential hash-bound one-model "
                "worker processes; no sample or covariate reduction."
            ),
            "models_using_demeaning_fallback": sum(
                bool(item.get("demeaning_fallback_used"))
                for item in diagnostics
                if item.get("status") == "converged"
            ),
            "preparation_manifest": str(preparation_path),
            "preparation_manifest_sha256": sha256_file(preparation_path),
            "isolated_result_files": result_files,
            "separate_analysis": True,
            "never_pooled_with_primary": True,
            "provider_measurement_version": (
                "provider_master_v2_full_name_race_v1"
            ),
            "pre_estimation_gate": preparation["pre_estimation_gate"],
            "pre_estimation_gate_status": preparation[
                "pre_estimation_gate_status"
            ],
            "hourly_los_used": False,
            "los_outcome": "length_of_stay_days",
            "source_release_modified": False,
        }
        manifest_path = output / "historical_analysis_manifest.json"
        atomic_json(manifest_path, manifest)
        (
            documentation / "Historical_Race_Concordance_Sensitivity.md"
        ).write_text(
            """# Historical 2005-2008 race-concordance sensitivity

This analysis is separate from the 2010-2024 primary cohort. It uses the
provider-v2 full-name race probability model and six prespecified measurement
specifications. Compatible outcomes use day-level LOS; hourly LOS is
structurally unavailable and not imputed. Models use facility-year-quarter and
principal clinical-category fixed effects with two-way physician/facility
clustered standard errors and the full prespecified adjustment set.

Each model is fit in a fresh OS process from a hash-bound prepared parquet
input. Isolation is computational only and does not alter any sample,
covariate, fixed effect, cluster, outcome, or contrast.
""",
            encoding="utf-8",
        )
    else:
        output = (
            phase2
            / "results"
            / "historical_provider_v2_sex_gender_sensitivity"
        )
        output.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(model_rows).to_csv(
            output / "historical_sex_gender_adjusted_interactions.csv",
            index=False,
        )
        pd.DataFrame(diagnostics).to_csv(
            qa
            / "historical_provider_v2_sex_gender_model_diagnostics.csv",
            index=False,
        )
        manifest = {
            "created_utc": now_utc(),
            "status": status,
            "analysis_id": (
                "historical_provider_v2_sex_gender_sensitivity_v1"
            ),
            "rows": preparation["frame_rows"],
            "outcomes": RACE_OUTCOMES,
            "models_expected": expected,
            "models_converged": converged,
            "sample_variants": preparation["sample_variants"],
            "recorded_source_conflict_visits": preparation[
                "recorded_source_conflict_visits"
            ],
            "elixhauser_indicator_count": preparation[
                "elixhauser_indicator_count"
            ],
            "worker_isolation": (
                "Preparation exits before sequential hash-bound one-model "
                "worker processes; no sample or covariate reduction."
            ),
            "models_using_demeaning_fallback": sum(
                bool(item.get("demeaning_fallback_used"))
                for item in diagnostics
                if item.get("status") == "converged"
            ),
            "preparation_manifest": str(preparation_path),
            "preparation_manifest_sha256": sha256_file(preparation_path),
            "isolated_result_files": result_files,
            "separate_analysis": True,
            "never_pooled_with_primary": True,
            "provider_measurement_version": (
                "provider_master_v2_full_name_race_v1"
            ),
            "pre_estimation_gate": preparation["pre_estimation_gate"],
            "pre_estimation_gate_status": preparation[
                "pre_estimation_gate_status"
            ],
            "hourly_los_used": False,
            "los_outcome": "length_of_stay_days",
            "terminology": (
                "recorded patient sex-physician gender concordance; "
                "not gender identity"
            ),
            "source_release_modified": False,
        }
        manifest_path = (
            output / "historical_sex_gender_analysis_manifest.json"
        )
        atomic_json(manifest_path, manifest)
        (
            documentation / "Historical_Sex_Gender_Sensitivity.md"
        ).write_text(
            """# Historical 2005-2008 sex/gender sensitivity

This all-diagnosis sensitivity is separate from the 2010-2024 primary cohort
and the historical AMI extension. Primary physician gender uses recorded
NPPES/CMS categories; a second exact variant excludes recorded-source
conflicts. Hourly LOS is structurally unavailable and not imputed.

Each model is fit in a fresh OS process from a hash-bound prepared parquet
input. Isolation is computational only and changes no model definition.
""",
            encoding="utf-8",
        )

    print(json.dumps(manifest, indent=2))
    if status != "PASS":
        raise SystemExit(
            f"One or more isolated historical {args.analysis} models failed"
        )


if __name__ == "__main__":
    main()
