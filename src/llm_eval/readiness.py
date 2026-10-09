"""Local, selection-aware prerequisite checks with explicit installation consent.

Probes never install. Installers are argument arrays and run only after consent.
Readiness concerns tools/runtime dependencies, not model or benchmark acceptance.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, field
import io
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
from typing import Callable

from .common import digest, environment_kind, read_json, write_json
from .core.contracts import identifier
from .core.hardware import limits, profile
from .provision import OS_IDS, install_plan, python_in


def probe_command(argv, timeout=30):
    try:
        p = subprocess.run([str(x) for x in argv], capture_output=True, text=True,
                           errors='replace', timeout=timeout, shell=False)
        return p.returncode == 0, (p.stdout + p.stderr).strip()[-4000:]
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)


def python_probe(python, source):
    return probe_command([python, '-c', source])


def refresh_path():
    """Refresh only this process; never rewrite a shell profile or system PATH."""
    paths = []
    if os.name == 'nt':
        import winreg
        for hive, key in [(winreg.HKEY_LOCAL_MACHINE, r'SYSTEM\CurrentControlSet\Control\Session Manager\Environment'),
                          (winreg.HKEY_CURRENT_USER, r'Environment')]:
            try:
                with winreg.OpenKey(hive, key) as handle:
                    paths.extend(os.path.expandvars(winreg.QueryValueEx(handle, 'Path')[0]).split(os.pathsep))
            except OSError:
                pass
    else:
        paths += ['/usr/lib/wsl/lib', '/usr/local/cuda/bin']
    # Preserve activated compiler and virtual-environment precedence.
    paths = os.environ.get('PATH', '').split(os.pathsep) + paths
    os.environ['PATH'] = os.pathsep.join(dict.fromkeys(p for p in paths if p))


def apt_commands(packages):
    prefix = [] if hasattr(os, 'geteuid') and os.geteuid() == 0 else ['sudo']
    return [prefix + ['apt-get', 'update'],
            prefix + ['apt-get', 'install', '-y', '--no-install-recommends', *packages]]


def winget_commands(package, extra=()):
    return [['winget', 'install', '--id', package, '--exact', '--source', 'winget',
             '--accept-source-agreements', '--accept-package-agreements', *extra]]


def package_probe(packages):
    ok, detail = probe_command(['dpkg-query', '-W', '-f=${Package} ${Status}\n', *packages])
    lines = detail.splitlines()
    return ok and len(lines) == len(packages) and all(x.endswith('install ok installed') for x in lines), detail


@dataclass
class Check:
    id: str
    label: str
    probe: Callable
    commands: list = field(default_factory=list)
    requires: tuple = ()
    remedy: str = ''
    required: bool = True

    def inspect(self):
        try:
            ok, detail = self.probe()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            ok, detail = False, str(exc)
        return {'id': self.id, 'label': self.label, 'status': 'pass' if ok else 'missing',
                'required': self.required, 'detail': detail, 'install_commands': self.commands,
                'remedy': self.remedy}


def run_checks(checks, *, check_only=False, yes=False, input_fn=input, interactive=None):
    """Report all gaps, then offer each repair, then re-probe (including failures)."""
    interactive = sys.stdin.isatty() if interactive is None else interactive
    by_id = {c.id: c for c in checks}
    before = [c.inspect() for c in checks]
    for row in before:
        print(f"[{row['status'].upper()}] {row['id']}: {row['label']}")
        if row['detail']: print('  ' + row['detail'].replace('\n', '\n  '))
        if row['status'] != 'pass' and row['remedy']: print('  ' + row['remedy'])
    actions = []
    if not check_only:
        for check in checks:
            if check.inspect()['status'] == 'pass' or not check.commands:
                continue
            missing = [key for key in check.requires if by_id[key].inspect()['status'] != 'pass']
            if missing:
                actions.append({'id': check.id, 'status': 'blocked', 'dependencies': missing})
                print(f"[BLOCKED] {check.id}: needs {', '.join(missing)}")
                continue
            print('\nProposed installation for ' + check.label + ':')
            for command in check.commands: print('  ' + json.dumps(command))
            consent = yes
            if not consent and interactive:
                try: consent = input_fn('Install this now? [y/N] ').strip().lower() in {'y', 'yes'}
                except EOFError: consent = False
            if not consent:
                actions.append({'id': check.id, 'status': 'declined'})
                continue
            action = {'id': check.id, 'status': 'installed', 'commands': check.commands}
            for command in check.commands:
                try:
                    # Installers retain their progress, sudo/UAC prompts and diagnostics.
                    p = subprocess.run([str(x) for x in command], shell=False, check=False)
                    if p.returncode:
                        action.update(status='failed', exit_code=p.returncode)
                        break
                except OSError as exc:
                    action.update(status='failed', error=str(exc))
                    break
            refresh_path()
            if action['status'] == 'installed' and check.inspect()['status'] != 'pass':
                action['status'] = 'verification_failed'
            actions.append(action)
            print(f"[{action['status'].upper()}] {check.id}")
    after = [c.inspect() for c in checks]
    ready = all(r['status'] == 'pass' for r in after if r['required'])
    return {'ready': ready, 'before': before, 'checks': after, 'actions': actions}


def select(args, root):
    """Use the real campaign planner rather than duplicating its resolution rules."""
    chosen_os = args.os or environment_kind()
    hardware = args.hardware_profile
    runtimes = {}
    target = {}
    jobs = []
    if args.campaign:
        from .orchestration.planner import compile_campaign
        plan = compile_campaign(args.campaign, root)
        ids = sorted({j['hardware_config_id'] for j in plan['jobs']})
        selected = args.hardware_config or (ids[0] if len(ids) == 1 else None)
        if selected not in ids:
            raise ValueError('Select one --hardware-config from: ' + ', '.join(ids))
        jobs = [j for j in plan['jobs'] if j['hardware_config_id'] == selected]
        hw = jobs[0]['hardware']; target = jobs[0]['target']
        if target['transport'] != 'local':
            raise ValueError('Readiness runs on the test host. For SSH targets run it there with --platform/--os/--hardware-profile; it does not install remotely.')
        if args.os and args.os != hw['os_id']:
            raise ValueError('--os conflicts with the selected hardware configuration')
        chosen_os, hardware = hw['os_id'], hw['hardware_profile']
        for job in jobs:
            p = job['parameters']
            if p.get('synthetic'): continue
            deployments = [p['config']] if 'config' in p else [p.get('router', {})]
            if job['mode'] == 'live': deployments += list(p.get('candidates', {}).values())
            for d in deployments:
                if d.get('network', {}).get('kind') == 'hosted' or d.get('target_id'):
                    continue  # Dependencies belong to the remote deployment.
                name = d.get('platform') or ('ollama' if d.get('kind') == 'systemone' else None)
                if not name: continue
                prefix = Path(p['installation_state']).parent if p.get('installation_state') else root/'.platforms'/chosen_os/name
                key = (name, str(prefix))
                runtimes[key] = runtimes.get(key, False) or job['mode'] == 'livebench'
    else:
        for name in args.platform or ['ollama']:
            runtimes[(name, str(args.prefix or root/'.platforms'/chosen_os/name))] = args.with_livebench
    if args.lock_root: target = {**target, 'lock_root': str(args.lock_root)}
    if chosen_os not in OS_IDS: raise ValueError('Supported hosts: native Windows 11, native Ubuntu 26.04, and WSL2 Ubuntu 26.04')
    identifier(hardware)
    return {'os_id': chosen_os, 'hardware_profile': hardware, 'runtimes': runtimes, 'target': target,
            'needs_gpu': bool(runtimes) or any(not j['parameters'].get('synthetic') for j in jobs)}


def gpu_probe(hardware):
    ok, raw = probe_command(['nvidia-smi', '--query-gpu=name,memory.total,driver_version', '--format=csv,noheader,nounits'])
    if not ok: return False, raw
    for row in csv.reader(io.StringIO(raw)):
        if len(row) == 3 and row[0].strip() == hardware['gpu']['name']:
            return float(row[1]) >= hardware['gpu']['vram_gib'] * 1024 * .95, raw
    return False, 'Expected ' + hardware['gpu']['name'] + '; observed: ' + raw


def cuda_probe(arch):
    ok, text = probe_command(['nvcc', '--list-gpu-code'])
    return ok and 'sm_' + arch in text.split(), text or 'nvcc absent or cannot list GPU code targets'


def cuda_linux_install():
    # Only toolkit packages from an already configured repository. Never CUDA
    # driver metapackages (particularly unsafe inside WSL).
    ok, names = probe_command(['apt-cache', 'pkgnames', 'cuda-toolkit-'])
    if not ok: return []
    choices = [n for n in names.splitlines() if re.fullmatch(r'cuda-toolkit-\d+-\d+', n)]
    choices.sort(key=lambda n: tuple(map(int, n.split('-')[-2:])), reverse=True)
    for name in choices:
        ok, policy = probe_command(['apt-cache', 'policy', name])
        if ok and re.search(r'Candidate:\s+(?!\(none\))\S+', policy): return apt_commands([name])
    return []


def expected_runtime_plan(root, selection, name, prefix, livebench, py):
    bounds = limits(selection, root)
    expected = install_plan(root, name, selection['os_id'], prefix, python=py,
                            jobs=min(8, bounds['threads']), hardware_profile=selection['hardware_profile'],
                            with_livebench=livebench)
    # setup.py adds these defaults to the provisioner plan before hashing it.
    expected.update(selected_models=['qwen38-flash-next-strata' if name == 'strata' else 'llama33-70b'],
                    selected_categories=[c['id'] for c in read_json(root/'catalog/benchmarks.json')['categories']],
                    download_spec=None, grading_image_tag=None)
    return expected


def runtime_probe(root, selection, name, prefix, livebench, py):
    state_file = prefix/'state.json'
    if not state_file.is_file(): return False, 'Missing ' + str(state_file)
    state = read_json(state_file)
    expected = expected_runtime_plan(root, selection, name, prefix, livebench, py)
    if state.get('status') != 'installed' or state.get('plan_sha256') != digest(expected):
        return False, 'Installation state differs from the requested pinned plan; use a new prefix or the original setup options.'
    backend_py = state.get('python', '')
    ok, detail = probe_command([backend_py, '-m', 'pip', 'check'])
    if not ok: return False, detail
    recipe = expected['recipe']
    pins = recipe.get('packages', []) + (['torch==' + recipe['torch']] if recipe.get('torch') else [])
    if recipe['kind'] == 'archive': pins += read_json(root/'catalog/installers.json')['archive_packages']
    code = 'import importlib.metadata as m\nimport psutil\n'
    for pin in pins:
        package, version = pin.split('==')
        # PEP 440 ==2.9.1 accepts the CUDA wheel's 2.9.1+cu128 local label.
        code += f'v=m.version({package!r}); assert v=={version!r} or ("+" not in {version!r} and v.split("+")[0]=={version!r}), {pin!r}\n'
    if recipe['kind'] == 'pip':
        code += 'import torch\nassert torch.cuda.is_available(), "CUDA unavailable in backend environment"\n'
        code += 'print(torch.cuda.get_device_name(0)); print(torch.cuda.get_arch_list())\n'
        code += 'assert (torch.ones(1,device="cuda")+1).sum().item()==2; torch.cuda.synchronize()\n'
        modules = {'accelerate': ['transformers', 'accelerate', 'sentencepiece'],
                   'airllm': ['airllm', 'transformers', 'accelerate', 'sentencepiece'],
                   'vllm': ['vllm'], 'ktransformers': ['kt_kernel', 'sglang']}
        code += '\n'.join('import ' + m for m in modules[name]) + '\n'
        if name == 'ktransformers': code += 'assert "avx2" in kt_kernel.__cpu_variant__.lower()\n'
    ok, detail = python_probe(backend_py, code)
    if not ok: return False, detail
    if state.get('executable'):
        exe = Path(state['executable'])
        if not exe.is_file(): return False, 'Runtime executable missing: ' + str(exe)
        if name == 'ollama':
            ok, detail = probe_command([exe, '--version'])
            if not ok or recipe['version'] not in detail: return False, detail
        else:
            ok, detail = probe_command([exe, '--version' if name in {'llama.cpp', 'ik_llama.cpp'} else '--help'])
            if not ok: return False, detail
            if os.name != 'nt':
                ok, detail = probe_command(['ldd', exe])
                if not ok or 'not found' in detail: return False, detail
    elif recipe['kind'] != 'pip':
        return False, 'Installed state has no runtime executable'
    if livebench:
        if state.get('livebench_revision') != expected['livebench']['revision']:
            return False, 'Pinned LiveBench checkout missing'
        ok, detail = probe_command([state.get('livebench_python', ''), '-m', 'pip', 'check'])
        if not ok: return False, detail
    return True, 'Pinned runtime, Python dependency consistency and executable/library probes passed'


def build_checks(root, selection):
    os_id = selection['os_id']; windows = os_id == 'windows-11-native'
    py = python_in(root/'.venv', os_id)
    catalog = read_json(root/'catalog/installers.json')
    bounds = limits(selection, root); hardware = profile(selection, root)
    checks = []
    def add(key, label, probe, commands=(), requires=(), remedy='', required=True):
        checks.append(Check(key, label, probe, list(commands), tuple(requires), remedy, required))
    add('os', 'Selected OS matches this host', lambda: (environment_kind() == os_id, environment_kind()))
    add('architecture', 'x86-64 host and 64-bit Python', lambda: (platform.machine().lower() in {'amd64', 'x86_64'} and sys.maxsize > 2**32, platform.machine()))
    add('python', 'Python 3.11-3.13 with venv, pip and TLS', lambda: python_probe(sys.executable,
        'import sys,venv,ensurepip,ssl,tarfile; assert (3,11)<=sys.version_info[:2]<=(3,13); assert hasattr(tarfile,"data_filter"); print(sys.version)'),
        remedy='Use scripts/readiness.ps1 or bash scripts/readiness.sh to bootstrap a compatible Python.')
    manager = 'winget' if windows else 'apt-get'
    # The package manager is optional when all selected dependencies are present.
    add('package-manager', manager, lambda: probe_command([manager, '--version']), required=False,
        remedy='Install/repair Windows App Installer (winget).' if windows else 'Use Ubuntu apt; sudo rights are needed for missing system packages.')
    def system(key, label, command, apt=(), winget=None, extra=()):
        commands = winget_commands(winget, extra) if windows and winget else apt_commands(list(apt)) if not windows and apt else []
        add(key, label, lambda: probe_command(command), commands, ('os', 'architecture', 'package-manager'))
    system('git', 'Git', ['git', '--version'], ['git'], 'Git.Git')
    if windows:
        system('powershell', 'PowerShell 7.4 or newer', ['pwsh', '-NoProfile', '-NonInteractive', '-Command',
               'if ($PSVersionTable.PSVersion -lt [version]"7.4") { exit 1 }; $PSVersionTable.PSVersion.ToString()'], winget='Microsoft.PowerShell')
        add('vc-runtime', 'Visual C++ x64 runtime', lambda: python_probe(sys.executable,
            'import ctypes; ctypes.WinDLL("vcruntime140.dll"); ctypes.WinDLL("msvcp140.dll"); print("VC runtime loadable")'),
            winget_commands('Microsoft.VCRedist.2015+.x64'), ('os', 'architecture', 'package-manager'))
    else:
        packages = ['ca-certificates', 'curl', 'libgomp1']
        add('system-libraries', 'TLS certificates, curl and OpenMP runtime', lambda p=tuple(packages): package_probe(p),
            apt_commands(packages), ('os', 'architecture', 'package-manager'))
    venv = root/'.venv'
    harness_commands = []
    if not venv.exists(): harness_commands.append([sys.executable, '-m', 'venv', str(venv)])
    if not venv.exists() or (venv/'pyvenv.cfg').is_file():
        harness_commands.append([py, '-m', 'pip', 'install', '-e', str(root)+'[telemetry,reporting]'])
    def harness_probe():
        ok, detail = python_probe(py, 'import sys,llm_eval,psutil,matplotlib,ssl; import importlib.metadata as m; from packaging.version import Version as V; '
            'assert (3,11)<=sys.version_info[:2]<=(3,13); '
            'assert m.version("llm-eval-lab")==llm_eval.__version__; '
            'assert V("6")<=V(psutil.__version__)<V("8"); assert V("3.8")<=V(matplotlib.__version__)<V("4"); '
            'print(sys.version); print(llm_eval.__version__)')
        return probe_command([py, '-m', 'pip', 'check']) if ok else (ok, detail)
    add('harness', 'Local harness, telemetry and report libraries', harness_probe, harness_commands,
        ('os', 'architecture', 'python'), 'A conflicting/broken .venv is not deleted; preserve it and choose a clean checkout.')
    if selection['runtimes']:
        pin = catalog['model_download_package']; package, version = pin.split('==')
        add('model-downloader', pin, lambda: python_probe(py,
            f'import huggingface_hub; import importlib.metadata as m; assert m.version({package!r})=={version!r}; print(m.version({package!r}))'),
            [[py, '-m', 'pip', 'install', pin]], ('harness',))
    if selection['needs_gpu']:
        remedy = 'Install/repair the NVIDIA Windows host driver; never install a Linux GPU driver in WSL.' if 'wsl2' in os_id else 'Install/repair the NVIDIA driver for this OS, then reboot if requested and rerun readiness.'
        add('gpu', 'NVIDIA driver, configured GPU name and VRAM', lambda: gpu_probe(hardware), remedy=remedy)
        minimum = bounds['ram_budget_gib'] if 'wsl2' in os_id else hardware['ram']['installed_gib'] * .95
        add('ram', 'Memory visible to the selected OS', lambda: python_probe(py,
            f'import psutil; n=psutil.virtual_memory().total/2**30; print(n,"GiB visible"); assert n>={minimum!r}, "Insufficient visible RAM for profile/budget"'),
            remedy='Check hardware/profile or the WSL guest memory cap; this is not a model-fit test.')
    if 'wsl2' in os_id:
        lock = selection['target'].get('lock_root', '')
        def lock_probe():
            p = Path(lock)
            valid = bool(lock) and 'REPLACE' not in lock and p.is_absolute() and p.is_dir() and os.access(p, os.W_OK)
            return valid, str(p) if valid else 'Set a real writable Windows-shared lock_root in the local inventory, or --lock-root for a standalone check.'
        add('wsl-lock', 'Windows/WSL shared reservation directory', lock_probe,
            remedy='Use the same physical directory and physical_host_id in Windows and WSL. See docs/WSL_RAIDER_WALKTHROUGH.md.')
        add('wsl-storage', 'Linux filesystem for model/runtime work', lambda: (not str(root).startswith('/mnt/'), str(root)),
            remedy='Prefer a clone under Linux home; inspect actual mount and backing-volume free space.', required=False)
    needs_build = any(catalog['platforms'][n]['kind'] in {'cmake', 'strata'} for n, _ in selection['runtimes'])
    if needs_build:
        system('cmake', 'CMake', ['cmake', '--version'], ['cmake'], 'Kitware.CMake')
        if windows:
            # CMake Visual Studio generators discover an installed toolchain without
            # cl.exe being on PATH; vswhere verifies the x64 C++ component.
            vswhere = Path(os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)'))/'Microsoft Visual Studio/Installer/vswhere.exe'
            def compiler_probe():
                ok, out = probe_command([vswhere, '-products', '*', '-requires', 'Microsoft.VisualStudio.Component.VC.Tools.x86.x64', '-property', 'installationPath'])
                return ok and bool(out), out
            add('compiler', 'MSVC x64 C++ build tools', compiler_probe,
                winget_commands('Microsoft.VisualStudio.2022.BuildTools', ['--override', '--wait --passive --norestart --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended']),
                ('os', 'architecture', 'package-manager'))
        else:
            packages = ['build-essential', 'ninja-build', 'pkg-config', 'libcurl4-openssl-dev']
            add('compiler', 'C++ compiler, build tools and curl development files', lambda p=tuple(packages): package_probe(p),
                apt_commands(packages), ('os', 'architecture', 'package-manager'))
        add('cuda', 'CUDA toolkit with sm_' + bounds['cuda_arch'], lambda: cuda_probe(bounds['cuda_arch']),
            winget_commands('Nvidia.CUDA', ['--interactive']) if windows else cuda_linux_install(),
            ('os', 'architecture', 'package-manager', 'compiler'),
            'Use an appropriate toolkit from https://developer.nvidia.com/cuda-downloads. Linux auto-install requires a configured NVIDIA apt repository; WSL uses toolkit-only packages. Windows opens the CUDA component-selection installer. Rerun after PATH/reboot changes.')
    if any(n in {'vllm', 'ktransformers'} for n, _ in selection['runtimes']) and not windows:
        packages = ['libnuma1', 'libnuma-dev', 'numactl', 'build-essential']
        add('numa-build', 'NUMA libraries and native extension compiler', lambda p=tuple(packages): package_probe(p),
            apt_commands(packages), ('os', 'architecture', 'package-manager'))
    livebench = any(selection['runtimes'].values())
    if livebench:
        commands = winget_commands('Docker.DockerDesktop') if windows else apt_commands(['docker.io']) if 'wsl2' not in os_id else []
        add('docker-cli', 'Docker CLI for LiveBench grading', lambda: probe_command(['docker', '--version']), commands,
            ('os', 'architecture', 'package-manager'), 'For WSL enable Docker Desktop integration for this distribution.')
        add('docker-daemon', 'Accessible Docker daemon', lambda: probe_command(['docker', 'info', '--format', '{{.ServerVersion}}']),
            remedy='Start Docker Desktop/Engine and configure access, then rerun; readiness does not change group privileges.')
    for index, ((name, folder), lb) in enumerate(selection['runtimes'].items()):
        prefix = Path(folder).resolve(); kind = catalog['platforms'][name]['kind']
        support = {p['id']: p for p in read_json(root/'catalog/platforms.json')['platforms']}[name]['os_support'][os_id]
        if support == 'unsupported':
            add('runtime-'+str(index), name, lambda: (False, 'Unsupported on ' + os_id), remedy='Select a supported OS/platform; no install offered.')
            continue
        commands = []
        if not (prefix/'state.json').exists():
            cmd = [py, str(root/'scripts/setup.py'), '--non-interactive', '--platform', name, '--os', os_id,
                   '--prefix', str(prefix), '--hardware-profile', selection['hardware_profile'], '--jobs', str(min(8, bounds['threads']))]
            if lb: cmd.append('--with-livebench')
            commands = [cmd]
        else:
            # Repair missing Python dependencies only in the exact installed
            # plan's environment. Never rewrite state or replace an engine.
            try:
                state = read_json(prefix/'state.json')
                expected = expected_runtime_plan(root, selection, name, prefix, lb, py)
                backend_py = state.get('python', '')
                if state.get('status') == 'installed' and state.get('plan_sha256') == digest(expected) and Path(backend_py).is_file():
                    recipe = expected['recipe']
                    commands = [[backend_py, '-m', 'pip', 'install', str(root)+'[telemetry]']]
                    if recipe.get('torch'):
                        commands.append([backend_py, '-m', 'pip', 'install', 'torch=='+recipe['torch'], '--index-url', recipe['torch_index']])
                    pins = recipe.get('packages', []) + (catalog['archive_packages'] if kind == 'archive' else [])
                    if pins: commands.append([backend_py, '-m', 'pip', 'install', *pins])
                    if kind == 'strata': commands.append([backend_py, '-m', 'pip', 'install', '-r', str(prefix/'source/requirements.txt')])
                    if lb:
                        lb_py = state.get('livebench_python', '')
                        if Path(lb_py).is_file():
                            commands.append([lb_py, '-m', 'pip', 'install', str(prefix/'livebench-source')])
                    freezes = [(backend_py, prefix/'pip-freeze.txt')]
                    if lb and Path(state.get('livebench_python', '')).is_file():
                        freezes.append((state['livebench_python'], prefix/'livebench-pip-freeze.txt'))
                    for env_py, freeze in freezes:
                        commands.append([env_py, '-c', 'import subprocess,sys; from pathlib import Path; '
                            f'Path({str(freeze)!r}).write_text(subprocess.check_output([sys.executable,"-m","pip","freeze","--all"],text=True),encoding="utf-8")'])
            except (OSError, ValueError, KeyError):
                commands = []
        required = ['os', 'architecture', 'python', 'git', 'harness', 'gpu']
        required += ['vc-runtime'] if windows else ['system-libraries']
        if kind in {'cmake', 'strata'}: required += ['cmake', 'compiler', 'cuda']
        if name in {'vllm', 'ktransformers'} and not windows: required += ['numa-build']
        add('runtime-'+str(index), name + ' pinned runtime at ' + str(prefix),
            lambda n=name, p=prefix, l=lb: runtime_probe(root, selection, n, p, l, py), commands, required,
            'Matching environments can repair Python dependencies after consent. Conflicting state or missing binaries require a new prefix/checkout; see docs/READINESS.md.')
    return checks


def parser():
    p = argparse.ArgumentParser(description='Check local hardware prerequisites and offer missing dependency installations (default answer: no).')
    p.add_argument('--project-root', type=Path, default=Path(__file__).resolve().parents[2])
    p.add_argument('--campaign', type=Path)
    p.add_argument('--hardware-config', help='One local hardware configuration from the campaign')
    p.add_argument('--platform', action='append', help='Repeat for multiple engines; defaults to ollama without a campaign')
    p.add_argument('--os', choices=OS_IDS)
    p.add_argument('--hardware-profile', default='msi-raider-18-hx-ai')
    p.add_argument('--prefix', type=Path, help='One standalone runtime installation prefix')
    p.add_argument('--lock-root', type=Path, help='Existing shared Windows/WSL reservation directory')
    p.add_argument('--with-livebench', action='store_true')
    mode = p.add_mutually_exclusive_group()
    mode.add_argument('--check-only', action='store_true', help='No installation or prompts')
    mode.add_argument('--yes', action='store_true', help='Consent to displayed supported installs, including package agreements; OS prompts can still appear')
    p.add_argument('--json-output', type=Path, help='Save local report with before/after checks and install outcomes')
    return p


def main(argv=None):
    args = parser().parse_args(argv); root = args.project_root.resolve()
    if args.campaign and (args.platform or args.prefix or args.with_livebench):
        parser().error('--campaign derives platform/prefix/LiveBench settings; do not combine these overrides')
    if args.prefix and len(args.platform or ['ollama']) != 1: parser().error('--prefix requires one platform')
    if args.hardware_config and not args.campaign: parser().error('--hardware-config requires --campaign')
    if args.lock_root and args.campaign: parser().error('Set lock_root in the campaign inventory; --lock-root is only for standalone checks')
    refresh_path()
    bootstrap = None
    try:
        # Campaign resolution needs Git. Check/offer it before asking the real
        # planner to resolve the remaining prerequisites (e.g. a downloaded ZIP).
        if args.campaign and not shutil.which('git'):
            actual = environment_kind()
            if actual not in OS_IDS: raise ValueError('Unsupported host; no installations performed')
            commands = winget_commands('Git.Git') if actual == 'windows-11-native' else apt_commands(['git'])
            bootstrap = run_checks([Check('git', 'Git needed to resolve campaign', lambda: probe_command(['git', '--version']), commands)],
                                   check_only=args.check_only, yes=args.yes)
            if not bootstrap['ready']:
                if args.json_output: write_json(args.json_output, {'schema_version': 1, 'scope': 'campaign-resolution', **bootstrap})
                print('NOT READY: install Git, then rerun to resolve the campaign dependencies.'); return 1
        selection = select(args, root)
        # Validate catalog names before constructing any installation commands.
        known = read_json(root/'catalog/installers.json')['platforms']
        if any(n not in known for n, _ in selection['runtimes']): raise ValueError('Unknown platform selection')
        checks = build_checks(root, selection)
        # A mismatch must never install software for another OS/architecture.
        compatible = all(c.inspect()['status'] == 'pass' for c in checks if c.id in {'os', 'architecture', 'python'})
        result = run_checks(checks, check_only=args.check_only or not compatible, yes=args.yes)
        result.update(schema_version=1, scope='local-tools-and-runtime-dependencies', os_id=selection['os_id'],
                      hardware_profile=selection['hardware_profile'], python=sys.executable,
                      note='Does not certify models, services, benchmark data, credentials, GPU performance or memory fit.')
        if bootstrap: result['bootstrap'] = bootstrap
        if args.json_output: write_json(args.json_output, result)
        missing = [r['id'] for r in result['checks'] if r['required'] and r['status'] != 'pass']
        print('\nREADY: selected tools and runtime dependencies passed.' if result['ready'] else '\nNOT READY: ' + ', '.join(missing))
        print('Harness Python: ' + python_in(root/'.venv', selection['os_id']))
        if args.json_output: print('Readiness report: ' + str(args.json_output))
        return 0 if result['ready'] else 1
    except KeyboardInterrupt:
        print('\nReadiness cancelled; completed installations remain. Rerun to inspect actual state.'); return 130
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print('Readiness configuration error: ' + str(exc), file=sys.stderr); return 2
