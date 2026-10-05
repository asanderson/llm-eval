import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from llm_eval.artifacts import lock_artifact, verify_artifact
from llm_eval.catalog import matrix, validate_catalog
from llm_eval.common import read_json, write_json
from llm_eval.report import quantile, summarize
from llm_eval.runner import grade, run, validate_config

ROOT = Path(__file__).resolve().parents[1]


class ArtifactTests(unittest.TestCase):
    def test_lock_tamper_and_vram_threshold(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "model"
            root.mkdir()
            weights = root / "model.gguf"
            weights.write_bytes(b"fixture")
            lock = lock_artifact(root, "org/quant", "a" * 40, "Q4", Path(directory) / "lock.json")
            self.assertEqual(verify_artifact(root, lock, False), 7)
            with self.assertRaisesRegex(ValueError, "does not exceed"):
                verify_artifact(root, lock)
            weights.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "verification failed"):
                verify_artifact(root, lock, False)

    def test_revision_and_traversal(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                lock_artifact(d, "org/model", "main", "Q4", Path(d).parent / "x.json")
            lock = {"source_revision": "a" * 40, "weight_bytes": 1,
                    "files": [{"path": "../outside", "bytes": 1, "sha256": "x", "weight": True}]}
            with self.assertRaisesRegex(ValueError, "escapes"):
                verify_artifact(d, lock)

    def test_new_unreviewed_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "model"
            root.mkdir()
            (root / "model.gguf").write_bytes(b"fixture")
            lock = lock_artifact(root, "org/model", "b" * 40, "Q4", Path(directory) / "lock.json")
            (root / "modeling.py").write_text("# an unreviewed new file")
            with self.assertRaisesRegex(ValueError, "inventory changed"):
                verify_artifact(root, lock, False)


class ProjectTests(unittest.TestCase):
    def test_catalog_and_matrix(self):
        models = validate_catalog(read_json(ROOT / "catalog/models.json"))["models"]
        rows = matrix(ROOT)
        self.assertEqual(len(rows), len(models) * 9 * 3)
        self.assertTrue(all(r["status"] == "blocked" for r in rows if r["platform"] == "strata" and r["model"] != "qwen38-flash-next-strata"))
        self.assertTrue(all(r["status"] == "blocked" for r in rows if r["platform"] == "vllm" and r["os"] == "windows-11-native"))
        self.assertEqual(len([m for m in models if m["provider"] == "xAI" and m["status"] != "excluded"]), 0)

    def test_control_and_invalid_config(self):
        c = read_json(ROOT / "configs/runs/llama.cpp.example.json")
        validate_config(c, ROOT, True)
        c["repeats"] = float("nan")
        with self.assertRaises(ValueError):
            validate_config(c, ROOT, True)

    def test_quality_checks_are_not_code_execution(self):
        self.assertTrue(grade('{"a":1}', {"check": {"type": "json_equal", "expected": {"a": 1}}}))
        self.assertFalse(grade('```json\n{"a":1}\n```', {"check": {"type": "json_equal", "expected": {"a": 1}}}))
        self.assertTrue(grade("3973\n", {"check": {"type": "exact", "expected": "3973"}}))

    def test_quantiles(self):
        self.assertIsNone(quantile([], .95))
        self.assertAlmostEqual(quantile([1, 2, 3], .95), 2.9)

    def test_warmups_synthetic_and_engine_cohorts(self):
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(2):
                p = Path(tmp) / str(i)
                p.mkdir()
                c = dict(model_id="x", platform="llama.cpp", os_id="ubuntu", context_tokens=4096,
                         backend_version=str(i), lane="offload")
                write_json(p / "metadata.json", {"synthetic": True, "config": c, "suite_sha256": "a"})
                rows = [{"task_id": "a", "warmup": w, "status": "ok", "elapsed_s": v, "quality_pass": True}
                        for w, v in [(True, 999), (False, 2), (False, 4)]]
                (p / "requests.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
            self.assertEqual(summarize(tmp), [])
            report = summarize(tmp, True)
            self.assertEqual(len(report), 2)
            self.assertTrue(all(r["elapsed_s_median"] == 3 for r in report))
            self.assertTrue(all(r["requests"] == 2 for r in report))

    def test_end_to_end_synthetic_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = read_json(ROOT / "configs/runs/llama.cpp.example.json")
            c.update(suite=str(ROOT / "workloads/smoke.json"), repeats=1, warmups=1)
            path = Path(tmp) / "run.json"
            write_json(path, c)
            response = {"text": "3973", "prompt_tokens": 4, "completion_tokens": 2, "elapsed_s": .1,
                        "first_output_s": .01, "first_visible_s": .01, "backend_decode_tps": None}
            with patch("llm_eval.runner.HTTPAdapter.generate", side_effect=lambda *a, **k: dict(response)):
                out = run(path, ROOT, Path(tmp) / "results", synthetic=True)
            meta = read_json(out / "metadata.json")
            self.assertEqual(meta["status"], "completed")
            self.assertEqual(meta["measured_requests"], 6)
            rows = [json.loads(s) for s in (out / "requests.jsonl").read_text().splitlines()]
            self.assertTrue(all("output" not in r for r in rows))
            self.assertEqual(summarize(Path(tmp) / "results"), [])


if __name__ == "__main__":
    unittest.main()
