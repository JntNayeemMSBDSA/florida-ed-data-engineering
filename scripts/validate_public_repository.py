#!/usr/bin/env python3
"""Validate repository completeness, reproducibility, and public safety."""

from __future__ import annotations

import argparse
import csv
import importlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


REQUIRED_FILES = {
    "README.md",
    "PROJECT_STATUS.md",
    "METHODOLOGY.md",
    "CONTRIBUTIONS.md",
    "DATA_ACCESS_AND_PRIVACY.md",
    "NOTICE.md",
    "VIDEO_WALKTHROUGH_SCRIPT.md",
    "REPOSITORY_INVENTORY.csv",
    ".gitignore",
    "requirements.txt",
    "docs/architecture.md",
    "docs/prototype_to_production.md",
    "docs/validation_summary.md",
    "configs/synthetic_demo.yaml",
    "configs/full_production.template.yaml",
    "synthetic_demo/README.md",
    "synthetic_demo/generate_synthetic_data.py",
    "synthetic_demo/run_demo_pipeline.py",
    "tests/test_synthetic_pipeline.py",
    "tests/test_public_repository_safety.py",
    "tests/test_documented_claims.py",
    "evidence/phase1_build_summary.json",
    "evidence/phase1_validation_summary.json",
    "evidence/provider_v2_summary.json",
    "evidence/phase2_cohort_summary.json",
    "evidence/historical_validation_summary.json",
    "evidence/current_project_status.json",
    "scripts/build_sanitized_evidence.py",
    "scripts/validate_public_repository.py",
}

PROHIBITED_EXTENSIONS = {
    ".parquet",
    ".h5",
    ".hdf5",
    ".feather",
    ".sas7bdat",
    ".sas7bcat",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".mdb",
    ".dta",
    ".sav",
    ".npy",
    ".npz",
    ".mmap",
    ".memmap",
}
MAX_FILE_BYTES = 2 * 1024 * 1024
TEXT_EXTENSIONS = {".md", ".py", ".json", ".csv", ".yaml", ".yml", ".txt"}
SOURCE_USERNAME = "".join(("ja", "nna"))
WINDOWS_USER_PATH = re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s]+", re.I)
EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
SECRET = re.compile(
    r"(?i)(api[_-]?key|client[_-]?secret|password|access[_-]?token)\s*[:=]\s*['\"][^'\"]{8,}"
)
PRIVATE_KEY = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
NPI_JSON_FIELD = re.compile(
    r'(?i)"[^"\n]*npi[^"\n]*"\s*:\s*"?(\d{10})"?'
)
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
REQUIRED_README_CLAIMS = {
    "0.5%",
    "743,767",
    "148,686,146",
    "76",
    "2005",
    "2008",
    "2010",
    "2024",
    "342",
    "1,813,546",
    "60",
    "119,543,044",
    "16",
    "23,304,846",
    "2.0.0",
    "2020",
}
ALLOWED_HIDDEN = {".gitignore", ".gitattributes", ".git", ".platform"}
IGNORED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    "generated",
    "output",
}


def repository_files(root: Path) -> list[Path]:
    return [
        path
        for path in root.rglob("*")
        if path.is_file() and not any(part in IGNORED_DIRS for part in path.parts)
    ]


def relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def check_required(root: Path, errors: list[str]) -> None:
    missing = sorted(path for path in REQUIRED_FILES if not (root / path).is_file())
    if missing:
        errors.append("Missing required files: " + ", ".join(missing))


def check_location(root: Path, errors: list[str]) -> None:
    parts = {part.lower() for part in root.resolve().parts}
    protected = {
        "dataset",
        "florida_ed_full_build_20260724",
        "florida_ed_concordance_analysis_20260726",
    }
    overlap = sorted(parts & protected)
    if overlap:
        errors.append("Repository is nested in a protected source location: " + ", ".join(overlap))


def check_filesystem_safety(root: Path, errors: list[str]) -> None:
    for path in root.rglob("*"):
        if any(part in IGNORED_DIRS for part in path.parts):
            continue
        rel = relative(path, root)
        try:
            stat = path.lstat()
        except OSError as exc:
            errors.append(f"Cannot inspect {rel}: {exc}")
            continue
        reparse = bool(getattr(stat, "st_file_attributes", 0) & 0x400)
        if path.is_symlink() or reparse:
            errors.append(f"Symlink or junction is not permitted: {rel}")
        if path.name.startswith(".") and path.name not in ALLOWED_HIDDEN:
            errors.append(f"Unexpected hidden artifact: {rel}")
        if path.is_file():
            if path.suffix.lower() in PROHIBITED_EXTENSIONS:
                errors.append(f"Prohibited data extension: {rel}")
            if path.stat().st_size > MAX_FILE_BYTES:
                errors.append(f"File exceeds {MAX_FILE_BYTES} bytes: {rel}")


def check_text_safety(root: Path, errors: list[str]) -> None:
    for path in repository_files(root):
        if path.suffix.lower() not in TEXT_EXTENSIONS and path.name != ".gitignore":
            continue
        rel = relative(path, root)
        text = path.read_text(encoding="utf-8", errors="replace")
        self_pattern_file = (
            rel == "scripts/validate_public_repository.py"
            or (rel.startswith("dashboard/support/") and path.name.startswith("validate_"))
        )
        if not self_pattern_file and WINDOWS_USER_PATH.search(text):
            errors.append(f"Absolute Windows user path found: {rel}")
        if not self_pattern_file and SOURCE_USERNAME.lower() in text.lower():
            errors.append(f"Source-workstation username found: {rel}")
        if not self_pattern_file and EMAIL.search(text):
            errors.append(f"Email address found: {rel}")
        if (
            not self_pattern_file
            and (SECRET.search(text) or PRIVATE_KEY.search(text) or "AKIA" in text)
        ):
            errors.append(f"Possible credential or secret found: {rel}")


def check_data_artifacts(root: Path, errors: list[str]) -> None:
    for path in repository_files(root):
        rel = relative(path, root)
        lower_name = path.name.lower()
        if path.suffix.lower() in {".csv", ".json"} and re.search(
            r"(?:coefficient|partial[_-]?estimate|model[_-]?result)", lower_name
        ):
            errors.append(f"Model result artifact is not permitted: {rel}")
        data_bearing_scope = rel.startswith("evidence/") or rel.startswith(
            "dashboard/dashboard_data/"
        )
        if path.suffix.lower() in {".csv", ".json"} and data_bearing_scope:
            text = path.read_text(encoding="utf-8", errors="replace")
            if path.suffix.lower() == ".json" and NPI_JSON_FIELD.search(text):
                errors.append(f"Ten-digit NPI value found in committed data artifact: {rel}")
            if path.suffix.lower() == ".csv":
                with path.open(newline="", encoding="utf-8", errors="replace") as stream:
                    reader = csv.DictReader(stream)
                    npi_fields = [name for name in (reader.fieldnames or []) if "npi" in name.lower()]
                    if any(
                        re.fullmatch(r"\d{10}", row.get(field, "") or "")
                        for row in reader
                        for field in npi_fields
                    ):
                        errors.append(f"Ten-digit NPI value found in committed data artifact: {rel}")
            if re.search(r'(?i)"?(sys_recid|patient_id|visit_key)"?\s*[:,]', text):
                errors.append(f"Encounter-level identifier field found in committed artifact: {rel}")


def check_markdown_links(root: Path, errors: list[str]) -> None:
    for path in repository_files(root):
        if path.suffix.lower() != ".md":
            continue
        text = path.read_text(encoding="utf-8")
        for target in MARKDOWN_LINK.findall(text):
            target = target.strip().split(maxsplit=1)[0].strip("<>")
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            local = target.split("#", 1)[0]
            if not local:
                continue
            resolved = (path.parent / local).resolve()
            if not resolved.exists():
                errors.append(f"Broken Markdown link in {relative(path, root)}: {target}")


def evidence_text(root: Path) -> str:
    values = []
    for path in sorted((root / "evidence").glob("*.json")):
        values.append(path.read_text(encoding="utf-8"))
    return "\n".join(values)


def check_claims(root: Path, errors: list[str]) -> None:
    readme = (root / "README.md").read_text(encoding="utf-8")
    evidence = evidence_text(root)
    for claim in sorted(REQUIRED_README_CLAIMS):
        if claim not in readme:
            errors.append(f"README is missing required quantitative claim: {claim}")
        if claim not in evidence and claim.replace(",", "") not in evidence:
            errors.append(f"README claim is absent from sanitized evidence: {claim}")
    prohibited = re.compile(
        r"(?i)(caused by|causal effect|statistically significant|p\s*[<=>]|q\s*[<=>])"
    )
    if prohibited.search(readme):
        errors.append("README contains prohibited causal or incomplete-result language")


def check_inventory(root: Path, errors: list[str]) -> None:
    path = root / "REPOSITORY_INVENTORY.csv"
    if not path.exists():
        return
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    indexed = {row["repository_path"]: row for row in rows}
    expected = {relative(path, root) for path in repository_files(root)}
    missing = sorted(expected - set(indexed))
    if missing:
        errors.append("Inventory is missing files: " + ", ".join(missing))
    for rel, row in indexed.items():
        if rel.startswith("src/") and rel.endswith(".py"):
            if not row.get("source_relative_path") or len(row.get("source_sha256", "")) != 64:
                errors.append(f"Production script provenance is incomplete: {rel}")
            script = root / rel
            if script.exists() and "Sanitized portfolio copy" not in script.read_text(encoding="utf-8")[:600]:
                errors.append(f"Production script lacks sanitization header: {rel}")


def check_python_syntax(root: Path, errors: list[str]) -> None:
    for path in repository_files(root):
        if path.suffix.lower() != ".py":
            continue
        try:
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
        except SyntaxError as exc:
            errors.append(f"Python syntax error in {relative(path, root)}: {exc}")


def check_requirements(root: Path, errors: list[str]) -> None:
    imports = {"pytest": "pytest"}
    for line in (root / "requirements.txt").read_text(encoding="utf-8").splitlines():
        clean = line.strip()
        if not clean or clean.startswith("#"):
            continue
        package = re.split(r"[<>=!~\[]", clean, maxsplit=1)[0].lower()
        module = imports.get(package, package.replace("-", "_"))
        try:
            importlib.import_module(module)
        except ImportError:
            errors.append(f"Requirement is not importable in this environment: {clean}")


def check_demo_reproducibility(root: Path, errors: list[str]) -> None:
    generator = root / "synthetic_demo" / "generate_synthetic_data.py"
    pipeline = root / "synthetic_demo" / "run_demo_pipeline.py"
    expected = root / "synthetic_demo" / "expected_outputs"
    with tempfile.TemporaryDirectory(prefix="fl_ed_public_demo_") as temporary:
        temp = Path(temporary)
        outputs: list[Path] = []
        for run in ("run_a", "run_b"):
            raw = temp / run / "raw"
            out = temp / run / "output"
            subprocess.run(
                [sys.executable, str(generator), "--output-dir", str(raw)],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                [
                    sys.executable,
                    str(pipeline),
                    "--input-dir",
                    str(raw),
                    "--output-dir",
                    str(out),
                ],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )
            outputs.append(out)
        for name in ("qa_summary.json", "schema_reconciliation.csv", "category_summary.csv"):
            first = (outputs[0] / name).read_bytes()
            second = (outputs[1] / name).read_bytes()
            if first != second:
                errors.append(f"Synthetic demo is not deterministic: {name}")
            expected_path = expected / name
            if not expected_path.exists() or first != expected_path.read_bytes():
                errors.append(f"Synthetic demo differs from committed expectation: {name}")


def validate_repository(root: Path, *, run_demo: bool = True) -> list[str]:
    errors: list[str] = []
    check_required(root, errors)
    check_location(root, errors)
    check_filesystem_safety(root, errors)
    check_text_safety(root, errors)
    check_data_artifacts(root, errors)
    check_markdown_links(root, errors)
    if (root / "README.md").exists() and (root / "evidence").exists():
        check_claims(root, errors)
    check_inventory(root, errors)
    check_python_syntax(root, errors)
    if (root / "requirements.txt").exists():
        check_requirements(root, errors)
    if run_demo and (root / "synthetic_demo" / "generate_synthetic_data.py").exists():
        try:
            check_demo_reproducibility(root, errors)
        except subprocess.CalledProcessError as exc:
            errors.append(f"Synthetic demo command failed: {exc.stderr or exc}")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--skip-demo", action="store_true")
    args = parser.parse_args()
    root = args.repository_root.resolve()
    errors = validate_repository(root, run_demo=not args.skip_demo)
    if errors:
        print(f"PUBLIC REPOSITORY VALIDATION: FAIL ({len(errors)} issues)")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)
    count = len(repository_files(root))
    size = sum(path.stat().st_size for path in repository_files(root))
    print("PUBLIC REPOSITORY VALIDATION: PASS")
    print(f"Checked {count} files ({size:,} bytes)")
    print("No prohibited data extensions, private paths, credentials, row-level identifiers, or model outputs found")
    print("Markdown links, claims, inventory, Python syntax, requirements, and synthetic reproducibility passed")


if __name__ == "__main__":
    main()
