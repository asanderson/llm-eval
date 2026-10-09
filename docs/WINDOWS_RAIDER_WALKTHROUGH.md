# Combined campaign on the MSI Raider: native Windows

This walkthrough installs the harness and a private Ollama runtime, prepares real models, then uses **plan → setup → run → status → resume → report** for both experiments on Windows 11. It targets the MSI Raider 18 HX AI, Core Ultra 9 285HX, **RTX 5090 Laptop GPU with 24 GiB VRAM and 64 GiB system RAM**.

The same campaign is also documented for [WSL2 / Ubuntu 26.04](WSL_RAIDER_WALKTHROUGH.md) and [native Ubuntu 26.04](UBUNTU_RAIDER_WALKTHROUGH.md), with separate configurations and OS-specific preparation.

**Output provenance:** the three-job plan below was verified with the actual planner in a Linux development environment. Windows installation, GPU inference, and successful-run transcripts are **illustrative expected output**, not measurements from this laptop. IDs, paths and output structure follow the scripts. No accuracy, latency or memory-performance numbers are invented here. Keep your own terminal output and generated artifacts as the evidence for your run.

## What this example runs

| Phase | Experiment and mode | Cases | Workload |
|---|---|---|---|
| 1: `offload` | Model offloading / `category-smoke` | DeepSeek-R1-Distill-Qwen-32B, GGUF Q8_0, through Ollama | Reasoning, coding and mathematics: three tasks per category |
| 2: `routing` | LLM routing / `decision` | Nimble and Tev1 through Ollama's SystemOne API | Two labeled category decisions per router |

Each task has one warmup and three measured repetitions. If every request completes, this produces 27 measured offload requests and six measured decisions per router. Warmups remain in raw data but are excluded from summaries. These small original workloads demonstrate the workflow; they do **not** produce a full LiveBench score. Decision mode evaluates the routing choice without generating a downstream answer. See the [routing guide](../experiments/llm-routing/README.md) for replay and live modes.

The Q8_0 file selected below is approximately 34.8 decimal GB, exceeding this GPU's 24 GiB capacity. This makes it an offload candidate, not a demonstrated fit. Initial settings are 4,096 context tokens, 16 CPU threads, 20 GPU layers, a 22 GiB GPU planning budget and a 52 GiB RAM planning budget. Budgets are not hard process limits. Inspect placement, memory and paging before interpreting a successful response as a useful configuration.

There is one physical machine and one active job. The routing phase waits for offloading to finish. Raising `max_parallel_jobs` would not permit isolated jobs to overlap on this same host. All three jobs use **one externally prepared Ollama service on `127.0.0.1:11435`**. The campaign does not start or stop this external service; later steps do that explicitly.

## 1. Install the harness

Install Git for Windows, Python 3.12 with the `py` launcher, and PowerShell 7.4 or newer. Use a working NVIDIA Windows driver for the laptop GPU and connect AC power. This prebuilt Ollama example does not compile a backend or require WSL, a CUDA toolkit, Visual Studio, or Docker. Close other inference workloads, including any loaded models in the Ollama tray application.

Run the following blocks in the **same native PowerShell 7 terminal**, from the repository root after cloning. PowerShell 7 is used for consistent UTF-8 handling; the helper below also writes JSON without a BOM. Installers do not change BIOS, power/MUX settings, drivers or disks.

```powershell
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion -lt [version]'7.4') { throw 'Use native PowerShell 7.4 or newer.' }
function Assert-NativeSuccess([string]$Step) {
    if ($LASTEXITCODE -ne 0) { throw "$Step failed (exit $LASTEXITCODE)." }
}
function Write-JsonFile($Value, [string]$Path) {
    $Json = $Value | ConvertTo-Json -Depth 100
    [IO.File]::WriteAllText($Path, $Json + "`n", [Text.UTF8Encoding]::new($false))
}

$Workspace = Join-Path $env:USERPROFILE 'src' # Or a writable folder on your model SSD.
New-Item -ItemType Directory -Force $Workspace | Out-Null
Set-Location $Workspace
git clone https://github.com/asanderson/llm-eval.git
Assert-NativeSuccess 'Clone'
Set-Location .\llm-eval
$Repo = (Get-Location).Path
py -3.12 -m venv .venv
Assert-NativeSuccess 'Create virtual environment'
$Py = Join-Path $Repo '.venv\Scripts\python.exe'
& $Py -m pip install -e '.[telemetry,reporting]'
Assert-NativeSuccess 'Install harness'
& $Py -c 'import llm_eval; print(llm_eval.__version__)'
git rev-parse HEAD
git status --short
```

Expected version at the introduction of this guide: `0.3.0`. The next line is your actual Git commit; a clean `git status --short` prints nothing. Use this same checkout/revision for the whole campaign. The explicit `$Py` path avoids virtual-environment activation and execution-policy changes.

## 2. Copy the example and inventory the laptop

The [example directory](../configs/examples/raider-windows/) contains six JSON files. Their relative paths work both there and in the destination below. Copy them together; edit the ignored local copies so real-run checks still see a clean repository.

```powershell
$Local = Join-Path $Repo 'configs\local\raider-windows'
if (Test-Path $Local) { throw 'Local example already exists; preserve it and use the resume section.' }
New-Item -ItemType Directory -Force $Local | Out-Null
Copy-Item .\configs\examples\raider-windows\*.json $Local
$Campaign = Join-Path $Local 'campaign.json'
$RunConfig = Join-Path $Local 'ollama-run.json'

& $Py -m llm_eval inventory --output "$Local\host-inventory.json"
Assert-NativeSuccess 'Inventory'
$ObservedHost = Get-Content "$Local\host-inventory.json" -Raw | ConvertFrom-Json
$ObservedHost | Select-Object environment_kind, ram_total_gib, ac_connected, psutil_available
$ObservedHost.gpus | Format-Table name, total_mib, driver_version
```

The inventory command prints a full JSON object and saves the same observations. Confirm `environment_kind` is `windows-11-native`, `psutil_available` is `true`, and the GPU name is `NVIDIA GeForce RTX 5090 Laptop GPU`. Driver, RAM, AC and GPU counters must come from your output. A missing/unknown AC sensor is not proof that the machine is on AC. The hardware profile's storage entries are intended configuration; record your actual installed SSD and filesystem below.

This inventory uses `physical_host_id: raider` and the default lock directory, `.cache\llm-eval\locks` under the Windows Python user's home. The WSL walkthrough maps that same physical directory into Linux. Keep both the host ID and directory aligned if you customize either; a matching ID alone cannot coordinate Windows and WSL reservations. Stop this guide's private service before switching to WSL measurements. Reservations do not control unrelated applications or an idle external server.

| Local file | Purpose |
|---|---|
| `campaign.json` | Two ordered phases, three jobs, automatic local reports |
| `inventory.json` | `raider-windows` configuration; physical host `raider` |
| `offload-case.json` | External Ollama service, three offload categories |
| `ollama-run.json` | Model, placement, paths and observed provenance |
| `nimble-case.json`, `tev1-case.json` | Router endpoints, repetitions and loaded-model digests |

## 3. Plan before installation

```powershell
$PlanJson = & $Py -m llm_eval plan --campaign $Campaign
Assert-NativeSuccess 'Plan'
$Plan = $PlanJson | ConvertFrom-Json
Write-JsonFile $Plan "$Local\plan-preview.json"
$Plan.jobs | Select-Object job_id, case_id, hardware_config_id, status | Format-Table -AutoSize
```

Verified planner projection; PowerShell column spacing may differ:

```text
job_id                                      case_id              hardware_config_id status
------                                      -------              ------------------ ------
offload-model-offloading-1-db17c5930ec0       deepseek-r1-32b-q8    raider-windows     planned
routing-llm-routing-1-389a241fd7b8            ollama-nimble        raider-windows     planned
routing-llm-routing-1-25eff864a7d1            ollama-tev1          raider-windows     planned
```

Without the projection, `plan` prints the complete resolved JSON, including dependencies, paths, input hashes and hardware settings. It does not install, download or launch anything. `planned` means the selection is valid; the placeholder provenance fields still prevent real execution until you populate them below.

## 4. Set up Ollama once for the campaign

```powershell
& $Py scripts/setup.py --campaign $Campaign --dry-run
Assert-NativeSuccess 'Preview campaign setup'
& $Py scripts/setup.py --campaign $Campaign
Assert-NativeSuccess 'Set up campaign'
```

The dry run prints the resolved campaign plan. Illustrative successful setup output:

```text
raider ollama succeeded
```

All three jobs share this installation, so setup is deduplicated. It installs the catalog-pinned Ollama archive with checksum verification and a backend environment. It does **not** download your models or start a service. The current catalog pins Ollama 0.35.1; SystemOne requires Ollama 0.35 or newer.

```powershell
$Prefix = Join-Path $Repo '.platforms\windows-11-native\ollama'
$StatePath = Join-Path $Prefix 'state.json'
$Install = Get-Content $StatePath -Raw | ConvertFrom-Json
$Install | Select-Object status, backend_version, executable
```

Expected shape after successful setup:

```text
status    backend_version executable
------    --------------- ----------
installed 0.35.1          ...\.platforms\windows-11-native\ollama\runtime\ollama.exe
```

Detailed setup output is in `.platforms/windows-11-native/ollama.setup.log`. If setup reports failure, inspect that file and any `state.json`; do not continue. Repeating the same setup reuses its installation. A prefix containing a different installation plan is rejected; preserve it and choose a separate prefix/configuration instead of deleting it blindly.

## 5. Download and lock one exact offload artifact

Review the [base model](https://huggingface.co/deepseek-ai/DeepSeek-R1-Distill-Qwen-32B) and [GGUF publisher's model card](https://huggingface.co/bartowski/DeepSeek-R1-Distill-Qwen-32B-GGUF), including their terms. The commands download only the named Q8_0 file. They resolve the quantization repository to a commit once and save that selection. Allow space for both the original GGUF and Ollama's imported copy, both router models, the runtime and results; check your actual SSD free space.

```powershell
$ArtifactRoot = Join-Path $Repo 'models\deepseek-r1-32b-q8'
$ArtifactLock = Join-Path $Repo 'artifacts\deepseek-r1-32b-q8.lock.json'
$QuantRepo = 'bartowski/DeepSeek-R1-Distill-Qwen-32B-GGUF'
$GgufName = 'DeepSeek-R1-Distill-Qwen-32B-Q8_0.gguf'
$SelectionPath = Join-Path $Local 'download-selection.json'
if (Test-Path $SelectionPath) {
    $Selection = Get-Content $SelectionPath -Raw | ConvertFrom-Json
    $QuantRevision = $Selection.source_revision
    if ($Selection.source_repo -ne $QuantRepo -or $Selection.filename -ne $GgufName) {
        throw 'Saved download selection differs; use a separate artifact directory.'
    }
} else {
    $QuantRevision = (Invoke-RestMethod "https://huggingface.co/api/models/$QuantRepo/revision/main").sha
    if ($QuantRevision -notmatch '^[0-9a-f]{40}$') { throw 'Missing immutable artifact revision.' }
    Write-JsonFile @{source_repo=$QuantRepo; source_revision=$QuantRevision; filename=$GgufName} $SelectionPath
}

& $Py -m venv "$Local\download-venv"
Assert-NativeSuccess 'Create download environment'
$DownloadPy = Join-Path $Local 'download-venv\Scripts\python.exe'
$Pins = Get-Content .\catalog\installers.json -Raw | ConvertFrom-Json
& $DownloadPy -m pip install $Pins.model_download_package
Assert-NativeSuccess 'Install pinned downloader'
& $DownloadPy -c 'import sys; from huggingface_hub import hf_hub_download; print(hf_hub_download(repo_id=sys.argv[1], filename=sys.argv[2], revision=sys.argv[3], local_dir=sys.argv[4]))' $QuantRepo $GgufName $QuantRevision $ArtifactRoot
Assert-NativeSuccess 'Download selected GGUF'

& $Py -m llm_eval lock --root $ArtifactRoot --source-repo $QuantRepo --source-revision $QuantRevision --base-model deepseek-ai/DeepSeek-R1-Distill-Qwen-32B --precision Q8_0 --output $ArtifactLock
Assert-NativeSuccess 'Lock artifact'
$Lock = Get-Content $ArtifactLock -Raw | ConvertFrom-Json
$Lock | Select-Object source_repo, source_revision, precision, weight_bytes
```

The lock command prints `Locked 1 files; <actual size> GiB weight artifacts`. Its SHA256 file inventory binds the exact downloaded representation to the catalog's base model. The approximately 32.4 GiB Q8_0 file is larger than physical VRAM; smaller quantizations may belong in the control lane. Keep only this representation in the artifact directory. The downloader's hidden cache metadata is excluded from the artifact lock.

This separate download environment avoids changing the campaign runtime's installation plan. Do not rerun legacy setup with a different download specification against the already-created campaign prefix.

## 6. Start the private service and prepare all models

Use the executable from installation state. Do not rely on a potentially different `ollama` found on `PATH`. First ensure port 11435 is unused. Existing services should be inspected and stopped by their owner, not killed by matching a generic process name.

```powershell
$Ollama = $Install.executable
$Api = 'http://127.0.0.1:11435'
if (Get-NetTCPConnection -LocalPort 11435 -State Listen -ErrorAction SilentlyContinue) {
    throw 'Port 11435 is occupied; identify the service before continuing.'
}
$env:OLLAMA_HOST = '127.0.0.1:11435'
$env:OLLAMA_MODELS = Join-Path $Prefix 'ollama-models'
$env:OLLAMA_NO_CLOUD = '1'
$env:OLLAMA_NUM_PARALLEL = '1'
$env:OLLAMA_MAX_LOADED_MODELS = '1'
$Gpu = @($ObservedHost.gpus | Where-Object { $_.name -eq 'NVIDIA GeForce RTX 5090 Laptop GPU' })
if ($Gpu.Count -ne 1) { throw 'Expected one matching NVIDIA laptop GPU.' }
$env:CUDA_VISIBLE_DEVICES = [string]$Gpu[0].index
$OllamaServer = Start-Process -FilePath $Ollama -ArgumentList 'serve' -PassThru `
    -RedirectStandardOutput "$Local\ollama.stdout.log" -RedirectStandardError "$Local\ollama.stderr.log"
$Ready = $false
for ($Try = 0; $Try -lt 60; $Try++) {
    if ($OllamaServer.HasExited) { throw 'Ollama exited; inspect ollama.stderr.log.' }
    try { $ServerVersion = Invoke-RestMethod "$Api/api/version"; $Ready = $true; break }
    catch { Start-Sleep -Seconds 1 }
}
if (-not $Ready) { throw 'Ollama readiness timed out; inspect the service logs.' }
$ServerVersion

$GgufPath = Join-Path $ArtifactRoot $GgufName
$From = ConvertTo-Json -InputObject $GgufPath -Compress
$Modelfile = "FROM $From`nPARAMETER num_ctx 4096`nPARAMETER num_gpu 20`nPARAMETER num_thread 16`n"
[IO.File]::WriteAllText("$Local\Modelfile", $Modelfile, [Text.UTF8Encoding]::new($false))
& $Ollama create llm-eval-deepseek-r1-32b-q8:locked -f "$Local\Modelfile"
Assert-NativeSuccess 'Import offload model'
& $Ollama pull nimble
Assert-NativeSuccess 'Download Nimble'
& $Ollama pull tev1
Assert-NativeSuccess 'Download Tev1'
& $Ollama cp nimble:latest llm-eval-nimble:locked
Assert-NativeSuccess 'Create study alias for Nimble'
& $Ollama cp tev1:latest llm-eval-tev1:locked
Assert-NativeSuccess 'Create study alias for Tev1'
```

Readiness returns a `version` field; create/pull commands print their own progress and completion output. Downloads do not count as benchmark requests. Study aliases are mutable names: keep their captured digests below and do not pull/recreate them during the campaign. `OLLAMA_MAX_LOADED_MODELS=1` permits replacement between phases; observed load/eviction time remains part of the experiment's timing policy.

### Record actual provenance and check placement

```powershell
$Config = Get-Content $RunConfig -Raw | ConvertFrom-Json
$Show = Invoke-RestMethod "$Api/api/show" -Method Post -ContentType 'application/json' `
    -Body (@{model=$Config.served_model} | ConvertTo-Json)
if (-not $Show.template) { throw 'Active model template is unavailable; resolve before measuring.' }
Write-JsonFile $Show "$Local\offload-model-info.json"
[IO.File]::WriteAllText("$Local\active-template.txt", [string]$Show.template, [Text.UTF8Encoding]::new($false))
$TemplateHash = (Get-FileHash "$Local\active-template.txt" -Algorithm SHA256).Hash.ToLowerInvariant()

$Config.artifact_root = $ArtifactRoot
$Config.artifact_lock = $ArtifactLock
$Config.backend_version = [string]$ServerVersion.version
$Config.backend_pid = $OllamaServer.Id
$Config.tokenizer_revision = "$QuantRepo@$QuantRevision (tokenizer embedded in locked GGUF)"
$Config.chat_template_sha256 = $TemplateHash
$Config.hardware_attestation = [ordered]@{
    bios = (Get-CimInstance Win32_BIOS).SMBIOSBIOSVersion
    os_build = (Get-CimInstance Win32_OperatingSystem).Version
    nvidia_driver = $Gpu[0].driver_version
    ac_connected = $ObservedHost.ac_connected
    ram_configured_mhz = @(Get-CimInstance Win32_PhysicalMemory | Select-Object -ExpandProperty ConfiguredClockSpeed)
    msi_power_fan_profile = (Read-Host 'Actual MSI power/fan profile')
    mux_hybrid_setting = (Read-Host 'Actual MUX/hybrid setting')
    gpu_tgp_power_limit = (Read-Host 'Observed GPU TGP/power limit, or unavailable')
    model_ssd_filesystem = (Read-Host 'Actual model SSD, filesystem, free space and temperature')
    model_path = $ArtifactRoot
}

$Probe = @{model=$Config.served_model; prompt='Reply with OK.'; stream=$false; options=@{num_ctx=4096; num_predict=16}; keep_alive='5m'}
$ProbeResult = Invoke-RestMethod "$Api/api/generate" -Method Post -ContentType 'application/json' `
    -Body ($Probe | ConvertTo-Json -Depth 10) -TimeoutSec 900
Write-JsonFile $ProbeResult "$Local\generation-preflight.json"
& $Ollama ps
Get-Content "$Local\ollama.stderr.log" -Tail 60
$Config.placement_notes = Read-Host 'Record observed CPU/GPU placement from ps/logs, requested 20 layers and 16 threads, plus any paging'
Write-JsonFile $Config $RunConfig

$Tags = Invoke-RestMethod "$Api/api/tags"
Write-JsonFile $Tags "$Local\model-digests.json"
foreach ($Name in @('nimble','tev1')) {
    $CasePath = Join-Path $Local "$Name-case.json"
    $Case = Get-Content $CasePath -Raw | ConvertFrom-Json
    $Match = @($Tags.models | Where-Object { $_.name -eq $Case.parameters.router.model })
    if ($Match.Count -ne 1 -or -not $Match[0].digest) { throw "Missing digest for $Name." }
    $Case.parameters.router.model_revision = $Match[0].digest
    Write-JsonFile $Case $CasePath
    $Question = @{type='choice'; instructions=$Case.parameters.router.instructions; criteria=$Case.parameters.router.criteria}
    $Request = @{model=$Case.parameters.router.model; state=@{text='Write a Python function to reverse a string.'}; questions=@{route=$Question}}
    $Decision = Invoke-RestMethod "$Api/v1/systemone" -Method Post -ContentType 'application/json' `
        -Body ($Request | ConvertTo-Json -Depth 20) -TimeoutSec 300
    Write-JsonFile $Decision "$Local\$Name-preflight.json"
    $Decision.answers.route | Select-Object type, choice
}
```

An expected SystemOne response has `type: choice` and one of the configured labels (`coding`, `math`, `general`); the harness will evaluate correctness itself. Inspect actual model output and placement. Stop if the load fails, placement differs from your settings, or paging makes the intended RAM-resident experiment invalid. Do not fill observations with assumed values merely to pass preflight. This brief generation probe is outside the measured suite and is not a quality qualification.

The external server honors the imported Modelfile. Changing `launch.gpu_layers` in the JSON alone does not reconfigure an external model. To change placement, create a new model/configuration, record its template/digest/observations, and start a new campaign. Likewise, changing model data after creating the artifact lock requires a new verified lock.

## 7. Final plan and optional automatic results PRs

All local provenance edits must finish **before** creating the campaign. For a first run, the supplied configuration generates local reports without needing GitHub credentials. To enable automatic PR creation instead, run this optional block **now**:

```powershell
# OPTIONAL: enable publication for this new campaign.
$CampaignConfig = Get-Content $Campaign -Raw | ConvertFrom-Json
$CampaignConfig.reporting.publish.mode = 'pull-request'
Write-JsonFile $CampaignConfig $Campaign
$env:GH_TOKEN = Read-Host 'GitHub token with repository contents and pull-request write permissions' -MaskInput
```

The token is process-local, not saved in JSON. The token account needs permission to push branches and open PRs in `asanderson/llm-eval`, and `origin` must point there. A fork requires changing both the configured repository and `origin`. For automatic publication set credentials after the inference service starts, as above. Inference workers do not need publication credentials.

```powershell
$FinalPlanJson = & $Py -m llm_eval plan --campaign $Campaign
Assert-NativeSuccess 'Final plan'
$FinalPlan = $FinalPlanJson | ConvertFrom-Json
Write-JsonFile $FinalPlan "$Local\final-plan.json"
$FinalPlan.jobs | Select-Object case_id, mode, hardware_config_id, status | Format-Table
git status --short
```

The same three jobs should remain `planned`; input/config hashes now reflect your real settings. Keep the checkout and input files unchanged while running or resuming. An initial planning preview is not an inference-ready certification.

## 8. Run the combined campaign

Use a dedicated output parent so the monitoring terminal can locate this run unambiguously. Save its name for later sessions.

```powershell
$OutputRoot = Join-Path $Repo ('results\raider-win-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory $OutputRoot | Out-Null
[IO.File]::WriteAllText("$Local\active-output-root.txt", $OutputRoot, [Text.UTF8Encoding]::new($false))
& $Py -u scripts/run.py --campaign $Campaign --output $OutputRoot
$RunExit = $LASTEXITCODE
"Run exit: $RunExit"
$CampaignDir = (Get-ChildItem $OutputRoot -Directory -Filter 'campaign-*' | Select-Object -First 1).FullName
```

Illustrative successful terminal output; the path is generated, not something to type literally:

```text
Campaign results: C:\Users\YOU\src\llm-eval\results\raider-win-20261009-153000\campaign-20261009T193000Z-a1b2c3d4
Run exit: 0
```

`-u` flushes the initial campaign path promptly. The foreground command remains busy while jobs run; it does not print a token stream or progress bar. Reports are generated after their experiment finishes, when local measurements are no longer active. The journal uses UTC; the example's outer PowerShell directory uses local time.

Exit `0` means evaluations and enabled reporting succeeded; `1` means incomplete/failed evaluation or reporting; `2` means a configuration/setup error; `130` means cancellation. A completed request with a failed quality check can still be a successful execution: inspect the report's quality metrics separately.

## 9. Check status from a second native PowerShell terminal

Replace the first path with your clone location. This terminal only reads state; it must not start a second campaign on the laptop.

```powershell
Set-Location "$env:USERPROFILE\src\llm-eval"
$Py = Join-Path (Get-Location).Path '.venv\Scripts\python.exe'
$Local = Join-Path (Get-Location).Path 'configs\local\raider-windows'
$OutputRoot = Get-Content "$Local\active-output-root.txt" -Raw
$CampaignDir = (Get-ChildItem $OutputRoot -Directory -Filter 'campaign-*' | Select-Object -First 1).FullName
& $Py -m llm_eval status --campaign-dir $CampaignDir
$Status = Get-Content "$CampaignDir\campaign.json" -Raw | ConvertFrom-Json
$Status.jobs.PSObject.Properties | ForEach-Object {
    [pscustomobject]@{Job=$_.Name; Status=$_.Value.status; Attempts=@($_.Value.attempts).Count}
} | Format-Table -AutoSize
```

The CLI prints the full JSON journal. An illustrative projection while the first job runs is:

```text
Job                                         Status  Attempts
---                                         ------  --------
offload-model-offloading-1-db17c5930ec0        running        1
routing-llm-routing-1-389a241fd7b8             planned        0
routing-llm-routing-1-25eff864a7d1             planned        0
```

After a successful run all three show `succeeded`, normally with one attempt each. Experiment report states appear separately in `campaign.json.reports` as `generated` or `published`. A `failed` report receipt does not erase completed model measurements.

## 10. Resume, retry or cancel

After the original coordinator exits, resume the **existing campaign directory**:

```powershell
& $Py -m llm_eval resume --campaign-dir $CampaignDir
"Resume exit: $LASTEXITCODE"
& $Py -m llm_eval status --campaign-dir $CampaignDir
```

For a completed campaign, normal output is just the added `Resume exit: 0` line, followed by the status JSON. `resume` itself is normally silent. Completed jobs retain their attempt counts and are not re-executed. Running `scripts/run.py` again would create a **new** campaign instead.

If a recoverable inference failure occurred, repair the service condition without changing the measured configuration, then explicitly retry failed/cancelled jobs:

```powershell
& $Py -m llm_eval resume --campaign-dir $CampaignDir --retry-failed
"Retry exit: $LASTEXITCODE"
```

Retries create new attempt directories; the report preserves all raw attempts and summarizes the latest attempt for each job. Failed dependencies leave the routing phase blocked until offloading succeeds. `lost` jobs require confirmed worker completion/reconciliation; a timeout is not permission to delete a lock or start duplicate requests.

To cancel while the first terminal is still running, use the second terminal:

```powershell
& $Py -m llm_eval cancel --campaign-dir $CampaignDir
"Cancel request exit: $LASTEXITCODE"
```

This command is normally silent; `0` acknowledges the cancellation request, not completed process cleanup. Wait for the original coordinator to exit and inspect status before resuming. The external Ollama service remains running and an in-flight external request may finish after the worker stops. Confirm the service is idle before another measurement.

Do not edit campaign/case/suite files or `git pull` between run and resume. In this external-service example, the recorded `backend_pid` must still identify the same service. After a service restart or reboot, record the new PID and fresh observations and create a **new campaign**; this avoids falsely attributing process telemetry to a stale PID. Preserve the old campaign as incomplete if necessary.

## 11. Generate and inspect both experiment reports

Automatic local reporting is already enabled. After measurement stops, the following command retries missing/failed finalization or reuses completed receipts:

```powershell
& $Py -m llm_eval report --input $CampaignDir
```

Illustrative output with local-only publication:

```json
{
  "offload-model-offloading-1": {
    "status": "generated",
    "report": "experiments/offload-model-offloading-1/report",
    "result_signature": "<actual result signature>"
  },
  "routing-llm-routing-1": {
    "status": "generated",
    "report": "experiments/routing-llm-routing-1/report",
    "result_signature": "<actual result signature>"
  }
}
```

Path separators may be backslashes in Windows JSON. There are **two reports**, one per experiment run; the routing report includes both routers. To regenerate an individual report explicitly and read its files:

```powershell
$OffloadDir = Join-Path $CampaignDir 'experiments\offload-model-offloading-1'
$RoutingDir = Join-Path $CampaignDir 'experiments\routing-llm-routing-1'
foreach ($ExperimentDir in @($OffloadDir,$RoutingDir)) {
    & $Py scripts/report_experiment.py --experiment-dir $ExperimentDir
    if ($LASTEXITCODE -ne 0) { throw 'Report generation failed.' }
    $Report = Join-Path $ExperimentDir 'report'
    $Publication = Get-Content "$Report\publication.json" -Raw | ConvertFrom-Json
    $ReportDocs = Join-Path "$Report\bundle" $Publication.report_path
    Get-Content "$ReportDocs\README.md"
    Import-Csv "$ReportDocs\summary.csv" | Select-Object category, requests, successful_requests, errors_or_missing
    Get-ChildItem "$Report\bundle\diagrams" -Recurse -Filter '*.png' | ForEach-Object { Invoke-Item $_.FullName }
}
```

The script prints `Experiment report: <actual experiment directory>\report`. A successful offload summary has three category rows with nine measured requests each. A successful routing summary has two category rows per router with three measured requests per row. Actual pass rates and timings must come from your files; low scores on these tiny smoke workloads are not robust model rankings.

| File in the report bundle | What to inspect |
|---|---|
| `docs/results/<experiment>/<publication>/README.md` | Configuration coverage, status, links and embedded chart |
| `raw/measurements.jsonl.gz` | Sanitized requests, telemetry, metadata and attempt records; warmups retained |
| `summary.json`, `summary.csv` | Category cohorts, missing/error counts, quality/decision metrics and successful-request timing |
| `benchmark-summary.json`, `benchmark-summary.csv` | Empty for this example; populated by upstream benchmark score exports |
| `manifest.json`, `resolved-config.json` | Recorded configuration, input/export hashes and omitted fields |
| `diagrams/results/<experiment>/<publication>/latency.png` | Rendered report chart |

Original artifacts remain under each experiment's `jobs/<job-id>/<attempt-id>/`. The public bundle omits known credentials, private paths and retained prompt/answer bodies by default. Keep the original local data for reproduction and review the export before publication.

## 12. Push results PRs and finish

If you enabled automatic publication before running, successful finalization already pushed results branches and opened PRs. The journal's report receipts contain their URLs. The publisher never merges them.

For local-only runs, preview each publication and then publish explicitly:

```powershell
foreach ($ExperimentDir in @($OffloadDir,$RoutingDir)) {
    & $Py -m llm_eval publish-results --input "$ExperimentDir\report" --dry-run
    if ($LASTEXITCODE -ne 0) { throw 'Publication bundle validation failed.' }
}
$env:GH_TOKEN = Read-Host 'GitHub token with repository contents and pull-request write permissions' -MaskInput
foreach ($ExperimentDir in @($OffloadDir,$RoutingDir)) {
    & $Py -m llm_eval publish-results --input "$ExperimentDir\report"
    if ($LASTEXITCODE -ne 0) { throw 'Publication failed; preserve the report and retry this command later.' }
}
Remove-Item Env:GH_TOKEN
```

Dry-run output contains `branch`, `bytes`, `files` and `dry_run: true`. Illustrative publication receipt, with placeholders rather than a fabricated PR:

```json
{
  "url": "https://github.com/asanderson/llm-eval/pull/<new-pr-number>",
  "branch": "results/model-offloading/<publication-id>",
  "commit": "<actual pushed commit>",
  "fingerprint": "<actual report fingerprint>",
  "status": "open"
}
```

Expect two results PRs, each adding its raw and summarized data, chart, manifest and results-index entry. Incomplete reports open draft PRs. Network/authentication failures preserve the complete local bundle; rerun `publish-results` without rerunning inference. Manual publication writes `report/publication-state.json`; the campaign's earlier receipt may still say `generated`. Automatic publication records `published` in the campaign journal.

Once no measurement or resume work remains, stop the external service you created, including its owned runner processes. From the original terminal:

```powershell
$OllamaServer.Refresh()
if (-not $OllamaServer.HasExited) {
    $OllamaServer.Kill($true) # PowerShell 7 / .NET: include this process's descendants.
    $OllamaServer.WaitForExit()
}
```

If the service has already exited, inspect the remaining processes rather than reusing an old PID. Do not stop an unrelated tray application or server. Keep `configs/local/raider-windows/`, the source revision, original results, artifact lock and exact model files for reproduction.

## Troubleshooting checkpoints

| Symptom | Next action |
|---|---|
| Setup prints `raider ollama setup failed` | Read `.platforms/windows-11-native/ollama.setup.log`; check network, archive verification and prefix-plan mismatch. |
| Job is `blocked` before model requests | Inspect its attempt `result.json`/journal error type; confirm native Windows, clean Git revision, GPU/telemetry and completed provenance. |
| Job is `failed` | Read `worker.log`, nested measurement `metadata.json`, request errors and private Ollama logs. |
| Reports show incorrect/low-quality answers | Inspect quality checks, model/template identity and token limits; a transport success does not imply a correct answer. |
| Resume rejects a changed input/revision | Restore the exact inputs/revision or start a new campaign; do not weaken the recorded hashes. |
| `lost` or resource-reserved status | Inspect owned worker/service processes and reservations before recovery; never delete a live lock. |
| Report publication fails | Fix credentials, repository access, origin mismatch or bundle size, then retry `publish-results`. |

See [campaign semantics](CAMPAIGNS.md), [reporting/publication](RESULTS.md), and [remaining hardware validation](VALIDATION.md).

## Source references

Checked 2026-10-09: [Ollama native Windows distribution](https://docs.ollama.com/windows), [SystemOne and decision-model announcement](https://ollama.com/blog/ollama-now-supports-jev-style-decision-models), [Ollama API reference](https://github.com/ollama/ollama/blob/main/docs/api.md), [Modelfile reference](https://docs.ollama.com/modelfile), [selected GGUF publisher](https://huggingface.co/bartowski/DeepSeek-R1-Distill-Qwen-32B-GGUF), and [revision-pinned Hugging Face downloads](https://huggingface.co/docs/huggingface_hub/guides/download). Installer pins come from this repository's [catalog](../catalog/installers.json); protocol compatibility and actual loaded artifacts must still be verified on the target laptop.
