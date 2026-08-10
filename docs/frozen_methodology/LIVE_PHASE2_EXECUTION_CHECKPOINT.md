# Live Phase 2 execution checkpoint

Updated: 2026-08-01 14:11 UTC

This file is an operational recovery note, not a result artifact. Do not cite it
for findings.

## Post-shutdown independent background recovery — 2026-08-01

- The latest valid race-M2 checkpoint was preserved across shutdown: all 115
  design columns and 20 of 42 outcome columns are restart-safe for 58,678,714
  rows. The persisted `y_20_24` strict attempt is `NONCONVERGED`; the recovered
  estimator reuses that record and proceeds directly to the already-authorized
  block-specific fallback. It does not repeat completed blocks.
- The reboot left restrictive ACLs on the local Phase 2 dependency tree. Only
  ownership and inherited permissions under
  `tmp/florida_ed_concordance_analysis_20260726/pydeps` were restored. DuckDB
  1.5.5 and pyfixest 0.60.0 imports then passed. No dependency contents,
  scientific scripts, model specifications, checkpoints, analysis data, or
  immutable Phase 1 files were changed.
- One pre-estimator startup failed closed because of those dependency ACLs.
  Its exact logs and markers were preserved with timestamped
  `_DEPENDENCY_ACL` names; active terminal marker names were not left behind.
- The healthy analytical chain was relaunched with the frozen commands and
  bindings. At 2026-08-01 14:11 UTC, canonical PID 29488, common runner PID
  10532, estimator PID 22160, post-canonical supervisor PID 24988, and final
  supervisor PID 29784 were active. The estimator working set was about
  23.14 GB. No terminal PASS or active fail-closed marker existed.
- An independent Windows-owned watchdog, PID 8772 at this checkpoint, now
  protects local continuity without Codex supervision. Its script is
  `scripts/RUN_PHASE2_BACKGROUND_WATCHDOG.ps1`, SHA-256
  `a9f90b067bc42f9297b39f2890aad520589831d92fba37668ef8d806034c1a41`.
  It validates frozen hashes, waits for the final supervisor, and reconstructs
  only a missing safe-runner chain when no terminal marker exists. It stops
  fail-closed if the analytical release fails.
- The machine must remain powered on and awake. Codex can be closed. Windows
  shutdown, restart, sleep, hibernation, forced process termination, or loss
  of the workspace drive stops or suspends local computation; the checkpoint
  remains recoverable after another restart.
- The complete machine-readable recovery record is
  `qa/shutdown_recovery_background_launch_20260801T141109Z.json`. Operational
  log: `qa/run_logs/background_watchdog/BACKGROUND_WATCHDOG.log`.
- `ANALYTICAL_RELEASE` remains in progress. `REPORT_AND_PUBLIC_RELEASE`
  remains `DEFERRED_BY_USER_BUDGET`; report, DOCX/PDF, visual, portfolio, and
  public-release work is not running.

## Latest user-authorized low-credit checkpoint

- At 2026-07-28 01:05 UTC, neither the final analytical PASS marker nor the
  final fail-closed marker existed.
- At 2026-07-28 01:06 UTC, the canonical parent PID 8692, common-primary
  runner PID 35384, estimator PID 40644, post-canonical supervisor PID 26704,
  and final-release supervisor PID 39160 were all present and healthy.
- The newest verified restart-safe race-M2 state then contained 52 of 115
  completed design columns and zero completed outcome columns. Block `x_48_52`
  recorded strict nonconvergence at
  `2026-07-27T23:24:41.610366+00:00`, fallback convergence at
  `2026-07-28T00:08:23.885995+00:00`, and a restart-safe state write at
  `2026-07-28T00:11:08.760919+00:00`.
- The user paused Codex-side work to conserve credits. The heartbeat
  `florida-ed-analytical-release-monitor` is `PAUSED`. The detached local
  estimator and supervisors were deliberately left running because they use
  local CPU/RAM rather than OpenAI credits and interrupting an in-flight block
  could discard progress.
- The authoritative pause handoff is
  `documentation/PAUSE_AND_RESUME_HANDOFF_20260728T010653Z.md`; the paste-ready
  completion prompt is
  `documentation/RESUME_PROMPT_FLORIDA_ED_PHASE2.txt`.
- This 52-column snapshot is a historical lower bound, not a rollback target.
  On resumption, inspect the live state and continue from the newest hash-valid
  checkpoint. Never duplicate a healthy process.

## Immutable source

- Never modify `outputs/florida_ed_full_build_20260724`.
- Phase 1 has 148,686,146 fact rows in 76 validated quarters.

## Canonical runner recovery state

- The previous `RUN_PHASE2_REMAINING_SAFE.ps1 -StartAt common` process stopped
  fail-closed during common-primary race M2 strict fixed-effect demeaning.
- No result was written for the failed M2 model. The already completed M1 file
  was preserved, and no coefficient values were read or interpreted.
- Hash-verified failure evidence is preserved at
  `audit_history/common_primary_race_m2_strict_nonconvergence_20260727T0221Z`.
- The tested inference engine permits a looser numerical tolerance only after
  a strict failure has been persisted. It does not alter the sample, formula,
  outcomes, fixed effects, clusters, or estimands.
- The exact 58,678,714-row, 115-column retry state is bound at
  `qa/demeaning_failure_checkpoints/common_primary_race_m2.json`, SHA-256
  `e777a576a4ce14040925ebb173c55b4ffcc70313bd9706cba53e0a5a7f6ce613`.
- The canonical recovery is active and detached:
  `RUN_PHASE2_REMAINING_SAFE.ps1 -StartAt common` PID 8692,
  `RUN_COMMON_PRIMARY_SAFE.ps1` PID 35384, and
  `08_estimate_primary_models.py` PID 40644.
- A fail-closed downstream supervisor,
  `RUN_POST_CANONICAL_ANALYSIS_SAFE.ps1` PID 26704, is waiting for PID 8692.
  It starts nothing unless the canonical parent exits with a fresh successful
  completion marker. It then runs corrected primary AMI, multiplicity, the
  independent AMI audit, and the fully audited directional sequence. It stops
  before the final independent analysis-release audit and PDF finalization.
- As of 2026-07-27 13:17 UTC, 28 of 115 race-M2 design columns are complete and
  restart-safe. Blocks `x_0_4` (raw columns `[1,2,3,34]`) and `x_4_8`
  (`[35,36,37,38]`) each have persisted strict nonconvergence followed by
  persisted fallback convergence. Block `x_8_12` (raw columns
  `[39,40,41,42]`) converged under the strict rule. Block `x_12_16` (raw
  columns `[43,44,45,46]`) recorded strict nonconvergence and then persisted
  fallback convergence at `2026-07-27T08:43:59.404024+00:00`. The estimator
  completed its restart-safe block write at
  `2026-07-27T08:47:26.503563+00:00`. The next block is running under the
  unchanged strict-first policy. Block `x_16_20` (raw columns
  `[47,48,49,50]`) recorded strict nonconvergence at
  `2026-07-27T10:02:38.351663+00:00`; its identical, already authorized
  block-specific fallback converged at
  `2026-07-27T10:23:14.808130+00:00`, and the block became restart-safe at
  `2026-07-27T10:25:38.911072+00:00`. Block `x_20_24` (raw columns
  `[51,52,53,54]`) converged under the strict rule at
  `2026-07-27T11:32:09.020423+00:00` and became restart-safe at
  `2026-07-27T11:34:19.605419+00:00`; no fallback was used for that block.
  Block `x_24_28` recorded strict nonconvergence at
  `2026-07-27T12:42:56.934695+00:00`; its identical, already authorized
  block-specific fallback converged at
  `2026-07-27T13:00:54.325016+00:00`, and the block became restart-safe at
  `2026-07-27T13:03:05.371552+00:00`. The estimator had accumulated 89,482
  CPU seconds; its working set was approximately 22.58 GB and its private set
  approximately 12.64 GB. The
  canonical parent, child runner,
  estimator, waiting post-canonical supervisor, and waiting final-release
  supervisor were all present. No race-M2 result file exists or has been
  interpreted.
- Do not interrupt these processes and do not launch a competing real-data
  estimator. On any later recovery, read the live `demeaning_state.json`
  first and resume the same canonical parent sequence from its last completed
  checkpoint.
- At 2026-07-27 07:36 UTC, header-only static review found a downstream schema
  compatibility defect before its stage ran: the independently audited
  historical AMI result uses `cohort_definition`, while
  `16_apply_multiple_testing.py` expected `definition`. The script now accepts
  either name and fails if neither exists; this changes no sample, outcome,
  estimator, contrast, family membership, multiplicity method, or result
  value. The exact pre-correction script and bindings are preserved at
  `audit_history/multiplicity_schema_alias_20260727T0736Z`; `DEV-017` records
  the timing. With no real directional result file present, the estimate-blind
  directional implementation and execution bindings were refreshed and all
  12 model-definition tests passed. The current implementation SHA-256 is
  `8d2b6bf51b19a7292ffe3f9a38c70b7cf2b87595a2d128f64c49a357d11236df`;
  the current execution-manifest SHA-256 is
  `6b1476e04de00ae897e31e43df920ad8269d3b248a25a69ffa00a5a7035feae7`.
- At 2026-07-27 08:39 UTC, an estimate-blind critical-path review found that
  the complete release gate did not require independent reconstruction of
  every non-directional Holm/BH table. `DEV-019` adds the validation-only
  `54_independent_global_multiplicity_audit.py` gate. Its independent
  Holm/BH reference and tamper-detection suite passes 6/6, and the updated
  complete-release structural suite passes 10/10. No analytical specification
  or result value changed.
- At 2026-07-27 08:30 UTC, the user authorized continued completion of the
  entire frozen analytical plan but deferred dossier, collaborator-report,
  PDF/DOCX, visual, portfolio, and public-release work for budget. The signed
  operational checkpoint is
  `qa/user_authorized_report_deferral_20260727T083046Z.json`.
  `ANALYTICAL_RELEASE` remains `IN_PROGRESS`;
  `REPORT_AND_PUBLIC_RELEASE` is `DEFERRED_BY_USER_BUDGET`. The pre-deferral
  11-file report framework is preserved in a separately hash-verified archive
  at `audit_history/report_deferral_20260727T083046Z`.
- At 2026-07-27 09:05 UTC, a lightweight fail-closed final analytical-release
  waiter was started as PID 39160. It uses `Wait-Process` on the protected
  post-canonical supervisor PID 26704, so it does not poll, interrupt, restart,
  pause, or modify the active estimator or supervisor. Only after a fresh
  successful post-canonical marker will it run the frozen multiplicity
  reconstruction, 573-file Phase 1 immutability audit, complete release audit,
  and split-status finalizer. Its exact code and order are frozen in
  `documentation/Final_Analytical_Release_Execution_FROZEN.json`. No report
  materialization, rendering, visual QA, or public packaging is in that
  sequence.

## Safe continuation order

1. Allow the active `RUN_PHASE2_REMAINING_SAFE.ps1 -StartAt common` recovery to
   continue with its existing Python, 12-thread, and 24-GB limits. The exact
   archived first-block strict failure was reused; all new blocks still try the
   strict policy first.
2. Independently audit every final strict/fallback demeaning attempt, matrix
   binding, model output, and unchanged scientific specification.
3. Allow the canonical runner to finish common-primary, outcome-specific,
   cohort-definition, multiple-testing, and environment stages.
4. Rerun the corrected primary ED-only AMI script
   `10_ami_validation_and_analysis.py`. It must yield 24 estimable and 6
   explicitly non-estimable required cells.
5. Rerun `16_apply_multiple_testing.py`.
6. Run `45_independent_primary_ami_results_audit.py`; do not interpret AMI
   results unless it passes.
7. Run `RUN_DIRECTIONAL_DYADS_SAFE.ps1 -Scope all`. The current estimate-blind
   directional execution manifest is
   `documentation/Directional_Dyad_Execution_Code_FROZEN.json`, SHA-256
   `6b1476e04de00ae897e31e43df920ad8269d3b248a25a69ffa00a5a7035feae7`.
   It freezes 14 files, including the corrected shared HDFE engine, before any
   real directional result existed.
8. For each of the two primary outcomes, race and intersectional directional
   matrices must complete the five-class measurement-sensitivity stage and its
   independent audit before compaction.
9. Aggregate directional multiplicity and family audits.
10. Run `54_independent_global_multiplicity_audit.py` and require a complete
    estimate-blind reconstruction PASS for every non-directional adjusted
    result table.
11. Run `55_independent_phase1_immutability_audit.py` only after all active
    analytical model processes finish. It must recompute and match all 573
    Phase 1 file sizes and SHA-256 hashes, reject missing or unexpected files,
    and write only to Phase 2.
12. Run the complete independent analysis-release audit.
13. Only after all analytical gates pass, record
    `ANALYTICAL_RELEASE=PASS_INDEPENDENTLY_AUDITED`. Stop with
    `REPORT_AND_PUBLIC_RELEASE=DEFERRED_BY_USER_BUDGET`. Do not materialize,
    build, render, visually inspect, finalize, or publicly package reports
    until the user later lifts the deferral. The already-running downstream
    supervisor remains unmodified; its pre-existing final framework-status
    refresh is not a report materialization or public-release step.

## Key correction and history files

- `documentation/SAP_deviation_log.csv` (`DEV-014` through `DEV-019`)
- `documentation/Directional_Dyad_Execution_Refreeze_History.json`
- `qa/directional_measurement_sensitivity_tests.json` (8/8 PASS)
- `qa/directional_inference_engine_tests.json` (10/10 PASS)
- `qa/demeaning_fallback_unit_tests.json` (4/4 PASS)
- `qa/demeaning_policy_audit_unit_tests.json` (4/4 PASS)
- `qa/demeaning_failure_checkpoints/common_primary_race_m2.json`
- `documentation/Report_Reference_Verification.json`
- `qa/report_materializer_unit_tests.json` (5/5 PASS)
- `qa/report_finalizer_unit_tests.json` (3/3 PASS)
- `qa/complete_release_audit_unit_tests.json` (10/10 PASS)
- `qa/independent_multiple_testing_audit_unit_tests.json` (6/6 PASS)
- `qa/independent_phase1_immutability_audit_unit_tests.json` (4/4 PASS)
- `qa/finalize_analytical_release_status_unit_tests.json` (4/4 PASS)
- `qa/user_authorized_report_deferral_20260727T083046Z.json`
- `audit_history/complete_release_sap_gate_20260727T0804Z/ARCHIVE_MANIFEST.json`
- `audit_history/global_multiplicity_release_gate_20260727T0839Z/ARCHIVE_MANIFEST.json`
- `audit_history/report_deferral_20260727T083046Z/ARCHIVE_MANIFEST.json`
- `reports/report_production/qa/Report_Finalization_Gate.json`

## Interpretation locks

- Do not inspect or report real-data estimates until the corresponding
  independent result audit passes.
- Use association language only.
- Physician race is an algorithm-inferred full-name probability proxy without
  geography; it is not self-reported identity and is not BISG.
- The primary AMI analysis is a standalone ED-only extension, not an inpatient
  Greenwood replication.
