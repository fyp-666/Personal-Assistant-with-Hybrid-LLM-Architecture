$ErrorActionPreference = "Stop"
$wslArguments = @(
    "-d", "Ubuntu", "-u", "fyp", "--exec", "/usr/bin/env",
    "HERMES_TIMEZONE=America/Los_Angeles",
    "HERMES_CRON_SCRIPT_TIMEOUT=21600",
    "/home/fyp/.local/bin/hermes", "--profile", "hw3-local", "cron"
)
$wsl = "$env:WINDIR\System32\wsl.exe"
$result = 1
try {
    & $wsl @wslArguments resume hw3-daily-email
    if ($LASTEXITCODE -ne 0) { throw "Could not enable the Hermes job for this run." }
    $runOutput = & $wsl @wslArguments run hw3-daily-email
    $runExitCode = $LASTEXITCODE
    $runOutput | Write-Output
    # Hermes 0.21 may return exit 0 even when the script fails.
    if ($runExitCode -eq 0 -and ($runOutput -match "Ran now: succeeded\.")) {
        $result = 0
    }
} finally {
    # Pause after every run so only Windows owns the next scheduled trigger.
    & $wsl @wslArguments pause hw3-daily-email
    if ($LASTEXITCODE -ne 0) { $result = 1 }
}
exit $result
