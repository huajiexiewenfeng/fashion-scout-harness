[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidateSet('Open','Status','Stop','Request','Intent','Bind','Locate')][string]$Action,
    [string]$PackageRoot,
    [string]$BindingPath,
    [ValidateSet('Start','Continue')][string]$Intent,
    [string]$InputJson,
    [ValidateSet('status','ensure','open','new','favorites','product','progress','latest','sites','default-plan','start','retry','cancel','user-state','set-default-plan','intents','resume','export','export-status','export-retry','maintenance','storage','verify','backup','maintenance-status','set-storage','browser-status','browser-attach','browser-continue','browser-observe','browser-upload','browser-asset-failure')][string]$Command
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$skillRoot=Split-Path -Path $PSScriptRoot -Parent
if (-not $BindingPath) { $BindingPath=Join-Path $skillRoot 'local-binding.json' }
$exitCode=3

function Hash([string]$Path) {
    $stream=[IO.File]::OpenRead($Path);$algorithm=[Security.Cryptography.SHA256]::Create()
    try { [BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-','').ToLowerInvariant() }
    finally { $stream.Dispose();$algorithm.Dispose() }
}
function Plain([string]$Path) {
    $item=Get-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    while ($null -ne $item) {
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'LINKED_PATH_UNSUPPORTED' }
        $parent=Split-Path -Path $item.FullName -Parent
        if (-not $parent -or $parent -eq $item.FullName) { break }
        $item=Get-Item -LiteralPath $parent -Force -ErrorAction SilentlyContinue
    }
}
function CheckPackage([string]$Root) {
    if (-not [IO.Path]::IsPathRooted($Root)) { throw 'ABSOLUTE_PACKAGE_ROOT_REQUIRED' }
    $rootPath=[IO.Path]::GetFullPath($Root).TrimEnd('\')
    Plain $rootPath
    if ($rootPath.Length -gt 100 -or -not (Test-Path -LiteralPath (Join-Path $rootPath 'package.ps1'))) { throw 'PACKAGE_MISSING_OR_PATH_UNSUPPORTED' }
    $manifestPath=Join-Path $rootPath 'manifest.json'
    $manifest=Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($manifest.schema -ne 1 -or $manifest.data_directory -ne 'data' -or $manifest.app_sha256 -notmatch '^[0-9a-f]{64}$') { throw 'PACKAGE_MANIFEST_INVALID' }
    foreach ($entry in $manifest.files) {
        if ($entry.path -notmatch '^[A-Za-z0-9_. +/-]+$' -or $entry.path -match '(^|/)(\.|\.\.)(/|$)' -or $entry.path.StartsWith('/')) { throw 'PACKAGE_MEMBER_INVALID' }
        $path=[IO.Path]::GetFullPath((Join-Path $rootPath $entry.path))
        if (-not $path.StartsWith($rootPath+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'PACKAGE_MEMBER_ESCAPED' }
        Plain $path
        if (-not (Test-Path -LiteralPath $path -PathType Leaf) -or (Hash $path) -ne $entry.sha256) { throw ('PACKAGE_FILE_INVALID: '+$entry.path) }
    }
    @{root=$rootPath;manifest_sha256=(Hash $manifestPath);app_sha256=$manifest.app_sha256}
}
function StartPayload([string]$Path) {
    if ($Path) { $payload=Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json }
    else { $payload=[pscustomobject]@{new_intent=$true} }
    if ($null -eq $payload.PSObject.Properties['new_intent'] -or -not ($payload.new_intent -is [bool]) -or -not $payload.new_intent) { throw 'EXPLICIT_NEW_INTENT_REQUIRED' }
    if ($null -eq $payload.PSObject.Properties['overrides']) { $payload | Add-Member -NotePropertyName overrides -NotePropertyValue ([pscustomobject]@{}) }
    if ($null -eq $payload.overrides) { throw 'OVERRIDES_OBJECT_REQUIRED' }
    if ($null -ne $payload.overrides.PSObject.Properties['source_mode']) {
        if ($payload.overrides.source_mode -ne 'browser') { throw 'SKILL_REQUIRES_BROWSER_SOURCE' }
    } else { $payload.overrides | Add-Member -NotePropertyName source_mode -NotePropertyValue 'browser' }
    $payload
}
function CallPackage([string]$Mode) {
    $hostPowerShell=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    & $hostPowerShell -NoLogo -NoProfile -ExecutionPolicy Bypass -File (Join-Path $binding.package_root 'package.ps1') -Action $Mode
    if ($LASTEXITCODE -ne 0) { $script:exitCode=$LASTEXITCODE;throw ('PACKAGE_ACTION_FAILED: '+$Mode) }
}
try {
    if ($Action -eq 'Intent') {
        if ($Intent -eq 'Start') {
            @{command='start';payload=(StartPayload $InputJson);source_execution='requires explicit user intent and current browser connection'} | ConvertTo-Json -Depth 20 -Compress
        } elseif ($Intent -eq 'Continue') {
            @{command='latest';read_only=$true;next='Read current Run and unresolved intents; continue the same browser Run, never issue replacement start.'} | ConvertTo-Json -Compress
        } else { throw 'INTENT_REQUIRED' }
        $exitCode=0
    } elseif ($Action -eq 'Bind') {
        $checked=CheckPackage $PackageRoot
        if (Test-Path -LiteralPath $BindingPath) {
            $old=Get-Content -LiteralPath $BindingPath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($old.package_root -ne $checked.root -or $old.manifest_sha256 -ne $checked.manifest_sha256) { throw 'BINDING_CONFLICT_KEEP_EXISTING' }
        } else {
            $record=@{schema=1;package_root=$checked.root;manifest_sha256=$checked.manifest_sha256;app_sha256=$checked.app_sha256} | ConvertTo-Json -Compress
            $stream=[IO.File]::Open($BindingPath,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
            try { $bytes=[Text.Encoding]::UTF8.GetBytes($record);$stream.Write($bytes,0,$bytes.Length);$stream.Flush($true) }
            finally { $stream.Dispose() }
        }
        @{bound=$true;package_root=$checked.root} | ConvertTo-Json -Compress
        $exitCode=0
    } else {
        if (-not (Test-Path -LiteralPath $BindingPath)) { throw 'BINDING_REQUIRED: Ask once for the application folder, then Bind; do not scan or guess.' }
        Plain $BindingPath
        $binding=Get-Content -LiteralPath $BindingPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($binding.schema -ne 1) { throw 'BINDING_INVALID' }
        $checked=CheckPackage $binding.package_root
        if ($checked.manifest_sha256 -ne $binding.manifest_sha256 -or $checked.app_sha256 -ne $binding.app_sha256) { throw 'BOUND_PACKAGE_CHANGED_KEEP_DATA' }
        $dataRoot=Join-Path $binding.package_root 'data'
        $python=Join-Path $binding.package_root '.local\env\Scripts\python.exe'
        $ready=Test-Path -LiteralPath (Join-Path $binding.package_root '.local\ready.json')
        if ($Action -eq 'Locate') {
            @{package_root=$binding.package_root;python=$python;data_root=$dataRoot;prepared=$ready} | ConvertTo-Json -Compress
        } elseif ($Action -eq 'Open') {
            if (-not $ready) { CallPackage 'Prepare' }
            CallPackage 'Open'
        } elseif ($Action -eq 'Status' -or $Action -eq 'Stop') {
            if (-not $ready) { @{prepared=$false;service_checked=$false;action=$Action} | ConvertTo-Json -Compress }
            else { CallPackage $Action }
        } elseif ($Action -eq 'Request') {
            if (-not $ready) { throw 'OPEN_FIRST_FOR_AUTOMATIC_PREPARATION' }
            if (-not $Command -or -not $InputJson) { throw 'FIXED_COMMAND_AND_CONTROLLED_JSON_REQUIRED' }
            $requests=Join-Path $dataRoot 'requests'
            $requestInput=[IO.Path]::GetFullPath($InputJson)
            if (-not $requestInput.StartsWith($requests+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'INPUT_MUST_STAY_IN_BOUND_DATA_REQUESTS' }
            Plain $requestInput
            if ($Command -eq 'start') {
                $payload=StartPayload $requestInput
                $effective=Join-Path $requests (([Guid]::NewGuid().ToString('N'))+'.json')
                $json=$payload | ConvertTo-Json -Depth 20 -Compress
                [IO.File]::WriteAllText($effective,$json,(New-Object Text.UTF8Encoding $false))
                $requestInput=$effective
            }
            & $python -I -B -m fashion_scout.client request $Command --data-root $dataRoot --json-input $requestInput
            $exitCode=$LASTEXITCODE
            if ($exitCode -ne 0) { throw 'FIXED_CLIENT_REJECTED_KEEP_ORIGINAL_INTENT' }
        }
        $exitCode=0
    }
} catch {
    @{ok=$false;error=$_.Exception.Message;exit_code=$exitCode} | ConvertTo-Json -Compress
}
exit $exitCode
