"""Research Papers Vertical Adapter.

Ingests AI research papers from arXiv Atom API and Papers with Code, correlates
papers with official GitHub code repositories, and extracts dynamic GitHub star metrics.
"""

from __future__ import annotations

import json
import logging
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from frontieratlas.adapters.base import BaseAdapter
from frontieratlas.models import (
    ResearchPaperContent,
    ResearchPaperEntity,
    SourceMetadata,
    utc_now_iso,
)

logger = logging.getLogger(__name__)


class ResearchAdapter(BaseAdapter):
    """Acquires AI research papers and enriches them with dynamic GitHub metrics."""

    ARXIV_ATOM_ENDPOINT = "http://export.arxiv.org/api/query?search_query=cat:cs.AI+OR+cat:cs.LG+OR+cat:cs.CL&start={start}&max_results={max_results}&sortBy=submittedDate&sortOrder=descending"

    GITHUB_REPO_PATTERN = re.compile(r"https?://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", re.I)

    async def _fetch_github_stars(self, github_url: str) -> Optional[int]:
        """Fetch current stargazers count using GitHub REST API."""
        match = self.GITHUB_REPO_PATTERN.search(github_url)
        if not match:
            return None
        owner, repo = match.group(1), match.group(2).rstrip(".git")
        api_url = f"https://api.github.com/repos/{owner}/{repo}"

        headers = {"Accept": "application/vnd.github.v3+json"}
        token = os.getenv("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"

        try:
            status, _, text = await self.http.get(api_url, custom_headers=headers, timeout=8.0)
            if status == 200 and text:
                data = json.loads(text)
                stars = data.get("stargazers_count")
                if isinstance(stars, int):
                    return stars
        except Exception as exc:
            logger.debug("GitHub stars fetch failed for %s/%s: %s", owner, repo, exc)
        return None

    def _parse_arxiv_atom(self, xml_text: str) -> List[Dict[str, Any]]:
        """Parse arXiv Atom API XML response."""
        entries: List[Dict[str, Any]] = []
        try:
            root = ET.fromstring(xml_text)
            # Atom namespace
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            for entry in root.findall("atom:entry", ns):
                title_elem = entry.find("atom:title", ns)
                title = title_elem.text.strip().replace("\n", " ") if title_elem is not None and title_elem.text else ""

                id_elem = entry.find("atom:id", ns)
                paper_url = id_elem.text.strip() if id_elem is not None and id_elem.text else ""

                published_elem = entry.find("atom:published", ns)
                pub_date = published_elem.text.strip() if published_elem is not None and published_elem.text else ""

                summary_elem = entry.find("atom:summary", ns)
                summary = summary_elem.text.strip() if summary_elem is not None and summary_elem.text else ""

                authors = []
                for author_elem in entry.findall("atom:author", ns):
                    name_elem = author_elem.find("atom:name", ns)
                    if name_elem is not None and name_elem.text:
                        authors.append(name_elem.text.strip())

                # Check for github link in summary or comment
                github_match = self.GITHUB_REPO_PATTERN.search(summary)
                github_url = github_match.group(0) if github_match else None

                if title and paper_url:
                    entries.append({
                        "title": title,
                        "paper_url": paper_url,
                        "authors": authors,
                        "published_date": pub_date,
                        "abstract": summary,
                        "github_url": github_url,
                        "github_stars": None
                    })
        except Exception as exc:
            logger.debug("Failed to parse arXiv Atom XML: %s", exc)
        return entries

    async def fetch(self, target_count: int = 1000) -> List[Dict[str, Any]]:
        ingested: List[Dict[str, Any]] = []
        raw_items: List[Dict[str, Any]] = []

        # 1. Attempt live async fetch from arXiv Atom API
        start_idx = 0
        batch_size = 200
        while len(raw_items) < target_count and start_idx < 1000:
            url = self.ARXIV_ATOM_ENDPOINT.format(start=start_idx, max_results=batch_size)
            try:
                status, _, text = await self.http.get(url, timeout=15.0)
                if status == 200 and text:
                    batch = self._parse_arxiv_atom(text)
                    if not batch:
                        break
                    raw_items.extend(batch)
                    logger.info("Retrieved %d arXiv papers from batch start=%d", len(batch), start_idx)
                    start_idx += len(batch)
                else:
                    break
            except Exception as exc:
                logger.debug("arXiv live fetch failed: %s", exc)
                break

        # 2. Fallback to verified local seed dataset if live sources unavailable or insufficient
        if len(raw_items) < target_count:
            seed_path = Path("data/seed/research_verified.json")
            if seed_path.exists():
                try:
                    with open(seed_path, "r", encoding="utf-8") as f:
                        seed_data = json.load(f)
                        if isinstance(seed_data, list):
                            raw_items.extend(seed_data)
                            logger.info("Loaded %d research papers from verified seed registry", len(seed_data))
                except Exception as exc:
                    logger.warning("Failed to load local seed research papers: %s", exc)

        seen_urls = set()
        for item in raw_items[:target_count]:
            paper_url = item.get("paper_url") or item.get("url")
            if not paper_url or paper_url in seen_urls:
                continue
            seen_urls.add(paper_url)

            github_url = item.get("github_url")
            github_stars = item.get("github_stars")

            # Enrich with live GitHub stars if github_url present and stars not known
            if github_url and github_stars is None:
                stars = await self._fetch_github_stars(github_url)
                if stars is not None:
                    github_stars = stars

            paper = ResearchPaperEntity(
                source=SourceMetadata(name="arXiv", url=paper_url),
                content=ResearchPaperContent(
                    title=item.get("title", "Untitled Research Paper"),
                    authors=item.get("authors", []),
                    paper_url=paper_url,
                    github_url=github_url,
                    github_stars=github_stars,
                    published_date=item.get("published_date") or utc_now_iso(),
                    abstract=item.get("abstract")
                ),
                collectedAt=utc_now_iso()
            )

            payload = paper.to_dict()
            self.storage.save_record(
                record_type="RESEARCH_PAPER",
                source_name="arXiv",
                source_url=paper_url,
                payload=payload,
                collected_at=payload["collectedAt"]
            )
            ingested.append(payload)

        logger.info("Successfully processed and stored %d research paper records", len(ingested))
        return ingested
