import html
import re
from pathlib import Path

_TERMS_PATH = Path(__file__).resolve().parents[1] / "TERMS_AND_CONDITIONS.md"


def _render_markdown_line(line):
    line = line.strip()
    if not line:
        return ""
    if line.startswith("## "):
        return f"<b>{html.escape(line[3:], quote=False)}</b>"
    if line.startswith("# "):
        return f"<b>{html.escape(line[2:], quote=False)}</b>"
    if line.startswith("- "):
        rendered = "• " + html.escape(line[2:], quote=False)
    else:
        rendered = html.escape(line, quote=False)
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", rendered)


def get_terms_message():
    try:
        terms = _TERMS_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return None

    rendered_terms = "\n".join(_render_markdown_line(line) for line in terms.splitlines())
    return (
        "📜 <b>Please read and accept these Terms &amp; Conditions before using the bot.</b>\n\n"
        f"{rendered_terms}\n\n"
        "<i>Tap Accept to continue or Reject to stop.</i>"
    )