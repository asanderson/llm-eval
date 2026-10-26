"""Managed LM Studio lifecycle through the MIT ``lms`` CLI.

LM Studio's engine runs inside the desktop app or the ``llmster`` daemon, which
``lms`` starts detached from this process. The ``serve`` command therefore acts
as the owned backend process: it imports the locked GGUF, loads it with explicit
context/GPU placement, starts the loopback server, and stays alive until it is
terminated. ``cleanup`` releases exactly what ``serve`` recorded in its state
file, so it is safe to run after an abrupt termination. Commands are argument
arrays, never shell text.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import signal
import subprocess
import sys
import time

from .common import read_json, write_json

GPU_VALUES = {'off', 'max'}
IMPORT_MODES = ('symbolic-link', 'hard-link', 'copy')


def gpu_offload(value):
    """``lms load --gpu`` accepts off, max, or a ratio from 0 to 1; never a layer count."""
    text = str(value).strip()
    if text in GPU_VALUES:
        return text
    try:
        ratio = float(text)
    except ValueError as exc:
        raise ValueError('launch.gpu_offload must be off, max, or a ratio from 0 to 1') from exc
    if not 0 <= ratio <= 1 or text.lower() in {'nan', 'inf', '-inf'}:
        raise ValueError('launch.gpu_offload must be off, max, or a ratio from 0 to 1')
    return text


def run(argv, timeout=900):
    p = subprocess.run([str(a) for a in argv], capture_output=True, text=True, errors='replace',
                       timeout=timeout, shell=False)
    return p.returncode, (p.stdout + p.stderr)


def last_json(text):
    for line in reversed(text.strip().splitlines()):
        line = line.strip()
        if line.startswith('{'):
            try:
                return json.loads(line)
            except ValueError:
                continue
    return {}


def model_key(artifact_id, model_file):
    """Content-addressed LM Studio model path for the imported artifact."""
    return f'llm-eval/{artifact_id}/{Path(model_file).name}'


def serve(args, load_args):
    state_path = Path(args.state)
    state = {'daemon_started': False, 'daemon_pid': None, 'server_started': False, 'loaded': None}
    write_json(state_path, state)

    def fail(message):
        print('lmstudio supervisor: ' + message, file=sys.stderr, flush=True)
        cleanup(args)
        return 1

    code, out = run([args.lms, 'daemon', 'status', '--json'])
    was_running = code == 0 and last_json(out).get('status') == 'running'
    code, out = run([args.lms, 'daemon', 'up', '--json'], timeout=args.load_timeout)
    info = last_json(out)
    if code or info.get('status') != 'running':
        return fail('lms daemon up failed; is LM Studio or llmster installed for this user?\n' + out[-2000:])
    state.update(daemon_started=not was_running, daemon_pid=info.get('pid'))
    write_json(state_path, state)
    version = info.get('version')
    if args.expected_version and version != args.expected_version:
        return fail(f'Running LM Studio version {version!r} differs from the pinned recipe {args.expected_version!r}; '
                    'install the pinned version or select a new prefix with its own catalog pin')
    code, out = run([args.lms, 'server', 'status', '--json', '--quiet'])
    if code == 0 and last_json(out).get('running'):
        return fail('An LM Studio server is already running; stop it with `lms server stop` before a managed run')

    key = model_key(args.artifact_id, args.model_file)
    code, out = run([args.lms, 'import', args.model_file, '--user-repo', f'llm-eval/{args.artifact_id}',
                     '--yes', '--' + args.import_mode], timeout=args.load_timeout)
    if code and 'already exists' not in out:
        return fail('lms import failed\n' + out[-2000:])
    argv = [args.lms, 'load', key, '--identifier', args.identifier, '--context-length', str(args.context_length),
            '--gpu', args.gpu, '--parallel', '1', '--exact', '--yes', *load_args]
    code, out = run(argv, timeout=args.load_timeout)
    if code:
        return fail('lms load failed\n' + out[-2000:])
    state['loaded'] = args.identifier
    write_json(state_path, state)
    code, out = run([args.lms, 'server', 'start', '--port', str(args.port), '--bind', '127.0.0.1'])
    if code:
        return fail('lms server start failed\n' + out[-2000:])
    state['server_started'] = True
    write_json(state_path, state)
    print(f'lmstudio supervisor: {key} loaded as {args.identifier}; server on 127.0.0.1:{args.port}', flush=True)

    stopping = []
    def stop(*_):
        stopping.append(True)
    for name in ('SIGTERM', 'SIGINT', 'SIGBREAK'):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), stop)
    while not stopping:
        time.sleep(0.5)
    return 0


def cleanup(args):
    """Release only what this supervisor started; idempotent after partial failures."""
    state_path = Path(args.state)
    if not state_path.is_file():
        return 0
    state = read_json(state_path)
    if state.get('loaded'):
        run([args.lms, 'unload', state['loaded']], timeout=300)
    if state.get('server_started'):
        run([args.lms, 'server', 'stop'], timeout=120)
    if state.get('daemon_started'):
        run([args.lms, 'daemon', 'down'], timeout=120)
    state_path.unlink(missing_ok=True)
    return 0


def parser():
    p = argparse.ArgumentParser(description='Internal LM Studio supervisor for managed benchmark runs')
    sub = p.add_subparsers(dest='command', required=True)
    s = sub.add_parser('serve')
    s.add_argument('--lms', required=True)
    s.add_argument('--model-file', required=True)
    s.add_argument('--artifact-id', required=True)
    s.add_argument('--identifier', required=True)
    s.add_argument('--port', type=int, required=True)
    s.add_argument('--context-length', type=int, required=True)
    s.add_argument('--gpu', type=gpu_offload, default='0.5')
    s.add_argument('--import-mode', choices=IMPORT_MODES, default='symbolic-link')
    s.add_argument('--state', required=True)
    s.add_argument('--load-timeout', type=int, default=900)
    s.add_argument('--expected-version')
    c = sub.add_parser('cleanup')
    c.add_argument('--lms', required=True)
    c.add_argument('--state', required=True)
    return p


def main(argv=None):
    args, extra = parser().parse_known_args(argv)
    if args.command == 'serve':
        return serve(args, extra)
    if extra:
        raise SystemExit('cleanup accepts no extra arguments')
    return cleanup(args)


if __name__ == '__main__':
    raise SystemExit(main())
