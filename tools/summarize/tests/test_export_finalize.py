"""`_finalized` must not freeze a day whose content changed.

The flag is the gate on --export-past: a date marked finalized is never
revisited (daily_export.py's pending-dates calculation), and it travels inside
the log file to other machines, where daily_merge reads it to decide what to
skip. So marking a day final on a criterion weaker than its content is how a
stale export becomes permanent.

The criterion used to be conversation-count equality. The merge that runs just
above it keys on (source, project, timestamp), so a conversation that gained
messages keeps its key and leaves the count unchanged -- the exact case where
counting says "nothing happened" and the content says otherwise.
"""

import json
from datetime import date, timedelta

from summarize.daily_export import _conversations_hash


def _conv(ts, body):
    return {"source": "claude_code", "project": "p", "timestamp": ts,
            "messages": body}


def test_identical_conversations_hash_the_same():
    a = [_conv("10:00", ["hi"]), _conv("11:00", ["yo"])]
    b = [_conv("10:00", ["hi"]), _conv("11:00", ["yo"])]
    assert _conversations_hash(a) == _conversations_hash(b)


def test_a_conversation_that_grew_changes_the_hash():
    """Same count, same keys, different content -- the case counting missed."""
    before = [_conv("10:00", ["hi"])]
    after = [_conv("10:00", ["hi", "and one more turn"])]
    assert len(before) == len(after), "the premise is that the count is equal"
    assert _conversations_hash(before) != _conversations_hash(after)


def test_an_added_conversation_changes_the_hash():
    before = [_conv("10:00", ["hi"])]
    after = before + [_conv("11:00", ["new"])]
    assert _conversations_hash(before) != _conversations_hash(after)


def test_key_order_does_not_change_the_hash():
    """Detect changed content, not changed serialization order."""
    a = [{"source": "x", "timestamp": "10:00", "messages": []}]
    b = [{"messages": [], "timestamp": "10:00", "source": "x"}]
    assert _conversations_hash(a) == _conversations_hash(b)


def test_the_finalize_rule_uses_the_hash_not_the_count():
    import inspect
    from summarize import daily_export

    src = inspect.getsource(daily_export.cmd_export)
    assert "_conversations_hash" in src
    assert "new_count == old_count" not in src, (
        "count equality is back: a conversation that grew would be frozen")
