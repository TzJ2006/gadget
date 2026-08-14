"""DiskCache UTF-8 round-trip."""

from common.cache import DiskCache


def test_put_get_roundtrip_non_ascii(tmp_path):
    cache = DiskCache(tmp_path)
    payload = {"title": "论文摘要", "note": "café — 日本語"}
    cache.put("papers", "arxiv:2301.00001", payload)
    assert cache.get("papers", "arxiv:2301.00001") == payload
