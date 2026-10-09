# Combined campaign on the MSI Raider: native Ubuntu 26.04

This walkthrough installs the harness and a private Ollama runtime, prepares real models, then uses **plan → setup → run → status → resume → report** for a combined campaign. The physical machine is the **MSI Raider 18 HX AI, Core Ultra 9 285HX, RTX 5090 Laptop GPU with 24 GiB VRAM and 64 GiB system RAM**.

**Output provenance:** the three-job plan below was verified with the actual planner in a Linux development environment. Installation, GPU inference and successful-run transcripts for this laptop are **illustrative expected output**, not measurements. No accuracy, latency or memory-performance numbers are invented. Retain your actual terminal output and generated artifacts.

## What this example runs

| Phase | Experiment and mode | Cases | Workload |
|---|---|---|---|
| 1: `offload` | Model offloading / `category-smoke` | DeepSeek-R1-Distill-Qwen-32B, GGUF Q8_0, through Ollama | Reasoning, coding and mathematics: three tasks per category |
| 2: `routing` | LLM routing / `decision` | Nimble and Tev1 through Ollama's SystemOne API | Two labeled category decisions per router |

Each task has one warmup and three measured repetitions: 27 measured offload requests and six measured decisions per router if all requests complete. Warmups remain in raw data and are excluded from summaries. These small original workloads demonstrate the workflow; they do **not** produce a full LiveBench score. Decision mode checks the routing choice without generating a downstream answer. See the [routing guide](../experiments/llm-routing/README.md) for replay/live modes.

The selected Q8_0 artifact is approximately 34.8 decimal GB (32.4 GiB), exceeding the GPU's capacity. It is an offload candidate, not a demonstrated fit. Initial settings are 4,096 context tokens, 16 CPU threads, 20 GPU layers and a 22 GiB GPU planning budget. The RAM planning budget is 52 GiB, leaving an initial allowance for the OS and other allocations. Budgets are not hard process limits; confirm actual placement and paging before measuring.

All three jobs run serially on physical host `raider`, using **one external Ollama service at `127.0.0.1:11435`**. Routing waits for offloading. Increasing `max_parallel_jobs` cannot overlap isolated jobs on this same host. Separate machines can run in parallel through [campaign hardware configurations](CAMPAIGNS.md). The campaign does not start/stop this external service; the steps below do so explicitly.

## 0. Prepare native Ubuntu 26.04

Boot an installed **Ubuntu 26.04 LTS amd64** system directly on the laptop. A WSL guest uses the [WSL walkthrough](WSL_RAIDER_WALKTHROUGH.md). Install a supported NVIDIA driver using [Ubuntu's driver instructions](https://ubuntu.com/server/docs/how-to/graphics/install-nvidia-drivers/), including the appropriate open kernel module stack for this Blackwell GPU and any required Secure Boot enrollment. Reboot when the driver installation requests it. Do not mix an unrelated CUDA repository or runfile driver into that installation.

Verify the actual OS and GPU before installing the harness:

```bash
cat /etc/os-release
uname -r
nvidia-smi
export OS_ID='ubuntu-26.04-native'
export EXAMPLE_NAME='raider-ubuntu'
```

`/etc/os-release` must identify Ubuntu `26.04`; `nvidia-smi` must identify the RTX 5090 Laptop GPU. Driver/kernel versions and available memory depend on the installed system. Resolve driver errors first. The prebuilt Ollama recipe does not need a separate CUDA toolkit.

Use a writable Linux filesystem, preferably on the model SSD. Record the actual SSD and filesystem rather than inferring them from the hardware profile. Allow space for two copies of the offload weights, router downloads and reports. Inspect available disk space before downloading. This guide does not repartition disks or change firmware/power profiles.

If dual booting from Windows, finish or cancel its campaign and stop its private Ollama service first. Native Ubuntu and Windows are separate evaluation configurations; preserve each OS's checkout, results and runtime environment.

## 1. Install the harness with Python 3.12

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

The inventory command prints and saves JSON. Confirm `environment_kind` is `ubuntu-26.04-native`, `psutil_available` is `true`, and `gpus` contains `NVIDIA GeForce RTX 5090 Laptop GPU`. Counters, driver versions and AC state must come from the actual host. Unknown AC or sensor values remain unknown; confirm AC manually. The hardware profile describes the physical laptop, not proof of the current SSD, RAM speed or power configuration.

Native Ubuntu uses the default Linux reservation directory, `~/.cache/llm-eval/locks`, with `physical_host_id: raider`. Keep that identity/directory consistent for other local harness checkouts. A dual-boot Windows installation cannot run concurrently, but its campaign must be finished or stopped before rebooting. Do not reuse a WSL shared-lock placeholder here.

Six local JSON files define the experiment:

| File | Purpose |
|---|---|
| `campaign.json` | Ordered offload/routing phases, serial jobs and automatic local reports |
| `inventory.json` | `raider-ubuntu` hardware configuration and physical host `raider` |
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
offload-model-offloading-1-2f46b21a7865 deepseek-r1-32b-q8 raider-ubuntu planned
routing-llm-routing-1-750be8baacd3 ollama-nimble raider-ubuntu planned
routing-llm-routing-1-c3bc44c87e22 ollama-tev1 raider-ubuntu planned
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
installed 0.35.1 /home/YOU/src/llm-eval/.platforms/ubuntu-26.04-native/ollama/runtime/bin/ollama
```

Setup deduplicates the runtime across all three jobs. It verifies the pinned Linux archive and creates an installation environment; it does not download the three models or start a service. The current catalog pins Ollama 0.35.1, which supports SystemOne. Read `.platforms/ubuntu-26.04-native/ollama.setup.log` on failure. Repeating the same setup reuses its state; a different plan requires a separate prefix instead of overwriting an existing installation.

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

Run in the original Bash terminal after checking that the GPU and host are otherwise idle.

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
Campaign results: /home/YOU/src/llm-eval/results/raider-ubuntu-20261009T203000Z/campaign-20261009T203000Z-a1b2c3d4
Run exit: 0
```

`-u` flushes the initial path promptly. The foreground process stays busy without a token stream/progress bar. Jobs are serial on this one physical host. Reporting finalizes each experiment after its jobs finish when local measurements are idle.

Exit codes: `0` means evaluation and enabled reporting succeeded, `1` incomplete/failed work, `2` configuration/setup errors, and `130` cancellation. A wrong answer can be a successful request: interpret execution status separately from quality metrics.

## 9. Check status in a second Bash terminal

Open another terminal in the **same Ubuntu installation**. Change the clone path if you used another location:

```bash
cd "$HOME/src/llm-eval"
export REPO="$PWD" PY="$PWD/.venv/bin/python"
export LOCAL="$REPO/configs/local/raider-ubuntu"
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
offload-model-offloading-1-2f46b21a7865 running 1
routing-llm-routing-1-750be8baacd3 planned 0
routing-llm-routing-1-c3bc44c87e22 planned 0
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

For a matched-budget comparison with the WSL example, create a separate local configuration with `ram_budget_gib: 46` before planning a new campaign. The default native lane uses 52 GiB; label that difference when comparing results. Match actual model digests, driver/runtime versions where possible, placement and power conditions as well.

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
