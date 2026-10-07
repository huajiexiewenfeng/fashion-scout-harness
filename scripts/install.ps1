# Project-local Windows x64 runtime. No PATH, registry, service or scheduled-task changes.
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$runtimeRoot = Join-Path $projectRoot '.runtime'
$pin = Get-Content -LiteralPath (Join-Path $projectRoot 'runtime-win.json') -Raw | ConvertFrom-Json
if (-not [Environment]::Is64BitOperatingSystem) { throw 'Windows x64 is required.' }
New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
$archive = Join-Path $runtimeRoot 'python.tar.gz'
$basePython = Join-Path $runtimeRoot 'python\python.exe'
$projectPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $basePython)) {
    if (-not (Test-Path -LiteralPath $archive)) {
        Invoke-WebRequest -UseBasicParsing -Uri $pin.url -OutFile $archive
    }
    if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $pin.sha256) {
        throw 'Python archive hash mismatch. Nothing has been extracted.'
    }
    $entries = & tar -tf $archive
    if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect pinned Python archive.' }
    foreach ($entry in $entries) {
        if ($entry -notmatch '^python(/|$)' -or $entry -match '(^|/)\.\.(/|$)' -or $entry.Contains('\')) {
            throw 'Archive contains an unexpected path.'
        }
    }
    & tar -xf $archive -C $runtimeRoot
    if ($LASTEXITCODE -ne 0) { throw 'Python archive extraction failed.' }
}
$version = & $basePython -I -c 'import platform; print(platform.python_version())'
if ($LASTEXITCODE -ne 0 -or $version -ne $pin.version) { throw 'Pinned Python version is unavailable.' }
# Environment edits are scoped to this script and restored, including on error.
$savedPythonPath = $env:PYTHONPATH
$savedPythonHome = $env:PYTHONHOME
try {
    $env:PYTHONPATH = $null
    $env:PYTHONHOME = $null
    if (-not (Test-Path -LiteralPath $projectPython)) {
        & $basePython -I -m venv (Join-Path $projectRoot '.venv')
        if ($LASTEXITCODE -ne 0) { throw 'Project venv creation failed.' }
    }
    & $projectPython -I -c 'import sys,sqlite3,struct,pathlib; assert pathlib.Path(sys.prefix).resolve()==pathlib.Path(sys.argv[1]).resolve(); assert sys.version_info[:3]==(3,13,16) and struct.calcsize("P")==8; assert sqlite3.sqlite_version_info>=(3,51,3); print("Runtime gate: Python",sys.version.split()[0],"SQLite",sqlite3.sqlite_version)' (Join-Path $projectRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Project Python/SQLite gate failed.' }
    & $projectPython -I -m pip --disable-pip-version-check install --require-hashes --only-binary=:all: -r (Join-Path $projectRoot 'requirements-win.lock')
    if ($LASTEXITCODE -ne 0) { throw 'Locked dependency installation failed.' }
    & $projectPython -I -m pip --disable-pip-version-check install --no-deps --no-build-isolation -e $projectRoot
    if ($LASTEXITCODE -ne 0) { throw 'Project package installation failed.' }
    & $projectPython -I -m pip --disable-pip-version-check check
    if ($LASTEXITCODE -ne 0) { throw 'Dependency verification failed.' }
} finally {
    $env:PYTHONPATH = $savedPythonPath
    $env:PYTHONHOME = $savedPythonHome
}
Write-Output 'Installed T1 foundation. No Run or application process was started.'
