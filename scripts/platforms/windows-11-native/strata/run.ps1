# Platform/OS-specific entry point; accepts every option in scripts/run.py.
$ErrorActionPreference = "Stop"
$Python = if ($env:LLM_EVAL_PYTHON) { $env:LLM_EVAL_PYTHON } else { "python" }
$Entry = Join-Path $PSScriptRoot "../../../run.py"
& $Python $Entry --platform "strata" --os "windows-11-native" @args
exit $LASTEXITCODE
