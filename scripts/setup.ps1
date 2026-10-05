$ErrorActionPreference = "Stop"
$Python = if ($env:LLM_EVAL_PYTHON) { $env:LLM_EVAL_PYTHON } else { "python" }
& $Python (Join-Path $PSScriptRoot "setup.py") @args
exit $LASTEXITCODE
