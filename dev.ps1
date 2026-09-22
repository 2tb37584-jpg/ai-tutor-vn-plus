param(
    [Parameter(Position = 0)]
    [string]$Command,

    [Parameter(Position = 1)]
    [string]$Subcommand,

    [Parameter(Position = 2)]
    [string]$Argument
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
    Write-Host "  task status  Show task lifecycle consistency"
    Write-Host "  task start <task-id>"
    Write-Host "  task done <task-id>"
}

function Show-TaskUsage {
    Write-Host "Usage: .\dev.ps1 task <status|start|done> [task-id]"
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
        & docker compose exec backend pytest -q tests/test_eval_runner.py tests/test_verifier_benchmark.py
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

$LifecycleStatuses = @("BACKLOG", "READY", "ACTIVE", "BLOCKED", "REVIEW", "DONE")

function Get-NewlineStyle {
    param([string]$Text)

    if ($Text.Contains("`r`n")) {
        return "CRLF"
    }
    if ($Text.Contains("`n")) {
        return "LF"
    }
    return "none"
}

function Read-Utf8File {
    param([string]$Path)

    try {
        $bytes = [System.IO.File]::ReadAllBytes($Path)
        $hasBom = $bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF
        $encoding = [System.Text.UTF8Encoding]::new($hasBom, $true)
        $offset = if ($hasBom) { 3 } else { 0 }
        $text = $encoding.GetString($bytes, $offset, $bytes.Length - $offset)
        $newline = Get-NewlineStyle $text

        return [pscustomobject]@{
            Path = $Path
            Text = $text
            HasBom = $hasBom
            Newline = $newline
        }
    }
    catch {
        throw "Could not read valid UTF-8 file: $Path"
    }
}

function Write-Utf8File {
    param(
        [pscustomobject]$FileData,
        [string]$Text,
        [string]$Path
    )

    $encoding = [System.Text.UTF8Encoding]::new($FileData.HasBom)
    $payload = $encoding.GetBytes($Text)
    if ($FileData.HasBom) {
        $preamble = $encoding.GetPreamble()
        $bytes = [byte[]]::new($preamble.Length + $payload.Length)
        [System.Array]::Copy($preamble, 0, $bytes, 0, $preamble.Length)
        [System.Array]::Copy($payload, 0, $bytes, $preamble.Length, $payload.Length)
        [System.IO.File]::WriteAllBytes($Path, $bytes)
        return
    }

    [System.IO.File]::WriteAllBytes($Path, $payload)
}

function New-TextFileData {
    param(
        [pscustomobject]$Original,
        [string]$Text
    )

    return [pscustomobject]@{
        Path = $Original.Path
        Text = $Text
        HasBom = $Original.HasBom
        Newline = Get-NewlineStyle $Text
    }
}

function Parse-TaskIndex {
    param([pscustomobject]$FileData)

    $records = [System.Collections.Generic.List[object]]::new()
    $errors = [System.Collections.Generic.List[string]]::new()
    $lineMatches = [regex]::Matches($FileData.Text, '(?m)^(?<line>\|[^\r\n]*)(?=\r?$)')

    foreach ($lineMatch in $lineMatches) {
        $line = $lineMatch.Groups['line'].Value
        $coreLine = $line.TrimEnd()
        if (-not $coreLine.EndsWith('|') -or $coreLine.Length -lt 3) {
            continue
        }

        $cells = $coreLine.Substring(1, $coreLine.Length - 2).Split('|')
        if ($cells.Count -lt 1) {
            continue
        }

        $taskId = $cells[0].Trim()
        if ($taskId -notmatch '^M\d{2}-\d{2}[A-Z0-9-]*$') {
            continue
        }

        if ($cells.Count -ne 5) {
            $errors.Add("Malformed TASK_INDEX row for $taskId.")
            continue
        }

        $status = $cells[3].Trim()
        if ($LifecycleStatuses -notcontains $status) {
            $errors.Add("Malformed lifecycle status for $taskId.")
        }

        $records.Add([pscustomobject]@{
            Id = $taskId
            Status = $status
            Cells = $cells
            Line = $line
            CoreLine = $coreLine
            TrailingWhitespace = $line.Substring($coreLine.Length)
            Index = $lineMatch.Index
            Length = $lineMatch.Length
        })
    }

    return [pscustomobject]@{
        File = $FileData
        Records = @($records)
        Errors = @($errors)
    }
}

function Parse-TaskFile {
    param([pscustomobject]$FileData)

    $errors = [System.Collections.Generic.List[string]]::new()
    $allStatusMatches = [regex]::Matches(
        $FileData.Text,
        '(?m)^(?<prefix>Status:[ \t]*)(?<status>[^\r\n]*?)(?<suffix>[ \t]*)(?=\r?$)'
    )
    $firstSection = [regex]::Match($FileData.Text, '(?m)^##\s+')
    $metadataLimit = if ($firstSection.Success) { $firstSection.Index } else { 4096 }
    $statusMatches = @($allStatusMatches | Where-Object { $_.Index -lt $metadataLimit })

    if ($statusMatches.Count -ne 1) {
        $errors.Add("Expected exactly one top-level Status line.")
        return [pscustomobject]@{ File = $FileData; Errors = @($errors); Status = $null; Match = $null }
    }

    $statusMatch = $statusMatches[0]
    if ($statusMatch.Index -gt 4096) {
        $errors.Add("Status line must appear near the beginning of the task file.")
    }

    $status = $statusMatch.Groups['status'].Value.Trim()
    if ($LifecycleStatuses -notcontains $status) {
        $errors.Add("Malformed task-file lifecycle status.")
    }

    return [pscustomobject]@{
        File = $FileData
        Errors = @($errors)
        Status = $status
        Match = $statusMatch
    }
}

function Find-TaskFiles {
    param(
        [string]$Root,
        [string]$TaskId
    )

    $tasksRoot = Join-Path $Root 'tasks'
    if (-not (Test-Path -LiteralPath $tasksRoot)) {
        return @()
    }

    return @(
        Get-ChildItem -LiteralPath $tasksRoot -Recurse -File -Filter "$TaskId.md" |
            Where-Object { $_.Name -ceq "$TaskId.md" }
    )
}

function Get-TaskContext {
    param(
        [string]$Root,
        [string]$TaskId
    )

    try {
        $indexPath = Join-Path $Root 'TASK_INDEX.md'
        $index = Parse-TaskIndex (Read-Utf8File $indexPath)
        if ($index.Errors.Count -gt 0) {
            return [pscustomobject]@{ Ok = $false; Reason = $index.Errors -join ' '; Index = $index }
        }

        $records = @($index.Records | Where-Object { $_.Id -ceq $TaskId })
        if ($records.Count -eq 0) {
            return [pscustomobject]@{ Ok = $false; Reason = "Task $TaskId is not in TASK_INDEX.md."; Index = $index }
        }
        if ($records.Count -ne 1) {
            return [pscustomobject]@{ Ok = $false; Reason = "Task $TaskId has duplicate TASK_INDEX.md rows."; Index = $index }
        }

        $taskFiles = Find-TaskFiles $Root $TaskId
        if ($taskFiles.Count -eq 0) {
            return [pscustomobject]@{ Ok = $false; Reason = "Task file for $TaskId is missing."; Index = $index }
        }
        if ($taskFiles.Count -ne 1) {
            return [pscustomobject]@{ Ok = $false; Reason = "Task file for $TaskId is ambiguous."; Index = $index }
        }

        $taskFile = Parse-TaskFile (Read-Utf8File $taskFiles[0].FullName)
        if ($taskFile.Errors.Count -gt 0) {
            return [pscustomobject]@{ Ok = $false; Reason = $taskFile.Errors -join ' '; Index = $index; TaskFile = $taskFile }
        }
        if ($records[0].Status -cne $taskFile.Status) {
            return [pscustomobject]@{ Ok = $false; Reason = "TASK_INDEX.md and task-file statuses disagree."; Index = $index; TaskFile = $taskFile; Record = $records[0] }
        }

        return [pscustomobject]@{
            Ok = $true
            Index = $index
            Record = $records[0]
            TaskFile = $taskFile
        }
    }
    catch {
        return [pscustomobject]@{ Ok = $false; Reason = $_.Exception.Message }
    }
}

function Test-AcceptanceChecklist {
    param([pscustomobject]$TaskFile)

    $headingCount = 0
    $inChecklist = $false
    $checkboxMarks = [System.Collections.Generic.List[string]]::new()
    $fenceCharacter = $null
    $fenceLength = 0

    foreach ($line in [regex]::Split($TaskFile.File.Text, '\r\n|\n|\r')) {
        if ($null -ne $fenceCharacter) {
            $closingFencePattern = '^[ \t]*' + [regex]::Escape($fenceCharacter) + '{' + $fenceLength + ',}[ \t]*$'
            if ([regex]::IsMatch($line, $closingFencePattern)) {
                $fenceCharacter = $null
                $fenceLength = 0
            }
            continue
        }

        $openingFence = [regex]::Match($line, '^[ \t]*(?<fence>`{3,}|~{3,}).*$')
        if ($openingFence.Success) {
            $fenceCharacter = $openingFence.Groups['fence'].Value.Substring(0, 1)
            $fenceLength = $openingFence.Groups['fence'].Value.Length
            continue
        }

        if ([regex]::IsMatch($line, '^## Acceptance checklist[ \t]*$')) {
            $headingCount += 1
            $inChecklist = $true
            continue
        }

        if ($inChecklist -and [regex]::IsMatch($line, '^##\s+')) {
            $inChecklist = $false
            continue
        }

        if ($inChecklist) {
            $checkbox = [regex]::Match($line, '^\s*[-*]\s*\[(?<mark>[^\]])\]')
            if ($checkbox.Success) {
                $checkboxMarks.Add($checkbox.Groups['mark'].Value)
            }
        }
    }

    if ($headingCount -ne 1) {
        return [pscustomobject]@{ Ok = $false; Reason = "Expected exactly one ## Acceptance checklist section." }
    }

    if ($checkboxMarks.Count -eq 0) {
        return [pscustomobject]@{ Ok = $false; Reason = "Acceptance checklist has no checkbox items." }
    }

    foreach ($mark in $checkboxMarks) {
        if ($mark -cne 'x' -and $mark -cne 'X') {
            return [pscustomobject]@{ Ok = $false; Reason = "Acceptance checklist has unchecked items." }
        }
    }

    return [pscustomobject]@{ Ok = $true }
}

function Replace-TextRange {
    param(
        [string]$Text,
        [int]$Index,
        [int]$Length,
        [string]$Replacement
    )

    return $Text.Substring(0, $Index) + $Replacement + $Text.Substring($Index + $Length)
}

function Update-IndexStatus {
    param(
        [pscustomobject]$Index,
        [pscustomobject]$Record,
        [string]$NewStatus
    )

    $cells = [string[]]$Record.Cells.Clone()
    $statusCell = $cells[3]
    $leadingWhitespace = [regex]::Match($statusCell, '^\s*').Value
    $trailingWhitespace = [regex]::Match($statusCell, '\s*$').Value
    $cells[3] = $leadingWhitespace + $NewStatus + $trailingWhitespace
    $newLine = '|' + [string]::Join('|', $cells) + '|' + $Record.TrailingWhitespace

    return Replace-TextRange $Index.File.Text $Record.Index $Record.Length $newLine
}

function Update-TaskFileStatus {
    param(
        [pscustomobject]$TaskFile,
        [string]$NewStatus
    )

    $match = $TaskFile.Match
    $newLine = $match.Groups['prefix'].Value + $NewStatus + $match.Groups['suffix'].Value
    return Replace-TextRange $TaskFile.File.Text $match.Index $match.Length $newLine
}

function Test-PreparedTransition {
    param(
        [pscustomobject]$Context,
        [string]$IndexText,
        [string]$TaskText,
        [string]$NewStatus
    )

    $updatedIndex = Parse-TaskIndex (New-TextFileData $Context.Index.File $IndexText)
    $updatedRecords = @($updatedIndex.Records | Where-Object { $_.Id -ceq $Context.Record.Id })
    $updatedTaskFile = Parse-TaskFile (New-TextFileData $Context.TaskFile.File $TaskText)

    if ($updatedIndex.Errors.Count -gt 0 -or $updatedRecords.Count -ne 1 -or $updatedRecords[0].Status -cne $NewStatus) {
        return $false
    }
    if ($updatedTaskFile.Errors.Count -gt 0 -or $updatedTaskFile.Status -cne $NewStatus) {
        return $false
    }
    if ($Context.Index.File.Newline -ne (New-TextFileData $Context.Index.File $IndexText).Newline) {
        return $false
    }
    if ($Context.TaskFile.File.Newline -ne (New-TextFileData $Context.TaskFile.File $TaskText).Newline) {
        return $false
    }

    return $true
}

function Invoke-AtomicLifecycleUpdate {
    param(
        [pscustomobject]$Context,
        [string]$IndexText,
        [string]$TaskText
    )

    $indexTemp = "$($Context.Index.File.Path).m00-07.$([guid]::NewGuid().ToString('N')).tmp"
    $taskTemp = "$($Context.TaskFile.File.Path).m00-07.$([guid]::NewGuid().ToString('N')).tmp"
    $indexBackup = "$indexTemp.backup"
    $taskBackup = "$taskTemp.backup"
    $indexReplaced = $false

    try {
        Write-Utf8File $Context.Index.File $IndexText $indexTemp
        Write-Utf8File $Context.TaskFile.File $TaskText $taskTemp

        $preparedIndex = Read-Utf8File $indexTemp
        $preparedTask = Read-Utf8File $taskTemp
        if ($preparedIndex.Text -cne $IndexText -or $preparedTask.Text -cne $TaskText) {
            throw "Temporary lifecycle files could not be validated."
        }
        if ($preparedIndex.HasBom -ne $Context.Index.File.HasBom -or $preparedTask.HasBom -ne $Context.TaskFile.File.HasBom) {
            throw "Temporary lifecycle files changed UTF-8 BOM state."
        }
        if ($preparedIndex.Newline -ne $Context.Index.File.Newline -or $preparedTask.Newline -ne $Context.TaskFile.File.Newline) {
            throw "Temporary lifecycle files changed newline style."
        }

        [System.IO.File]::Replace($indexTemp, $Context.Index.File.Path, $indexBackup)
        $indexReplaced = $true
        [System.IO.File]::Replace($taskTemp, $Context.TaskFile.File.Path, $taskBackup)
    }
    catch {
        if ($indexReplaced) {
            try {
                if (Test-Path -LiteralPath $indexBackup) {
                    [System.IO.File]::Copy($indexBackup, $Context.Index.File.Path, $true)
                }
                else {
                    Write-Utf8File $Context.Index.File $Context.Index.File.Text $Context.Index.File.Path
                }
            }
            catch {
                throw "Lifecycle update failed and rollback could not restore TASK_INDEX.md."
            }
        }
        throw "Lifecycle update failed: $($_.Exception.Message)"
    }
    finally {
        foreach ($tempPath in @($indexTemp, $taskTemp, $indexBackup, $taskBackup)) {
            if (Test-Path -LiteralPath $tempPath) {
                Remove-Item -LiteralPath $tempPath -Force
            }
        }
    }
}

function Invoke-TaskStatus {
    param([string]$Root)

    Write-Host "===== TASK STATUS ====="
    try {
        $index = Parse-TaskIndex (Read-Utf8File (Join-Path $Root 'TASK_INDEX.md'))
        $activeRecords = @($index.Records | Where-Object { $_.Status -ceq 'ACTIVE' })
        $consistent = $index.Errors.Count -eq 0
        $activeLabel = 'none'
        $indexStatus = 'n/a'
        $fileStatus = 'n/a'
        $reason = if ($index.Errors.Count -gt 0) { $index.Errors -join ' ' } else { $null }

        if ($activeRecords.Count -gt 1) {
            $activeLabel = "multiple ($($activeRecords.Id -join ', '))"
            $consistent = $false
            $reason = if ($reason) { "$reason More than one ACTIVE task exists." } else { "More than one ACTIVE task exists." }
        }
        elseif ($activeRecords.Count -eq 1) {
            $activeLabel = $activeRecords[0].Id
            $indexStatus = $activeRecords[0].Status
            $context = Get-TaskContext $Root $activeRecords[0].Id
            if (-not $context.Ok) {
                $consistent = $false
                $reason = if ($reason) { "$reason $($context.Reason)" } else { $context.Reason }
            }
            else {
                $fileStatus = $context.TaskFile.Status
                if ($indexStatus -cne $fileStatus) {
                    $consistent = $false
                    $reason = if ($reason) { "$reason TASK_INDEX.md and task-file statuses disagree." } else { "TASK_INDEX.md and task-file statuses disagree." }
                }
            }
        }

        Write-Host "ACTIVE: $activeLabel"
        Write-Host "INDEX_STATUS: $indexStatus"
        Write-Host "FILE_STATUS: $fileStatus"
        Write-Host "CONSISTENT: $(if ($consistent) { 'yes' } else { 'no' })"
        if ($reason) {
            Write-Host "REASON: $reason"
        }
        $script:CommandExitCode = if ($consistent) { 0 } else { 1 }
    }
    catch {
        Write-Host "ERROR: $($_.Exception.Message)"
        $script:CommandExitCode = 1
    }
}

function Invoke-TaskTransition {
    param(
        [string]$Root,
        [string]$Operation,
        [string]$TaskId
    )

    if ([string]::IsNullOrWhiteSpace($TaskId)) {
        Show-TaskUsage
        $script:CommandExitCode = 1
        return
    }

    $context = Get-TaskContext $Root $TaskId
    if (-not $context.Ok) {
        Write-Host "ERROR: $($context.Reason)"
        $script:CommandExitCode = 1
        return
    }

    $activeRecords = @($context.Index.Records | Where-Object { $_.Status -ceq 'ACTIVE' })
    $newStatus = $null

    if ($Operation -ieq 'start') {
        if ($activeRecords.Count -ne 0) {
            Write-Host "ERROR: Another ACTIVE task exists."
            $script:CommandExitCode = 1
            return
        }
        if ($context.Record.Status -cne 'READY') {
            Write-Host "ERROR: Task $TaskId must be READY to start."
            $script:CommandExitCode = 1
            return
        }
        $newStatus = 'ACTIVE'
    }
    elseif ($Operation -ieq 'done') {
        if ($activeRecords.Count -ne 1 -or $activeRecords[0].Id -cne $TaskId) {
            Write-Host "ERROR: Task $TaskId must be the single ACTIVE task to complete."
            $script:CommandExitCode = 1
            return
        }
        if ($context.Record.Status -cne 'ACTIVE') {
            Write-Host "ERROR: Task $TaskId must be ACTIVE to complete."
            $script:CommandExitCode = 1
            return
        }
        $checklist = Test-AcceptanceChecklist $context.TaskFile
        if (-not $checklist.Ok) {
            Write-Host "ERROR: $($checklist.Reason)"
            $script:CommandExitCode = 1
            return
        }
        $newStatus = 'DONE'
    }
    else {
        Show-TaskUsage
        $script:CommandExitCode = 1
        return
    }

    $indexText = Update-IndexStatus $context.Index $context.Record $newStatus
    $taskText = Update-TaskFileStatus $context.TaskFile $newStatus
    if (-not (Test-PreparedTransition $context $indexText $taskText $newStatus)) {
        Write-Host "ERROR: Lifecycle update validation failed."
        $script:CommandExitCode = 1
        return
    }

    try {
        Invoke-AtomicLifecycleUpdate $context $indexText $taskText
        Write-Host "TASK: $TaskId $($context.Record.Status) -> $newStatus"
        $script:CommandExitCode = 0
    }
    catch {
        Write-Host "ERROR: $($_.Exception.Message)"
        $script:CommandExitCode = 1
    }
}

if ($MyInvocation.InvocationName -eq '.') {
    return
}

switch ($Command) {
    "status" {
        if ($Subcommand -or $Argument) {
            Show-Usage
            exit 1
        }
        Invoke-Status
        exit 0
    }
    "review" {
        if ($Subcommand -or $Argument) {
            Show-Usage
            exit 1
        }
        Invoke-Review
        exit $script:CommandExitCode
    }
    "test" {
        if ($Subcommand -notin @('eval', 'full') -or $Argument) {
            Show-Usage
            exit 1
        }
        Invoke-Tests $Subcommand
        exit $script:CommandExitCode
    }
    "snapshot" {
        if ($Subcommand -or $Argument) {
            Show-Usage
            exit 1
        }
        Invoke-Snapshot
        exit 0
    }
    "task" {
        if ($Subcommand -ceq 'status' -and -not $Argument) {
            Invoke-TaskStatus $PSScriptRoot
            exit $script:CommandExitCode
        }
        if ($Subcommand -in @('start', 'done') -and $Argument) {
            Invoke-TaskTransition $PSScriptRoot $Subcommand $Argument
            exit $script:CommandExitCode
        }
        Show-TaskUsage
        exit 1
    }
    default {
        Show-Usage
        exit 1
    }
}
