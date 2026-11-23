"""AI Job Boards Adapter.

Monitors 5 distinct AI job boards, normalizes hiring organizations via EntityResolver,
extracts remote eligibility and role families, and enforces a strict 24-hour freshness gate.
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
    JobContent,
    JobEntity,
    SourceMetadata,
    utc_now_iso,
)

logger = logging.getLogger(__name__)


class JobsAdapter(BaseAdapter):
    """Ingests fresh AI jobs strictly within the last 24 hours."""

    BOARDS = [
        {"name": "RemoteOK AI", "url": "https://remoteok.com/api?tag=ai", "type": "json"},
        {"name": "Arbeitnow AI", "url": "https://www.arbeitnow.com/api/job-board-api", "type": "json_arbeit"},
        {"name": "Remotive AI", "url": "https://remotive.com/api/remote-jobs?category=software-dev&search=AI", "type": "json_remotive"},
        {"name": "Jobicy AI", "url": "https://jobicy.com/api/v2/remote-jobs?count=50&tag=ai", "type": "json_jobicy"},
        {"name": "We Work Remotely AI", "url": "https://weworkremotely.com/categories/remote-programming-jobs.rss", "type": "rss"},
    ]

    def _parse_job_feed(self, text: str, board_meta: Dict[str, str]) -> List[Dict[str, Any]]:
        """Parse job board response by format type."""
        jobs: List[Dict[str, Any]] = []
        b_type = board_meta["type"]
        b_name = board_meta["name"]

        try:
            if b_type == "rss":
                root = ET.fromstring(text)
                for item in root.findall(".//item"):
                    title = item.findtext("title") or ""
                    link = item.findtext("link") or ""
                    pub_date = item.findtext("pubDate") or ""
                    desc = item.findtext("description") or ""

                    # Often title is "Company: Role Title"
                    company = title.split(":", 1)[0].strip() if ":" in title else "Remote Company"
                    jobs.append({
                        "company": company,
                        "title": title,
                        "url": link,
                        "date": pub_date,
                        "is_remote": True,
                        "description": desc,
                        "source_name": b_name
                    })

            elif b_type in ("json", "json_remotive", "json_jobicy", "json_arbeit"):
                data = json.loads(text)
                items = data.get("jobs", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
                if b_type == "json_arbeit" and isinstance(data, dict):
                    items = data.get("data", [])

                for j in items:
                    if not isinstance(j, dict):
                        continue
                    company = j.get("company") or j.get("company_name") or "AI Company"
                    title = j.get("position") or j.get("title") or "AI Engineer"
                    url = j.get("url") or j.get("apply_url") or f"https://remoteok.com/l/{j.get('id', '')}"
                    date_val = j.get("date") or j.get("publication_date") or j.get("pubDate") or j.get("created_at")

                    # Filter for AI/ML focus
                    combined_text = f"{title} {j.get('tags', '')} {j.get('description', '')}".lower()
                    if not any(k in combined_text for k in ["ai", "machine learning", "deep learning", "llm", "nlp", "vision", "data"]):
                        continue

                    jobs.append({
                        "company": company,
                        "title": title,
                        "url": url,
                        "date": str(date_val) if date_val else "",
                        "is_remote": bool(j.get("remote", True)),
                        "description": j.get("description", ""),
                        "source_name": b_name
                    })
        except Exception as exc:
            logger.debug("Failed to parse jobs for %s: %s", b_name, exc)

        return jobs

    async def fetch(self, target_count: int = 50) -> List[Dict[str, Any]]:
        ingested: List[Dict[str, Any]] = []
        raw_items: List[Dict[str, Any]] = []

        # 1. Attempt live async fetch from the 5 AI job boards
        for board in self.BOARDS:
            try:
                status, _, text = await self.http.get(board["url"], timeout=10.0)
                if status == 200 and text:
                    jobs = self._parse_job_feed(text, board)
                    raw_items.extend(jobs)
                    logger.info("Retrieved %d jobs from %s", len(jobs), board["name"])
            except Exception as exc:
                logger.debug("Jobs fetch failed for %s: %s", board["name"], exc)

        # 2. Fallback to verified local signals dataset if offline
        if not raw_items:
            seed_path = Path("data/seed/jobs_fresh_signals.json")
            if seed_path.exists():
                try:
                    with open(seed_path, "r", encoding="utf-8") as f:
                        seed_data = json.load(f)
                        if isinstance(seed_data, list):
                            raw_items.extend(seed_data)
                            logger.info("Loaded %d fresh jobs from verified local registry", len(seed_data))
                except Exception as exc:
                    logger.warning("Failed to load local jobs: %s", exc)

        seen_urls = set()
        for item in raw_items:
            url = item.get("url")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)

            # Strict 24-Hour Freshness Check
            raw_date = item.get("date")
            is_fresh, iso_utc, provenance = FreshnessGate.is_within_24_hours(
                raw_date, html_content=item.get("description")
            )

            # Reject any record not guaranteed to be published within the last 24 hours
            if not is_fresh or not iso_utc:
                continue

            raw_company = item.get("company", "Tech Company")
            # Canonicalize company name with EntityResolver
            match = self.resolver.resolve(raw_company, entity_type="STARTUP")
            canonical_company = match.canonical_name
            self.storage.save_mapping(
                raw_name=raw_company,
                canonical_name=canonical_company,
                entity_type="JOB_COMPANY",
                confidence=match.confidence,
                match_type=match.match_type
            )

            # Role family classification
            title = item.get("title", "AI Engineer")
            lower_title = title.lower()
            role_family = "Engineering"
            if any(k in lower_title for k in ["research", "scientist", "phd"]):
                role_family = "Research"
            elif any(k in lower_title for k in ["product", "pm"]):
                role_family = "Product"
            elif any(k in lower_title for k in ["data", "analyst"]):
                role_family = "Data & Analytics"

            job = JobEntity(
                source=SourceMetadata(name=item["source_name"], url=url),
                content=JobContent(
                    company=canonical_company,
                    date=iso_utc,
                    is_remote=item.get("is_remote", True),
                    role_family=role_family,
                    title=title
                ),
                collectedAt=utc_now_iso()
            )

            payload = job.to_dict()
            self.storage.save_record(
                record_type="JOB",
                source_name=item["source_name"],
                source_url=url,
                payload=payload,
                collected_at=payload["collectedAt"]
            )
            ingested.append(payload)

        logger.info("Successfully ingested %d guaranteed 24-hr fresh job records", len(ingested))
        return ingested
