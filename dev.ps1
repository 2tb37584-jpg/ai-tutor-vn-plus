param(
    [Parameter(Position = 0)]
    [string]$Command,

    [Parameter(Position = 1)]
    [string]$Subcommand
)

function Show-Usage {
    Write-Host "Usage: .\dev.ps1 <command>"
    Write-Host ""
    Write-Host "Commands:"
    Write-Host "  status       Show repository and Docker status"
    Write-Host "  review       Run git diff and working-tree checks"
    Write-Host "  test eval    Run deterministic eval tests"
    Write-Host "  test full    Run the full backend test suite"
    Write-Host "  snapshot     Print a safe, concise project snapshot"
}

function Test-DockerComposeAvailable {
    if ($null -eq (Get-Command docker -ErrorAction SilentlyContinue)) {
        return $false
    }

    & docker compose version 2>$null | Out-Null
    return $LASTEXITCODE -eq 0
}

function Get-ActiveTask {
    $taskIndex = Join-Path $PSScriptRoot "TASK_INDEX.md"
    if (-not (Test-Path $taskIndex)) {
        return "unknown"
    }

    $activeTask = Select-String -Path $taskIndex -Pattern '^\|\s*([^|]+?)\s*\|.*?\|\s*ACTIVE\s*\|' |
        Select-Object -First 1

    if ($null -eq $activeTask) {
        return "none"
    }

    return $activeTask.Matches[0].Groups[1].Value.Trim()
}

function Get-GitSummary {
    $changes = @(& git status --short)
    if ($LASTEXITCODE -ne 0) {
        return "unknown"
    }

    if ($changes.Count -eq 0) {
        return "clean"
    }

    return "changed ($($changes.Count) file(s))"
}

function Get-DockerServiceStatus {
    if (-not (Test-DockerComposeAvailable)) {
        return @("unavailable")
    }

    $services = @(& docker compose ps --format '{{.Service}}: {{.State}}' 2>$null)
    if ($LASTEXITCODE -ne 0) {
        return @("unavailable")
    }

    if ($services.Count -eq 0) {
        return @("no services")
    }

    return $services
}

function Get-EvalCorpusCount {
    $casesPath = Join-Path $PSScriptRoot "evals\cases.jsonl"
    if (-not (Test-Path $casesPath)) {
        return "unknown"
    }

    return @(
        Get-Content $casesPath | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    ).Count
}

function Get-ApiMode {
    if (-not (Test-DockerComposeAvailable)) {
        return "unavailable"
    }

    $apiMode = @(
        & docker compose exec -T backend python -c "from app.core.config import Settings; s = Settings(); print(s.openai_api_mode)" 2>$null
    ) | Select-Object -Last 1

    if ($LASTEXITCODE -ne 0 -or $apiMode -notin @("responses", "chat_completions")) {
        return "unavailable"
    }

    return $apiMode
}

function Invoke-Status {
    Write-Host "===== STATUS ====="
    $head = (& git rev-parse --short HEAD 2>$null)
    if ($LASTEXITCODE -ne 0) {
        $head = "unknown"
    }
    Write-Host "HEAD: $head"
    Write-Host "ACTIVE: $(Get-ActiveTask)"
    Write-Host "GIT: $(Get-GitSummary)"
    Write-Host ""
    Write-Host "===== DOCKER ====="
    Get-DockerServiceStatus | ForEach-Object { Write-Host $_ }
}

function Invoke-Review {
    Write-Host "===== REVIEW ====="
    & git diff --check
    $unstagedDiffCheckExitCode = $LASTEXITCODE

    & git diff --cached --check
    $stagedDiffCheckExitCode = $LASTEXITCODE

    $unstagedDiffStat = @(& git diff --stat)
    if ($unstagedDiffStat.Count -gt 0) {
        Write-Host ""
        Write-Host "===== UNSTAGED DIFF STAT ====="
        $unstagedDiffStat | Write-Output
    }

    $stagedDiffStat = @(& git diff --cached --stat)
    if ($stagedDiffStat.Count -gt 0) {
        Write-Host ""
        Write-Host "===== STAGED DIFF STAT ====="
        $stagedDiffStat | Write-Output
    }

    Write-Host ""
    Write-Host "===== GIT STATUS ====="
    & git status --short

    if ($unstagedDiffCheckExitCode -ne 0 -or $stagedDiffCheckExitCode -ne 0) {
        $script:CommandExitCode = 1
    }
    else {
        $script:CommandExitCode = 0
    }
}

function Invoke-Tests {
    param([string]$Suite)

    if (-not (Test-DockerComposeAvailable)) {
        Write-Host "ERROR: Docker Compose is unavailable. Start Docker Desktop and try again."
        $script:CommandExitCode = 1
        return
    }

    if ($Suite -eq "eval") {
        & docker compose exec backend pytest -q tests/test_eval_runner.py
    }
    else {
        & docker compose exec backend pytest -q
    }

    $script:CommandExitCode = $LASTEXITCODE
}

function Invoke-Snapshot {
    Write-Host "===== SNAPSHOT ====="
    $head = (& git rev-parse --short HEAD 2>$null)
    if ($LASTEXITCODE -ne 0) {
        $head = "unknown"
    }
    Write-Host "HEAD: $head"
    Write-Host "ACTIVE: $(Get-ActiveTask)"
    Write-Host "GIT: $(Get-GitSummary)"
    Write-Host "DOCKER: $((Get-DockerServiceStatus) -join ', ')"
    Write-Host "EVAL_CORPUS: $(Get-EvalCorpusCount)"
    Write-Host "API_MODE: $(Get-ApiMode)"
}

switch ("$Command $Subcommand".Trim()) {
    "status" {
        Invoke-Status
        exit 0
    }
    "review" {
        Invoke-Review
        exit $script:CommandExitCode
    }
    "test eval" {
        Invoke-Tests "eval"
        exit $script:CommandExitCode
    }
    "test full" {
        Invoke-Tests "full"
        exit $script:CommandExitCode
    }
    "snapshot" {
        Invoke-Snapshot
        exit 0
    }
    default {
        Show-Usage
        exit 1
    }
}
