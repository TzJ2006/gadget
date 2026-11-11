import httpx
import pytest

from common.ollama_chat import complete, LLMError


@pytest.mark.parametrize("limit,expected", [(None, [8192, 4096]), (1000, [1000, 1000])])
def test_token_limit_applies_to_thinking_and_same_model_recovery(monkeypatch, limit, expected):
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: httpx.Response(200, json={"models": []}))
    calls = []

    def post(url, **kwargs):
        calls.append(kwargs["json"])
        return httpx.Response(200, json={"done": True,
            "done_reason": "length" if len(calls) == 1 else "stop",
            "message": {"content": "" if len(calls) == 1 else '{"summary":"complete"}'}})

    monkeypatch.setattr(httpx, "post", post)
    result = complete("http://127.0.0.1:19999", "fake", [], 60, schema="json", max_tokens=limit)
    assert result.text == '{"summary":"complete"}'
    assert [body["options"]["num_predict"] for body in calls] == expected
    assert [body["model"] for body in calls] == ["fake", "fake"]


def test_truncated_json_is_not_accepted_to_meet_the_budget(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: httpx.Response(200, json={"models": []}))
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: httpx.Response(200, json={
        "done": True, "done_reason": "length", "message": {"content": '{"summary":'}}))
    with pytest.raises(LLMError, match="完整正文"):
        complete("http://127.0.0.1:19999", "fake", [], 60, schema="json", max_tokens=1000)


@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
def test_invalid_budget_does_not_contact_the_backend(monkeypatch, limit):
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: pytest.fail("must not contact backend"))
    with pytest.raises(ValueError, match="positive integer"):
        complete("http://127.0.0.1:19999", "fake", [], 60, max_tokens=limit)
