"""Bounded native Gemma chat. Caller must hold the model-access lease."""
import re
import time
import uuid
from dataclasses import dataclass, field

class LLMError(RuntimeError):
    pass


class LLMTimeout(LLMError):
    pass


class LLMRefused(LLMError):
    """The configured lease API is missing or denied the call. Nothing was sent."""


@dataclass
class LLMResult:
    text: str
    request_id: str
    model: str
    diagnostics: dict = field(default_factory=dict)


def complete(endpoint, model, messages, timeout, *, schema=None, max_tokens=None):
    import httpx
    if max_tokens is not None and (type(max_tokens) is not int or max_tokens <= 0):
        raise ValueError("max_tokens must be a positive integer")
    deadline = time.monotonic() + timeout
    try:
        resident = httpx.get(endpoint + "/api/ps", timeout=min(timeout, 10))
        if resident.status_code >= 400:
            raise LLMRefused("无法核对 Ollama 当前驻留模型，未加载新模型")
        running = resident.json().get("models")
        if not isinstance(running, list):
            raise LLMRefused("Ollama 驻留模型列表无效")
        for item in running:
            name = str(item.get("name") or item.get("model") or "")
            if name == model:
                continue
            parameter_size = str((item.get("details") or {}).get("parameter_size") or name)
            size = re.search(r"(?i)(\d+(?:\.\d+)?)\s*([bm])(?:\b|_)", parameter_size)
            if not size or (size.group(2).lower() == "b" and float(size.group(1)) > 10):
                raise LLMRefused("GPU 上有其他大模型或大小未知的模型；请先卸载该模型")
    except httpx.TimeoutException as exc:
        raise LLMTimeout("本地模型调用超时") from exc
    except httpx.HTTPError as exc:
        raise LLMError("无法连接本地 Ollama") from exc
    except (ValueError, TypeError, AttributeError) as exc:
        raise LLMRefused("无法核对 Ollama 驻留模型") from exc
    attempts = []
    for attempt in range(2):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise LLMTimeout("本地模型总等待时间已用完")
        thinking = attempt == 0
        # Reserve time for one same-model final-answer recovery. Never expose
        # raw thinking or mislabel a token-truncated answer as complete.
        call_timeout = min(180.0, remaining * .7) if thinking else remaining
        current = [dict(m) for m in messages]
        if not thinking:
            instruction = ("本次思考预算已经用完。请直接给出你有把握的回答；复杂问题可给出部分结论并说明"
                           "尚未解决的部分，不要编造证明或答案，不再从头长篇推演。保留原人设、权限和输出格式。")
            current.insert(0, {'role': 'system', 'content': instruction})
        started = time.monotonic()
        token_limit = 8192 if thinking else 4096
        if max_tokens is not None:
            token_limit = min(token_limit, max_tokens)
        try:
            response = httpx.post(endpoint + "/api/chat", json={
                "model": model, "messages": current, "think": thinking, "stream": False,
                **({"format": schema} if schema else {}),
                "options": {"temperature": 1.0, "num_predict": token_limit},
            }, timeout=call_timeout)
        except httpx.TimeoutException as exc:
            attempts.append({'thinking': thinking, 'outcome': 'timeout',
                             'seconds': round(time.monotonic() - started, 3)})
            if thinking:
                continue
            raise LLMTimeout("Gemma 思考和直接回答均未在预算内完成") from exc
        except httpx.HTTPError as exc:
            raise LLMError("无法连接本地 Ollama") from exc
        if response.status_code >= 400:
            raise LLMError(f"Ollama HTTP {response.status_code}；模型未被自动替换")
        try:
            body = response.json()
            message = body['message']
            content = message.get('content', '')
            if (body.get('error') or body.get('done') is not True
                    or message.get('tool_calls') or not isinstance(content, str)):
                raise ValueError('invalid completion')
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise LLMError("Ollama 返回格式无效或请求未正常结束") from exc
        incomplete = body.get('done_reason') == 'length' or not content.strip()
        attempts.append({'thinking': thinking, 'seconds': round(time.monotonic() - started, 3),
                         'outcome': 'incomplete' if incomplete else 'complete',
                         'stop_reason': body.get('done_reason'), 'output_tokens': body.get('eval_count'),
                         'input_tokens': body.get('prompt_eval_count'), 'answer_chars': len(content)})
        if not incomplete:
            return LLMResult(content, uuid.uuid4().hex, model,
                             {'attempts': attempts, 'direct_answer_recovery': not thinking})
        if not thinking:
            raise LLMError("Gemma 在生成预算内仍未返回完整正文（停止原因："
                           + str(body.get('done_reason'))[:30] + "）；请缩小问题范围")
    raise LLMTimeout("本地模型未能在预算内完成")

