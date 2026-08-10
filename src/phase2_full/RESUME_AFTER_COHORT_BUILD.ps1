# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/RESUME_AFTER_COHORT_BUILD.ps1
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
param(
    [Parameter(Mandatory)]
    [int]$BuilderPid,

    [Parameter(Mandatory)]
    [string]$Python
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$WorkspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$Phase2 = Join-Path $WorkspaceRoot 'outputs\florida_ed_concordance_analysis_20260726'
$Release = Join-Path $WorkspaceRoot 'outputs\florida_ed_full_build_20260724'
$Temp = Join-Path $WorkspaceRoot 'tmp\florida_ed_concordance_analysis_20260726'
$DataRoot = Join-Path $Phase2 'analysis_data\concordance_visit_data_provider_v2'
$LogRoot = Join-Path $Phase2 'qa\run_logs'
$StatePath = Join-Path $Phase2 'qa\background_orchestrator_state.json'
New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null

function Write-State {
    param(
        [Parameter(Mandatory)]
        [string]$Status,
        [Parameter()]
        [hashtable]$Additional = @{}
    )
    $payload = [ordered]@{
        updated_utc = (Get-Date).ToUniversalTime().ToString('o')
        status = $Status
        process_id = $PID
        builder_process_id = $BuilderPid
    }
    foreach ($key in $Additional.Keys) {
        $payload[$key] = $Additional[$key]
    }
    $temporary = "$StatePath.tmp"
    $payload | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $StatePath -Force
}

try {
    $builder = Get-Process -Id $BuilderPid -ErrorAction SilentlyContinue
    if ($null -ne $builder) {
        Write-State 'waiting_for_existing_cohort_builder'
        Wait-Process -Id $BuilderPid
    }

    $successCount = @(
        Get-ChildItem -LiteralPath $DataRoot -Recurse -Filter '_SUCCESS.json' -ErrorAction SilentlyContinue
    ).Count

    if ($successCount -ne 60) {
        throw "Provider-v2 cohort is incomplete: $successCount of 60 partitions pass."
    }
    Write-State 'running_storage_safe_postcohort_workflow' @{
        provider_v2_partitions = $successCount
        note = 'Phase 1 remains immutable; all estimation is gated and storage-safe.'
    }
    & (Join-Path $PSScriptRoot 'RUN_PHASE2_REMAINING_SAFE.ps1') `
        -WorkspaceRoot $WorkspaceRoot `
        -Python $Python `
        -StartAt gate `
        -Threads 12 `
        -MemoryLimit '24GB'
    if ($LASTEXITCODE -ne 0) {
        throw "RUN_PHASE2_REMAINING_SAFE failed with exit code $LASTEXITCODE"
    }
    Write-State 'postbuild_workflow_complete' @{
        provider_v2_partitions = $successCount
    }
}
catch {
    Write-State 'failed' @{
        error = $_.Exception.Message
        script_stack_trace = $_.ScriptStackTrace
    }
    throw
}
