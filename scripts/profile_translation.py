"""Profile translation engine to find GPU utilization bottleneck.

Measures: tokenization, generation, decoding time per batch.
Tests different batch sizes to find throughput sweet spot.
"""

import time
import torch
import threading
import subprocess
from common.engine import create_engine, build_chat_messages, SAMPLING_DEFAULTS
from common.translation import build_translation_prompt, split_frontmatter, protect_fragments, split_large_text


# --- GPU monitoring thread ---
class GPUMonitor:
    def __init__(self, interval=0.2):
        self.interval = interval
        self.running = False
        self.samples = []
        self._thread = None

    def start(self):
        self.running = True
        self.samples = []
        self._thread = threading.Thread(target=self._poll, daemon=True)
        self._thread.start()

    def stop(self):
        self.running = False
        if self._thread:
            self._thread.join()

    def _poll(self):
        while self.running:
            try:
                out = subprocess.check_output(
                    ["nvidia-smi", "--query-gpu=utilization.gpu,utilization.memory,power.draw,power.limit",
                     "--format=csv,noheader,nounits"],
                    text=True
                ).strip()
                parts = out.split(", ")
                self.samples.append({
                    "gpu_util": float(parts[0]),
                    "mem_util": float(parts[1]),
                    "power_draw": float(parts[2]),
                    "power_limit": float(parts[3]),
                })
            except Exception:
                pass
            time.sleep(self.interval)

    def summary(self):
        if not self.samples:
            return "No samples"
        gpu = [s["gpu_util"] for s in self.samples]
        mem = [s["mem_util"] for s in self.samples]
        pwr = [s["power_draw"] for s in self.samples]
        plim = self.samples[0]["power_limit"]
        return (
            f"  GPU Util: avg={sum(gpu)/len(gpu):.1f}%, max={max(gpu):.0f}%, min={min(gpu):.0f}%\n"
            f"  Mem Util: avg={sum(mem)/len(mem):.1f}%, max={max(mem):.0f}%\n"
            f"  Power:    avg={sum(pwr)/len(pwr):.0f}W / {plim:.0f}W cap "
            f"({sum(pwr)/len(pwr)/plim*100:.0f}%)\n"
            f"  Samples:  {len(self.samples)}"
        )


def make_test_prompts(n: int) -> list[str]:
    """Generate n realistic translation prompts of varying length."""
    samples = [
        "This is a short sentence about AI development.",
        "Today I worked on optimizing the translation pipeline. The main bottleneck was that the model was being loaded and unloaded for each document, which wasted GPU time on initialization.",
        "## Problems & Solutions\n\n### 1. Build Error\n\n**Problem:** The TypeScript compiler reported type mismatches in the API response handler.\n\n**Solution:** Added proper generic type constraints and used type narrowing with discriminated unions.\n\n**Key Insight:** TypeScript's structural typing means interfaces should be defined at the boundary, not internally.",
        "The research paper presents a novel approach to neural machine translation that leverages cross-attention mechanisms between the source and target language representations. Unlike previous work that relied solely on encoder-decoder architectures, this method introduces a bidirectional attention bridge that allows information to flow freely between languages during the decoding phase. Experimental results on WMT benchmarks show consistent improvements of 1.2-2.4 BLEU points across language pairs.",
    ]
    prompts = []
    for i in range(n):
        text = samples[i % len(samples)]
        prompts.append(build_translation_prompt(text, "zh", markdown=True))
    return prompts


def profile_tokenization(engine, prompts):
    """Profile just the tokenization step."""
    tokenizer = engine._tokenizer
    formatted = [
        tokenizer.apply_chat_template(
            build_chat_messages(p), tokenize=False, add_generation_prompt=True
        )
        for p in prompts
    ]

    t0 = time.perf_counter()
    inputs = tokenizer(formatted, return_tensors="pt", padding=True, truncation=True)
    inputs = {k: v.to(engine._model.device) for k, v in inputs.items() if k != "token_type_ids"}
    t1 = time.perf_counter()

    seq_len = inputs["input_ids"].shape[1]
    pad_ratio = (inputs["attention_mask"] == 0).float().mean().item()

    print(f"  Tokenization: {(t1-t0)*1000:.1f}ms")
    print(f"  Batch shape: {list(inputs['input_ids'].shape)}")
    print(f"  Seq length (padded): {seq_len}")
    print(f"  Padding ratio: {pad_ratio*100:.1f}% (wasted compute)")

    return inputs, formatted


def profile_generation(engine, inputs, max_new_tokens=256):
    """Profile just the model.generate() step."""
    model = engine._model
    monitor = GPUMonitor(interval=0.1)

    torch.cuda.synchronize()
    monitor.start()
    t0 = time.perf_counter()

    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=True,
            top_k=SAMPLING_DEFAULTS["top_k"],
            top_p=SAMPLING_DEFAULTS["top_p"],
            temperature=SAMPLING_DEFAULTS["temperature"],
            repetition_penalty=SAMPLING_DEFAULTS["repetition_penalty"],
        )

    torch.cuda.synchronize()
    t1 = time.perf_counter()
    monitor.stop()

    prompt_len = inputs["input_ids"].shape[1]
    gen_tokens = outputs[:, prompt_len:]
    total_new_tokens = (gen_tokens != engine._tokenizer.pad_token_id).sum().item()
    elapsed = t1 - t0

    print(f"  Generation: {elapsed*1000:.0f}ms")
    print(f"  Tokens generated: {total_new_tokens} total, "
          f"{total_new_tokens/outputs.shape[0]:.0f} avg/seq")
    print(f"  Throughput: {total_new_tokens/elapsed:.0f} tok/s")
    print(f"  GPU stats during generation:")
    print(monitor.summary())

    return outputs, gen_tokens


def profile_greedy_vs_sampling(engine, inputs, max_new_tokens=256):
    """Compare greedy decode vs sampling to see if sampling is the bottleneck."""
    model = engine._model

    # Greedy
    torch.cuda.synchronize()
    t0 = time.perf_counter()
    with torch.no_grad():
        outputs_greedy = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)
    torch.cuda.synchronize()
    t_greedy = time.perf_counter() - t0

    prompt_len = inputs["input_ids"].shape[1]
    gen_greedy = (outputs_greedy[:, prompt_len:] != engine._tokenizer.pad_token_id).sum().item()

    # Sampling
    torch.cuda.synchronize()
    t0 = time.perf_counter()
    with torch.no_grad():
        outputs_sample = model.generate(
            **inputs, max_new_tokens=max_new_tokens,
            do_sample=True,
            top_k=SAMPLING_DEFAULTS["top_k"],
            top_p=SAMPLING_DEFAULTS["top_p"],
            temperature=SAMPLING_DEFAULTS["temperature"],
            repetition_penalty=SAMPLING_DEFAULTS["repetition_penalty"],
        )
    torch.cuda.synchronize()
    t_sample = time.perf_counter() - t0

    gen_sample = (outputs_sample[:, prompt_len:] != engine._tokenizer.pad_token_id).sum().item()

    print(f"  Greedy:   {t_greedy*1000:.0f}ms, {gen_greedy} tokens, {gen_greedy/t_greedy:.0f} tok/s")
    print(f"  Sampling: {t_sample*1000:.0f}ms, {gen_sample} tokens, {gen_sample/t_sample:.0f} tok/s")
    print(f"  Sampling overhead: {(t_sample-t_greedy)/t_greedy*100:+.0f}%")


def profile_batch_sizes(engine, max_new_tokens=256):
    """Test different batch sizes to find optimal throughput."""
    print("\n" + "="*60)
    print("BATCH SIZE SWEEP (max_new_tokens=256)")
    print("="*60)

    for bs in [1, 4, 8, 16, 32, 64, 128]:
        prompts = make_test_prompts(bs)
        tokenizer = engine._tokenizer
        formatted = [
            tokenizer.apply_chat_template(
                build_chat_messages(p), tokenize=False, add_generation_prompt=True
            )
            for p in prompts
        ]
        inputs = tokenizer(formatted, return_tensors="pt", padding=True, truncation=True)
        inputs = {k: v.to(engine._model.device) for k, v in inputs.items() if k != "token_type_ids"}

        monitor = GPUMonitor(interval=0.1)
        torch.cuda.synchronize()
        monitor.start()
        t0 = time.perf_counter()

        try:
            with torch.no_grad():
                outputs = engine._model.generate(
                    **inputs, max_new_tokens=max_new_tokens,
                    do_sample=True,
                    top_k=SAMPLING_DEFAULTS["top_k"],
                    top_p=SAMPLING_DEFAULTS["top_p"],
                    temperature=SAMPLING_DEFAULTS["temperature"],
                    repetition_penalty=SAMPLING_DEFAULTS["repetition_penalty"],
                )
            torch.cuda.synchronize()
            elapsed = time.perf_counter() - t0
            monitor.stop()

            prompt_len = inputs["input_ids"].shape[1]
            gen_tokens = (outputs[:, prompt_len:] != tokenizer.pad_token_id).sum().item()

            gpu_samples = [s["gpu_util"] for s in monitor.samples]
            avg_gpu = sum(gpu_samples)/len(gpu_samples) if gpu_samples else 0
            pwr_samples = [s["power_draw"] for s in monitor.samples]
            avg_pwr = sum(pwr_samples)/len(pwr_samples) if pwr_samples else 0

            print(f"  BS={bs:>3}: {elapsed:.1f}s, {gen_tokens} tok, "
                  f"{gen_tokens/elapsed:.0f} tok/s, "
                  f"GPU={avg_gpu:.0f}%, Power={avg_pwr:.0f}W, "
                  f"PadSeqLen={inputs['input_ids'].shape[1]}")
        except RuntimeError as e:
            monitor.stop()
            if "out of memory" in str(e).lower():
                print(f"  BS={bs:>3}: OOM!")
                torch.cuda.empty_cache()
                break
            raise


def main():
    print("="*60)
    print("TRANSLATION ENGINE PROFILING")
    print("="*60)

    # Load engine
    print("\n[1] Loading engine...")
    engine = create_engine()
    engine.load()
    print(f"  Model: {engine.model_id}")
    print(f"  Device: {engine._model.device}")
    print(f"  Params: {sum(p.numel() for p in engine._model.parameters())/1e6:.0f}M")

    # VRAM usage
    vram_used = torch.cuda.memory_allocated() / 1024**3
    vram_total = torch.cuda.get_device_properties(0).total_memory / 1024**3
    print(f"  VRAM: {vram_used:.1f}GB / {vram_total:.1f}GB ({vram_used/vram_total*100:.0f}%)")

    # Warmup
    print("\n[2] Warmup generation...")
    warmup_prompts = make_test_prompts(4)
    engine.generate_batch(warmup_prompts, max_new_tokens=32)
    print("  Done.")

    # Profile tokenization + padding waste
    print("\n[3] Tokenization & Padding Analysis (batch=16)...")
    prompts_16 = make_test_prompts(16)
    inputs, _ = profile_tokenization(engine, prompts_16)

    # Profile generation
    print("\n[4] Generation (batch=16, max_new_tokens=256)...")
    profile_generation(engine, inputs, max_new_tokens=256)

    # Greedy vs sampling
    print("\n[5] Greedy vs Sampling comparison (batch=16)...")
    prompts_8 = make_test_prompts(8)
    tokenizer = engine._tokenizer
    formatted = [
        tokenizer.apply_chat_template(
            build_chat_messages(p), tokenize=False, add_generation_prompt=True
        )
        for p in prompts_8
    ]
    inputs_8 = tokenizer(formatted, return_tensors="pt", padding=True, truncation=True)
    inputs_8 = {k: v.to(engine._model.device) for k, v in inputs_8.items() if k != "token_type_ids"}
    profile_greedy_vs_sampling(engine, inputs_8, max_new_tokens=256)

    # Batch size sweep
    profile_batch_sizes(engine, max_new_tokens=256)

    # Realistic workload profile
    print("\n" + "="*60)
    print("REALISTIC WORKLOAD (max_new_tokens=4096, batch=16)")
    print("="*60)
    prompts_real = make_test_prompts(16)
    tokenizer = engine._tokenizer
    formatted = [
        tokenizer.apply_chat_template(
            build_chat_messages(p), tokenize=False, add_generation_prompt=True
        )
        for p in prompts_real
    ]
    inputs_real = tokenizer(formatted, return_tensors="pt", padding=True, truncation=True)
    inputs_real = {k: v.to(engine._model.device) for k, v in inputs_real.items() if k != "token_type_ids"}
    profile_generation(engine, inputs_real, max_new_tokens=4096)

    engine.unload()
    print("\nDone.")


if __name__ == "__main__":
    main()
