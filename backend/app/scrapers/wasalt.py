"""Wasalt.sa scraper.

Access policy followed (https://wasalt.sa/robots.txt and https://wasalt.sa/llms.txt):
  * URL discovery comes from the public sitemap, never from /search (disallowed).
  * Only public listing content is kept. Owner names, phone numbers, WhatsApp links and
    licence holder details are dropped before anything is written to disk.
  * Low request rate (one request every ~1.2 s, single connection).
  * Every record keeps its source URL so answers can attribute "Source: Wasalt.sa".

Run:  python -m app.scrapers.wasalt                      (live crawl)
      python -m app.scrapers.wasalt --from-html DIR      (parse listing pages saved from a browser)

Known limitation (19 Nov 2026): Cloudflare answers this client with a managed challenge
(HTTP 403, `cf-mitigated: challenge`). The crawler stops at the first 403 by design. The
`--from-html` mode exists as the compliant alternative: it parses listing pages a person
saved while browsing normally, without any automated request to the site.
"""
import argparse
import gzip
import logging
import random
import re
import time
from pathlib import Path
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.scrapers.base import (
    BlockedError,
    RobotsRules,
    append_jsonl,
    extract_next_data,
    read_jsonl,
    utc_now,
)

logger = logging.getLogger("scraper.wasalt")

BASE_URL = "https://wasalt.sa"
SITEMAP_URL = "https://cdn.wasalt.sa/sitemap/product_sitemap_en_sa.xml.gz"
RAW_FILE = "wasalt_listings.jsonl"

# Fields removed from the raw payload: contact / personal data and UI noise.
_DROP_KEYS = {
    "leadContactInfo",
    "propertyOwner",
    "contactDetails",
    "regaVerifiedInfo",
    "classificationData",
    "packageData",
    "scoringData",
    "views",
    "priceValuation",
}


class WasaltScraper:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = httpx.Client(
            headers={"User-Agent": self.settings.scraper_user_agent, "Accept-Language": "en"},
            timeout=40.0,
            follow_redirects=True,
        )
        self.raw_path = self.settings.raw_dir / RAW_FILE
        self.robots: RobotsRules | None = None

    def _get(self, url: str, retries: int = 2) -> httpx.Response | None:
        """GET with polite delay and bounded retries. 403 means we are not welcome: stop."""
        for attempt in range(retries + 1):
            time.sleep(self.settings.scraper_delay_seconds)
            try:
                response = self.client.get(url)
            except httpx.HTTPError as exc:
                logger.warning("request failed", extra={"url": url, "error": repr(exc), "attempt": attempt})
                time.sleep(2 ** attempt * 2)
                continue
            if response.status_code == 200:
                return response
            if response.status_code == 403:
                raise BlockedError(f"403 from {url}")
            if response.status_code in (404, 410):
                return None
            if response.status_code == 429 or response.status_code >= 500:
                wait = float(response.headers.get("Retry-After", 2 ** attempt * 5))
                logger.warning("backing off", extra={"url": url, "status": response.status_code, "wait": wait})
                time.sleep(min(wait, 60))
                continue
            logger.warning("unexpected status", extra={"url": url, "status": response.status_code})
            return None
        return None

    def load_robots(self) -> None:
        response = self._get(f"{BASE_URL}/robots.txt")
        self.robots = RobotsRules(response.text if response else "")

    def discover_urls(self) -> dict[str, list[str]]:
        """Listing URLs from the sitemap, split by purpose."""
        response = self._get(SITEMAP_URL)
        if response is None:
            raise RuntimeError("could not download the Wasalt sitemap")
        body = response.content
        if body[:2] == b"\x1f\x8b":
            body = gzip.decompress(body)
        urls = re.findall(r"<loc>(.*?)</loc>", body.decode("utf-8", "ignore"))
        grouped: dict[str, list[str]] = {"sale": [], "rent": []}
        for url in urls:
            match = re.search(r"/en/property/(sale|rent)/", url)
            if match:
                grouped[match.group(1)].append(url)
        logger.info("sitemap parsed", extra={k: len(v) for k, v in grouped.items()})
        return grouped

    def sample_urls(self, grouped: dict[str, list[str]]) -> list[str]:
        """The sitemap lists ~60k listings. A fixed-seed random sample keeps the crawl small
        and reproducible while preserving the natural mix of cities and property types."""
        rng = random.Random(42)
        chosen: list[str] = []
        for purpose, size in (("sale", self.settings.wasalt_sale_sample), ("rent", self.settings.wasalt_rent_sample)):
            pool = sorted(grouped[purpose])
            chosen.extend(rng.sample(pool, min(size, len(pool))))
        return chosen

    @staticmethod
    def _clean(details: dict[str, Any]) -> dict[str, Any]:
        cleaned = {k: v for k, v in details.items() if k not in _DROP_KEYS}
        info = cleaned.get("propertyInfo") or {}
        info.pop("managedBy", None)  # advertiser name: not needed, not kept
        return cleaned

    @classmethod
    def parse_listing(cls, html: str) -> dict[str, Any] | None:
        """The listing a detail page is about."""
        data = extract_next_data(html)
        if not data:
            return None
        page_props = data.get("props", {}).get("pageProps", {})
        details = page_props.get("propertyDetailsV3")
        if not isinstance(details, dict) or not details.get("propertyInfo"):
            return None
        cleaned = cls._clean(details)
        info = page_props.get("infoDetails") or {}
        cleaned["amenities"] = info.get("amenities") or []
        cleaned["fittings"] = info.get("fittings") or []
        return cleaned

    @classmethod
    def parse_similar(cls, html: str) -> list[tuple[str, dict[str, Any]]]:
        """Listing cards shown in the "similar properties" section of a detail page."""
        data = extract_next_data(html) or {}
        similar = data.get("props", {}).get("pageProps", {}).get("similarProperty") or {}
        results: list[tuple[str, dict[str, Any]]] = []
        for item in similar.get("properties") or []:
            info = item.get("propertyInfo") or {}
            if not info.get("slug") or info.get("propertyFor") not in ("sale", "rent"):
                continue
            url = f"{BASE_URL}/en/property/{info['propertyFor']}/{info['slug']}"
            results.append((url, cls._clean(item)))
        return results

    def ingest_html_dir(self, directory: Path) -> dict[str, int]:
        """Parse saved listing pages. Makes no network requests."""
        done = {row["url"] for row in read_jsonl(self.raw_path)}
        stats = {"files": 0, "saved": 0, "unparsed": 0}
        for path in sorted(directory.glob("*.html")):
            stats["files"] += 1
            html = path.read_text(encoding="utf-8", errors="ignore")
            listing = self.parse_listing(html)
            if listing is None:
                stats["unparsed"] += 1
                continue
            info = listing["propertyInfo"]
            entries = [(f"{BASE_URL}/en/property/{info['propertyFor']}/{info['slug']}", listing, "detail_page")]
            entries += [(url, data, "similar_listing_card") for url, data in self.parse_similar(html)]
            for url, data, origin in entries:
                if url in done:
                    continue
                done.add(url)
                append_jsonl(self.raw_path, {"url": url, "scraped_at": utc_now(), "origin": origin, "data": data})
                stats["saved"] += 1
        logger.info("wasalt html ingest finished", extra=stats)
        return stats

    def run(self) -> dict[str, int]:
        self.load_robots()
        urls = self.sample_urls(self.discover_urls())
        done = {row["url"] for row in read_jsonl(self.raw_path)}  # resume support
        stats = {"planned": len(urls), "skipped_existing": 0, "saved": 0, "missing": 0, "unparsed": 0, "disallowed": 0}
        for index, url in enumerate(urls, 1):
            if url in done:
                stats["skipped_existing"] += 1
                continue
            if self.robots and not self.robots.allowed(url):
                stats["disallowed"] += 1
                continue
            response = self._get(url)
            if response is None:
                stats["missing"] += 1
                continue
            listing = self.parse_listing(response.text)
            if listing is None:
                stats["unparsed"] += 1
                continue
            append_jsonl(self.raw_path, {"url": url, "scraped_at": utc_now(), "origin": "detail_page", "data": listing})
            stats["saved"] += 1
            if index % 25 == 0:
                logger.info("progress", extra={"done": index, **stats})
        logger.info("wasalt scrape finished", extra=stats)
        return stats


if __name__ == "__main__":
    configure_logging()
    parser = argparse.ArgumentParser(description="Wasalt.sa listing scraper")
    parser.add_argument("--from-html", type=Path, help="directory of saved listing pages to parse offline")
    args = parser.parse_args()
    try:
        if args.from_html:
            WasaltScraper().ingest_html_dir(args.from_html)
        else:
            WasaltScraper().run()
    except BlockedError as exc:
        logger.error("access blocked, stopping without workaround", extra={"error": str(exc)})
        raise SystemExit(2)
