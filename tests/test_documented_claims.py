from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence"


def load(name: str) -> dict:
    return json.loads((EVIDENCE / name).read_text(encoding="utf-8"))


def test_phase1_claims_match_evidence() -> None:
    build = load("phase1_build_summary.json")
    validation = load("phase1_validation_summary.json")
    assert build["encounter_records"] == 148_686_146
    assert build["expected_quarters"] == build["completed_quarters"] == 76
    assert build["distinct_visit_keys"] == build["encounter_records"]
    assert build["fact_field_count"] == 342
    assert build["schema_family_count"] == 5
    assert build["excluded_years"] == [2009, 2025]
    assert build["raw_data_mutated"] is False
    assert validation["status"] == "PASS"
    assert validation["required_release_artifacts_passed"] is True


def test_phase2_claims_match_evidence() -> None:
    provider = load("provider_v2_summary.json")
    cohort = load("phase2_cohort_summary.json")
    historical = load("historical_validation_summary.json")
    assert provider["provider_master"]["unique_npis"] == 1_813_546
    assert provider["provider_master"]["complete_ed_observed_universe"] is True
    assert provider["ed_observed_provider_counts"]["organizational_npis_classified_md_do"] == 0
    assert provider["race_measurement"]["is_bisg"] is False
    assert provider["race_measurement"]["is_self_reported"] is False
    assert cohort["validated_partitions"] == 60
    assert cohort["cohort_rows"] == 119_543_044
    assert historical["historical_cohort"]["reconciled_partitions"] == 16
    assert historical["historical_cohort"]["cohort_rows"] == 23_304_846
    assert historical["historical_analysis_audit"]["status"] == "PASS"
    assert historical["directional_result_interpretation_authorized"] is False


def test_status_does_not_overstate_completion() -> None:
    status = load("current_project_status.json")
    states = status["component_status"]
    assert states["phase1_database_construction"] == "COMPLETE"
    assert states["historical_analyses"] == "COMPLETE"
    if not status["final_analytical_pass_exists"]:
        assert states["primary_race_models"] == "IN PROGRESS"
        assert states["primary_race_m1_m3_estimation"] == "COMPLETE_AUDIT_PENDING"
        assert states["primary_gender_models"] == "IN PROGRESS"
        assert states["primary_gender_m1_estimation"] == "COMPLETE_AUDIT_PENDING"
        assert states["primary_gender_m2"] == "RESTART_REQUIRED"
        assert states["primary_gender_m3"] == "PENDING"
        for name in (
            "outcome_specific_models",
            "directional_dyad_models",
            "corrected_primary_ami",
            "multiplicity",
            "final_analytical_audit",
            "final_research_report",
        ):
            assert states[name] == "PENDING"


def test_readme_has_no_unreleased_result_language() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8").lower()
    assert "no incomplete effect estimates are reported" in readme
    assert "causal effect" not in readme
    assert "statistically significant" not in readme
    assert "fully completed research project" not in readme
