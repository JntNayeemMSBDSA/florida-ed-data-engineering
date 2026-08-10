# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/RUN_COHORT_DEFINITION_SENSITIVITIES.ps1
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
param(
    [Parameter()]
    [string]$WorkspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path,

    [Parameter()]
    [string]$Python = '',

    [Parameter()]
    [ValidateSet('build', 'estimate', 'audit')]
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
$Scratch = Join-Path $Temp 'cohort_definition_model_scratch'

New-Item -ItemType Directory -Force -Path $Logs, $MatrixRoot, $Scratch | Out-Null

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

$stages = @('build', 'estimate', 'audit')
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

$variants = @(
    @{
        Id = 'direct_plus_unique_license_nh_t50'
        Policy = 'race_direct_plus_unique_license_nh_t50'
    },
    @{
        Id = 'race_only_direct_t50'
        Policy = 'race_only_direct_t50'
    }
)
$outcomes = @(
    @{
        Id = 'los'
        Policy = 'los_outcome'
        Outcome = 'los_hours_primary_0_168'
    },
    @{
        Id = 'charge'
        Policy = 'charge_outcome'
        Outcome = 'total_charge_reported_real_2024'
    }
)
foreach ($variant in $variants) {
    foreach ($outcome in $outcomes) {
        $matrixId = "race__$($variant.Id)__$($outcome.Id)"
        Invoke-Step 'build' "07_prepare_${matrixId}" @(
            (Join-Path $Scripts '07_prepare_primary_model_matrix.py'),
            '--phase2', $Phase2,
            '--scratch', $MatrixRoot,
            '--cohort', 'race',
            '--analysis-sample', $outcome.Policy,
            '--eligibility-policy', $variant.Policy,
            '--matrix-id', $matrixId,
            '--threads', [string]$Threads,
            '--memory-limit', $MemoryLimit
        )
        Invoke-Step 'estimate' "08_estimate_${matrixId}" @(
            (Join-Path $Scripts '08_estimate_primary_models.py'),
            '--matrix-root', $MatrixRoot,
            '--matrix-id', $matrixId,
            '--scratch', (Join-Path $Scratch "$($variant.Id)\$($outcome.Id)"),
            '--output', (Join-Path $Phase2 "results\cohort_definition_adjusted\$($variant.Id)\$($outcome.Id)"),
            '--cohort', 'race',
            '--bootstrap-draws', '9999',
            '--seed', '20260726'
        )
        $auditId = "cohort_definition_$($variant.Id)_$($outcome.Id)"
        $matrixScratch = Join-Path $Scratch "$($variant.Id)\$($outcome.Id)"
        Invoke-Step 'audit' "30e_audit_${auditId}" @(
            (Join-Path $Scripts '30e_checkpoint_primary_matrix_audit.py'),
            '--phase2', $Phase2,
            '--matrix-root', $MatrixRoot,
            '--matrix-id', $matrixId,
            '--primary-scratch', $matrixScratch,
            '--scratch-id', 'race',
            '--results-root', (Join-Path $Phase2 "results\cohort_definition_adjusted\$($variant.Id)\$($outcome.Id)"),
            '--cohort', 'race',
            '--audit-id', $auditId,
            '--expected-analysis-sample', $outcome.Policy,
            '--expected-eligibility-policy', $variant.Policy,
            '--expected-outcome', $outcome.Outcome,
            '--expected-confirmatory', 'false',
            '--row-chunk', '333333'
        )
        Invoke-Step 'audit' "32_compact_${auditId}" @(
            (Join-Path $Scripts '32_compact_validated_model_intermediates.py'),
            '--phase2', $Phase2,
            '--checkpoint-json', (Join-Path $Phase2 "qa\model_audit_checkpoints\$auditId.json"),
            '--matrix-root', $MatrixRoot,
            '--matrix-id', $matrixId,
            '--scratch-dir', (Join-Path $matrixScratch 'race'),
            '--execute'
        )
    }
}

Invoke-Step 'audit' '30f_aggregate_cohort_definition_results_audit' @(
    (Join-Path $Scripts '30f_aggregate_model_audit_checkpoints.py'),
    '--phase2', $Phase2,
    '--expected-audit-ids', (
        'cohort_definition_direct_plus_unique_license_nh_t50_los,' +
        'cohort_definition_direct_plus_unique_license_nh_t50_charge,' +
        'cohort_definition_race_only_direct_t50_los,' +
        'cohort_definition_race_only_direct_t50_charge'
    ),
    '--output-stem', 'independent_cohort_definition_results_audit',
    '--audit-id', 'cohort_definition_adjusted_results_audit_v2'
)

"[$(Get-Date -Format o)] RUN_COHORT_DEFINITION_SENSITIVITIES completed successfully." |
    Tee-Object -FilePath (Join-Path $Logs 'RUN_COHORT_DEFINITION_SENSITIVITIES_COMPLETE.log')
