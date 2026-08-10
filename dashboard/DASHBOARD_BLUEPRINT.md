# Dashboard blueprint

## Purpose and audience

This seven-page Power BI dashboard is a portfolio and collaborator-orientation surface for data analysts, researchers, faculty, clinicians, and hiring reviewers. It answers: what was built, how it was controlled, what is safe to claim, and where work can resume. It is not a results dashboard and does not support causal interpretation.

## Visual system

- Canvas: 1280 x 720, 16:9, near-white background #F7F9FC.
- Primary/complete: blue #1F4E79. Validated safeguard: teal #2F6B5F. In progress: gold #C69214. Pending/historical: gray #6B7280. Deferred: purple #7A5195. Warning: orange #B45309.
- Use status text and icons as well as color. Never rely on red/green alone.
- Use Segoe UI, dark charcoal text, subtle gray separators, and no 3-D charts, gauges, decorative gradients, or unnecessary legends.
- Every page carries a footer: “Public-safe metadata and synthetic demonstration only; no row-level data or numerical concordance estimates.”

## Page wireframes

### 1. Executive Overview

```
[Title and status date]
[Encounter records] [Quarters] [Fields] [Schema families]
[Authorized sources -> Standardize -> Validate -> Measure -> Analyze]
[Components by status]          [Controlled status statement]
[Public disclosure boundary]
```

The reader should understand the scale, architecture, Phase 1 completion, Phase 2 incompleteness, and privacy boundary in under 30 seconds.

### 2. Coverage & Standardization

```
[Title] [Period slicer] [Year slicer] [Reconciliation] [Available] [Excluded]
[Available quarters by year]                       [Year x quarter matrix]
[Quarters by schema family]                        [Schema boundary table]
```

The reader should see 19 included years, 76 available quarters, explicit gaps in 2009 and 2025, and five schema families without seeing encounter counts by year.

### 3. Clinical & Visit Enhancements

```
[Title]
[Implemented] [Proxy only] [Unavailable] [Total inventory]
[Enhancements by status]          [Coding/grouping map]
[Detailed availability and guardrail table]
```

The reader should understand what was decoded and why triage, revisit, same-facility admission, and historical hourly LOS were not fabricated.

### 4. Provider & Facility Measurement

```
[Title]
[Master NPIs] [ED NPIs] [New NPIs] [Facilities] [Organizations called physicians = 0]
[Selected provider categories]       [Measurement control table]
[Race method and limitation]          [Gender/affiliation limitation]
```

The reader should understand provider master v2 as a measurement and coverage correction, with organizations separated from physicians and physician race explicitly described as probabilistic full-name inference—not BISG or self-report.

### 5. Cohort & Analytical Design

```
[Title]
[Primary cohort] [Historical cohort] [Never-pooled rule]
[M1 -> M2 -> M3 progression table]
[Current model-family status]         [Outcomes and interpretation guardrail]
```

The reader should understand cohort separation, adjustment progression, fixed effects/clustering at a high level, and why the work supports association language only.

### 6. Validation & Reproducibility

```
[Title]
[Controls] [Pass rate] [Synthetic input] [Synthetic output]
[Checks by stage]                    [Synthetic schema reconciliation]
[Validation ledger]
```

The reader should see the reconciliation, hashes, immutability, fail-closed gates, synthetic demonstration, and independent audit structure.

### 7. Completion & Handoff

```
[Title]
[Complete] [Pending] [Deferred] [Controlled overall status]
[Components by status]       [Continuation ledger]
[Verified gender-M2 restart point]
[No numerical results / no causal claim]
```

The reader should know precisely what another analyst can trust, what remains, and how to resume without rebuilding Phase 1.

## Interaction policy

Use only PeriodGroup and Year slicers on page 2. Do not create cross-page synchronized slicers that imply unsupported comparability. Do not configure drill-through: there is no public-safe row-level detail table. Use a page navigator on every page and one reset-filter bookmark on page 2.

## Source and disclosure notes

All numerical values are high-level, nondisclosive project metadata already represented in validated evidence or explicitly fictional. No numerical concordance coefficient, confidence interval, p-value, q-value, or substantive treatment-outcome finding is displayed.
