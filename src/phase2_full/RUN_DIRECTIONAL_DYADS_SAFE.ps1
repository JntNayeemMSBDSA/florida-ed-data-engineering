# Sanitized portfolio copy of a production workflow source file.
# Original: outputs/florida_ed_concordance_analysis_20260726/scripts/RUN_DIRECTIONAL_DYADS_SAFE.ps1
# No source data, model matrices, checkpoints, coefficients, or analytical result files are included.
param(
    [Parameter()]
    [string]$WorkspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path,

    [Parameter()]
    [string]$Python = '',

    [Parameter()]
    [ValidateSet('primary', 'all')]
    [string]$Scope = 'primary',

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
$MatrixRoot = Join-Path $Phase2 'analysis_data\directional_model_matrices'
$ScratchRoot = Join-Path $Temp 'directional_model_scratch'
$ResultsRoot = Join-Path $Phase2 'results\directional_dyads\models'

New-Item -ItemType Directory -Force -Path `
    $Logs, $MatrixRoot, $ScratchRoot, $ResultsRoot | Out-Null

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

$PrimaryOutcomes = @(
    'los_hours_primary_0_168',
    'total_charge_reported_real_2024'
)
$AllOutcomes = @(
    'los_hours_primary_0_168',
    'total_charge_reported_real_2024',
    'procedure_count_analysis',
    'any_procedure_flag',
    'high_procedure_flag',
    'em_acuity_proxy_level',
    'em_critical_care_flag',
    'routine_discharge_flag',
    'transfer_flag',
    'hospice_flag',
    'mortality_flag',
    'left_discontinued_care_flag',
    'aneschgs_real_2024',
    'cardiochgs_real_2024',
    'erchgs_real_2024',
    'gastrochgs_real_2024',
    'labchgs_real_2024',
    'lithochgs_real_2024',
    'medchgs_real_2024',
    'obserchgs_real_2024',
    'oprmchgs_real_2024',
    'othchgs_real_2024',
    'pharmchgs_real_2024',
    'radchgs_real_2024',
    'recovchgs_real_2024',
    'traumachgs_real_2024',
    'higher_discretion_procedure_count',
    'lower_discretion_procedure_count',
    'ambiguous_discretion_procedure_count',
    'any_higher_discretion_candidate_flag',
    'any_lower_discretion_candidate_flag',
    'higher_minus_lower_discretion_procedure_count',
    'any_higher_minus_any_lower_discretion_candidate'
)
$Outcomes = if ($Scope -eq 'primary') { $PrimaryOutcomes } else { $AllOutcomes }
$Families = @('gender_dyads', 'race_dyads', 'intersectional_dyads')

function Invoke-PythonStep {
    param(
        [Parameter(Mandatory)]
        [string]$Name,
        [Parameter(Mandatory)]
        [string[]]$Arguments
    )
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

function Test-Completed {
    param(
        [Parameter(Mandatory)]
        [string]$Family,
        [Parameter(Mandatory)]
        [string]$Outcome
    )
    $audit = Join-Path $Phase2 "qa\directional_result_audits\${Family}__${Outcome}.json"
    $compaction = Join-Path $Phase2 "qa\directional_compaction\${Family}__${Outcome}.json"
    if (
        (Test-Path -LiteralPath $audit -PathType Leaf) -and
        (Test-Path -LiteralPath $compaction -PathType Leaf)
    ) {
        $auditPayload = Get-Content -LiteralPath $audit -Raw | ConvertFrom-Json
        $compactPayload = Get-Content -LiteralPath $compaction -Raw | ConvertFrom-Json
        $measurementAuditRequired = (
            $Family -in @('race_dyads', 'intersectional_dyads') -and
            $Outcome -in $PrimaryOutcomes
        )
        $measurementAuditPassed = $true
        if ($measurementAuditRequired) {
            $measurementAudit = Join-Path $Phase2 (
                "qa\directional_measurement_sensitivity_audits\" +
                "${Family}__${Outcome}.json"
            )
            if (-not (Test-Path -LiteralPath $measurementAudit -PathType Leaf)) {
                $measurementAuditPassed = $false
            }
            else {
                $measurementPayload = Get-Content -LiteralPath `
                    $measurementAudit -Raw | ConvertFrom-Json
                $measurementAuditPassed = $measurementPayload.status -eq 'PASS'
            }
        }
        return (
            $auditPayload.status -eq 'PASS' -and
            $compactPayload.status -eq 'EXECUTED' -and
            $measurementAuditPassed
        )
    }
    return $false
}

Invoke-PythonStep '42b_directional_inference_engine_tests' @(
    (Join-Path $Scripts '42b_directional_inference_engine_tests.py'),
    '--phase2', $Phase2
)
Invoke-PythonStep '46b_directional_measurement_sensitivity_tests' @(
    (Join-Path $Scripts '46b_directional_measurement_sensitivity_tests.py'),
    '--phase2', $Phase2
)

foreach ($Family in $Families) {
    foreach ($Outcome in $Outcomes) {
        if (Test-Completed -Family $Family -Outcome $Outcome) {
            "[$(Get-Date -Format o)] SKIP completed $Family / $Outcome"
            continue
        }
        $stem = "${Family}__${Outcome}"
        Invoke-PythonStep "39_build_${stem}" @(
            (Join-Path $Scripts '39_build_directional_outcome_matrix.py'),
            '--phase2', $Phase2,
            '--matrix-root', $MatrixRoot,
            '--family', $Family,
            '--outcome', $Outcome,
            '--threads', [string]$Threads,
            '--memory-limit', $MemoryLimit
        )
        Invoke-PythonStep "40_matrix_audit_${stem}" @(
            (Join-Path $Scripts '40_independent_directional_matrix_audit.py'),
            '--phase2', $Phase2,
            '--matrix-root', $MatrixRoot,
            '--scratch-root', $ScratchRoot,
            '--family', $Family,
            '--outcome', $Outcome,
            '--threads', [string]$Threads,
            '--memory-limit', $MemoryLimit,
            '--row-chunk', '100000',
            '--block-columns', '4',
            '--tolerance', '1e-8'
        )
        Invoke-PythonStep "41_estimate_${stem}" @(
            (Join-Path $Scripts '41_estimate_directional_models.py'),
            '--phase2', $Phase2,
            '--matrix-root', $MatrixRoot,
            '--scratch-root', $ScratchRoot,
            '--output-root', $ResultsRoot,
            '--family', $Family,
            '--outcome', $Outcome,
            '--row-chunk', '100000',
            '--bootstrap-draws', '9999',
            '--seed', '20260726'
        )
        Invoke-PythonStep "42_result_audit_${stem}" @(
            (Join-Path $Scripts '42_independent_directional_result_audit.py'),
            '--phase2', $Phase2,
            '--matrix-root', $MatrixRoot,
            '--scratch-root', $ScratchRoot,
            '--results-root', $ResultsRoot,
            '--family', $Family,
            '--outcome', $Outcome,
            '--row-chunk', '137777'
        )
        if (
            $Family -in @('race_dyads', 'intersectional_dyads') -and
            $Outcome -in $PrimaryOutcomes
        ) {
            Invoke-PythonStep "47_measurement_sensitivity_${stem}" @(
                (
                    Join-Path $Scripts `
                        '47_estimate_directional_measurement_sensitivities.py'
                ),
                '--phase2', $Phase2,
                '--matrix-root', $MatrixRoot,
                '--scratch-root', $ScratchRoot,
                '--results-root', $ResultsRoot,
                '--family', $Family,
                '--outcome', $Outcome,
                '--imputations', '20',
                '--seed', '20260726',
                '--row-chunk', '100000',
                '--block-columns', '4',
                '--tolerance', '1e-8'
            )
            Invoke-PythonStep "48_measurement_sensitivity_audit_${stem}" @(
                (
                    Join-Path $Scripts `
                        '48_independent_directional_measurement_sensitivity_audit.py'
                ),
                '--phase2', $Phase2,
                '--matrix-root', $MatrixRoot,
                '--results-root', $ResultsRoot,
                '--family', $Family,
                '--outcome', $Outcome,
                '--row-chunk', '137777'
            )
        }
        Invoke-PythonStep "44_compact_${stem}" @(
            (Join-Path $Scripts '44_compact_directional_intermediates.py'),
            '--phase2', $Phase2,
            '--matrix-root', $MatrixRoot,
            '--scratch-root', $ScratchRoot,
            '--family', $Family,
            '--outcome', $Outcome,
            '--execute'
        )
    }
}

$measurementAuditFolder = Join-Path `
    $Phase2 'qa\directional_measurement_sensitivity_audits'
$measurementAudits = @(
    'race_dyads__los_hours_primary_0_168.json',
    'race_dyads__total_charge_reported_real_2024.json',
    'intersectional_dyads__los_hours_primary_0_168.json',
    'intersectional_dyads__total_charge_reported_real_2024.json'
)
$allMeasurementAuditsPresent = $true
foreach ($auditName in $measurementAudits) {
    if (
        -not (
            Test-Path -LiteralPath (
                Join-Path $measurementAuditFolder $auditName
            ) -PathType Leaf
        )
    ) {
        $allMeasurementAuditsPresent = $false
    }
}
if ($allMeasurementAuditsPresent) {
    Invoke-PythonStep '48b_aggregate_measurement_sensitivity_audits' @(
        (
            Join-Path $Scripts `
                '48b_aggregate_directional_measurement_sensitivity_audits.py'
        ),
        '--phase2', $Phase2,
        '--results-root', $ResultsRoot
    )
}

if ($Scope -eq 'all') {
    Invoke-PythonStep '43_apply_directional_multiplicity' @(
        (Join-Path $Scripts '43_apply_directional_multiplicity.py'),
        '--phase2', $Phase2,
        '--results-root', $ResultsRoot
    )
    Invoke-PythonStep '43b_independent_directional_family_audit' @(
        (Join-Path $Scripts '43b_independent_directional_family_audit.py'),
        '--phase2', $Phase2
    )
}

"[$(Get-Date -Format o)] RUN_DIRECTIONAL_DYADS_SAFE scope=$Scope completed." |
    Tee-Object -FilePath (
        Join-Path $Logs "RUN_DIRECTIONAL_DYADS_SAFE_${Scope}_COMPLETE.log"
    )
