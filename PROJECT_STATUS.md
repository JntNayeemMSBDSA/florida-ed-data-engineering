# Project status

Status snapshot: **2026-08-10 (America/New_York)**.

Overall research status: **IN PROGRESS**. Phase 1 is complete and independently validated. Phase 2 has substantial completed and checkpointed work, but the analytical release has not passed its final independent audit.

| Component | Controlled status | Meaning |
|---|---|---|
| Phase 1 database construction | COMPLETE | 148,686,146 rows, 76 quarterly partitions, and 342 standardized fields built |
| Phase 1 independent validation | COMPLETE | Required release, reconciliation, and immutability controls passed at the checkpoint |
| Provider master v2 | COMPLETE | Complete ED-observed NPI universe and entity/clinician controls passed |
| Race and gender measurement gates | COMPLETE | Definitions, provenance, alternatives, and limitations frozen |
| Primary 2010–2024 cohort | COMPLETE | 60 provider-v2 partitions and 119,543,044 rows reconciled |
| Historical 2005–2008 cohort | COMPLETE | 16 partitions and 23,304,846 rows separately reconciled |
| Historical compatible analyses | COMPLETE | Independent historical audit passed; findings are not published here |
| Primary race M1–M3 computation | COMPLETE, AUDIT PENDING | Computational outputs are checkpointed; release-level audit remains pending |
| Primary gender M1 computation | COMPLETE, AUDIT PENDING | Computational output is checkpointed; release-level audit remains pending |
| Primary gender M2 | RESTART REQUIRED | Initialization was not committed; restart after validating checkpoint hashes |
| Primary gender M3 | PENDING | Follows gender M2 |
| Outcome-specific and cohort-definition models | PENDING | Frozen specifications exist; required execution/audits remain |
| Corrected primary AMI/Greenwood | PENDING | Kept separate under its corrected frozen definition |
| Directional gender, race, and intersectional dyads | PENDING | Design and code gates exist; fitted/audited families remain |
| Measurement sensitivities and multiple imputation | PENDING | Florida/national priors, thresholds, hard labels, and MI remain required |
| Multiplicity | PENDING | Applies only after all eligible families are complete |
| Final Phase 1 immutability audit | PENDING FOR FINAL RELEASE | Must be rerun before analytical release |
| Final independent analytical-release audit | PENDING | No terminal analytical PASS exists |
| Final research reports | DEFERRED | Not required for this local public-safe code/dashboard checkpoint |

Safe public statement:

> Phase 1 complete and independently validated. Phase 2 measurement, cohort construction, historical analyses, and primary race M1–M3 estimation complete; primary gender M1 complete. Remaining primary and sensitivity analyses and the final independent analytical-release audit are pending.

The completed computations above are not interpreted as released scientific findings. This repository contains no numerical concordance estimates.

The authoritative restart record is [docs/frozen_methodology/USER_AUTHORIZED_HANDOFF_PAUSE_20260809T211227Z.md](docs/frozen_methodology/USER_AUTHORIZED_HANDOFF_PAUSE_20260809T211227Z.md). The navigation and resumption sequence is summarized in [docs/HANDOFF_AND_RESUMPTION_GUIDE.md](docs/HANDOFF_AND_RESUMPTION_GUIDE.md).
