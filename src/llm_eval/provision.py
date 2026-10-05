"""Reproducible user-local installers. Commands are argument arrays, never shell text."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request
import zipfile

from .common import digest, environment_kind, read_json, require_revision, sha256_file, write_json

OS_IDS = ('ubuntu-26.04-native', 'windows-11-native', 'windows-11-wsl2-ubuntu-26.04')


def python_in(folder, os_id):
    return str(Path(folder) / ('Scripts/python.exe' if os_id == 'windows-11-native' else 'bin/python'))


def invoke(argv, *, cwd=None, env=None, capture=False):
    return subprocess.run([str(a) for a in argv], cwd=cwd, env=env, check=True,
                          text=True, capture_output=capture, shell=False)


def https_download(url, sha256, destination, max_bytes=20 * 2**30):
    if urllib.parse.urlsplit(url).scheme != 'https' or not re.fullmatch(r'[0-9a-f]{64}', sha256):
        raise ValueError('Downloads require HTTPS and an exact SHA256')
    destination = Path(destination)
    if destination.exists():
        if sha256_file(destination) == sha256:
            return
        raise ValueError(f'Existing download hash mismatch: {destination}')
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=destination.name+'.', suffix='.partial', dir=destination.parent)
    os.close(descriptor)
    temp = Path(temporary)
    h, count = hashlib.sha256(), 0
    try:
        with urllib.request.urlopen(url, timeout=60) as response, temp.open('wb') as out:
            if urllib.parse.urlsplit(response.url).scheme != 'https':
                raise ValueError('Download redirected away from HTTPS')
            while block := response.read(8 * 1024 * 1024):
                count += len(block)
                if count > max_bytes:
                    raise ValueError('Download size limit exceeded')
                h.update(block)
                out.write(block)
        if h.hexdigest() != sha256:
            raise ValueError('Downloaded asset failed SHA256 verification')
        temp.replace(destination)
    finally:
        temp.unlink(missing_ok=True)


def extract_archive(archive, output):
    """Extract verified assets with path, link, special-file and expansion guards."""
    archive, output = Path(archive), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    def check(name):
        if '\\' in name or ':' in name or name.startswith('/'):
            raise ValueError('Unsafe archive path')
        p = (output / name).resolve()
        if not p.is_relative_to(output):
            raise ValueError('Archive path escapes destination')
    if archive.suffix == '.zip':
        with zipfile.ZipFile(archive) as z:
            if sum(i.file_size for i in z.infolist()) > 30 * 2**30:
                raise ValueError('Archive expansion limit exceeded')
            for i in z.infolist():
                check(i.filename)
                if stat.S_ISLNK(i.external_attr >> 16):
                    raise ValueError('ZIP symlinks are not accepted')
            z.extractall(output)
    else:
        import zstandard  # installed only in the setup environment used for Ollama
        with tempfile.TemporaryFile() as expanded, archive.open('rb') as compressed:
            with zstandard.ZstdDecompressor().stream_reader(compressed) as stream:
                total = 0
                while block := stream.read(8 * 1024 * 1024):
                    total += len(block)
                    if total > 30 * 2**30:
                        raise ValueError('Archive expansion limit exceeded')
                    expanded.write(block)
            expanded.seek(0)
            with tarfile.open(fileobj=expanded, mode='r:') as t:
                if not hasattr(tarfile, 'data_filter'):
                    raise ValueError('Update Python to a maintenance release with tarfile.data_filter')
                for member in t.getmembers():
                    check(member.name)
                t.extractall(output, filter='data')


def checkout(repository, revision, destination):
    require_revision(revision)
    if not repository.startswith('https://github.com/') or not repository.endswith('.git'):
        raise ValueError('Source recipes must use an HTTPS GitHub .git repository')
    destination = Path(destination)
    if destination.exists():
        if not (destination / '.git').exists():
            raise ValueError('Refusing to replace a non-repository source directory')
        head = invoke(['git', '-C', destination, 'rev-parse', 'HEAD'], capture=True).stdout.strip()
        dirty = invoke(['git', '-C', destination, 'status', '--porcelain', '--untracked-files=no'], capture=True).stdout.strip()
        if head.lower() != revision.lower() or dirty:
            raise ValueError('Existing source checkout differs from the requested clean revision; use another prefix')
        invoke(['git', '-C', destination, '-c', 'protocol.file.allow=never', 'submodule', 'update', '--init', '--recursive'])
        return
    invoke(['git', 'init', destination])
    invoke(['git', '-C', destination, 'remote', 'add', 'origin', repository])
    invoke(['git', '-C', destination, 'fetch', '--depth', '1', 'origin', revision])
    invoke(['git', '-C', destination, 'checkout', '--detach', 'FETCH_HEAD'])
    actual = invoke(['git', '-C', destination, 'rev-parse', 'HEAD'], capture=True).stdout.strip()
    if actual.lower() != revision.lower():
        raise ValueError('Checked-out source does not match requested revision')
    invoke(['git', '-C', destination, '-c', 'protocol.file.allow=never', 'submodule', 'update', '--init', '--recursive'])


def install_plan(root, platform, os_id, prefix, python=sys.executable, jobs=8, cuda_arch='120',
                 revision=None, packages=None, with_livebench=False):
    platforms = {p['id']: p for p in read_json(root / 'catalog/platforms.json')['platforms']}
    if platform not in platforms or os_id not in OS_IDS:
        raise ValueError('Unknown platform or OS')
    if platforms[platform]['os_support'][os_id] == 'unsupported':
        raise ValueError(f'{platform} is unsupported on {os_id}; use its Linux/WSL script')
    if not 1 <= jobs <= 24 or not re.fullmatch(r'[0-9]{2,3}', cuda_arch):
        raise ValueError('Use 1–24 build jobs and a numeric CUDA architecture (120 for this laptop)')
    catalog = read_json(root / 'catalog/installers.json')
    recipe = dict(catalog['platforms'][platform])
    if revision:
        if 'revision' not in recipe:
            raise ValueError('--revision applies only to source recipes')
        require_revision(revision)
        recipe['revision'] = revision
    if packages:
        if recipe['kind'] != 'pip' or any(not re.fullmatch(r'[A-Za-z0-9_.-]+==[A-Za-z0-9.+_-]+', p) for p in packages):
            raise ValueError('--package requires exact name==version pins for a Python recipe')
        recipe['packages'] = packages
    prefix = Path(prefix).resolve()
    return {'schema_version':1, 'platform':platform, 'os_id':os_id, 'prefix':str(prefix),
            'python':str(python), 'jobs':jobs, 'cuda_arch':cuda_arch, 'recipe':recipe,
            'with_livebench':with_livebench, 'livebench':catalog['livebench'] if with_livebench else None,
            'prerequisites':['Python 3.11–3.13', 'working NVIDIA host driver',
                             *(['Git', 'CMake', 'CUDA toolkit with sm_120 support', 'C++ compiler'] if recipe['kind'] in {'cmake','strata'} else [])],
            'qualification':'Installer recipe only; GPU/model compatibility must be measured.'}


def execute_install(plan, root):
    if environment_kind() != plan['os_id']:
        raise ValueError('Detected OS does not match selected profile; --dry-run can preview another OS')
    prefix, recipe = Path(plan['prefix']), plan['recipe']
    state_file = prefix / 'state.json'
    if state_file.exists():
        state = read_json(state_file)
        if state.get('plan_sha256') == digest(plan) and state.get('status') == 'installed':
            print(f'Already installed: {state_file}')
            return state_file
        raise ValueError('Prefix already contains another installation; choose a new --prefix')
    marker = prefix / 'installation-plan.json'
    if marker.exists() and read_json(marker) != plan:
        raise ValueError('Partial installation uses another plan; choose a new prefix')
    for binary in (['git','cmake','nvcc'] if recipe['kind'] in {'cmake','strata'} else []):
        if not shutil.which(binary):
            raise ValueError(f'Missing prerequisite: {binary}. See docs/WORKFLOWS.md; no drivers are auto-installed.')
    check = invoke([plan['python'],'-c','import sys; assert (3,11) <= sys.version_info[:2] <= (3,13), "Use Python 3.11–3.13 for backend environments"'],capture=True)
    prefix.mkdir(parents=True,exist_ok=True)
    write_json(marker,plan)
    env_dir = prefix / 'venv'
    if not env_dir.exists():
        invoke([plan['python'],'-m','venv',env_dir])
    py = python_in(env_dir,plan['os_id'])
    invoke([py,'-m','pip','install','--disable-pip-version-check',str(root)+'[telemetry]'])
    state = {'schema_version':1,'status':'installing','plan_sha256':digest(plan),'plan':plan,'python':py}
    source = prefix / 'source'
    env = os.environ.copy()
    env['PATH']=str(Path(py).parent)+os.pathsep+env.get('PATH','')
    env.update(CMAKE_BUILD_PARALLEL_LEVEL=str(plan['jobs']), CUDAARCHS=plan['cuda_arch'],
               CPUINFER_CPU_INSTRUCT='AVX2', CPUINFER_ENABLE_AMX='OFF', KT_RAWINT4_BACKEND='avx2', KT_KERNEL_CPU_VARIANT='avx2')
    try:
        kind = recipe['kind']
        if kind in {'cmake','strata'}:
            checkout(recipe['repository'],recipe['revision'],source)
            if kind == 'strata':
                invoke([py,'-m','pip','install','-r',source/'requirements.txt'],env=env)
            flag = '-DSTRATA_ENABLE_CUDA=ON' if kind == 'strata' else '-DGGML_CUDA=ON'
            argv=['cmake','-S',source,'-B',source/'build',flag,'-DCMAKE_BUILD_TYPE=Release',
                  '-DCMAKE_CUDA_ARCHITECTURES='+plan['cuda_arch']]
            if kind == 'strata': argv.append('-DSTRATA_PORTABLE=ON')
            invoke(argv,env=env)
            invoke(['cmake','--build',source/'build','--config','Release','-j',str(plan['jobs'])],env=env)
            name='strata' if kind=='strata' else 'llama-server'
            suffix='.exe' if plan['os_id']=='windows-11-native' else ''
            candidates=[source/'build/bin'/('Release' if suffix else '')/(name+suffix),source/'build/bin'/(name+suffix),source/'build'/('Release' if suffix else '')/(name+suffix)]
            exe=next((p for p in candidates if p.is_file()),None)
            if not exe: raise ValueError(f'Build succeeded but {name} was not found')
            state.update(executable=str(exe),source=str(source),backend_version=recipe['revision'])
        elif kind in {'archive','executable'}:
            asset=recipe['assets']['windows' if plan['os_id']=='windows-11-native' else 'linux']
            archive=prefix/'downloads'/asset['filename']
            https_download(asset['url'],asset['sha256'],archive)
            runtime=prefix/'runtime'
            if kind=='archive':
                invoke([py,'-m','pip','install','zstandard==0.25.0'])
                invoke([py,'-m','llm_eval.provision','extract',archive,runtime])
                candidates=[runtime/'ollama.exe',runtime/'bin/ollama']
                exe=next((p for p in candidates if p.is_file()),None)
                if not exe: raise ValueError('Ollama executable absent from verified archive')
            else:
                runtime.mkdir(exist_ok=True)
                exe=runtime/asset['filename']
                shutil.copyfile(archive,exe)
            if plan['os_id']!='windows-11-native':exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
            state.update(executable=str(exe),backend_version=recipe['version'],asset_sha256=asset['sha256'])
        else:
            if recipe.get('torch'):
                invoke([py,'-m','pip','install','torch=='+recipe['torch'],'--index-url',recipe['torch_index']],env=env)
            invoke([py,'-m','pip','install',*recipe['packages']],env=env)
            # CUDA build availability is checked before declaring a Python backend installed.
            invoke([py,'-c','import torch; assert torch.cuda.is_available(), "CUDA is unavailable"; print(torch.cuda.get_device_name(0)); print(torch.cuda.get_arch_list())'],env=env)
            if plan['platform']=='ktransformers':
                invoke([py,'-c','import kt_kernel; print(kt_kernel.__cpu_variant__); assert "avx2" in kt_kernel.__cpu_variant__.lower(), "Expected AVX2 backend"'],env=env)
            state['backend_version']=';'.join(recipe['packages'])
        if plan['with_livebench']:
            lb=prefix/'livebench-source'
            checkout(plan['livebench']['repository'],plan['livebench']['revision'],lb)
            lb_env=prefix/'livebench-venv'
            invoke([plan['python'],'-m','venv',lb_env])
            lb_py=python_in(lb_env,plan['os_id'])
            invoke([lb_py,'-m','pip','install',str(lb)])
            state.update(livebench_source=str(lb),livebench_python=lb_py,livebench_revision=plan['livebench']['revision'])
            (prefix/'livebench-pip-freeze.txt').write_text(invoke([lb_py,'-m','pip','freeze','--all'],capture=True).stdout,encoding='utf-8')
        (prefix/'pip-freeze.txt').write_text(invoke([py,'-m','pip','freeze','--all'],capture=True).stdout,encoding='utf-8')
        state['status']='installed'
        write_json(state_file,state)
        return state_file
    except BaseException:
        state['status']='failed'
        write_json(prefix/'failed-installation.json',state)
        raise


if __name__=='__main__':
    if len(sys.argv)!=4 or sys.argv[1]!='extract':raise SystemExit('Internal use: extract ARCHIVE DESTINATION')
    extract_archive(sys.argv[2],sys.argv[3])
