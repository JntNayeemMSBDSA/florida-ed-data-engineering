#!/usr/bin/env python3
"""Build a deterministic SHA-256 inventory for the sanitized release."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "REPOSITORY_INVENTORY.csv"
PROVENANCE = ROOT / "SOURCE_PROVENANCE.csv"
IGNORED_PARTS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "generated", "output"}
FIELDS = [
    "repository_path",
    "size_bytes",
    "sha256",
    "source_class",
    "source_relative_path",
    "source_sha256",
    "sanitization_note",
]


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def files() -> list[Path]:
    return sorted(
        path
        for path in ROOT.rglob("*")
        if path.is_file()
        and path != OUTPUT
        and not any(part in IGNORED_PARTS for part in path.relative_to(ROOT).parts)
    )


def provenance() -> dict[str, dict[str, str]]:
    if not PROVENANCE.exists():
        return {}
    with PROVENANCE.open(newline="", encoding="utf-8-sig") as stream:
        return {row["repository_path"]: row for row in csv.DictReader(stream)}


def main() -> None:
    source = provenance()
    rows: list[dict[str, object]] = []
    for path in files():
        rel = path.relative_to(ROOT).as_posix()
        origin = source.get(rel, {})
        rows.append(
            {
                "repository_path": rel,
                "size_bytes": path.stat().st_size,
                "sha256": digest(path),
                "source_class": origin.get("source_class", "release_authored"),
                "source_relative_path": origin.get("source_relative_path", rel),
                "source_sha256": origin.get("source_sha256", digest(path)),
                "sanitization_note": origin.get(
                    "transformation",
                    "authored or revised in the sanitized release; contains no restricted data or unpublished estimates",
                ),
            }
        )
    rows.append(
        {
            "repository_path": "REPOSITORY_INVENTORY.csv",
            "size_bytes": "",
            "sha256": "",
            "source_class": "release_generated",
            "source_relative_path": "REPOSITORY_INVENTORY.csv",
            "source_sha256": "",
            "sanitization_note": "self-entry; hash intentionally blank to avoid recursive self-hashing",
        }
    )
    with OUTPUT.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} inventory rows to {OUTPUT.name}")


if __name__ == "__main__":
    main()
