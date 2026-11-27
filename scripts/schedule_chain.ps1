# Registers scripts\run_chain.ps1 as a per-user scheduled task so it runs independently of VS Code / any terminal,
# starts now, and starts again at every logon (the chain resumes from the database, so a restart only continues).
# run_chain.ps1 unregisters the task when the chain completes. No admin rights needed.
# Remove manually:  Unregister-ScheduledTask -TaskName FlightRecorderChain -Confirm:$false
$root = Split-Path $PSScriptRoot -Parent
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Minimized -File `"$root\scripts\run_chain.ps1`"" `
    -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5) `
    -MultipleInstances IgnoreNew -StartWhenAvailable
Register-ScheduledTask -TaskName "FlightRecorderChain" -Action $action -Trigger $trigger -Settings $settings `
    -Description "Flight Recorder eval/chaos/repro chain (resumable)" -Force | Out-Null
Start-ScheduledTask -TaskName "FlightRecorderChain"
Get-ScheduledTask -TaskName "FlightRecorderChain" | Select-Object TaskName, State
