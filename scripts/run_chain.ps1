# Runs DEEPDIVE section 19 steps 6-8 (everything up to the human `label` step) unattended.
# Every step is resumable (--resume reads the database), so re-running this script after a reboot or a failure
# continues where it stopped. With --wait, eval/chaos/repeatability sleep until the daily quota reset (13:30 IST).
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\run_chain.ps1        (log: logs\chain.log)
$ErrorActionPreference = "Continue"   # PS 5.1 would turn uv's normal stderr output into terminating errors under "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$env:Path = "$env:LOCALAPPDATA\Microsoft\WinGet\Links;$env:Path"
$env:PYTHONIOENCODING = "utf-8"
New-Item -ItemType Directory -Force logs | Out-Null

# one chain at a time (scheduled task + a manual run would race on the same cases)
$mutex = New-Object System.Threading.Mutex($false, "Global\FlightRecorderChain")
if (-not $mutex.WaitOne(0)) { "another run_chain.ps1 is already running; exiting"; exit 0 }
$log = "logs\chain.log"

# keep the machine awake (not the display) while this process runs; released automatically when it exits
Add-Type -Namespace Win32 -Name Power -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint f);'
[Win32.Power]::SetThreadExecutionState(0x80000001) | Out-Null   # ES_CONTINUOUS | ES_SYSTEM_REQUIRED

function Step([string]$name, [string[]]$cmd) {
    # every step is resumable, so a failed step is retried (after 15 min) before the chain gives up
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        "`n===== $(Get-Date -Format 'yyyy-MM-dd HH:mm') START $name (attempt $attempt/3) : uv $($cmd -join ' ')" | Tee-Object -FilePath $log -Append
        & uv @cmd 2>&1 | ForEach-Object { "$_" } | Tee-Object -FilePath $log -Append
        if ($LASTEXITCODE -eq 0) {
            "===== $(Get-Date -Format 'yyyy-MM-dd HH:mm') DONE $name" | Tee-Object -FilePath $log -Append
            return
        }
        "===== $(Get-Date -Format 'yyyy-MM-dd HH:mm') FAILED $name (exit $LASTEXITCODE, attempt $attempt/3)" | Tee-Object -FilePath $log -Append
        if ($attempt -lt 3) { Start-Sleep -Seconds 900 }
    }
    "===== $(Get-Date -Format 'yyyy-MM-dd HH:mm') GAVE UP on $name; fix and re-run this script" | Tee-Object -FilePath $log -Append
    exit 1
}

Step "baseline-v1"        @("run", "flightrec", "eval", "--label", "baseline-v1", "--resume", "--wait")
Step "retrieval-hybrid"   @("run", "flightrec", "eval-retrieval", "--mode", "hybrid")
Step "retrieval-vector"   @("run", "flightrec", "eval-retrieval", "--mode", "vector")
Step "chaos-baseline-v1"  @("run", "flightrec", "chaos", "--label", "chaos-baseline-v1", "--faults", "all", "--resume", "--wait")
Step "hardened-v2"        @("run", "flightrec", "eval", "--label", "hardened-v2", "--prompt-version", "v2", "--resume", "--wait")
Step "chaos-hardened-v2"  @("run", "flightrec", "chaos", "--label", "chaos-hardened-v2", "--faults", "all", "--prompt-version", "v2", "--resume", "--wait")
Step "diff-clean"         @("run", "flightrec", "diff", "baseline-v1", "hardened-v2")
Step "diff-chaos"         @("run", "flightrec", "diff", "chaos-baseline-v1", "chaos-hardened-v2")
Step "repeatability"      @("run", "flightrec", "repeatability", "--wait")
Step "replay-check"       @("run", "flightrec", "replay-check", "--label", "baseline-v1")
Step "stats"              @("run", "flightrec", "stats")
Step "report"             @("run", "flightrec", "report")
"===== $(Get-Date -Format 'yyyy-MM-dd HH:mm') CHAIN COMPLETE. Next (human): uv run flightrec label" | Tee-Object -FilePath $log -Append
# the scheduled task (scripts/schedule_chain.ps1) is only needed until the chain completes
Unregister-ScheduledTask -TaskName "FlightRecorderChain" -Confirm:$false -ErrorAction SilentlyContinue
