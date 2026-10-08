"""Hardware limits are profile data, never laptop constants in shared code."""
from pathlib import Path
from llm_eval.common import read_json
from .contracts import identifier


def profile(config,root=None):
    root=Path(root or Path(__file__).resolve().parents[3])
    name=identifier(config.get('hardware_profile','msi-raider-18-hx-ai'))
    return read_json(root/'configs/hardware'/(name+'.json'))


def limits(config,root=None):
    p=profile(config,root)
    overrides=p.get('os_limits',{}).get(config.get('os_id'),{})
    return {'threads':p['cpu']['threads'],'gpu_total_gib':p['gpu']['vram_gib'],
            'gpu_budget_gib':p['gpu']['vram_gib']-p['gpu'].get('initial_reserve_gib',0),
            'ram_budget_gib':overrides.get('ram_budget_gib',p['ram']['installed_gib']-p.get('host_reserve_gib',12)),
            'cuda_arch':p['gpu'].get('compute_capability','').replace('.','')}
