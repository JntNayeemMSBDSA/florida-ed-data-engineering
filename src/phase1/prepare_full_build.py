# Sanitized portfolio copy of the validated production script.
# Original: outputs/florida_ed_full_build_20260724/scripts/prepare_full_build.py
# Data, dictionary, analysis, output, and scratch roots are supplied by environment.

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import shutil
import sys
import urllib.request
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


DATASET_ROOT = Path(os.environ.get("FL_ED_DATASET_ROOT", "private_data")).expanduser()
PROJECT_ROOT = Path(
    os.environ.get("FL_ED_PROJECT_ROOT", str(DATASET_ROOT.parent))
).expanduser()
DICTIONARY_ROOT = Path(
    os.environ.get("FL_ED_DICTIONARY_ROOT", str(PROJECT_ROOT / "Dictionary"))
).expanduser()
ANALYSIS_ROOT = Path(
    os.environ.get("FL_ED_ANALYSIS_ROOT", str(PROJECT_ROOT / "Analysis"))
).expanduser()
DEFAULT_OUTPUT = Path(
    os.environ.get(
        "FL_ED_PHASE1_OUTPUT",
        str(DATASET_ROOT / "outputs" / "florida_ed_full_build_20260724"),
    )
).expanduser()
DEFAULT_TMP = Path(
    os.environ.get(
        "FL_ED_PHASE1_SCRATCH",
        str(DATASET_ROOT / "tmp" / "florida_ed_full_build_20260724"),
    )
).expanduser()
PYDEPS = Path(
    os.environ.get(
        "FL_ED_PYDEPS",
        str(DATASET_ROOT / "tmp" / "florida_ed_standardization_20260724" / "pydeps"),
    )
).expanduser()

if PYDEPS.exists():
    sys.path.insert(0, str(PYDEPS))

import pandas as pd  # noqa: E402
import pyarrow as pa  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402


CMS_METADATA_URL = (
    "https://data.cms.gov/provider-data/api/1/metastore/schemas/"
    "dataset/items/xubh-q36u"
)
AHCA_ER_SERVICES_URL = (
    "https://ahca.myflorida.com/content/download/27704/file/"
    "Hospital%20Emergency%20Services%20Inventory.pdf"
)
CENSUS_COUNTY_URL = (
    "https://api.census.gov/data/2020/dec/pl?"
    "get=NAME&for=county:*&in=state:12"
)
CMS_HCPCS_2026_Q3_URL = (
    "https://www.cms.gov/files/zip/"
    "july-2026-alpha-numeric-hcpcs-file.zip"
)
CMS_PFS_RVU_2026_URL = (
    "https://www.cms.gov/files/zip/"
    "rvu26a-updated-12-29-2025.zip"
)


def sha256_file(path: Path, block_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(block_size), b""):
            digest.update(block)
    return digest.hexdigest()


def download_file(url: str, destination: Path) -> None:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/124 Safari/537.36"
            )
        },
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        destination.write_bytes(response.read())


def normalize_code(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = re.sub(r"[^0-9A-Z]", "", str(value).upper().strip())
    return text or None


def clean_text(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = re.sub(r"\s+", " ", str(value).strip())
    return text or None


def write_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, path, compression="zstd", use_dictionary=True)


def write_csv(rows: list[dict[str, object]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def read_csv_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as stream:
        return next(csv.reader(stream))


def audit_analysis_folder(output: Path) -> dict[str, object]:
    inventory: list[dict[str, object]] = []
    notebook_rows: list[dict[str, object]] = []
    parquet_rows: list[dict[str, object]] = []
    csv_rows: list[dict[str, object]] = []

    for path in sorted(ANALYSIS_ROOT.rglob("*")):
        if not path.is_file():
            continue
        stat = path.stat()
        inventory.append(
            {
                "relative_path": str(path.relative_to(ANALYSIS_ROOT)),
                "extension": path.suffix.lower(),
                "bytes": stat.st_size,
                "modified_utc": datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.utc
                ).isoformat(),
            }
        )

        if path.suffix.lower() == ".ipynb":
            try:
                notebook = json.loads(path.read_text(encoding="utf-8"))
                cells = notebook.get("cells", [])
                code_cells = [c for c in cells if c.get("cell_type") == "code"]
                markdown_cells = [
                    c for c in cells if c.get("cell_type") == "markdown"
                ]

                def flatten(source: object) -> str:
                    if isinstance(source, list):
                        return "".join(str(item) for item in source)
                    return str(source or "")

                code = "\n".join(flatten(c.get("source")) for c in code_cells)
                markdown = "\n".join(
                    flatten(c.get("source")) for c in markdown_cells
                )
                notebook_rows.append(
                    {
                        "relative_path": str(path.relative_to(ANALYSIS_ROOT)),
                        "cell_count": len(cells),
                        "code_cell_count": len(code_cells),
                        "markdown_cell_count": len(markdown_cells),
                        "code_characters": len(code),
                        "markdown_characters": len(markdown),
                        "code_sha256": hashlib.sha256(
                            code.encode("utf-8")
                        ).hexdigest(),
                        "mentions_revisit": bool(
                            re.search(r"revisit|days_to_next", code, re.I)
                        ),
                        "mentions_patient_proxy": bool(
                            re.search(r"patient_proxy|md5\s*\(", code, re.I)
                        ),
                        "mentions_visit_date": bool(
                            re.search(r"visitdate|visit_date", code, re.I)
                        ),
                        "mentions_triage": bool(
                            re.search(r"triage|severity", code, re.I)
                        ),
                        "mentions_admission": bool(
                            re.search(r"admitted_flag|flag_admitted", code, re.I)
                        ),
                        "mentions_ccs_ccsr": bool(
                            re.search(r"\bCCS\b|\bCCSR\b", code, re.I)
                        ),
                        "mentions_npi": bool(re.search(r"\bNPI\b", code, re.I)),
                    }
                )
            except Exception as exc:
                notebook_rows.append(
                    {
                        "relative_path": str(path.relative_to(ANALYSIS_ROOT)),
                        "cell_count": None,
                        "code_cell_count": None,
                        "markdown_cell_count": None,
                        "code_characters": None,
                        "markdown_characters": None,
                        "code_sha256": None,
                        "mentions_revisit": None,
                        "mentions_patient_proxy": None,
                        "mentions_visit_date": None,
                        "mentions_triage": None,
                        "mentions_admission": None,
                        "mentions_ccs_ccsr": None,
                        "mentions_npi": None,
                        "error": repr(exc),
                    }
                )

        if path.suffix.lower() == ".parquet":
            try:
                parquet_file = pq.ParquetFile(path)
                schema = parquet_file.schema_arrow
                parquet_rows.append(
                    {
                        "relative_path": str(path.relative_to(ANALYSIS_ROOT)),
                        "rows": parquet_file.metadata.num_rows,
                        "row_groups": parquet_file.metadata.num_row_groups,
                        "column_count": len(schema.names),
                        "columns": "|".join(schema.names),
                    }
                )
            except Exception as exc:
                parquet_rows.append(
                    {
                        "relative_path": str(path.relative_to(ANALYSIS_ROOT)),
                        "rows": None,
                        "row_groups": None,
                        "column_count": None,
                        "columns": None,
                        "error": repr(exc),
                    }
                )

        if path.suffix.lower() == ".csv":
            try:
                header = read_csv_header(path)
                csv_rows.append(
                    {
                        "relative_path": str(path.relative_to(ANALYSIS_ROOT)),
                        "column_count": len(header),
                        "columns": "|".join(header),
                    }
                )
            except Exception as exc:
                csv_rows.append(
                    {
                        "relative_path": str(path.relative_to(ANALYSIS_ROOT)),
                        "column_count": None,
                        "columns": None,
                        "error": repr(exc),
                    }
                )

    audit_dir = output / "qa" / "analysis_folder_audit"
    write_csv(inventory, audit_dir / "analysis_file_inventory.csv")
    write_csv(notebook_rows, audit_dir / "analysis_notebook_audit.csv")
    write_csv(parquet_rows, audit_dir / "analysis_parquet_schema_inventory.csv")
    write_csv(csv_rows, audit_dir / "analysis_csv_header_inventory.csv")

    findings = {
        "analysis_root": str(ANALYSIS_ROOT),
        "file_count": len(inventory),
        "total_bytes": sum(int(row["bytes"]) for row in inventory),
        "notebook_count": len(notebook_rows),
        "nonempty_notebook_count": sum(
            bool(row.get("code_characters")) for row in notebook_rows
        ),
        "unique_nonempty_notebook_code_streams": len(
            {
                row["code_sha256"]
                for row in notebook_rows
                if row.get("code_characters")
            }
        ),
        "parquet_count": len(parquet_rows),
        "csv_count": len(csv_rows),
        "production_decisions": [
            {
                "item": "Demographic patient proxy / revisit",
                "decision": "Rejected",
                "reason": (
                    "The released ED files lack a stable patient identifier and "
                    "encounter date. A hash of age, sex, ZIP, race, and ethnicity "
                    "is not an individual identifier."
                ),
            },
            {
                "item": "VisitDate and Patient_Key in 18Q4 readme",
                "decision": "Not available in supplied raw release",
                "reason": (
                    "Those fields do not occur in any of the five observed raw "
                    "schemas and cannot be reconstructed."
                ),
            },
            {
                "item": "Admission flag",
                "decision": "Replaced with disposition/transfer flags",
                "reason": (
                    "Patient status 02 is transfer to another short-term "
                    "hospital, not same-facility admission."
                ),
            },
            {
                "item": "Triage / severity",
                "decision": "Retained only as E/M acuity proxy",
                "reason": (
                    "AHCA calls EVALCODE an acuity-representative E/M code; it is "
                    "not a clinical triage scale."
                ),
            },
            {
                "item": "Prior diagnosis/procedure engines",
                "decision": "Logic retained after source/version validation",
                "reason": (
                    "Exact code normalization and one-to-many CCSR mapping are "
                    "implemented from authoritative local AHRQ references."
                ),
            },
        ],
    }
    (audit_dir / "analysis_audit_findings.json").write_text(
        json.dumps(findings, indent=2), encoding="utf-8"
    )
    return findings


def audit_primary_sources(output: Path) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    expected = []
    for year in list(range(2005, 2009)) + list(range(2010, 2025)):
        for quarter in range(1, 5):
            folder = DATASET_ROOT / f"{year % 100:02d}Q{quarter}ED"
            csv_files = sorted(folder.glob("*.csv"))
            if len(csv_files) != 1:
                raise RuntimeError(
                    f"Expected one CSV in {folder}; found {len(csv_files)}"
                )
            source = csv_files[0]
            header = read_csv_header(source)
            facility_files = sorted(
                list(folder.glob("*_F.xls")) + list(folder.glob("*_F.xlsx"))
            )
            expected.append((year, quarter))
            rows.append(
                {
                    "year": year,
                    "quarter": quarter,
                    "folder": folder.name,
                    "csv_file": source.name,
                    "csv_bytes": source.stat().st_size,
                    "csv_column_count": len(header),
                    "csv_header": "|".join(header),
                    "facility_file": (
                        facility_files[0].name if facility_files else None
                    ),
                    "facility_file_status": (
                        "Present" if facility_files else "Missing"
                    ),
                }
            )
    write_csv(rows, output / "qa" / "primary_source_inventory.csv")
    return {
        "quarter_count": len(rows),
        "expected_quarters": expected,
        "csv_total_bytes": sum(int(row["csv_bytes"]) for row in rows),
        "facility_file_count": sum(
            row["facility_file_status"] == "Present" for row in rows
        ),
    }


def download_source_snapshots(output: Path) -> dict[str, object]:
    source_dir = output / "source_snapshots"
    source_dir.mkdir(parents=True, exist_ok=True)
    retrieved = datetime.now(timezone.utc).isoformat()

    with urllib.request.urlopen(CMS_METADATA_URL, timeout=60) as response:
        cms_metadata = json.load(response)
    cms_url = cms_metadata["distribution"][0]["downloadURL"]
    cms_csv = source_dir / "cms_hospital_general_information.csv"
    if not cms_csv.exists():
        download_file(cms_url, cms_csv)
    (source_dir / "cms_hospital_general_information_metadata.json").write_text(
        json.dumps(cms_metadata, indent=2), encoding="utf-8"
    )
    cms_hcpcs_zip = source_dir / "cms_hcpcs_2026_q3.zip"
    if not cms_hcpcs_zip.exists():
        download_file(CMS_HCPCS_2026_Q3_URL, cms_hcpcs_zip)
    cms_pfs_rvu_zip = source_dir / "cms_rvu26a_2026.zip"
    if not cms_pfs_rvu_zip.exists():
        download_file(CMS_PFS_RVU_2026_URL, cms_pfs_rvu_zip)

    census_json_path = source_dir / "census_2020_florida_counties.json"
    census_download_status = "Present"
    census_download_error = None
    if not census_json_path.exists():
        try:
            download_file(CENSUS_COUNTY_URL, census_json_path)
        except Exception as exc:
            census_download_status = "Unavailable at build time"
            census_download_error = repr(exc)
    if census_json_path.exists():
        try:
            census_payload = json.loads(census_json_path.read_text(encoding="utf-8"))
            if (
                not isinstance(census_payload, list)
                or len(census_payload) < 2
                or "NAME" not in census_payload[0]
            ):
                raise ValueError("Unexpected Census API response structure")
        except Exception as exc:
            census_download_status = "Invalid response; local ZIP reference used"
            census_download_error = repr(exc)
            invalid_census_response = (
                source_dir / "census_api_invalid_response.html"
            )
            census_json_path.replace(invalid_census_response)
            census_json_path = invalid_census_response

    ahca_pdf = source_dir / "ahca_hospital_emergency_services_20251211.pdf"
    ahca_download_status = "Present"
    ahca_download_error = None
    if not ahca_pdf.exists():
        try:
            download_file(AHCA_ER_SERVICES_URL, ahca_pdf)
        except Exception as exc:
            ahca_download_status = "Unavailable at build time"
            ahca_download_error = repr(exc)

    manifest = {
        "retrieved_utc": retrieved,
        "sources": [
            {
                "name": "CMS Hospital General Information",
                "url": cms_url,
                "modified": cms_metadata.get("modified"),
                "released": cms_metadata.get("released"),
                "local_file": str(cms_csv),
                "sha256": sha256_file(cms_csv),
            },
            {
                "name": "2020 Census Florida counties",
                "url": CENSUS_COUNTY_URL,
                "local_file": str(census_json_path),
                "sha256": sha256_file(census_json_path),
                "download_status": census_download_status,
                "download_error": census_download_error,
            },
            {
                "name": "CMS July 2026 Alpha-Numeric HCPCS File",
                "url": CMS_HCPCS_2026_Q3_URL,
                "local_file": str(cms_hcpcs_zip),
                "sha256": sha256_file(cms_hcpcs_zip),
            },
            {
                "name": (
                    "CMS 2026 Physician Fee Schedule Relative "
                    "Value File (RVU26A)"
                ),
                "url": CMS_PFS_RVU_2026_URL,
                "local_file": str(cms_pfs_rvu_zip),
                "sha256": sha256_file(cms_pfs_rvu_zip),
                "use": (
                    "Public-use short descriptions for CPT/HCPCS "
                    "codes; CPT descriptions retain the source "
                    "file's AMA copyright notice"
                ),
            },
            {
                "name": "AHCA Hospital Emergency Services Inventory",
                "url": AHCA_ER_SERVICES_URL,
                "local_file": str(ahca_pdf) if ahca_pdf.exists() else None,
                "sha256": sha256_file(ahca_pdf) if ahca_pdf.exists() else None,
                "download_status": ahca_download_status,
                "download_error": ahca_download_error,
            },
        ],
    }
    (source_dir / "download_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return manifest


def build_geography_references(output: Path) -> None:
    decoder_dir = output / "decoders"
    source_dir = output / "source_snapshots"

    ruca_path = DICTIONARY_ROOT / "RUCA-codes-2020-zipcode.csv"
    ruca = pd.read_csv(ruca_path, dtype="string")
    ruca.columns = [
        re.sub(r"[^0-9a-z]+", "_", str(col).lower()).strip("_")
        for col in ruca.columns
    ]
    zip_col = next(col for col in ruca if col in {"zip_code", "zip", "zipcode"})
    ruca["zip5"] = ruca[zip_col].str.extract(r"(\d{5})", expand=False)
    write_parquet(ruca, decoder_dir / "zip_ruca_2020_reference.parquet")

    uszips_path = (
        DICTIONARY_ROOT
        / "Demographic"
        / "Location"
        / "simplemaps_uszips_basicv1.93"
        / "uszips.csv"
    )
    uszips = pd.read_csv(uszips_path, dtype="string")
    uszips.columns = [
        re.sub(r"[^0-9a-z]+", "_", str(col).lower()).strip("_")
        for col in uszips.columns
    ]
    uszips["zip5"] = uszips["zip"].str.zfill(5)
    census_path = source_dir / "census_2020_florida_counties.json"
    county: pd.DataFrame
    try:
        census_payload = json.loads(census_path.read_text(encoding="utf-8"))
        if (
            not isinstance(census_payload, list)
            or len(census_payload) < 2
            or "NAME" not in census_payload[0]
        ):
            raise ValueError("Unexpected Census API response structure")
        county = pd.DataFrame(census_payload[1:], columns=census_payload[0])
        county["county_fips"] = (
            county["state"].astype(str) + county["county"].astype(str)
        )
        county["county_name"] = county["NAME"].str.replace(
            r" County, Florida$", "", regex=True
        )
        county["source"] = "2020 Census PL API"
    except Exception:
        county = (
            uszips.loc[
                uszips["state_id"].eq("FL"),
                ["county_name", "county_fips"],
            ]
            .dropna()
            .drop_duplicates()
            .sort_values(["county_fips", "county_name"])
        )
        county["state"] = county["county_fips"].str[:2]
        county["county"] = county["county_fips"].str[2:]
        county["source"] = "SimpleMaps ZIP reference fallback"
    write_parquet(
        county[
            ["county_name", "county_fips", "state", "county", "source"]
        ],
        decoder_dir / "florida_county_fips_reference.parquet",
    )
    keep = [
        col
        for col in [
            "zip5",
            "city",
            "state_id",
            "state_name",
            "county_name",
            "county_fips",
            "lat",
            "lng",
            "population",
            "density",
        ]
        if col in uszips.columns
    ]
    write_parquet(
        uszips[keep].drop_duplicates("zip5"),
        decoder_dir / "zip_geography_reference.parquet",
    )


def build_cms_hospital_reference(output: Path) -> None:
    source = output / "source_snapshots" / "cms_hospital_general_information.csv"
    df = pd.read_csv(source, dtype="string")
    df.columns = [
        re.sub(r"[^0-9a-z]+", "_", str(col).lower()).strip("_")
        for col in df.columns
    ]
    state_col = "state"
    florida = df[df[state_col].str.upper().eq("FL")].copy()
    rename = {
        "facility_id": "facility_medicare_id",
        "facility_name": "cms_facility_name",
        "address": "cms_address",
        "city_town": "cms_city",
        "state": "cms_state",
        "zip_code": "cms_zip_code",
        "county_parish": "cms_county_name",
        "telephone_number": "cms_telephone_number",
        "hospital_type": "cms_hospital_type",
        "hospital_ownership": "cms_hospital_ownership",
        "emergency_services": "cms_emergency_services",
    }
    florida = florida.rename(
        columns={key: value for key, value in rename.items() if key in florida}
    )
    florida["facility_medicare_id"] = (
        florida["facility_medicare_id"].str.strip().str.zfill(6)
    )
    florida["cms_zip5"] = (
        florida.get("cms_zip_code", pd.Series(index=florida.index, dtype="string"))
        .str.extract(r"(\d{5})", expand=False)
        .str.zfill(5)
    )

    zip_geo = pd.read_parquet(
        output / "decoders" / "zip_geography_reference.parquet"
    )
    zip_geo = zip_geo.rename(
        columns={
            "lat": "cms_zip_centroid_latitude",
            "lng": "cms_zip_centroid_longitude",
            "county_fips": "cms_zip_county_fips",
        }
    )
    florida = florida.merge(zip_geo, left_on="cms_zip5", right_on="zip5", how="left")
    florida["geocode_method"] = "ZIP centroid; not rooftop geocoding"
    florida["cms_source_modified"] = "2026-04-28"
    florida["cms_source_dataset_id"] = "xubh-q36u"
    write_parquet(
        florida.drop(columns=["zip5"], errors="ignore"),
        output / "dimensions" / "cms_hospital_current_reference.parquet",
    )


def build_diagnosis_references(output: Path) -> None:
    decoder_dir = output / "decoders"
    sample = ANALYSIS_ROOT / "Sample Analysis"

    icd9_source = sample / "icd9_dx_master_FIXED.parquet"
    icd9 = pd.read_parquet(icd9_source)
    icd9["icd9_key"] = icd9["icd9_key"].map(normalize_code)
    icd9 = icd9.dropna(subset=["icd9_key"]).drop_duplicates("icd9_key")
    icd9["mapping_version"] = "AHRQ CCS 2015 / CMS ICD-9-CM descriptions"
    write_parquet(icd9, decoder_dir / "icd9_diagnosis_reference.parquet")

    ccsr_path = DICTIONARY_ROOT / "Diagnoses" / "CCRS_diagnoses.xlsx"
    ccsr = pd.read_excel(
        ccsr_path, sheet_name="DX_to_CCSR_Mapping", header=1, dtype="string"
    )
    ccsr.columns = [
        "icd10_code",
        "icd10_description",
        "ccsr_category",
        "ccsr_category_description",
        "inpatient_default",
        "outpatient_default",
        "default_rationale",
    ]
    ccsr["icd10_key"] = ccsr["icd10_code"].map(normalize_code)
    ccsr["mapping_version"] = "AHRQ CCSR for ICD-10-CM v2026.1"
    ccsr["mapping_source_file"] = str(ccsr_path)
    ccsr = ccsr.dropna(subset=["icd10_key", "ccsr_category"])
    ccsr["category_sequence"] = (
        ccsr.groupby("icd10_key").cumcount().add(1).astype("int16")
    )
    write_parquet(
        ccsr[
            [
                "icd10_key",
                "icd10_description",
                "ccsr_category",
                "ccsr_category_description",
                "inpatient_default",
                "outpatient_default",
                "default_rationale",
                "category_sequence",
                "mapping_version",
                "mapping_source_file",
            ]
        ],
        decoder_dir / "icd10_ccsr_diagnosis_mapping.parquet",
    )


def build_procedure_references(output: Path) -> None:
    decoder_dir = output / "decoders"
    sample = ANALYSIS_ROOT / "Sample Analysis"

    icd9 = pd.read_parquet(sample / "icd9_pcs_master.parquet")
    icd9["icd9_proc_code"] = icd9["icd9_proc_code"].map(normalize_code)
    icd9["mapping_version"] = "AHRQ CCS ICD-9-CM procedures 2015"
    write_parquet(icd9, decoder_dir / "icd9_procedure_reference.parquet")

    icd10 = pd.read_parquet(sample / "icd10_pcs_master.parquet")
    icd10["icd10pcs_code"] = icd10["icd10pcs_code"].map(normalize_code)
    icd10["mapping_version"] = "AHRQ Procedure Classes Refined v2026.1"
    write_parquet(
        icd10, decoder_dir / "icd10pcs_procedure_class_reference.parquet"
    )

    cpt = pd.read_parquet(sample / "cpt_ranges.parquet")
    cpt["mapping_version"] = "AHRQ CCS Services and Procedures v2025.1"
    write_parquet(cpt, decoder_dir / "cpt_hcpcs_ccs_range_reference.parquet")
    cpt_exact_rows = []
    for row in cpt.itertuples(index=False):
        start = str(row.code_start_norm)
        end = str(row.code_end_norm)
        if bool(row.is_numeric_range):
            codes = [
                f"{value:05d}"
                for value in range(int(start), int(end) + 1)
            ]
        else:
            codes = [start]
        for code in codes:
            cpt_exact_rows.append(
                {
                    "service_code": code,
                    "ccs_service_category": str(row.CCS),
                    "ccs_service_category_label": str(
                        getattr(row, "_5")
                    ),
                    "mapping_version": str(row.mapping_version),
                }
            )
    cpt_exact = (
        pd.DataFrame(cpt_exact_rows)
        .drop_duplicates(
            ["service_code", "ccs_service_category"], keep="first"
        )
        .sort_values(["service_code", "ccs_service_category"])
    )
    write_parquet(
        cpt_exact,
        decoder_dir / "cpt_hcpcs_ccs_exact_reference.parquet",
    )

    hcpcs_zip = (
        output / "source_snapshots" / "cms_hcpcs_2026_q3.zip"
    )
    with zipfile.ZipFile(hcpcs_zip) as archive:
        workbook_name = next(
            name
            for name in archive.namelist()
            if name.upper().endswith(".XLSX")
            and "CORRECTION" not in name.upper()
            and "TRANSACTION" not in name.upper()
            and "NOC " not in name.upper()
        )
        workbook_bytes = archive.read(workbook_name)
    hcpcs_source = pd.read_excel(
        io.BytesIO(workbook_bytes), dtype="string"
    )
    hcpcs = hcpcs_source[
        ["HCPC", "LONG DESCRIPTION", "SHORT DESCRIPTION"]
    ].rename(
        columns={
            "HCPC": "hcpcs_code",
            "LONG DESCRIPTION": "hcpcs_long_description",
            "SHORT DESCRIPTION": "hcpcs_short_description",
        }
    )
    hcpcs["hcpcs_code"] = hcpcs["hcpcs_code"].str.strip().str.upper()
    hcpcs = hcpcs[
        hcpcs["hcpcs_code"].str.fullmatch(r"[A-Z0-9]{2,5}", na=False)
    ].copy()
    hcpcs["description_version"] = "CMS HCPCS July 2026"
    hcpcs["source_file"] = f"{hcpcs_zip}!{workbook_name}"
    hcpcs = hcpcs.drop_duplicates("hcpcs_code")
    write_parquet(
        hcpcs, decoder_dir / "hcpcs_level2_2026_q3_reference.parquet"
    )

    pfs_zip = output / "source_snapshots" / "cms_rvu26a_2026.zip"
    with zipfile.ZipFile(pfs_zip) as archive:
        pfs_name = next(
            name
            for name in archive.namelist()
            if name.upper().endswith("_NONQPP.CSV")
        )
        with archive.open(pfs_name) as stream:
            pfs = pd.read_csv(
                stream,
                skiprows=9,
                dtype="string",
                encoding="latin1",
            )
    pfs = pfs.loc[
        pfs["MOD"].fillna("").str.strip().eq(""),
        ["HCPCS", "DESCRIPTION"],
    ].rename(
        columns={
            "HCPCS": "service_code",
            "DESCRIPTION": "service_short_description",
        }
    )
    pfs["service_code"] = (
        pfs["service_code"].str.strip().str.upper()
    )
    pfs["service_short_description"] = pfs[
        "service_short_description"
    ].map(clean_text)
    pfs = pfs.loc[
        pfs["service_code"].str.fullmatch(
            r"[A-Z0-9]{5}", na=False
        )
        & pfs["service_short_description"].notna()
    ].copy()
    pfs["description_version"] = (
        "CMS PFS RVU26A January 2026"
    )
    pfs["source_file"] = f"{pfs_zip}!{pfs_name}"
    pfs["copyright_notice"] = (
        "CPT codes and descriptions copyright 2026 "
        "American Medical Association. All Rights Reserved. "
        "Applicable FARS/DFARS Apply."
    )
    pfs = pfs.drop_duplicates("service_code")
    write_parquet(
        pfs,
        decoder_dir
        / "cpt_hcpcs_cms_pfs_2026_reference.parquet",
    )


ICD9_CONDITION_DESCRIPTIONS = {
    "CHF": "Congestive heart failure",
    "VALVE": "Valvular disease",
    "PULMCIRC": "Pulmonary circulation disorder",
    "PERIVASC": "Peripheral vascular disorder",
    "HTN": "Hypertension, uncomplicated",
    "HTNCX": "Hypertension, complicated",
    "PARA": "Paralysis",
    "NEURO": "Other neurological disorders",
    "CHRNLUNG": "Chronic pulmonary disease",
    "DM": "Diabetes without chronic complications",
    "DMCX": "Diabetes with chronic complications",
    "HYPOTHY": "Hypothyroidism",
    "RENLFAIL": "Renal failure",
    "LIVER": "Liver disease",
    "ULCER": "Peptic ulcer disease excluding bleeding",
    "AIDS": "AIDS/HIV",
    "LYMPH": "Lymphoma",
    "METS": "Metastatic cancer",
    "TUMOR": "Solid tumor without metastasis",
    "ARTH": "Rheumatoid arthritis/collagen vascular disease",
    "COAG": "Coagulopathy",
    "OBESE": "Obesity",
    "WGHTLOSS": "Weight loss",
    "LYTES": "Fluid and electrolyte disorders",
    "BLDLOSS": "Blood loss anemia",
    "ANEMDEF": "Deficiency anemia",
    "ALCOHOL": "Alcohol abuse",
    "DRUG": "Drug abuse",
    "PSYCH": "Psychoses",
    "DEPRESS": "Depression",
    "HTNPREG": "Pre-existing hypertension complicating pregnancy",
    "HTNWOCHF": "Hypertensive heart disease without heart failure",
    "HTNWCHF": "Hypertensive heart disease with heart failure",
    "HRENWORF": "Hypertensive renal disease without renal failure",
    "HRENWRF": "Hypertensive renal disease with renal failure",
    "HHRWOHRF": "Hypertensive heart/renal disease without failure",
    "HHRWCHF": "Hypertensive heart/renal disease with heart failure",
    "HHRWRF": "Hypertensive heart/renal disease with renal failure",
    "HHRWHRF": "Hypertensive heart/renal disease with heart and renal failure",
    "OHTNPREG": "Other hypertension in pregnancy",
}


def parse_icd9_elixhauser_ranges(path: Path) -> list[dict[str, object]]:
    text = path.read_text(encoding="latin-1", errors="replace")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    match = re.search(
        r"VALUE\s+\$RCOMFMT(?P<body>.*?);", text, flags=re.I | re.S
    )
    if not match:
        raise RuntimeError("Could not locate VALUE $RCOMFMT in ICD-9 Elixhauser file")
    body = match.group("body")
    assignments = []
    pattern = re.compile(
        r'(?P<items>(?:(?:"[^"]+"\s*(?:-\s*"[^"]+")?\s*,?\s*)+))'
        r'=\s*"(?P<label>[A-Z0-9_]+)"',
        flags=re.I | re.S,
    )
    item_pattern = re.compile(r'"([^"]+)"\s*(?:-\s*"([^"]+)")?')
    for assignment in pattern.finditer(body):
        label = assignment.group("label").upper()
        for item in item_pattern.finditer(assignment.group("items")):
            start = item.group(1).strip().upper()
            end = (item.group(2) or item.group(1)).strip().upper()
            assignments.append(
                {
                    "start": start,
                    "end": end,
                    "condition": label,
                    "condition_description": ICD9_CONDITION_DESCRIPTIONS.get(
                        label, label
                    ),
                }
            )
    return assignments


def build_elixhauser_references(output: Path) -> None:
    decoder_dir = output / "decoders"
    icd9 = pd.read_parquet(decoder_dir / "icd9_diagnosis_reference.parquet")
    icd9_codes = icd9[["icd9_key"]].dropna().drop_duplicates()
    icd9_codes["sas_key"] = icd9_codes["icd9_key"].str.pad(
        width=5, side="right", fillchar=" "
    )
    sas_path = (
        DICTIONARY_ROOT / "Comorbidity" / "comformat2012-2015.txt"
    )
    assignments = parse_icd9_elixhauser_ranges(sas_path)
    mapped_parts = []
    for assignment in assignments:
        start = assignment["start"].ljust(5)
        end = assignment["end"].ljust(5)
        subset = icd9_codes[
            icd9_codes["sas_key"].between(start, end, inclusive="both")
        ][["icd9_key"]].copy()
        if subset.empty:
            continue
        subset["condition"] = assignment["condition"]
        subset["condition_description"] = assignment["condition_description"]
        mapped_parts.append(subset)
    icd9_map = pd.concat(mapped_parts, ignore_index=True).drop_duplicates()
    icd9_map["mapping_version"] = (
        "AHRQ Elixhauser Comorbidity Software v3.7, FY2012-2015 ICD-9-CM"
    )
    icd9_map["mapping_scope_note"] = (
        "Code-presence mapping only; ED source lacks DRG and POA fields."
    )
    write_parquet(
        icd9_map, decoder_dir / "elixhauser_icd9_mapping.parquet"
    )

    cmr_path = (
        DICTIONARY_ROOT / "Comorbidity" / "CMR-Reference-File-v2026-1.xlsx"
    )
    measures = pd.read_excel(
        cmr_path, sheet_name="Comorbidity_Measures", header=1, dtype="string"
    )
    measures.columns = ["abbreviation", "condition_description", "uses_poa"]
    measures["condition"] = measures["abbreviation"].str.replace(
        r"^CMR_", "", regex=True
    )
    measure_lookup = measures.set_index("condition")[
        ["condition_description", "uses_poa"]
    ]

    mapping = pd.read_excel(
        cmr_path, sheet_name="DX_to_Comorb_Mapping", header=1, dtype="string"
    )
    mapping = mapping.rename(
        columns={
            mapping.columns[0]: "icd10_code",
            mapping.columns[1]: "icd10_description",
            mapping.columns[2]: "condition_count",
        }
    )
    mapping["icd10_key"] = mapping["icd10_code"].map(normalize_code)
    condition_columns = list(mapping.columns[3:-1])
    long = mapping.melt(
        id_vars=["icd10_key", "icd10_description"],
        value_vars=condition_columns,
        var_name="condition",
        value_name="flag",
    )
    long = long[long["flag"].astype("string").eq("1")].copy()
    long = long.drop(columns=["flag"]).drop_duplicates(
        ["icd10_key", "condition"]
    )
    long = long.join(measure_lookup, on="condition")
    long["mapping_version"] = (
        "AHRQ Elixhauser Comorbidity Software Refined v2026.1"
    )
    long["mapping_scope_note"] = (
        "Code-presence mapping; POA-dependent measures cannot apply POA "
        "restrictions because the ED release has no POA indicators."
    )
    write_parquet(
        long, decoder_dir / "elixhauser_icd10_mapping.parquet"
    )


FACILITY_COLUMN_ALIASES = {
    "year": {"YR", "YEAR"},
    "quarter": {"QTR", "QUARTER"},
    "facility_id": {
        "FAC_NUM",
        "FACL_NUM",
        "FACLNBR",
        "FACILITYNUMBER",
        "AHCAFACILITYNUMBER",
    },
    "facility_name": {
        "FAC_NAME",
        "FCLNAME",
        "FACLNAME",
        "FACL_NAME",
        "NAME",
        "FACILITYNAME",
        "ORG_NAME",
    },
    "county_name": {
        "FACLCOUNTY",
        "FACL_COUNTY",
        "FACL_CNTY",
        "FAC_COUNTY_NAME",
        "FAC_CNTY",
        "FACLCNTY",
        "FACILITY_COUNTY",
        "CNTYNAME",
        "COUNTYDESC",
        "COUNTY",
        "COUNTYNAME",
        "ST_COUNTY_DESC",
    },
    "ed_visit_count": {
        "DISCHARGES",
        "VISITS",
        "VISIT",
        "VISTIS",
        "SYS_RECID_NU",
        "EDVISITS",
        "ED_VISITS",
    },
}


def normalized_header(value: object) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value).upper().strip())


def find_facility_column(columns: list[object], aliases: set[str]) -> object | None:
    normalized = {normalized_header(col): col for col in columns}
    for alias in aliases:
        if normalized_header(alias) in normalized:
            return normalized[normalized_header(alias)]
    return None


def build_facility_companion_history(output: Path) -> None:
    rows = []
    audit = []
    for year in list(range(2005, 2009)) + list(range(2010, 2025)):
        for quarter in range(1, 5):
            folder = DATASET_ROOT / f"{year % 100:02d}Q{quarter}ED"
            files = sorted(
                list(folder.glob("*_F.xls")) + list(folder.glob("*_F.xlsx"))
            )
            if not files:
                audit.append(
                    {
                        "year": year,
                        "quarter": quarter,
                        "status": "Missing",
                        "source_file": None,
                        "rows_read": 0,
                    }
                )
                continue
            path = files[0]
            frame = pd.read_excel(path, dtype="string")
            mapped = {
                target: find_facility_column(
                    list(frame.columns), FACILITY_COLUMN_ALIASES[target]
                )
                for target in FACILITY_COLUMN_ALIASES
            }
            if mapped["facility_id"] is None:
                raise RuntimeError(f"Facility ID column not found in {path}")
            for _, source_row in frame.iterrows():
                facility_id = clean_text(source_row.get(mapped["facility_id"]))
                if not facility_id:
                    continue
                visit_value = (
                    source_row.get(mapped["ed_visit_count"])
                    if mapped["ed_visit_count"] is not None
                    else None
                )
                rows.append(
                    {
                        "visit_year": year,
                        "visit_quarter": quarter,
                        "facility_ahca_id": facility_id,
                        "facility_name_companion": clean_text(
                            source_row.get(mapped["facility_name"])
                        )
                        if mapped["facility_name"] is not None
                        else None,
                        "facility_county_name_companion": clean_text(
                            source_row.get(mapped["county_name"])
                        )
                        if mapped["county_name"] is not None
                        else None,
                        "reported_ed_visit_count_companion": pd.to_numeric(
                            visit_value, errors="coerce"
                        ),
                        "facility_companion_source_file": str(path),
                        "facility_name_source": (
                            "AHCA quarterly facility companion"
                            if mapped["facility_name"] is not None
                            else None
                        ),
                    }
                )
            audit.append(
                {
                    "year": year,
                    "quarter": quarter,
                    "status": "Present",
                    "source_file": str(path),
                    "rows_read": len(frame),
                    "mapped_columns": json.dumps(
                        {key: str(value) for key, value in mapped.items()}
                    ),
                }
            )
    history = pd.DataFrame(rows)
    history["facility_ahca_id"] = (
        history["facility_ahca_id"]
        .str.replace(r"\.0$", "", regex=True)
        .str.strip()
    )
    history = history.drop_duplicates(
        ["visit_year", "visit_quarter", "facility_ahca_id"], keep="first"
    )
    write_parquet(
        history,
        output / "dimensions" / "facility_companion_history.parquet",
    )
    write_csv(audit, output / "qa" / "facility_companion_source_audit.csv")


def copy_physician_dimensions(output: Path) -> None:
    prior = (
        DATASET_ROOT / "outputs" / "florida_ed_standardization_20260724"
    )
    copies = {
        "Florida_Physician_Master.parquet": "physician_master.parquet",
        "Florida_Physician_Hospital_Affiliations.parquet": (
            "physician_hospital_affiliations.parquet"
        ),
        "Florida_Physician_Group_Practice_Affiliations.parquet": (
            "physician_group_practice_affiliations.parquet"
        ),
        "physician_master_qa.json": "physician_master_qa.json",
        "physician_master_schema.json": "physician_master_schema.json",
    }
    for source_name, destination_name in copies.items():
        source = prior / source_name
        if not source.exists():
            raise FileNotFoundError(source)
        destination = output / "dimensions" / destination_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    license_source = (
        DICTIONARY_ROOT
        / "Physician"
        / "_derived_master_decoder"
        / "nppes_fl_license_xwalk.parquet"
    )
    license = pd.read_parquet(license_source)
    license["license_number_norm"] = (
        license["license_number_norm"].astype("string").str.upper().str.strip()
    )
    license["npi"] = license["NPI"].astype("string").str.strip()
    license = license[
        license["license_number_norm"].str.match(
            r"^[A-Z]{1,4}[0-9]{3,}$", na=False
        )
        & license["npi"].str.match(r"^[0-9]{10}$", na=False)
    ].copy()
    counts = license.groupby("license_number_norm")["npi"].nunique()
    unique_keys = counts[counts.eq(1)].index
    unique_license = (
        license[license["license_number_norm"].isin(unique_keys)]
        [["license_number_norm", "npi"]]
        .drop_duplicates()
    )
    unique_license["linkage_rule"] = (
        "Unique Florida license-to-NPI link from NPPES license slots"
    )
    write_parquet(
        unique_license,
        output / "decoders" / "florida_license_to_npi_unique.parquet",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--tmp", type=Path, default=DEFAULT_TMP)
    args = parser.parse_args()
    output = args.output.resolve()
    tmp = args.tmp.resolve()
    for directory in [
        output,
        output / "decoders",
        output / "dimensions",
        output / "qa",
        output / "source_snapshots",
        output / "scripts",
        tmp,
    ]:
        directory.mkdir(parents=True, exist_ok=True)

    print("1/10 Auditing primary ED and facility sources", flush=True)
    primary = audit_primary_sources(output)
    print("2/10 Auditing the complete added Analysis folder", flush=True)
    analysis = audit_analysis_folder(output)
    print("3/10 Downloading authoritative CMS, Census, and AHCA snapshots", flush=True)
    downloads = download_source_snapshots(output)
    print("4/10 Building county, ZIP, and RUCA references", flush=True)
    build_geography_references(output)
    print("5/10 Building current CMS Florida hospital reference", flush=True)
    build_cms_hospital_reference(output)
    print("6/10 Building ICD-9 and ICD-10 diagnosis references", flush=True)
    build_diagnosis_references(output)
    print("7/10 Building procedure references", flush=True)
    build_procedure_references(output)
    print("8/10 Building ICD-specific Elixhauser references", flush=True)
    build_elixhauser_references(output)
    print("9/10 Building quarterly facility companion history", flush=True)
    build_facility_companion_history(output)
    print("10/10 Copying validated physician dimensions and license crosswalk", flush=True)
    copy_physician_dimensions(output)

    build_manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "output": str(output),
        "tmp": str(tmp),
        "primary_source_audit": primary,
        "analysis_folder_audit": analysis,
        "download_manifest": downloads,
        "scope": {
            "years": "2005-2008 and 2010-2024",
            "excluded_years": [2009, 2025],
            "type_of_service_filter": "TYPE_SERV = 2",
        },
    }
    (output / "build_manifest_prepare.json").write_text(
        json.dumps(build_manifest, indent=2), encoding="utf-8"
    )
    shutil.copy2(Path(__file__), output / "scripts" / Path(__file__).name)
    print(json.dumps(build_manifest, indent=2), flush=True)


if __name__ == "__main__":
    main()
