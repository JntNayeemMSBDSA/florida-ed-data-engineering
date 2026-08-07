#!/usr/bin/env python3
"""Build public aggregate evidence from an approved private source workspace.

The extractor reads only the small JSON checkpoints named below plus the
non-substantive demeaning progress checkpoint supplied on the command line. It
does not open encounter files, provider rows, model matrices, or result tables.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PHASE1_RELEASE = "outputs/florida_ed_full_build_20260724"
PHASE2_RELEASE = "outputs/florida_ed_concordance_analysis_20260726"

EXPECTED_SOURCE_HASHES = {
    f"{PHASE1_RELEASE}/build_manifest_final.json": "0ca547d9179d913c7b4af0668f06107383e86d75013a2ea1b5694736d55c218f",
    f"{PHASE1_RELEASE}/qa/qa_summary.json": "5b66d41517eb0ea47f5fef09ad66cd695a29cd79152d9ad35a4eef4a8753bf3b",
    f"{PHASE1_RELEASE}/qa/independent_release_validation.json": "758dd46559c0498433abf9ebba8f08a6e8f6085c6c60982bb4ecab58bfc0ad3e",
    f"{PHASE2_RELEASE}/qa/provider_master_v2_qa.json": "15e3e2548e9f5dcc1cb32ef15e13cea318801ec56909ad126a2a738c1bbed541",
    f"{PHASE2_RELEASE}/qa/provider_race_proxy_v2_qa.json": "2c9d1a80519db33e80e05703db010f36df554149608ef174495c9b272868f9de",
    f"{PHASE2_RELEASE}/qa/pre_estimation_measurement_gate.json": "575095a279b632b407792142b6d92ec596a1d073781a6306479cfc695f22c786",
    f"{PHASE2_RELEASE}/qa/provider_gender_measurement_checkpoint.json": "aa973aabe29f03a0af667e84ed8415ee1be4116a9391956c7567e83145baacdf",
    f"{PHASE2_RELEASE}/qa/cohort_validation_report.json": "153197dd95d814b5189706f42e8f85bc5b74991266db81185343508acc688275",
    f"{PHASE2_RELEASE}/qa/historical_provider_v2_pre_estimation_gate.json": "454fd433c1245294133a8eb7a29dfdc39d4843fbf21da117d49594cb2f97a12c",
    f"{PHASE2_RELEASE}/qa/independent_historical_results_audit.json": "ca5358a2823d684dd3a408ab231d04bce39c38c52d93ec4ef377cd332d7b8d55",
    f"{PHASE2_RELEASE}/qa/directional_dyad_extension_pre_estimation_gate.json": "416771e528cc1f41c9cbf869f446921e3777c0fa75d7bf676b131176c14ed4b8",
    f"{PHASE2_RELEASE}/qa/directional_model_implementation_pre_estimation_gate.json": "aa74edf1ce780b43ff1f7401b9f11c8bd8b7fc1e6fcfc8930506aaf72fec1b83",
    f"{PHASE2_RELEASE}/qa/ami_validation_report.json": "92a43b8ee9245022274ee04220ac5e84d7150c0af68feb8b95de3b51687a5f52",
    f"{PHASE2_RELEASE}/qa/historical_ami_validation_report.json": "6c36c3003462d6f2081d3b2558c0a3cf47bfb73fbe3cdf12cf79141df2c80eb9",
    f"{PHASE2_RELEASE}/qa/linkage_selection_audit.json": "bf58f868abd492f3fb6a219d95a8a53a4715bf3f2f6e6ae20eff2c47f8c710e4",
}

SOURCE_SCRIPT_PROVENANCE = {
    "src/phase1/prepare_full_build.py": (
        f"{PHASE1_RELEASE}/scripts/prepare_full_build.py",
        "039788c29493ae76ed2bef33763eca0a080a89c85a54406f2bb6d58f4b8fae12",
    ),
    "src/phase1/build_ed_partitions.py": (
        f"{PHASE1_RELEASE}/scripts/build_ed_partitions.py",
        "503bb4d77a3a3a3762786a58db9efd907f253864b516f88c8ffff97558bb73f5",
    ),
    "src/phase1/build_physician_master.py": (
        f"{PHASE1_RELEASE}/scripts/build_physician_master.py",
        "c079cb76f0b4c3b13570ccfceab3280dcfbcb61ac8796f6ad64c9a19d30bcb04",
    ),
    "src/phase1/finalize_facility_summaries_qa.py": (
        f"{PHASE1_RELEASE}/scripts/finalize_facility_summaries_qa.py",
        "92fb5a7e83cf1b10ba9731eedf750b6e090342630352fa6fca9b286707f6f613",
    ),
    "src/phase1/validate_final_release.py": (
        f"{PHASE1_RELEASE}/scripts/validate_final_release.py",
        "c4402f5e569e1f9f4b3bb84af7ad327c16031397ca76ea02d65bee1aee6eff01",
    ),
    "src/phase2/04a_build_provider_master_v2.py": (
        f"{PHASE2_RELEASE}/scripts/04a_build_provider_master_v2.py",
        "c4c0493bef59704e012f0bf335c4ea50290eee53bac13906f8f08f50b86ffd7a",
    ),
    "src/phase2/04c_validate_provider_race_v2.py": (
        f"{PHASE2_RELEASE}/scripts/04c_validate_provider_race_v2.py",
        "a62e32018b09157c0bd08c5aa709966d0287555bb084326c32da091181236d73",
    ),
    "src/phase2/05_validate_analysis_cohort.py": (
        f"{PHASE2_RELEASE}/scripts/05_validate_analysis_cohort.py",
        "4b188ed902d8bafa246911497a3a4c23ffcbb85c8efb7050e8f088f4afdacdee",
    ),
    "src/phase2/07_prepare_primary_model_matrix.py": (
        f"{PHASE2_RELEASE}/scripts/07_prepare_primary_model_matrix.py",
        "62ae3417c3685c9f81da754caa5ac1a74c1ad3fb0b8d14c9bcd3cd3e76a01471",
    ),
    "src/phase2/08_estimate_primary_models.py": (
        f"{PHASE2_RELEASE}/scripts/08_estimate_primary_models.py",
        "fe6a21ca466dd58919b9e13e6b3ec511dbaf175fbf54f29d5ae38bbb3e6bc8c9",
    ),
    "src/phase2/09_validate_hdfe_engine.py": (
        f"{PHASE2_RELEASE}/scripts/09_validate_hdfe_engine.py",
        "deb279ecfb4a027a5b1bd44741168d071794d7892d168aae911518a5edecf8ab",
    ),
    "src/phase2/13_build_historical_sensitivity_cohort.py": (
        f"{PHASE2_RELEASE}/scripts/13_build_historical_sensitivity_cohort.py",
        "db625a561fa4fc915a2550923bd7e46dc9f209431a96b38798f334488548467e",
    ),
    "src/phase2/15_linkage_selection_audit.py": (
        f"{PHASE2_RELEASE}/scripts/15_linkage_selection_audit.py",
        "573b6b9e4fcb4492708cc90ee1c1cdf8341a5b00a67527bc7086baf19102b5a1",
    ),
    "src/phase2/16_apply_multiple_testing.py": (
        f"{PHASE2_RELEASE}/scripts/16_apply_multiple_testing.py",
        "870e1b056d66ecbb032815d6fa3e2c00e4c07ab588ee537d85c639a8cfb76da7",
    ),
    "src/phase2/38b_directional_model_definition_tests.py": (
        f"{PHASE2_RELEASE}/scripts/38b_directional_model_definition_tests.py",
        "31c878975df7996bc50c5286d011c17d4e7830bc261877e281e2e7ab56c096dc",
    ),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_approved_json(source_root: Path, relative: str) -> tuple[dict[str, Any], dict[str, str]]:
    path = source_root / Path(relative)
    expected = EXPECTED_SOURCE_HASHES[relative]
    actual = sha256_file(path)
    if actual != expected:
        raise RuntimeError(f"Approved source hash changed: {relative}")
    return json.loads(path.read_text(encoding="utf-8")), {
        "file": relative,
        "sha256": actual,
    }


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def evidence_header(extracted: str, sources: list[dict[str, str]]) -> dict[str, Any]:
    return {"extracted_at_utc": extracted, "sources": sources}


def checkpoint_summary(path: Path) -> tuple[dict[str, Any], dict[str, str]]:
    state = json.loads(path.read_text(encoding="utf-8"))
    completed_design = state.get("completed_local_columns", [])
    completed_outcomes = state.get("completed_outcome_columns", [])
    design_total = len(state.get("column_indices", []))
    design_complete = design_total > 0 and len(completed_design) == design_total
    outcomes_complete = bool(state.get("outcomes_completed", False))
    return {
        "checkpoint_updated_utc": state.get("updated_utc"),
        "cohort_id": path.parent.parent.name,
        "model_id": path.parent.name,
        "design_columns_completed": len(completed_design),
        "design_columns_total": design_total,
        "outcome_columns_completed": len(completed_outcomes),
        "outcomes_completed": outcomes_complete,
        "overall_completion_flag": design_complete and outcomes_complete,
    }, {"file": path.name, "sha256": sha256_file(path)}


def final_pass_status(path: Path | None) -> tuple[bool, dict[str, str] | None]:
    if path is None:
        return False, None
    payload = json.loads(path.read_text(encoding="utf-8"))
    status = str(payload.get("status", "")).upper()
    return status == "PASS", {"file": path.name, "sha256": sha256_file(path)}


def category_for(relative: str) -> str:
    if relative.startswith("src/"):
        return "sanitized production code"
    if relative.startswith("synthetic_demo/"):
        return "synthetic demonstration"
    if relative.startswith("tests/"):
        return "test"
    if relative.startswith("evidence/"):
        return "sanitized evidence"
    if relative.startswith("scripts/"):
        return "repository tooling"
    if relative.startswith("docs/") or relative.endswith(".md"):
        return "documentation"
    if relative.startswith("configs/"):
        return "configuration template"
    return "repository metadata"


def write_inventory(repository_root: Path) -> None:
    inventory_path = repository_root / "REPOSITORY_INVENTORY.csv"
    ignored_parts = {".git", "__pycache__", ".pytest_cache", "generated", "output"}
    files = [
        path
        for path in repository_root.rglob("*")
        if path.is_file() and not any(part in ignored_parts for part in path.parts)
    ]
    rows: list[dict[str, Any]] = []
    for path in sorted(files, key=lambda item: item.relative_to(repository_root).as_posix()):
        relative = path.relative_to(repository_root).as_posix()
        if relative == "REPOSITORY_INVENTORY.csv":
            continue
        source_relative, source_hash = SOURCE_SCRIPT_PROVENANCE.get(relative, ("", ""))
        rows.append(
            {
                "repository_path": relative,
                "category": category_for(relative),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "source_relative_path": source_relative,
                "source_sha256": source_hash,
                "sanitization_notes": (
                    "Header added; private roots parameterized; scientific logic retained."
                    if source_relative
                    else ""
                ),
            }
        )
    rows.append(
        {
            "repository_path": "REPOSITORY_INVENTORY.csv",
            "category": "repository metadata",
            "bytes": "",
            "sha256": "",
            "source_relative_path": "",
            "source_sha256": "",
            "sanitization_notes": "Self-referential size and hash intentionally omitted.",
        }
    )
    with inventory_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--brief-source", type=Path)
    parser.add_argument("--final-pass-marker", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("evidence"))
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--write-inventory", action="store_true")
    parser.add_argument("--inventory-only", action="store_true")
    args = parser.parse_args()

    if args.inventory_only:
        write_inventory(args.repository_root.resolve())
        print("Updated REPOSITORY_INVENTORY.csv")
        return
    if not args.source_root or not args.checkpoint or not args.brief_source:
        parser.error("--source-root, --checkpoint, and --brief-source are required")

    source_root = args.source_root.resolve()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    extracted = datetime.now(timezone.utc).isoformat()

    manifest, manifest_ref = load_approved_json(
        source_root, f"{PHASE1_RELEASE}/build_manifest_final.json"
    )
    phase1_qa, phase1_qa_ref = load_approved_json(
        source_root, f"{PHASE1_RELEASE}/qa/qa_summary.json"
    )
    independent, independent_ref = load_approved_json(
        source_root, f"{PHASE1_RELEASE}/qa/independent_release_validation.json"
    )
    provider, provider_ref = load_approved_json(
        source_root, f"{PHASE2_RELEASE}/qa/provider_master_v2_qa.json"
    )
    race, race_ref = load_approved_json(
        source_root, f"{PHASE2_RELEASE}/qa/provider_race_proxy_v2_qa.json"
    )
    gate, gate_ref = load_approved_json(
        source_root, f"{PHASE2_RELEASE}/qa/pre_estimation_measurement_gate.json"
    )
    gender, gender_ref = load_approved_json(
        source_root, f"{PHASE2_RELEASE}/qa/provider_gender_measurement_checkpoint.json"
    )
    cohort, cohort_ref = load_approved_json(
        source_root, f"{PHASE2_RELEASE}/qa/cohort_validation_report.json"
    )
    historical, historical_ref = load_approved_json(
        source_root,
        f"{PHASE2_RELEASE}/qa/historical_provider_v2_pre_estimation_gate.json",
    )
    historical_audit, historical_audit_ref = load_approved_json(
        source_root, f"{PHASE2_RELEASE}/qa/independent_historical_results_audit.json"
    )
    directional_plan, directional_plan_ref = load_approved_json(
        source_root,
        f"{PHASE2_RELEASE}/qa/directional_dyad_extension_pre_estimation_gate.json",
    )
    directional_impl, directional_impl_ref = load_approved_json(
        source_root,
        f"{PHASE2_RELEASE}/qa/directional_model_implementation_pre_estimation_gate.json",
    )
    ami, ami_ref = load_approved_json(
        source_root, f"{PHASE2_RELEASE}/qa/ami_validation_report.json"
    )
    historical_ami, historical_ami_ref = load_approved_json(
        source_root, f"{PHASE2_RELEASE}/qa/historical_ami_validation_report.json"
    )
    linkage, linkage_ref = load_approved_json(
        source_root, f"{PHASE2_RELEASE}/qa/linkage_selection_audit.json"
    )

    write_json(
        output / "phase1_build_summary.json",
        {
            **evidence_header(extracted, [manifest_ref]),
            "release_id": manifest["release_id"],
            "scope_years": manifest["scope_years"],
            "excluded_years": manifest["excluded_years"],
            "expected_quarters": manifest["expected_quarters"],
            "completed_quarters": manifest["qa_summary"]["completed_quarters"],
            "encounter_records": manifest["qa_summary"]["fact_row_count"],
            "distinct_visit_keys": manifest["qa_summary"]["fact_distinct_visit_key_count"],
            "fact_field_count": manifest["fact_field_count"],
            "schema_family_count": 5,
            "schema_families": [
                "2005-2008",
                "2010-2015 Q3",
                "2015 Q4-2017",
                "2018-2022",
                "2023-2024",
            ],
            "raw_data_mutated": manifest["raw_data_mutated"],
        },
    )
    write_json(
        output / "phase1_validation_summary.json",
        {
            **evidence_header(extracted, [phase1_qa_ref, independent_ref]),
            "status": independent["status"],
            "quarter_manifest_count": independent["quarter_manifest_count"],
            "fact_partition_count": independent["fact_partition_count"],
            "fact_row_count": independent["fact_row_count"],
            "fact_field_count": independent["fact_field_count"],
            "visit_key_uniqueness_passed": phase1_qa["visit_key_uniqueness_passed"],
            "excluded_years_passed": phase1_qa["excluded_years_passed"],
            "icd_transition_passed": phase1_qa["icd_transition_passed"],
            "structural_null_measure_check": independent["structural_null_measure_check"],
            "required_release_artifacts_passed": independent["required_release_artifacts_passed"],
        },
    )
    write_json(
        output / "provider_v2_summary.json",
        {
            **evidence_header(extracted, [provider_ref, race_ref, gate_ref, gender_ref]),
            "provider_master": {
                "status": "PASS" if provider["qa_passed"] else "FAIL",
                "unique_npis": provider["distinct_npis"],
                "duplicate_npis": provider["duplicate_npis"],
                "ed_observed_npis_absent": provider["ed_observed_npis_absent_master_v2"],
                "complete_ed_observed_universe": provider["ed_observed_npis_absent_master_v2"] == 0,
            },
            "ed_observed_provider_counts": gate["provider_counts"],
            "race_measurement": {
                "status": "PASS" if race["qa_passed"] else "FAIL",
                "method": race["method_label"],
                "interpretation": race["interpretation"],
                "method_id": race["primary_method_id"],
                "name_likelihood_release": "wru 2.0.0",
                "primary_prior": "AAMC Florida active physicians, 2020",
                "sensitivity_prior": "wru national 2020 population marginal",
                "uses_residential_geography": False,
                "is_bisg": False,
                "is_self_reported": False,
            },
            "gender_measurement": {
                "status": gender["status"],
                "primary_sources": gender["primary_definition"]["physician_gender_sources"],
                "categories": gender["primary_definition"]["physician_categories"],
                "is_self_identified_gender_identity": False,
            },
        },
    )
    write_json(
        output / "phase2_cohort_summary.json",
        {
            **evidence_header(extracted, [cohort_ref, gate_ref]),
            "status": cohort["status"],
            "period": "2010-2024",
            "expected_partitions": cohort["expected_partitions"],
            "validated_partitions": cohort["validated_partitions"],
            "cohort_rows": cohort["aggregate_counts"]["all_rows"],
            "failed_checks": len(cohort["failed_checks"]),
            "source_release_modified": cohort["source_release_modified"],
            "rebuilt_from_immutable_phase1_facts": True,
        },
    )
    write_json(
        output / "historical_validation_summary.json",
        {
            **evidence_header(
                extracted,
                [
                    historical_ref,
                    historical_audit_ref,
                    historical_ami_ref,
                    directional_plan_ref,
                    directional_impl_ref,
                    ami_ref,
                    linkage_ref,
                ],
            ),
            "historical_cohort": {
                "status": historical["status"],
                "period": "2005-2008",
                "expected_partitions": historical["expected_partitions"],
                "reconciled_partitions": historical["reconciled_partitions"],
                "cohort_rows": historical["historical_rows"],
                "phase1_rows": historical["phase1_rows"],
                "source_release_modified": historical["source_release_modified"],
            },
            "historical_analysis_audit": {
                "status": historical_audit["status"],
                "checks_passed": historical_audit["checks_passed"],
                "checks_total": historical_audit["checks_total"],
                "source_release_modified": historical_audit["source_release_modified"],
            },
            "historical_ami": {
                "status": historical_ami["status"],
                "setting": historical_ami["setting"],
                "replication_claim_permitted": historical_ami[
                    "greenwood_replication_claim_permitted"
                ],
            },
            "primary_ami_definition_gate": {
                "status": ami["status"],
                "interpretation_gate": ami["interpretation_gate"],
            },
            "directional_plan_gate": directional_plan["status"],
            "directional_implementation_gate": directional_impl["status"],
            "directional_result_interpretation_authorized": directional_impl[
                "model_estimate_interpretation_authorized"
            ],
            "linkage_selection_audit": {
                "status": linkage["status"],
                "ipw_used_as_primary_correction": False,
                "source_release_modified": linkage["source_release_modified"],
            },
        },
    )

    progress, checkpoint_ref = checkpoint_summary(args.checkpoint.resolve())
    final_pass, final_pass_ref = final_pass_status(
        args.final_pass_marker.resolve() if args.final_pass_marker else None
    )
    brief_hash = sha256_file(args.brief_source.resolve())
    if brief_hash != "b590dd7bcc3537280ffee98dc0c1826cd20c0deadbc6148564f37eb40ba098fe":
        raise RuntimeError("Repository-construction brief hash changed")
    status_sources = [
        {"file": "repository_construction_brief.txt", "sha256": brief_hash},
        checkpoint_ref,
    ]
    if final_pass_ref:
        status_sources.append(final_pass_ref)
    current_status = {
        **evidence_header(extracted, status_sources),
        "status_statement": (
            "Phase 1 complete and independently validated; Phase 2 measurement, "
            "cohort construction, historical analyses, and analytical specifications "
            "complete; primary 2010-2024 estimation and final analytical audits in progress."
        ),
        "development_history": {
            "prototype_share": "approximately 0.5%",
            "prototype_encounter_rows": 743767,
            "production_identity_claim": False,
        },
        "primary_race_progress": progress,
        "final_analytical_pass_exists": final_pass,
        "component_status": {
            "phase1_database_construction": "COMPLETE",
            "phase1_independent_validation": "COMPLETE",
            "provider_master_v2": "COMPLETE",
            "primary_phase2_cohort": "COMPLETE",
            "historical_cohort": "COMPLETE",
            "historical_analyses": "COMPLETE",
            "primary_race_models": "COMPLETE" if final_pass else "IN PROGRESS",
            "primary_gender_models": "COMPLETE" if final_pass else "PENDING",
            "outcome_specific_models": "COMPLETE" if final_pass else "PENDING",
            "directional_dyad_models": "COMPLETE" if final_pass else "PENDING",
            "corrected_primary_ami": "COMPLETE" if final_pass else "PENDING",
            "multiplicity": "COMPLETE" if final_pass else "PENDING",
            "final_analytical_audit": "COMPLETE" if final_pass else "PENDING",
            "final_research_report": "PENDING",
        },
    }
    write_json(output / "current_project_status.json", current_status)

    if args.write_inventory:
        write_inventory(args.repository_root.resolve())

    print(f"Wrote 6 sanitized evidence files to {output}")
    if args.write_inventory:
        print("Updated REPOSITORY_INVENTORY.csv")


if __name__ == "__main__":
    main()
