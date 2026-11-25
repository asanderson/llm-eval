"""Evidence that a measured run stayed inside GPU VRAM: pure parsing and the verdict rule.

Three sources, none of them a per-layer measurement: the device-wide VRAM counter read before the launch and sampled
during the run, the placement lines llama.cpp prints into the backend log (KoboldCpp and Ollama embed it), and what
Ollama reports about the model it holds. Every function takes plain values, so the rule is checked without a GPU."""
import re

MIN_GPU_WEIGHT_FRACTION = 0.8      # VRAM use must rise by this share of the weights; below 1 because the counter is device-wide and sampled
LOG_KEYS = ('layers_offloaded', 'layers_total', 'model_layers', 'model_loads', 'partial_loads', 'gpu_model_buffer_mib',
            'host_model_buffer_mib', 'gpu_kv_buffer_mib', 'cpu_kv_buffer_mib', 'gpu_compute_buffer_mib', 'device_free_mib_at_load')

# Matched anywhere in a line: the function-name prefix differs between llama.cpp versions and the engines that embed it.
OFFLOADED = re.compile(r'offloaded (\d+)/(\d+) layers to GPU')
BUFFER = re.compile(r'(\S+) (model|KV|compute) buffer size =\s*(\d+(?:\.\d+)?) MiB')
DEVICE = re.compile(r'using device (\S+) \(.*\) - (\d+) MiB free')
LAYERS = re.compile(r'\bn_layer\s*=\s*(\d+)')
GPU = re.compile(r'CUDA\d+')      # a numbered CUDA device; CPU, CPU_Mapped and CUDA_Host buffers are host memory


def parse_backend_log(text):
    """Placement facts from a llama.cpp-family backend log; a value is None when its line is absent.

    The values describe the last model load: the last layer line and the buffer lines after it (the whole log when no layer
    line was printed). Cache buffers are summed, because a model can have several caches. Model and compute buffers take the
    last line of each device, then the devices of a kind are summed. `layers_total` is the count the layer line prints,
    which is larger than the model's own `n_layer` in `model_layers`: the engine also counts the output layer, and for
    some architectures one layer more. `model_loads` counts the layer lines. `partial_loads` counts the loads among them
    that placed fewer layers than the line's total or a cache buffer on the CPU: a backend that reloaded the model served
    its earlier requests from the earlier load."""
    lines = text.splitlines()
    loads = [i for i, line in enumerate(lines) if OFFLOADED.search(line)]
    facts = dict.fromkeys(LOG_KEYS)
    if loads:
        partial = 0
        for start, end in zip(loads, [*loads[1:], len(lines)]):
            offloaded, total = (int(value) for value in OFFLOADED.search(lines[start]).groups())
            buffers = (BUFFER.search(line) for line in lines[start:end])
            partial += offloaded < total or any(m and m.group(2) == 'KV' and float(m.group(3)) > 0 and not GPU.fullmatch(m.group(1)) for m in buffers)
        facts.update(layers_offloaded=offloaded, layers_total=total, model_loads=len(loads), partial_loads=partial)
    caches, buffers = {}, {}
    for line in lines[loads[-1] if loads else 0:]:
        match = BUFFER.search(line)
        if match:
            name, kind, size = match.group(1), match.group(2), float(match.group(3))
            where = 'gpu' if GPU.fullmatch(name) else 'host'
            if kind == 'KV':
                caches[where] = caches.get(where, 0) + size
            else:
                buffers[(kind, where, name)] = size
    for key, kind, where in (('gpu_model_buffer_mib', 'model', 'gpu'), ('host_model_buffer_mib', 'model', 'host'),
                             ('gpu_compute_buffer_mib', 'compute', 'gpu')):
        sizes = [size for (k, w, _), size in buffers.items() if (k, w) == (kind, where)]
        facts[key] = sum(sizes) if sizes else None
    facts.update(gpu_kv_buffer_mib=caches.get('gpu'), cpu_kv_buffer_mib=caches.get('host'))
    for line in lines:
        device, layers = DEVICE.search(line), LAYERS.search(line)
        if device and GPU.fullmatch(device.group(1)):
            facts['device_free_mib_at_load'] = float(device.group(2))
        if layers:
            facts['model_layers'] = int(layers.group(1))
    return facts


def served_model_memory(payload, served_model):
    """`size` and `size_vram` in bytes that Ollama's /api/ps reports for the served model; None for what it does not report."""
    models = payload.get('models') if isinstance(payload, dict) else None
    names = (served_model, served_model + ':latest')      # Ollama adds the default tag to a name without one
    entry = next((m for m in models if isinstance(m, dict) and (m.get('name') in names or m.get('model') in names)), {}) \
        if isinstance(models, list) else {}
    return {key: entry[key] if type(entry.get(key)) is int else None for key in ('size', 'size_vram')}


def device(rows, gpu_name, index=0):
    """The GPU a run is judged on: the nvidia-smi row with the index the launch selects (`launch.gpu`, default 0), when it
    carries the profile's GPU name; None otherwise. The launch hands that index to the engine as its only visible device.
    The index is read as nvidia-smi's, which is bus order; CUDA can number unequal cards differently."""
    return next((row for row in rows if str(row.get('index')) == str(index) and gpu_name in (row.get('name') or '')), None)


def peak_used_mib(samples, index):
    """Highest sampled memory use of one device, or None when no sample read it. Device-wide: every process counts."""
    values = [g['used_mib'] for s in samples for g in s.get('gpus') or [] if g.get('index') == index and g.get('used_mib') is not None]
    return max(values) if values else None


def exceeds_free_vram(weight_bytes, total_mib, reserve_mib, baseline_used_mib):
    """True when the weights alone are larger than the VRAM that is free before the launch, after the profile reserve."""
    return weight_bytes / 2 ** 20 > total_mib - reserve_mib - baseline_used_mib


def placement(log, ps):
    """Where the backend says the model is: its layer and cache lines decide, else what Ollama reports, else unobserved.
    Any load of the run that left layers or cache on the CPU decides, not only the last one."""
    offloaded, total, cpu_cache = log['layers_offloaded'], log['layers_total'], log['cpu_kv_buffer_mib']
    line = offloaded is not None and total is not None
    if log['partial_loads'] or (line and offloaded < total) or cpu_cache:
        return 'layers_on_cpu'
    if line and total > 0 and offloaded == total:
        return 'all_layers_on_gpu'
    if not line and ps['size'] is not None and ps['size'] > 0 and ps['size_vram'] is not None and ps['size_vram'] >= 0:
        return 'reported_in_vram' if ps['size_vram'] >= ps['size'] else 'reported_partly_in_ram'
    return 'unobserved'


def verdict(weight_mib, total_mib, reserve_mib, baseline_used_mib, peak_used_mib, log, ps,
            min_gpu_weight_fraction=MIN_GPU_WEIGHT_FRACTION, require_layer_evidence=False):
    """Whether a completed run stayed inside VRAM, and the first reason it did not.

    Capacity: the sampled device-wide peak stayed at or under the device total minus the profile reserve (the rule of the
    legal serving-profile check). Placement: the backend did not report layers or cache on the CPU. Rise: memory use rose by
    at least the given share of the weights, so a run that fell back to the CPU does not pass. A run without any placement
    report passes unless layer evidence is required; a run without a GPU reading never passes."""
    where = placement(log, ps)
    observed = None not in (total_mib, baseline_used_mib, peak_used_mib)
    capacity_ok = peak_used_mib <= total_mib - reserve_mib if observed else None
    rise = peak_used_mib - baseline_used_mib if observed else None
    rise_ok = rise >= min_gpu_weight_fraction * weight_mib if observed else None
    if observed and not capacity_ok:
        reason = 'vram_reserve_exceeded'
    elif where in ('layers_on_cpu', 'reported_partly_in_ram'):
        reason = 'layers_on_cpu'
    elif not observed:
        reason = 'gpu_memory_unobserved'
    elif not rise_ok:
        reason = 'gpu_use_below_weights'
    elif where == 'unobserved' and require_layer_evidence:
        reason = 'placement_unobserved'
    else:
        reason = None
    return {'capacity_ok': capacity_ok, 'placement': where, 'gpu_rise_mib': rise, 'rise_ok': rise_ok, 'in_vram': reason is None, 'reason': reason}


def load_failure(log_text):
    """Narrow loader diagnostics only. An HTTP error or a small VRAM rise alone identifies no cause."""
    if re.search(r'unknown (?:model )?architecture|unsupported (?:model )?architecture|architecture\b[^\n]{0,80}\bnot supported', log_text, re.I):
        return 'unsupported_model_architecture'
    if re.search(r'(?:cuda|gpu)[^\n]{0,140}(?:out of memory|erroroutofmemory)|out of (?:device|gpu) memory', log_text, re.I):
        return 'gpu_out_of_memory'
    if re.search(r'(?:error loading|failed to load) (?:the )?model\b', log_text, re.I):
        return 'model_load_failed'
    return None


def cache_types(log_text):
    """Cache precision pairs reported by llama.cpp. Multiple types can coexist in a hybrid model."""
    return sorted({(k.lower(), v.lower()) for k, v in re.findall(
        r'\bK \(([\w]+)\):[^\n]*?\bV \(([\w]+)\):', log_text, re.I)})


def other_compute_memory(index, backend_pid):
    """One post-request snapshot of compute allocations outside the managed process tree, when attributable."""
    from llm_eval.common import command
    from llm_eval.telemetry import psutil
    if not psutil or not backend_pid:
        return None
    try:
        owned = {backend_pid, *(p.pid for p in psutil.Process(backend_pid).children(recursive=True))}
    except psutil.Error:
        return None
    data = command(['nvidia-smi', '-i', str(index), '--query-compute-apps=pid,used_gpu_memory',
                    '--format=csv,noheader,nounits'], timeout=3)
    if not data:
        return None
    try:
        rows = [tuple(int(s.strip()) for s in line.split(',')) for line in data.splitlines()]
        if not any(pid in owned for pid, _ in rows) or any(mib < 0 for _, mib in rows):
            return None
        return sum(mib for pid, mib in rows if pid not in owned)
    except ValueError:  # WDDM and WSL can report unavailable process allocations.
        return None
