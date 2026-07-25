"""Minimal Markdown → HTML for dual-flavor pasting.

Covers exactly the subset emitted by Voooxly modes (##/###, bullets, numbered
lists, checkboxes, `code`, residual **bold**) — it's not a general Markdown
parser. The HTML goes to the clipboard ALONGSIDE the plain text: Mail/Gmail/Notion
paste real titles and lists; Terminal, Obsidian, or an IDE take the plain flavor
and see the raw Markdown. Each app picks its flavor.
"""
from __future__ import annotations

import html as _html
import re

_BOLD = re.compile(r"\*\*(.+?)\*\*")
_CODE = re.compile(r"`([^`]+)`")
_CHECK = re.compile(r"^- \[( |x|X)\] (.*)$")
_ORDERED = re.compile(r"^\d+[.)] (.*)$")


def _inline(s: str) -> str:
    s = _html.escape(s, quote=False)
    s = _BOLD.sub(r"<b>\1</b>", s)
    s = _CODE.sub(r"<code>\1</code>", s)
    return s


def markdown_to_html(md: str) -> str:
    out: list[str] = []
    open_list: str | None = None

    def close_list() -> None:
        nonlocal open_list
        if open_list:
            out.append(f"</{open_list}>")
            open_list = None

    def ensure_list(kind: str) -> None:
        nonlocal open_list
        if open_list != kind:
            close_list()
            out.append(f"<{kind}>")
            open_list = kind

    for raw in (md or "").splitlines():
        s = raw.strip()
        if not s:
            close_list()
            continue
        if s.startswith("### "):
            close_list()
            out.append(f"<h3>{_inline(s[4:])}</h3>")
            continue
        if s.startswith("## "):
            close_list()
            out.append(f"<h2>{_inline(s[3:])}</h2>")
            continue
        if s.startswith("# "):
            close_list()
            out.append(f"<h2>{_inline(s[2:])}</h2>")
            continue
        m = _CHECK.match(s)
        if m:
            ensure_list("ul")
            mark = "☑" if m.group(1).lower() == "x" else "☐"
            out.append(f"<li>{mark} {_inline(m.group(2))}</li>")
            continue
        if s.startswith("- ") or s.startswith("* "):
            ensure_list("ul")
            out.append(f"<li>{_inline(s[2:])}</li>")
            continue
        m = _ORDERED.match(s)
        if m:
            ensure_list("ol")
            out.append(f"<li>{_inline(m.group(1))}</li>")
            continue
        close_list()
        out.append(f"<p>{_inline(s)}</p>")
    close_list()
    return "\n".join(out)
