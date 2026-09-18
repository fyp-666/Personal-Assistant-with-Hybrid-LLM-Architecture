$ErrorActionPreference = "Stop"

# An offset-free Windows trigger follows this zone's daylight-saving changes.
if ((Get-TimeZone).Id -ne "Pacific Standard Time") {
    throw "This installer expects Windows time zone Pacific Standard Time."
}
$projectDirectory = Split-Path -Parent $PSScriptRoot
$wslProject = [string](& wsl.exe -d Ubuntu -u fyp --exec /usr/bin/wslpath -a $projectDirectory)
if ($LASTEXITCODE -ne 0 -or -not $wslProject.StartsWith("/")) {
    throw "Could not resolve the project directory in WSL."
}
& wsl.exe -d Ubuntu -u fyp --cd $wslProject -- .venv/bin/python scripts/install_daily_briefing.py
if ($LASTEXITCODE -ne 0) {
    throw "Hermes job installation failed."
}

$name = "HW3 Daily Email Briefing"
$runner = Join-Path $PSScriptRoot "run_daily_briefing.ps1"
$existing = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
if ($existing -and $existing.Description -notlike "HW3 Gmail daily briefing*") {
    throw "An unrelated scheduled task already uses this name."
}
$actionArguments = '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy RemoteSigned -File "{0}"' -f $runner
$action = New-ScheduledTaskAction -Execute "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe" -Argument $actionArguments -WorkingDirectory $projectDirectory
$trigger = New-ScheduledTaskTrigger -Daily -At "08:00"
$trigger.StartBoundary = (Get-Date).ToString("yyyy-MM-dd") + "T08:00:00"
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 7)
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description "HW3 Gmail daily briefing at 08:00 Pacific; wake WSL and run the project's Hermes job."
Register-ScheduledTask -TaskName $name -InputObject $task -Force | Select-Object TaskName, State
Get-ScheduledTaskInfo -TaskName $name | Select-Object NextRunTime, LastTaskResult | Format-List
