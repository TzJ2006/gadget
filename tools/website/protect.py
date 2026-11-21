#!/usr/bin/env python3
"""Password-protect the report pages (bugJournal) in the built site.

GitHub Pages serves static files from a public repository, so there is no server to check a password.
Each report page is therefore replaced by a small unlock page that carries the original page encrypted
(AES-256-GCM, key = PBKDF2-SHA256 of the password) and decrypts it in the browser.

Report text also leaks through feeds, the search index and list cards on other pages; those entries are
removed, and the build is refused if a link to a single report is still readable anywhere else.

Password: environment variable GADGET_SITE_PASSWORD, else "website": {"report_password": "..."} in the
repo-root config.json (never committed). No password means no publish.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import sys
from pathlib import Path

SECTION = "bugjournal"  # Hugo lowercases the URL of content/bugJournal
# ponytail: one fixed public salt so a browser that unlocked once keeps working after every publish;
# switch to a per-build salt (and re-entering the password) if targeted precomputation ever matters.
SALT = b"gadget-site-reports-v1"
ITERATIONS = 600_000
REPORT_LINK = re.compile(r"/%s/[^/\"'<>\s]+/[^/\"'<>\s]+" % SECTION, re.IGNORECASE)  # /bugjournal/daily/2026-01-01
ARTICLE = re.compile(r"<article\b.*?</article>", re.DOTALL)
ITEM = re.compile(r"<item>.*?</item>\s*", re.DOTALL)

UNLOCK_PAGE = """<!doctype html>
<html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>需要密码 · Password required</title>
<style>body{font:16px system-ui,sans-serif;display:grid;place-items:center;min-height:100vh;margin:0;background:#f5f5f7;color:#1d1d1f}
form{background:#fff;padding:32px;border-radius:16px;box-shadow:0 2px 16px #0001;max-width:320px;width:calc(100% - 96px)}
input,button{font:inherit;box-sizing:border-box;width:100%;padding:10px 12px;margin-top:12px;border-radius:8px;border:1px solid #c7c7cc}
button{background:#1d1d1f;color:#fff;border:0;cursor:pointer}#e{color:#c00;min-height:1.4em;margin:12px 0 0}
@media(prefers-color-scheme:dark){body{background:#1d1d1f;color:#f5f5f7}form{background:#2c2c2e}button{background:#f5f5f7;color:#1d1d1f}}</style></head>
<body><form id="f"><label for="p">这页内容需要密码<br>This page needs a password</label>
<input id="p" type="password" autocomplete="current-password" autofocus required>
<button>打开 · Open</button><p id="e" role="alert"></p></form>
<script>
const DATA="__DATA__",SALT="__SALT__",ITER=__ITER__,SLOT="report-key";
const bytes=s=>Uint8Array.from(atob(s),c=>c.charCodeAt(0));
async function decrypt(raw){const key=await crypto.subtle.importKey("raw",raw,"AES-GCM",false,["decrypt"]);const d=bytes(DATA);
return new TextDecoder().decode(await crypto.subtle.decrypt({name:"AES-GCM",iv:d.slice(0,12)},key,d.slice(12)))}
async function derive(password){const m=await crypto.subtle.importKey("raw",new TextEncoder().encode(password),"PBKDF2",false,["deriveBits"]);
return new Uint8Array(await crypto.subtle.deriveBits({name:"PBKDF2",hash:"SHA-256",salt:bytes(SALT),iterations:ITER},m,256))}
// Writing before this page has finished loading would append to it instead of replacing it.
async function show(html){if(document.readyState!=="complete")await new Promise(r=>addEventListener("load",r));document.open();document.write(html);document.close()}
function saved(){try{return localStorage.getItem(SLOT)}catch{return null}}
(async()=>{const k=saved();if(!k)return;try{await show(await decrypt(bytes(k)))}catch{try{localStorage.removeItem(SLOT)}catch{}}})();
document.getElementById("f").onsubmit=async e=>{e.preventDefault();const note=document.getElementById("e");note.textContent="";
try{const raw=await derive(document.getElementById("p").value),html=await decrypt(raw);
try{localStorage.setItem(SLOT,btoa(String.fromCharCode(...raw)))}catch{}await show(html)}
catch{note.textContent="密码不对 · Wrong password"}};
</script></body></html>
"""


def configured_password() -> str:
    password = os.environ.get("GADGET_SITE_PASSWORD", "")
    if not password:
        path = Path(os.environ.get("GADGET_CONFIG") or Path(__file__).resolve().parents[2] / "config.json")
        try:
            password = json.loads(path.read_text(encoding="utf-8")).get("website", {}).get("report_password", "")
        except (OSError, ValueError, AttributeError):
            password = ""
    return str(password)


def derive_key(password: str) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), SALT, ITERATIONS)


def encrypt(key: bytes, plain: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    # The nonce depends on the content, so an unchanged page encrypts to the same bytes (no churn in the
    # published repository) and two different pages never share a nonce.
    nonce = hmac.new(hashlib.sha256(key + b"nonce").digest(), plain, "sha256").digest()[:12]
    return nonce + AESGCM(key).encrypt(nonce, plain, None)


def decrypt(key: bytes, data: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    return AESGCM(key).decrypt(data[:12], data[12:], None)


def unlock_page(key: bytes, plain: bytes) -> str:
    return (UNLOCK_PAGE.replace("__DATA__", base64.b64encode(encrypt(key, plain)).decode())
            .replace("__SALT__", base64.b64encode(SALT).decode()).replace("__ITER__", str(ITERATIONS)))


def protect(public: Path, password: str) -> int:
    """Encrypt every report page under ``public``; return how many. Raises if report text could still be read."""
    sections = [p for p in public.rglob("*") if p.is_dir() and p.name.lower() == SECTION]
    if not sections:
        return 0
    if not password:
        raise RuntimeError('没有设置报告密码：在 gadget 的 config.json 里加 "website": {"report_password": "你的密码"}，'
                           "或设置环境变量 GADGET_SITE_PASSWORD。未加密的报告不会发布。")
    key = derive_key(password)
    count = 0
    for section in sections:
        for path in section.rglob("*"):
            if path.suffix == ".html":
                path.write_text(unlock_page(key, path.read_bytes()), encoding="utf-8")
                count += 1
            elif path.suffix in (".xml", ".json"):  # feeds of the section repeat the report text
                path.unlink()
    inside = lambda p: any(s in p.parents for s in sections)
    drop = lambda pattern, text: pattern.sub(lambda m: "" if REPORT_LINK.search(m.group()) else m.group(), text)
    for path in public.rglob("*"):
        if path.suffix not in (".html", ".xml", ".json") or inside(path) or ".git" in path.parts or path.name == "sitemap.xml":
            continue
        text = path.read_text(encoding="utf-8")
        if not REPORT_LINK.search(text):
            continue
        if path.suffix == ".json":  # PaperMod search index: a list of pages
            entries = json.loads(text)
            text = json.dumps([e for e in entries if not REPORT_LINK.search(json.dumps(e))], ensure_ascii=False)
        else:
            text = drop(ITEM if path.suffix == ".xml" else ARTICLE, text)
        if REPORT_LINK.search(text):
            raise RuntimeError(f"{path} 里还能读到指向单篇报告的内容，已停止发布。")
        path.write_text(text, encoding="utf-8")
    return count


if __name__ == "__main__":
    try:
        print(f" -- 已加密 {protect(Path(sys.argv[1]), configured_password())} 个报告页面")
    except RuntimeError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
