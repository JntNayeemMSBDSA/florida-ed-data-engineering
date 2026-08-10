#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/44_compact_directional_intermediates.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Remove only large directional intermediates after an independent PASS.

The matrix/result manifests, hashes, encoders, support tables, result files,
and audit history are retained.  Exact deletion targets are enumerated and
validated beneath the supplied matrix and scratch roots before unlinking.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


FAMILIES = ("gender_dyads", "race_dyads", "intersectional_dyads")
MATRIX_LARGE_FILES = (
    "raw_design.float64.mmap",
    "outcome.float64.mmap",
    "fe_codes.uint64.mmap",
    "cluster_codes.uint64.mmap",
    "visit_hash.uint64.mmap",
)
SCRATCH_LARGE_FILES = (
    "demeaned_design.float64.mmap",
    "demeaned_outcomes.float64.mmap",
)


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(16 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    os.replace(temporary, path)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_child(path: Path, root: Path) -> None:
    resolved = path.resolve()
    root_resolved = root.resolve()
    if resolved == root_resolved or root_resolved not in resolved.parents:
        raise SystemExit(
            f"Refusing compaction target outside intended child root: {resolved}"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    parser.add_argument("--matrix-root", required=True, type=Path)
    parser.add_argument("--scratch-root", required=True, type=Path)
    parser.add_argument("--family", required=True, choices=FAMILIES)
    parser.add_argument("--outcome", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    phase2 = args.phase2.resolve()
    matrix_root = args.matrix_root.resolve()
    scratch_root = args.scratch_root.resolve()
    matrix_dir = matrix_root / args.family / args.outcome
    scratch_dir = scratch_root / args.family / args.outcome
    ensure_child(matrix_dir, matrix_root)
    ensure_child(scratch_dir, scratch_root)
    result_audit_path = (
        phase2
        / "qa"
        / "directional_result_audits"
        / f"{args.family}__{args.outcome}.json"
    )
    matrix_audit_path = (
        phase2
        / "qa"
        / "directional_matrix_audits"
        / f"{args.family}__{args.outcome}.json"
    )
    if not result_audit_path.is_file() or not matrix_audit_path.is_file():
        raise SystemExit("Required directional audits are missing")
    result_audit = load_json(result_audit_path)
    matrix_audit = load_json(matrix_audit_path)
    if (
        result_audit.get("status") != "PASS"
        or matrix_audit.get("status") != "PASS"
        or result_audit.get("matrix_audit_sha256")
        != sha256_file(matrix_audit_path)
    ):
        raise SystemExit("Directional audit chain does not pass")

    matrix_hashes = {
        item["name"]: item["sha256"]
        for item in matrix_audit["matrix_file_audit"]
    }
    targets = []
    for name in MATRIX_LARGE_FILES:
        path = matrix_dir / name
        ensure_child(path, matrix_root)
        if path.is_file():
            actual = sha256_file(path)
            expected = matrix_hashes.get(name, "")
            if actual != expected:
                raise SystemExit(f"Matrix hash changed before compaction: {path}")
            targets.append(
                {
                    "path": str(path),
                    "kind": "matrix",
                    "bytes": path.stat().st_size,
                    "sha256": actual,
                }
            )
    for model_id in ("M2_DIRECTIONAL", "M3_WITHIN_PHYSICIAN"):
        for name in SCRATCH_LARGE_FILES:
            path = scratch_dir / model_id / name
            ensure_child(path, scratch_root)
            if path.is_file():
                targets.append(
                    {
                        "path": str(path),
                        "kind": "demeaning_scratch",
                        "model_id": model_id,
                        "bytes": path.stat().st_size,
                        "sha256": sha256_file(path),
                    }
                )
    if not targets:
        existing_manifest = (
            phase2
            / "qa"
            / "directional_compaction"
            / f"{args.family}__{args.outcome}.json"
        )
        if existing_manifest.is_file():
            print(existing_manifest.read_text(encoding="utf-8"))
            return
        raise SystemExit("No validated directional intermediates found")

    payload = {
        "compaction_id": "directional_validated_intermediate_compaction_v1",
        "created_utc": now_utc(),
        "status": "EXECUTED" if args.execute else "DRY_RUN",
        "family_id": args.family,
        "outcome": args.outcome,
        "result_audit_path": str(result_audit_path),
        "result_audit_sha256": sha256_file(result_audit_path),
        "matrix_audit_path": str(matrix_audit_path),
        "matrix_audit_sha256": sha256_file(matrix_audit_path),
        "targets": targets,
        "bytes_reclaimed": sum(item["bytes"] for item in targets),
        "retained": [
            "matrix_manifest.json",
            "_SUCCESS.json",
            "encoders.json",
            "storage_preflight.json",
            "all result CSV/NPZ files",
            "all QA JSON/CSV files",
            "all source and audit hashes",
        ],
        "rebuild_rule": (
            "The compacted numerical intermediates are reproducibly rebuilt "
            "only from the retained hash-bound matrix builder and audited "
            "directional base."
        ),
        "source_release_modified": False,
        "phase2_cohort_modified": False,
    }
    output_root = phase2 / "qa" / "directional_compaction"
    output_root.mkdir(parents=True, exist_ok=True)
    output_path = output_root / f"{args.family}__{args.outcome}.json"
    if args.execute:
        for item in targets:
            Path(item["path"]).unlink()
    atomic_json(output_path, payload)
    print(
        json.dumps(
            {
                "status": payload["status"],
                "family_id": args.family,
                "outcome": args.outcome,
                "files_compacted": len(targets),
                "bytes_reclaimed": payload["bytes_reclaimed"],
                "audit_history_retained": True,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
