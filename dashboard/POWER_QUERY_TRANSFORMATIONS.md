# Power Query transformations

## Recommended import path

Use **dashboard_data/POWER_BI_IMPORT.xlsx** and select the 14 named Excel tables. The workbook is already normalized for Power BI. Do not use the worksheet object named PowerBI_Tables and do not use the Folder connector.

## Required transformations

No filtering, joins, grouping, parsing, or value replacement is required. In Power Query, verify types only:

- Whole number: keys that are numeric, Year, Quarter, order fields, flags, MetricValue, QuarterCount.
- Date: AsOfDate, StatusAsOf.
- True/False: SyntheticFlag.
- Text: every other field, including text keys.

After setting types, select **Close & Apply**. Do not derive analytical results in Power Query. Do not edit source values. Do not point any query to the private research workspace.

## Optional parameterized M pattern

The UI import is recommended. If the workbook later moves, change the source path through **Data source settings**. A custom M function is unnecessary for this static portfolio snapshot and would add maintenance risk.

## Refresh rule

Refresh is allowed only after a new public-safe import workbook has passed the disclosure and preparation validators. Never substitute a Phase 1 fact, Phase 2 cohort partition, provider master, result table, Parquet file, or model matrix.
