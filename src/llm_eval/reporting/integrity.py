"""Verify manifest inventories against a public checkout and its HEAD tree."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess

from llm_eval.common import digest


COMPATIBILITY_FILE = 'docs/result-integrity-v1.json'
COMPATIBILITY_SHA256 = '71109221aab3589ab547ca8f619c928510b0ba7fa8f6823cb28f23cc493227d4'


def _tree(root):
    completed = subprocess.run(
        ['git', '-C', str(root), 'ls-tree', '-rz', '--full-tree', 'HEAD', '--', 'docs/results', 'diagrams/results'],
        capture_output=True, check=False, timeout=120)
    if completed.returncode:
        raise ValueError('Cannot read the published results from Git HEAD')
    tree = {}
    for entry in completed.stdout.split(b'\0'):
        if entry:
            meta, name = entry.split(b'\t', 1)
            mode, _, oid = meta.decode('ascii').split()
            tree[name.decode('utf-8')] = (mode, oid)
    return tree


def _checked_bytes(root, tree, name):
    mode, oid = tree[name]
    target = root / name
    if mode != '100644' or not target.is_file() or target.is_symlink() or not target.resolve().is_relative_to(root):
        raise ValueError('Missing or unexpected result file type: ' + name)
    data = target.read_bytes()
    # Git blob IDs hash a typed header and the exact bytes. Checking the worktree this way catches checkout conversion.
    algorithm = 'sha1' if len(oid) == 40 else 'sha256'
    hasher = hashlib.new(algorithm, f'blob {len(data)}\0'.encode('ascii'))
    hasher.update(data)
    if hasher.hexdigest() != oid:
        raise ValueError('Checkout bytes differ from the committed Git blob: ' + name)
    return data


def verify_results(root):
    root = Path(root).resolve()
    ledger = (root / COMPATIBILITY_FILE).read_bytes()
    if hashlib.sha256(ledger).hexdigest() != COMPATIBILITY_SHA256:
        raise ValueError('The versioned historical compatibility map has changed')
    historical = json.loads(ledger)['manifests']
    tree = _tree(root)
    inventories = {}
    for name in tree:
        parts = PurePosixPath(name).parts
        if len(parts) < 5 or parts[:3] in {('docs','results','index'), ('diagrams','results','summary')}:
            continue
        manifest_path = '/'.join(('docs', 'results', parts[2], parts[3], 'manifest.json'))
        inventories.setdefault(manifest_path, set()).add(name)
    missing = set(historical) - inventories.keys()
    if missing:
        raise ValueError('Missing historical bundle: ' + min(missing))
    files = exceptions = affected = 0
    for name, inventory in sorted(inventories.items()):
        if name not in inventory:
            raise ValueError('Missing manifest: ' + name)
        baseline = historical.get(name, {})
        if baseline and tree[name][1] != baseline['manifest_blob']:
            raise ValueError('Historical manifest differs from its original Git object: ' + name)
        manifest = json.loads(_checked_bytes(root, tree, name))
        if digest({k:v for k,v in manifest.items() if k != 'report_fingerprint'}) != manifest['report_fingerprint']:
            raise ValueError('Manifest fingerprint mismatch: ' + name)
        if inventory != set(manifest['files']) | {name}:
            raise ValueError('Committed file inventory differs from the manifest: ' + name)
        report_dir = name.rsplit('/', 1)[0]
        chart_dir = 'diagrams' + report_dir[len('docs'):]
        checkout = {p.relative_to(root).as_posix() for directory in (root / report_dir, root / chart_dir)
                    for p in directory.rglob('*') if p.is_file() or p.is_symlink()}
        if checkout != inventory:
            raise ValueError('Checkout file inventory differs from the manifest: ' + name)
        allowed = {report_dir + '/' + path: entry for path, entry in baseline.get('crlf_exceptions', {}).items()}
        affected += bool(allowed)
        for path, original in manifest['files'].items():
            data = _checked_bytes(root, tree, path)
            current = hashlib.sha256(data).hexdigest()
            files += 1
            if path in allowed:
                entry = allowed[path]
                if (entry['original_sha256'], entry['git_blob'], entry['checkout_sha256']) != (original, tree[path][1], current):
                    raise ValueError('Historical result differs from the recorded compatibility entry: ' + path)
                if hashlib.sha256(data.replace(b'\n', b'\r\n')).hexdigest() != original:
                    raise ValueError('Historical CRLF bytes do not reproduce the original digest: ' + path)
                exceptions += 1
            elif current != original:
                raise ValueError('Result SHA-256 differs from the manifest: ' + path)
    return {'bundles':len(inventories), 'files':files, 'exact':files-exceptions,
            'historical_crlf_files':exceptions, 'affected_historical_bundles':affected}
