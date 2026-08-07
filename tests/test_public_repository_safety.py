from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = ROOT / "scripts" / "validate_public_repository.py"
SPEC = importlib.util.spec_from_file_location("public_validator", VALIDATOR_PATH)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


def test_public_repository_safety_checks_pass() -> None:
    errors = VALIDATOR.validate_repository(ROOT, run_demo=False)
    assert errors == []


def test_no_prohibited_extensions_or_large_files() -> None:
    files = VALIDATOR.repository_files(ROOT)
    assert not [path for path in files if path.suffix.lower() in VALIDATOR.PROHIBITED_EXTENSIONS]
    assert not [path for path in files if path.stat().st_size > VALIDATOR.MAX_FILE_BYTES]


def test_no_links_or_junctions() -> None:
    for path in ROOT.rglob("*"):
        if ".git" in path.parts:
            continue
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
        assert not path.is_symlink()
        assert not (attributes & 0x400)
