#!/usr/bin/env python
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/49d_report_materializer_unit_tests.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Synthetic, estimate-blind tests for the audited report materializer."""

from __future__ import annotations

import importlib.util
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


PHASE2 = Path(__file__).resolve().parents[1]
SCRIPT = PHASE2 / "scripts" / "49c_materialize_audited_report_sources.py"


def load_module():
    spec = importlib.util.spec_from_file_location("report_materializer", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load report materializer")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    module = load_module()
    checks = []

    def add(check_id: str, passed: bool, evidence):
        checks.append(
            {"check_id": check_id, "passed": bool(passed), "evidence": evidence}
        )

    primary = pd.DataFrame(
        [
            {
                "testing_family": "confirmatory_race_primary",
                "outcome": "los_hours_primary_0_168",
                "cohort": "race",
                "model_id": "m2_fully_adjusted_facility_yq_clinical_fe",
                "analysis_sample_policy": "los_outcome",
                "estimate": 1.2,
                "ci95_low": 0.2,
                "ci95_high": 2.2,
                "p_value": 0.02,
                "adjusted_p_value": 0.04,
                "n": 1000,
            },
            {
                "testing_family": "confirmatory_race_primary",
                "outcome": "total_charge_reported_real_2024",
                "cohort": "race",
                "model_id": "m2_fully_adjusted_facility_yq_clinical_fe",
                "analysis_sample_policy": "charge_outcome",
                "estimate": 20.0,
                "ci95_low": -5.0,
                "ci95_high": 45.0,
                "p_value": 0.12,
                "adjusted_p_value": 0.12,
                "n": 900,
            },
        ]
    )
    selected = module.primary_rows(primary)
    add(
        "confirmatory_filter_requires_exact_two_outcome_family",
        len(selected) == 2
        and set(selected["outcome"]) == set(module.PRIMARY_OUTCOMES),
        selected[["outcome", "analysis_sample_policy"]].to_dict("records"),
    )
    rejected = False
    try:
        module.primary_rows(primary.iloc[:1])
    except SystemExit:
        rejected = True
    add(
        "incomplete_confirmatory_family_fails_closed",
        rejected,
        "One-row synthetic family rejected.",
    )

    directional = pd.DataFrame(
        [
            {
                "family_id": family,
                "estimability_status": status,
                "limited_support_flag": limited,
                "q_value_bh": q,
            }
            for family, status, limited, q in (
                ("gender_dyads", "ESTIMABLE", False, 0.04),
                ("gender_dyads", "NON_ESTIMABLE_VARIANCE", True, None),
                ("race_dyads", "ESTIMABLE", False, 0.20),
                ("intersectional_dyads", "ESTIMABLE", True, 0.01),
            )
        ]
    )
    summary = module.directional_summary(directional)
    gender = summary.loc[summary["family_id"] == "gender_dyads"].iloc[0]
    add(
        "directional_summary_preserves_nonestimable_and_limited_counts",
        int(gender["rows"]) == 2
        and int(gender["estimable"]) == 1
        and int(gender["limited_support"]) == 1,
        summary.to_dict("records"),
    )

    issue = {
        "chronology_date_utc": "2026-07-27T00:00:00+00:00",
        "issue_id": "ISS-T",
        "issue_title": "Synthetic issue",
        "what_happened": "A test condition occurred.",
        "detection": "Synthetic detection.",
        "potentially_affected_artifacts": "None.",
        "scientific_or_computational_importance": "Tests completeness.",
        "correction": "Synthetic correction.",
        "rebuilt_or_rerun": "None.",
        "preserved_artifacts": "Synthetic only.",
        "recurrence_prevention": "Unit test.",
        "validation_evidence_candidates": "synthetic",
    }
    narrative = module.issue_narrative([issue])
    add(
        "issue_narrative_contains_all_required_fields",
        all(
            label in narrative
            for label in (
                "What happened",
                "Detection",
                "Potentially affected artifacts",
                "Scientific or computational importance",
                "Correction",
                "Rebuilt or rerun",
                "Preserved artifacts",
                "Recurrence prevention",
                "Validation evidence",
            )
        ),
        len(narrative),
    )

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        module.timeline_figure(root / "timeline.png")
        module.forest_figure(root / "forest.png", selected)
        module.directional_figure(root / "directional.png", summary)
        figures = list(root.glob("*.png"))
        add(
            "synthetic_figures_render",
            len(figures) == 3 and all(path.stat().st_size > 0 for path in figures),
            {path.name: path.stat().st_size for path in figures},
        )

    status = "PASS" if all(check["passed"] for check in checks) else "FAIL"
    payload = {
        "test_id": "report_materializer_unit_tests_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "checks_passed": sum(check["passed"] for check in checks),
        "checks_total": len(checks),
        "checks": checks,
        "synthetic_only": True,
        "real_result_values_read": False,
    }
    output = PHASE2 / "qa" / "report_materializer_unit_tests.json"
    output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2))
    if status != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
