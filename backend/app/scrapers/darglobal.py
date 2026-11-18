"""DarGlobal scraper.

darglobal.co.uk sits behind a JavaScript challenge, so plain HTTP clients receive an empty
shell. A normal Playwright Chromium (no stealth plugins, no fingerprint spoofing) executes
the page like any browser and gets the content. If a CAPTCHA or a block page ever appears
we raise BlockedError and stop: we do not attempt to get around access controls.

What is collected (all public, all permitted by robots.txt):
  * every project linked from /projects
  * press releases listed under /press (paginated)
  * a small set of corporate pages (about, why-invest, faq, ...)

Run:  python -m app.scrapers.darglobal
"""
import logging
import re
import time
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.sync_api import Browser, Page, TimeoutError as PlaywrightTimeout, sync_playwright

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.scrapers.base import (
    BlockedError,
    RobotsRules,
    extract_next_data,
    html_to_text,
    utc_now,
    write_jsonl,
)

logger = logging.getLogger("scraper.darglobal")

BASE_URL = "https://www.darglobal.co.uk"
RAW_FILE = "darglobal_pages.jsonl"
STATIC_PAGES = [
    "/about",
    "/why-invest",
    "/faq",
    "/one-of-one",
    "/hospitality",
    "/commercial",
    "/luxury-golf-communities",
    "/tokenization",
    "/exclusive-membership",
]
# Non-project links that also appear on the /projects page.
_NON_PROJECT_PREFIXES = (
    "/projects", "/press", "/blog", "/insights", "/investor", "/pay-online", "/get-in-touch",
    "/privacy-policy", "/terms", "/faq", "/why-invest", "/about", "/partners",
)
_BLOCK_MARKERS = re.compile(r"captcha|access denied|request unsuccessful|incident id", re.I)
MAX_PRESS_PAGES = 5


class DarGlobalScraper:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.raw_path = self.settings.raw_dir / RAW_FILE
        self.robots: RobotsRules | None = None
        self.rows: list[dict[str, Any]] = []
        self.stats = {"projects": 0, "press": 0, "pages": 0, "failed": 0, "disallowed": 0}

    def _load(self, page: Page, url: str) -> str | None:
        """Navigate and return rendered HTML once the Next.js payload is present."""
        if self.robots and not self.robots.allowed(url):
            self.stats["disallowed"] += 1
            logger.info("skipped by robots.txt", extra={"url": url})
            return None
        time.sleep(self.settings.scraper_delay_seconds)
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_selector("#__NEXT_DATA__", state="attached", timeout=25_000)
            page.wait_for_timeout(1_200)  # let client-side sections hydrate
        except PlaywrightTimeout:
            html = page.content()
            if _BLOCK_MARKERS.search(html):
                raise BlockedError(f"challenge or block page at {url}")
            logger.warning("timeout", extra={"url": url})
            self.stats["failed"] += 1
            return None
        if response is not None and response.status in (403, 429):
            raise BlockedError(f"HTTP {response.status} at {url}")
        if response is not None and response.status >= 400:
            self.stats["failed"] += 1
            return None
        return page.content()

    @staticmethod
    def clean_text(html: str) -> str:
        """Visible page text with cross-page boilerplate removed.

        Everything from "Other projects" onward is cut on purpose: that carousel names
        *different* developments and would make a project chunk match the wrong query.
        """
        text = html_to_text(html)
        for marker in ("\nOther projects\n", "\nRegister Your Interest\n", "\nWe value our privacy\n"):
            cut = text.find(marker)
            if cut != -1:
                text = text[:cut]
        skip = {"Download Brochure", "BOOK UNIT", "Progress Update", "Gallery", "View All Images",
                "Register Interest", "|", ".", "English", "العربية"}
        lines = [line for line in text.splitlines() if line not in skip]
        return "\n".join(lines).strip()

    def _save(self, kind: str, url: str, html: str, extra: dict[str, Any] | None = None) -> None:
        text = self.clean_text(html)
        if len(text) < 80:
            self.stats["failed"] += 1
            logger.warning("page had no usable text", extra={"url": url})
            return
        soup = BeautifulSoup(html, "html.parser")
        description = soup.find("meta", attrs={"name": "description"})
        row: dict[str, Any] = {
            "kind": kind,
            "url": url,
            "scraped_at": utc_now(),
            "page_title": soup.title.get_text(strip=True) if soup.title else "",
            "meta_description": (description.get("content") or "") if description else "",
            "text": text,
        }
        row.update(extra or {})
        self.rows.append(row)

    def discover_projects(self, html: str) -> list[dict[str, str]]:
        """Project cards on /projects: an anchor whose text is '<location> | <name>'."""
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["header", "footer", "nav"]):
            tag.decompose()
        projects: dict[str, dict[str, str]] = {}
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"].split("?")[0].rstrip("/")
            if not href.startswith("/") or len(href) < 2 or href.startswith(_NON_PROJECT_PREFIXES):
                continue
            # Cards render as separate text nodes: location, name, optional tagline.
            parts = [p.strip() for p in anchor.get_text("\n", strip=True).split("\n") if p.strip()]
            if len(parts) < 2:
                continue
            projects.setdefault(href, {"href": href, "location": parts[0], "name": parts[1]})
        return list(projects.values())

    def scrape_projects(self, page: Page) -> None:
        html = self._load(page, f"{BASE_URL}/projects")
        if html is None:
            raise RuntimeError("could not load the DarGlobal projects page")
        projects = self.discover_projects(html)
        logger.info("projects discovered", extra={"count": len(projects)})
        for project in projects:
            url = urljoin(BASE_URL, project["href"])
            page_html = self._load(page, url)
            if page_html is None:
                continue
            before = len(self.rows)
            self._save("project", url, page_html, {"name": project["name"], "location": project["location"]})
            self.stats["projects"] += len(self.rows) - before

    def scrape_press(self, page: Page) -> None:
        articles: dict[str, dict[str, Any]] = {}
        for number in range(1, MAX_PRESS_PAGES + 1):
            url = f"{BASE_URL}/press" + (f"?page={number}" if number > 1 else "")
            html = self._load(page, url)
            if html is None:
                break
            data = extract_next_data(html) or {}
            items = data.get("props", {}).get("pageProps", {}).get("pressListSSR") or []
            new = [item for item in items if item.get("slug") and item["slug"] not in articles]
            if not new:
                break  # pagination parameter not honoured or last page reached
            for item in new:
                articles[item["slug"]] = item
        logger.info("press releases discovered", extra={"count": len(articles)})
        for slug, item in articles.items():
            url = f"{BASE_URL}/press/{slug}"
            html = self._load(page, url)
            if html is None:
                continue
            before = len(self.rows)
            self._save("press", url, html, {
                "name": item.get("heading") or "",
                "date": item.get("date"),
                "summary": item.get("description") or "",
            })
            self.stats["press"] += len(self.rows) - before

    def scrape_static(self, page: Page) -> None:
        for path in STATIC_PAGES:
            url = BASE_URL + path
            html = self._load(page, url)
            if html is None:
                continue
            before = len(self.rows)
            self._save("page", url, html)
            self.stats["pages"] += len(self.rows) - before

    def run(self) -> dict[str, int]:
        with sync_playwright() as playwright:
            browser: Browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            try:
                # robots.txt is behind the same JS challenge, so it is read through the browser too.
                page.goto(f"{BASE_URL}/", wait_until="domcontentloaded", timeout=60_000)
                page.wait_for_selector("#__NEXT_DATA__", state="attached", timeout=25_000)
                robots_text = page.evaluate("() => fetch('/robots.txt').then(r => r.ok ? r.text() : '')")
                self.robots = RobotsRules(robots_text or "")
                logger.info("robots.txt loaded", extra={"rules": len(self.robots.rules)})
                self.scrape_projects(page)
                self.scrape_static(page)
                self.scrape_press(page)
            finally:
                browser.close()
                if self.rows:  # keep whatever was collected even if the crawl stopped early
                    write_jsonl(self.raw_path, self.rows)
        logger.info("darglobal scrape finished", extra=self.stats)
        return self.stats


if __name__ == "__main__":
    configure_logging()
    try:
        DarGlobalScraper().run()
    except BlockedError as exc:
        logger.error("access blocked, stopping without workaround", extra={"error": str(exc)})
        raise SystemExit(2)
