"""Optional Accelerate/AirLLM worker; only local, previously reviewed artifacts."""
import contextlib
import importlib.metadata
import json
from pathlib import Path
import sys
import time


def main():
    config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    protocol_stdout = sys.stdout

    def emit(data):
        protocol_stdout.write(json.dumps(data, allow_nan=False) + "\n")
        protocol_stdout.flush()

    # Libraries sometimes log to stdout; reserve stdout for the worker protocol.
    with contextlib.redirect_stdout(sys.stderr):
        try:
            import torch
            from transformers import AutoTokenizer, set_seed
            started = time.perf_counter()
            model_dir = str(Path(config["artifact_root"]).resolve())
            trust = bool(config.get("reviewed_model_code", False))
            if config["platform"] == "airllm":
                # AirLLM's internal loader behavior is version-dependent. An explicit source review
                # is required even when a particular architecture ultimately uses no custom code.
                if not config.get("reviewed_airllm_source", False):
                    raise ValueError("Review and pin AirLLM's loader before enabling it")
                from airllm import AutoModel
                model = AutoModel.from_pretrained(model_dir, max_seq_len=config["context_tokens"],
                                                   layer_shards_saving_path=config["offload_dir"])
                tokenizer = model.tokenizer
            else:
                import transformers
                allowed = {"AutoModelForCausalLM", "AutoModelForImageTextToText", "AutoModelForMultimodalLM"}
                loader = config.get("loader_class", "AutoModelForCausalLM")
                if loader not in allowed:
                    raise ValueError("Unsupported loader class")
                tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True, trust_remote_code=trust)
                dtype = config.get("dtype", "auto")
                if dtype not in {"auto", "bfloat16", "float16", "float32"}:
                    raise ValueError("Unsupported dtype")
                model = getattr(transformers, loader).from_pretrained(
                    model_dir, local_files_only=True, trust_remote_code=trust, device_map="auto",
                    torch_dtype="auto" if dtype == "auto" else getattr(torch, dtype),
                    low_cpu_mem_usage=True,
                    max_memory={0: f"{config['gpu_budget_gib']}GiB", "cpu": f"{config['ram_budget_gib']}GiB"},
                    offload_folder=config["offload_dir"])
                if not config.get("allow_disk_offload", False) and "disk" in getattr(model, "hf_device_map", {}).values():
                    raise ValueError("Disk placement is outside the resident-memory lane")
                model.eval()
            versions = {}
            for pkg in ("torch", "transformers", "accelerate", "airllm"):
                try:
                    versions[pkg] = importlib.metadata.version(pkg)
                except importlib.metadata.PackageNotFoundError:
                    pass
            emit({"type": "ready", "load_s": time.perf_counter() - started, "versions": versions})
            for line in sys.stdin:
                request = json.loads(line)
                set_seed(request["seed"])
                template_options = config.get("chat_template_options", {})
                forbidden = {"tokenize", "return_tensors", "return_dict", "add_generation_prompt"}
                if forbidden.intersection(template_options):
                    raise ValueError("Template options override controlled fields")
                tokens = tokenizer.apply_chat_template(request["messages"], add_generation_prompt=True,
                                                        return_tensors="pt", **template_options)
                prompt_count = tokens.shape[-1]
                if prompt_count + request["max_tokens"] > config["context_tokens"]:
                    raise ValueError("Prompt plus output exceeds configured context; no silent truncation")
                device = "cuda:0" if config["platform"] == "airllm" else model.get_input_embeddings().weight.device
                if str(device) == "meta":
                    device = "cuda:0"
                tokens = tokens.to(device)
                if torch.cuda.is_available():
                    torch.cuda.synchronize()
                begin = time.perf_counter()
                with torch.inference_mode():
                    out = model.generate(tokens, max_new_tokens=request["max_tokens"],
                                         do_sample=request["temperature"] > 0,
                                         **({"temperature": request["temperature"]} if request["temperature"] > 0 else {}))
                if torch.cuda.is_available():
                    torch.cuda.synchronize()
                elapsed = time.perf_counter() - begin
                sequences = out.sequences if hasattr(out, "sequences") else out
                new_tokens = sequences[0, prompt_count:]
                text = tokenizer.decode(new_tokens, skip_special_tokens=True)
                count = len(new_tokens)
                emit({"type": "result", "result": {"text": text, "reasoning_chars": None,
                      "elapsed_s": elapsed, "first_output_s": None, "first_visible_s": None,
                      "prompt_tokens": prompt_count, "completion_tokens": count,
                      "token_count_source": "generated_token_ids", "output_tokens_per_wall_second": count / elapsed,
                      "backend_decode_tps": None, "backend_prefill_tps": None, "backend_load_s": None,
                      "finish_reason": "length" if count == request["max_tokens"] else "stop",
                      "measurement_scope": "generate_only_including_prefill; nonstreaming; raw reasoning may be in text"}})
        except Exception as exc:
            emit({"type": "error", "error_type": type(exc).__name__})
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
