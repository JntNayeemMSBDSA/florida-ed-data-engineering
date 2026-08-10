# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/36b_audit_project_development_history.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PHASE2 = Path(__file__).resolve().parents[1]
WORKSPACE = PHASE2.parents[1]
EMAIL_SOURCE = (
    WORKSPACE / "tmp" / "email_context_20260725" / "emails_extracted.txt"
)
INDEX = PHASE2 / "documentation" / "Project_Development_History_Source_Index.md"
OUTPUT = PHASE2 / "qa" / "project_development_history_source_audit.json"
EXPECTED_SHA256 = (
    "e4d62f526f39301cbe1243cad4d8a7d7d6a0195b8848b00f49ab0bfa5cdb432a"
)
REQUIRED_LABELS = [
    "P15",
    "P16",
    "P32",
    "P58",
    "P64",
    "P76",
    "P128",
    "P135",
    "P154",
    "P155",
    "P172",
    "P236",
    "P247",
    "P289",
    "P309",
    "P324",
    "P328",
    "P354",
    "P379",
    "P385",
    "P591",
    "P630",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def main() -> None:
    checks: list[dict[str, Any]] = []

    def add(check_id: str, passed: bool, evidence: Any) -> None:
        checks.append(
            {
                "check_id": check_id,
                "passed": bool(passed),
                "evidence": evidence,
            }
        )

    email_exists = EMAIL_SOURCE.is_file()
    observed_sha = sha256(EMAIL_SOURCE) if email_exists else ""
    add(
        "preserved_email_extraction_hash_matches",
        email_exists and observed_sha == EXPECTED_SHA256,
        {
            "workspace_relative_path": (
                EMAIL_SOURCE.relative_to(WORKSPACE).as_posix()
                if email_exists
                else "tmp/email_context_20260725/emails_extracted.txt"
            ),
            "expected_sha256": EXPECTED_SHA256,
            "observed_sha256": observed_sha,
            "bytes": EMAIL_SOURCE.stat().st_size if email_exists else 0,
        },
    )

    email_text = (
        EMAIL_SOURCE.read_text(encoding="utf-8", errors="replace")
        if email_exists
        else ""
    )
    missing_labels = [
        label for label in REQUIRED_LABELS if f"[{label}]" not in email_text
    ]
    add(
        "all_indexed_email_paragraph_labels_exist",
        not missing_labels,
        {
            "required_labels": REQUIRED_LABELS,
            "missing_labels": missing_labels,
        },
    )

    index_exists = INDEX.is_file()
    index_text = (
        INDEX.read_text(encoding="utf-8", errors="strict")
        if index_exists
        else ""
    )
    add(
        "history_index_binds_email_hash_and_internal_disposition",
        index_exists
        and EXPECTED_SHA256 in index_text.lower()
        and "INTERNAL — DO NOT PUBLISH" in index_text,
        {
            "index_path": (
                INDEX.relative_to(WORKSPACE).as_posix()
                if index_exists
                else ""
            ),
            "hash_present": EXPECTED_SHA256 in index_text.lower(),
            "internal_disposition_present": (
                "INTERNAL — DO NOT PUBLISH" in index_text
            ),
        },
    )

    absolute_windows_paths = re.findall(
        r"(?i)(?:^|[\s`\"'])\b[A-Z]:\\[^\r\n`\"']+",
        index_text,
    )
    add(
        "history_index_contains_no_absolute_windows_paths",
        not absolute_windows_paths,
        {"matches": absolute_windows_paths},
    )

    normalized_index = " ".join(index_text.split())
    required_boundaries = [
        "not evidence that an analysis was correct",
        "Any numerical or substantive finding must instead trace",
        "design history only",
        "do not control the final cohort",
        "does not support",
    ]
    missing_boundaries = [
        phrase for phrase in required_boundaries if phrase not in normalized_index
    ]
    add(
        "history_index_separates_documentary_context_from_results",
        not missing_boundaries,
        {"missing_required_boundary_phrases": missing_boundaries},
    )

    passed = sum(check["passed"] for check in checks)
    payload = {
        "audit_id": "project_development_history_source_audit_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if passed == len(checks) else "FAIL",
        "checks_passed": passed,
        "checks_total": len(checks),
        "checks": checks,
        "public_release_authorized": False,
        "finding_evidence_authorized": False,
        "permitted_use": (
            "Internal documentary reconstruction of project development and "
            "specification timing only."
        ),
    }
    atomic_json(OUTPUT, payload)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    if payload["status"] != "PASS":
        raise SystemExit("Project development history source audit failed")


if __name__ == "__main__":
    main()
