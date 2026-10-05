"""Isolated optional Python engine process. No backend installs are performed."""
import json
import os
import queue
import subprocess
import sys
import threading
import time


class LocalAdapter:
    def __init__(self, config, config_path):
        env = os.environ.copy()
        threads=str(config.get('launch',{}).get('threads',16))
        env.update(OMP_NUM_THREADS=threads,MKL_NUM_THREADS=threads,
                   CUDA_VISIBLE_DEVICES=str(config.get('launch',{}).get('gpu',0)))
        env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_DATASETS_OFFLINE="1",
                   HF_HUB_DISABLE_TELEMETRY="1", TOKENIZERS_PARALLELISM="false")
        for name in list(env):
            if any(s in name.upper() for s in ("TOKEN", "SECRET", "PASSWORD", "API_KEY")) and name != "TOKENIZERS_PARALLELISM":
                env.pop(name)
        self.process = subprocess.Popen([config.get("worker_python", sys.executable), "-m", "llm_eval.worker", str(config_path)],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                        text=True, encoding="utf-8", bufsize=1, env=env)
        self.events = queue.Queue(maxsize=4096)
        self.config = config
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        try:
            ready = self._receive(time.monotonic() + config.get("load_timeout_s", 600))
            if ready.get("type") != "ready":
                raise RuntimeError("Local engine failed to load; check installed backend and model support")
            self.load_s = ready["load_s"]
            self.backend_versions = ready.get("versions", {})
        except BaseException:
            self.close()
            raise

    def _read(self):
        try:
            while True:
                line = self.process.stdout.readline(2 * 1024 * 1024 + 1)
                if not line:
                    break
                if len(line) > 2 * 1024 * 1024:
                    break
                try:
                    event = json.loads(line)
                except ValueError:
                    event = {"type": "error"}
                try:
                    self.events.put(event, timeout=2)
                except queue.Full:
                    break
        finally:
            try:
                self.events.put({"type": "eof"}, timeout=2)
            except queue.Full:
                pass

    def _receive(self, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Local engine request deadline exceeded")
        try:
            return self.events.get(timeout=remaining)
        except queue.Empty as exc:
            raise TimeoutError("Local engine request deadline exceeded") from exc

    def generate(self, messages, max_tokens, seed, temperature):
        self.process.stdin.write(json.dumps({"messages": messages, "max_tokens": max_tokens,
                                            "seed": seed, "temperature": temperature}) + "\n")
        self.process.stdin.flush()
        deadline = time.monotonic() + self.config["timeout_s"]
        try:
            event = self._receive(deadline)
            if event.get("type") != "result":
                raise RuntimeError("Local backend failed; output omitted to protect prompt data")
            return event["result"]
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.process.poll() is None:
            try:
                import psutil
                for child in psutil.Process(self.process.pid).children(recursive=True):
                    child.kill()
            except Exception:
                pass
            self.process.kill()
            self.process.wait(timeout=10)
        for stream in (self.process.stdin, self.process.stdout):
            if stream:
                stream.close()
