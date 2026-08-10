#!/usr/bin/env python3
# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/01_fetch_external_sources.py
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
"""Fetch public reference data and record exact provenance for Phase 2."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests


BLS_ENDPOINT = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
BLS_SERIES = {
    "CUUR0000SA0": "CPI-U, U.S. city average, all items, not seasonally adjusted",
    "CUUR0000SAM": "CPI-U, U.S. city average, medical care, not seasonally adjusted",
}

SOURCE_REGISTRY = [
    {
        "source_id": "bls_cpi_api",
        "publisher": "U.S. Bureau of Labor Statistics",
        "title": "BLS Public Data API",
        "url": BLS_ENDPOINT,
        "doi": "",
        "role": "Quarterly and annual inflation adjustment",
        "source_type": "Official public data API",
    },
    {
        "source_id": "bls_cpi_series_ids",
        "publisher": "U.S. Bureau of Labor Statistics",
        "title": "CPI series ID codes",
        "url": "https://www.bls.gov/cpi/factsheets/cpi-series-ids.htm",
        "doi": "",
        "role": "Official interpretation of CPI series identifiers",
        "source_type": "Official methodology",
    },
    {
        "source_id": "bls_constant_dollars",
        "publisher": "U.S. Bureau of Labor Statistics",
        "title": "Purchasing power and constant dollars",
        "url": "https://www.bls.gov/cpi/factsheets/purchasing-power-constant-dollars.htm",
        "doi": "",
        "role": "Constant-dollar transformation",
        "source_type": "Official methodology",
    },
    {
        "source_id": "bls_medical_care",
        "publisher": "U.S. Bureau of Labor Statistics",
        "title": "Measuring Price Change in the CPI: Medical care",
        "url": "https://www.bls.gov/cpi/factsheets/medical-care.htm",
        "doi": "",
        "role": "Medical-care CPI sensitivity analysis and interpretation",
        "source_type": "Official methodology",
    },
    {
        "source_id": "cdc_icd10_fy2024",
        "publisher": "CDC/NCHS and CMS",
        "title": "ICD-10-CM Official Guidelines for Coding and Reporting, FY 2024",
        "url": "https://stacks.cdc.gov/view/cdc/150422/cdc_150422_DS1.pdf",
        "doi": "",
        "role": "AMI ICD-10-CM definition and subsequent-MI rules",
        "source_type": "Official coding guideline",
    },
    {
        "source_id": "cdc_icd9_2011",
        "publisher": "CDC/NCHS and CMS",
        "title": "ICD-9-CM Official Guidelines for Coding and Reporting, 2011",
        "url": "https://www.cdc.gov/nchs/data/icd/icd9cm_guidelines_2011.pdf",
        "doi": "",
        "role": "AMI ICD-9-CM episode-of-care definition",
        "source_type": "Official coding guideline",
    },
    {
        "source_id": "census_surname_2010",
        "publisher": "U.S. Census Bureau",
        "title": "Decennial Census Surname Files (2010, 2000)",
        "url": "https://www.census.gov/data/developers/data-sets/surnames.html",
        "doi": "",
        "role": "Physician surname-imputation provenance and limitations",
        "source_type": "Official public data documentation",
    },
    {
        "source_id": "fl_ahca_fddc_data_guide",
        "publisher": "Florida Agency for Health Care Administration",
        "title": "Florida Discharge Data Reporting Specifications",
        "url": (
            "https://ahca.myflorida.com/content/download/22913/file/"
            "FDDC%20Data%20Guide%20update.pdf"
        ),
        "doi": "",
        "role": (
            "Official interpretation of ED arrival/discharge hour codes and "
            "other Florida discharge-data elements"
        ),
        "source_type": "Official state reporting specification",
    },
    {
        "source_id": "greenwood_2018",
        "publisher": "Proceedings of the National Academy of Sciences",
        "title": "Patient-physician gender concordance and increased mortality among female heart attack patients",
        "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC6112736/",
        "doi": "10.1073/pnas.1800097115",
        "role": "AMI sex/gender-concordance reference study",
        "source_type": "Peer-reviewed primary study",
    },
    {
        "source_id": "ye_yi_2023",
        "publisher": "Review of Economics and Statistics",
        "title": "Patient-Physician Race Concordance, Physician Decisions, and Patient Outcomes",
        "url": "https://doi.org/10.1162/rest_a_01236",
        "doi": "10.1162/rest_a_01236",
        "role": "ED racial-concordance and clinical-uncertainty framework",
        "source_type": "Peer-reviewed primary study",
    },
    {
        "source_id": "hill_jones_woodworth_2023",
        "publisher": "Journal of Health Economics",
        "title": "Physician-patient race-match reduces patient mortality",
        "url": "https://doi.org/10.1016/j.jhealeco.2023.102821",
        "doi": "10.1016/j.jhealeco.2023.102821",
        "role": "Florida emergency-admission racial-concordance comparison",
        "source_type": "Peer-reviewed primary study",
    },
    {
        "source_id": "record_statement",
        "publisher": "PLOS Medicine",
        "title": "The RECORD Statement",
        "url": "https://doi.org/10.1371/journal.pmed.1001885",
        "doi": "10.1371/journal.pmed.1001885",
        "role": "Reporting guidance for routinely collected health data",
        "source_type": "Peer-reviewed reporting guideline",
    },
    {
        "source_id": "harron_linkage_2017",
        "publisher": "International Journal of Epidemiology",
        "title": "A guide to evaluating linkage quality for the analysis of linked data",
        "url": "https://doi.org/10.1093/ije/dyx177",
        "doi": "10.1093/ije/dyx177",
        "role": "Physician linkage-quality evaluation",
        "source_type": "Peer-reviewed methods guidance",
    },
    {
        "source_id": "benjamini_hochberg_1995",
        "publisher": "Journal of the Royal Statistical Society Series B",
        "title": "Controlling the False Discovery Rate",
        "url": "https://doi.org/10.1111/j.2517-6161.1995.tb02031.x",
        "doi": "10.1111/j.2517-6161.1995.tb02031.x",
        "role": "Multiple-testing correction",
        "source_type": "Peer-reviewed statistical method",
    },
    {
        "source_id": "manning_mullahy_2001",
        "publisher": "Journal of Health Economics",
        "title": "Estimating log models: to transform or not to transform?",
        "url": "https://doi.org/10.1016/S0167-6296(01)00086-8",
        "doi": "10.1016/S0167-6296(01)00086-8",
        "role": "Skewed health-utilization outcome modeling",
        "source_type": "Peer-reviewed statistical method",
    },
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_bls_window(
    session: requests.Session, start_year: int, end_year: int, raw_dir: Path
) -> list[dict[str, object]]:
    payload = {
        "seriesid": list(BLS_SERIES),
        "startyear": str(start_year),
        "endyear": str(end_year),
        "catalog": True,
        "calculations": False,
        "annualaverage": True,
    }
    response = session.post(BLS_ENDPOINT, json=payload, timeout=90)
    response.raise_for_status()
    body = response.json()
    if body.get("status") != "REQUEST_SUCCEEDED":
        raise RuntimeError(f"BLS request failed: {body}")
    raw_path = raw_dir / f"bls_cpi_{start_year}_{end_year}.json"
    raw_path.write_text(json.dumps(body, indent=2), encoding="utf-8")

    records: list[dict[str, object]] = []
    for series in body["Results"]["series"]:
        series_id = series["seriesID"]
        for item in series["data"]:
            period = item["period"]
            if period.startswith("M") and period != "M13":
                month = int(period[1:])
                records.append(
                    {
                        "series_id": series_id,
                        "series_label": BLS_SERIES[series_id],
                        "year": int(item["year"]),
                        "month": month,
                        "value": float(item["value"]),
                    }
                )
    return records


def download_public_pdf(
    session: requests.Session, url: str, path: Path
) -> dict[str, object]:
    response = session.get(url, timeout=120)
    response.raise_for_status()
    path.write_bytes(response.content)
    return {
        "path": str(path),
        "url": url,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    raw_dir = output / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Florida-ED-Concordance-Research/1.0 "
                "(public academic reproducibility download)"
            )
        }
    )

    cpi_records = []
    cpi_records.extend(fetch_bls_window(session, 2005, 2014, raw_dir))
    cpi_records.extend(fetch_bls_window(session, 2015, 2024, raw_dir))
    monthly = pd.DataFrame(cpi_records).sort_values(["series_id", "year", "month"])
    monthly.to_csv(output / "bls_cpi_monthly_2005_2024.csv", index=False)

    quarterly = (
        monthly.assign(quarter=((monthly["month"] - 1) // 3 + 1))
        .groupby(["series_id", "series_label", "year", "quarter"], as_index=False)["value"]
        .mean()
        .rename(columns={"value": "quarterly_mean_index"})
    )
    annual = (
        monthly.groupby(["series_id", "series_label", "year"], as_index=False)["value"]
        .mean()
        .rename(columns={"value": "annual_mean_index"})
    )
    reference = (
        annual.loc[annual["year"].eq(2024), ["series_id", "annual_mean_index"]]
        .rename(columns={"annual_mean_index": "reference_2024_index"})
    )
    quarterly = quarterly.merge(reference, on="series_id", how="left")
    quarterly["factor_to_2024_dollars"] = (
        quarterly["reference_2024_index"] / quarterly["quarterly_mean_index"]
    )
    annual = annual.merge(reference, on="series_id", how="left")
    annual["factor_to_2024_dollars"] = (
        annual["reference_2024_index"] / annual["annual_mean_index"]
    )
    quarterly.to_csv(output / "bls_cpi_quarterly_factors_to_2024.csv", index=False)
    annual.to_csv(output / "bls_cpi_annual_factors_to_2024.csv", index=False)

    downloads = [
        download_public_pdf(
            session,
            "https://stacks.cdc.gov/view/cdc/150422/cdc_150422_DS1.pdf",
            raw_dir / "ICD-10-CM_Guidelines_FY2024.pdf",
        ),
        download_public_pdf(
            session,
            "https://www.cdc.gov/nchs/data/icd/icd9cm_guidelines_2011.pdf",
            raw_dir / "ICD-9-CM_Guidelines_2011.pdf",
        ),
        download_public_pdf(
            session,
            (
                "https://ahca.myflorida.com/content/download/22913/file/"
                "FDDC%20Data%20Guide%20update.pdf"
            ),
            raw_dir / "Florida_AHCA_FDDC_Data_Guide.pdf",
        ),
    ]

    accessed_utc = datetime.now(timezone.utc).isoformat()
    registry_rows = []
    for row in SOURCE_REGISTRY:
        registry_rows.append({**row, "accessed_utc": accessed_utc})
    with (output / "source_registry.csv").open(
        "w", newline="", encoding="utf-8-sig"
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=list(registry_rows[0]))
        writer.writeheader()
        writer.writerows(registry_rows)

    file_inventory = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name != "download_manifest.json":
            file_inventory.append(
                {
                    "path": str(path.relative_to(output)),
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
    manifest = {
        "created_utc": accessed_utc,
        "bls_endpoint": BLS_ENDPOINT,
        "bls_series": BLS_SERIES,
        "reference_year": 2024,
        "downloads": downloads,
        "files": file_inventory,
    }
    (output / "download_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
