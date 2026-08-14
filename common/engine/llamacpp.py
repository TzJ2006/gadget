"""llama-cpp-python (GGUF) translation backend."""

from __future__ import annotations

import logging

from common.engine.base import SAMPLING_DEFAULTS, TranslationEngine, build_chat_messages

logger = logging.getLogger(__name__)


class LlamaCppEngine(TranslationEngine):
    """llama-cpp-python backend for GGUF models - fast, low-memory, no PyTorch needed."""

    def __init__(self, model_id: str, n_gpu_layers: int = -1) -> None:
        super().__init__(model_id)
        self._n_gpu_layers = n_gpu_layers
        self._llm = None
        self._chat_template = None

    def load(self) -> None:
        if self._llm is not None:
            return
        from llama_cpp import Llama

        gguf_path = self._resolve_gguf_path()
        logger.info("Loading GGUF model from %s (n_gpu_layers=%d)...", gguf_path, self._n_gpu_layers)

        self._llm = Llama(
            model_path=str(gguf_path),
            # translate_body feeds chunks up to split_large_text's 7000-char ceiling
            # (~4.5k tokens CJK) and asks for up to 4096 output tokens. n_ctx=4096 could
            # not hold prompt+output, so the first/largest chunk overflowed and the head
            # of long docs was silently dropped. 16k fits both with headroom (model
            # trains at 262144). ponytail: bump toward chunk_ceiling+max_new_tokens if you
            # raise either.
            n_ctx=16384,
            n_gpu_layers=self._n_gpu_layers,
            verbose=False,
        )
        logger.info("GGUF model loaded")

    def _resolve_gguf_path(self) -> str:
        """Resolve model_id to a local .gguf file path.

        Supports: direct .gguf path, or HuggingFace repo id (auto-downloads via huggingface_hub).
        """
        import pathlib

        if pathlib.Path(self.model_id).suffix == ".gguf":
            return self.model_id

        from huggingface_hub import hf_hub_download, list_repo_files

        files = list_repo_files(self.model_id)
        gguf_files = [f for f in files if f.endswith(".gguf")]
        if not gguf_files:
            raise FileNotFoundError(f"No .gguf files found in repo {self.model_id}")

        # Prefer Q4_K_M for balance of speed and quality, else first available
        preferred = [f for f in gguf_files if "Q4_K_M" in f.upper()]
        chosen = preferred[0] if preferred else gguf_files[0]

        logger.info("Downloading %s/%s...", self.model_id, chosen)
        return hf_hub_download(repo_id=self.model_id, filename=chosen)

    def generate_batch(
        self,
        prompts: list[str],
        *,
        max_new_tokens: int = 4096,
    ) -> list[str]:
        if self._llm is None:
            raise RuntimeError("Engine not loaded — call load() first")

        results: list[str] = []
        for prompt in prompts:
            messages = build_chat_messages(prompt)
            output = self._llm.create_chat_completion(
                messages=messages,
                max_tokens=max_new_tokens,
                top_k=SAMPLING_DEFAULTS["top_k"],
                top_p=SAMPLING_DEFAULTS["top_p"],
                temperature=SAMPLING_DEFAULTS["temperature"],
                repeat_penalty=SAMPLING_DEFAULTS["repetition_penalty"],
            )
            text = output["choices"][0]["message"]["content"] or ""
            results.append(text.strip())
        return results

    def unload(self) -> None:
        if self._llm is None:
            return
        del self._llm
        self._llm = None
        logger.info("GGUF engine unloaded")


def _llamacpp_available() -> bool:
    try:
        import llama_cpp  # noqa: F401
        return True
    except ImportError:
        return False
