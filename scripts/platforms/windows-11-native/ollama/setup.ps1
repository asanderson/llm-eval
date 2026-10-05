# Platform/OS-specific entry point; accepts every option in scripts/setup.py.
$ErrorActionPreference = "Stop"
$Python = if ($env:LLM_EVAL_PYTHON) { $env:LLM_EVAL_PYTHON } else { "python" }
$Entry = Join-Path $PSScriptRoot "../../../setup.py"
& $Python $Entry --platform "ollama" --os "windows-11-native" @args
exit $LASTEXITCODE
