"""Persistent reservations. Expiry is never evidence that a worker stopped."""
import os
from pathlib import Path
import shutil
import time

from llm_eval.common import read_json
from llm_eval.core.contracts import atomic_json, identifier


def lock_root(target=None):
    return Path((target or {}).get('lock_root') or Path.home()/'.cache/llm-eval/locks').expanduser()


def reserve(root, resource, owner):
    directory = Path(root)/identifier(resource)
    directory.parent.mkdir(parents=True, exist_ok=True)
    try:
        directory.mkdir()
    except FileExistsError:
        try:
            if read_json(directory/'owner.json')['owner'] == owner:
                return directory
        except (OSError, ValueError, KeyError):
            pass
        raise BlockingIOError('Resource reserved: '+resource)
    atomic_json(directory/'owner.json', {'owner':owner,'pid':os.getpid(),'created':time.time()})
    return directory


def release(root, resource, owner):
    directory = Path(root)/identifier(resource)
    try:
        if read_json(directory/'owner.json')['owner'] != owner:
            raise ValueError('Reservation owner mismatch')
        shutil.rmtree(directory)
    except FileNotFoundError:
        pass

class ProcessLock:
    """OS-held coordinator lock, automatically released after a crash."""
    def __init__(self,path):self.path=Path(path);self.handle=None
    def acquire(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.handle=self.path.open('a+b');self.handle.seek(0)
        if self.path.stat().st_size==0:self.handle.write(b'0');self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.handle.close();raise BlockingIOError('Another coordinator is running')
    def close(self):
        if self.handle:self.handle.close();self.handle=None
