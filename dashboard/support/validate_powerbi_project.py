from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path


PACKAGE = Path(__file__).resolve().parent.parent
PROJECT_ROOT = Path(
    os.environ.get(
        "FLORIDA_ED_PBI_PROJECT_ROOT",
        str(Path.home() / "Desktop" / "Florida_ED_PBI_Build"),
    )
).resolve()
PROJECT = "Florida_ED_Project_Portfolio_Dashboard"
MODEL = PROJECT_ROOT / f"{PROJECT}.SemanticModel"
REPORT = PROJECT_ROOT / f"{PROJECT}.Report"

EXPECTED_TABLES = {
    "DimPeriod": 84,
    "DimSchemaFamily": 5,
    "DimProjectStage": 5,
    "DimMetric": 25,
    "DimClinicalDomain": 9,
    "DimCodingMap": 6,
    "DimModelSpec": 3,
    "FactProjectCoverage": 14,
    "FactPartitionStatus": 84,
    "FactEnhancementCoverage": 20,
    "FactProviderMeasurement": 11,
    "FactValidationStatus": 20,
    "FactAnalyticalStatus": 20,
    "FactSyntheticDemonstration": 13,
}

EXPECTED_PAGES = [
    "Executive Overview",
    "Coverage & Standardization",
    "Clinical & Visit Enhancements",
    "Provider & Facility Measurement",
    "Cohort & Analytical Design",
    "Validation & Reproducibility",
    "Completion & Handoff",
]

PROHIBITED = [
    r"C:\\Users\\",
    r"AppData",
    r"MacTransfer",
    r"@(?:gmail|ou|msu|hotmail|outlook)\.",
    r"patient_id",
    r"\bnpi\b\s*[:=]\s*\d{10}",
    r"coefficient\s*[:=]\s*[-+]?\d",
    r"p[-_ ]?value\s*[:=]\s*(?:0|\.)",
    r"q[-_ ]?value\s*[:=]\s*(?:0|\.)",
    r"confidence interval\s*[:=]\s*[\[(]?[-+]?\d",
    r"Autonomous_Driving",
    r"Waymo",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def public_path(path: Path) -> str:
    """Return a repository-safe path for generated validation evidence."""
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return path.name


def check(checks: list[dict], name: str, passed: bool, evidence: object) -> None:
    checks.append({"check": name, "passed": bool(passed), "evidence": evidence})


def main() -> int:
    checks: list[dict] = []
    pbip = PROJECT_ROOT / f"{PROJECT}.pbip"
    check(checks, "pbip_exists", pbip.exists(), public_path(pbip))

    json_failures = []
    for path in REPORT.rglob("*.json"):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            json_failures.append({"file": str(path.relative_to(PROJECT_ROOT)), "error": str(exc)})
    check(checks, "all_report_json_parses", not json_failures, json_failures)

    table_dir = MODEL / "definition" / "tables"
    table_files = {p.stem: p for p in table_dir.glob("*.tmdl")}
    expected_names = set(EXPECTED_TABLES) | {"Dashboard Measures"}
    check(checks, "semantic_table_inventory", set(table_files) == expected_names, {"actual": sorted(table_files), "expected": sorted(expected_names)})

    row_checks = {}
    for table, expected in EXPECTED_TABLES.items():
        source_rows = sum(1 for _ in (PACKAGE / "dashboard_data" / f"{table}.csv").open(encoding="utf-8-sig")) - 1
        row_checks[table] = {"observed": source_rows, "expected": expected, "passed": source_rows == expected}
    check(checks, "source_row_counts", all(v["passed"] for v in row_checks.values()), row_checks)

    measures_text = table_files["Dashboard Measures"].read_text(encoding="utf-8")
    measure_count = len(re.findall(r"(?m)^\s*measure ", measures_text))
    check(checks, "measure_count", measure_count == 34, {"observed": measure_count, "expected": 34, "documented": 33, "supplemental_visual_only": 1})

    relationships = (MODEL / "definition" / "relationships.tmdl").read_text(encoding="utf-8")
    relationship_count = len(re.findall(r"(?m)^relationship ", relationships))
    check(checks, "relationship_count", relationship_count == 8, relationship_count)
    check(checks, "single_direction_relationships", "crossFilteringBehavior" not in relationships, "Default single-direction behavior retained")

    table_sources = "\n".join(path.read_text(encoding="utf-8") for path in table_files.values())
    invalid_m_type_tokens = sorted(
        set(re.findall(r"=\s*type\s+(?:text|date|logical)\b", table_sources))
    )
    check(
        checks,
        "power_query_primitive_type_syntax",
        not invalid_m_type_tokens,
        {
            "invalid_tokens": invalid_m_type_tokens,
            "requirement": "Primitive fields inside type table use text, date, or logical without a second type keyword",
        },
    )

    pages_meta = json.loads((REPORT / "definition" / "pages" / "pages.json").read_text(encoding="utf-8"))
    page_names = []
    visual_count = 0
    bounds_failures = []
    footer_pages = 0
    for page_id in pages_meta["pageOrder"]:
        page_dir = REPORT / "definition" / "pages" / page_id
        page = json.loads((page_dir / "page.json").read_text(encoding="utf-8"))
        page_names.append(page["displayName"])
        page_text = ""
        for visual_file in page_dir.glob("visuals/*/visual.json"):
            visual_count += 1
            raw = visual_file.read_text(encoding="utf-8")
            page_text += raw
            visual = json.loads(raw)
            pos = visual["position"]
            if pos["x"] < 0 or pos["y"] < 0 or pos["x"] + pos["width"] > 1280 or pos["y"] + pos["height"] > 720:
                bounds_failures.append(str(visual_file.relative_to(PROJECT_ROOT)))
        if "Public-safe metadata and synthetic demonstration only" in page_text:
            footer_pages += 1
    check(checks, "page_order_and_names", page_names == EXPECTED_PAGES, page_names)
    check(checks, "visual_inventory", visual_count == 76, {"observed": visual_count, "expected": 76, "contract_visuals": 63, "supplemental_page_subtitles_and_footers": 13})
    check(checks, "visual_bounds", not bounds_failures, bounds_failures)
    check(checks, "footer_on_every_page", footer_pages == 7, footer_pages)

    generated_audits = {"POWER_BI_PROJECT_MANIFEST.json", "POWER_BI_PROJECT_STATIC_VALIDATION.json"}
    project_text = "\n".join(
        p.read_text(encoding="utf-8", errors="ignore")
        for p in PROJECT_ROOT.rglob("*")
        if p.is_file() and p.name not in generated_audits and p.suffix.lower() in {".json", ".tmdl", ".pbip", ".pbir"}
    )
    prohibited_hits = {
        f"prohibited_pattern_{index:02d}": bool(re.search(pattern, project_text, re.IGNORECASE))
        for index, pattern in enumerate(PROHIBITED, start=1)
    }
    check(checks, "privacy_and_unrelated_content_scan", not any(prohibited_hits.values()), prohibited_hits)
    check(checks, "no_external_file_sources", "File.Contents" not in project_text and "Excel.Workbook" not in project_text, "All dashboard data is embedded public-safe metadata")
    affirmative_causal = bool(re.search(r"(?<!not )(?<!no )causal (?:effect|impact)", project_text, re.IGNORECASE))
    check(checks, "no_causal_claim", not affirmative_causal, "Association language retained; negated causal-language disclosures are allowed")
    required_language = ["not BISG", "not self-reported", "never silently pooled", "Phase 1 must remain immutable", "observational associations"]
    language = {item: item.lower() in project_text.lower() for item in required_language}
    check(checks, "scientific_guardrail_language", all(language.values()), language)

    qa_images = sorted((PACKAGE / "dashboard_qa").glob("*.png"))
    qa_hashes = [sha256(path) for path in qa_images]
    check(
        checks,
        "desktop_render_qa_capture_set",
        len(qa_images) == 7 and len(set(qa_hashes)) == 7,
        {"images": [path.name for path in qa_images], "unique_hashes": len(set(qa_hashes))},
    )

    files = []
    for path in sorted(
        p
        for p in PROJECT_ROOT.rglob("*")
        if p.is_file() and ".pbi" not in p.parts and p.name not in generated_audits
    ):
        files.append({"path": str(path.relative_to(PROJECT_ROOT)).replace("\\", "/"), "bytes": path.stat().st_size, "sha256": sha256(path)})
    manifest = {"project": PROJECT, "files": files}
    manifest_path = PROJECT_ROOT / "POWER_BI_PROJECT_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8", newline="\n")

    overall = "PASS" if all(c["passed"] for c in checks) else "FAIL_CLOSED"
    report = {"overall_status": overall, "scope": "Static PBIP/PBIR/TMDL validation before Power BI Desktop open; no unpublished analytical estimates inspected", "checks_passed": sum(c["passed"] for c in checks), "checks_total": len(checks), "checks": checks, "manifest": public_path(manifest_path)}
    report_path = PROJECT_ROOT / "POWER_BI_PROJECT_STATIC_VALIDATION.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8", newline="\n")
    print(json.dumps(report, indent=2))
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
