# Florida ED Phase 2 — pause and resume handoff

Created: 2026-07-28 01:06:53 UTC

This is an operational recovery document, not a result artifact. It contains no
real-data estimates and must not be cited as a scientific finding.

## User-authorized pause

The user paused Codex-side work because of low OpenAI credits. The heartbeat
automation `florida-ed-analytical-release-monitor` was set to `PAUSED`.

The protected detached local estimator and its two downstream supervisors were
intentionally **not** interrupted. They do not consume OpenAI credits, and an
in-flight interruption could discard block-level work or cause an avoidable
fail-closed recovery event. Therefore, this document records a historical safe
checkpoint, but a later resumption must first inspect the live state because the
local pipeline may have progressed or completed.

## Release status at the pause

- `ANALYTICAL_RELEASE`: `IN_PROGRESS`
- `REPORT_AND_PUBLIC_RELEASE`: `DEFERRED_BY_USER_BUDGET`
- Terminal PASS marker: absent at 2026-07-28 01:05:14 UTC
- Terminal fail-closed marker: absent at 2026-07-28 01:05:14 UTC
- No result values were inspected to guide specifications.

## Immutable source

Never modify:

`outputs/florida_ed_full_build_20260724`

All reconstruction, recovery, model, audit, documentation, and report writes
belong under:

`outputs/florida_ed_concordance_analysis_20260726`

or its corresponding Phase 2 temporary workspace:

`tmp/florida_ed_concordance_analysis_20260726`

## Live-process snapshot

At 2026-07-28 01:06:53 UTC, all protected processes were present:

| Role | PID | Program |
|---|---:|---|
| Canonical parent | 8692 | `RUN_PHASE2_REMAINING_SAFE.ps1 -StartAt common` |
| Common-primary runner | 35384 | `RUN_COMMON_PRIMARY_SAFE.ps1` |
| Race-M2 estimator | 40644 | `08_estimate_primary_models.py` |
| Post-canonical supervisor | 26704 | `RUN_POST_CANONICAL_ANALYSIS_SAFE.ps1` |
| Final analytical-release supervisor | 39160 | `RUN_FINAL_ANALYTICAL_RELEASE_SAFE.ps1` |

These PIDs are historical identifiers. A later session must not assume they
remain valid or that a reused PID represents the same command.

## Last verified restart-safe numerical checkpoint

State file:

`tmp/florida_ed_concordance_analysis_20260726/common_primary_model_scratch/race/m2_fully_adjusted_facility_yq_clinical_fe/demeaning_state.json`

At state timestamp `2026-07-28T00:11:08.760919+00:00`:

- 52 of 115 race-M2 design columns were complete and restart-safe.
- Zero outcome columns were complete.
- The last completed block was `x_48_52`.
- Its strict attempt recorded nonconvergence at
  `2026-07-27T23:24:41.610366+00:00`.
- Its already authorized block-specific fallback converged at
  `2026-07-28T00:08:23.885995+00:00`.
- The block was persisted restart-safe at
  `2026-07-28T00:11:08.760919+00:00`.

This is a lower-bound historical checkpoint. **Never roll the work back to 52
columns.** Read the live state and resume from the newest hash-valid completed
block.

The numerical policy remains frozen:

- Strict: Rust backend, tolerance `1e-8`, maximum 10,000 iterations.
- Fallback: Rust backend, tolerance `1e-6`, maximum 50,000 iterations.
- Fallback is permitted only after block-specific strict nonconvergence is
  documented.
- No fallback may change the sample, formula, outcomes, fixed effects,
  clustering, weights, contrasts, or estimands.

The live state is bound to:

- Provider measurement: `provider_master_v2_full_name_race_v1`
- Inference engine SHA-256:
  `fe6a21ca466dd58919b9e13e6b3ec511dbaf175fbf54f29d5ae38bbb3e6bc8c9`
- Provider gate SHA-256:
  `575095a279b632b407792142b6d92ec596a1d073781a6306479cfc695f22c786`
- Cohort gate SHA-256:
  `153197dd95d814b5189706f42e8f85bc5b74991266db81185343508acc688275`
- Provider-gender checkpoint SHA-256:
  `aa973aabe29f03a0af667e84ed8415ee1be4116a9391956c7567e83145baacdf`
- Race matrix manifest SHA-256:
  `a2cb7ccbfeb2aa8b86b1c3d3b2160c15ea6a2bb9a2a215638f54e5eb07f0295d`

## Required first actions on resumption

1. Read this file, `documentation/LIVE_PHASE2_EXECUTION_CHECKPOINT.md`,
   `documentation/Final_Analytical_Release_Execution_FROZEN.json`, the user
   deferral checkpoint, and all terminal markers.
2. Check, in this order:
   - final PASS marker;
   - final fail-closed marker;
   - current process command lines and start times;
   - the newest restart-safe state and its bindings;
   - canonical, post-canonical, and final-supervisor logs.
3. If the final PASS marker exists, do not rerun models. Verify the split-status
   JSON and all independent audits before inspecting or reporting estimates.
4. If a fail-closed marker exists, preserve it, identify the exact failed stage,
   and recover only through the frozen stage-specific sequence.
5. If a healthy canonical worker or supervisor is active, do not duplicate,
   restart, pause, or modify it. Monitor no more frequently than every 15
   minutes and do not narrate unchanged states.
6. If no protected process and no terminal marker exists, verify the latest
   restart-safe state and logs before running the canonical recovery command.
   Do not delete partial files unless a fail-closed audit proves they are
   uncommitted and the exact recovery procedure authorizes removal.
7. Do not inspect partial estimates to select specifications.

## Frozen continuation sequence

The authoritative recovery and execution details are in
`documentation/LIVE_PHASE2_EXECUTION_CHECKPOINT.md`. The intended sequence is:

1. Finish canonical common-primary race and gender models.
2. Finish outcome-specific primary models, cohort-definition analyses,
   multiplicity, and environment capture.
3. Run the corrected ED-only primary AMI analysis.
4. Run non-directional multiple testing.
5. Run the independent primary AMI audit.
6. Run the complete directional sequence:
   - all 4 gender dyads;
   - all 25 race dyads;
   - all 100 intersectional race-gender dyads;
   - all frozen directional contrasts;
   - both Florida and national physician-race priors;
   - all frozen confidence thresholds;
   - physician-level multiple imputation;
   - hard-classification and other frozen measurement sensitivities.
7. Preserve 2010–2024 as primary and 2005–2008 as a separately reconciled
   historical cohort using only comparable variables.
8. Keep AMI/Greenwood separate and use its corrected, frozen specification.
9. Complete robustness, sensitivity, estimability, and multiplicity families.
10. Run the independent global multiplicity reconstruction.
11. Run the full 573-file Phase 1 immutability audit.
12. Run the complete analytical-release audit.
13. Record the split release status only if every analytical gate passes.

The detached post-canonical and final-release supervisors already encode this
order. Prefer allowing them to complete over manually reissuing their stages.

## Required scientific invariants

- Physician race remains an algorithm-inferred, full-name probability vector
  without geography. It is not self-reported race and is not BISG.
- Retain probabilistic weighting and physician-level multiple imputation.
- Keep MD/DO physicians distinct from NP/PA and other clinicians.
- Never classify organizational NPIs as physicians.
- Preserve all frozen samples, outcomes, covariates, fixed effects, clustering,
  weights, estimands, directional contrasts, thresholds, priors, and
  multiplicity families.
- Mark sparse or non-estimable cells explicitly; never silently merge them.
- Use association language, not causal language.
- Maintain exact commands, execution order, hashes, source provenance, SAP
  deviations, numerical failures/fallbacks, estimability decisions, and
  machine-readable results.

## Documentation and public-release rule

At this pause, dossier, collaborator-report, DOCX/PDF, figure, rendering,
portfolio, and public-release work remains deferred. The saved resume prompt
explicitly lifts that deferral only after the analytical release has passed and
authorizes creation of the final local, public-safe package. It does not
authorize uploading restricted data or publishing to an external service
without separate confirmation.

## Resumption prompt

The exact paste-ready prompt is saved at:

`documentation/RESUME_PROMPT_FLORIDA_ED_PHASE2.txt`

## Completion condition

Do not claim the whole project is complete until:

1. `ANALYTICAL_RELEASE=PASS_INDEPENDENTLY_AUDITED`;
2. all required technical and collaborator deliverables are built from audited
   results;
3. report evidence, content, public-safety, render, and file-integrity audits
   pass; and
4. the final handoff inventory and navigation guide are verified.

