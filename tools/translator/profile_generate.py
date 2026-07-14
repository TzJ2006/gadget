"""Profile a single-chunk (batch=1) translation to show where time goes.

Run:  PYTHONPATH=D:/Github/gadget /d/Miniconda3/envs/AI/python.exe translator/profile_generate.py
"""
from __future__ import annotations

import time

import torch

from common.engine import SAMPLING_DEFAULTS, create_engine
from common.translation import build_translation_prompt

PARAGRAPH = (
    "The robot learns manipulation skills from demonstrations. "
    "Each policy is trained end to end with reinforcement learning. "
    "We evaluate on a suite of tabletop tasks and report success rates. "
) * 6  # ~ one realistic batch=1 chunk, well under 7000 chars


def sync():
    if torch.cuda.is_available():
        torch.cuda.synchronize()


def main() -> None:
    eng = create_engine()._engine  # unwrap proxy to reach _model/_tokenizer
    tok, model = eng._tokenizer, eng._model
    dev = model.device
    print(f"device={dev} dtype={model.dtype} chars={len(PARAGRAPH)}")

    prompt = build_translation_prompt(PARAGRAPH, "zh", markdown=True)
    formatted = tok.apply_chat_template(
        [{"role": "user", "content": prompt}], tokenize=False, add_generation_prompt=True
    )

    # warmup (kernels, autotune, custom-code import)
    inputs = tok([formatted], return_tensors="pt", padding=True, truncation=True).to(dev)
    inputs.pop("token_type_ids", None)
    with torch.no_grad():
        model.generate(**inputs, max_new_tokens=8, do_sample=False)
    sync()

    # 1) tokenize
    sync(); t0 = time.perf_counter()
    inputs = tok([formatted], return_tensors="pt", padding=True, truncation=True).to(dev)
    inputs.pop("token_type_ids", None)
    sync(); t_tok = time.perf_counter() - t0
    prompt_len = inputs["input_ids"].shape[1]

    # 2) generate (real sampling settings)
    sync(); t0 = time.perf_counter()
    with torch.no_grad():
        out = model.generate(
            **inputs, max_new_tokens=512, do_sample=True,
            top_k=SAMPLING_DEFAULTS["top_k"], top_p=SAMPLING_DEFAULTS["top_p"],
            temperature=SAMPLING_DEFAULTS["temperature"],
            repetition_penalty=SAMPLING_DEFAULTS["repetition_penalty"],
        )
    sync(); t_gen = time.perf_counter() - t0
    n_new = out.shape[1] - prompt_len

    # 3) decode
    t0 = time.perf_counter()
    tok.decode(out[0, prompt_len:], skip_special_tokens=True, clean_up_tokenization_spaces=False)
    t_dec = time.perf_counter() - t0

    print(f"\nprompt_len={prompt_len} tok | generated={n_new} tok")
    print(f"tokenize : {t_tok*1000:8.1f} ms")
    print(f"generate : {t_gen*1000:8.1f} ms  ({n_new/t_gen:6.1f} tok/s, {t_gen/n_new*1000:5.1f} ms/tok)")
    print(f"decode   : {t_dec*1000:8.1f} ms")

    # 4) torch profiler — where inside generate the wall time lands
    # (static cache / torch.compile would need Triton, absent on this Windows box —
    #  see perf_report.md; the only working speedup is batching → micro-chunking.)
    print("\n--- torch.profiler (top ops, 128-step generate) ---")
    from torch.profiler import ProfilerActivity, profile
    acts = [ProfilerActivity.CPU]
    if torch.cuda.is_available():
        acts.append(ProfilerActivity.CUDA)
    with torch.no_grad(), profile(activities=acts) as prof:
        model.generate(
            **inputs, max_new_tokens=128, do_sample=True,
            top_k=SAMPLING_DEFAULTS["top_k"], top_p=SAMPLING_DEFAULTS["top_p"],
            temperature=SAMPLING_DEFAULTS["temperature"],
            repetition_penalty=SAMPLING_DEFAULTS["repetition_penalty"],
        )
    sort_key = "cuda_time_total" if torch.cuda.is_available() else "cpu_time_total"
    print(prof.key_averages().table(sort_by=sort_key, row_limit=12))


if __name__ == "__main__":
    main()
