"""Product Vertical Adapter.

Ingests AI products, models, and tools from Hugging Face Hub and product directories,
canonicalizes the creator entity name, and classifies the pricing model.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from frontieratlas.adapters.base import BaseAdapter
from frontieratlas.models import (
    PricingModel,
    ProductContent,
    ProductEntity,
    SourceMetadata,
    utc_now_iso,
)

logger = logging.getLogger(__name__)


class ProductsAdapter(BaseAdapter):
    """Acquires structured AI product records."""

    LIVE_SOURCES = [
        "https://huggingface.co/api/models?limit=500&full=false",
        "https://huggingface.co/api/spaces?limit=500",
    ]

    async def fetch(self, target_count: int = 1000) -> List[Dict[str, Any]]:
        ingested: List[Dict[str, Any]] = []
        raw_items: List[Dict[str, Any]] = []

        # 1. Attempt live async fetch from Hugging Face Hub APIs
        for url in self.LIVE_SOURCES:
            try:
                status, headers, text = await self.http.get(url, timeout=12.0)
                if status == 200 and text:
                    data = json.loads(text)
                    if isinstance(data, list):
                        for item in data:
                            model_id = item.get("id") or item.get("_id")
                            if model_id and "/" in model_id:
                                org, name = model_id.split("/", 1)
                            else:
                                org = "Community"
                                name = model_id or "AI Model"
                            raw_items.append({
                                "startup_name": org,
                                "product_name": name,
                                "url": f"https://huggingface.co/{model_id}",
                                "source_name": "Hugging Face Hub",
                                "pricing_model": "FREE"
                            })
                        logger.info("Retrieved %d products from Hugging Face endpoint %s", len(data), url)
                        if len(raw_items) >= target_count:
                            break
            except Exception as exc:
                logger.debug("Live fetch failed for %s: %s", url, exc)

        # 2. Fallback to verified local seed dataset if live sources unavailable or insufficient
        if len(raw_items) < target_count:
            seed_path = Path("data/seed/products_verified.json")
            if seed_path.exists():
                try:
                    with open(seed_path, "r", encoding="utf-8") as f:
                        seed_data = json.load(f)
                        if isinstance(seed_data, list):
                            raw_items.extend(seed_data)
                            logger.info("Loaded %d products from verified seed registry", len(seed_data))
                except Exception as exc:
                    logger.warning("Failed to load local seed products: %s", exc)

        seen_urls = set()
        for item in raw_items[:target_count]:
            source_url = item.get("url") or item.get("source_url") or "https://huggingface.co"
            if source_url in seen_urls:
                continue
            seen_urls.add(source_url)

            raw_startup = item.get("startup_name") or item.get("company") or "Open Source"
            # Canonicalize startup name
            match = self.resolver.resolve(raw_startup, entity_type="PRODUCT")
            canonical_startup = match.canonical_name
            self.storage.save_mapping(
                raw_name=raw_startup,
                canonical_name=canonical_startup,
                entity_type="PRODUCT",
                confidence=match.confidence,
                match_type=match.match_type
            )

            # Classify pricing model
            raw_pricing = item.get("pricing_model") or "FREEMIUM"
            try:
                pricing = PricingModel(raw_pricing.upper())
            except ValueError:
                pricing = PricingModel.FREEMIUM

            product_name = item.get("product_name") or item.get("name") or "AI Tool"
            source_name = item.get("source_name") or "Hugging Face Hub"

            product = ProductEntity(
                source=SourceMetadata(name=source_name, url=source_url),
                content=ProductContent(
                    startupName=canonical_startup,
                    productName=product_name,
                    pricingModel=pricing,
                    description=item.get("description")
                ),
                collectedAt=utc_now_iso()
            )

            payload = product.to_dict()
            self.storage.save_record(
                record_type="PRODUCT",
                source_name=source_name,
                source_url=source_url,
                payload=payload,
                collected_at=payload["collectedAt"]
            )
            ingested.append(payload)

        logger.info("Successfully processed and stored %d product records", len(ingested))
        return ingested
