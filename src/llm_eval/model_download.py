"""Optional, explicitly selected, revision-pinned model downloads in a separate environment."""
from pathlib import Path
import re
import sys

from .artifacts import lock_artifact
from .common import read_json, require_revision, write_json
from .provision import invoke, python_in


def validate_download_spec(root,spec,selected=None):
    models={m['id']:m for m in read_json(Path(root)/'catalog/models.json')['models']}
    entries=read_json(spec)['models']
    if not entries:raise ValueError('Download manifest has no models')
    seen=set();targets=[]
    for entry in entries:
        model=entry['model_id']
        if model not in models or model in seen or (selected is not None and model not in selected):
            raise ValueError('Download model must be a unique selected catalog ID')
        seen.add(model)
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',entry['source_repo']):
            raise ValueError('Invalid Hugging Face repository ID')
        require_revision(entry['source_revision'])
        if not entry.get('accept_license'):
            raise ValueError('Set accept_license=true only after reviewing this model and quantization license')
        patterns=entry.get('include',[])
        if not patterns or any(not isinstance(p,str) or p in {'*','**','**/*'} or '\\' in p or p.startswith('/') or '..' in p.split('/') for p in patterns):
            raise ValueError('Specify exact files or narrow --include patterns for one quantization')
        destination=Path(entry['artifact_root']).expanduser().resolve()
        lock=Path(entry['artifact_lock']).expanduser().resolve()
        if lock.is_relative_to(destination):raise ValueError('Store artifact lock outside its model directory')
        if any(destination.is_relative_to(p) or p.is_relative_to(destination) for p in targets):
            raise ValueError('Model download directories must not overlap')
        targets.append(destination)
        if not entry.get('precision'):raise ValueError('Record the selected precision')
        entry.update(artifact_root=str(destination),artifact_lock=str(lock),base_model_repo=models[model]['upstream_repo'])
    return entries


def download_with_environment(root,plan,spec):
    entries=validate_download_spec(root,spec,plan['selected_models'])
    environment=Path(plan['prefix'])/'download-venv'
    if not environment.exists():invoke([plan['python'],'-m','venv',environment])
    py=python_in(environment,plan['os_id'])
    package=read_json(Path(root)/'catalog/installers.json')['model_download_package']
    invoke([py,'-m','pip','install',str(root),package])
    prepared=Path(plan['prefix'])/'model-downloads.json'
    write_json(prepared,{'models':entries})
    invoke([py,'-m','llm_eval.model_download',prepared])


def download(entries):
    from huggingface_hub import snapshot_download
    for entry in entries:
        destination=Path(entry['artifact_root'])
        # An interrupted download can be resumed only with the identical recorded spec.
        marker=destination.parent/(destination.name+'.download.json')
        if destination.exists() and any(destination.iterdir()):
            if not marker.exists() or read_json(marker)!=entry:
                raise ValueError('Destination is nonempty and not from this exact download specification')
        write_json(marker,entry)
        snapshot_download(repo_id=entry['source_repo'],revision=entry['source_revision'],
                          allow_patterns=entry['include'],local_dir=destination,max_workers=2)
        locked=lock_artifact(destination,entry['source_repo'],entry['source_revision'],entry['precision'],entry['artifact_lock'])
        locked['base_model_repo']=entry['base_model_repo']
        write_json(entry['artifact_lock'],locked)
        print('Model artifact locked:',entry['artifact_lock'])


if __name__=='__main__':download(read_json(sys.argv[1])['models'])
