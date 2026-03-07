<#
.SYNOPSIS
    Bob Agent Daemon Manager - OpenClaw-style always-on deployment for Windows.

.DESCRIPTION
    Manages Bob as an always-on background service on Windows.
    Supports: install (Task Scheduler auto-start), start, stop, restart, status, logs, uninstall.

    Like OpenClaw's systemd/launchd daemon, Bob will:
    - Auto-start on Windows boot
    - Auto-restart on crash (up to 3 retries, then cooldown)
    - Run Telegram polling + FastAPI + heartbeat + cron
    - Log to rotating log files

.PARAMETER Action
    One of: install, uninstall, start, stop, restart, status, logs

.EXAMPLE
    .\bob_daemon.ps1 install    # Register as startup task + start
    .\bob_daemon.ps1 start      # Start Bob in background
    .\bob_daemon.ps1 stop       # Stop Bob gracefully
    .\bob_daemon.ps1 restart    # Stop + Start
    .\bob_daemon.ps1 status     # Check if running
    .\bob_daemon.ps1 logs       # Tail the log file
    .\bob_daemon.ps1 uninstall  # Remove startup task
#>

param(
    [Parameter(Position=0)]
    [ValidateSet("install", "uninstall", "start", "stop", "restart", "status", "logs")]
    [string]$Action = "status"
)

# ============================================================================
# CONFIGURATION
# ============================================================================

$TASK_NAME = "BobAgent"
$BOB_DIR = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$MIND_CLONE_DIR = Join-Path $BOB_DIR "mind-clone"
$LOG_DIR = Join-Path $env:USERPROFILE ".mind-clone" "logs"
$LOG_FILE = Join-Path $LOG_DIR "bob-agent.log"
$PID_FILE = Join-Path $env:USERPROFILE ".mind-clone" "bob-agent.pid"
$PYTHON = "python"

# Ensure log directory exists
if (-not (Test-Path $LOG_DIR)) {
    New-Item -ItemType Directory -Path $LOG_DIR -Force | Out-Null
}

# ============================================================================
# HELPERS
# ============================================================================

function Get-BobProcess {
    <# Find running Bob process by PID file or command line #>
    if (Test-Path $PID_FILE) {
        $pid = Get-Content $PID_FILE -ErrorAction SilentlyContinue
        if ($pid) {
            $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
            if ($proc -and $proc.ProcessName -eq "python") {
                return $proc
            }
        }
    }
    # Fallback: find by command line
    Get-Process python -ErrorAction SilentlyContinue | Where-Object {
        try {
            $cmdline = (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)").CommandLine
            $cmdline -match "mind_clone" -and ($cmdline -match "--web" -or $cmdline -match "--telegram-poll")
        } catch { $false }
    } | Select-Object -First 1
}

function Write-BobLog {
    param([string]$Message)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $entry = "[$ts] $Message"
    Add-Content -Path $LOG_FILE -Value $entry
    Write-Host $entry
}

function Rotate-Logs {
    <# Keep last 5 log files, each max 10MB #>
    if (Test-Path $LOG_FILE) {
        $size = (Get-Item $LOG_FILE).Length
        if ($size -gt 10MB) {
            for ($i = 4; $i -ge 1; $i--) {
                $old = "$LOG_FILE.$i"
                $new = "$LOG_FILE.$($i+1)"
                if (Test-Path $old) { Move-Item $old $new -Force }
            }
            Move-Item $LOG_FILE "$LOG_FILE.1" -Force
        }
    }
}

# ============================================================================
# ACTIONS
# ============================================================================

function Start-Bob {
    $existing = Get-BobProcess
    if ($existing) {
        Write-Host "[WARN] Bob is already running (PID: $($existing.Id))" -ForegroundColor Yellow
        return
    }

    Rotate-Logs
    Write-BobLog "Starting Bob Agent..."

    # Start Bob with both web server AND Telegram polling via --web mode
    # The web server's lifespan handler starts Telegram webhook/polling, heartbeat, cron
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $PYTHON
    $startInfo.Arguments = "-m mind_clone --web --host 127.0.0.1 --port 8000"
    $startInfo.WorkingDirectory = $MIND_CLONE_DIR
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.CreateNoWindow = $true

    $process = [System.Diagnostics.Process]::Start($startInfo)

    # Save PID
    $process.Id | Out-File -FilePath $PID_FILE -Force

    Write-BobLog "Bob Agent started (PID: $($process.Id))"
    Write-Host "[OK] Bob is running (PID: $($process.Id))" -ForegroundColor Green
    Write-Host "[OK] API: http://127.0.0.1:8000" -ForegroundColor Green
    Write-Host "[OK] Health: http://127.0.0.1:8000/health" -ForegroundColor Green
    Write-Host "[OK] Telegram: polling active (if token configured)" -ForegroundColor Green
    Write-Host "[OK] Logs: $LOG_FILE" -ForegroundColor Green
}

function Stop-Bob {
    $proc = Get-BobProcess
    if (-not $proc) {
        Write-Host "[INFO] Bob is not running" -ForegroundColor Yellow
        return
    }

    Write-BobLog "Stopping Bob Agent (PID: $($proc.Id))..."
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2

    # Verify stopped
    $check = Get-Process -Id $proc.Id -ErrorAction SilentlyContinue
    if ($check) {
        Write-Host "[WARN] Force-killing Bob..." -ForegroundColor Yellow
        Stop-Process -Id $proc.Id -Force
    }

    if (Test-Path $PID_FILE) { Remove-Item $PID_FILE -Force }
    Write-BobLog "Bob Agent stopped"
    Write-Host "[OK] Bob stopped" -ForegroundColor Green
}

function Get-BobStatus {
    $proc = Get-BobProcess
    if ($proc) {
        $uptime = (Get-Date) - $proc.StartTime
        $uptimeStr = "{0}d {1}h {2}m" -f $uptime.Days, $uptime.Hours, $uptime.Minutes
        Write-Host "==========================================" -ForegroundColor Cyan
        Write-Host "  BOB AGENT STATUS" -ForegroundColor Cyan
        Write-Host "==========================================" -ForegroundColor Cyan
        Write-Host "  State:    RUNNING" -ForegroundColor Green
        Write-Host "  PID:      $($proc.Id)"
        Write-Host "  Uptime:   $uptimeStr"
        Write-Host "  Memory:   $([math]::Round($proc.WorkingSet64 / 1MB, 1)) MB"
        Write-Host "  API:      http://127.0.0.1:8000"
        Write-Host "  Logs:     $LOG_FILE"
        Write-Host "==========================================" -ForegroundColor Cyan

        # Try health check
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" -TimeoutSec 3
            Write-Host "  Health:   OK" -ForegroundColor Green
        } catch {
            Write-Host "  Health:   UNREACHABLE (starting up?)" -ForegroundColor Yellow
        }
    } else {
        Write-Host "==========================================" -ForegroundColor Red
        Write-Host "  BOB AGENT STATUS" -ForegroundColor Red
        Write-Host "==========================================" -ForegroundColor Red
        Write-Host "  State:    STOPPED" -ForegroundColor Red
        Write-Host "  Run:      .\bob_daemon.ps1 start" -ForegroundColor Yellow
        Write-Host "==========================================" -ForegroundColor Red
    }
}

function Install-BobDaemon {
    <# Register Bob as a Windows Task Scheduler task that:
       - Starts on user logon
       - Restarts on failure (via wrapper)
       - Runs hidden in background
    #>

    Write-Host "Installing Bob Agent daemon..." -ForegroundColor Cyan

    # Create a wrapper script that auto-restarts on crash
    $wrapperPath = Join-Path $env:USERPROFILE ".mind-clone" "bob-watchdog.ps1"
    $wrapperContent = @"
# Bob Agent Watchdog - Auto-restarts on crash
`$LOG = Join-Path `$env:USERPROFILE ".mind-clone" "logs" "bob-agent.log"
`$MIND_CLONE_DIR = "$MIND_CLONE_DIR"
`$MAX_RESTARTS = 3
`$COOLDOWN_SECONDS = 300  # 5 min cooldown after max restarts
`$restartCount = 0

while (`$true) {
    `$ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path `$LOG -Value "[`$ts] Watchdog: Starting Bob Agent (attempt `$(`$restartCount + 1))..."

    `$proc = Start-Process -FilePath "python" -ArgumentList "-m mind_clone --web --host 127.0.0.1 --port 8000" ``
        -WorkingDirectory `$MIND_CLONE_DIR -NoNewWindow -PassThru -RedirectStandardOutput "`$LOG.stdout" -RedirectStandardError "`$LOG.stderr"

    `$proc.Id | Out-File -FilePath (Join-Path `$env:USERPROFILE ".mind-clone" "bob-agent.pid") -Force
    `$proc.WaitForExit()

    `$exitCode = `$proc.ExitCode
    `$ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path `$LOG -Value "[`$ts] Watchdog: Bob exited with code `$exitCode"

    `$restartCount++
    if (`$restartCount -ge `$MAX_RESTARTS) {
        Add-Content -Path `$LOG -Value "[`$ts] Watchdog: Max restarts reached. Cooling down `$COOLDOWN_SECONDS seconds..."
        Start-Sleep -Seconds `$COOLDOWN_SECONDS
        `$restartCount = 0
    } else {
        Start-Sleep -Seconds 5
    }
}
"@
    $wrapperContent | Out-File -FilePath $wrapperPath -Encoding utf8 -Force

    # Remove old task if exists
    Unregister-ScheduledTask -TaskName $TASK_NAME -Confirm:$false -ErrorAction SilentlyContinue

    # Create scheduled task
    $action = New-ScheduledTaskAction `
        -Execute "powershell.exe" `
        -Argument "-WindowStyle Hidden -ExecutionPolicy Bypass -File `"$wrapperPath`"" `
        -WorkingDirectory $MIND_CLONE_DIR

    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit (New-TimeSpan -Days 365)

    Register-ScheduledTask `
        -TaskName $TASK_NAME `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Description "Bob Agent - Always-on AI assistant (OpenClaw-style daemon)" `
        -RunLevel Limited `
        -ErrorAction Stop

    Write-Host "[OK] Bob daemon installed as scheduled task '$TASK_NAME'" -ForegroundColor Green
    Write-Host "[OK] Will auto-start on logon and auto-restart on crash" -ForegroundColor Green
    Write-Host "[OK] Watchdog script: $wrapperPath" -ForegroundColor Green

    # Start immediately
    Start-Bob
}

function Uninstall-BobDaemon {
    Stop-Bob
    Unregister-ScheduledTask -TaskName $TASK_NAME -Confirm:$false -ErrorAction SilentlyContinue
    $wrapperPath = Join-Path $env:USERPROFILE ".mind-clone" "bob-watchdog.ps1"
    if (Test-Path $wrapperPath) { Remove-Item $wrapperPath -Force }
    Write-Host "[OK] Bob daemon uninstalled" -ForegroundColor Green
}

function Show-BobLogs {
    if (Test-Path $LOG_FILE) {
        Write-Host "=== Bob Agent Logs (last 50 lines) ===" -ForegroundColor Cyan
        Get-Content $LOG_FILE -Tail 50
        Write-Host ""
        Write-Host "Live tail: Get-Content '$LOG_FILE' -Wait -Tail 20" -ForegroundColor Yellow
    } else {
        Write-Host "[INFO] No log file found at $LOG_FILE" -ForegroundColor Yellow
    }
}

# ============================================================================
# DISPATCH
# ============================================================================

switch ($Action) {
    "install"   { Install-BobDaemon }
    "uninstall" { Uninstall-BobDaemon }
    "start"     { Start-Bob }
    "stop"      { Stop-Bob }
    "restart"   { Stop-Bob; Start-Sleep -Seconds 2; Start-Bob }
    "status"    { Get-BobStatus }
    "logs"      { Show-BobLogs }
}
