from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def add(checks: list[dict], check_id: str, passed: bool, evidence) -> None:
    checks.append({"check_id": check_id, "passed": bool(passed), "evidence": evidence})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--portfolio-root", required=True)
    parser.add_argument("--write-audit", action="store_true")
    args = parser.parse_args()

    root = Path(args.output_root).resolve()
    project = Path(args.project_root).resolve()
    portfolio = Path(args.portfolio_root).resolve()
    data = root / "dashboard_data"
    checks: list[dict] = []

    expected_tables = {
        "DimPeriod": (84, ("PeriodKey",)),
        "DimSchemaFamily": (5, ("SchemaFamilyKey",)),
        "DimProjectStage": (5, ("StageKey",)),
        "DimMetric": (25, ("MetricKey",)),
        "DimClinicalDomain": (9, ("ClinicalDomainKey",)),
        "DimCodingMap": (6, ("CodingMapKey",)),
        "DimModelSpec": (3, ("ModelSpecKey",)),
        "FactProjectCoverage": (14, ("ProjectMetricKey",)),
        "FactPartitionStatus": (84, ("PartitionKey",)),
        "FactEnhancementCoverage": (20, ("EnhancementKey",)),
        "FactProviderMeasurement": (11, ("ProviderMetricKey",)),
        "FactValidationStatus": (20, ("ValidationKey",)),
        "FactAnalyticalStatus": (20, ("AnalyticalStatusKey",)),
        "FactSyntheticDemonstration": (13, ("DemoMetricKey",)),
    }
    tables: dict[str, list[dict[str, str]]] = {}
    for table, (expected_rows, key_cols) in expected_tables.items():
        file = data / f"{table}.csv"
        exists = file.is_file()
        rows = read_csv(file) if exists else []
        tables[table] = rows
        keys = [tuple(row[col] for col in key_cols) for row in rows] if rows else []
        add(
            checks,
            f"table_{table}",
            exists and len(rows) == expected_rows and len(keys) == len(set(keys)),
            {"exists": exists, "rows": len(rows), "expected_rows": expected_rows, "key_unique": len(keys) == len(set(keys))},
        )

    relationships = [
        ("DimPeriod", "PeriodKey", "FactPartitionStatus", "PeriodKey"),
        ("DimSchemaFamily", "SchemaFamilyKey", "FactPartitionStatus", "SchemaFamilyKey"),
        ("DimProjectStage", "StageKey", "FactValidationStatus", "StageKey"),
        ("DimProjectStage", "StageKey", "FactAnalyticalStatus", "StageKey"),
        ("DimMetric", "MetricKey", "FactProjectCoverage", "MetricKey"),
        ("DimMetric", "MetricKey", "FactProviderMeasurement", "MetricKey"),
        ("DimClinicalDomain", "ClinicalDomainKey", "FactEnhancementCoverage", "ClinicalDomainKey"),
        ("DimModelSpec", "ModelSpecKey", "FactAnalyticalStatus", "ModelSpecKey"),
    ]
    orphan_total = 0
    for parent_table, parent_col, child_table, child_col in relationships:
        parents = {row[parent_col] for row in tables[parent_table]}
        orphans = [row for row in tables[child_table] if row[child_col] and row[child_col] not in parents]
        orphan_total += len(orphans)
    add(checks, "relationship_integrity", orphan_total == 0, {"relationships": len(relationships), "orphan_rows": orphan_total})

    project_values = {r["MetricKey"]: int(r["MetricValue"]) for r in tables["FactProjectCoverage"]}
    provider_values = {r["MetricKey"]: int(r["MetricValue"]) for r in tables["FactProviderMeasurement"]}
    exact = {
        "M001": 148_686_146, "M002": 76, "M003": 19, "M004": 342, "M005": 5,
        "M006": 240, "M007": 1_805_795, "M008": 119_543_044, "M009": 60,
        "M010": 23_304_846, "M011": 16, "M012": 743_767, "M013": 800, "M014": 76,
    }
    provider_exact = {"PM001": 1_813_546, "PM002": 83_541, "PM003": 75_790, "PM004": 7_751, "PM010": 0, "PM011": 0}
    add(checks, "project_metric_reconciliation", all(project_values.get(k) == v for k, v in exact.items()), {"checked_metrics": len(exact)})
    add(checks, "provider_metric_reconciliation", all(provider_values.get(k) == v for k, v in provider_exact.items()), {"checked_metrics": len(provider_exact)})

    available = [r for r in tables["FactPartitionStatus"] if r["AvailableFlag"] == "1"]
    excluded = [r for r in tables["FactPartitionStatus"] if r["PartitionStatus"] == "EXCLUDED"]
    add(checks, "period_scope", len(available) == 76 and len(excluded) == 8 and all(r["ReconciliationStatus"] == "PASS" for r in available), {"available": len(available), "excluded": len(excluded)})

    status_rows = tables["FactAnalyticalStatus"]
    component_vocab = {"COMPLETE", "IN PROGRESS", "PENDING", "DEFERRED"}
    audit_vocab = {"PASS", "PENDING", "NOT_APPLICABLE"}
    add(checks, "analytical_status_vocabulary", all(r["ComponentStatus"] in component_vocab and r["IndependentAuditStatus"] in audit_vocab for r in status_rows), {"rows": len(status_rows)})
    must_complete = {"Primary race M1 estimation", "Primary race M2 estimation", "Primary race M3 estimation", "Primary gender M1 estimation"}
    completed = {r["ComponentName"] for r in status_rows if r["ComponentStatus"] == "COMPLETE"}
    pending = {r["ComponentName"] for r in status_rows if r["ComponentStatus"] == "PENDING"}
    add(checks, "pause_status_alignment", must_complete <= completed and "Primary gender M2 estimation" in pending and "Final independent analytical-release audit" in pending, {"completed_estimation_items": sorted(must_complete), "gender_m2_pending": "Primary gender M2 estimation" in pending})

    synthetic_rows = tables["FactSyntheticDemonstration"]
    syn_input = sum(int(r["MetricValue"]) for r in synthetic_rows if r["DemoSection"] == "Schema reconciliation" and r["MetricName"] == "Input rows")
    syn_output = sum(int(r["MetricValue"]) for r in synthetic_rows if r["DemoSection"] == "Schema reconciliation" and r["MetricName"] == "Output rows")
    add(checks, "synthetic_label_and_reconciliation", syn_input == syn_output == 800 and all(r["SyntheticFlag"].lower() == "true" and r["DisclosureClass"] == "SYNTHETIC_PUBLIC_SAFE" for r in synthetic_rows), {"input_rows": syn_input, "output_rows": syn_output})

    dictionary = read_csv(root / "METRIC_AND_MEASURE_DICTIONARY.csv")
    dax_text = (root / "POWER_BI_MEASURES.dax").read_text(encoding="utf-8")
    dax_names = [m.group(1).strip() for m in re.finditer(r"(?m)^([^/\s][^\n=]*) =\s*$", dax_text)]
    dict_names = [r["MeasureName"] for r in dictionary]
    add(checks, "dax_dictionary_alignment", dax_names == dict_names and len(dax_names) == 33, {"dax_measures": len(dax_names), "dictionary_measures": len(dict_names)})

    visuals = read_csv(root / "POWER_BI_VISUAL_SPECIFICATION.csv")
    pages = {int(r["PageNumber"]) for r in visuals}
    ids = [r["VisualID"] for r in visuals]
    in_bounds = all(int(r["X"]) >= 0 and int(r["Y"]) >= 0 and int(r["X"]) + int(r["Width"]) <= 1280 and int(r["Y"]) + int(r["Height"]) <= 720 for r in visuals)
    add(checks, "visual_contract", pages == set(range(1, 8)) and len(ids) == len(set(ids)) == 63 and in_bounds, {"pages": sorted(pages), "visuals": len(ids), "unique_ids": len(set(ids)), "all_in_bounds": in_bounds})

    xlsx = data / "POWER_BI_IMPORT.xlsx"
    xlsx_tables: set[str] = set()
    xlsx_sheet_count = 0
    has_external_links = False
    if xlsx.is_file() and zipfile.is_zipfile(xlsx):
        with zipfile.ZipFile(xlsx) as zf:
            names = zf.namelist()
            has_external_links = any(name.startswith("xl/externalLinks/") for name in names)
            workbook_xml = ET.fromstring(zf.read("xl/workbook.xml"))
            ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            xlsx_sheet_count = len(workbook_xml.findall("m:sheets/m:sheet", ns))
            for name in names:
                if name.startswith("xl/tables/table") and name.endswith(".xml"):
                    node = ET.fromstring(zf.read(name))
                    xlsx_tables.add(node.attrib.get("name", ""))
    add(checks, "excel_import_structure", xlsx_sheet_count == 1 and xlsx_tables == set(expected_tables) and not has_external_links, {"sheets": xlsx_sheet_count, "named_tables": len(xlsx_tables), "external_links": has_external_links})

    manifest = read_csv(root / "DASHBOARD_FILE_MANIFEST.csv")
    manifest_map = {r["RelativePath"]: r for r in manifest}
    manifest_exclusions = {
        "DASHBOARD_FILE_MANIFEST.csv", "DASHBOARD_FILE_MANIFEST.sha256",
        "INDEPENDENT_DASHBOARD_PACKAGE_AUDIT.json", "INDEPENDENT_DASHBOARD_PACKAGE_AUDIT.sha256",
    }
    actual_core = set()
    junctions_or_links = []
    for current, dirs, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        for dirname in dirs:
            candidate = current_path / dirname
            if candidate.is_symlink() or os.path.islink(candidate):
                junctions_or_links.append(candidate.relative_to(root).as_posix())
        for filename in files:
            rel = (current_path / filename).relative_to(root).as_posix()
            if rel not in manifest_exclusions:
                actual_core.add(rel)
    listed = set(manifest_map)
    missing_from_manifest = sorted(actual_core - listed)
    stale_manifest_rows = sorted(listed - actual_core)
    hash_failures = [rel for rel in sorted(actual_core & listed) if sha256(root / rel) != manifest_map[rel]["SHA256"]]
    add(checks, "manifest_coverage_and_hashes", not missing_from_manifest and not stale_manifest_rows and not hash_failures, {"listed": len(listed), "actual_core": len(actual_core), "missing": missing_from_manifest, "stale": stale_manifest_rows, "hash_failures": hash_failures})
    sidecar = (root / "DASHBOARD_FILE_MANIFEST.sha256").read_text(encoding="utf-8").strip().split()[0]
    add(checks, "manifest_root_checksum", sidecar == sha256(root / "DASHBOARD_FILE_MANIFEST.csv"), {"matches": sidecar == sha256(root / "DASHBOARD_FILE_MANIFEST.csv")})
    add(checks, "no_filesystem_links", not junctions_or_links, {"links": junctions_or_links})

    text_extensions = {".md", ".txt", ".csv", ".json", ".dax", ".mjs", ".py", ".sha256"}
    private_path_hits = []
    email_hits = []
    ten_digit_csv_values = []
    prohibited_columns = {"npi", "patient_id", "visit_key", "source_record_id", "facility_id", "estimate", "coefficient", "standard_error", "ci95_low", "ci95_high", "p_value", "q_value"}
    prohibited_column_hits = []
    for file in root.rglob("*"):
        if not file.is_file() or file.name.startswith("INDEPENDENT_DASHBOARD_PACKAGE_AUDIT"):
            continue
        if file.suffix.lower() in text_extensions:
            text = file.read_text(encoding="utf-8-sig", errors="strict")
            if re.search(r"(?i)\b[A-Z]:\\", text) or re.search(r"(?i)users[\\/][^\\/\s]+", text):
                private_path_hits.append(file.relative_to(root).as_posix())
            if re.search(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", text):
                email_hits.append(file.relative_to(root).as_posix())
        if file.parent == data and file.suffix.lower() == ".csv":
            rows = read_csv(file)
            if rows:
                headers = {h.lower() for h in rows[0]}
                prohibited_column_hits.extend(f"{file.name}:{h}" for h in sorted(headers & prohibited_columns))
                for row in rows:
                    for value in row.values():
                        if re.fullmatch(r"\d{10}", value.strip()):
                            ten_digit_csv_values.append(f"{file.name}:{value}")
    add(checks, "no_private_paths", not private_path_hits, {"hits": private_path_hits})
    add(checks, "no_email_addresses", not email_hits, {"hits": email_hits})
    add(checks, "no_identifier_or_result_columns", not prohibited_column_hits and not ten_digit_csv_values, {"prohibited_columns": prohibited_column_hits, "ten_digit_values": ten_digit_csv_values[:10]})

    disclosure = json.loads((root / "PUBLIC_DASHBOARD_DISCLOSURE_AUDIT.json").read_text(encoding="utf-8"))
    preparation = json.loads((root / "DASHBOARD_PREPARATION_VALIDATION.json").read_text(encoding="utf-8"))
    add(checks, "embedded_audits_pass", disclosure.get("overall_status") == "PASS" and preparation.get("overall_status") == "PASS", {"disclosure": disclosure.get("overall_status"), "preparation": preparation.get("overall_status")})

    source_map = {
        "SRC_P1_MANIFEST": project / "outputs/florida_ed_full_build_20260724/build_manifest_final.json",
        "SRC_P1_QA": project / "outputs/florida_ed_full_build_20260724/qa/qa_summary.json",
        "SRC_P1_INDEPENDENT": project / "outputs/florida_ed_full_build_20260724/qa/independent_release_validation.json",
        "SRC_FACT_DICTIONARY": project / "outputs/florida_ed_full_build_20260724/documentation/fact_field_dictionary.csv",
        "SRC_PAUSE": project / "outputs/florida_ed_concordance_analysis_20260726/qa/user_authorized_handoff_pause_20260809T211227Z.json",
        "SRC_PROVIDER_PUBLIC": portfolio / "evidence/provider_v2_summary.json",
        "SRC_COHORT_PUBLIC": portfolio / "evidence/phase2_cohort_summary.json",
        "SRC_HISTORICAL_PUBLIC": portfolio / "evidence/historical_validation_summary.json",
        "SRC_PROVIDER_QA": project / "outputs/florida_ed_concordance_analysis_20260726/qa/provider_master_v2_qa.json",
        "SRC_RACE_QA": project / "outputs/florida_ed_concordance_analysis_20260726/qa/provider_race_proxy_v2_qa.json",
        "SRC_GENDER_GATE": project / "outputs/florida_ed_concordance_analysis_20260726/qa/provider_gender_measurement_checkpoint.json",
        "SRC_HISTORICAL_GATE": project / "outputs/florida_ed_concordance_analysis_20260726/qa/historical_provider_v2_pre_estimation_gate.json",
        "SRC_HISTORICAL_AUDIT": project / "outputs/florida_ed_concordance_analysis_20260726/qa/independent_historical_results_audit.json",
        "SRC_SYNTHETIC_SCHEMA": portfolio / "synthetic_demo/expected_outputs/schema_reconciliation.csv",
        "SRC_SYNTHETIC_CATEGORY": portfolio / "synthetic_demo/expected_outputs/category_summary.csv",
        "SRC_SYNTHETIC_QA": portfolio / "synthetic_demo/expected_outputs/qa_summary.json",
        "SRC_METHOD": portfolio / "METHODOLOGY.md",
        "SRC_PRIVACY": portfolio / "DATA_ACCESS_AND_PRIVACY.md",
    }
    recorded_sources = preparation.get("source_inventory", {})
    source_hash_failures = []
    for key, source_path in source_map.items():
        if not source_path.is_file() or recorded_sources.get(key, {}).get("sha256") != sha256(source_path):
            source_hash_failures.append(key)
    add(checks, "source_hash_immutability", not source_hash_failures, {"checked_sources": len(source_map), "failures": source_hash_failures})

    status_statement = (
        "Phase 1 complete and independently validated. Phase 2 measurement, cohort construction, historical analyses, "
        "and primary race M1-M3 estimation complete; primary gender M1 complete. Remaining primary and sensitivity "
        "analyses and the final independent analytical-release audit are pending."
    )
    readme = (root / "00_READ_ME_FIRST.md").read_text(encoding="utf-8")
    add(checks, "controlled_status_statement", status_statement in readme and status_statement in dax_text, {"readme": status_statement in readme, "dax": status_statement in dax_text})

    failed = [c for c in checks if not c["passed"]]
    audit = {
        "audit_id": "independent_power_bi_dashboard_package_audit_v1",
        "overall_status": "PASS" if not failed else "FAIL_CLOSED",
        "checks_passed": len(checks) - len(failed),
        "checks_total": len(checks),
        "failed_check_ids": [c["check_id"] for c in failed],
        "checks": checks,
        "scope": "Public-safe dashboard preparation package; no encounter rows or numerical concordance estimates inspected",
        "phase1_or_phase2_modified": False,
        "publication_authorized": False,
    }
    if args.write_audit:
        audit_path = root / "INDEPENDENT_DASHBOARD_PACKAGE_AUDIT.json"
        audit_path.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
        checksum_path = root / "INDEPENDENT_DASHBOARD_PACKAGE_AUDIT.sha256"
        checksum_path.write_text(f"{sha256(audit_path)}  INDEPENDENT_DASHBOARD_PACKAGE_AUDIT.json\n", encoding="utf-8")
    print(json.dumps({k: audit[k] for k in ("audit_id", "overall_status", "checks_passed", "checks_total", "failed_check_ids")}, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
