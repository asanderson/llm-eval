import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from llm_eval import adapters
from llm_eval.adapters import HTTPAdapter, endpoint_parts, request_events


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    mode = "openai"

    def log_message(self, *args):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        if self.mode == "late":
            time.sleep(.3)
        if self.mode == "redirect":
            self.send_response(302)
            self.send_header("Location", "http://example.com/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        if self.mode == "slow":
            time.sleep(.3)
            return
        if self.mode == "ollama":
            events = [{"message": {"thinking": "work"}}, {"message": {"content": "3973"}},
                      {"done": True, "done_reason": "stop", "prompt_eval_count": 12,
                       "eval_count": 4, "eval_duration": 2_000_000_000,
                       "prompt_eval_duration": 1_000_000_000, "load_duration": 0}]
            self.wfile.write("\n".join(json.dumps(e) for e in events).encode() + b"\n")
        else:
            events = [{"choices": [{"delta": {"role": "assistant"}}]},
                      {"choices": [{"delta": {"reasoning_content": "work"}}]},
                      {"choices": [{"delta": {"content": "3973"}}]}]
            if self.mode != "truncated":
                events.append({"choices": [{"delta": {}, "finish_reason": "stop"}]})
                if self.mode == "lmstudio":
                    events[-1].update(usage={"prompt_tokens": 12, "completion_tokens": 4},
                                      stats={"tokens_per_second": 41.5, "time_to_first_token": 0.2, "stop_reason": "eosFound"})
                elif self.mode != "no_usage":
                    events.append({"choices": [], "usage": {"prompt_tokens": 12, "completion_tokens": 4}})
            for e in events:
                self.wfile.write(("data: " + json.dumps(e) + "\r\n\r\n").encode())
            if self.mode != "truncated":
                self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()
        self.close_connection = True


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.handler = type("PerTestHandler", (Handler,), {})
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.config = dict(protocol="openai", endpoint=f"http://127.0.0.1:{self.server.server_port}/v1/chat/completions",
                           served_model="fixture", timeout_s=5, context_tokens=4096)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def generate(self):
        return HTTPAdapter(self.config).generate([{"role": "user", "content": "test"}], 16, 1, 0)

    def test_stream_usage_and_reasoning(self):
        result = self.generate()
        self.assertEqual(result["text"], "3973")
        self.assertEqual(result["completion_tokens"], 4)
        self.assertLessEqual(result["first_output_s"], result["first_visible_s"])
        self.assertIsNone(result["backend_decode_tps"])

    def test_missing_usage_is_unknown_not_chunk_count(self):
        self.handler.mode = "no_usage"
        result = self.generate()
        self.assertIsNone(result["completion_tokens"])
        self.assertIsNone(result["output_tokens_per_wall_second"])

    def test_ollama_backend_timing(self):
        self.handler.mode = "ollama"
        self.config["protocol"] = "ollama"
        result = self.generate()
        self.assertEqual(result["backend_decode_tps"], 2)
        self.assertEqual(result["backend_prefill_tps"], 12)

    def test_lmstudio_stats_report_explicit_decode_rate(self):
        self.handler.mode = "lmstudio"
        result = self.generate()
        self.assertEqual(result["completion_tokens"], 4)
        self.assertEqual(result["backend_decode_tps"], 41.5)
        self.assertIsNone(result["backend_prefill_tps"])
        self.assertEqual(result["finish_reason"], "stop")

    def test_truncation_is_failure(self):
        self.handler.mode = "truncated"
        with self.assertRaises(RuntimeError):
            self.generate()

    def test_redirect_rejected(self):
        self.handler.mode = "redirect"
        with self.assertRaisesRegex(RuntimeError, "302"):
            self.generate()

    def test_wall_clock_deadline(self):
        self.handler.mode = "slow"
        self.config["timeout_s"] = .05
        with self.assertRaises(TimeoutError):
            self.generate()

    def test_slow_first_byte_is_bounded_by_request_deadline_not_connect_timeout(self):
        # Ollama loads the model on the first request; a 30 GiB load kept the socket silent for 30 s.
        self.handler.mode = "late"
        with mock.patch.object(adapters, 'CONNECT_TIMEOUT_S', .1):
            result = self.generate()
        self.assertEqual(result["finish_reason"], "stop")

    def test_endpoint_scope(self):
        for url in ["https://example.com/", "http://192.168.1.1/", "http://localhost/", "http://user:pw@127.0.0.1/", "file:///tmp/a", "http://127.0.0.1/?key=x"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                endpoint_parts(url)
        self.assertEqual(endpoint_parts("http://[::1]:8000/v1").hostname, "::1")

    def test_endpoint_has_one_spelling(self):
        # urlsplit forgives every one of these, and each used to pass as a loopback endpoint.
        for url in [" http://127.0.0.1:8000/v1", "http://127.0.0.1:8000/v1\n", "ht\ttp://127.0.0.1:8000/v1",
                    "http://127.0.0.1:8000/v1 x", "HTTP://127.0.0.1:8000/v1",
                    "http://127.0.0.1:99999/v1", "http://127.0.0.1:0/v1", "http://127.0.0.1:/v1", "http://127.0.0.1:080/v1",
                    "http://[::ffff:127.0.0.1]:8000/v1", "http://[::1%25eth0]:8000/v1", "http://[0:0:0:0:0:0:0:1]:8000/v1",
                    b"http://127.0.0.1:8000/v1", None]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                endpoint_parts(url)
        for url, port in [("http://127.0.0.1/v1", None), ("http://127.0.0.1:8000/v1", 8000), ("http://127.0.0.2:65535", 65535),
                          ("http://[::1]/v1", None), ("http://[::1]:8000/v1", 8000)]:
            with self.subTest(url=url):
                self.assertEqual(endpoint_parts(url).port, port)
