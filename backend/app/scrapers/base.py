"""Shared scraping utilities: robots.txt rules, HTML helpers, raw JSONL storage."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit

from bs4 import BeautifulSoup


class BlockedError(RuntimeError):
    """The site refused automated access (403, CAPTCHA, challenge that never clears).
    We stop instead of trying to get around it."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RobotsRules:
    """Minimal robots.txt matcher with Google-style `*` and `$` support.

    The standard-library parser ignores wildcards, and both target sites use them.
    Rule precedence: longest matching pattern wins; ties go to Allow.
    """

    def __init__(self, text: str, user_agent: str = "*") -> None:
        self.rules: list[tuple[bool, re.Pattern[str], int]] = []
        groups: dict[str, list[tuple[bool, str]]] = {}
        current: list[str] = []
        last_was_agent = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, value = (part.strip() for part in line.split(":", 1))
            key = key.lower()
            if key == "user-agent":
                if not last_was_agent:
                    current = []
                current.append(value.lower())
                groups.setdefault(value.lower(), [])
                last_was_agent = True
            elif key in ("allow", "disallow"):
                last_was_agent = False
                if value:
                    for agent in current:
                        groups[agent].append((key == "allow", value))
            else:
                last_was_agent = False
        agent = user_agent.lower()
        chosen = groups.get(agent) if agent in groups else groups.get("*", [])
        for allow, pattern in chosen or []:
            regex = re.escape(pattern).replace(r"\*", ".*")
            if regex.endswith(r"\$"):
                regex = regex[:-2] + "$"
            self.rules.append((allow, re.compile(regex), len(pattern)))

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        best: tuple[int, bool] | None = None
        for allow, regex, length in self.rules:
            if regex.match(path) and (best is None or length > best[0] or (length == best[0] and allow)):
                best = (length, allow)
        return True if best is None else best[1]


_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def extract_next_data(html: str) -> dict[str, Any] | None:
    """Next.js embeds the page's server-side props as JSON. Parsing this is far more
    stable than CSS selectors, which break whenever the site is restyled."""
    match = _NEXT_DATA_RE.search(html)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


_STRIP_TAGS = ["script", "style", "noscript", "svg", "header", "footer", "form", "nav", "select", "iframe"]


def html_to_text(html: str) -> str:
    """Visible text of a page or HTML fragment, one logical line per block."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(_STRIP_TAGS):
        tag.decompose()
    root = soup.body or soup
    lines = [line.strip() for line in root.get_text("\n", strip=True).splitlines()]
    return "\n".join(line for line in lines if line)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
    return count


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
