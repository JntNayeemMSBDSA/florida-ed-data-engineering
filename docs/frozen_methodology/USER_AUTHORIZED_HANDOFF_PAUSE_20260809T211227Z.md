# Florida ED Phase 2 — user-authorized handoff pause

Captured: 2026-08-09T21:12:27Z (2026-08-09 17:12:27 America/New_York)

## Authorization and scope

The user authorized a safe local analytical pause in order to prepare the
completed work for faculty handoff. This pause does not change any research
question, specification, cohort, estimand, result, or source artifact. Phase 1
remains immutable. Uploading, Git publication, report production, presentation
production, and email drafting were explicitly deferred and were not executed
as part of this pause.

## Analytical status at the pause

- Final analytical release: `IN_PROGRESS`; no final PASS marker exists.
- Phase 1: complete and independently validated.
- Provider master v2, measurement gates, primary/historical cohorts, and
  historical analyses: preserved as previously checkpointed.
- Primary race common-sample models M1, M2, and M3: computationally complete.
- Primary race M3: 107/107 design columns and 42/42 outcomes complete; model
  output and diagnostics written.
- Primary gender M1: computationally complete; output and diagnostics written.
- Primary gender M2: initialized, but no demeaning state or completed block was
  committed. Resumption should restart gender M2 from its beginning after
  validating all existing hashes.
- Primary gender M3, common-primary postmodels/audits, outcome-specific models,
  cohort-definition sensitivities, corrected AMI, directional analyses,
  multiplicity, and final independent release audits: pending.

## Committed result hashes

| Artifact | SHA-256 |
|---|---|
| `results/models/race/primary_models_manifest.json` | `E93A69B9AD5DEF82383418255ED06C37421C113619053CCEDFC9EC9A5F73BA23` |
| `results/models/race/primary_model_coefficients.csv` | `4173D5E84B488E685176DFD2FF29301F9A537F3C1710C89A49E746DB5450EFD9` |
| `results/models/race/m3_physician_facility_yq_clinical_fe_coefficients.csv` | `9B58B4AC568CA2A35FDE03DA38285084085C0035D64F62CE523A360CB53E3B12` |
| `results/models/race/m3_physician_facility_yq_clinical_fe_diagnostics.json` | `4E1EC51728C7907012A22AB29746AFB62EA3349EDBF5F8D2F9B51BA703240FCE` |
| `results/models/sex_gender/m1_patient_adjusted_coefficients.csv` | `98DA6F96E61CA2365B0961ECD96A2B9AE26952D5F8B115D3E0217DD98EB9F110` |
| `results/models/sex_gender/m1_patient_adjusted_diagnostics.json` | `63A2F0E990DC95FD0D29069A57972C9B243E874464EBB97813553A10916D52DD` |

## Live process tree captured before stopping

| Role | PID | Command |
|---|---:|---|
| Background watchdog | 8772 | `RUN_PHASE2_BACKGROUND_WATCHDOG.ps1` |
| Gender estimator | 19588 | `08_estimate_primary_models.py --matrix-id sex_gender --cohort sex_gender` |
| Post-canonical supervisor | 29432 | `RUN_POST_CANONICAL_ANALYSIS_SAFE.ps1` |
| Common-primary runner | 30760 | `RUN_COMMON_PRIMARY_SAFE.ps1` |
| Final-release supervisor | 32900 | `RUN_FINAL_ANALYTICAL_RELEASE_SAFE.ps1` |
| Canonical parent | 37632 | `RUN_PHASE2_REMAINING_SAFE.ps1 -StartAt common` |

The safe stop order is watchdog, final supervisor, post-canonical supervisor,
common-primary runner, canonical parent, then the gender estimator. Stopping
the watchdog and waiting supervisors first prevents automatic relaunch and
prevents an intentional pause from being interpreted by those supervisors as
a new terminal analytical failure.

## Resume requirements

Before resuming:

1. Verify there is no active Florida ED estimator or supervisor.
2. Verify the committed hashes above and all upstream provider, cohort, matrix,
   and measurement-gate hashes.
3. Preserve all outputs, scratch files, run logs, and this pause record.
4. Treat the gender M2 initialization as uncommitted; restart it from the
   beginning unless a newer independently validated checkpoint exists.
5. Resume the frozen canonical sequence from `common` without rebuilding Phase
   1 or overwriting completed race outputs.
6. Do not interpret provisional outputs as a final independently audited
   analytical release.

The existing recovery references remain:

- `documentation/LIVE_PHASE2_EXECUTION_CHECKPOINT.md`
- `documentation/PAUSE_AND_RESUME_HANDOFF_20260728T010653Z.md`
- `documentation/RESUME_PROMPT_FLORIDA_ED_PHASE2.txt`
- `qa/shutdown_recovery_background_launch_20260801T141109Z.json`

## Post-stop verification

At 2026-08-09T21:14:23Z, all six recorded project processes were confirmed
absent. A command-line scan found no active Florida ED estimator, background
watchdog, canonical runner, post-canonical supervisor, or final-release
supervisor. No new terminal analytical failure marker was created. All result,
scratch, log, documentation, and audit files were left in place.
