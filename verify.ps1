# Windows PowerShell entry point for the same gates as ./verify.
#   .\verify.ps1            everything
#   .\verify.ps1 --quick    shorter lab runs
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
uv sync --all-packages --frozen --quiet
uv run --frozen --no-sync python tools/verify.py @args
exit $LASTEXITCODE
