# From prototype to production

## Exploratory stage

The project began with an approximately 0.5% sample of 743,767 emergency-department encounter rows. The sample was useful for working through early field decoding, physician and facility enrichment, clinical grouping, and presentation ideas with faculty and a physician collaborator. It established that the source could support a richer, linked analytical structure and exposed practical problems that would matter at production scale.

The prototype was development work, not a miniature final release. Some early definitions were exploratory. Physician race work used earlier hard-label inputs; provider coverage was narrower; proposed revisit logic could not establish stable patient identity; and the sample-era outputs did not receive the complete production reconciliation and independent-audit framework.

The original sample dataset, prototype results, and uncorrected notebooks are not included here. The synthetic demonstration is newly generated and does not reconstruct the sample.

## Production redesign

The production pipeline changed the unit of work from a notebook-sized extract to a controlled quarterly build. It added:

- explicit recognition of five source-schema families;
- a quarter-aware ICD-9-CM to ICD-10-CM transition;
- a unique production encounter key without claiming patient identity;
- normalized diagnosis, diagnosis-category, procedure, and Elixhauser bridges;
- separate physician, affiliation, and facility dimensions;
- source-to-fact reconciliation for every quarter;
- structural-null rules for unavailable measures;
- manifests, hashes, machine-readable QA, and independent release validation; and
- restartable analytical tooling designed for the full cohort.

Phase 2 then corrected provider coverage and measurement before primary estimation. Provider master v2 expanded to all validated ED-observed NPIs, enforced entity and clinician-type rules, replaced surname-only race labeling with an official-dictionary full-name probability method, limited primary physician gender to recorded NPPES/CMS categories, and rebuilt the primary cohort from immutable Phase 1 facts.

## What remained continuous

The prototype did influence the production work. The focus on decoding, provider/facility enrichment, clinical grouping, and faculty-facing reporting carried forward. What did not carry forward automatically were the sample’s exact definitions, data products, or findings. Each retained idea had to be restated in production code and pass the later QA and audit gates.

That distinction is important when reading this portfolio: it shows an iterative development path without treating exploratory output as validated evidence.
