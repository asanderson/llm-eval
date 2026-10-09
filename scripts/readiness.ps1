# Windows PowerShell 5.1 can bootstrap Python; PowerShell 7 is checked afterward.
$ErrorActionPreference = 'Stop'
$ForwardArgs = @($args)
$CheckOnly = $ForwardArgs -contains '--check-only'
$AssumeYes = $ForwardArgs -contains '--yes'
if ($CheckOnly -and $AssumeYes) { Write-Error '--check-only and --yes are mutually exclusive.'; exit 2 }
$Repo = Split-Path -Parent $PSScriptRoot
$Probe = 'import sys,venv,ensurepip,ssl,tarfile; assert (3,11)<=sys.version_info[:2]<=(3,13); assert sys.maxsize>2**32; assert hasattr(tarfile,"data_filter"); print(sys.executable)'
function Find-CompatiblePython {
    # Older Windows PowerShell treats native stderr as an ErrorRecord even when
    # probing an unavailable launcher version. A failed probe must not abort.
    $ErrorActionPreference = 'Continue'
    $Candidates = @($env:LLM_EVAL_PYTHON, (Join-Path $Repo '.venv\Scripts\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'), 'python')
    foreach ($Candidate in $Candidates) {
        if ($Candidate -and (Get-Command $Candidate -ErrorAction SilentlyContinue)) {
            $Result = & $Candidate -c $Probe 2>$null
            if ($LASTEXITCODE -eq 0) { return [string]($Result | Select-Object -Last 1) }
        }
    }
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($Version in @('-3.12', '-3.13', '-3.11')) {
            $Result = & py $Version -c $Probe 2>$null
            if ($LASTEXITCODE -eq 0) { return [string]($Result | Select-Object -Last 1) }
        }
    }
    return $null
}
$Python = Find-CompatiblePython
if (-not $Python) {
    Write-Host '[MISSING] Python 3.11-3.13 x64 with venv/pip/TLS.'
    if (($ForwardArgs -contains '--help') -or ($ForwardArgs -contains '-h')) {
        Write-Host 'readiness.ps1 [--platform NAME | --campaign FILE] [--check-only | --yes] [--json-output FILE]'
        Write-Host 'See docs/READINESS.md; complete CLI help is available after Python bootstrap.'
        exit 0
    }
    if ($CheckOnly) { Write-Host 'Full inspection needs Python; rerun without --check-only to offer installation.'; exit 1 }
    if ([Environment]::OSVersion.Platform -ne 'Win32NT') { Write-Error 'Use readiness.sh inside Ubuntu/WSL.'; exit 2 }
    $Build = [int](Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion').CurrentBuildNumber
    if ($Build -lt 22000 -or ($env:PROCESSOR_ARCHITECTURE -ne 'AMD64' -and $env:PROCESSOR_ARCHITEW6432 -ne 'AMD64')) {
        Write-Host 'Automatic bootstrap requires native Windows 11 on x86-64 hardware.'
        exit 2
    }
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Write-Host '[MISSING] winget: install/repair App Installer, then rerun. https://learn.microsoft.com/windows/package-manager/winget/'
        exit 1
    }
    Write-Host 'Proposed: winget install --id Python.Python.3.12 --exact --source winget --architecture x64 --accept-source-agreements --accept-package-agreements'
    $Consent = $AssumeYes
    if (-not $Consent -and -not [Console]::IsInputRedirected) {
        $Consent = (Read-Host 'Install Python 3.12 and accept its package/source agreements? [y/N]') -match '^(y|yes)$'
    }
    if (-not $Consent) { exit 1 }
    & winget install --id Python.Python.3.12 --exact --source winget --architecture x64 --accept-source-agreements --accept-package-agreements
    if ($LASTEXITCODE -ne 0) { Write-Host "Python installer exit: $LASTEXITCODE. Rerun after any requested reboot."; exit 1 }
    $env:Path = $env:Path + ';' + [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
    $Python = Find-CompatiblePython
    if (-not $Python) { Write-Host 'Python is not yet discoverable. Open a new terminal and rerun readiness.'; exit 1 }
}
& $Python (Join-Path $PSScriptRoot 'readiness.py') @ForwardArgs
exit $LASTEXITCODE
