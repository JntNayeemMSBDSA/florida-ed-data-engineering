#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/32_compact_validated_model_intermediates.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Remove only independently audited model intermediates and record the action."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MATRIX_MEMMAPS = (
    "raw_design.float64.mmap",
    "model_outcomes.float64.mmap",
    "fe_codes.uint64.mmap",
    "cluster_codes.uint64.mmap",
)


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(16 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    os.replace(temporary, path)


def is_within(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def validate_results(checkpoint: dict[str, Any]) -> None:
    result_manifest = checkpoint["result_manifest"]
    manifest_path = Path(result_manifest["path"]).resolve()
    if (
        not manifest_path.exists()
        or sha256_file(manifest_path) != result_manifest["sha256"]
    ):
        raise RuntimeError("Result manifest changed after independent audit")
    result_folder = manifest_path.parent
    for item in checkpoint["results_inventory"]:
        path = result_folder / item["relative_path"]
        if (
            not path.exists()
            or path.stat().st_size != int(item["bytes"])
            or sha256_file(path) != item["sha256"]
        ):
            raise RuntimeError(
                f"Result artifact changed after independent audit: {path}"
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True, type=Path)
    parser.add_argument("--checkpoint-json", required=True, type=Path)
    parser.add_argument("--matrix-root", required=True, type=Path)
    parser.add_argument("--matrix-id", required=True)
    parser.add_argument("--scratch-dir", required=True, type=Path)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Required to remove generated intermediates.",
    )
    args = parser.parse_args()

    if not args.execute:
        raise SystemExit(
            "Dry safety stop: pass --execute only after the audit checkpoint "
            "has passed"
        )
    if (
        Path(args.matrix_id).name != args.matrix_id
        or args.matrix_id in {".", ".."}
    ):
        raise SystemExit("--matrix-id must be one safe directory name")

    phase2 = args.phase2.resolve()
    workspace = phase2.parents[1]
    allowed_matrix_root = (
        phase2 / "analysis_data" / "model_matrices"
    ).resolve()
    matrix_root = args.matrix_root.resolve()
    matrix_folder = (matrix_root / args.matrix_id).resolve()
    allowed_temp_root = (
        workspace / "tmp" / "florida_ed_concordance_analysis_20260726"
    ).resolve()
    scratch_dir = args.scratch_dir.resolve()
    if matrix_root != allowed_matrix_root:
        raise RuntimeError(f"Unexpected matrix root: {matrix_root}")
    if not is_within(matrix_folder, allowed_matrix_root):
        raise RuntimeError(f"Unsafe matrix folder: {matrix_folder}")
    if not is_within(scratch_dir, allowed_temp_root):
        raise RuntimeError(f"Unsafe scratch directory: {scratch_dir}")

    checkpoint_path = args.checkpoint_json.resolve()
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    if checkpoint.get("all_passed") is not True:
        raise RuntimeError("Independent audit checkpoint does not pass")
    if checkpoint.get("matrix_id") != args.matrix_id:
        raise RuntimeError("Checkpoint matrix ID does not match target")
    matrix_manifest = checkpoint["matrix_manifest"]
    matrix_manifest_path = Path(matrix_manifest["path"]).resolve()
    if matrix_manifest_path.parent != matrix_folder:
        raise RuntimeError("Checkpoint matrix path does not match target")
    if (
        not matrix_manifest_path.exists()
        or sha256_file(matrix_manifest_path) != matrix_manifest["sha256"]
    ):
        raise RuntimeError("Matrix manifest changed after independent audit")
    validate_results(checkpoint)

    targets: list[dict[str, Any]] = []
    for name in MATRIX_MEMMAPS:
        path = matrix_folder / name
        if path.exists():
            targets.append(
                {
                    "path": str(path),
                    "bytes": path.stat().st_size,
                    "kind": "matrix_memmap",
                }
            )
    if scratch_dir.exists():
        scratch_files = [
            path for path in scratch_dir.rglob("*") if path.is_file()
        ]
        targets.append(
            {
                "path": str(scratch_dir),
                "bytes": sum(path.stat().st_size for path in scratch_files),
                "files": len(scratch_files),
                "kind": "model_scratch_directory",
            }
        )
    if not targets:
        raise RuntimeError("No validated intermediate targets exist")

    for item in targets:
        path = Path(item["path"])
        if item["kind"] == "matrix_memmap":
            path.unlink()
        else:
            shutil.rmtree(path)

    remaining_errors = [
        item["path"] for item in targets if Path(item["path"]).exists()
    ]
    if remaining_errors:
        raise RuntimeError(
            f"Validated intermediates were not removed: {remaining_errors}"
        )
    manifest = {
        "created_utc": now_utc(),
        "compaction_id": f"compact_{args.matrix_id}",
        "matrix_id": args.matrix_id,
        "checkpoint_json": str(checkpoint_path),
        "checkpoint_sha256": sha256_file(checkpoint_path),
        "removed_generated_intermediates": targets,
        "removed_bytes": sum(int(item["bytes"]) for item in targets),
        "matrix_manifest_preserved": str(matrix_manifest_path),
        "result_artifacts_preserved_and_reverified": True,
        "source_release_modified": False,
        "compaction_passed": True,
    }
    output = (
        phase2
        / "qa"
        / "model_intermediate_compaction"
        / f"{args.matrix_id}.json"
    )
    atomic_json(output, manifest)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
