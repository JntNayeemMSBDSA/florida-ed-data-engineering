#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/11_build_clinical_classification_review.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Build provisional, evidence-informed clinical classification review tables."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd


VERSION = "1.0-provisional"
EVIDENCE_ACCESSED = "2026-07-26"


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def qpath(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace("'", "''")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def classify_treatment(label: str) -> tuple[str, str, str, bool]:
    text = (label or "").upper()
    higher_discretion_terms = (
        "CT SCAN",
        "COMPUTERIZED AXIAL TOMOGRAPHY",
        "MAGNETIC RESONANCE",
        "DIAGNOSTIC ULTRASOUND",
        "X-RAY",
        "LABORATORY",
        "MICROSCOPIC EXAMINATION",
        "PATHOLOGY",
        "CONSULTATION",
        "EVALUATION",
        "CARDIAC STRESS",
        "RADIOISOTOPE SCAN",
        "ELECTROENCEPHALOGRAM",
        "OTHER DIAGNOSTIC RADIOLOGY",
    )
    lower_discretion_terms = (
        "RESPIRATORY INTUBATION",
        "MECHANICAL VENTILATION",
        "BLOOD AND BLOOD PRODUCT TRANSFUSION",
        "CORONARY THROMBOLYSIS",
        "PERCUTANEOUS TRANSLUMINAL CORONARY ANGIOPLASTY",
        "APPENDECTOMY",
        "CHOLECYSTECTOMY",
        "HEMODIALYSIS",
        "CONTROL OF EPISTAXIS",
        "SUTURE OF SKIN",
        "INCISION AND DRAINAGE",
        "TREATMENT, FRACTURE",
        "REMOVAL OF ECTOPIC PREGNANCY",
    )
    if any(term in text for term in higher_discretion_terms):
        return (
            "higher_discretion_candidate",
            (
                "Diagnostic test or consultation ordering has documented "
                "practice variation and condition-specific appropriateness; "
                "classification does not imply that a given use was low value."
            ),
            "moderate",
            False,
        )
    if any(term in text for term in lower_discretion_terms):
        return (
            "lower_discretion_candidate",
            (
                "Definitive or urgent therapeutic procedure with a narrower "
                "usual indication set; urgency and appropriateness cannot be "
                "confirmed from claims-style fields."
            ),
            "low_to_moderate",
            True,
        )
    return (
        "ambiguous_or_unclassified",
        (
            "The group is too heterogeneous or context-dependent for a "
            "defensible binary assignment without code-level clinician review."
        ),
        "low",
        True,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    parser.add_argument("--release", required=True, type=Path)
    parser.add_argument("--threads", type=int, default=12)
    parser.add_argument("--memory-limit", default="24GB")
    parser.add_argument("--temp", required=True, type=Path)
    args = parser.parse_args()

    phase2 = args.phase2.resolve()
    release = args.release.resolve()
    args.temp.mkdir(parents=True, exist_ok=True)
    output = phase2 / "results" / "clinical_classification"
    documentation = phase2 / "documentation"
    output.mkdir(parents=True, exist_ok=True)
    documentation.mkdir(parents=True, exist_ok=True)
    provider_gate_path = phase2 / "qa" / "pre_estimation_measurement_gate.json"
    cohort_gate_path = phase2 / "qa" / "cohort_validation_report.json"
    for gate_path in (provider_gate_path, cohort_gate_path):
        if not gate_path.is_file():
            raise FileNotFoundError(gate_path)
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        if gate.get("status") != "PASS":
            raise RuntimeError(f"Clinical-classification gate failed: {gate_path}")
    provider_gate_sha256 = sha256_file(provider_gate_path)
    cohort_gate_sha256 = sha256_file(cohort_gate_path)
    core_glob = (
        phase2
        / "analysis_data"
        / "concordance_visit_data_provider_v2"
        / "visit_year=*"
        / "visit_quarter=*"
        / "concordance_visit_core.parquet"
    )
    procedure_glob = (
        release
        / "bridges"
        / "visit_procedure"
        / "visit_year=*"
        / "visit_quarter=*"
        / "visit_procedure.parquet"
    )

    con = duckdb.connect()
    con.execute(f"SET threads={args.threads}")
    con.execute(f"SET memory_limit='{args.memory_limit}'")
    con.execute(f"SET temp_directory='{qpath(args.temp)}'")
    con.execute("SET preserve_insertion_order=false")
    presentation = con.execute(
        f"""
        SELECT
            diagnosis_code_system,
            principal_clinical_category AS source_clinical_category,
            principal_clinical_category_label AS source_clinical_category_label,
            count(*) AS visit_count,
            sum(presentation_code_group = 'symptom_sign_coded')
                AS symptom_sign_coded_visits,
            sum(
                presentation_code_group =
                    'disease_condition_or_injury_coded'
            ) AS disease_condition_or_injury_coded_visits,
            sum(presentation_code_group = 'ambiguous_or_missing')
                AS ambiguous_or_missing_visits,
            avg(
                (presentation_code_group = 'symptom_sign_coded')::DOUBLE
            ) AS symptom_sign_share
        FROM read_parquet('{qpath(core_glob)}', hive_partitioning=false)
        GROUP BY
            diagnosis_code_system,
            principal_clinical_category,
            principal_clinical_category_label
        ORDER BY diagnosis_code_system, visit_count DESC
        """
    ).fetchdf()
    presentation["assigned_group"] = "ambiguous_or_mixed"
    presentation.loc[
        presentation["symptom_sign_share"] >= 0.80, "assigned_group"
    ] = "higher_subjectivity_proxy_symptom_sign_coded"
    presentation.loc[
        presentation["symptom_sign_share"] <= 0.20, "assigned_group"
    ] = "lower_subjectivity_proxy_disease_condition_injury_coded"
    presentation["operational_definition"] = (
        "Category-level empirical predominance: >=80% symptom/sign coded, "
        "<=20% symptom/sign coded, otherwise ambiguous/mixed."
    )
    presentation["rationale"] = presentation["assigned_group"].map(
        {
            "higher_subjectivity_proxy_symptom_sign_coded": (
                "Symptom/sign principal coding is used as a proxy for greater "
                "diagnostic uncertainty, not as proof of subjective symptoms."
            ),
            "lower_subjectivity_proxy_disease_condition_injury_coded": (
                "Disease/condition/injury principal coding is used as a proxy "
                "for a more established coded diagnosis, not objective truth."
            ),
            "ambiguous_or_mixed": (
                "The clinical category contains a material mixture of code "
                "types and is not forced into a binary group."
            ),
        }
    )
    presentation["supporting_source"] = (
        "AHRQ CCSR/CCS category mappings plus ICD-9 780-799 and ICD-10-CM "
        "R00-R99 symptom/sign chapter logic"
    )
    presentation["supporting_url"] = (
        "https://hcup-us.ahrq.gov/toolssoftware/ccsr/ccs_refined.jsp"
    )
    presentation["confidence"] = presentation["assigned_group"].map(
        {
            "higher_subjectivity_proxy_symptom_sign_coded": "moderate",
            "lower_subjectivity_proxy_disease_condition_injury_coded": "moderate",
            "ambiguous_or_mixed": "low",
        }
    )
    presentation["ambiguity_flag"] = (
        presentation["assigned_group"] == "ambiguous_or_mixed"
    )
    presentation["version"] = VERSION
    presentation["date_accessed"] = EVIDENCE_ACCESSED
    presentation["clinician_review_status"] = "pending"
    presentation["clinician_reviewer"] = ""
    presentation["clinician_decision"] = ""
    presentation["clinician_comments"] = ""
    presentation_review_path = output / "presentation_subjectivity_review.csv"
    presentation.to_csv(presentation_review_path, index=False)
    presentation_review_sha256 = sha256_file(presentation_review_path)

    procedures = con.execute(
        f"""
        SELECT
            procedure_code_system,
            procedure_group AS source_procedure_group,
            procedure_group_label AS source_procedure_group_label,
            count(*) AS occurrence_count,
            min(visit_year) AS first_year,
            max(visit_year) AS last_year,
            count(DISTINCT visit_key) AS distinct_visit_count,
            avg(code_description_mapped_flag::DOUBLE)
                AS code_description_mapped_share,
            avg(group_mapped_flag::DOUBLE) AS group_mapped_share
        FROM read_parquet('{qpath(procedure_glob)}', hive_partitioning=false)
        GROUP BY
            procedure_code_system,
            procedure_group,
            procedure_group_label
        ORDER BY procedure_code_system, occurrence_count DESC
        """
    ).fetchdf()
    classifications = procedures["source_procedure_group_label"].fillna("").map(
        classify_treatment
    )
    procedures["assigned_group"] = [
        item[0] for item in classifications
    ]
    procedures["operational_definition"] = (
        "Keyword-conservative CCS procedure-group review; only clearly "
        "diagnostic-ordering or narrowly indicated urgent/definitive groups "
        "receive candidate labels; all others remain ambiguous."
    )
    procedures["rationale"] = [item[1] for item in classifications]
    procedures["supporting_source"] = (
        "AHRQ CCS procedure groups; AHRQ ED imaging research agenda; "
        "ACEP E-QUAL avoidable-imaging resources; published ED imaging "
        "practice-variation literature"
    )
    procedures["supporting_url"] = (
        "https://www.ahrq.gov/diagnostic-safety/research/ed-imaging.html"
    )
    procedures["secondary_supporting_url"] = (
        "https://www.acep.org/administration/quality/equal/"
        "emergency-quality-network-e-qual/reduce-avoidable-imaging-initiative/"
        "equal-imaging---toolkits2"
    )
    procedures["confidence"] = [item[2] for item in classifications]
    procedures["ambiguity_flag"] = [item[3] for item in classifications]
    procedures["version"] = VERSION
    procedures["date_accessed"] = EVIDENCE_ACCESSED
    procedures["clinician_review_status"] = "pending"
    procedures["clinician_reviewer"] = ""
    procedures["clinician_decision"] = ""
    procedures["clinician_comments"] = ""
    treatment_review_path = output / "treatment_discretion_review.csv"
    procedures.to_csv(treatment_review_path, index=False)
    treatment_review_sha256 = sha256_file(treatment_review_path)
    mapping = procedures[
        [
            "procedure_code_system",
            "source_procedure_group",
            "assigned_group",
        ]
    ].rename(columns={"source_procedure_group": "procedure_group"})
    con.register("procedure_discretion_mapping", mapping)
    sidecar_root = phase2 / "analysis_data" / "discretion_outcomes"
    sidecar_manifests = []
    for year in range(2010, 2025):
        for quarter in range(1, 5):
            destination = (
                sidecar_root
                / f"visit_year={year}"
                / f"visit_quarter={quarter}"
            )
            destination.mkdir(parents=True, exist_ok=True)
            sidecar = destination / "visit_discretion_outcomes.parquet"
            stage = destination / "visit_discretion_outcomes.parquet.partial"
            success = destination / "_SUCCESS.json"
            core = (
                phase2
                / "analysis_data"
                / "concordance_visit_data_provider_v2"
                / f"visit_year={year}"
                / f"visit_quarter={quarter}"
                / "concordance_visit_core.parquet"
            )
            if success.exists() and sidecar.exists():
                prior = json.loads(success.read_text(encoding="utf-8"))
                reusable = (
                    prior.get("classification_version") == VERSION
                    and prior.get("classification_mapping_sha256")
                    == treatment_review_sha256
                    and prior.get("provider_gate_sha256")
                    == provider_gate_sha256
                    and prior.get("cohort_gate_sha256")
                    == cohort_gate_sha256
                    and prior.get("sha256") == sha256_file(sidecar)
                    and prior.get("passed") is True
                )
                if reusable:
                    sidecar_manifests.append(prior)
                    continue
                raise RuntimeError(
                    "Existing discretion sidecar is stale or corrupt; preserve "
                    f"it for audit before rebuilding: {destination}"
                )
            bridge = (
                release
                / "bridges"
                / "visit_procedure"
                / f"visit_year={year}"
                / f"visit_quarter={quarter}"
                / "visit_procedure.parquet"
            )
            con.execute(
                f"""
                COPY (
                    WITH procedure_counts AS (
                        SELECT
                            p.visit_key,
                            count(*) FILTER (
                                WHERE m.assigned_group =
                                    'higher_discretion_candidate'
                            ) AS higher_discretion_procedure_count,
                            count(*) FILTER (
                                WHERE m.assigned_group =
                                    'lower_discretion_candidate'
                            ) AS lower_discretion_procedure_count,
                            count(*) FILTER (
                                WHERE coalesce(
                                    m.assigned_group,
                                    'ambiguous_or_unclassified'
                                ) = 'ambiguous_or_unclassified'
                            ) AS ambiguous_discretion_procedure_count
                        FROM read_parquet(
                            '{qpath(bridge)}', hive_partitioning=false
                        ) p
                        LEFT JOIN procedure_discretion_mapping m
                          ON p.procedure_code_system =
                             m.procedure_code_system
                         AND p.procedure_group = m.procedure_group
                        GROUP BY p.visit_key
                    )
                    SELECT
                        c.visit_key,
                        c.visit_year,
                        c.visit_quarter,
                        coalesce(
                            p.higher_discretion_procedure_count, 0
                        )::UINTEGER AS higher_discretion_procedure_count,
                        coalesce(
                            p.lower_discretion_procedure_count, 0
                        )::UINTEGER AS lower_discretion_procedure_count,
                        coalesce(
                            p.ambiguous_discretion_procedure_count, 0
                        )::UINTEGER AS ambiguous_discretion_procedure_count,
                        (
                            coalesce(
                                p.higher_discretion_procedure_count, 0
                            ) > 0
                        )::UTINYINT AS any_higher_discretion_candidate_flag,
                        (
                            coalesce(
                                p.lower_discretion_procedure_count, 0
                            ) > 0
                        )::UTINYINT AS any_lower_discretion_candidate_flag
                    FROM read_parquet(
                        '{qpath(core)}', hive_partitioning=false
                    ) c
                    LEFT JOIN procedure_counts p USING (visit_key)
                ) TO '{qpath(stage)}'
                (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000)
                """
            )
            os.replace(stage, sidecar)
            sidecar_rows = con.execute(
                f"""
                SELECT count(*), count(DISTINCT visit_key)
                FROM read_parquet(
                    '{qpath(sidecar)}', hive_partitioning=false
                )
                """
            ).fetchone()
            payload = {
                "visit_year": year,
                "visit_quarter": quarter,
                "rows": int(sidecar_rows[0]),
                "distinct_visit_keys": int(sidecar_rows[1]),
                "bytes": sidecar.stat().st_size,
                "sha256": sha256_file(sidecar),
                "classification_version": VERSION,
                "classification_mapping_sha256": treatment_review_sha256,
                "provider_gate_sha256": provider_gate_sha256,
                "cohort_gate_sha256": cohort_gate_sha256,
                "passed": bool(sidecar_rows[0] == sidecar_rows[1]),
            }
            atomic_json(success, payload)
            sidecar_manifests.append(payload)
    con.close()

    overview = f"""# Clinical classification review

**Version:** {VERSION}  
**Status:** Provisional and evidence-informed; not clinically validated  
**Clinician review:** Required before confirmatory clinical interpretation

## Presentation framework

The analysis does not claim that diagnoses are inherently “subjective” or
“objective.” It uses the more defensible administrative-data distinction
between a principal code from the ICD symptom/sign chapters (ICD-9-CM
780–799; ICD-10-CM R00–R99) and a disease/condition/injury code. At the
clinical-category level, categories with at least 80% symptom/sign-coded
visits are candidate higher-uncertainty groups; those with at most 20% are
candidate lower-uncertainty groups; the remainder are ambiguous.

## Treatment-discretion framework

Diagnostic imaging, laboratory testing, and consultation groups are candidate
higher-discretion decisions because appropriate use is condition-dependent
and documented practice variation exists. A small set of urgent or definitive
therapeutic groups are candidate lower-discretion decisions. Most categories
remain ambiguous because claims-style codes do not contain the clinical
indication, test result, bedside assessment, or urgency needed to judge
appropriateness.

No classification implies that a service was unnecessary, inappropriate, or
caused by concordance. Results using these labels are secondary and remain
provisional until a qualified clinician completes the review columns.

Key sources:

- AHRQ CCSR: https://hcup-us.ahrq.gov/toolssoftware/ccsr/ccs_refined.jsp
- AHRQ ED diagnostic imaging research agenda:
  https://www.ahrq.gov/diagnostic-safety/research/ed-imaging.html
- ACEP E-QUAL avoidable imaging resources:
  https://www.acep.org/administration/quality/equal/emergency-quality-network-e-qual/reduce-avoidable-imaging-initiative/equal-imaging---toolkits2
- Kline et al., *Use of Imaging in the Emergency Department: Do Individual
  Physicians Contribute to Variation?* PubMed:
  https://pubmed.ncbi.nlm.nih.gov/31063428/
"""
    (documentation / "Clinical_Classification_Methods.md").write_text(
        overview, encoding="utf-8"
    )
    manifest = {
        "created_utc": now_utc(),
        "version": VERSION,
        "status_gate": "PASS",
        "status": "provisional_evidence_informed_not_clinically_validated",
        "presentation_rows": len(presentation),
        "treatment_rows": len(procedures),
        "discretion_sidecar_partitions": len(sidecar_manifests),
        "discretion_sidecar_rows": sum(
            item["rows"] for item in sidecar_manifests
        ),
        "clinician_review_required": True,
        "presentation_review_sha256": presentation_review_sha256,
        "treatment_review_sha256": treatment_review_sha256,
        "provider_gate_sha256": provider_gate_sha256,
        "cohort_gate_sha256": cohort_gate_sha256,
        "all_sidecars_passed": (
            len(sidecar_manifests) == 60
            and all(item.get("passed") is True for item in sidecar_manifests)
        ),
        "sidecar_manifest_digest_sha256": hashlib.sha256(
            json.dumps(
                sidecar_manifests, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest(),
        "sidecar_manifests": sidecar_manifests,
        "files": [
            "presentation_subjectivity_review.csv",
            "treatment_discretion_review.csv",
        ],
    }
    if not manifest["all_sidecars_passed"]:
        raise RuntimeError("Clinical-classification sidecar validation failed")
    atomic_json(output / "clinical_classification_manifest.json", manifest)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
