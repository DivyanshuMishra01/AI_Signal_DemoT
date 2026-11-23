"""Startup Vertical Adapter.

Ingests AI startups, canonicalizes organization names, extracts employee counts,
and records all entity resolution actions.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from frontieratlas.adapters.base import BaseAdapter
from frontieratlas.models import (
    SourceMetadata,
    StartupContent,
    StartupData,
    StartupEntity,
    utc_now_iso,
)

logger = logging.getLogger(__name__)


class StartupsAdapter(BaseAdapter):
    """Acquires structured AI startup records from directories and registries."""

    LIVE_SOURCES = [
        "https://raw.githubusercontent.com/yc-oss/startups/main/data/companies.json",
        "https://raw.githubusercontent.com/algolia/datasets/master/ecommerce/ycombinator.json",
    ]

    async def fetch(self, target_count: int = 1000) -> List[Dict[str, Any]]:
        ingested: List[Dict[str, Any]] = []
        raw_items: List[Dict[str, Any]] = []

        # 1. Attempt live async fetch across configured endpoints
        for url in self.LIVE_SOURCES:
            try:
                status, headers, text = await self.http.get(url, timeout=10.0)
                if status == 200 and text:
                    data = json.loads(text)
                    if isinstance(data, list):
                        raw_items.extend(data)
                        logger.info("Retrieved %d startups from live source %s", len(data), url)
                        if len(raw_items) >= target_count:
                            break
            except Exception as exc:
                logger.debug("Live fetch failed for %s: %s", url, exc)

        # 2. Fallback to verified local seed dataset if live sources unavailable or insufficient
        if len(raw_items) < target_count:
            seed_path = Path("data/seed/startups_verified.json")
            if seed_path.exists():
                try:
                    with open(seed_path, "r", encoding="utf-8") as f:
                        seed_data = json.load(f)
                        if isinstance(seed_data, list):
                            raw_items.extend(seed_data)
                            logger.info("Loaded %d startups from verified seed registry", len(seed_data))
                except Exception as exc:
                    logger.warning("Failed to load local seed startups: %s", exc)

        # Deduplicate raw items by name/url
        seen_names = set()
        unique_raw: List[Dict[str, Any]] = []
        for item in raw_items:
            name = item.get("name") or item.get("company_name") or item.get("title")
            if name and name.lower() not in seen_names:
                seen_names.add(name.lower())
                unique_raw.append(item)

        # Process and normalize records
        for item in unique_raw[:target_count]:
            raw_name = item.get("name") or item.get("company_name") or item.get("title") or "Unknown Startup"
            
            # Resolve entity name through deterministic entity resolver
            match = self.resolver.resolve(raw_name, entity_type="STARTUP")
            canonical_name = match.canonical_name
            self.storage.save_mapping(
                raw_name=raw_name,
                canonical_name=canonical_name,
                entity_type="STARTUP",
                confidence=match.confidence,
                match_type=match.match_type
            )

            # Extract employee count
            team_size = item.get("team_size") or item.get("employees") or item.get("employee_count")
            emp_count: Optional[int] = None
            if team_size is not None:
                try:
                    emp_count = int(team_size)
                except (ValueError, TypeError):
                    emp_count = None

            # Source URL
            source_url = item.get("website") or item.get("url") or item.get("source_url") or f"https://www.ycombinator.com/companies/{raw_name.lower().replace(' ', '-')}"
            source_name = item.get("source_name") or "YC OSS Directory"

            startup = StartupEntity(
                source=SourceMetadata(name=source_name, url=source_url),
                content=StartupContent(
                    entityName=canonical_name,
                    data=StartupData(employeeCount=emp_count),
                    description=item.get("one_liner") or item.get("description")
                ),
                collectedAt=utc_now_iso()
            )

            payload = startup.to_dict()
            is_new, rec_id = self.storage.save_record(
                record_type="STARTUP",
                source_name=source_name,
                source_url=source_url,
                payload=payload,
                collected_at=payload["collectedAt"]
            )
            ingested.append(payload)

        logger.info("Successfully processed and stored %d startup records", len(ingested))
        return ingested
