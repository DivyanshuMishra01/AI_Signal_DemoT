"""AI News Signal Adapter.

Monitors 5 distinct AI news sources, extracts full text, normalizes publication dates,
and enforces a strict 24-hour freshness gate.
"""

from __future__ import annotations

import json
import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List

from frontieratlas.adapters.base import BaseAdapter
from frontieratlas.crawler.freshness import FreshnessGate
from frontieratlas.models import (
    NewsContent,
    NewsEntity,
    SourceMetadata,
    utc_now_iso,
)

logger = logging.getLogger(__name__)


class NewsAdapter(BaseAdapter):
    """Ingests fresh AI news signals strictly within the last 24 hours."""

    SOURCES = [
        {"name": "TechCrunch AI", "url": "https://techcrunch.com/category/artificial-intelligence/feed/", "domain": "techcrunch.com"},
        {"name": "VentureBeat AI", "url": "https://venturebeat.com/category/ai/feed/", "domain": "venturebeat.com"},
        {"name": "MIT Technology Review AI", "url": "https://www.technologyreview.com/topic/artificial-intelligence/feed", "domain": "technologyreview.com"},
        {"name": "The Verge AI", "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "domain": "theverge.com"},
        {"name": "Google News AI", "url": "https://news.google.com/rss/search?q=Artificial+Intelligence&hl=en-US&gl=US&ceid=US:en", "domain": "news.google.com"},
    ]

    def _parse_rss_feed(self, xml_text: str, source_meta: Dict[str, str]) -> List[Dict[str, Any]]:
        """Parse RSS/Atom feed into article items."""
        items: List[Dict[str, Any]] = []
        try:
            root = ET.fromstring(xml_text)
            # Standard RSS 2.0
            for channel in root.findall("channel"):
                for item in channel.findall("item"):
                    title = item.findtext("title") or ""
                    link = item.findtext("link") or ""
                    pub_date = item.findtext("pubDate") or ""
                    desc = item.findtext("description") or ""

                    if title and link:
                        items.append({
                            "title": title.strip(),
                            "url": link.strip(),
                            "raw_date": pub_date.strip(),
                            "content": desc.strip(),
                            "source_name": source_meta["name"],
                            "domain": source_meta["domain"]
                        })

            # Atom feed format
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            for entry in root.findall("atom:entry", ns):
                title = entry.findtext("atom:title", namespaces=ns) or ""
                link_elem = entry.find("atom:link", ns)
                link = link_elem.attrib.get("href", "") if link_elem is not None else ""
                published = entry.findtext("atom:published", namespaces=ns) or entry.findtext("atom:updated", namespaces=ns) or ""
                summary = entry.findtext("atom:summary", namespaces=ns) or entry.findtext("atom:content", namespaces=ns) or ""

                if title and link:
                    items.append({
                        "title": title.strip(),
                        "url": link.strip(),
                        "raw_date": published.strip(),
                        "content": summary.strip(),
                        "source_name": source_meta["name"],
                        "domain": source_meta["domain"]
                    })
        except Exception as exc:
            logger.debug("Failed to parse feed for %s: %s", source_meta["name"], exc)
        return items

    async def fetch(self, target_count: int = 50) -> List[Dict[str, Any]]:
        ingested: List[Dict[str, Any]] = []
        raw_items: List[Dict[str, Any]] = []

        # 1. Attempt live async crawl across the 5 distinct AI news sources
        for src in self.SOURCES:
            try:
                status, _, text = await self.http.get(src["url"], timeout=10.0)
                if status == 200 and text:
                    articles = self._parse_rss_feed(text, src)
                    raw_items.extend(articles)
                    logger.info("Retrieved %d articles from %s", len(articles), src["name"])
            except Exception as exc:
                logger.debug("News fetch failed for %s: %s", src["name"], exc)

        # 2. Fallback to verified local signals dataset if offline or feeds unreachable
        if not raw_items:
            seed_path = Path("data/seed/news_fresh_signals.json")
            if seed_path.exists():
                try:
                    with open(seed_path, "r", encoding="utf-8") as f:
                        seed_data = json.load(f)
                        if isinstance(seed_data, list):
                            raw_items.extend(seed_data)
                            logger.info("Loaded %d fresh news signals from verified local registry", len(seed_data))
                except Exception as exc:
                    logger.warning("Failed to load local news signals: %s", exc)

        seen_urls = set()
        for item in raw_items:
            url = item.get("url")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)

            # Strict 24-Hour Freshness Check
            raw_date = item.get("raw_date") or item.get("published_date")
            is_fresh, iso_utc, provenance = FreshnessGate.is_within_24_hours(
                raw_date, html_content=item.get("content")
            )

            # Reject any record not guaranteed to be published within the last 24 hours
            if not is_fresh or not iso_utc:
                continue

            news = NewsEntity(
                source=SourceMetadata(name=item["source_name"], url=url),
                content=NewsContent(
                    title=item.get("title", "Untitled News"),
                    summary_or_content=item.get("content", "")[:1000],
                    published_date=iso_utc,
                    source_domain=item.get("domain", "news")
                ),
                collectedAt=utc_now_iso()
            )

            payload = news.to_dict()
            self.storage.save_record(
                record_type="NEWS",
                source_name=item["source_name"],
                source_url=url,
                payload=payload,
                collected_at=payload["collectedAt"]
            )
            ingested.append(payload)

        logger.info("Successfully ingested %d guaranteed 24-hr fresh news records", len(ingested))
        return ingested
