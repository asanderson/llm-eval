"""Small, dependency-free schema and persistence primitives."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile
import time

from llm_eval.common import digest, finite_number

SCHEMA_VERSION = 2
TERMINAL = frozenset({'succeeded', 'failed', 'skipped', 'cancelled'})
WINDOWS = os.name == 'nt'
REPLACE_ATTEMPTS = 8       # at most 8 tries, pausing 25 ms longer each time: about 0.7 s in all


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,99}', value):
        raise ValueError('Expected a lowercase identifier, at most 100 characters')
    return value


def fields(value, allowed, required=()):
    if not isinstance(value, dict):
        raise ValueError('Expected an object')
    if set(value) - set(allowed):
        raise ValueError('Unknown fields: ' + ', '.join(sorted(set(value) - set(allowed))))
    if set(required) - set(value):
        raise ValueError('Missing fields: ' + ', '.join(sorted(set(required) - set(value))))
    return value


def integer(value, name, low=1, high=10000):
    finite_number(value, name, low, high)
    if type(value) is not int:
        raise ValueError(name + ' must be an integer')
    return value


def no_credentials(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in {'api_key', 'password', 'secret', 'access_token', 'authorization'}:
                raise ValueError('Use credential environment references, not credentials in JSON')
            no_credentials(item)
    elif isinstance(value, list):
        for item in value:
            no_credentials(item)


def replace_file(source, target):
    """`os.replace`, retried briefly on Windows. Replacing a file that another process holds open (a reader, a virus scanner,
    an indexer) fails there with PermissionError until that handle closes, usually within milliseconds. Elsewhere, and after
    the last try, the error is raised as before."""
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if not WINDOWS or attempt == REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(0.025 * (attempt + 1))


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(value, handle, ensure_ascii=False, allow_nan=False, indent=2)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        replace_file(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def config_hash(value):
    return digest(value)
