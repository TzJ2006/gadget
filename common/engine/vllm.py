"""vLLM translation backend."""

from __future__ import annotations

import logging
import sys

from common.engine.base import SAMPLING_DEFAULTS, TranslationEngine, build_chat_messages

logger = logging.getLogger(__name__)


class VLLMEngine(TranslationEngine):
    """vLLM offline batch inference backend."""

    def __init__(self, model_id: str) -> None:
        super().__init__(model_id)
        self._llm = None
        self._tokenizer = None

    def load(self) -> None:
        if self._llm is not None:
            return
        from vllm import LLM
        from transformers import AutoTokenizer

        logger.info("Loading model %s with vLLM...", self.model_id)
        self._llm = LLM(
            model=self.model_id,
            trust_remote_code=True,
            dtype="half",
            max_model_len=8192,
        )
        self._tokenizer = AutoTokenizer.from_pretrained(
            self.model_id, trust_remote_code=True,
        )
        logger.info("vLLM engine ready")

    def is_alive(self) -> bool:
        if self._llm is None:
            return False
        try:
            return self._llm.llm_engine is not None
        except Exception:
            return False

    def generate_batch(
        self,
        prompts: list[str],
        *,
        max_new_tokens: int = 4096,
    ) -> list[str]:
        from vllm import SamplingParams

        if self._llm is None or self._tokenizer is None:
            raise RuntimeError("Engine not loaded — call load() first")

        formatted = [
            self._tokenizer.apply_chat_template(
                build_chat_messages(p), tokenize=False, add_generation_prompt=True,
            )
            for p in prompts
        ]

        params = SamplingParams(
            max_tokens=max_new_tokens,
            top_k=SAMPLING_DEFAULTS["top_k"],
            top_p=SAMPLING_DEFAULTS["top_p"],
            temperature=SAMPLING_DEFAULTS["temperature"],
            repetition_penalty=SAMPLING_DEFAULTS["repetition_penalty"],
        )

        outputs = self._llm.generate(formatted, params)
        return [out.outputs[0].text.strip() for out in outputs]

    def unload(self) -> None:
        if self._llm is None:
            return
        del self._llm
        del self._tokenizer
        self._llm = None
        self._tokenizer = None
        logger.info("vLLM engine unloaded")


def _vllm_available() -> bool:
    if sys.platform == "win32":
        return False
    try:
        import vllm  # noqa: F401
        return True
    except ImportError:
        return False
