[CmdletBinding()]
param([Parameter(Mandatory=$true)][ValidateSet('Prepare','Open','Stop','Status')][string]$Action)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$packageRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$localRoot = Join-Path $packageRoot '.local'
$dataRoot = Join-Path $packageRoot 'data'
$packagePython = Join-Path $localRoot 'env\Scripts\python.exe'
$payload = Join-Path $packageRoot 'payload'
$appWheelFile = Join-Path $payload 'fashion_scout-0.2.0a1-py3-none-any.whl'
$lockStream = $null
$exitCode = 2

function Get-SHA256([string]$Path) {
    $stream = [IO.File]::OpenRead($Path)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-','').ToLowerInvariant() }
    finally { $stream.Dispose(); $algorithm.Dispose() }
}
function Assert-OrdinaryPath([string]$Path) {
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    while ($null -ne $item) {
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Linked package/data/runtime paths are unsupported.' }
        $parent = Split-Path -Path $item.FullName -Parent
        if (-not $parent -or $parent -eq $item.FullName) { break }
        $item = Get-Item -LiteralPath $parent -Force -ErrorAction SilentlyContinue
    }
}
function Assert-Package {
    Assert-OrdinaryPath $packageRoot
    $manifestFile = Join-Path $packageRoot 'manifest.json'
    if (-not (Test-Path -LiteralPath $manifestFile -PathType Leaf)) { throw 'manifest.json is missing. Extract the complete ZIP.' }
    $manifest = Get-Content -LiteralPath $manifestFile -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($manifest.schema -ne 1 -or $manifest.data_directory -ne 'data' -or $manifest.default_port -ne 8765) { throw 'Unsupported package manifest.' }
    $seen = @{}
    foreach ($entry in $manifest.files) {
        if ($entry.path -notmatch '^[A-Za-z0-9_. +/-]+$' -or $entry.path -match '(^|/)(\.|\.\.)(/|$)' -or $entry.path.StartsWith('/') -or $seen.ContainsKey($entry.path)) { throw 'Invalid manifest member.' }
        $seen[$entry.path] = $true
        $file = [IO.Path]::GetFullPath((Join-Path $packageRoot $entry.path))
        if (-not $file.StartsWith($packageRoot+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) { throw 'Manifest path escaped package.' }
        Assert-OrdinaryPath $file
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw ('Package file missing: '+$entry.path) }
        if ((Get-Item -LiteralPath $file).Length -ne $entry.bytes -or (Get-SHA256 $file) -ne $entry.sha256) { throw ('Package hash mismatch: '+$entry.path) }
    }
    $wheelMember = if ($manifest.PSObject.Properties.Name -contains 'app_wheel') { $manifest.app_wheel } else { 'payload/fashion_scout-0.2.0a1-py3-none-any.whl' }
    if ($wheelMember -notmatch '^payload/fashion_scout-[0-9][A-Za-z0-9._+]{0,31}-py3-none-any\.whl$') { throw 'Unsupported application wheel member.' }
    foreach ($required in @('package.ps1','payload/verify_install.py','payload/python.tar.gz','payload/requirements-win.lock','payload/runtime-win.json','payload/empty.json','payload/setup.json',$wheelMember)) {
        if (-not $seen.ContainsKey($required)) { throw ('Required manifest member absent: '+$required) }
    }
    $script:appWheelFile = Join-Path $packageRoot $wheelMember
    if ((Get-SHA256 $script:appWheelFile) -ne $manifest.app_sha256) { throw 'Selected application hash conflicts with manifest.' }
}
function Invoke-Checked([string]$Program,[string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw ('Command failed with exit '+$LASTEXITCODE+'. Keep the printed result; data was not reset.') }
}
function Assert-ExistingData {
    Assert-OrdinaryPath $dataRoot
    $config = Join-Path $dataRoot 'control\client.json'
    if (Test-Path -LiteralPath $dataRoot) {
        if (Test-Path -LiteralPath $config -PathType Leaf) {
            Assert-OrdinaryPath $config
            $value = Get-Content -LiteralPath $config -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($value.schema -ne 1 -or $value.data_root -ne $dataRoot -or $value.port -lt 1 -or $value.port -gt 65535) { throw 'Existing data configuration conflicts. Keep data; no rebinding was attempted.' }
        } elseif (@(Get-ChildItem -LiteralPath $dataRoot -Force).Count -ne 0) {
            throw 'Existing data has no confirmed client configuration. Keep data; prepare refused.'
        }
    }
}
$savedPath = $env:PYTHONPATH
$savedHome = $env:PYTHONHOME
$savedVenv = $env:VIRTUAL_ENV
$savedBytecode = $env:PYTHONDONTWRITEBYTECODE
try {
    if (-not [Environment]::Is64BitOperatingSystem) { throw 'Windows x64 is required.' }
    if ($packageRoot.Length -gt 100) { throw 'Package path is too long (maximum 100 characters). Extract into a short writable folder such as D:\FashionScout; keep existing data.' }
    Assert-Package
    Assert-OrdinaryPath $localRoot
    Assert-ExistingData
    $lockStream = [IO.File]::Open((Join-Path $packageRoot '.entry.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
    $env:PYTHONPATH = $null
    $env:PYTHONHOME = $null
    $env:VIRTUAL_ENV = $null
    $env:PYTHONDONTWRITEBYTECODE = '1'
    $ready = Join-Path $localRoot 'ready.json'
    if ($Action -eq 'Prepare' -and -not (Test-Path -LiteralPath $ready)) {
        if (Test-Path -LiteralPath $localRoot) { throw 'Previous preparation is incomplete. Keep data and logs; extract a fresh ZIP in another folder.' }
        New-Item -ItemType Directory -Path $localRoot | Out-Null
        '{"preparing":true}' | Set-Content -LiteralPath (Join-Path $localRoot 'preparing.json') -Encoding UTF8
        $archive = Join-Path $payload 'python.tar.gz'
        $entries = & tar.exe -tf $archive
        if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect runtime archive.' }
        foreach ($entry in $entries) {
            if ($entry -notmatch '^python(/|$)' -or $entry -match '(^|/)\.\.(/|$)' -or $entry.Contains('\')) { throw 'Unexpected runtime archive path.' }
        }
        & tar.exe -xf $archive -C $localRoot
        if ($LASTEXITCODE -ne 0) { throw 'Runtime extraction failed; no application was started.' }
        $basePython = Join-Path $localRoot 'python\python.exe'
        Invoke-Checked $basePython @('-I','-B','-m','venv',(Join-Path $localRoot 'env'))
        Invoke-Checked $packagePython @('-I','-B','-m','pip','--isolated','--disable-pip-version-check','install','--no-index','--no-cache-dir','--find-links',(Join-Path $payload 'wheels'),'--require-hashes','--only-binary=:all:','-r',(Join-Path $payload 'requirements-win.lock'))
        Invoke-Checked $packagePython @('-I','-B','-m','pip','--isolated','--disable-pip-version-check','install','--no-index','--no-cache-dir','--no-deps',$appWheelFile)
        Invoke-Checked $packagePython @('-I','-B','-m','pip','--isolated','--disable-pip-version-check','check')
        if (-not (Test-Path -LiteralPath (Join-Path $dataRoot 'control\client.json'))) {
            Invoke-Checked $packagePython @('-I','-B','-m','fashion_scout.client','configure','--data-root',$dataRoot,'--json-input',(Join-Path $payload 'setup.json'))
        }
        Invoke-Checked $packagePython @('-I','-B',(Join-Path $payload 'verify_install.py'),'freeze',$packageRoot)
        Write-Output 'Preparation complete. Double-click 02 Open.cmd. No Run or service was started.'
    } else {
        if (-not (Test-Path -LiteralPath $ready) -or -not (Test-Path -LiteralPath $packagePython)) { throw 'Run 01 Prepare.cmd first. Existing data was preserved.' }
        Invoke-Checked $packagePython @('-I','-B',(Join-Path $payload 'verify_install.py'),'check',$packageRoot)
        if ($Action -eq 'Prepare') {
            Write-Output 'Already prepared; verified. Existing data and settings were preserved.'
        } elseif ($Action -eq 'Stop') {
            & $packagePython -I -B -m fashion_scout.launcher stop --data-root $dataRoot --graceful --json
            $exitCode = $LASTEXITCODE
            if ($exitCode -ne 0) { throw ('Stop failed with exit '+$exitCode+'. Only verified package identities can be stopped.') }
            Write-Output 'This package instance was stopped.'
        } else {
            $command = if ($Action -eq 'Open') { 'open' } else { 'status' }
            & $packagePython -I -B -m fashion_scout.client request $command --data-root $dataRoot --json-input (Join-Path $payload 'empty.json')
            $exitCode = $LASTEXITCODE
            if ($exitCode -ne 0) { throw ('Open/status failed with exit '+$exitCode+'. A busy port or identity conflict is not force-stopped; keep the printed error.') }
        }
    }
    $exitCode = 0
} catch {
    Write-Host ('Fashion Scout: '+$_.Exception.Message) -ForegroundColor Red
} finally {
    $env:PYTHONPATH = $savedPath
    $env:PYTHONHOME = $savedHome
    $env:VIRTUAL_ENV = $savedVenv
    $env:PYTHONDONTWRITEBYTECODE = $savedBytecode
    if ($null -ne $lockStream) {
        $lockStream.Dispose()
        Remove-Item -LiteralPath (Join-Path $packageRoot '.entry.lock') -Force
    }
}
exit $exitCode
