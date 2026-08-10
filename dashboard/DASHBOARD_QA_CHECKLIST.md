# Dashboard QA checklist

## Data and model

- [ ] Exactly 14 named source tables imported; worksheet object not imported.
- [ ] Eight active one-to-many, single-direction relationships; no others.
- [ ] Declared keys unique and foreign keys resolved.
- [ ] Numeric, date, Boolean, and text types match dashboard_data_dictionary.csv.
- [ ] Technical keys, order fields, source keys, and disclosure fields hidden from Report view.
- [ ] Cards reconcile to the checkpoint values in the clickbook.
- [ ] No implicit measure is used where an explicit DAX measure exists.

## Filters and interactions

- [ ] Page 2 PeriodGroup and Year slicers filter only intended coverage visuals.
- [ ] Reset_Page_2 restores the documented default.
- [ ] No synchronized slicer implies historical/primary outcome comparability.
- [ ] No drill-through to nonexistent row-level detail.
- [ ] Page navigation works from every page.

## Visual and accessibility

- [ ] Every page is 1280 x 720 and readable at 100% zoom.
- [ ] Titles, subtitles, units, denominators, and caveats are visible where needed.
- [ ] Bars comparing absolute values start at zero.
- [ ] No 3-D charts, gauges, unnecessary pies, decorative gradients, or redundant legends.
- [ ] Color palette matches the theme and status semantics.
- [ ] Statuses use text/icons as well as color.
- [ ] Alt text and tab order are complete.
- [ ] No label, title, card value, legend, or table text is clipped.

## Scientific and status language

- [ ] Phase 1 is labeled complete and independently validated.
- [ ] Race M1-M3 and gender M1 are labeled as completed estimation, not final analytical release.
- [ ] Gender M2 restart point is stated exactly.
- [ ] Pending outcome-specific, directional, AMI, multiplicity, and final audits are visible.
- [ ] Historical 2005-2008 and primary 2010-2024 remain separate.
- [ ] Race is algorithm-inferred, probabilistic, full-name based, not BISG, and not self-reported.
- [ ] Recorded physician-gender fields are not described as self-identified gender identity.
- [ ] Association language is used; no causal claim appears.

## Privacy and publication

- [ ] Data source is only dashboard_data/POWER_BI_IMPORT.xlsx.
- [ ] No encounter rows or patient identifiers.
- [ ] No provider names, NPIs, or provider-level rows.
- [ ] No facility identifiers/names or facility-level rows.
- [ ] No purchased source file, Parquet, matrix, result table, credential, email, or private path.
- [ ] No concordance coefficient, confidence interval, p-value, q-value, or treatment-outcome result.
- [ ] Every synthetic visual is labeled fictional/synthetic.
- [ ] PBIX has not been published before final QA.

## Performance

- [ ] Initial open and page navigation are responsive.
- [ ] No auto date/time tables are needed; disable Auto date/time if it creates hidden date tables.
- [ ] No unused imported worksheet or duplicate query.
- [ ] Visual count and cross-highlighting remain modest.
