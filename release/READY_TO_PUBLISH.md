# Local publication gate

This file defines the gate; it does not authorize a GitHub push.

The repository is `READY_TO_PUBLISH` only when:

- the synthetic demonstration and automated tests pass;
- Power BI static and render QA pass;
- source provenance and repository inventory hashes reconcile;
- privacy and disclosure validation pass;
- a clean fresh-clone check passes;
- the configured remote is verified as the intended `florida-ed-data-engineering` repository;
- the working tree is clean; and
- the annotated local tag `READY_TO_PUBLISH_20260810` points to the validated commit.

The user authorized deployment to the existing public repository on 2026-08-10. The publication operation may proceed only after all gates pass and must still exclude restricted data and unpublished numerical estimates.
