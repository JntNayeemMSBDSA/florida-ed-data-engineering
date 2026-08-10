#!/usr/bin/env python3
"""Fail-closed validation for the full sanitized Florida ED handoff."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
EXPECTED_PHASE2_SOURCES = 108
EXPECTED_DASHBOARD_PAGES = 7
EXPECTED_DASHBOARD_CHECKS = 17


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def load_public_validator():
    path = ROOT / "scripts" / "validate_public_repository.py"
    spec = importlib.util.spec_from_file_location("public_validator", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load public repository validator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def add(errors: list[str], condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def validate_provenance(errors: list[str]) -> None:
    path = ROOT / "SOURCE_PROVENANCE.csv"
    add(errors, path.is_file(), "SOURCE_PROVENANCE.csv is missing")
    if not path.is_file():
        return
    with path.open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    add(errors, len(rows) >= 350, f"Source provenance is unexpectedly small: {len(rows)} rows")
    for row in rows:
        rel = row.get("repository_path", "")
        if not (ROOT / rel).is_file():
            errors.append(f"Provenance target is missing: {rel}")
        if not HEX64.fullmatch(row.get("source_sha256", "")):
            errors.append(f"Invalid source SHA-256 in provenance: {rel}")


def validate_inventory(errors: list[str]) -> None:
    path = ROOT / "REPOSITORY_INVENTORY.csv"
    add(errors, path.is_file(), "REPOSITORY_INVENTORY.csv is missing")
    if not path.is_file():
        return
    with path.open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        rel = row.get("repository_path", "")
        if rel == "REPOSITORY_INVENTORY.csv":
            continue
        target = ROOT / rel
        if not target.is_file():
            errors.append(f"Inventory target is missing: {rel}")
            continue
        if row.get("sha256", "").lower() != digest(target).lower():
            errors.append(f"Inventory SHA-256 mismatch: {rel}")


def validate_dashboard(errors: list[str]) -> None:
    project = ROOT / "dashboard" / "powerbi_project"
    required = [
        project / "Florida_ED_Project_Portfolio_Dashboard.pbip",
        project / "POWER_BI_PROJECT_MANIFEST.json",
        project / "POWER_BI_PROJECT_STATIC_VALIDATION.json",
        ROOT / "dashboard" / "dashboard_qa" / "POWER_BI_DESKTOP_RENDER_QA.json",
    ]
    for path in required:
        add(errors, path.is_file(), f"Dashboard artifact is missing: {path.relative_to(ROOT).as_posix()}")
    static_path = required[2]
    if static_path.is_file():
        static = json.loads(static_path.read_text(encoding="utf-8"))
        add(errors, static.get("overall_status") == "PASS", "Dashboard static validation is not PASS")
        add(errors, static.get("checks_passed") == EXPECTED_DASHBOARD_CHECKS, "Dashboard did not pass 17 checks")
        add(errors, static.get("checks_total") == EXPECTED_DASHBOARD_CHECKS, "Dashboard static check total is not 17")
    qa_dir = ROOT / "dashboard" / "dashboard_qa"
    images = sorted(qa_dir.glob("*.png"))
    add(errors, len(images) == EXPECTED_DASHBOARD_PAGES, f"Expected 7 dashboard screenshots; found {len(images)}")
    add(errors, len({digest(path) for path in images}) == EXPECTED_DASHBOARD_PAGES, "Dashboard screenshots are not seven unique images")
    qa_path = required[3]
    if qa_path.is_file():
        qa = json.loads(qa_path.read_text(encoding="utf-8"))
        add(errors, qa.get("status") == "PASS", "Power BI Desktop render QA is not PASS")
        add(errors, qa.get("runtime_checks", {}).get("unpublished_concordance_estimates_inspected") is False, "Dashboard QA does not preserve the estimate-inspection boundary")


def validate_construction(errors: list[str]) -> None:
    path = ROOT / "release" / "CONSTRUCTION_MANIFEST.json"
    add(errors, path.is_file(), "Construction manifest is missing")
    if not path.is_file():
        return
    manifest = json.loads(path.read_text(encoding="utf-8"))
    add(errors, manifest.get("unpublished_estimates_inspected_or_copied") is False, "Construction manifest does not confirm estimates were excluded")
    add(errors, manifest.get("phase2_source_files") == EXPECTED_PHASE2_SOURCES, "Construction manifest Phase 2 source count is not 108")
    add(errors, manifest.get("dashboard_pages") == EXPECTED_DASHBOARD_PAGES, "Construction manifest dashboard page count is not 7")


def validate_git(errors: list[str]) -> None:
    if not (ROOT / ".git").exists():
        return
    remote = subprocess.run(
        ["git", "-C", str(ROOT), "remote"], capture_output=True, text=True, check=True
    ).stdout.strip()
    # A remote is allowed only after the user-authorized deployment step. The
    # validator records its presence without interpreting unpublished results.
    if remote:
        print(f"GIT REMOTE PRESENT: {remote}")


def main() -> None:
    errors: list[str] = []
    public_validator = load_public_validator()
    errors.extend(public_validator.validate_repository(ROOT, run_demo=True))
    phase2_sources = list((ROOT / "src" / "phase2_full").rglob("*.py")) + list(
        (ROOT / "src" / "phase2_full").rglob("*.ps1")
    )
    add(errors, len(phase2_sources) == EXPECTED_PHASE2_SOURCES, f"Expected 108 Phase 2 source files; found {len(phase2_sources)}")
    validate_provenance(errors)
    validate_inventory(errors)
    validate_dashboard(errors)
    validate_construction(errors)
    try:
        validate_git(errors)
    except subprocess.CalledProcessError as exc:
        errors.append(f"Git inspection failed: {exc}")
    if errors:
        print(f"FULL RELEASE VALIDATION: FAIL_CLOSED ({len(errors)} issues)")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)
    print("FULL RELEASE VALIDATION: PASS")
    print("Public safety, claims, synthetic reproducibility, provenance, inventory, dashboard, and construction gates passed")


if __name__ == "__main__":
    main()
