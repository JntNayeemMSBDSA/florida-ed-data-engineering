# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/36_initialize_report_production_framework.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


PHASE2 = Path(__file__).resolve().parents[1]
WORKSPACE = PHASE2.parents[1]
PHASE1 = WORKSPACE / "outputs" / "florida_ed_full_build_20260724"
REPORT_ROOT = PHASE2 / "reports" / "report_production"
SOURCE_ROOT = REPORT_ROOT / "source"
LEDGER_ROOT = REPORT_ROOT / "ledgers"
QA_ROOT = REPORT_ROOT / "qa"
MANIFEST_ROOT = REPORT_ROOT / "manifest"
REQUEST_COPY = (
    PHASE2
    / "documentation"
    / "Report_Production_Request_20260726.txt"
)

TECHNICAL_SOURCE = SOURCE_ROOT / "Florida_ED_Technical_Project_Dossier_SOURCE.md"
COLLABORATOR_SOURCE = (
    SOURCE_ROOT / "Florida_ED_Collaborator_Project_Report_SOURCE.md"
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def rel(path: Path) -> str:
    return path.resolve().relative_to(WORKSPACE.resolve()).as_posix()


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def atomic_json(path: Path, value: Any) -> None:
    atomic_text(path, json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def atomic_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, path)


def public_class(path: Path) -> tuple[str, str]:
    p = rel(path).lower()
    if "/fact_ed_visits/" in p or "/bridges/" in p:
        return "RESTRICTED_DATA", "NO"
    if "/analysis_data/" in p and path.suffix.lower() in {".parquet", ".csv"}:
        return "INTERNAL_DERIVED_DATA", "NO"
    if "/results/" in p:
        return "AGGREGATE_REVIEW_REQUIRED", "REVIEW_REQUIRED"
    if "/external_sources/" in p:
        return "EXTERNAL_SOURCE_LICENSE_REVIEW", "CITE_BY_DEFAULT"
    if "/scripts/" in p:
        return "CODE_PATH_SCRUB_REQUIRED", "REVIEW_REQUIRED"
    if "/qa/" in p or "/documentation/" in p:
        return "PROJECT_EVIDENCE_REVIEW_REQUIRED", "REVIEW_REQUIRED"
    return "INTERNAL_PROJECT_FILE", "REVIEW_REQUIRED"


def evidence_role(path: Path) -> str:
    p = rel(path).lower()
    name = path.name.lower()
    if "sap" in name or "analysis_plan" in name or "implementation_specification" in name:
        return "analysis_plan"
    if "audit" in name or "/qa/" in p or "validation" in name:
        return "validation_or_audit"
    if "manifest" in name:
        return "provenance_manifest"
    if "/scripts/" in p:
        return "reproducible_code"
    if "/results/" in p:
        return "result_artifact"
    if "/external_sources/" in p:
        return "external_source"
    if "dictionary" in name or "schema" in name or "crosswalk" in name:
        return "data_definition"
    return "project_documentation"


def existing(paths: Iterable[Path]) -> list[Path]:
    return [p for p in paths if p.is_file()]


def source_files() -> list[Path]:
    phase1_explicit = existing(
        [
            PHASE1 / "README.md",
            PHASE1 / "build_manifest_final.json",
            PHASE1 / "build_manifest_prepare.json",
            PHASE1 / "source_snapshots" / "download_manifest.json",
            PHASE1 / "documentation" / "file_manifest_sha256.csv",
            PHASE1 / "documentation" / "fact_field_dictionary.csv",
            PHASE1 / "documentation" / "analytical_table_schema_inventory.csv",
            PHASE1
            / "documentation"
            / "Florida_ED_Standardization_Data_Dictionary.xlsx",
            PHASE1 / "qa" / "qa_summary.json",
            PHASE1 / "qa" / "independent_release_validation.json",
            PHASE1 / "qa" / "quarterly_build_reconciliation.csv",
            PHASE1 / "qa" / "primary_source_inventory.csv",
            PHASE1 / "qa" / "diagnosis_mapping_coverage.csv",
            PHASE1 / "qa" / "procedure_mapping_coverage.csv",
            PHASE1 / "qa" / "charge_reconciliation_by_year.csv",
            PHASE1 / "qa" / "physician_linkage_by_year_role.csv",
            PHASE1 / "dimensions" / "physician_master_qa.json",
            PHASE1 / "dimensions" / "physician_master_schema.json",
        ]
    )

    phase2_docs = [
        p
        for p in (PHASE2 / "documentation").glob("*")
        if p.is_file()
        and p.suffix.lower() in {".md", ".csv", ".json", ".txt"}
    ]
    phase2_qa = [
        p
        for p in (PHASE2 / "qa").glob("*")
        if p.is_file() and p.suffix.lower() in {".md", ".csv", ".json"}
    ]
    phase2_code = [
        p
        for p in (PHASE2 / "scripts").glob("*")
        if p.is_file() and p.suffix.lower() in {".py", ".ps1"}
    ]
    phase2_results = [
        p
        for p in (PHASE2 / "results").rglob("*")
        if p.is_file() and p.suffix.lower() in {".csv", ".json", ".md"}
    ]
    phase2_analysis_manifests = [
        p
        for p in (PHASE2 / "analysis_data").rglob("*manifest*.json")
        if p.is_file() and "_smoke" not in p.as_posix()
    ]
    phase2_external = [
        p
        for p in (PHASE2 / "external_sources").rglob("*")
        if p.is_file()
        and (
            "manifest" in p.name.lower()
            or p.suffix.lower() in {".md", ".txt"}
            or (p.suffix.lower() == ".pdf" and p.stat().st_size <= 25_000_000)
        )
    ]
    audit_history = [
        p
        for p in (PHASE2 / "audit_history").rglob("*")
        if p.is_file() and p.suffix.lower() in {".json", ".csv", ".md"}
    ]

    all_paths = (
        phase1_explicit
        + phase2_docs
        + phase2_qa
        + phase2_code
        + phase2_results
        + phase2_analysis_manifests
        + phase2_external
        + audit_history
    )
    excluded_roots = {REPORT_ROOT.resolve()}
    unique: dict[str, Path] = {}
    for path in all_paths:
        resolved = path.resolve()
        if any(root == resolved or root in resolved.parents for root in excluded_roots):
            continue
        unique[rel(resolved)] = resolved
    return [unique[k] for k in sorted(unique)]


def json_status(path: Path) -> str:
    if path.suffix.lower() != ".json":
        return "NOT_APPLICABLE"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return "UNREADABLE_JSON"
    if isinstance(payload, dict):
        if "status" in payload:
            return str(payload["status"])
        if payload.get("qa_passed") is True:
            return "PASS"
        if payload.get("all_required_checks_passed") is True:
            return "PASS"
    return "NO_TOP_LEVEL_STATUS"


def build_source_manifest(paths: list[Path]) -> dict[str, Any]:
    files = []
    for path in paths:
        safety, github = public_class(path)
        st = path.stat()
        files.append(
            {
                "workspace_relative_path": rel(path),
                "sha256": sha256(path),
                "bytes": st.st_size,
                "modified_utc": datetime.fromtimestamp(
                    st.st_mtime, tz=timezone.utc
                ).isoformat(),
                "evidence_role": evidence_role(path),
                "artifact_status": json_status(path),
                "public_safety_class": safety,
                "github_disposition": github,
            }
        )
    return {
        "manifest_id": "florida_ed_report_source_manifest_v1",
        "created_utc": utc_now(),
        "scope": (
            "Verified project documentation, code, QA, manifests, aggregate results, "
            "and selected external-source records available at the report-outline checkpoint. "
            "Restricted encounter partitions and large provider-level data are referenced by "
            "their validated upstream manifests rather than duplicated here."
        ),
        "path_policy": "All paths are workspace-relative; no absolute local path is report-facing.",
        "public_safety_policy": (
            "No file is publishable solely because it appears in this manifest. "
            "REVIEW_REQUIRED items need final path, credential, identifier, license, "
            "small-cell, and data-use review."
        ),
        "file_count": len(files),
        "files": files,
    }


@dataclass(frozen=True)
class Claim:
    claim_id: str
    reports: str
    section_ids: str
    claim_or_element: str
    claim_type: str
    classification: str
    source_rel: str
    validation_rel: str
    evidence_state: str
    public_disposition: str
    result_gate: str
    notes: str


CLAIMS = [
    Claim(
        "T-P1-001",
        "technical;collaborator",
        "TD-02;TD-03;CR-02",
        "Phase 1 contains 76 reconciled quarters and 148,686,146 unique visit rows.",
        "structural_count",
        "descriptive",
        "outputs/florida_ed_full_build_20260724/build_manifest_final.json",
        "outputs/florida_ed_full_build_20260724/qa/independent_release_validation.json",
        "VERIFIED_STRUCTURAL",
        "PUBLIC_AGGREGATE_AFTER_REVIEW",
        "phase1_release_audit",
        "Use exact counts only with both manifest and independent validation bound.",
    ),
    Claim(
        "T-P1-002",
        "technical;collaborator",
        "TD-02;CR-02;CR-04",
        "Included periods are 2005-2008 and 2010-2024; 2009 and 2025 are excluded.",
        "scope_definition",
        "descriptive",
        "outputs/florida_ed_full_build_20260724/build_manifest_final.json",
        "outputs/florida_ed_full_build_20260724/qa/independent_release_validation.json",
        "VERIFIED_STRUCTURAL",
        "PUBLIC_AFTER_REVIEW",
        "phase1_release_audit",
        "Do not imply that excluded years were imputed.",
    ),
    Claim(
        "T-P2-001",
        "technical;collaborator",
        "TD-03;CR-02",
        "The refreshed 2010-2024 provider-v2 cohort contains 60 validated partitions and 119,543,044 encounter rows.",
        "structural_count",
        "descriptive",
        "outputs/florida_ed_concordance_analysis_20260726/qa/cohort_validation_report.json",
        "outputs/florida_ed_concordance_analysis_20260726/qa/pre_estimation_measurement_gate.json",
        "VERIFIED_STRUCTURAL",
        "PUBLIC_AGGREGATE_AFTER_REVIEW",
        "primary_cohort_gate",
        "This is the complete refreshed encounter universe, not the binary race analysis sample.",
    ),
    Claim(
        "T-PV2-001",
        "technical;collaborator",
        "TD-03;CR-03",
        "Provider master v2 contains one row per NPI and covers every checksum-valid ED-observed selected NPI.",
        "measurement_coverage",
        "measurement_correction",
        "outputs/florida_ed_concordance_analysis_20260726/qa/provider_master_v2_qa.json",
        "outputs/florida_ed_concordance_analysis_20260726/qa/pre_estimation_measurement_gate.json",
        "VERIFIED_STRUCTURAL",
        "PUBLIC_AGGREGATE_AFTER_REVIEW",
        "provider_measurement_gate",
        "Report exact counts from the QA artifact; never expose row-level provider data publicly.",
    ),
    Claim(
        "T-PV2-002",
        "technical;collaborator",
        "TD-03;CR-03",
        "MD/DO, NP, PA, other individuals, and organizational NPIs are distinct; organizational NPIs are never classified as physicians.",
        "classification_rule",
        "measurement_correction",
        "outputs/florida_ed_concordance_analysis_20260726/documentation/Provider_Measurement_V2_SAP_Addendum.md",
        "outputs/florida_ed_concordance_analysis_20260726/qa/pre_estimation_measurement_gate.json",
        "VERIFIED_STRUCTURAL",
        "PUBLIC_AFTER_REVIEW",
        "provider_measurement_gate",
        "Preserve clinician-type distinctions in all coverage tables.",
    ),
    Claim(
        "T-PV2-003",
        "technical",
        "TD-03;TD-06",
        "Old physician-dependent Phase 2 checkpoints were stale and the refreshed cohort was rebuilt from immutable Phase 1 facts.",
        "provenance_correction",
        "measurement_correction",
        "outputs/florida_ed_concordance_analysis_20260726/qa/pre_estimation_measurement_gate.json",
        "outputs/florida_ed_concordance_analysis_20260726/qa/provider_v2_cohort_fact_reconciliation.csv",
        "VERIFIED_STRUCTURAL",
        "PUBLIC_AFTER_REVIEW",
        "provider_measurement_gate",
        "Explain why a join-only refresh was insufficient and what remained immutable.",
    ),
    Claim(
        "T-RACE-001",
        "technical;collaborator",
        "TD-04;CR-06",
        "Physician race is a five-class Bayesian full-name probability proxy using official wru v2.0.0 name likelihoods and no residential geography; it is not BISG or self-reported identity.",
        "measurement_definition",
        "measurement_correction",
        "outputs/florida_ed_concordance_analysis_20260726/qa/provider_race_proxy_v2_qa.json",
        "outputs/florida_ed_concordance_analysis_20260726/qa/pre_estimation_measurement_gate.json",
        "VERIFIED_STRUCTURAL",
        "PUBLIC_AFTER_REVIEW",
        "provider_measurement_gate",
        "Use the exact method ID and retain the algorithm-inferred/probabilistic qualifier.",
    ),
    Claim(
        "T-RACE-002",
        "technical",
        "TD-04",
        "The earlier first-name likelihood table matches the official wru first-name likelihood dictionary to floating-point tolerance, while the earlier posterior table has different conditional semantics.",
        "source_provenance",
        "measurement_correction",
        "outputs/florida_ed_concordance_analysis_20260726/qa/harvard_tables_vs_official_wru_comparison.json",
        "outputs/florida_ed_concordance_analysis_20260726/qa/pre_estimation_measurement_gate.json",
        "VERIFIED_STRUCTURAL",
        "PUBLIC_AFTER_REVIEW",
        "provider_measurement_gate",
        "Do not call either table Harvard-authored without documentary evidence.",
    ),
    Claim(
        "T-RACE-003",
        "technical;collaborator",
        "TD-04;CR-06",
        "The primary physician prior is an AAMC Florida physician distribution; the wru national population prior is a required sensitivity.",
        "measurement_definition",
        "measurement_correction",
        "outputs/florida_ed_concordance_analysis_20260726/qa/provider_race_prior_provenance_checkpoint.json",
        "outputs/florida_ed_concordance_analysis_20260726/qa/provider_race_proxy_v2_qa.json",
        "VERIFIED_STRUCTURAL",
        "PUBLIC_AFTER_REVIEW",
        "provider_measurement_gate",
        "Disclose the AAMC category normalization limitation.",
    ),
    Claim(
        "T-GENDER-001",
        "technical;collaborator",
        "TD-04;CR-06",
        "Primary physician gender uses recorded NPPES/CMS binary categories; SSA name imputation is sensitivity-only.",
        "measurement_definition",
        "measurement_correction",
        "outputs/florida_ed_concordance_analysis_20260726/qa/provider_gender_measurement_checkpoint.json",
        "outputs/florida_ed_concordance_analysis_20260726/qa/pre_estimation_measurement_gate.json",
        "VERIFIED_STRUCTURAL",
        "PUBLIC_AFTER_REVIEW",
        "provider_measurement_gate",
        "Administrative categories are not described as gender identity.",
    ),
    Claim(
        "T-HIST-001",
        "technical;collaborator",
        "TD-03;TD-07;CR-04",
        "The separate 2005-2008 provider-v2 historical cohort retains and reconciles all 23,304,846 Phase 1 encounters across 16 quarters.",
        "structural_count",
        "historical_sensitivity",
        "outputs/florida_ed_concordance_analysis_20260726/analysis_data/historical_provider_v2/historical_provider_v2_build_manifest.json",
        "outputs/florida_ed_concordance_analysis_20260726/qa/independent_historical_results_audit.json",
        "VERIFIED_HISTORICAL_AUDIT",
        "PUBLIC_AGGREGATE_AFTER_REVIEW",
        "historical_independent_audit",
        "Hourly LOS is structurally unavailable and never imputed.",
    ),
    Claim(
        "T-DYAD-001",
        "technical;collaborator",
        "TD-05;CR-09",
        "The frozen directional extension contains 4 gender cells, 25 race cells, and 100 intersectional cells, with sparse cells marked rather than merged.",
        "analysis_plan",
        "secondary_and_exploratory_extension",
        "outputs/florida_ed_concordance_analysis_20260726/qa/directional_dyad_extension_pre_estimation_gate.json",
        "outputs/florida_ed_concordance_analysis_20260726/qa/directional_dyad_definition_unit_tests.json",
        "VERIFIED_STRUCTURAL",
        "PUBLIC_AFTER_REVIEW",
        "directional_pre_estimation_gate",
        "Directional gender/race families are secondary; expanded intersectional family is exploratory.",
    ),
    Claim(
        "T-DYAD-002",
        "technical",
        "TD-03;TD-07",
        "The directional derived base reconciles all 119,543,044 primary-period visits across 60 partitions without filtering or source modification.",
        "structural_count",
        "secondary_and_exploratory_extension",
        "outputs/florida_ed_concordance_analysis_20260726/analysis_data/directional_dyad_base/directional_dyad_base_manifest.json",
        "outputs/florida_ed_concordance_analysis_20260726/qa/independent_directional_dyad_base_audit.json",
        "VERIFIED_STRUCTURAL",
        "PUBLIC_AGGREGATE_AFTER_REVIEW",
        "directional_base_independent_audit",
        "All 60 partitions independently passed exact key, copied-field, eligibility, probability, and provider-type checks.",
    ),
    Claim(
        "T-DYAD-003",
        "technical;collaborator",
        "TD-05;TD-07;CR-09",
        "All 129 frozen directional cells and all 433 planned contrasts pass outcome-independent pre-model support checks.",
        "analysis_plan_support",
        "secondary_and_exploratory_extension",
        "outputs/florida_ed_concordance_analysis_20260726/results/directional_dyads/support/directional_support_manifest.json",
        "outputs/florida_ed_concordance_analysis_20260726/qa/independent_directional_cell_support_audit.json",
        "VERIFIED_STRUCTURAL",
        "PUBLIC_AGGREGATE_AFTER_REVIEW",
        "directional_support_independent_audit",
        "Final estimability still requires outcome-specific support, matrix-rank, cluster, and covariance checks.",
    ),
    Claim(
        "T-DYAD-004",
        "technical",
        "TD-05;TD-07",
        "The directional model coding, covariates, fixed effects, clustering, adjusted-prediction formulas, and reporting restrictions were frozen before real-data estimates were viewed.",
        "analysis_implementation",
        "secondary_and_exploratory_extension",
        "outputs/florida_ed_concordance_analysis_20260726/documentation/Directional_Dyad_Model_Implementation_FROZEN.json",
        "outputs/florida_ed_concordance_analysis_20260726/qa/directional_model_definition_tests.json",
        "VERIFIED_STRUCTURAL",
        "PUBLIC_METHODS_AFTER_REVIEW",
        "directional_model_implementation_gate",
        "The pre-estimation gate authorizes matrix construction but keeps real-data result interpretation closed.",
    ),
    Claim(
        "T-DYAD-005",
        "technical",
        "TD-05;TD-07",
        "The tested storage-safe directional build, independent matrix audit, estimator, independent result audit, multiplicity, and compaction code was hash-frozen before any real directional result file existed.",
        "analysis_implementation",
        "secondary_and_exploratory_extension",
        "outputs/florida_ed_concordance_analysis_20260726/documentation/Directional_Dyad_Execution_Code_FROZEN.json",
        "outputs/florida_ed_concordance_analysis_20260726/qa/directional_execution_code_gate.json",
        "VERIFIED_STRUCTURAL",
        "PUBLIC_METHODS_AFTER_REVIEW",
        "directional_execution_code_gate",
        "The gate remains estimate-blind and does not authorize result interpretation.",
    ),
    Claim(
        "T-DYAD-006",
        "technical;collaborator",
        "TD-04;TD-05;TD-07;CR-06;CR-10",
        "Before any real directional result existed, the five-class race and expanded intersectional execution was extended to include Florida- and national-prior probability models, four hard-confidence thresholds under each prior, and 20 NPI-level imputations under each prior for both frozen primary outcomes.",
        "analysis_implementation",
        "secondary_and_exploratory_extension",
        "outputs/florida_ed_concordance_analysis_20260726/documentation/Directional_Dyad_Execution_Refreeze_History.json",
        "outputs/florida_ed_concordance_analysis_20260726/qa/directional_measurement_sensitivity_tests.json",
        "VERIFIED_STRUCTURAL",
        "PUBLIC_METHODS_AFTER_REVIEW",
        "directional_measurement_sensitivity_audit",
        "The optimized execution passed eight estimate-blind synthetic tests; real-data sensitivity interpretation remains locked until all four independent result audits pass.",
    ),
    Claim(
        "T-HISTORY-001",
        "technical",
        "TD-01",
        "Development history from the 0.5% sample to the complete release.",
        "development_history",
        "mixed",
        "outputs/florida_ed_concordance_analysis_20260726/documentation/Project_Development_History_Source_Index.md",
        "outputs/florida_ed_concordance_analysis_20260726/qa/project_development_history_source_audit.json",
        "VERIFIED_DOCUMENTARY_HISTORY",
        "INTERNAL_SOURCE_PUBLIC_PARAPHRASE_AFTER_REVIEW",
        "source_history_gate",
        "The preserved email archive is hash-bound and internal. It supports design-history and timing statements only, never analytical findings.",
    ),
    Claim(
        "F-PRIMARY-001",
        "technical;collaborator",
        "TD-08;CR-11;CR-12",
        "Primary adjusted outcome estimates and uncertainty.",
        "inferential_result",
        "confirmatory_or_prespecified",
        "",
        "outputs/florida_ed_concordance_analysis_20260726/qa/independent_primary_results_audit.json",
        "PENDING_FINAL_RESULT_AUDIT",
        "PENDING_PUBLIC_SAFETY_REVIEW",
        "all_primary_and_common_postmodel_audits",
        "Do not populate until all primary outcome-specific and common-postmodel audits pass.",
    ),
    Claim(
        "F-DYAD-GENDER-001",
        "technical;collaborator",
        "TD-08;CR-11;CR-12",
        "Directional gender-dyad adjusted predictions and planned contrasts.",
        "inferential_result",
        "secondary",
        "",
        "",
        "PENDING_FINAL_RESULT_AUDIT",
        "PENDING_PUBLIC_SAFETY_REVIEW",
        "directional_gender_independent_audit",
        "Report every cell's support and estimability, CI, raw p, and q.",
    ),
    Claim(
        "F-DYAD-RACE-001",
        "technical;collaborator",
        "TD-08;CR-11;CR-12",
        "Directional race-dyad probability-weighted and multiple-imputation results.",
        "inferential_result",
        "secondary",
        "",
        "",
        "PENDING_FINAL_RESULT_AUDIT",
        "PENDING_PUBLIC_SAFETY_REVIEW",
        "directional_race_independent_audit",
        "Physician race must remain probabilistic and algorithm-inferred.",
    ),
    Claim(
        "F-DYAD-INTERSECTIONAL-001",
        "technical;collaborator",
        "TD-08;CR-11;CR-12",
        "Intersectional directional race-gender adjusted predictions and planned contrasts.",
        "inferential_result",
        "exploratory",
        "",
        "",
        "PENDING_FINAL_RESULT_AUDIT",
        "PENDING_PUBLIC_SAFETY_REVIEW",
        "directional_intersectional_independent_audit",
        "Do not merge sparse cells; mark unstable/non-estimable explicitly.",
    ),
    Claim(
        "F-HIST-RACE-001",
        "technical;collaborator",
        "TD-08;CR-11;CR-13",
        "Historical 2005-2008 race sensitivity findings.",
        "inferential_result",
        "historical_sensitivity",
        "outputs/florida_ed_concordance_analysis_20260726/results/historical_provider_v2_sensitivity/historical_adjusted_race_sensitivities.csv",
        "outputs/florida_ed_concordance_analysis_20260726/qa/independent_historical_results_audit.json",
        "VERIFIED_HISTORICAL_AUDIT",
        "PENDING_PUBLIC_SAFETY_REVIEW",
        "full_project_finalization_gate",
        "Independent historical audit passes, but reporting remains held until the full project gate opens.",
    ),
    Claim(
        "F-HIST-GENDER-001",
        "technical;collaborator",
        "TD-08;CR-11;CR-13",
        "Historical 2005-2008 sex/gender sensitivity findings.",
        "inferential_result",
        "historical_sensitivity",
        "outputs/florida_ed_concordance_analysis_20260726/results/historical_provider_v2_sex_gender_sensitivity/historical_sex_gender_adjusted_interactions.csv",
        "outputs/florida_ed_concordance_analysis_20260726/qa/independent_historical_results_audit.json",
        "VERIFIED_HISTORICAL_AUDIT",
        "PENDING_PUBLIC_SAFETY_REVIEW",
        "full_project_finalization_gate",
        "Independent historical audit passes, but reporting remains held until the full project gate opens.",
    ),
    Claim(
        "F-AMI-001",
        "technical;collaborator",
        "TD-08;CR-11;CR-13",
        "Separate AMI/Greenwood findings, including explicit non-estimability.",
        "inferential_result",
        "separate_analysis",
        "outputs/florida_ed_concordance_analysis_20260726/results/historical_provider_v2_ami/historical_ami_interaction_results.csv",
        "outputs/florida_ed_concordance_analysis_20260726/qa/independent_historical_results_audit.json",
        "VERIFIED_HISTORICAL_AUDIT",
        "PENDING_PUBLIC_SAFETY_REVIEW",
        "full_ami_and_project_finalization_gate",
        "Historical ED-only extension is not an inpatient Greenwood replication.",
    ),
    Claim(
        "F-SENS-001",
        "technical;collaborator",
        "TD-08;CR-13",
        "Robustness across thresholds, priors, multiple imputation, model forms, subsets, and influential-facility refits.",
        "inferential_result",
        "sensitivity",
        "",
        "",
        "PENDING_FINAL_RESULT_AUDIT",
        "PENDING_PUBLIC_SAFETY_REVIEW",
        "all_sensitivity_and_common_postmodel_audits",
        "Include inconsistent and non-robust findings.",
    ),
    Claim(
        "F-CONCLUSION-001",
        "technical;collaborator",
        "TD-10;CR-15;CR-16",
        "Final evidence-supported conclusions, limitations, and next steps.",
        "synthesis",
        "mixed",
        "",
        "",
        "PENDING_FINAL_RESULT_AUDIT",
        "PENDING_PUBLIC_SAFETY_REVIEW",
        "full_analysis_and_report_audits",
        "Association language only; no causal claims.",
    ),
]


def manifest_index(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["workspace_relative_path"]: row for row in manifest["files"]}


def build_claim_rows(source_manifest: dict[str, Any]) -> list[dict[str, Any]]:
    index = manifest_index(source_manifest)
    complete_audit = (
        PHASE2 / "qa" / "complete_analysis_release_audit.json"
    )
    complete_manifest = (
        PHASE2 / "manifest" / "Complete_Analysis_Release_Manifest.json"
    )
    final_result_claim_ids = {
        "F-PRIMARY-001",
        "F-DYAD-GENDER-001",
        "F-DYAD-RACE-001",
        "F-DYAD-INTERSECTIONAL-001",
        "F-HIST-RACE-001",
        "F-HIST-GENDER-001",
        "F-AMI-001",
        "F-SENS-001",
        "F-CONCLUSION-001",
    }
    final_analysis_ready = (
        complete_audit.is_file()
        and complete_manifest.is_file()
        and json_status(complete_audit) == "PASS"
    )
    public_audit = QA_ROOT / "Report_Public_Safety_Audit.json"
    public_ready = (
        public_audit.is_file() and json_status(public_audit) == "PASS"
    )
    rows = []
    for c in CLAIMS:
        source_rel = c.source_rel
        validation_rel = c.validation_rel
        evidence_state = c.evidence_state
        public_disposition = c.public_disposition
        notes = c.notes
        if c.claim_id in final_result_claim_ids and final_analysis_ready:
            source_rel = rel(complete_manifest)
            validation_rel = rel(complete_audit)
            evidence_state = "FINAL_AUDITED"
            public_disposition = (
                "PUBLIC_SAFE_AGGREGATE"
                if public_ready
                else "PENDING_PUBLIC_SAFETY_REVIEW"
            )
            notes = (
                f"{c.notes} Final analytical release is bound through the "
                "complete manifest and independent release audit; exact "
                "reported numbers require the separate number-provenance "
                "ledger."
            )
        source = index.get(source_rel, {}) if source_rel else {}
        validation = index.get(validation_rel, {}) if validation_rel else {}
        rows.append(
            {
                "claim_id": c.claim_id,
                "reports": c.reports,
                "section_ids": c.section_ids,
                "claim_or_element": c.claim_or_element,
                "claim_type": c.claim_type,
                "classification": c.classification,
                "source_artifact": source_rel,
                "source_sha256": source.get("sha256", ""),
                "validation_artifact": validation_rel,
                "validation_sha256": validation.get("sha256", ""),
                "evidence_state": evidence_state,
                "public_disposition": public_disposition,
                "result_gate": c.result_gate,
                "notes": notes,
            }
        )
    return rows


ISSUES = [
    ("ISS-001", "Incorrect or incomplete source selection"),
    ("ISS-002", "NPPES file-selection issue"),
    ("ISS-003", "Provider coverage gaps and Phase 1 inner-join selection"),
    ("ISS-004", "Stale physician-dependent Phase 2 checkpoints"),
    ("ISS-005", "Updated CMS source integration"),
    ("ISS-006", "DuckDB compatibility and Boolean aggregation"),
    ("ISS-007", "ICD-9/ICD-10 transition handling"),
    ("ISS-008", "Python environment and dependency-path failures"),
    ("ISS-009", "Memory limits, orphaned workers, and overlapping processes"),
    ("ISS-010", "HDFE convergence and numerical tolerances"),
    ("ISS-011", "Windows memory retention and isolated model workers"),
    ("ISS-012", "Non-finite inference and explicit non-estimability"),
    ("ISS-013", "Stale checkpoint and provenance risks"),
    ("ISS-014", "Other material failures discovered during final audit"),
    (
        "ISS-015",
        "Directional five-class measurement-sensitivity execution gap",
    ),
    (
        "ISS-016",
        "Common-primary race M2 strict HDFE nonconvergence",
    ),
]


def build_issue_rows() -> list[dict[str, str]]:
    complete_audit_path = PHASE2 / "qa" / "complete_analysis_release_audit.json"
    analytically_release_ready = (
        complete_audit_path.is_file()
        and json_status(complete_audit_path) == "PASS"
    )
    known = {
        "ISS-001": (
            "documentation/Project_Development_History_Source_Index.md;"
            "reports/report_production/ledgers/Report_Source_Manifest.json;"
            "../florida_ed_full_build_20260724/build_manifest_final.json"
        ),
        "ISS-002": (
            "scripts/04a_build_provider_master_v2.py;"
            "qa/provider_master_v2_source_manifest.json;"
            "qa/provider_master_v2_qa.json"
        ),
        "ISS-003": (
            "qa/pre_estimation_measurement_gate.json;"
            "qa/provider_v2_cohort_fact_reconciliation.csv"
        ),
        "ISS-004": (
            "qa/pre_estimation_measurement_gate.json;"
            "qa/superseded_phase2_provider_partitions.csv"
        ),
        "ISS-005": (
            "qa/provider_master_v2_source_manifest.json;"
            "documentation/Provider_Measurement_V2_SAP_Addendum.md"
        ),
        "ISS-006": (
            "qa/run_logs/20260726_150759_17_historical_sensitivity_analysis.log;"
            "scripts/17_historical_sensitivity_analysis.py;"
            "qa/independent_historical_results_audit.json"
        ),
        "ISS-007": (
            "../florida_ed_full_build_20260724/build_manifest_final.json;"
            "../florida_ed_full_build_20260724/qa/qa_summary.json"
        ),
        "ISS-008": (
            "scripts/RUN_PHASE2_REMAINING_SAFE.ps1;"
            "scripts/RUN_HISTORICAL_PROVIDER_V2.ps1;"
            "scripts/22_capture_environment.py"
        ),
        "ISS-009": (
            "documentation/LIVE_PHASE2_EXECUTION_CHECKPOINT.md;"
            "qa/run_logs/20260726_223427_RECOVERY_PARENT_STDOUT.log;"
            "scripts/RUN_POST_CANONICAL_ANALYSIS_SAFE.ps1"
        ),
        "ISS-010": (
            "qa/hdfe_engine_validation.json;"
            "qa/historical_provider_v2_race_model_diagnostics.csv"
        ),
        "ISS-011": (
            "scripts/run_historical_sensitivity_isolated.py;"
            "documentation/SAP_deviation_log.csv"
        ),
        "ISS-012": (
            "qa/independent_historical_results_audit.json;"
            "audit_history/historical_ami_nonestimable_fix_20260726T220036Z/"
            "ARCHIVE_MANIFEST.json"
        ),
        "ISS-013": (
            "qa/directional_dyad_extension_pre_estimation_gate.json;"
            "documentation/SAP_deviation_log.csv"
        ),
        "ISS-014": (
            "qa/run_logs/20260726_200745_10_ami_validation_and_analysis.log;"
            "audit_history/ami_pre_const_fix_20260726T0038Z/ARCHIVE_MANIFEST.json;"
            "scripts/45_independent_primary_ami_results_audit.py;"
            "audit_history/multiplicity_schema_alias_20260727T0736Z/"
            "ARCHIVE_MANIFEST.json;"
            "audit_history/complete_release_sap_gate_20260727T0804Z/"
            "ARCHIVE_MANIFEST.json;"
            "documentation/Directional_Dyad_Execution_Refreeze_History.json"
        ),
        "ISS-015": (
            "documentation/Directional_Dyad_Execution_Refreeze_History.json;"
            "qa/directional_measurement_sensitivity_tests.json;"
            "documentation/Directional_Dyad_Execution_Code_FROZEN.json"
        ),
        "ISS-016": (
            "documentation/SAP_deviation_log.csv;"
            "qa/demeaning_failure_checkpoints/common_primary_race_m2.json;"
            "qa/demeaning_fallback_unit_tests.json;"
            "qa/demeaning_policy_audit_unit_tests.json;"
            "audit_history/common_primary_race_m2_strict_nonconvergence_"
            "20260727T0221Z/ARCHIVE_MANIFEST.json"
        ),
    }
    details = {
        "ISS-001": {
            "chronology_date_utc": "2026-07-24T00:00:00+00:00",
            "what_happened": (
                "Early project development used an incompletely documented "
                "selection of locally available dictionary and reference files. "
                "The exact first mistaken selection event is not fully "
                "reconstructable from the retained logs."
            ),
            "detection": (
                "The later full-build inventory compared every retained source, "
                "mapping, manifest, and build dependency and exposed gaps in the "
                "early documentary chain."
            ),
            "potentially_affected_artifacts": (
                "Early sample-era decoding and enhancement drafts; no final "
                "Phase 1 or provider-v2 release artifact is accepted on that "
                "documentary basis alone."
            ),
            "scientific_or_computational_importance": (
                "Unrecorded source selection can make otherwise correct "
                "transformations impossible to reproduce or independently verify."
            ),
            "correction": (
                "Replace implicit file choice with enumerated, versioned, "
                "hash-bound source manifests and explicit mapping provenance."
            ),
            "rebuilt_or_rerun": (
                "The complete Phase 1 build and all provider-v2-dependent Phase 2 "
                "cohorts were built under the manifest-controlled source chain."
            ),
            "preserved_artifacts": (
                "Early analysis files remain as context, while the source index "
                "honestly records that the exact initial selection failure cannot "
                "be reconstructed."
            ),
            "recurrence_prevention": (
                "Release audits now require source-manifest membership, hashes, "
                "and provenance for every citable analytical dependency."
            ),
        },
        "ISS-002": {
            "chronology_date_utc": "2026-07-26T03:31:11+00:00",
            "what_happened": (
                "Raw NPPES archives can contain similarly named data and "
                "file-header CSVs. An early provider-v2 attempt did not yet have "
                "a sufficiently explicit file-selection safeguard; the exact "
                "first failure body was not retained."
            ),
            "detection": (
                "Provider-master review inspected the NPPES archive candidate "
                "set and the selected file's schema before the validated rebuild."
            ),
            "potentially_affected_artifacts": (
                "The preliminary provider-master v2 attempt and any provider "
                "attributes derived before candidate filtering was corrected."
            ),
            "scientific_or_computational_importance": (
                "Selecting a file-header record rather than the full NPI data "
                "file could destroy coverage and invalidate provider linkage."
            ),
            "correction": (
                "Restrict selection to npidata_pfile CSV candidates, explicitly "
                "exclude names containing fileheader, validate schema, and bind "
                "the selected source in the provider manifest."
            ),
            "rebuilt_or_rerun": (
                "Provider master v2, provider race proxy v2, provider coverage, "
                "and every dependent primary and historical cohort."
            ),
            "preserved_artifacts": (
                "Raw NPPES source files and manual build logs were retained; the "
                "missing first failure body is documented as a limitation."
            ),
            "recurrence_prevention": (
                "Candidate-name filtering, schema checks, one-row-per-NPI QA, "
                "coverage reconciliation, and a selected-source SHA-256."
            ),
        },
        "ISS-003": {
            "chronology_date_utc": "2026-07-26T18:16:37.091818+00:00",
            "what_happened": (
                "The pre-amendment Phase 2 cohort builder inner-joined the "
                "Phase 1 physician master and required its match and MD/DO "
                "flags before inclusion. Phase 1 surname-race and gender "
                "fields also affected concordance eligibility."
            ),
            "detection": (
                "Estimate-blind provider-v2 review compared every selected "
                "ED NPI with the Phase 1 master and audited the old builder's "
                "row-inclusion logic."
            ),
            "potentially_affected_artifacts": (
                "All pre-amendment physician-dependent Phase 2 cohorts and "
                "provider-linked descriptive checkpoints."
            ),
            "scientific_or_computational_importance": (
                "Provider linkage was a selection rule, so merely replacing "
                "attributes could not restore encounters excluded from the "
                "old cohort."
            ),
            "correction": (
                "Build provider master v2 over the complete ED-observed NPI "
                "universe and rebuild the primary cohort directly from the "
                "immutable Phase 1 facts and bridges."
            ),
            "rebuilt_or_rerun": (
                "All 60 primary-period provider-v2 cohort partitions, "
                "coverage tables, and provider/cohort measurement gates."
            ),
            "preserved_artifacts": (
                "The immutable Phase 1 release and the old Phase 2 partitions "
                "were preserved; old partitions were explicitly superseded."
            ),
            "recurrence_prevention": (
                "Independent fact-to-cohort key/count reconciliation and a "
                "fail-closed rule prohibit estimation from stale partitions."
            ),
        },
        "ISS-004": {
            "chronology_date_utc": "2026-07-26T18:16:37.091818+00:00",
            "what_happened": (
                "Physician-dependent Phase 2 checkpoints contained Phase 1 "
                "provider attributes, eligibility decisions, and derived "
                "concordance fields, making them stale after provider v2."
            ),
            "detection": (
                "A field and row-inclusion audit traced provider dependencies "
                "in the completed pre-v2 partitions."
            ),
            "potentially_affected_artifacts": (
                "Forty-two previously successful Phase 2 partitions and every "
                "downstream physician-dependent checkpoint derived from them."
            ),
            "scientific_or_computational_importance": (
                "Reusing stale partitions could mix incompatible provider "
                "definitions and preserve encounters lost through old filters."
            ),
            "correction": (
                "Mark old partitions superseded and reconstruct the complete "
                "60-partition primary cohort from immutable Phase 1 inputs."
            ),
            "rebuilt_or_rerun": (
                "Primary provider-v2 cohort, provider fields, eligibility "
                "flags, race probabilities, gender fields, and validations."
            ),
            "preserved_artifacts": (
                "The old successful partitions remain available only as "
                "audited comparators."
            ),
            "recurrence_prevention": (
                "Partition manifests bind provider, race, gender, source, and "
                "cohort versions; downstream gates reject superseded inputs."
            ),
        },
        "ISS-005": {
            "chronology_date_utc": "2026-07-26T11:59:00+00:00",
            "what_happened": (
                "The first provider-v2 draft inherited legacy CMS clinician "
                "attributes and did not directly integrate the newer official "
                "CMS facility-affiliation file."
            ),
            "detection": (
                "Estimate-blind comparison of legacy provider coverage with "
                "the CMS Doctors and Clinicians files modified June 26, 2026."
            ),
            "potentially_affected_artifacts": (
                "Provider specialty, education, group-practice, facility-"
                "affiliation, and recorded CMS-gender fields."
            ),
            "scientific_or_computational_importance": (
                "Stale or missing provider attributes reduce coverage and can "
                "misstate measurement completeness and adjustment variables."
            ),
            "correction": (
                "Refresh from current official CMS national clinician and "
                "facility-affiliation files, retain legacy fields alongside "
                "explicit v2 fields, and hash both large sources."
            ),
            "rebuilt_or_rerun": (
                "Provider master v2, physician-race proxy, all 60 provider-v2 "
                "cohort partitions, coverage summaries, and measurement gates."
            ),
            "preserved_artifacts": (
                "Legacy Phase 1 CMS attributes and the pre-current-CMS "
                "provider-v2 build were preserved for comparison."
            ),
            "recurrence_prevention": (
                "Current source version, modification date, file size, and "
                "SHA-256 are required in the provider source manifest."
            ),
        },
        "ISS-006": {
            "chronology_date_utc": "2026-07-26T19:07:59.899558+00:00",
            "what_happened": (
                "DuckDB rejected avg(BOOLEAN) while creating historical "
                "descriptive summaries for any_procedure_flag."
            ),
            "detection": (
                "The historical sensitivity runner stopped with a preserved "
                "BinderException before result interpretation."
            ),
            "potentially_affected_artifacts": (
                "Historical descriptive summaries and the downstream historical "
                "race sensitivity sequence in that failed run."
            ),
            "scientific_or_computational_importance": (
                "Database-version-specific aggregation rules can halt a build or "
                "silently encourage inconsistent manual workarounds."
            ),
            "correction": (
                "Cast every summarized outcome, including Boolean indicators, to "
                "DOUBLE inside the aggregate expressions."
            ),
            "rebuilt_or_rerun": (
                "Historical descriptive summaries and all dependent race "
                "sensitivity models and audits."
            ),
            "preserved_artifacts": (
                "The original failing log and the corrected executable script."
            ),
            "recurrence_prevention": (
                "Typed aggregate expressions and the independent historical "
                "result audit are required in the release gate."
            ),
        },
        "ISS-007": {
            "chronology_date_utc": "2026-07-26T10:20:00+00:00",
            "what_happened": (
                "An AMI source-benchmark summary initially selected one ICD "
                "system for all of 2015, although the model cohort itself used "
                "correct row-level quarter-specific code-system flags."
            ),
            "detection": (
                "Estimate-blind static review reconciled annual validation "
                "counts to the frozen ICD transition rule."
            ),
            "potentially_affected_artifacts": (
                "The AMI annual source-side validation benchmark for 2015; "
                "not the row-level model cohort."
            ),
            "scientific_or_computational_importance": (
                "Using one code system for the transition year understates or "
                "misclassifies the source benchmark and weakens validation."
            ),
            "correction": (
                "Aggregate 2015 from ICD-9-CM counts in Q1-Q3 and ICD-10-CM "
                "counts in Q4."
            ),
            "rebuilt_or_rerun": (
                "AMI validation counts and checks; model definitions and rows "
                "were unchanged."
            ),
            "preserved_artifacts": (
                "The frozen transition rule and row-level cohort flags."
            ),
            "recurrence_prevention": (
                "Quarter-specific transition checks are explicit in AMI and "
                "Phase 1 QA."
            ),
        },
        "ISS-008": {
            "chronology_date_utc": "2026-07-26T03:00:00+00:00",
            "what_happened": (
                "Some early invocations did not consistently resolve the local "
                "Python dependency bundle. The exact first import traceback is "
                "not present in the retained logs."
            ),
            "detection": (
                "Execution review found that successful runs depended on the "
                "project-local pydeps directory being placed on PYTHONPATH."
            ),
            "potentially_affected_artifacts": (
                "Only incomplete early invocations; accepted outputs were "
                "regenerated under runners that set the same dependency path."
            ),
            "scientific_or_computational_importance": (
                "An implicit environment can make identical code fail or import "
                "different library versions across machines."
            ),
            "correction": (
                "Every canonical PowerShell runner sets PYTHONPATH to the "
                "project-local pydeps directory; Python entry points use that "
                "resolved environment and the environment capture inventories it."
            ),
            "rebuilt_or_rerun": (
                "All accepted provider, cohort, historical, primary, and "
                "directional stages were or will be executed by canonical runners."
            ),
            "preserved_artifacts": (
                "Runner scripts, local dependency tree, and retained successful "
                "execution logs; the missing first traceback remains disclosed."
            ),
            "recurrence_prevention": (
                "Centralized runner initialization, environment capture, and "
                "release-time script and package inventories."
            ),
        },
        "ISS-009": {
            "chronology_date_utc": "2026-07-26T22:34:27+00:00",
            "what_happened": (
                "A long-running analytical session outlived an application/server "
                "timeout. Detached workers and large memory-mapped computations "
                "therefore required explicit liveness and overlap checks before "
                "recovery."
            ),
            "detection": (
                "Process, log, checkpoint, result-file, and CPU/working-set "
                "inspection showed which canonical worker was still active and "
                "which prior orchestration state was stale."
            ),
            "potentially_affected_artifacts": (
                "Common-primary estimation and any downstream stage that could "
                "have been duplicated by an unsafe restart."
            ),
            "scientific_or_computational_importance": (
                "Overlapping writers can corrupt checkpoints, duplicate expensive "
                "work, or make result provenance ambiguous."
            ),
            "correction": (
                "Retain a single canonical estimator, forbid competing real-data "
                "workers, and attach a fail-closed supervisor that waits for a "
                "fresh successful parent completion marker."
            ),
            "rebuilt_or_rerun": (
                "The interrupted common-primary sequence resumed from its "
                "persisted checkpoint; no completed scientific stage was "
                "unnecessarily rebuilt."
            ),
            "preserved_artifacts": (
                "Recovery logs, process identifiers, strict-failure archive, "
                "restart state, and the live operational checkpoint."
            ),
            "recurrence_prevention": (
                "Single-writer process checks, atomic state, fresh completion "
                "markers, fail-closed downstream queuing, and no-overlap rules."
            ),
        },
        "ISS-010": {
            "chronology_date_utc": "2026-07-26T19:02:00+00:00",
            "what_happened": (
                "Fifteen required historical M3 HDFE models reached the strict "
                "1e-8, 10,000-iteration demeaning ceiling."
            ),
            "detection": (
                "The historical isolated workers raised explicit numerical "
                "nonconvergence before interpretation."
            ),
            "potentially_affected_artifacts": (
                "Historical race, sex/gender, and AMI models using physician "
                "plus facility-year-quarter fixed effects."
            ),
            "scientific_or_computational_importance": (
                "Silently accepting unfinished residualization or dropping "
                "models would invalidate comparisons and completeness."
            ),
            "correction": (
                "Persist the strict failure, then retry the identical sample, "
                "formula, fixed effects, clustering, and contrast at 1e-6 with "
                "a 50,000-iteration ceiling."
            ),
            "rebuilt_or_rerun": (
                "Only strict-failed historical models were retried; all "
                "diagnostics and fallback provenance were saved."
            ),
            "preserved_artifacts": (
                "Strict-attempt diagnostics, original samples, formulas, and "
                "all converged strict models."
            ),
            "recurrence_prevention": (
                "Strict-before-fallback policy, model diagnostics, isolated "
                "workers, and independent result audit."
            ),
        },
        "ISS-011": {
            "chronology_date_utc": "2026-07-26T19:02:00+00:00",
            "what_happened": (
                "Repeated large HDFE fits on Windows did not reliably return "
                "all native-library memory to the long-lived parent process "
                "between models."
            ),
            "detection": (
                "Process-level memory observation during the historical model "
                "sequence showed retained working memory after completed fits."
            ),
            "potentially_affected_artifacts": (
                "Later historical race and sex/gender HDFE models if the parent "
                "process exhausted available memory before completing the grid."
            ),
            "scientific_or_computational_importance": (
                "Resource exhaustion can produce incomplete model families and "
                "selective availability that is mistaken for scientific "
                "non-estimability."
            ),
            "correction": (
                "Fit one historical HDFE model per operating-system-isolated "
                "worker process, validate and save its result, then allow process "
                "exit to release memory before starting the next model."
            ),
            "rebuilt_or_rerun": (
                "Historical race and sex/gender sensitivity sequences were "
                "executed through isolated workers; completed results were reused "
                "only after hash and diagnostic validation."
            ),
            "preserved_artifacts": (
                "Per-model inputs, job specifications, diagnostics, results, and "
                "the orchestration manifests."
            ),
            "recurrence_prevention": (
                "Isolated-worker execution, per-model completion checks, "
                "idempotent reuse, and independent aggregate result audits."
            ),
        },
        "ISS-012": {
            "chronology_date_utc": "2026-07-26T22:00:36.988157+00:00",
            "what_happened": (
                "Six historical AMI any-procedure cells had no outcome "
                "variation, so inferential quantities were undefined; the "
                "first independent audit rejected zero-like outputs."
            ),
            "detection": (
                "Independent result-diagnostic reconciliation found non-finite "
                "p-values and invalid zero estimate/standard-error substitution."
            ),
            "potentially_affected_artifacts": (
                "Six historical AMI outcome-by-specification cells and the "
                "initial historical audit."
            ),
            "scientific_or_computational_importance": (
                "A constant outcome cannot identify an association; reporting "
                "zero inference would falsely imply precision."
            ),
            "correction": (
                "Add a pre-fit variation gate and retain the cells as explicit "
                "NON_ESTIMABLE rows with missing inferential quantities."
            ),
            "rebuilt_or_rerun": (
                "Historical AMI results, diagnostics, manifest, multiplicity, "
                "and the independent historical audit."
            ),
            "preserved_artifacts": (
                "The failed audit and pre-correction results were archived "
                "with a checksum manifest."
            ),
            "recurrence_prevention": (
                "All AMI grids now require outcome-variation checks and exact "
                "result-diagnostic alignment."
            ),
        },
        "ISS-013": {
            "chronology_date_utc": "2026-07-27T01:08:09.153585+00:00",
            "what_happened": (
                "Repeated estimate-blind directional execution refinements "
                "atomically replaced the canonical freeze manifest; two "
                "intermediate JSON bodies had not been copied before replacement."
            ),
            "detection": (
                "Provenance review compared the freeze sequence, retained "
                "hashes, execution logs, and result-file timing."
            ),
            "potentially_affected_artifacts": (
                "Historical reconstruction of two superseded directional "
                "execution-code manifests, not the current frozen specification."
            ),
            "scientific_or_computational_importance": (
                "Incomplete freeze history can obscure when implementation "
                "changes occurred relative to result generation."
            ),
            "correction": (
                "Create an explicit refreeze-history artifact preserving the "
                "known sequence, hashes, timestamps where available, scope, "
                "supersession reasons, and the limitation."
            ),
            "rebuilt_or_rerun": (
                "Current execution freeze and estimate-blind synthetic tests "
                "were regenerated; no scientific cells or estimands changed."
            ),
            "preserved_artifacts": (
                "Known superseded hashes and execution-log timing; the missing "
                "intermediate bodies are not claimed to be reconstructable."
            ),
            "recurrence_prevention": (
                "Future refreezes must append history and bind the current "
                "manifest, tests, and real-result-file count."
            ),
        },
        "ISS-014": {
            "chronology_date_utc": "2026-07-27T00:07:45.206731+00:00",
            "what_happened": (
                "The first primary AMI extension run attempted to convert a "
                "nullable principal-physician indicator containing NaN directly "
                "to Boolean and stopped with a ValueError. Later static header "
                "review also found that the audited historical AMI file names "
                "its cohort field cohort_definition while the multiplicity "
                "script expected definition. A subsequent estimate-blind "
                "release preflight found that the complete release audit still "
                "required SAP history only through DEV-016 after DEV-017 had "
                "already been documented."
            ),
            "detection": (
                "The canonical runner failed closed and preserved the complete "
                "traceback before any corrected AMI estimate was accepted. "
                "Header-only and registry-only static preflights found the two "
                "later defects before their affected stages ran."
            ),
            "potentially_affected_artifacts": (
                "Primary-period ED-only AMI cohort preparation and all primary "
                "AMI estimates in that failed run; historical AMI multiplicity "
                "output would also have stopped before writing; the final "
                "release audit would have produced a false failure despite a "
                "complete contiguous deviation history."
            ),
            "scientific_or_computational_importance": (
                "Implicit missing-to-Boolean conversion could create an "
                "unreviewed inclusion rule for physician attribution. The "
                "schema mismatch would prevent multiplicity output, and an "
                "incomplete deviation registry would break the final provenance "
                "gate even when the scientific release was otherwise valid."
            ),
            "correction": (
                "Handle nullable principal indicators explicitly, rerun the "
                "primary AMI extension after canonical primary completion, and "
                "require exact result/diagnostic reconciliation. Accept the "
                "audited historical field name as a schema alias without "
                "changing family membership, and refresh estimate-blind code "
                "bindings before directional execution. Require the complete "
                "DEV-001 through DEV-018 sequence in the release audit and "
                "expose that expectation to a synthetic unit test."
            ),
            "rebuilt_or_rerun": (
                "The primary AMI analysis is queued for a corrected rerun, "
                "multiplicity refresh, and an independent dedicated audit. The "
                "complete-release unit tests were rerun and pass 8/8."
            ),
            "preserved_artifacts": (
                "The original failing log and pre-correction state are retained "
                "under audit_history. The exact pre-alias multiplicity script "
                "and superseded directional bindings are checksum-archived. "
                "The pre-DEV018 release-audit script and SAP ledger are also "
                "checksum-archived."
            ),
            "recurrence_prevention": (
                "Explicit null policy, required estimability grid, 24 estimable "
                "plus 6 non-estimable cell expectation, input-schema assertion, "
                "synthetic revalidation, independent AMI/multiplicity audits, "
                "and a unit-tested contiguous SAP-history constant."
            ),
        },
        "ISS-015": {
            "chronology_date_utc": "2026-07-27T01:08:09.153585+00:00",
            "what_happened": (
                "The first storage-safe directional runner implemented only "
                "the primary probability-weighted path even though the frozen "
                "plan also required alternative priors, thresholds, and NPI-"
                "level multiple imputation."
            ),
            "detection": (
                "Estimate-blind execution-coverage review compared the frozen "
                "scientific manifest with every callable runner stage."
            ),
            "potentially_affected_artifacts": (
                "Future five-class race and intersectional measurement-"
                "sensitivity outputs; no real directional result yet existed."
            ),
            "scientific_or_computational_importance": (
                "Omitting uncertainty analyses would overstate confidence in "
                "algorithm-inferred physician race."
            ),
            "correction": (
                "Add Florida/national-prior probability models, four hard "
                "thresholds under each prior, and 20 deterministic NPI-level "
                "imputations per prior for both primary outcomes."
            ),
            "rebuilt_or_rerun": (
                "Synthetic measurement tests, execution freeze, independent "
                "measurement audits, and pre-compaction locks."
            ),
            "preserved_artifacts": (
                "Superseded freeze hashes and timing history."
            ),
            "recurrence_prevention": (
                "Eight synthetic measurement tests and four mandatory real-"
                "data sensitivity audit sets are required before compaction."
            ),
        },
        "ISS-016": {
            "chronology_date_utc": "2026-07-27T02:21:01.0584176+00:00",
            "what_happened": (
                "The 58,678,714-row common-primary race M2 model stopped after "
                "the first design block failed strict fixed-effect demeaning at "
                "1e-8 and 10,000 iterations. No M2 result was written."
            ),
            "detection": (
                "The estimator failed closed and the traceback, engine hash, "
                "matrix binding, and failed block were archived."
            ),
            "potentially_affected_artifacts": (
                "Common-primary race M2 and downstream common-primary models; "
                "the existing M1 file was not interpreted."
            ),
            "scientific_or_computational_importance": (
                "Proceeding without proven convergence could contaminate every "
                "coefficient and covariance derived from the residualized block."
            ),
            "correction": (
                "Require strict 1e-8/10,000 for every new block; only after a "
                "persisted strict failure retry the identical block at "
                "1e-6/50,000. Reuse the hash-bound first failure rather than "
                "repeat it."
            ),
            "rebuilt_or_rerun": (
                "The M2 scratch state resumed blockwise with persisted attempt "
                "provenance; downstream computation remained queued."
            ),
            "preserved_artifacts": (
                "Failed logs, traceback, pre-patch engine hash, matrix "
                "manifest, M1 output, and every strict/fallback attempt."
            ),
            "recurrence_prevention": (
                "Six fallback/restart unit tests, independent policy tests, "
                "attempt-grid audits, and pre-compaction provenance checks."
            ),
        },
    }
    rows = []
    for issue_id, title in ISSUES:
        detail = details.get(issue_id, {})
        rows.append(
            {
                "issue_id": issue_id,
                "chronology_date_utc": detail.get("chronology_date_utc", ""),
                "issue_title": title,
                "what_happened": detail.get("what_happened", ""),
                "detection": detail.get("detection", ""),
                "potentially_affected_artifacts": detail.get(
                    "potentially_affected_artifacts", ""
                ),
                "scientific_or_computational_importance": detail.get(
                    "scientific_or_computational_importance", ""
                ),
                "correction": detail.get("correction", ""),
                "rebuilt_or_rerun": detail.get("rebuilt_or_rerun", ""),
                "preserved_artifacts": detail.get("preserved_artifacts", ""),
                "recurrence_prevention": detail.get(
                    "recurrence_prevention", ""
                ),
                "validation_evidence_candidates": known.get(issue_id, ""),
                "evidence_status": (
                    "SOURCE_COMPLETE_PENDING_REPORT_AUDIT"
                    if issue_id in details
                    else (
                        "SOURCE_CANDIDATES_IDENTIFIED"
                        if issue_id in known
                        else "PENDING_SOURCE_RECONSTRUCTION"
                    )
                ),
                "final_report_ready": (
                    "YES" if analytically_release_ready else "NO"
                ),
            }
        )
    rows.sort(
        key=lambda row: (
            row["chronology_date_utc"] or "9999-12-31T23:59:59+00:00",
            row["issue_id"],
        )
    )
    return rows


EXHIBITS = [
    ("FIG-T1", "technical", "TD-02", "Source-to-report provenance and hash-binding chain", "diagram", "VERIFIED_STRUCTURAL", "report_source_manifest"),
    ("FIG-T2", "technical", "TD-03", "Cohort construction and attrition", "flow", "PENDING_FINAL_COHORT_TABLE", "all_cohort_gates"),
    ("FIG-T3", "technical", "TD-07", "Fail-closed analytical and documentation gate sequence", "flow", "VERIFIED_STRUCTURAL", "report_finalization_gate"),
    ("FIG-T4", "technical", "TD-09", "End-to-end reproducibility workflow", "flow", "PENDING_FINAL_SCRIPT_INVENTORY", "final_release_audit"),
    ("TAB-T1", "technical", "TD-01", "Dated design and measurement decision history", "table", "PENDING_DECISION_LEDGER", "sap_and_deviation_hashes"),
    ("TAB-T2", "technical", "TD-02", "External-source provenance and permissible use", "table", "PENDING_LICENSE_REVIEW", "source_manifest_and_license_review"),
    ("TAB-T3", "technical", "TD-03", "Partition and row-count reconciliation", "table", "VERIFIED_STRUCTURAL", "phase1_primary_historical_gates"),
    ("TAB-T4", "technical", "TD-06", "Chronological issue and resolution log", "table", "PENDING_ISSUE_LEDGER_COMPLETION", "report_issue_audit"),
    ("FIG-C1", "collaborator", "CR-02", "Timeline of included primary and historical data", "timeline", "VERIFIED_STRUCTURAL", "phase1_release_audit"),
    ("FIG-C2", "collaborator", "CR-03", "Encounter-to-facility-to-clinician linkage", "diagram", "VERIFIED_STRUCTURAL_PUBLIC_REVIEW_PENDING", "provider_measurement_gate"),
    ("FIG-C3", "collaborator", "CR-06", "Physician measurement sources and sensitivity paths", "diagram", "VERIFIED_STRUCTURAL_PUBLIC_REVIEW_PENDING", "measurement_gate"),
    ("FIG-C4", "collaborator", "CR-08", "From raw differences to adjusted comparisons", "diagram", "VERIFIED_SPECIFICATION", "final_model_audit"),
    ("FIG-C5", "collaborator", "CR-09", "Directional dyad analysis grid", "matrix", "VERIFIED_STRUCTURAL", "directional_support_audit"),
    ("FIG-C6", "collaborator", "CR-10", "Quality gates from sources to final report", "flow", "VERIFIED_STRUCTURAL", "report_finalization_gate"),
    ("FIG-C7", "collaborator", "CR-12", "Adjusted estimates and 95% confidence intervals", "forest_plot", "PENDING_FINAL_RESULT_AUDIT", "all_result_audits"),
    ("FIG-C8", "collaborator", "CR-13", "Robustness across key sensitivity analyses", "specification_plot", "PENDING_FINAL_RESULT_AUDIT", "all_sensitivity_audits"),
    ("TAB-C1", "collaborator", "CR-04", "Measures comparable across primary and historical periods", "table", "VERIFIED_STRUCTURAL", "historical_comparability_gate"),
]


EXHIBIT_DETAILS = {
    "FIG-T1": {
        "analytical_question": (
            "How does each reported claim trace from source data through "
            "validated transformations, frozen specifications, results, and "
            "report evidence?"
        ),
        "planned_source_artifacts": (
            "reports/report_production/ledgers/Report_Source_Manifest.json;"
            "outputs/florida_ed_full_build_20260724/build_manifest_final.json;"
            "qa/pre_estimation_measurement_gate.json;"
            "documentation/Directional_Dyad_Execution_Code_FROZEN.json"
        ),
        "planned_claim_ids": "T-P1-001;T-PV2-001;T-DYAD-005",
        "notes": "Diagram only; no encounter-level values.",
    },
    "FIG-T2": {
        "analytical_question": (
            "Which encounter universes enter the primary and historical "
            "tracks, and where do measurement and outcome eligibility apply?"
        ),
        "planned_source_artifacts": (
            "outputs/florida_ed_full_build_20260724/qa/qa_summary.json;"
            "qa/cohort_validation_report.json;"
            "analysis_data/historical_provider_v2/"
            "historical_provider_v2_build_manifest.json"
        ),
        "planned_claim_ids": "T-P1-001;T-P2-001;T-HIST-001",
        "notes": (
            "Show retained encounter universes separately from analytic "
            "eligibility; do not imply that provider linkage removed Phase 1 "
            "facts."
        ),
    },
    "FIG-T3": {
        "analytical_question": (
            "Which fail-closed gates must pass before estimate interpretation "
            "and report finalization?"
        ),
        "planned_source_artifacts": (
            "reports/report_production/qa/Report_Finalization_Gate.json;"
            "scripts/49_complete_analysis_release_audit.py"
        ),
        "planned_claim_ids": "T-DYAD-004;T-DYAD-005;F-CONCLUSION-001",
        "notes": "Update only after the complete analysis release audit runs.",
    },
    "FIG-T4": {
        "analytical_question": (
            "What exact execution and verification sequence reproduces the "
            "released analysis and reports?"
        ),
        "planned_source_artifacts": (
            "scripts/RUN_PHASE2_REMAINING_SAFE.ps1;"
            "scripts/RUN_POST_CANONICAL_ANALYSIS_SAFE.ps1;"
            "scripts/RUN_DIRECTIONAL_DYADS_SAFE.ps1;"
            "manifest/Complete_Analysis_Release_Manifest.json"
        ),
        "planned_claim_ids": "T-DYAD-005;F-CONCLUSION-001",
        "notes": "Finalize after final script inventory and environment capture.",
    },
    "TAB-T1": {
        "analytical_question": (
            "When was each design, measurement correction, secondary family, "
            "or exploratory extension added relative to result generation?"
        ),
        "planned_source_artifacts": (
            "documentation/Statistical_Analysis_Plan.md;"
            "documentation/Provider_Measurement_V2_SAP_Addendum.md;"
            "documentation/Directional_Dyad_Analysis_Plan_Extension_FROZEN.json;"
            "documentation/SAP_deviation_log.csv"
        ),
        "planned_claim_ids": "T-PV2-003;T-DYAD-001;T-DYAD-004",
        "notes": "Preserve honest timing and original/secondary/exploratory labels.",
    },
    "TAB-T2": {
        "analytical_question": (
            "What are the version, acquisition/effective date, coverage, "
            "license, redistribution rule, and main limitation of every "
            "external source?"
        ),
        "planned_source_artifacts": (
            "qa/provider_master_v2_source_manifest.json;"
            "qa/provider_race_proxy_v2_source_manifest.json;"
            "outputs/florida_ed_full_build_20260724/source_snapshots/"
            "download_manifest.json"
        ),
        "planned_claim_ids": "T-P1-002;T-RACE-001;T-RACE-003",
        "notes": "Licensing and GitHub disposition require final legal/data-use review.",
    },
    "TAB-T3": {
        "analytical_question": (
            "Do Phase 1, the refreshed primary cohort, and the historical "
            "cohort reconcile exactly by period and partition?"
        ),
        "planned_source_artifacts": (
            "outputs/florida_ed_full_build_20260724/qa/"
            "quarterly_build_reconciliation.csv;"
            "qa/provider_v2_cohort_fact_reconciliation.csv;"
            "qa/historical_provider_v2_phase1_reconciliation.csv"
        ),
        "planned_claim_ids": "T-P1-001;T-P2-001;T-HIST-001;T-DYAD-002",
        "notes": "Use aggregate partition counts only.",
    },
    "TAB-T4": {
        "analytical_question": (
            "What material problem occurred, how was it detected and corrected, "
            "what was rerun, and which independent validation proved resolution?"
        ),
        "planned_source_artifacts": (
            "reports/report_production/ledgers/Report_Issue_Log_Ledger.csv;"
            "documentation/SAP_deviation_log.csv;"
            "audit_history/"
        ),
        "planned_claim_ids": "T-PV2-003;T-DYAD-005",
        "notes": "Rows remain blocked until each narrative is source-complete.",
    },
    "FIG-C1": {
        "analytical_question": (
            "Which years form the primary and historical periods, and which "
            "years are absent?"
        ),
        "planned_source_artifacts": (
            "outputs/florida_ed_full_build_20260724/build_manifest_final.json"
        ),
        "planned_claim_ids": "T-P1-001;T-HIST-001",
        "notes": "State that 2009 and 2025 were not processed; do not interpolate.",
    },
    "FIG-C2": {
        "analytical_question": (
            "How are encounters connected to facilities and individual "
            "clinicians while keeping organizations and clinician types distinct?"
        ),
        "planned_source_artifacts": (
            "documentation/Provider_Measurement_V2_SAP_Addendum.md;"
            "qa/pre_estimation_measurement_gate.json"
        ),
        "planned_claim_ids": "T-PV2-001;T-PV2-002;T-PV2-003",
        "notes": "Public-safe conceptual diagram; no NPI or encounter identifiers.",
    },
    "FIG-C3": {
        "analytical_question": (
            "Which recorded and algorithmic sources contribute to physician "
            "race and gender measurement, and how is uncertainty tested?"
        ),
        "planned_source_artifacts": (
            "qa/provider_race_proxy_v2_qa.json;"
            "qa/provider_gender_measurement_checkpoint.json;"
            "qa/provider_race_prior_provenance_checkpoint.json"
        ),
        "planned_claim_ids": "T-RACE-001;T-RACE-003;T-GENDER-001;T-DYAD-006",
        "notes": (
            "Always label physician race algorithm-inferred and probabilistic; "
            "never self-reported or BISG."
        ),
    },
    "FIG-C4": {
        "analytical_question": (
            "How do raw group differences become adjusted associations while "
            "retaining measured confounding and clustering limitations?"
        ),
        "planned_source_artifacts": (
            "documentation/Primary_Model_Implementation_Specification.md;"
            "documentation/Directional_Dyad_Model_Implementation_FROZEN.json"
        ),
        "planned_claim_ids": "T-DYAD-004;F-PRIMARY-001",
        "notes": "Conceptual methods figure; no result values until final audits pass.",
    },
    "FIG-C5": {
        "analytical_question": (
            "Which directional gender, race, and intersectional cells and "
            "contrasts were frozen and supported before fitting?"
        ),
        "planned_source_artifacts": (
            "qa/directional_dyad_extension_pre_estimation_gate.json;"
            "qa/independent_directional_cell_support_audit.json"
        ),
        "planned_claim_ids": "T-DYAD-001;T-DYAD-003",
        "notes": "Mark sparse or non-estimable cells; never silently merge them.",
    },
    "FIG-C6": {
        "analytical_question": (
            "What checks protect the analysis between raw source files and "
            "the final public report?"
        ),
        "planned_source_artifacts": (
            "reports/report_production/qa/Report_Finalization_Gate.json;"
            "qa/complete_analysis_release_audit.json"
        ),
        "planned_claim_ids": "T-P1-001;T-PV2-001;T-DYAD-005",
        "notes": "Update gate counts after the final analysis release audit.",
    },
    "FIG-C7": {
        "analytical_question": (
            "What are the audited adjusted differences and 95% confidence "
            "intervals for the prioritized outcomes and directional contrasts?"
        ),
        "planned_source_artifacts": (
            "results/models/;results/directional_dyads/;"
            "qa/complete_analysis_release_audit.json"
        ),
        "planned_claim_ids": (
            "F-PRIMARY-001;F-DYAD-GENDER-001;F-DYAD-RACE-001;"
            "F-DYAD-INTERSECTIONAL-001"
        ),
        "notes": "Remain empty until all result and public-safety audits pass.",
    },
    "FIG-C8": {
        "analytical_question": (
            "How stable are prioritized associations across priors, thresholds, "
            "multiple imputation, samples, model forms, and influence checks?"
        ),
        "planned_source_artifacts": (
            "results/;qa/independent_common_postmodel_results_audit.json;"
            "qa/independent_directional_measurement_sensitivity_audit.json"
        ),
        "planned_claim_ids": "F-SENS-001",
        "notes": "Show null, inconsistent, and non-robust findings as clearly as stable ones.",
    },
    "TAB-C1": {
        "analytical_question": (
            "Which outcomes and covariates are fully, partially, or not "
            "comparable between 2005-2008 and 2010-2024?"
        ),
        "planned_source_artifacts": (
            "documentation/Historical_2005_2008_Comparability_Matrix.csv;"
            "qa/historical_provider_v2_pre_estimation_gate.json"
        ),
        "planned_claim_ids": "T-HIST-001;F-HIST-RACE-001;F-HIST-GENDER-001",
        "notes": "Hourly LOS is structurally unavailable historically and is not imputed.",
    },
}


def build_exhibit_rows() -> list[dict[str, str]]:
    rows = []
    for exhibit_id, report, section, title, kind, status, gate in EXHIBITS:
        details = EXHIBIT_DETAILS.get(exhibit_id, {})
        rows.append(
            {
                "exhibit_id": exhibit_id,
                "report": report,
                "section_id": section,
                "title": title,
                "exhibit_type": kind,
                "analytical_question": details.get("analytical_question", ""),
                "planned_source_artifacts": details.get(
                    "planned_source_artifacts", ""
                ),
                "planned_claim_ids": details.get("planned_claim_ids", ""),
                "current_status": status,
                "required_gate": gate,
                "public_safety_review": (
                    "REQUIRED" if report == "collaborator" else "AS_APPLICABLE"
                ),
                "static_pdf_representation_required": "YES",
                "adjacent_explanatory_paragraph_required": "YES",
                "notes": details.get("notes", ""),
            }
        )
    return rows


REQUIRED_GATES = [
    {
        "gate_id": "phase1_release_audit",
        "path": PHASE1 / "qa" / "independent_release_validation.json",
        "required_status": "PASS",
        "required_for_finalization": True,
    },
    {
        "gate_id": "provider_measurement_gate",
        "path": PHASE2 / "qa" / "pre_estimation_measurement_gate.json",
        "required_status": "PASS",
        "required_for_finalization": True,
    },
    {
        "gate_id": "primary_cohort_gate",
        "path": PHASE2 / "qa" / "cohort_validation_report.json",
        "required_status": "PASS",
        "required_for_finalization": True,
    },
    {
        "gate_id": "historical_independent_audit",
        "path": PHASE2 / "qa" / "independent_historical_results_audit.json",
        "required_status": "PASS",
        "required_for_finalization": True,
    },
    {
        "gate_id": "directional_pre_estimation_gate",
        "path": PHASE2 / "qa" / "directional_dyad_extension_pre_estimation_gate.json",
        "required_status": "PASS",
        "required_for_finalization": True,
    },
    {
        "gate_id": "directional_base_independent_audit",
        "path": PHASE2 / "qa" / "independent_directional_dyad_base_audit.json",
        "required_status": "PASS",
        "required_for_finalization": True,
    },
    {
        "gate_id": "directional_support_independent_audit",
        "path": PHASE2 / "qa" / "independent_directional_cell_support_audit.json",
        "required_status": "PASS",
        "required_for_finalization": True,
    },
    {
        "gate_id": "directional_model_implementation_gate",
        "path": PHASE2
        / "qa"
        / "directional_model_implementation_pre_estimation_gate.json",
        "required_status": "PASS",
        "required_for_finalization": True,
    },
    {
        "gate_id": "directional_model_definition_tests",
        "path": PHASE2 / "qa" / "directional_model_definition_tests.json",
        "required_status": "PASS",
        "required_for_finalization": True,
    },
    {
        "gate_id": "directional_execution_code_gate",
        "path": PHASE2 / "qa" / "directional_execution_code_gate.json",
        "required_status": "PASS",
        "required_for_finalization": True,
    },
    {
        "gate_id": "primary_results_independent_audit",
        "path": PHASE2 / "qa" / "independent_primary_results_audit.json",
        "required_status": "PASS",
        "required_for_finalization": True,
    },
    {
        "gate_id": "outcome_specific_results_audit",
        "path": PHASE2 / "qa" / "independent_outcome_specific_results_audit.json",
        "required_status": "PASS",
        "required_for_finalization": True,
    },
    {
        "gate_id": "cohort_definition_results_audit",
        "path": PHASE2 / "qa" / "independent_cohort_definition_results_audit.json",
        "required_status": "PASS",
        "required_for_finalization": True,
    },
    {
        "gate_id": "payer_heterogeneity_audit",
        "path": PHASE2 / "qa" / "independent_payer_heterogeneity_audit.json",
        "required_status": "PASS",
        "required_for_finalization": True,
    },
    {
        "gate_id": "common_postmodel_results_audit",
        "path": PHASE2 / "qa" / "independent_common_postmodel_results_audit.json",
        "required_status": "PASS",
        "required_for_finalization": True,
    },
    {
        "gate_id": "primary_ami_results_audit",
        "path": PHASE2 / "qa" / "independent_primary_ami_results_audit.json",
        "required_status": "PASS",
        "required_for_finalization": True,
    },
    {
        "gate_id": "directional_measurement_sensitivity_audit",
        "path": PHASE2
        / "qa"
        / "independent_directional_measurement_sensitivity_audit.json",
        "required_status": "PASS",
        "required_for_finalization": True,
    },
    {
        "gate_id": "directional_gender_results_audit",
        "path": PHASE2 / "qa" / "independent_directional_gender_results_audit.json",
        "required_status": "PASS",
        "required_for_finalization": True,
    },
    {
        "gate_id": "directional_race_results_audit",
        "path": PHASE2 / "qa" / "independent_directional_race_results_audit.json",
        "required_status": "PASS",
        "required_for_finalization": True,
    },
    {
        "gate_id": "directional_intersectional_results_audit",
        "path": PHASE2
        / "qa"
        / "independent_directional_intersectional_results_audit.json",
        "required_status": "PASS",
        "required_for_finalization": True,
    },
    {
        "gate_id": "complete_analysis_release_audit",
        "path": PHASE2 / "qa" / "complete_analysis_release_audit.json",
        "required_status": "PASS",
        "required_for_finalization": True,
    },
    {
        "gate_id": "report_content_accuracy_audit",
        "path": QA_ROOT / "Report_Content_Accuracy_Audit.json",
        "required_status": "PASS",
        "required_for_finalization": True,
    },
    {
        "gate_id": "report_public_safety_audit",
        "path": QA_ROOT / "Report_Public_Safety_Audit.json",
        "required_status": "PASS",
        "required_for_finalization": True,
    },
    {
        "gate_id": "report_visual_quality_audit",
        "path": QA_ROOT / "Report_Visual_Quality_Audit.json",
        "required_status": "PASS",
        "required_for_finalization": True,
    },
]


def gate_status(path: Path) -> tuple[str, str]:
    if not path.is_file():
        return "MISSING", ""
    status = json_status(path)
    return status, sha256(path)


def build_gate(request_sha: str) -> dict[str, Any]:
    gates = []
    for spec in REQUIRED_GATES:
        status, digest = gate_status(spec["path"])
        gates.append(
            {
                "gate_id": spec["gate_id"],
                "workspace_relative_path": rel(spec["path"]),
                "required_status": spec["required_status"],
                "observed_status": status,
                "sha256": digest,
                "required_for_finalization": spec["required_for_finalization"],
                "passed": status == spec["required_status"],
            }
        )
    required = [g for g in gates if g["required_for_finalization"]]
    report_production_gate_ids = {
        "report_content_accuracy_audit",
        "report_public_safety_audit",
        "report_visual_quality_audit",
    }
    analytical_required = [
        g for g in required if g["gate_id"] not in report_production_gate_ids
    ]
    analytical_passed = bool(analytical_required) and all(
        g["passed"] for g in analytical_required
    )
    all_passed = bool(required) and all(g["passed"] for g in required)
    if all_passed:
        current_stage = "final_reports_authorized"
    elif analytical_passed:
        current_stage = "audited_findings_and_draft_report_qa_authorized"
    else:
        current_stage = "outline_evidence_and_source_manifest_only"
    final_pdfs = [
        REPORT_ROOT / "Florida_ED_Technical_Project_Dossier.pdf",
        REPORT_ROOT / "Florida_ED_Collaborator_Project_Report.pdf",
    ]
    return {
        "gate_id": "florida_ed_two_report_finalization_gate_v1",
        "created_utc": utc_now(),
        "request_checkpoint_sha256": request_sha,
        "current_stage": current_stage,
        "findings_insertion_authorized": analytical_passed,
        "draft_document_and_pdf_build_authorized": analytical_passed,
        "pdf_finalization_authorized": all_passed,
        "finalization_authorized": all_passed,
        "analytical_gates_passed": sum(
            g["passed"] for g in analytical_required
        ),
        "analytical_gates_total": len(analytical_required),
        "required_gates_passed": sum(g["passed"] for g in required),
        "required_gates_total": len(required),
        "gates": gates,
        "final_pdf_state": [
            {
                "workspace_relative_path": rel(path),
                "exists": path.exists(),
            }
            for path in final_pdfs
        ],
        "fail_closed_rule": (
            "Any missing, failed, unreadable, unbound, or superseded analytical "
            "audit keeps findings insertion and draft report production "
            "unauthorized. Stable final PDFs additionally require the report "
            "content-accuracy, public-safety, and visual-quality audits to pass."
        ),
    }


def audit_framework(
    source_manifest: dict[str, Any],
    claim_rows: list[dict[str, Any]],
    gate: dict[str, Any],
    request_sha: str,
) -> dict[str, Any]:
    checks = []

    def add(check_id: str, passed: bool, evidence: Any) -> None:
        checks.append(
            {"check_id": check_id, "passed": bool(passed), "evidence": evidence}
        )

    add(
        "editable_markdown_sources_exist",
        TECHNICAL_SOURCE.is_file() and COLLABORATOR_SOURCE.is_file(),
        [rel(TECHNICAL_SOURCE), rel(COLLABORATOR_SOURCE)],
    )
    technical = TECHNICAL_SOURCE.read_text(encoding="utf-8")
    collaborator = COLLABORATOR_SOURCE.read_text(encoding="utf-8")
    add(
        "final_audit_gated_markers_present",
        technical.count("[FINAL-AUDIT-GATED]") >= 2
        and collaborator.count("[FINAL-AUDIT-GATED]") >= 5,
        {
            "technical_markers": technical.count("[FINAL-AUDIT-GATED]"),
            "collaborator_markers": collaborator.count("[FINAL-AUDIT-GATED]"),
        },
    )
    local_path_pattern = re.compile(r"[A-Za-z]:\\\\")
    add(
        "collaborator_source_contains_no_windows_absolute_paths",
        local_path_pattern.search(collaborator) is None,
        "No drive-letter path permitted in public-facing source.",
    )
    add(
        "request_copy_exists_and_hashed",
        REQUEST_COPY.is_file() and sha256(REQUEST_COPY) == request_sha,
        {
            "path": rel(REQUEST_COPY),
            "sha256": request_sha,
        },
    )
    indexed = manifest_index(source_manifest)
    missing_sources = []
    mismatched_sources = []
    for row in claim_rows:
        for path_field, hash_field in [
            ("source_artifact", "source_sha256"),
            ("validation_artifact", "validation_sha256"),
        ]:
            p = row[path_field]
            if not p:
                continue
            if p not in indexed:
                if row["evidence_state"].startswith("VERIFIED"):
                    missing_sources.append(
                        {"claim_id": row["claim_id"], "path": p}
                    )
            elif row[hash_field] != indexed[p]["sha256"]:
                mismatched_sources.append(
                    {"claim_id": row["claim_id"], "path": p}
                )
    add(
        "claim_sources_present_in_source_manifest",
        not missing_sources,
        missing_sources,
    )
    add(
        "claim_hashes_match_source_manifest",
        not mismatched_sources,
        mismatched_sources,
    )
    verified_missing = [
        row["claim_id"]
        for row in claim_rows
        if row["evidence_state"].startswith("VERIFIED")
        and (not row["source_artifact"] or not row["validation_artifact"])
    ]
    add(
        "verified_claims_have_source_and_validation",
        not verified_missing,
        verified_missing,
    )
    pending_result_ids = [
        row["claim_id"]
        for row in claim_rows
        if row["claim_type"] in {"inferential_result", "synthesis"}
        and row["evidence_state"] == "PENDING_FINAL_RESULT_AUDIT"
    ]
    add(
        "result_claim_states_match_analysis_gate",
        (
            len(pending_result_ids) >= 5
            if not gate["findings_insertion_authorized"]
            else len(pending_result_ids) == 0
        ),
        {
            "findings_insertion_authorized": gate[
                "findings_insertion_authorized"
            ],
            "pending_result_claims": pending_result_ids,
        },
    )
    add(
        "report_stage_authorization_is_internally_consistent",
        (
            gate["findings_insertion_authorized"]
            == (
                gate["analytical_gates_passed"]
                == gate["analytical_gates_total"]
            )
        )
        and (
            gate["finalization_authorized"]
            == (
                gate["required_gates_passed"]
                == gate["required_gates_total"]
            )
        ),
        {
            "analytical_passed": gate["analytical_gates_passed"],
            "analytical_total": gate["analytical_gates_total"],
            "required_passed": gate["required_gates_passed"],
            "required_total": gate["required_gates_total"],
            "findings_insertion_authorized": gate[
                "findings_insertion_authorized"
            ],
            "finalization_authorized": gate["finalization_authorized"],
        },
    )
    analytical_gate_ids = {
        g["gate_id"]
        for g in gate["gates"]
        if g["gate_id"]
        not in {
            "report_content_accuracy_audit",
            "report_public_safety_audit",
            "report_visual_quality_audit",
        }
    }
    add(
        "report_gate_has_non_circular_two_stage_authorization",
        bool(analytical_gate_ids)
        and gate["analytical_gates_total"] == len(analytical_gate_ids)
        and (
            gate["findings_insertion_authorized"]
            == (
                gate["analytical_gates_passed"]
                == gate["analytical_gates_total"]
            )
        )
        and (
            not gate["finalization_authorized"]
            or gate["required_gates_passed"] == gate["required_gates_total"]
        ),
        {
            "analytical_passed": gate["analytical_gates_passed"],
            "analytical_total": gate["analytical_gates_total"],
            "findings_insertion_authorized": gate[
                "findings_insertion_authorized"
            ],
            "required_passed": gate["required_gates_passed"],
            "required_total": gate["required_gates_total"],
            "finalization_authorized": gate["finalization_authorized"],
        },
    )
    final_pdf_paths = [
        REPORT_ROOT / "Florida_ED_Technical_Project_Dossier.pdf",
        REPORT_ROOT / "Florida_ED_Collaborator_Project_Report.pdf",
    ]
    add(
        "stable_final_pdfs_not_prematurely_created",
        gate["finalization_authorized"]
        or not any(path.exists() for path in final_pdf_paths),
        [rel(path) for path in final_pdf_paths if path.exists()],
    )
    status = "PASS" if all(c["passed"] for c in checks) else "FAIL"
    return {
        "audit_id": "florida_ed_report_framework_audit_v1",
        "created_utc": utc_now(),
        "status": status,
        "checks_passed": sum(c["passed"] for c in checks),
        "checks_total": len(checks),
        "checks": checks,
        "scope": (
            "Outline, evidence-ledger, source-manifest, gating, and public-path "
            "controls only. This is not a findings, content-accuracy, or visual audit."
        ),
    }


def write_framework_manifest(paths: list[Path]) -> dict[str, Any]:
    files = []
    for path in sorted(paths, key=lambda p: rel(p)):
        files.append(
            {
                "workspace_relative_path": rel(path),
                "sha256": sha256(path),
                "bytes": path.stat().st_size,
            }
        )
    payload = {
        "manifest_id": "florida_ed_report_framework_manifest_v1",
        "created_utc": utc_now(),
        "file_count": len(files),
        "files": files,
    }
    atomic_json(MANIFEST_ROOT / "Report_Framework_Manifest.json", payload)
    return payload


def main() -> None:
    if not REQUEST_COPY.is_file():
        raise FileNotFoundError(
            f"Missing preserved report request: {REQUEST_COPY}"
        )
    if not TECHNICAL_SOURCE.is_file() or not COLLABORATOR_SOURCE.is_file():
        raise FileNotFoundError("Editable report outline source is missing.")

    LEDGER_ROOT.mkdir(parents=True, exist_ok=True)
    QA_ROOT.mkdir(parents=True, exist_ok=True)
    MANIFEST_ROOT.mkdir(parents=True, exist_ok=True)

    request_sha = sha256(REQUEST_COPY)
    source_manifest = build_source_manifest(source_files())
    source_manifest_path = LEDGER_ROOT / "Report_Source_Manifest.json"
    atomic_json(source_manifest_path, source_manifest)

    claim_rows = build_claim_rows(source_manifest)
    claim_fields = [
        "claim_id",
        "reports",
        "section_ids",
        "claim_or_element",
        "claim_type",
        "classification",
        "source_artifact",
        "source_sha256",
        "validation_artifact",
        "validation_sha256",
        "evidence_state",
        "public_disposition",
        "result_gate",
        "notes",
    ]
    evidence_csv = LEDGER_ROOT / "Report_Evidence_Ledger.csv"
    atomic_csv(evidence_csv, claim_rows, claim_fields)
    evidence_json = LEDGER_ROOT / "Report_Evidence_Manifest.json"
    atomic_json(
        evidence_json,
        {
            "manifest_id": "florida_ed_report_evidence_manifest_v1",
            "created_utc": utc_now(),
            "source_manifest_sha256": sha256(source_manifest_path),
            "claim_count": len(claim_rows),
            "claims": claim_rows,
        },
    )

    issue_csv = LEDGER_ROOT / "Report_Issue_Log_Ledger.csv"
    issue_rows = build_issue_rows()
    issue_fields = list(issue_rows[0])
    atomic_csv(issue_csv, issue_rows, issue_fields)

    exhibit_csv = LEDGER_ROOT / "Report_Chart_Table_Plan.csv"
    exhibit_rows = build_exhibit_rows()
    exhibit_fields = list(exhibit_rows[0])
    atomic_csv(exhibit_csv, exhibit_rows, exhibit_fields)

    checkpoint = {
        "checkpoint_id": "REPORT_PRODUCTION_REQUEST_20260726",
        "created_utc": utc_now(),
        "request_copy": rel(REQUEST_COPY),
        "request_sha256": request_sha,
        "instruction_state": "QUEUED_AND_APPLIED_AT_SAFE_CHECKPOINT",
        "audit_process_interrupted": False,
        "current_action_authorized": [
            "build outlines",
            "build evidence ledgers",
            "build source manifests",
        ],
        "currently_prohibited": [
            "finalize findings",
            "finalize conclusions",
            "create stable final PDFs",
        ],
        "finalization_condition": (
            "All primary, historical, AMI/Greenwood, directional-dyad, "
            "sensitivity, independent-result, full-release, and report audits pass."
        ),
    }
    checkpoint_path = (
        PHASE2
        / "documentation"
        / "Report_Production_Request_Checkpoint_20260726.json"
    )
    atomic_json(checkpoint_path, checkpoint)

    gate = build_gate(request_sha)
    gate_path = QA_ROOT / "Report_Finalization_Gate.json"
    atomic_json(gate_path, gate)

    audit = audit_framework(source_manifest, claim_rows, gate, request_sha)
    audit_path = QA_ROOT / "Report_Framework_Audit.json"
    atomic_json(audit_path, audit)

    framework_files = [
        TECHNICAL_SOURCE,
        COLLABORATOR_SOURCE,
        REPORT_ROOT / "REPORT_PRODUCTION_README.md",
        source_manifest_path,
        evidence_csv,
        evidence_json,
        issue_csv,
        exhibit_csv,
        gate_path,
        audit_path,
        checkpoint_path,
        REQUEST_COPY,
        Path(__file__).resolve(),
    ]
    framework_manifest = write_framework_manifest(framework_files)

    if audit["status"] != "PASS":
        raise RuntimeError(
            f"Report framework audit failed: {audit_path}"
        )

    print(
        json.dumps(
            {
                "status": "PASS",
                "source_files_hashed": source_manifest["file_count"],
                "evidence_claims": len(claim_rows),
                "issues_seeded": len(issue_rows),
                "exhibits_planned": len(exhibit_rows),
                "report_finalization_authorized": gate[
                    "finalization_authorized"
                ],
                "required_gates_passed": gate["required_gates_passed"],
                "required_gates_total": gate["required_gates_total"],
                "framework_files": framework_manifest["file_count"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
