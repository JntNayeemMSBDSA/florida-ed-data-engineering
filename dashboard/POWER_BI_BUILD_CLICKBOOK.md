# Power BI Desktop build clickbook

Follow these steps in order. Do not improvise with private data or analytical-result files.

## 1. Start and save the file

1. Open **Power BI Desktop**.
2. Select **File > Save As**.
3. Browse to this dashboard-preparation folder.
4. Save as **Florida_ED_Project_Portfolio_Dashboard.pbix**.
5. If Power BI offers to enable preview features, leave the current settings unchanged.

## 2. Import the prepared tables

1. On the Home ribbon, choose **Get data > Excel workbook**.
2. Open **dashboard_data/POWER_BI_IMPORT.xlsx**.
3. In Navigator, check these named tables—not the PowerBI_Tables worksheet:

   - DimPeriod
   - DimSchemaFamily
   - DimProjectStage
   - DimMetric
   - DimClinicalDomain
   - DimCodingMap
   - DimModelSpec
   - FactProjectCoverage
   - FactPartitionStatus
   - FactEnhancementCoverage
   - FactProviderMeasurement
   - FactValidationStatus
   - FactAnalyticalStatus
   - FactSyntheticDemonstration

4. Select **Transform Data**.
5. In the Queries pane, click each query and confirm its name exactly matches the table name.
6. Set types according to dashboard_data_dictionary.csv. Use the icon at the left of each column heading or **Transform > Data type**.
7. Confirm AsOfDate and StatusAsOf are **Date**, SyntheticFlag is **True/False**, numeric keys/counts/orders/flags are **Whole number**, and all remaining columns are **Text**.
8. Select **Home > Close & Apply**.

Checkpoint: Model view must show 14 imported tables and zero load errors.

## 3. Build the relationships

1. Select the **Model** icon on the left.
2. Select **Home > Manage relationships > New** for each relationship below.
3. Set cardinality to **One to many (1:*)**, cross-filter direction to **Single**, and make the relationship active.

1. DimPeriod[PeriodKey] (one) -> FactPartitionStatus[PeriodKey] (many)
2. DimSchemaFamily[SchemaFamilyKey] (one) -> FactPartitionStatus[SchemaFamilyKey] (many)
3. DimProjectStage[StageKey] (one) -> FactValidationStatus[StageKey] (many)
4. DimProjectStage[StageKey] (one) -> FactAnalyticalStatus[StageKey] (many)
5. DimMetric[MetricKey] (one) -> FactProjectCoverage[MetricKey] (many)
6. DimMetric[MetricKey] (one) -> FactProviderMeasurement[MetricKey] (many)
7. DimClinicalDomain[ClinicalDomainKey] (one) -> FactEnhancementCoverage[ClinicalDomainKey] (many)
8. DimModelSpec[ModelSpecKey] (one) -> FactAnalyticalStatus[ModelSpecKey] (many)

4. Do not create any other relationship.
5. Confirm Power BI did not create hidden automatic relationships. Delete any relationship not listed above.

Checkpoint: there are eight active relationships, no many-to-many relationships, and no bidirectional filters.

## 4. Set sort-by columns

In Data view, select the display column, then **Column tools > Sort by column**:

- DimPeriod[QuarterLabel] by DimPeriod[Quarter]
- DimPeriod[PeriodGroup] by DimPeriod[PeriodGroupOrder]
- DimSchemaFamily[SchemaFamilyLabel] by DimSchemaFamily[DisplayOrder]
- DimProjectStage[StageName] by DimProjectStage[StageOrder]
- DimMetric[MetricName] by DimMetric[DisplayOrder]
- DimClinicalDomain[ClinicalDomainName] by DimClinicalDomain[DisplayOrder]
- DimModelSpec[ModelLabel] by DimModelSpec[ModelOrder]
- FactEnhancementCoverage[EnhancementName] by FactEnhancementCoverage[DisplayOrder]
- FactValidationStatus[ValidationCheck] by FactValidationStatus[CheckOrder]
- FactAnalyticalStatus[ComponentStatus] by FactAnalyticalStatus[StatusOrder]

## 5. Create the measure table and measures

1. Select **Home > Enter data**.
2. Name the column **Placeholder**, enter 1 in the first row, and name the table **Measures**.
3. Select **Load**.
4. In Model view, right-click Measures[Placeholder] and choose **Hide in report view**.
5. Open POWER_BI_MEASURES.dax.
6. For each measure block, right-click the Measures table and choose **New measure**.
7. Copy the measure name and expression from the block into the formula bar. Create one measure at a time.
8. In Measure tools, set the format shown in each block and set **Display folder** to the folder listed in METRIC_AND_MEASURE_DICTIONARY.csv.

Checkpoint values before filters:

- Total Validated Encounters = 148,686,146
- Completed Quarterly Partitions = 76
- Covered Years = 19
- Standardized Encounter Fields = 342
- Schema Families = 5
- Phase 1 Completion % = 100.0%
- Partition Reconciliation % = 100.0%
- Provider Master V2 NPIs = 1,813,546
- Facility Dimension Rows = 240
- Organizational NPIs Classified as Physicians = 0
- Synthetic Input Rows = 800
- Synthetic Output Rows = 800

Stop and correct the model if any checkpoint differs.

## 6. Hide technical fields

After relationships and sorting work, hide from Report view:

- Every column ending in Key
- Every field containing Order
- SourceArtifactKey
- DisclosureClass
- SourceClass
- FormatString

Do not hide fields named MetricName, MetricValue, Status, Year, QuarterLabel, PeriodGroup, ComponentName, ValidationCheck, EvidenceSummary, or NextAction.

## 7. Apply the theme and page defaults

1. Switch to Report view.
2. Select **View > Themes > Browse for themes**.
3. Open **powerbi_theme.json**.
4. For every page, open **Format page > Canvas settings > Type > Custom** and enter Width **1280** and Height **720**.
5. Set canvas background to **#F7F9FC**, transparency **0%**.
6. Set wallpaper to white, transparency **100%**.
7. Turn off visual shadows unless specifically instructed.
8. Use 8-pixel corner radius only for cards and text-callout containers.

## 8. Create the seven pages

Rename pages exactly:

1. Executive Overview
2. Coverage & Standardization
3. Clinical & Visit Enhancements
4. Provider & Facility Measurement
5. Cohort & Analytical Design
6. Validation & Reproducibility
7. Completion & Handoff

Use POWER_BI_VISUAL_SPECIFICATION.csv for the exact X, Y, width, height, title, fields, filters, sorting, and purpose of every visual. After selecting a visual, enter position and size under **Format visual > General > Properties**.

### Shared formatting for all pages

- Page title: Segoe UI Semibold, 22 pt, #1F2937.
- Subtitle: 10 pt, #4B5563.
- Visual titles: 12 pt, semibold, left aligned.
- Body/table text: 9-10 pt.
- Card callout: 24-30 pt; category label 10 pt.
- Chart background: white; border #D9E2EC at 1 px; no shadow.
- Gridlines: #E5E7EB, thin.
- Data labels: on only where the specification says; no display-unit abbreviation for record/provider cards.
- Add this 9-pt footer at Y=660, X=24, W=1232, H=20 on every page: **Public-safe metadata and synthetic demonstration only; no row-level data or numerical concordance estimates.**

### Page 1 - Executive Overview

1. Add the title and subtitle text boxes from P1V01-P1V02.
2. Add four **Card (new)** visuals using P1V03-P1V06. Set display units to None and thousands separator on.
3. Build P1V07 with six rounded rectangles and five right arrows. Use white fills, #1F4E79 outlines, and the exact architecture text in the specification. This is intentionally static because it documents process, not data.
4. Add P1V08 as a clustered bar. Use ComponentStatus on Y and count of AnalyticalStatusKey on X. Show labels and hide the legend.
5. Add P1V09 as a multi-row card using [Dashboard Overall Status]. Turn category label off and word wrap on.
6. Add P1V10 as an amber-bordered text box.

Validation: the four cards must show 148,686,146; 76; 342; and 5. The page must state that Phase 2 is unfinished without showing any model estimate.

### Page 2 - Coverage & Standardization

1. Add the title.
2. Add dropdown slicers for PeriodGroup and Year. Keep all values selected by default.
3. Add the three cards P2V04-P2V06.
4. Add P2V07. Set Y-axis start 0, end 4, interval 1. Set data color #1F4E79. Keep 2009 and 2025 visible at zero.
5. Add P2V08 matrix. Rows=Year, columns=QuarterLabel, values=Sum of AvailableFlag. Disable subtotals. Conditional formatting for values: 1 uses #DCEAF7 background and #1F4E79 font; 0 uses #F3F4F6 background and #6B7280 font.
6. Add P2V09 using DimSchemaFamily only. Use horizontal bars and data labels.
7. Add P2V10 table and sort by DisplayOrder.
8. Select **Format > Edit interactions**. Both slicers should filter P2V04, P2V06-P2V08. They must not change the fixed project-total card P2V05 or schema-family table/bar; set those interactions to None.

Validation: years 2005-2008 and 2010-2024 show four available quarters; 2009 and 2025 show zero. Schema-family quarter counts must sum to 76.

### Page 3 - Clinical & Visit Enhancements

1. Add the title and four cards P3V02-P3V05.
2. Add P3V06 with ImplementationStatus on Y and count of EnhancementKey on X. Use direct labels and no legend. Apply colors: IMPLEMENTED #1F4E79; IMPLEMENTED_PRIMARY_ONLY #2F6B5F; PROXY_ONLY #C69214; STRUCTURALLY_UNAVAILABLE #6B7280.
3. Add P3V07 as a table with word wrap and alternating rows off.
4. Add P3V08 as a table. Show both status text and conditional-format icons. Do not use icons alone.

Validation: the unavailable rows must explicitly include true triage, same-facility admission, 7-day revisit, and 30-day revisit. The hourly-LOS row must say primary-only and must not imply historical imputation.

### Page 4 - Provider & Facility Measurement

1. Add the title and five cards P4V02-P4V06.
2. Add P4V07. Add a visual-level filter retaining only MetricKey PM006 through PM009. In the subtitle write: **Selected validated categories; not a complete part-to-whole distribution.**
3. Add P4V08. Filter to PM001-PM011. Use MetricName, MetricValue, MeasurementScope, MetricStatus.
4. Add the three race, gender, and facility method/limitation text boxes exactly as specified.

Validation: the fifth card must be zero and the facility card must be 240. The page must say organizations are not physicians, physician race is probabilistic full-name inference, no geography was used, and the method is not BISG or self-reported identity.

### Page 5 - Cohort & Analytical Design

1. Add the title, two cohort cards, and the separation-rule text box.
2. Add the M1-M3 table using DimModelSpec and sort by ModelOrder.
3. Add P5V06 and filter StageKey to S04.
4. Add the outcomes and interpretation callout P5V07.

Validation: primary and historical cohorts must remain visually separate. Race M1-M3 and gender M1 may be labeled as completed estimation, but the page must also show the pending independent analytical-release audit and must not display coefficients or significance.

### Page 6 - Validation & Reproducibility

1. Add the title and four cards.
2. Add P6V06 with StageName on Y and count of ValidationKey on X. Sort StageName by StageOrder.
3. Add P6V07. Apply the visual filter DemoSection=Schema reconciliation. Use MetricName as legend and MetricValue as Y. Use blue for input and gold with an outline for output. Subtitle: **Fictional deterministic demonstration; not Florida encounter data.**
4. Add P6V08 as a table. Use conditional icons plus visible status text.

Validation: synthetic input and output both equal 800. The pass-rate card is 100% because the verified pause state is excluded from the validation denominator; this does not imply final analytical release.

### Page 7 - Completion & Handoff

1. Add the title, three status cards, and controlled-status multi-row card.
2. Add P7V06 with ComponentStatus on Y and count of AnalyticalStatusKey on X. Sort by StatusOrder.
3. Add P7V07 and sort by StageOrder then AnalyticalStatusKey.
4. Add P7V08 and P7V09 as static guardrail text boxes.

Validation: gender M2 must say “restart from its beginning after hash validation.” Phase 1 must remain immutable. The page must not claim the entire analytical release is complete.

## 9. Navigation and reset behavior

1. On each page, select **Insert > Buttons > Navigator > Page navigator**.
2. Position it at X=24, Y=684, W=1232, H=28. If the footer overlaps, move the footer to Y=654.
3. Use selected fill #1F4E79 with white text; default fill white with #1F4E79 text.
4. On page 2, clear slicers to their all-selected default.
5. Open **View > Bookmarks**, choose **Add**, rename it **Reset_Page_2**, and ensure Data and Current page are checked.
6. Insert a blank button at X=1160, Y=74, W=96, H=32, text **Reset**. Turn Action on, Type=Bookmark, Bookmark=Reset_Page_2.
7. Do not add drill-through pages. The public dataset intentionally has no row-level detail grain.

## 10. Accessibility and interactions

1. For each visual, set **General > Alt text** to the AnalyticalQuestion in POWER_BI_VISUAL_SPECIFICATION.csv plus the visual title.
2. Open **View > Selection** and rename every visual to its VisualID followed by its title.
3. Open **View > Tab order** and order title, slicers, KPI cards, charts, tables, notes, navigation.
4. Verify every state encoded by color is also stated in text.
5. Do not use automatic insights, Q&A visuals, custom visuals, maps, or AI-generated narratives.

## 11. Final local checks and save

1. Click every page-navigation button.
2. Test page 2 slicers and Reset.
3. Check that titles, labels, and wrapped text are not clipped at 100% zoom.
4. Confirm there are no blank visuals, (Blank) categories, implicit Sum/Count labels exposed to viewers, or unexpected relationships.
5. Confirm no numerical concordance estimates appear anywhere, including tooltips.
6. Select **File > Options and settings > Data source settings** and confirm the only source is POWER_BI_IMPORT.xlsx in this staging package.
7. Save the PBIX.
8. Do not publish to Power BI Service or GitHub yet.

Next, use POWER_BI_FINAL_QA_PROMPT.txt in a new Codex task for the independent dashboard review.
