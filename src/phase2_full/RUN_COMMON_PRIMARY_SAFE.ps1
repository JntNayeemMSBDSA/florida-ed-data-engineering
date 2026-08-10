# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/RUN_COMMON_PRIMARY_SAFE.ps1
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
param(
    [Parameter()]
    [string]$WorkspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path,

    [Parameter()]
    [string]$Python = '',

    [Parameter()]
    [ValidateSet('build', 'estimate', 'postmodels', 'audit', 'compact')]
    [string]$StartAt = 'build',

    [Parameter()]
    [int]$Threads = 12,

    [Parameter()]
    [string]$MemoryLimit = '24GB'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Phase2 = Join-Path $WorkspaceRoot 'outputs\florida_ed_concordance_analysis_20260726'
$Temp = Join-Path $WorkspaceRoot 'tmp\florida_ed_concordance_analysis_20260726'
$Scripts = Join-Path $Phase2 'scripts'
$Logs = Join-Path $Phase2 'qa\run_logs'
$MatrixRoot = Join-Path $Phase2 'analysis_data\model_matrices'
$PrimaryScratch = Join-Path $Temp 'common_primary_model_scratch'

New-Item -ItemType Directory -Force -Path $Logs, $MatrixRoot, $PrimaryScratch | Out-Null

if ([string]::IsNullOrWhiteSpace($Python)) {
    $resolvedPython = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $resolvedPython) {
        throw 'Python was not found on PATH. Supply -Python explicitly.'
    }
    $Python = $resolvedPython.Source
}
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Python runtime not found: $Python"
}

$env:PYTHONPATH = Join-Path $Temp 'pydeps'
$env:PYTHONHASHSEED = '0'
$env:OMP_NUM_THREADS = [string][Math]::Max(1, [Math]::Min($Threads, 16))

$stages = @('build', 'estimate', 'postmodels', 'audit', 'compact')
$startIndex = [Array]::IndexOf($stages, $StartAt)

function Invoke-Step {
    param(
        [Parameter(Mandatory)]
        [string]$Stage,
        [Parameter(Mandatory)]
        [string]$Name,
        [Parameter(Mandatory)]
        [string[]]$Arguments
    )
    if ([Array]::IndexOf($stages, $Stage) -lt $startIndex) {
        return
    }
    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $log = Join-Path $Logs "${stamp}_${Name}.log"
    "[$(Get-Date -Format o)] START $Name" | Tee-Object -FilePath $log
    $previousErrorAction = $ErrorActionPreference
    $processExitCode = -1
    try {
        $ErrorActionPreference = 'Continue'
        & $Python @Arguments 2>&1 | Tee-Object -FilePath $log -Append
        $processExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorAction
    }
    if ($processExitCode -ne 0) {
        throw "Step '$Name' failed. See $log"
    }
    "[$(Get-Date -Format o)] PASS $Name" | Tee-Object -FilePath $log -Append
}

foreach ($cohort in @('race', 'sex_gender')) {
    Invoke-Step 'build' "07_prepare_common_primary_${cohort}" @(
        (Join-Path $Scripts '07_prepare_primary_model_matrix.py'),
        '--phase2', $Phase2,
        '--scratch', $MatrixRoot,
        '--cohort', $cohort,
        '--analysis-sample', 'common_primary',
        '--matrix-id', $cohort,
        '--threads', [string]$Threads,
        '--memory-limit', $MemoryLimit
    )
    Invoke-Step 'estimate' "08_estimate_common_primary_${cohort}" @(
        (Join-Path $Scripts '08_estimate_primary_models.py'),
        '--matrix-root', $MatrixRoot,
        '--matrix-id', $cohort,
        '--scratch', $PrimaryScratch,
        '--output', (Join-Path $Phase2 'results\models'),
        '--cohort', $cohort,
        '--bootstrap-draws', '9999',
        '--seed', '20260726'
    )
}

Invoke-Step 'postmodels' '18_race_threshold_probability_sensitivities' @(
    (Join-Path $Scripts '18_race_threshold_probability_sensitivities.py'),
    '--phase2', $Phase2,
    '--matrix-root', $MatrixRoot,
    '--scratch', (Join-Path $Temp 'race_threshold_models'),
    '--output', (Join-Path $Phase2 'results'),
    '--bootstrap-draws', '9999',
    '--seed', '20260726'
)

foreach ($cohort in @('race', 'sex_gender')) {
    Invoke-Step 'postmodels' "25_outcome_appropriate_glm_${cohort}" @(
        (Join-Path $Scripts '25_outcome_appropriate_glm_sensitivities.py'),
        '--phase2', $Phase2,
        '--matrix-root', $MatrixRoot,
        '--output', (Join-Path $Phase2 'results\outcome_appropriate_glm'),
        '--cohort', $cohort,
        '--target-rows', '2000000',
        '--tolerance', '1e-8',
        '--max-iterations', '100',
        '--seed', '20260726'
    )

    Invoke-Step 'postmodels' "19_heterogeneity_models_${cohort}" @(
        (Join-Path $Scripts '19_heterogeneity_models.py'),
        '--phase2', $Phase2,
        '--matrix-root', $MatrixRoot,
        '--primary-scratch', $PrimaryScratch,
        '--scratch', (Join-Path $Temp 'heterogeneity'),
        '--output', (Join-Path $Phase2 'results\heterogeneity'),
        '--cohort', $cohort,
        '--bootstrap-draws', '9999',
        '--seed', '20260726'
    )

    Invoke-Step 'postmodels' "19c_classified_subjectivity_${cohort}" @(
        (Join-Path $Scripts '19c_classified_subjectivity_sensitivity.py'),
        '--phase2', $Phase2,
        '--matrix-root', $MatrixRoot,
        '--scratch', (Join-Path $Temp 'classified_subjectivity'),
        '--output', (Join-Path $Phase2 'results\classified_subjectivity'),
        '--cohort', $cohort,
        '--block-columns', '4',
        '--tolerance', '1e-8',
        '--bootstrap-draws', '9999',
        '--seed', '20260726'
    )

    Invoke-Step 'postmodels' "26_leave_one_year_out_${cohort}" @(
        (Join-Path $Scripts '26_leave_one_year_out_primary_models.py'),
        '--phase2', $Phase2,
        '--matrix-root', $MatrixRoot,
        '--primary-scratch', $PrimaryScratch,
        '--scratch', (Join-Path $Temp 'leave_one_year_out'),
        '--output', (Join-Path $Phase2 'results\leave_one_year_out'),
        '--cohort', $cohort,
        '--block-columns', '4',
        '--tolerance', '1e-8',
        '--bootstrap-draws', '9999',
        '--seed', '20260726'
    )

    Invoke-Step 'postmodels' "27_exact_subset_sensitivities_${cohort}" @(
        (Join-Path $Scripts '27_exact_subset_sensitivities.py'),
        '--phase2', $Phase2,
        '--matrix-root', $MatrixRoot,
        '--primary-scratch', $PrimaryScratch,
        '--scratch', (Join-Path $Temp 'exact_subset_sensitivities'),
        '--output', (Join-Path $Phase2 'results\exact_subset_sensitivities'),
        '--cohort', $cohort,
        '--block-columns', '4',
        '--tolerance', '1e-8',
        '--bootstrap-draws', '9999',
        '--seed', '20260726'
    )

    Invoke-Step 'postmodels' "28_influential_facility_exact_refits_${cohort}" @(
        (Join-Path $Scripts '28_influential_facility_exact_refits.py'),
        '--phase2', $Phase2,
        '--matrix-root', $MatrixRoot,
        '--primary-scratch', $PrimaryScratch,
        '--scratch', (Join-Path $Temp 'influential_facility_exact_refits'),
        '--output', (Join-Path $Phase2 'results\influential_facility'),
        '--cohort', $cohort,
        '--top-per-outcome', '5',
        '--block-columns', '4',
        '--tolerance', '1e-8',
        '--bootstrap-draws', '9999',
        '--seed', '20260726'
    )

    Invoke-Step 'postmodels' "24_negative_control_${cohort}" @(
        (Join-Path $Scripts '24_negative_control_analysis.py'),
        '--phase2', $Phase2,
        '--matrix-root', $MatrixRoot,
        '--primary-scratch', $PrimaryScratch,
        '--scratch', (Join-Path $Temp 'negative_control'),
        '--output', (Join-Path $Phase2 'results\negative_control'),
        '--cohort', $cohort,
        '--bootstrap-draws', '9999',
        '--seed', '20260726'
    )
}

Invoke-Step 'postmodels' '19b_payer_category_heterogeneity' @(
    (Join-Path $Scripts '19b_payer_category_heterogeneity.py'),
    '--phase2', $Phase2,
    '--matrix-root', $MatrixRoot,
    '--primary-scratch', $PrimaryScratch,
    '--scratch', (Join-Path $Temp 'payer_category_heterogeneity'),
    '--output', (Join-Path $Phase2 'results\payer_category_heterogeneity'),
    '--bootstrap-draws', '9999',
    '--seed', '20260726'
)

Invoke-Step 'postmodels' '21_intersectional_analysis' @(
    (Join-Path $Scripts '21_intersectional_analysis.py'),
    '--phase2', $Phase2,
    '--matrix-root', $MatrixRoot,
    '--scratch', (Join-Path $Temp 'intersectional'),
    '--output', (Join-Path $Phase2 'results\intersectional'),
    '--bootstrap-draws', '9999',
    '--seed', '20260726'
)

Invoke-Step 'postmodels' '23_race_proxy_multiple_imputation' @(
    (Join-Path $Scripts '23_race_proxy_multiple_imputation.py'),
    '--phase2', $Phase2,
    '--matrix-root', $MatrixRoot,
    '--primary-scratch', $PrimaryScratch,
    '--scratch', (Join-Path $Temp 'race_proxy_mi'),
    '--output', (Join-Path $Phase2 'results\race_proxy_multiple_imputation'),
    '--imputations', '20',
    '--bootstrap-draws', '9999',
    '--seed', '20260726'
)

Invoke-Step 'audit' '30_independent_primary_results_audit' @(
    (Join-Path $Scripts '30_independent_primary_results_audit.py'),
    '--phase2', $Phase2,
    '--matrix-root', $MatrixRoot,
    '--primary-scratch', $PrimaryScratch,
    '--row-chunk', '333333'
)

Invoke-Step 'audit' '30d_independent_payer_heterogeneity_audit' @(
    (Join-Path $Scripts '30d_independent_payer_heterogeneity_audit.py'),
    '--phase2', $Phase2,
    '--matrix-root', $MatrixRoot,
    '--primary-scratch', $PrimaryScratch,
    '--payer-scratch', (Join-Path $Temp 'payer_category_heterogeneity'),
    '--row-chunk', '333333'
)

Invoke-Step 'audit' '33_audit_common_postmodels' @(
    (Join-Path $Scripts '33_audit_common_postmodels.py'),
    '--phase2', $Phase2,
    '--matrix-root', $MatrixRoot
)

foreach ($cohort in @('race', 'sex_gender')) {
    $auditId = "common_primary_${cohort}"
    Invoke-Step 'audit' "30e_audit_${auditId}" @(
        (Join-Path $Scripts '30e_checkpoint_primary_matrix_audit.py'),
        '--phase2', $Phase2,
        '--matrix-root', $MatrixRoot,
        '--matrix-id', $cohort,
        '--primary-scratch', $PrimaryScratch,
        '--scratch-id', $cohort,
        '--results-root', (Join-Path $Phase2 'results\models'),
        '--cohort', $cohort,
        '--audit-id', $auditId,
        '--expected-analysis-sample', 'common_primary',
        '--expected-eligibility-policy', 'primary',
        '--expected-outcome', 'los_hours_primary_0_168',
        '--expected-confirmatory', 'false',
        '--row-chunk', '333333'
    )

    Invoke-Step 'compact' "32_compact_${auditId}" @(
        (Join-Path $Scripts '32_compact_validated_model_intermediates.py'),
        '--phase2', $Phase2,
        '--checkpoint-json', (Join-Path $Phase2 "qa\model_audit_checkpoints\$auditId.json"),
        '--matrix-root', $MatrixRoot,
        '--matrix-id', $cohort,
        '--scratch-dir', (Join-Path $PrimaryScratch $cohort),
        '--execute'
    )
}

Invoke-Step 'compact' '30f_aggregate_common_primary_checkpoints' @(
    (Join-Path $Scripts '30f_aggregate_model_audit_checkpoints.py'),
    '--phase2', $Phase2,
    '--expected-audit-ids', (
        'common_primary_race,' +
        'common_primary_sex_gender'
    ),
    '--output-stem', 'independent_common_primary_checkpoint_audit',
    '--audit-id', 'common_primary_checkpoint_audit_v2'
)

"[$(Get-Date -Format o)] RUN_COMMON_PRIMARY_SAFE completed successfully." |
    Tee-Object -FilePath (Join-Path $Logs 'RUN_COMMON_PRIMARY_SAFE_COMPLETE.log')
