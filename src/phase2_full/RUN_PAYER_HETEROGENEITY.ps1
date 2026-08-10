# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/RUN_PAYER_HETEROGENEITY.ps1
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
param(
    [Parameter()]
    [string]$WorkspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path,

    [Parameter()]
    [string]$Python = '',

    [Parameter()]
    [ValidateSet('estimate', 'audit')]
    [string]$StartAt = 'estimate',

    [Parameter()]
    [int]$Threads = 12
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Phase2 = Join-Path $WorkspaceRoot 'outputs\florida_ed_concordance_analysis_20260726'
$Temp = Join-Path $WorkspaceRoot 'tmp\florida_ed_concordance_analysis_20260726'
$Scripts = Join-Path $Phase2 'scripts'
$Logs = Join-Path $Phase2 'qa\run_logs'
$MatrixRoot = Join-Path $Phase2 'analysis_data\model_matrices'
$PrimaryScratch = Join-Path $Temp 'primary_model_scratch'
$PayerScratch = Join-Path $Temp 'payer_category_heterogeneity'
$PayerResults = Join-Path $Phase2 'results\payer_category_heterogeneity'

New-Item -ItemType Directory -Force -Path $Logs, $PayerScratch, $PayerResults | Out-Null

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

$stages = @('estimate', 'audit')
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

Invoke-Step 'estimate' '19b_payer_category_heterogeneity' @(
    (Join-Path $Scripts '19b_payer_category_heterogeneity.py'),
    '--phase2', $Phase2,
    '--matrix-root', $MatrixRoot,
    '--primary-scratch', $PrimaryScratch,
    '--scratch', $PayerScratch,
    '--output', $PayerResults,
    '--bootstrap-draws', '9999',
    '--seed', '20260726'
)

Invoke-Step 'audit' '30d_independent_payer_heterogeneity_audit' @(
    (Join-Path $Scripts '30d_independent_payer_heterogeneity_audit.py'),
    '--phase2', $Phase2,
    '--matrix-root', $MatrixRoot,
    '--primary-scratch', $PrimaryScratch,
    '--payer-scratch', $PayerScratch,
    '--row-chunk', '333333'
)

"[$(Get-Date -Format o)] RUN_PAYER_HETEROGENEITY completed successfully." |
    Tee-Object -FilePath (Join-Path $Logs 'RUN_PAYER_HETEROGENEITY_COMPLETE.log')
