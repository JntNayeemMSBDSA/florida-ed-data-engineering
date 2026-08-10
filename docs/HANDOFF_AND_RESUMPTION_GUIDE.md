# Restricted-workspace handoff and resumption guide

This guide explains how an authorized collaborator can resume the unfinished analysis. It is not a command to start the pipeline, and the public repository alone is intentionally insufficient to recreate restricted encounter data.

## Authoritative state

At the handoff checkpoint:

- Phase 1 database construction and its independent validation are complete.
- Provider master v2, measurement gates, primary and historical cohorts, and historical compatible analyses are complete.
- Primary race M1-M3 computations and primary gender M1 are checkpointed, but no numerical concordance finding is released here.
- Primary gender M2 has no committed completion checkpoint and must restart from its beginning after validating dependencies.
- Gender M3, outcome-specific models, corrected primary AMI/Greenwood, directional dyads, measurement sensitivities, multiplicity, and the final independent release audits remain pending.

The authoritative pause record is [`frozen_methodology/USER_AUTHORIZED_HANDOFF_PAUSE_20260809T211227Z.md`](frozen_methodology/USER_AUTHORIZED_HANDOFF_PAUSE_20260809T211227Z.md). Older checkpoint documents are retained as audit history and must not override the newest timestamped checkpoint.

## Safety rules before resuming

1. Work only in the restricted research workspace; never place production inputs or model outputs in this public repository.
2. Verify the immutable Phase 1 release and source hashes before any Phase 2 restart.
3. Verify provider-v2, cohort, measurement-gate, configuration, and frozen-code hashes.
4. Confirm that the prior processes are stopped and that no duplicate estimator or supervisor is active.
5. Do not inspect partial estimates to alter specifications.
6. Treat completed computation as unreleased until the corresponding independent audit passes.
7. Preserve exact commands, logs, failures, fallbacks, manifests, hashes, and environment information.

## Safe restart sequence

1. Read the newest pause record, `RESUME_HERE.md`, the frozen statistical analysis plan, all applicable addenda, and the deviation log.
2. Reconcile the restricted workspace against its recorded input and checkpoint hashes.
3. Reconfirm Phase 1 immutability and the complete eligible NPI universe.
4. Accept race M1-M3 and gender M1 checkpoints only if their artifacts and dependency hashes validate.
5. Restart primary gender M2 from the beginning; do not attempt to infer completion from an initialization artifact.
6. Continue the frozen downstream order for gender M3, outcome-specific analyses, corrected primary AMI/Greenwood, directional dyads, measurement sensitivities/multiple imputation, and multiplicity.
7. Run the independent reconstruction and analytical-result audits.
8. Rerun the final Phase 1 immutability audit.
9. Create a terminal analytical PASS only if every required gate passes. Otherwise fail closed and write a durable recovery checkpoint.

## Completion language

Until the terminal audit passes, describe the project as an in-progress analytical release. Do not interpret checkpointed coefficients as findings. Even after completion, use association language because the design is observational unless a separately justified causal design is adopted.
