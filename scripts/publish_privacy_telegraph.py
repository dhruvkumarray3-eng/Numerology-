"""Publish PRIVACY_POLICY.md to Telegraph and print the public URL.

Usage:
    python scripts/publish_privacy_telegraph.py [--update <path>]

The first run creates a Telegraph account and stores its access token in
.telegraph_token (git-ignored) so later runs update the same page instead of
creating a new one.
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOKEN_FILE = ROOT / ".telegraph_token"
API = "https://api.telegra.ph"

AUTHOR = "Vendor Sellings"
SHORT_NAME = "vendor-sellings-privacy"


def api_call(method, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{API}/{method}",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        out = json.loads(resp.read().decode())
    if not out.get("ok"):
        raise RuntimeError(f"Telegraph {method} failed: {out}")
    return out["result"]


def get_token():
    if TOKEN_FILE.exists():
        tok = TOKEN_FILE.read_text().strip()
        if tok:
            return tok
    res = api_call("createAccount", {
        "short_name": SHORT_NAME,
        "author_name": AUTHOR,
        "author_url": "https://t.me/Vendor_masterz",
    })
    tok = res["access_token"]
    TOKEN_FILE.write_text(tok)
    return tok


def inline(text):
    """Split **bold** spans into Telegraph nodes."""
    nodes = []
    parts = text.split("**")
    for i, part in enumerate(parts):
        if not part:
            continue
        if i % 2 == 1:
            nodes.append({"tag": "b", "children": [part]})
        else:
            nodes.append(part)
    return nodes or [""]


def build_nodes(md_text):
    nodes = []
    bullets = []

    def flush_bullets():
        if bullets:
            nodes.append({
                "tag": "ul",
                "children": [{"tag": "li", "children": inline(b)} for b in bullets],
            })
            bullets.clear()

    seen_h1 = False
    for raw in md_text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()

        if not stripped:
            flush_bullets()
            continue
        # The page title already shows the H1 - skip it to avoid duplication.
        if stripped.startswith("# ") and not seen_h1:
            seen_h1 = True
            continue
        if stripped == "---":
            flush_bullets()
            nodes.append({"tag": "hr"})
            continue
        if stripped.startswith("### "):
            flush_bullets()
            nodes.append({"tag": "h4", "children": inline(stripped[4:])})
            continue
        if stripped.startswith("## "):
            flush_bullets()
            nodes.append({"tag": "h3", "children": inline(stripped[3:])})
            continue
        if stripped.startswith("# "):
            flush_bullets()
            nodes.append({"tag": "h3", "children": inline(stripped[2:])})
            continue
        if stripped.startswith("- "):
            bullets.append(stripped[2:])
            continue
        if stripped[0].isdigit() and ". " in stripped[:4]:
            bullets.append(stripped.split(". ", 1)[1])
            continue
        flush_bullets()
        nodes.append({"tag": "p", "children": inline(stripped)})

    flush_bullets()
    return nodes


def main():
    md = (ROOT / "PRIVACY_POLICY.md").read_text(encoding="utf-8")
    title = "Privacy Policy — Vendor Sellings"
    content = build_nodes(md)
    token = get_token()

    existing = TOKEN_FILE.with_suffix(".path")
    base = {
        "access_token": token,
        "title": title,
        "author_name": AUTHOR,
        "author_url": "https://t.me/Vendor_masterz",
        "content": json.dumps(content),
        "return_content": False,
    }

    if existing.exists() and existing.read_text().strip():
        # Edit the page we already published so the URL stays stable.
        payload = dict(base, path=existing.read_text().strip())
        res = api_call("editPage", payload)
    else:
        res = api_call("createPage", base)

    existing.write_text(res["path"])
    print(res["url"])


if __name__ == "__main__":
    main()
