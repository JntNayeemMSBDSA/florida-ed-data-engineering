# Validation summary

## Overall assessment

The public portfolio is ready to share as a code-and-methodology snapshot once the repository validator passes. That assessment applies to the repository, not to the unfinished research analysis.

## Phase 1

The controlling build manifest and QA agree on the released encounter count, completed quarter count, distinct production visit-key count, excluded years, field count, and non-mutation of raw inputs. Independent validation separately reports PASS and confirms the required release artifacts. The public evidence files retain only those aggregate fields plus source filenames, SHA-256 hashes, and extraction timestamps.

High-value checks represented in the release include:

- source-quarter to fact-row reconciliation;
- unique generated visit keys;
- zero released rows from excluded years;
- the 2015 Q3/Q4 ICD transition;
- structural nulls for unsupported triage, admission, and revisit measures;
- one row per NPI in the physician master;
- one row per state facility identifier in the facility master; and
- required documentation, QA, notebook, report, and code artifacts.

## Phase 2 measurement and cohorts

Provider master v2 passed uniqueness and ED-universe coverage checks. The estimate-blind measurement gate confirms that organizations are never classified as MD/DO physicians, the race-probability method uses the approved name likelihoods and priors, the primary physician-gender definition uses recorded provider sources, and the rebuilt primary cohort reconciles to immutable Phase 1 facts.

The primary cohort passed its expected partition, row-count, file-integrity, join, visit-key, indicator, outcome-support, and source-immutability checks. The separate historical cohort passed exact row and key reconciliation across all available historical partitions. Historical analyses passed their independent audit, but no historical findings are copied into this repository.

Directional analysis-plan and implementation gates report PASS. Those gates authorize later work; they do not establish that directional models or final result audits are complete. The primary AMI definition gate likewise supports an ED-only extension and does not permit an inpatient-replication claim.

## Public repository checks

`scripts/validate_public_repository.py` checks:

- required files and repository location;
- prohibited extensions and file-size limits;
- hidden artifacts, symlinks, and Windows junctions;
- local user paths, the source-workstation username, email addresses, and common secret formats;
- row-level identifier artifacts, NPI-like values in committed data artifacts, and result-like filenames;
- local Markdown links;
- README claim-to-evidence reconciliation;
- source-script provenance in the repository inventory;
- Python syntax and requirement imports; and
- deterministic demo outputs against committed expectations.

The test suite independently exercises the synthetic pipeline, safety validator, and documented production claims. A final local check also recomputes the hashes of the small approved private source files used during construction; it does not scan or hash the full encounter dataset.

## Remaining analytical caveat

Primary-period race estimation and the downstream gender, outcome-specific, directional, corrected AMI, multiplicity, and final-audit sequence are not all complete. The portfolio therefore reports engineering scale, validated measurement and cohort status, and methodology—not substantive primary-period associations.
