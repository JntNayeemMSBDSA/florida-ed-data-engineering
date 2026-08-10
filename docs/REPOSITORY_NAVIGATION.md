# Repository navigation

This repository is organized so that a collaborator can understand the project without receiving restricted encounter data or unpublished numerical concordance results.

## Recommended reading order

1. Read [`README.md`](../README.md) for the scope and high-level architecture.
2. Read [`PROJECT_STATUS.md`](../PROJECT_STATUS.md) for the controlled completion state.
3. Open the Power BI project described in [`dashboard/README.md`](../dashboard/README.md) for a visual project overview.
4. Read [`METHODOLOGY.md`](../METHODOLOGY.md) for the production data model, decoding, enhancement, and validation logic.
5. Review [`frozen_methodology/Statistical_Analysis_Plan.md`](frozen_methodology/Statistical_Analysis_Plan.md) and the linked addenda for the analytical specifications.
6. Use [`HANDOFF_AND_RESUMPTION_GUIDE.md`](HANDOFF_AND_RESUMPTION_GUIDE.md) only when resuming the restricted analytical pipeline.
7. Use [`REPRODUCIBILITY_GUIDE.md`](REPRODUCIBILITY_GUIDE.md) to reproduce the fictional demonstration and validate this public release.

## Directory map

| Location | Contents | Suitable for public sharing? |
|---|---|---|
| `src/phase1/` | Selected, validated Phase 1 production source snapshots | Yes |
| `src/phase2_full/` | Complete 108-file Phase 2 source snapshot at handoff | Yes |
| `configs/` | Sanitized analytical configuration | Yes |
| `docs/frozen_methodology/` | Frozen plans, dictionaries, execution checkpoints, and deviation records | Yes; contains methods and statuses, not numerical estimates |
| `evidence/` | Sanitized aggregate construction and validation evidence | Yes |
| `dashboard/` | Power BI Project source, public-safe embedded metadata, build utilities, and render QA | Yes |
| `synthetic_demo/` | Deterministic 800-row fictional demonstration | Yes |
| `tests/` | Automated checks for documented claims and reproducibility | Yes |
| `scripts/` | Repository evidence generation and fail-closed validators | Yes |
| `release/` | Construction and release-checkpoint records | Yes |

## What is intentionally absent

The repository does not contain the purchased Florida encounter files, row-level facts or bridges, patient/provider/facility identifiers, model matrices, coefficient tables, confidence intervals, p-values, q-values, unpublished findings, credentials, or private filesystem locations. Code that expects restricted inputs is included for review, but it cannot execute the production analysis without the separately controlled research workspace.

## Provenance

[`SOURCE_PROVENANCE.csv`](../SOURCE_PROVENANCE.csv) records the source snapshot, destination, SHA-256 hash, and sanitization decision for copied artifacts. [`REPOSITORY_INVENTORY.csv`](../REPOSITORY_INVENTORY.csv) records the final release contents and hashes. The release validator checks both ledgers before the `READY_TO_PUBLISH` checkpoint can be created.
