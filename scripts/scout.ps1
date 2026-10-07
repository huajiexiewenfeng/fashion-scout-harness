# Pass launcher arguments unchanged, e.g. ensure --json --data-root C:\ScoutData.
$projectPython = Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) { throw 'Run scripts/install.ps1 first.' }
& $projectPython -I -m fashion_scout.launcher @args
exit $LASTEXITCODE
