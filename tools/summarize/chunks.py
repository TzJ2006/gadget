"""Lossless message-boundary splitting shared by report entrypoints."""
def render_message(message: dict) -> str:
    return f"[{message['seq']}] {message['role']}: {message['text']}\n"


def chunk_messages(messages: list[dict], budget: int, overlap: int) -> list[list[dict]]:
    """Split one conversation on message boundaries. An oversized message is split by characters."""
    if budget < 1 or overlap < 0 or overlap >= budget:
        raise ValueError("chunk budget must be positive and larger than the overlap")
    chunks: list[list[dict]] = []
    current: list[dict] = []
    size = 0
    for message in messages:
        rendered = render_message(message)
        if len(rendered) > budget:
            if current:
                chunks.append(current)
                current, size = [], 0
            prefix = f"[{message['seq']}] {message['role']}: "
            room = budget - len(prefix) - 1
            if room < 1:
                raise ValueError("chunk budget is smaller than the message prefix")
            for part in split_text(str(message["text"]), room, min(overlap, room - 1) if room > 1 else 0):
                chunks.append([{**message, "text": part}])
            continue
        if current and size + len(rendered) > budget:
            chunks.append(current)
            current, size = [], 0
        current.append(message)
        size += len(rendered)
    if current:
        chunks.append(current)
    return chunks


def split_text(text: str, budget: int, overlap: int) -> list[str]:
    """Split one string on character boundaries. Adjacent pieces share `overlap` characters."""
    if budget < 1:
        raise ValueError("budget must be positive")
    if overlap < 0 or overlap >= budget:
        raise ValueError("overlap must be smaller than the budget")
    if len(text) <= budget:
        return [text]
    step = budget - overlap
    parts = []
    index = 0
    while index < len(text):
        parts.append(text[index : index + budget])
        if index + budget >= len(text):
            break
        index += step
    return parts


