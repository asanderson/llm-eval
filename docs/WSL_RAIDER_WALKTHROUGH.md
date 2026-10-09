# Combined campaign on the MSI Raider: WSL2 with Ubuntu 26.04

This walkthrough installs the harness and a private Ollama runtime, prepares real models, then uses **plan → setup → run → status → resume → report** for a combined campaign. The physical machine is the **MSI Raider 18 HX AI, Core Ultra 9 285HX, RTX 5090 Laptop GPU with 24 GiB VRAM and 64 GiB system RAM**.

**Output provenance:** the three-job plan below was verified with the actual planner in a Linux development environment. Installation, GPU inference and successful-run transcripts for this laptop are **illustrative expected output**, not measurements. No accuracy, latency or memory-performance numbers are invented. Retain your actual terminal output and generated artifacts.

## What this example runs

| Phase | Experiment and mode | Cases | Workload |
|---|---|---|---|
| 1: `offload` | Model offloading / `category-smoke` | DeepSeek-R1-Distill-Qwen-32B, GGUF Q8_0, through Ollama | Reasoning, coding and mathematics: three tasks per category |
| 2: `routing` | LLM routing / `decision` | Nimble and Tev1 through Ollama's SystemOne API | Two labeled category decisions per router |

Each task has one warmup and three measured repetitions: 27 measured offload requests and six measured decisions per router if all requests complete. Warmups remain in raw data and are excluded from summaries. These small original workloads demonstrate the workflow; they do **not** produce a full LiveBench score. Decision mode checks the routing choice without generating a downstream answer. See the [routing guide](../experiments/llm-routing/README.md) for replay/live modes.

The selected Q8_0 artifact is approximately 34.8 decimal GB (32.4 GiB), exceeding the GPU's capacity. It is an offload candidate, not a demonstrated fit. Initial settings are 4,096 context tokens, 16 CPU threads, 20 GPU layers and a 22 GiB GPU planning budget. The WSL RAM planning budget is 46 GiB within a configured 52 GiB guest memory cap. Budgets are not hard process limits; confirm actual placement and paging before measuring.

All three jobs run serially on physical host `raider`, using **one external Ollama service at `127.0.0.1:11435`**. Routing waits for offloading. Increasing `max_parallel_jobs` cannot overlap isolated jobs on this same host. Separate machines can run in parallel through [campaign hardware configurations](CAMPAIGNS.md). The campaign does not start/stop this external service; the steps below do so explicitly.

## 0. Prepare Ubuntu 26.04 under WSL2

Use Windows 11 with a working, current NVIDIA Windows driver that supports this laptop and WSL GPU compute. **The Windows driver supplies the WSL GPU interface. Do not install a Linux NVIDIA display/kernel driver inside WSL.** Follow [NVIDIA's WSL guidance](https://docs.nvidia.com/cuda/wsl-user-guide/index.html) for driver problems. The prebuilt Ollama runtime does not need a separate CUDA toolkit.

From a Windows PowerShell terminal, inspect the installed WSL version and available distributions:

```powershell
wsl --version
wsl --list --online
# For a new installation; skip if this distribution is already installed.
wsl --install --distribution Ubuntu-26.04
wsl --list --verbose
```

Grant elevation/reboot if Windows requests it, then complete Ubuntu's first-launch Linux username/password setup. The installed distribution should appear as `Ubuntu-26.04` with WSL version `2`; use its actual registered name if yours differs. See [Ubuntu's WSL installation guide](https://documentation.ubuntu.com/wsl/latest/guides/install-ubuntu-wsl2/) for an existing/custom distribution or installation failure. Confirm Ubuntu 26.04 inside the guest; another Ubuntu version does not match this campaign's OS identity.

### Give the guest an explicit memory envelope

Merge these settings into `%UserProfile%\.wslconfig` in Windows, preserving other existing sections/settings. The file is outside the Linux guest:

```ini
[wsl2]
memory=52GB
processors=24
swap=0
```

This example caps the WSL2 VM at 52 GiB and gives it 24 logical processors. Its 46 GiB evaluation budget leaves approximately 6 GiB within the guest for other memory; the host retains approximately 12 GiB of physical capacity outside the guest cap. These are planning allowances, not guaranteed free memory. All WSL2 distributions share VM resources. `swap=0` intentionally disables WSL swap for this example; it does not disable the Windows pagefile or prove the Windows host did not page. Record changes if you evaluate a swap-enabled lane separately.

Save work and stop campaigns/services in **all** WSL distributions before applying the settings:

```powershell
wsl --shutdown
wsl --distribution Ubuntu-26.04
```

`wsl --shutdown` stops all WSL distributions; do not run it during an experiment. Settings and their scope are documented in [Microsoft's WSL configuration reference](https://learn.microsoft.com/en-us/windows/wsl/wsl-config).

In the new **Ubuntu Bash terminal**, verify guest identity, GPU visibility and memory:

```bash
cd ~
cat /etc/os-release
uname -r
if command -v nvidia-smi >/dev/null 2>&1; then
    nvidia-smi
else
    /usr/lib/wsl/lib/nvidia-smi
fi
free -h
swapon --show
export OS_ID='windows-11-wsl2-ubuntu-26.04'
export EXAMPLE_NAME='raider-wsl'
export PATH="/usr/lib/wsl/lib:$PATH"
```

Expect Ubuntu `26.04`, a WSL2 kernel and the RTX 5090 Laptop GPU. Some GPU/AC telemetry is limited under WSL; unavailable counters remain unknown. Verify the cap and lack of guest swap from your actual output. Also record Windows host memory during measurement in step 8; guest RSS alone cannot establish host RAM usage or paging.

Keep the repository, virtual environments, runtime and model files under **Linux home on the WSL ext4 filesystem**, not `/mnt/c`. Check that the Windows volume holding the WSL virtual disk has enough physical free space too; a guest virtual-disk capacity alone is insufficient. The exception below is the shared reservation directory, which must reside on the Windows filesystem to coordinate with native Windows runs.

Stop any private Ollama service from the [native Windows walkthrough](WINDOWS_RAIDER_WALKTHROUGH.md) and close unrelated Windows/WSL inference workloads before measuring. A different port or Linux distribution does not create a separate physical GPU.

## 1. Install the harness with Python 3.12

The [WSL readiness script](READINESS.md) provides a prompted installation alternative from an existing clone: `bash scripts/readiness.sh --platform ollama`. It can bootstrap Python, harness libraries and the pinned runtime; the shared reservation check remains incomplete until step 2. The commands below document the manual path; preserve any environment already prepared by readiness. After configuring the shared directory, audit with `bash scripts/readiness.sh --campaign configs/local/raider-wsl/campaign.json --check-only`.

Use one **Bash terminal in this Ubuntu installation** for the following steps. Keep the `OS_ID` and `EXAMPLE_NAME` selections from the preparation section above. Connect AC power and close unrelated CPU/GPU inference workloads. The prebuilt Ollama recipe does not require compiling an engine, a CUDA toolkit, or Docker.

The harness setup environments support Python 3.11–3.13. Select Python 3.12 explicitly instead of assuming Ubuntu's default interpreter is compatible. This bootstrap uses an isolated uv installation; it does not replace system Python. It resolves a 3.12 patch release once and records the versions. Keep that interpreter unchanged during the campaign.

```bash
set -euo pipefail
sudo apt update
sudo apt install -y git ca-certificates curl python3-venv libgomp1

BOOTSTRAP="$HOME/.local/share/llm-eval-bootstrap-$OS_ID"
python3 -m venv "$BOOTSTRAP"
"$BOOTSTRAP/bin/python" -m pip install uv
"$BOOTSTRAP/bin/uv" python install 3.12
PYTHON312="$("$BOOTSTRAP/bin/uv" python find 3.12)"

export REPO="$HOME/src/llm-eval"
mkdir -p "$(dirname "$REPO")"
git clone https://github.com/asanderson/llm-eval.git "$REPO"
cd "$REPO"
"$PYTHON312" -m venv .venv
export PY="$REPO/.venv/bin/python"
"$PY" -m pip install -e '.[telemetry,reporting]'
"$PY" -c 'import sys,llm_eval; print(sys.version); print(llm_eval.__version__)'
git rev-parse HEAD
git status --short
```

For an existing clone, `cd` into it and set `REPO` rather than cloning over it. At the introduction of this guide, the package prints `0.3.0`. Record the actual Python version and Git SHA; a clean `git status --short` prints nothing. Use the same revision for setup, run and resume.

## 2. Copy the campaign and record inventory

```bash
export LOCAL="$REPO/configs/local/$EXAMPLE_NAME"
if [ -e "$LOCAL" ]; then
    printf '%s\n' 'Local campaign already exists; preserve it and use the resume instructions.'
    exit 1
fi
mkdir -p "$LOCAL"
cp "configs/examples/$EXAMPLE_NAME/"*.json "$LOCAL/"
export CAMPAIGN="$LOCAL/campaign.json"
"$BOOTSTRAP/bin/python" -m pip freeze > "$LOCAL/bootstrap-freeze.txt"
"$PY" -m pip freeze > "$LOCAL/harness-freeze.txt"
"$PY" -m llm_eval inventory --output "$LOCAL/host-inventory.json"
findmnt -T "$REPO" -o TARGET,SOURCE,FSTYPE
df -h "$REPO"
free -h
swapon --show
```

The inventory command prints and saves JSON. Confirm `environment_kind` is `windows-11-wsl2-ubuntu-26.04`, `psutil_available` is `true`, and `gpus` contains `NVIDIA GeForce RTX 5090 Laptop GPU`. Counters, driver versions and AC state must come from the actual host. Unknown AC or sensor values remain unknown; confirm AC manually. The hardware profile describes the physical laptop, not proof of the current SSD, RAM speed or power configuration.

### Share the Windows physical-host reservation

The [example inventory](../configs/examples/raider-wsl/inventory.json) deliberately contains `REPLACE_WITH_SHARED_WINDOWS_LOCK_ROOT`. Replace it before planning or setup. This block maps the default lock directory used by the native Windows walkthrough into WSL:

```bash
WIN_PROFILE="$(powershell.exe -NoProfile -NonInteractive -Command '[Environment]::GetFolderPath("UserProfile")' | tr -d '\r')"
export SHARED_LOCK_ROOT="$(wslpath -u "$WIN_PROFILE")/.cache/llm-eval/locks"
mkdir -p "$SHARED_LOCK_ROOT"
test -w "$SHARED_LOCK_ROOT"
"$PY" - <<'PY'
import json,os
from pathlib import Path
p=Path(os.environ['LOCAL'])/'inventory.json'
d=json.loads(p.read_text());root=os.environ['SHARED_LOCK_ROOT']
assert Path(root).is_absolute() and 'REPLACE' not in root
d['targets']['raider']['lock_root']=root
p.write_text(json.dumps(d,indent=2)+'\n')
print('Shared lock root:',root)
PY
```

Illustrative path: `/mnt/c/Users/YOU/.cache/llm-eval/locks`. Both OS inventories must refer to this **same physical directory** and `physical_host_id: raider`. If native Windows uses another account or an explicit `lock_root`, map that exact location instead. Matching the host ID without sharing the directory does not coordinate processes across OS environments. These locks protect cooperating harness jobs, not unrelated applications or the external Ollama server. Never delete an active reservation to start another job.

Six local JSON files define the experiment:

| File | Purpose |
|---|---|
| `campaign.json` | Ordered offload/routing phases, serial jobs and automatic local reports |
| `inventory.json` | `raider-wsl` hardware configuration and physical host `raider` |
| `offload-case.json` | External Ollama service; reasoning, coding and math categories |
| `ollama-run.json` | Q8_0 artifact paths, placement settings and observed provenance |
| `nimble-case.json`, `tev1-case.json` | Decision routers, endpoints, repetitions and model digests |

Edit these ignored local copies. Their paths remain valid when copied together to this exact directory depth.

## 3. Plan before installation

```bash
"$PY" -m llm_eval plan --campaign "$CAMPAIGN" > "$LOCAL/plan-preview.json"
"$PY" - "$LOCAL/plan-preview.json" <<'PY'
import json,sys
plan=json.load(open(sys.argv[1]))
for job in plan['jobs']:
    print(job['job_id'], job['case_id'], job['hardware_config_id'], job['status'])
PY
```

Verified planner projection:

```text
offload-model-offloading-1-3fc97a7bd950 deepseek-r1-32b-q8 raider-wsl planned
routing-llm-routing-1-ac901abb4fcd ollama-nimble raider-wsl planned
routing-llm-routing-1-c6e41214da48 ollama-tev1 raider-wsl planned
```

`plan` normally prints the full resolved JSON; redirection above saves it. It makes no installation, download or inference calls. The job selection can be `planned` while model provenance still contains placeholders. Real execution requires the preparation below. The router jobs depend on the offload job, and all three share one physical-host reservation.

## 4. Set up the pinned runtime

```bash
"$PY" scripts/setup.py --campaign "$CAMPAIGN" --dry-run
"$PY" scripts/setup.py --campaign "$CAMPAIGN"
export PREFIX="$REPO/.platforms/$OS_ID/ollama"
"$PY" - "$PREFIX/state.json" <<'PY'
import json,sys
s=json.load(open(sys.argv[1]))
print(s['status'], s['backend_version'], s['executable'])
PY
```

The dry-run prints the resolved campaign plan. Illustrative successful setup and state projection:

```text
raider ollama succeeded
installed 0.35.1 /home/YOU/src/llm-eval/.platforms/windows-11-wsl2-ubuntu-26.04/ollama/runtime/bin/ollama
```

Setup deduplicates the runtime across all three jobs. It verifies the pinned Linux archive and creates an installation environment; it does not download the three models or start a service. The current catalog pins Ollama 0.35.1, which supports SystemOne. Read `.platforms/windows-11-wsl2-ubuntu-26.04/ollama.setup.log` on failure. Repeating the same setup reuses its state; a different plan requires a separate prefix instead of overwriting an existing installation.

## 5. Download and lock the offload model

Review the [base model](https://huggingface.co/deepseek-ai/DeepSeek-R1-Distill-Qwen-32B) and [GGUF publisher](https://huggingface.co/bartowski/DeepSeek-R1-Distill-Qwen-32B-GGUF), including their terms. Only the named Q8_0 file is selected. The repository is resolved to a commit once and the selection is retained for download retries.

```bash
export ARTIFACT_ROOT="$REPO/models/deepseek-r1-32b-q8"
export ARTIFACT_LOCK="$REPO/artifacts/deepseek-r1-32b-q8.lock.json"
export GGUF_NAME='DeepSeek-R1-Distill-Qwen-32B-Q8_0.gguf'
"$PY" - <<'PY'
import json,os,re,urllib.request
from pathlib import Path
p=Path(os.environ['LOCAL'])/'download-selection.json'
repo='bartowski/DeepSeek-R1-Distill-Qwen-32B-GGUF'
if p.exists():
    d=json.loads(p.read_text())
    assert d['source_repo']==repo and d['filename']==os.environ['GGUF_NAME']
else:
    with urllib.request.urlopen('https://huggingface.co/api/models/'+repo+'/revision/main',timeout=60) as r:
        revision=json.load(r)['sha']
    assert re.fullmatch(r'[0-9a-f]{40}',revision)
    d={'source_repo':repo,'source_revision':revision,'filename':os.environ['GGUF_NAME']}
    p.write_text(json.dumps(d,indent=2)+'\n')
print(d['source_revision'])
PY
"$PY" -m venv "$LOCAL/download-venv"
DOWNLOAD_PY="$LOCAL/download-venv/bin/python"
DOWNLOAD_PACKAGE="$("$PY" -c 'import json; print(json.load(open("catalog/installers.json"))["model_download_package"])')"
"$DOWNLOAD_PY" -m pip install "$DOWNLOAD_PACKAGE"
"$DOWNLOAD_PY" - <<'PY'
import json,os
from pathlib import Path
from huggingface_hub import hf_hub_download
d=json.loads((Path(os.environ['LOCAL'])/'download-selection.json').read_text())
print(hf_hub_download(repo_id=d['source_repo'],revision=d['source_revision'],
                     filename=d['filename'],local_dir=os.environ['ARTIFACT_ROOT']))
PY
QUANT_REVISION="$("$PY" -c 'import json,os; from pathlib import Path; print(json.loads((Path(os.environ["LOCAL"])/"download-selection.json").read_text())["source_revision"])')"
"$PY" -m llm_eval lock --root "$ARTIFACT_ROOT" \
    --source-repo bartowski/DeepSeek-R1-Distill-Qwen-32B-GGUF \
    --source-revision "$QUANT_REVISION" \
    --base-model deepseek-ai/DeepSeek-R1-Distill-Qwen-32B \
    --precision Q8_0 --output "$ARTIFACT_LOCK"
```

The lock command prints `Locked 1 files; <actual size> GiB weight artifacts`. Its SHA256 inventory identifies the selected representation. Keep only this model variant in that directory. Hidden downloader metadata is excluded from the lock. Allow storage for the original artifact, Ollama's imported copy, both routing models, the runtime and results. The download environment is separate so it does not change the campaign installation plan.

## 6. Start and populate one private Ollama service

Use the executable from installation state, not an unrelated system service. This guide uses port **11435**, with one loaded model and one active request. It deliberately leaves service lifecycle under your control so the offload and routing jobs can share it.

```bash
export OLLAMA="$("$PY" -c 'import json,os; from pathlib import Path; print(json.loads((Path(os.environ["PREFIX"])/"state.json").read_text())["executable"])')"
export API='http://127.0.0.1:11435'
"$PY" - <<'PY'
import socket
with socket.socket() as s:
    s.bind(('127.0.0.1',11435))
print('Port 11435 is available')
PY
export OLLAMA_HOST='127.0.0.1:11435'
export OLLAMA_MODELS="$PREFIX/ollama-models"
export OLLAMA_NO_CLOUD=1 OLLAMA_NUM_PARALLEL=1 OLLAMA_MAX_LOADED_MODELS=1
export CUDA_VISIBLE_DEVICES="$("$PY" - <<'PY'
import json,os
from pathlib import Path
h=json.loads((Path(os.environ['LOCAL'])/'host-inventory.json').read_text())
g=[x for x in h['gpus'] if x['name']=='NVIDIA GeForce RTX 5090 Laptop GPU']
assert len(g)==1, 'Expected one matching laptop GPU'
print(g[0]['index'])
PY
)"
env -u GH_TOKEN -u GITHUB_TOKEN -u LLM_EVAL_PUBLISH_TOKEN \
    nohup "$OLLAMA" serve > "$LOCAL/ollama.stdout.log" 2> "$LOCAL/ollama.stderr.log" &
export OLLAMA_PID=$!
"$PY" - <<'PY'
import json,os,time,urllib.request,psutil
from pathlib import Path
local=Path(os.environ['LOCAL']);process=psutil.Process(int(os.environ['OLLAMA_PID']))
(local/'service.json').write_text(json.dumps({'pid':process.pid,'created':process.create_time()},indent=2)+'\n')
for attempt in range(60):
    if not process.is_running() or process.status()==psutil.STATUS_ZOMBIE:
        raise SystemExit('Ollama exited; inspect ollama.stderr.log')
    try:
        with urllib.request.urlopen(os.environ['API']+'/api/version',timeout=2) as r:
            version=json.load(r)
        print(version);break
    except OSError:time.sleep(1)
else:raise SystemExit('Ollama readiness timed out; inspect service logs')
PY
"$PY" - <<'PY'
import json,os
from pathlib import Path
model=str(Path(os.environ['ARTIFACT_ROOT'])/os.environ['GGUF_NAME'])
text='FROM '+json.dumps(model)+'\nPARAMETER num_ctx 4096\nPARAMETER num_gpu 20\nPARAMETER num_thread 16\n'
(Path(os.environ['LOCAL'])/'Modelfile').write_text(text)
PY
"$OLLAMA" create llm-eval-deepseek-r1-32b-q8:locked -f "$LOCAL/Modelfile"
"$OLLAMA" pull nimble
"$OLLAMA" pull tev1
"$OLLAMA" cp nimble:latest llm-eval-nimble:locked
"$OLLAMA" cp tev1:latest llm-eval-tev1:locked
```

Expected readiness output contains the server's actual version, such as `{'version': '0.35.1'}`. Create/pull commands print their own progress. An occupied port is an error; inspect its owner rather than stopping arbitrary processes. No global Ollama service is installed by these commands. Model aliases can be overwritten, so record their digests and leave them unchanged during the study.

### Probe generation and record real observations

```bash
"$PY" - <<'PY'
import json,os,urllib.request
from pathlib import Path
body={'model':'llm-eval-deepseek-r1-32b-q8:locked','prompt':'Reply with OK.',
      'stream':False,'options':{'num_ctx':4096,'num_predict':16},'keep_alive':'5m'}
request=urllib.request.Request(os.environ['API']+'/api/generate',data=json.dumps(body).encode(),
                               headers={'Content-Type':'application/json'})
with urllib.request.urlopen(request,timeout=900) as r: result=json.load(r)
(Path(os.environ['LOCAL'])/'generation-preflight.json').write_text(json.dumps(result,indent=2)+'\n')
print('Generation probe saved; inspect output and placement before measuring')
PY
"$OLLAMA" ps
tail -n 60 "$LOCAL/ollama.stderr.log"
free -h
swapon --show
read -r -p 'Actual BIOS version: ' BIOS_OBS
read -r -p 'Actual power/fan profile and AC state: ' POWER_OBS
read -r -p 'Actual MUX/hybrid setting: ' MUX_OBS
read -r -p 'Observed GPU TGP/power limit, or unavailable: ' TGP_OBS
read -r -p 'Actual RAM speed, SSD/filesystem/free space/temperature: ' STORAGE_OBS
read -r -p 'Observed CPU/GPU placement, requested 20 layers/16 threads, and paging: ' PLACEMENT_OBS
export BIOS_OBS POWER_OBS MUX_OBS TGP_OBS STORAGE_OBS PLACEMENT_OBS
"$PY" - <<'PY'
import hashlib,json,os,urllib.request
from pathlib import Path
local=Path(os.environ['LOCAL']);api=os.environ['API']
def request(path,body=None):
    r=urllib.request.Request(api+path,data=json.dumps(body).encode() if body is not None else None,
                             headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(r,timeout=300) as response:return json.load(response)
def save(path,data):path.write_text(json.dumps(data,indent=2)+'\n')
config=json.loads((local/'ollama-run.json').read_text())
show=request('/api/show',{'model':config['served_model']})
assert show.get('template'), 'Active template missing; resolve before measuring'
save(local/'offload-model-info.json',show)
template=show['template'].encode('utf-8');(local/'active-template.txt').write_bytes(template)
selection=json.loads((local/'download-selection.json').read_text())
host=json.loads((local/'host-inventory.json').read_text())
config.update(artifact_root=os.environ['ARTIFACT_ROOT'],artifact_lock=os.environ['ARTIFACT_LOCK'],
              backend_version=request('/api/version')['version'],backend_pid=int(os.environ['OLLAMA_PID']),
              tokenizer_revision=selection['source_repo']+'@'+selection['source_revision']+' (embedded GGUF tokenizer)',
              chat_template_sha256=hashlib.sha256(template).hexdigest(),placement_notes=os.environ['PLACEMENT_OBS'])
config['hardware_attestation']={
    'bios':os.environ['BIOS_OBS'],'power_fan_ac':os.environ['POWER_OBS'],
    'mux_hybrid':os.environ['MUX_OBS'],'gpu_tgp':os.environ['TGP_OBS'],
    'ram_storage':os.environ['STORAGE_OBS'],'observed_host':host}
save(local/'ollama-run.json',config)
tags=request('/api/tags');save(local/'model-digests.json',tags)
for name in ['nimble','tev1']:
    path=local/(name+'-case.json');case=json.loads(path.read_text());router=case['parameters']['router']
    matches=[m for m in tags['models'] if m['name']==router['model']]
    assert len(matches)==1 and matches[0]['digest'], 'Missing router digest'
    router['model_revision']=matches[0]['digest'];save(path,case)
    body={'model':router['model'],'state':{'text':'Write a Python function to reverse a string.'},
          'questions':{'route':{'type':'choice','instructions':router['instructions'],'criteria':router['criteria']}}}
    decision=request('/v1/systemone',body);save(local/(name+'-preflight.json'),decision)
    print(name,decision['answers']['route']['type'],decision['answers']['route']['choice'])
PY
```

SystemOne should return type `choice` and a configured label (`coding`, `math`, `general`). The harness measures correctness later. The generation probe and these decisions are outside the measured suite. Record what actually happened; do not assume the requested layers, memory budget, or a successful HTTP response prove the desired placement or quality. If loading, paging or placement is unacceptable, adjust the deployment before creating a campaign.

The external service uses the imported Modelfile. Editing `launch.gpu_layers` in JSON alone does not change an already imported external model. Recreate/recheck the model, update provenance and plan a new campaign after such changes. The one-loaded-model setting causes replacement between offload and router jobs; load/eviction effects remain part of the observed timing policy.

## 7. Final plan and optional automatic publication

Local report generation is enabled by default. To have each experiment automatically push its report and open a GitHub PR, run this optional block **before** creating the campaign:

```bash
# OPTIONAL: skip this whole block to keep reporting local.
"$PY" - <<'PY'
import json,os
from pathlib import Path
p=Path(os.environ['CAMPAIGN']);c=json.loads(p.read_text())
c['reporting']['publish']['mode']='pull-request'
p.write_text(json.dumps(c,indent=2)+'\n')
PY
read -r -s -p 'GitHub token with contents/PR write permissions: ' GH_TOKEN
printf '\n'
export GH_TOKEN
```

Use a token allowed to push branches and create PRs in `asanderson/llm-eval`; it stays in the coordinator environment. A fork requires matching both `reporting.publish.repository` and Git `origin`. The private service was started without publication tokens, and measurement workers do not need them.

```bash
"$PY" -m llm_eval plan --campaign "$CAMPAIGN" > "$LOCAL/final-plan.json"
git status --short
```

The same three jobs should resolve, now with your actual input/config hashes. Preserve the clean checkout and every campaign input. A plan preview validates configuration; it is not hardware certification.

## 8. Run the combined campaign

For WSL, start this logger in a **separate Windows PowerShell terminal** immediately before the Bash run block. Keep it running through measurement; press Ctrl+C there only after the coordinator finishes. It observes the whole Windows host, not just WSL, and saves actual host paging counters where available.

```powershell
$ErrorActionPreference = 'Stop'
$Root = Join-Path $env:USERPROFILE '.cache\llm-eval'
$Stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$Evidence = Join-Path $Root "wsl-observations\$Stamp"
New-Item -ItemType Directory -Force $Evidence | Out-Null
[IO.File]::WriteAllText((Join-Path $Root 'active-wsl-observations.txt'), $Evidence, [Text.UTF8Encoding]::new($false))
wsl --version | Out-File (Join-Path $Evidence 'wsl-version.txt')
wsl --list --verbose | Out-File (Join-Path $Evidence 'wsl-distributions.txt')
Copy-Item (Join-Path $env:USERPROFILE '.wslconfig') $Evidence
Get-CimInstance Win32_BIOS | Select-Object SMBIOSBIOSVersion | ConvertTo-Json | Out-File (Join-Path $Evidence 'bios.json')
Get-CimInstance Win32_ComputerSystem | Select-Object TotalPhysicalMemory | ConvertTo-Json | Out-File (Join-Path $Evidence 'physical-memory.json')
Write-Host "Windows host observations: $Evidence"
while ($true) {
    $Os = Get-CimInstance Win32_OperatingSystem
    $Mem = Get-CimInstance Win32_PerfFormattedData_PerfOS_Memory -ErrorAction SilentlyContinue
    [pscustomobject]@{
        utc = (Get-Date).ToUniversalTime().ToString('o')
        visible_total_kib = $Os.TotalVisibleMemorySize
        free_physical_kib = $Os.FreePhysicalMemory
        pages_input_per_s = $Mem.PagesInputPersec
        pages_output_per_s = $Mem.PagesOutputPersec
    } | Export-Csv (Join-Path $Evidence 'windows-host-memory.csv') -Append -NoTypeInformation
    Start-Sleep -Seconds 2
}
```

The logger prints its evidence directory; individual samples go to CSV. Missing counters are not zeros. Now start the campaign in the original Ubuntu Bash terminal:

```bash
OUTPUT_ROOT="$REPO/results/$EXAMPLE_NAME-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$OUTPUT_ROOT"
printf '%s\n' "$OUTPUT_ROOT" > "$LOCAL/active-output-root.txt"
if "$PY" -u scripts/run.py --campaign "$CAMPAIGN" --output "$OUTPUT_ROOT"; then
    RUN_EXIT=0
else
    RUN_EXIT=$?
fi
printf 'Run exit: %s\n' "$RUN_EXIT"
export CAMPAIGN_DIR="$(find "$OUTPUT_ROOT" -mindepth 1 -maxdepth 1 -type d -name 'campaign-*' -print -quit)"
```

Illustrative successful output; use the actual printed directory, not this example ID:

```text
Campaign results: /home/YOU/src/llm-eval/results/raider-wsl-20261009T203000Z/campaign-20261009T203000Z-a1b2c3d4
Run exit: 0
```

`-u` flushes the initial path promptly. The foreground process stays busy without a token stream/progress bar. Jobs are serial on this one physical host. Reporting finalizes each experiment after its jobs finish when local measurements are idle.

Exit codes: `0` means evaluation and enabled reporting succeeded, `1` incomplete/failed work, `2` configuration/setup errors, and `130` cancellation. A wrong answer can be a successful request: interpret execution status separately from quality metrics.

## 9. Check status in a second Bash terminal

Open another terminal in the **same Ubuntu installation**. Change the clone path if you used another location:

```bash
cd "$HOME/src/llm-eval"
export REPO="$PWD" PY="$PWD/.venv/bin/python"
export LOCAL="$REPO/configs/local/raider-wsl"
OUTPUT_ROOT="$(cat "$LOCAL/active-output-root.txt")"
export CAMPAIGN_DIR="$(find "$OUTPUT_ROOT" -mindepth 1 -maxdepth 1 -type d -name 'campaign-*' -print -quit)"
"$PY" -m llm_eval status --campaign-dir "$CAMPAIGN_DIR"
"$PY" - <<'PY'
import json,os
from pathlib import Path
s=json.loads((Path(os.environ['CAMPAIGN_DIR'])/'campaign.json').read_text())
for name,job in s['jobs'].items():print(name,job['status'],len(job['attempts']))
print('Reports:',s['reports'])
PY
```

The CLI prints the full journal. An illustrative projection while offloading runs is:

```text
offload-model-offloading-1-3fc97a7bd950 running 1
routing-llm-routing-1-ac901abb4fcd planned 0
routing-llm-routing-1-c6e41214da48 planned 0
Reports: {}
```

After successful completion all three show `succeeded`, usually with one attempt each. Report states (`generated`, `published`, or `failed`) are recorded separately. This terminal reads state; do not launch a competing campaign or unrelated inference service on the laptop.

## 10. Resume, retry and cancel

After the original coordinator exits, resume its existing directory:

```bash
if "$PY" -m llm_eval resume --campaign-dir "$CAMPAIGN_DIR"; then
    printf '%s\n' 'Resume exit: 0'
else
    printf 'Resume exit: %s\n' "$?"
fi
"$PY" -m llm_eval status --campaign-dir "$CAMPAIGN_DIR"
```

`resume` is normally silent. A completed campaign prints only the added `Resume exit: 0` line before status, and completed jobs keep their attempt counts. Calling `run` again would create a new campaign.

For a recoverable failure with unchanged settings and the same running service, explicitly retry failed/cancelled jobs:

If the Windows host logger has stopped, restart the step 8 logger before resuming. Each logger invocation creates a new timestamped observation segment. Retain all segments and identify any gaps; do not claim continuous host coverage across unobserved intervals.

```bash
"$PY" -m llm_eval resume --campaign-dir "$CAMPAIGN_DIR" --retry-failed
```

Retries create new attempt directories. All raw attempts remain; summaries use the latest attempt of each job. Failed offloading blocks its dependent routing phase. `lost` means completion needs reconciliation, not permission to remove a live reservation or send duplicate requests.

To request cancellation from the monitoring terminal while the original coordinator runs:

```bash
"$PY" -m llm_eval cancel --campaign-dir "$CAMPAIGN_DIR"
printf 'Cancel request exit: %s\n' "$?"
```

The command itself is silent. Exit `0` acknowledges the request; wait for the original coordinator to finish cleanup before resuming. The external Ollama service stays alive, and a request may finish there after the worker exits. Confirm the service is idle before further measurements.

Do not change inputs, upgrade packages or `git pull` before resuming. This example records an external `backend_pid`: after reboot, WSL shutdown or service restart, record the new PID and observations and start a **new campaign** to avoid attributing telemetry to a stale/reused PID. Do not transplant a campaign directory between Windows, WSL and native Ubuntu and claim it is the same measured run.

## 11. Generate and inspect both reports

```bash
"$PY" -m llm_eval report --input "$CAMPAIGN_DIR"
```

This retries missing/failed finalization or reuses its completed receipts. Illustrative local-only output:

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

There are two experiment reports; the routing report contains both routers. Regenerate them individually and locate the output:

```bash
for experiment in offload-model-offloading-1 routing-llm-routing-1; do
    EXPERIMENT_DIR="$CAMPAIGN_DIR/experiments/$experiment"
    "$PY" scripts/report_experiment.py --experiment-dir "$EXPERIMENT_DIR"
    "$PY" - "$EXPERIMENT_DIR/report" <<'PY'
import csv,json,sys
from pathlib import Path
r=Path(sys.argv[1]);publication=json.loads((r/'publication.json').read_text())
d=r/'bundle'/publication['report_path']
print('Markdown:',d/'README.md')
print('Raw:',d/'raw/measurements.jsonl.gz')
print('Chart:',r/'bundle'/publication['chart_path']/'latency.png')
with (d/'summary.csv').open() as f:
    for row in csv.DictReader(f):
        print(row['job_id'],row['category'],row['requests'],row['successful_requests'],row['errors_or_missing'])
PY
done
```

The script prints `Experiment report: <actual experiment directory>/report`. A fully successful offload report has three category rows with nine measured requests per row. Routing has two category rows per router, with three requests each. Accuracy, quality and timings must be read from the actual files; the tiny suites do not establish a model ranking.

| Bundle artifact | Contents |
|---|---|
| `docs/results/<experiment>/<publication>/README.md` | Status, coverage, metrics, links and embedded PNG |
| `raw/measurements.jsonl.gz` | Sanitized requests, telemetry, metadata and attempt records; warmups retained |
| `summary.json`, `summary.csv` | Cohorts, quality/decision metrics, missing/error counts and successful-request timings |
| `benchmark-summary.json`, `benchmark-summary.csv` | Empty in this example; upstream benchmark score exports belong here |
| `manifest.json`, `resolved-config.json` | Provenance, hashes, export inventory and omitted fields |
| `diagrams/results/<experiment>/<publication>/latency.png` | Rendered chart |

Use a Markdown viewer to inspect the README and PNG at the printed paths. Original data remains under `experiments/<run>/jobs/<job>/<attempt>/`. Public exports omit known credential fields, private paths and retained prompt/answer bodies by default. Preserve original artifacts for reproduction and review the bundle before publishing.

### Retain Windows host observations with the WSL campaign

After the coordinator completes, stop the Windows logger with Ctrl+C. Back in the Ubuntu terminal, copy its closed files alongside the campaign:

```bash
WIN_PROFILE="$(powershell.exe -NoProfile -NonInteractive -Command '[Environment]::GetFolderPath("UserProfile")' | tr -d '\r')"
WIN_PROFILE_LINUX="$(wslpath -u "$WIN_PROFILE")"
EVIDENCE_WINDOWS="$(cat "$WIN_PROFILE_LINUX/.cache/llm-eval/active-wsl-observations.txt" | tr -d '\r')"
EVIDENCE_LINUX="$(wslpath -u "$EVIDENCE_WINDOWS")"
EVIDENCE_DEST="$CAMPAIGN_DIR/host-observations/$(basename "$EVIDENCE_LINUX")"
mkdir -p "$EVIDENCE_DEST"
cp -a "$EVIDENCE_LINUX/." "$EVIDENCE_DEST/"
```

Check that UTC sample timestamps cover this campaign and record any monitoring gaps. Guest telemetry and this host CSV describe different scopes. The current report generator **does not ingest or publish these sidecar files automatically**. Preserve them with the original results, and add reviewed copies plus an explanation to the results PR if you make WSL host-memory/paging claims. Review machine/path identifiers first. Automatic publication can create the initial PR, but cannot supply this additional analysis.

The pointer file selects the most recent logger segment. For earlier segments from a retry/resume, set `EVIDENCE_LINUX` to their recorded directories and repeat the destination/copy commands; distinct timestamped subdirectories preserve each segment.

## 12. Publish results PRs and stop the service

Automatic publication, if enabled before the run, already records PR URLs in the report receipts. Otherwise, preview and publish each local report explicitly:

```bash
for experiment in offload-model-offloading-1 routing-llm-routing-1; do
    "$PY" -m llm_eval publish-results --input "$CAMPAIGN_DIR/experiments/$experiment/report" --dry-run
done
read -r -s -p 'GitHub token with contents/PR write permissions: ' GH_TOKEN
printf '\n'
export GH_TOKEN
for experiment in offload-model-offloading-1 routing-llm-routing-1; do
    "$PY" -m llm_eval publish-results --input "$CAMPAIGN_DIR/experiments/$experiment/report"
done
unset GH_TOKEN
```

The dry-run shows `branch`, `bytes`, `files` and `dry_run: true`. Illustrative publication receipt:

```json
{
  "url": "https://github.com/asanderson/llm-eval/pull/<new-pr-number>",
  "branch": "results/model-offloading/<publication-id>",
  "commit": "<actual pushed commit>",
  "fingerprint": "<actual report fingerprint>",
  "status": "open"
}
```

Expect one PR per experiment, with raw and summarized data, provenance, a chart and results-index updates. Incomplete results open draft PRs; nothing auto-merges. Authentication/network failures preserve the bundle. Retry `publish-results` without rerunning models. Manual publication writes `report/publication-state.json`; the earlier campaign receipt may still say `generated`.

When all measurement/resume work is finished, stop only the service saved by this guide. The PID creation-time check prevents cleanup of an unrelated process that reused its PID:

```bash
"$PY" - <<'PY'
import json,os,psutil
from pathlib import Path
s=json.loads((Path(os.environ['LOCAL'])/'service.json').read_text())
try:p=psutil.Process(s['pid'])
except psutil.NoSuchProcess:raise SystemExit('Service already exited; inspect any remaining runners manually')
assert abs(p.create_time()-s['created'])<.01, 'PID reused; inspect manually'
owned=p.children(recursive=True)+[p]
for child in owned:
    try:child.terminate()
    except psutil.NoSuchProcess:pass
_,alive=psutil.wait_procs(owned,timeout=10)
for child in alive:
    try:child.kill()
    except psutil.NoSuchProcess:pass
print('Stopped the recorded service and its observed child processes')
PY
```

Keep the exact source revision, local configuration, model files/digests, artifact lock and original results. Compare OS runs only with matched model revisions, templates, placement, context, workloads and documented memory/cache conditions.

## Troubleshooting

| Symptom | Action |
|---|---|
| Setup failure | Read `${PREFIX}.setup.log`; inspect installation state, archive verification and prefix-plan conflicts. |
| Python version rejected | Use the explicit 3.12 interpreter for the harness and setup; preserve the system interpreter. |
| `blocked` before inference | Check OS identity, clean Git revision, GPU/telemetry, configured lock directory and completed provenance. |
| `failed` job | Read its `worker.log`, nested `metadata.json`, request errors and private Ollama stderr. |
| Wrong answers despite completed requests | Check actual template, model identity and output limits; transport success is separate from quality. |
| Changed-input/revision rejection on resume | Restore the exact inputs/revision or start a new campaign; preserve the integrity checks. |
| `lost`/reserved resource | Reconcile owned processes and completion before recovery; never delete an active lock. |
| Report/PR failure | Fix the reporting dependency, bundle-size, origin or authentication problem; regenerate/publish without rerunning successful jobs. |

See [campaign semantics](CAMPAIGNS.md), [publication](RESULTS.md), [hardware acceptance](VALIDATION.md), and the [native Windows walkthrough](WINDOWS_RAIDER_WALKTHROUGH.md).

## Platform references

- [Ubuntu 26.04 release notes](https://documentation.ubuntu.com/release-notes/26.04/)
- [uv Python installation](https://docs.astral.sh/uv/guides/install-python/) and [uv installation methods](https://docs.astral.sh/uv/getting-started/installation/)
- [Ollama on Linux](https://docs.ollama.com/linux); the repository's pinned installer is used here instead of a rolling install command
- [Native Windows walkthrough](WINDOWS_RAIDER_WALKTHROUGH.md) · [WSL2 walkthrough](WSL_RAIDER_WALKTHROUGH.md) · [Native Ubuntu walkthrough](UBUNTU_RAIDER_WALKTHROUGH.md)
