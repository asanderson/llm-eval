"""Bounded streaming clients. Network access is limited to literal loopback IPs."""
from __future__ import annotations

import http.client
import ipaddress
import json
import os
import socket
import threading
import time
from urllib.parse import urlsplit

MAX_RESPONSE_BYTES = 16 * 1024 * 1024
MAX_LINE_BYTES = 1024 * 1024


def endpoint_parts(url):
    parts = urlsplit(url)
    if parts.scheme != "http" or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("Use an http loopback endpoint without embedded credentials, query or fragment")
    try:
        address = ipaddress.ip_address(parts.hostname or "")
    except ValueError as exc:
        raise ValueError("Use a literal loopback address, e.g. 127.0.0.1 (DNS is not used)") from exc
    if not address.is_loopback:
        raise ValueError("Remote endpoints are disabled: this project measures self-hosted local inference")
    return parts


def request_events(url, payload, protocol, timeout_s, api_key_env=None):
    parts = endpoint_parts(url)
    conn = http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=min(timeout_s, 30))
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    if api_key_env:
        key = os.environ.get(api_key_env)
        if not key:
            raise ValueError("Configured API key environment variable is unset")
        headers["Authorization"] = "Bearer " + key
    deadline = time.monotonic() + timeout_s
    expired = threading.Event()
    active_socket = [None]

    def abort():
        expired.set()
        sock = active_socket[0]
        if sock:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        conn.close()

    timer = threading.Timer(timeout_s, abort)
    timer.daemon = True
    timer.start()
    try:
        conn.connect()
        active_socket[0] = conn.sock
        conn.request("POST", parts.path or "/", body=json.dumps(payload).encode(), headers=headers)
        response = conn.getresponse()
        if response.status != 200:
            # Never save response bodies: they can echo tokens, prompts, or filesystem paths.
            raise RuntimeError(f"Backend HTTP status {response.status}; redirects are not followed")
        total = 0
        data_lines = []
        while True:
            line = response.readline(MAX_LINE_BYTES + 1)
            if expired.is_set() or time.monotonic() > deadline:
                raise TimeoutError("Generation exceeded request deadline")
            if not line:
                break
            total += len(line)
            if len(line) > MAX_LINE_BYTES or total > MAX_RESPONSE_BYTES:
                raise ValueError("Backend response exceeded size limit")
            text = line.decode("utf-8").rstrip("\r\n")
            if protocol == "ollama":
                if text:
                    yield json.loads(text)
                continue
            if text.startswith("data:"):
                data_lines.append(text[5:].lstrip(" "))
            elif not text and data_lines:
                data = "\n".join(data_lines)
                data_lines = []
                if data == "[DONE]":
                    yield {"_done": True}
                    return
                yield json.loads(data)
        if data_lines:
            data = "\n".join(data_lines)
            if data == "[DONE]":
                yield {"_done": True}
            else:
                yield json.loads(data)
    except (OSError, http.client.HTTPException) as exc:
        if expired.is_set():
            raise TimeoutError("Generation exceeded request deadline") from exc
        raise
    finally:
        timer.cancel()
        conn.close()


def positive_count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


class HTTPAdapter:
    def __init__(self, config):
        self.config = config
        self.protocol = config["protocol"]
        endpoint_parts(config["endpoint"])

    def generate(self, messages, max_tokens, seed, temperature):
        c = self.config
        extra = c.get("request_options", {})
        if any(k in extra for k in ("model", "messages", "stream", "max_tokens", "options")):
            raise ValueError("request_options cannot override benchmark-controlled fields")
        if self.protocol == "ollama":
            payload = {"model": c["served_model"], "messages": messages, "stream": True,
                       "options": {"num_predict": max_tokens, "num_ctx": c["context_tokens"],
                                   "seed": seed, "temperature": temperature}, **extra}
        else:
            payload = {"model": c["served_model"], "messages": messages, "stream": True,
                       "max_tokens": max_tokens, "seed": seed, "temperature": temperature, **extra}
            if c.get("request_usage", True):
                payload["stream_options"] = {"include_usage": True}
        start = time.perf_counter()
        first = first_visible = None
        content, reasoning = [], []
        input_tokens = output_tokens = None
        backend_decode_tps = backend_prefill_tps = backend_load_s = None
        done = False
        finish_reason = None
        for event in request_events(c["endpoint"], payload, self.protocol, c["timeout_s"], c.get("api_key_env")):
            if event.get("error"):
                raise RuntimeError("Backend reported an error (body omitted)")
            now = time.perf_counter()
            if self.protocol == "ollama":
                delta = event.get("message", {})
                visible = delta.get("content", "") or ""
                hidden = delta.get("thinking", "") or ""
                done = done or event.get("done", False)
                if event.get("done"):
                    finish_reason = event.get("done_reason")
                    input_tokens = positive_count(event.get("prompt_eval_count"))
                    output_tokens = positive_count(event.get("eval_count"))
                    if event.get("eval_duration", 0) > 0 and output_tokens is not None:
                        backend_decode_tps = output_tokens * 1e9 / event["eval_duration"]
                    if event.get("prompt_eval_duration", 0) > 0 and input_tokens is not None:
                        backend_prefill_tps = input_tokens * 1e9 / event["prompt_eval_duration"]
                    if event.get("load_duration") is not None:
                        backend_load_s = event["load_duration"] / 1e9
            else:
                choices = event.get("choices", [])
                choice = choices[0] if choices else {}
                delta = choice.get("delta", {})
                visible = delta.get("content", "") or ""
                hidden = delta.get("reasoning_content", delta.get("reasoning", "")) or ""
                finish_reason = choice.get("finish_reason") or finish_reason
                done = done or event.get("_done", False) or finish_reason is not None
                usage = event.get("usage") or {}
                if usage.get("prompt_tokens") is not None:
                    input_tokens = positive_count(usage["prompt_tokens"])
                if usage.get("completion_tokens") is not None:
                    output_tokens = positive_count(usage["completion_tokens"])
                timings = event.get("timings", {})
                if timings.get("predicted_ms", 0) > 0:
                    backend_decode_tps = timings["predicted_n"] * 1000 / timings["predicted_ms"]
                if timings.get("prompt_ms", 0) > 0:
                    backend_prefill_tps = timings["prompt_n"] * 1000 / timings["prompt_ms"]
            if not isinstance(visible, str) or not isinstance(hidden, str):
                raise ValueError("Only text deltas are supported in the text benchmark")
            if (visible or hidden) and first is None:
                first = now - start
            if visible and first_visible is None:
                first_visible = now - start
            content.append(visible)
            reasoning.append(hidden)
        if not done:
            raise RuntimeError("Incomplete stream: no completion marker or finish reason")
        elapsed = time.perf_counter() - start
        return {"text": "".join(content), "reasoning_chars": sum(map(len, reasoning)),
                "elapsed_s": elapsed, "first_output_s": first, "first_visible_s": first_visible,
                "prompt_tokens": input_tokens, "completion_tokens": output_tokens,
                "token_count_source": "backend_usage" if output_tokens is not None else "unavailable",
                "output_tokens_per_wall_second": output_tokens / elapsed if output_tokens is not None else None,
                "backend_decode_tps": backend_decode_tps, "backend_prefill_tps": backend_prefill_tps,
                "backend_load_s": backend_load_s, "finish_reason": finish_reason}
