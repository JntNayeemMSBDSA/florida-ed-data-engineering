# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/RUN_POST_CANONICAL_ANALYSIS_SAFE.ps1
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
param(
    [Parameter()]
    [string]$WorkspaceRoot = (
        Resolve-Path (Join-Path $PSScriptRoot '..\..\..')
    ).Path,

    [Parameter()]
    [string]$Python = '',

    [Parameter(Mandatory)]
    [int]$CanonicalParentProcessId,

    [Parameter()]
    [int]$Threads = 12,

    [Parameter()]
    [string]$MemoryLimit = '24GB'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Phase2 = Join-Path $WorkspaceRoot `
    'outputs\florida_ed_concordance_analysis_20260726'
$Temp = Join-Path $WorkspaceRoot `
    'tmp\florida_ed_concordance_analysis_20260726'
$Scripts = Join-Path $Phase2 'scripts'
$Logs = Join-Path $Phase2 'qa\run_logs'
$SupervisorLogs = Join-Path $Logs 'post_canonical_supervisor'
$CanonicalMarker = Join-Path $Logs `
    'RUN_PHASE2_REMAINING_SAFE_COMPLETE.log'
$DirectionalMarker = Join-Path $Logs `
    'RUN_DIRECTIONAL_DYADS_SAFE_all_COMPLETE.log'
$SupervisorStart = Get-Date

New-Item -ItemType Directory -Force -Path $SupervisorLogs | Out-Null

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
$env:OMP_NUM_THREADS = [string][Math]::Max(
    1, [Math]::Min($Threads, 16)
)

function Write-SupervisorEvent {
    param(
        [Parameter(Mandatory)]
        [string]$Message
    )
    $line = "[$(Get-Date -Format o)] $Message"
    $line | Tee-Object -FilePath (
        Join-Path $SupervisorLogs 'SUPERVISOR.log'
    ) -Append
}

function Invoke-PythonStep {
    param(
        [Parameter(Mandatory)]
        [string]$Name,
        [Parameter(Mandatory)]
        [string[]]$Arguments
    )
    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $log = Join-Path $SupervisorLogs "${stamp}_${Name}.log"
    "[$(Get-Date -Format o)] START $Name" |
        Tee-Object -FilePath $log
    $previousErrorAction = $ErrorActionPreference
    $exitCode = -1
    try {
        $ErrorActionPreference = 'Continue'
        & $Python @Arguments 2>&1 |
            Tee-Object -FilePath $log -Append
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorAction
    }
    if ($exitCode -ne 0) {
        throw "Step '$Name' failed. See $log"
    }
    "[$(Get-Date -Format o)] PASS $Name" |
        Tee-Object -FilePath $log -Append
}

function Require-PassingJson {
    param(
        [Parameter(Mandatory)]
        [string]$Path
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Required JSON is missing: $Path"
    }
    $payload = Get-Content -LiteralPath $Path -Raw |
        ConvertFrom-Json
    if ($payload.status -ne 'PASS') {
        throw "Required JSON does not pass: $Path"
    }
}

try {
    Write-SupervisorEvent (
        "WAIT canonical PID=$CanonicalParentProcessId; no downstream " +
        "estimator will start before it exits and its completion marker passes."
    )
    while (
        $null -ne (
            Get-Process -Id $CanonicalParentProcessId `
                -ErrorAction SilentlyContinue
        )
    ) {
        Start-Sleep -Seconds 30
    }
    Write-SupervisorEvent (
        "CANONICAL_PROCESS_EXITED PID=$CanonicalParentProcessId"
    )
    if (
        -not (
            Test-Path -LiteralPath $CanonicalMarker -PathType Leaf
        )
    ) {
        throw (
            'Canonical parent exited without its successful completion ' +
            "marker: $CanonicalMarker"
        )
    }
    $canonicalMarkerItem = Get-Item -LiteralPath $CanonicalMarker
    if ($canonicalMarkerItem.LastWriteTime -lt $SupervisorStart) {
        throw (
            'Canonical completion marker predates this recovery and cannot ' +
            'authorize downstream work.'
        )
    }
    $canonicalText = Get-Content -LiteralPath $CanonicalMarker -Raw
    if ($canonicalText -notmatch 'completed successfully') {
        throw 'Canonical completion marker content is invalid.'
    }
    Write-SupervisorEvent 'PASS canonical completion gate'

    Invoke-PythonStep '10_corrected_primary_ami' @(
        (Join-Path $Scripts '10_ami_validation_and_analysis.py'),
        '--phase2', $Phase2,
        '--temp', (Join-Path $Temp 'ami'),
        '--threads', [string]$Threads,
        '--memory-limit', $MemoryLimit
    )
    Invoke-PythonStep '16_multiplicity_after_corrected_ami' @(
        (Join-Path $Scripts '16_apply_multiple_testing.py'),
        '--phase2', $Phase2
    )
    Invoke-PythonStep '45_independent_primary_ami_audit' @(
        (
            Join-Path $Scripts `
                '45_independent_primary_ami_results_audit.py'
        ),
        '--phase2', $Phase2
    )
    Require-PassingJson (
        Join-Path $Phase2 `
            'qa\independent_primary_ami_results_audit.json'
    )
    Write-SupervisorEvent 'PASS corrected primary AMI gate'

    $directionalScript = Join-Path $Scripts `
        'RUN_DIRECTIONAL_DYADS_SAFE.ps1'
    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $directionalLog = Join-Path $SupervisorLogs `
        "${stamp}_RUN_DIRECTIONAL_DYADS_SAFE_all.log"
    "[$(Get-Date -Format o)] START directional scope=all" |
        Tee-Object -FilePath $directionalLog
    $previousErrorAction = $ErrorActionPreference
    $directionalExit = -1
    try {
        $ErrorActionPreference = 'Continue'
        & powershell.exe -NoProfile -ExecutionPolicy Bypass `
            -File $directionalScript `
            -WorkspaceRoot $WorkspaceRoot `
            -Python $Python `
            -Scope all `
            -Threads $Threads `
            -MemoryLimit $MemoryLimit 2>&1 |
            Tee-Object -FilePath $directionalLog -Append
        $directionalExit = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorAction
    }
    if ($directionalExit -ne 0) {
        throw "Directional runner failed. See $directionalLog"
    }
    if (-not (Test-Path -LiteralPath $DirectionalMarker -PathType Leaf)) {
        throw 'Directional runner exited without its completion marker.'
    }
    Require-PassingJson (
        Join-Path $Phase2 `
            'qa\independent_directional_family_aggregate_audit.json'
    )
    Require-PassingJson (
        Join-Path $Phase2 `
            'qa\independent_directional_measurement_sensitivity_audit.json'
    )
    Write-SupervisorEvent 'PASS complete directional result gates'

    Invoke-PythonStep '36_refresh_report_framework' @(
        (
            Join-Path $Scripts `
                '36_initialize_report_production_framework.py'
        ),
        '--phase2', $Phase2
    )

    $completeMarker = Join-Path $SupervisorLogs `
        'POST_CANONICAL_ANALYSIS_COMPLETE_PENDING_FINAL_RELEASE_AUDIT.log'
    (
        "[$(Get-Date -Format o)] PASS corrected primary AMI and complete " +
        "directional analysis/audits. Final independent analysis-release " +
        "audit, report finalization, rendering, visual QA, and PDF hashing " +
        "remain intentionally gated."
    ) | Tee-Object -FilePath $completeMarker
}
catch {
    $message = $_.Exception.Message
    Write-SupervisorEvent "FAIL_CLOSED $message"
    $failedMarker = Join-Path $SupervisorLogs `
        'POST_CANONICAL_ANALYSIS_FAILED_CLOSED.log'
    "[$(Get-Date -Format o)] $message" |
        Tee-Object -FilePath $failedMarker
    throw
}
