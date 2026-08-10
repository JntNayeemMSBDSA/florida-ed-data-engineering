#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/04aa_finalize_provider_source_hashes.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Finalize hashes for the large current CMS provider sources.

This provenance-only checkpoint never rewrites provider or encounter data.
It is safe to run after provider master construction and binds the two current
CMS source files to their manifest records with SHA-256 digests.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SOURCE_KEYS = (
    "cms_doctors_clinicians_national_downloadable_2026_06_26",
    "cms_doctors_clinicians_facility_affiliation_2026_06_26",
)


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path, block_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(block_size), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    args = parser.parse_args()

    phase2 = args.phase2.resolve()
    manifest_path = (
        phase2 / "qa" / "provider_master_v2_source_manifest.json"
    )
    audit_path = (
        phase2 / "qa" / "provider_master_v2_large_source_hash_audit.json"
    )
    if not manifest_path.exists():
        raise FileNotFoundError(manifest_path)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sources = manifest.get("sources", {})
    audit_rows: list[dict[str, Any]] = []
    for key in SOURCE_KEYS:
        record = sources.get(key)
        if not isinstance(record, dict):
            raise RuntimeError(f"Missing source manifest record: {key}")
        path = Path(str(record.get("path", ""))).resolve()
        if not path.exists():
            raise FileNotFoundError(path)
        observed_bytes = path.stat().st_size
        expected_bytes = int(record.get("bytes", -1))
        if observed_bytes != expected_bytes:
            raise RuntimeError(
                f"Source size changed for {key}: "
                f"{observed_bytes} != {expected_bytes}"
            )
        digest = sha256_file(path)
        record["sha256"] = digest
        record["hash_status"] = "computed"
        record["hash_completed_utc"] = now_utc()
        audit_rows.append(
            {
                "source_key": key,
                "path": str(path),
                "bytes": observed_bytes,
                "sha256": digest,
                "size_matches_provider_build_manifest": True,
            }
        )

    manifest["large_source_hashes_finalized_utc"] = now_utc()
    manifest["large_source_hash_checkpoint"] = str(audit_path)
    audit = {
        "checkpoint_id": "PROVIDER_MASTER_V2_LARGE_SOURCE_HASH_AUDIT",
        "created_utc": now_utc(),
        "status": "PASS",
        "provider_or_encounter_data_rewritten": False,
        "sources": audit_rows,
    }
    atomic_json(audit_path, audit)
    atomic_json(manifest_path, manifest)
    print(json.dumps(audit, indent=2), flush=True)


if __name__ == "__main__":
    main()
