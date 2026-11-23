"""CLI entrypoint for FrontierAtlas Intelligence Pipeline.

Supports granular and full pipeline modes:
- startups
- products
- research
- signals (news & jobs)
- all
- export
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Dict

from frontieratlas.adapters.jobs import JobsAdapter
from frontieratlas.adapters.news import NewsAdapter
from frontieratlas.adapters.products import ProductsAdapter
from frontieratlas.adapters.research import ResearchAdapter
from frontieratlas.adapters.startups import StartupsAdapter
from frontieratlas.crawler.http_client import AsyncHTTPClient
from frontieratlas.exporter import IntelligenceExporter
from frontieratlas.llm.orchestrator import LLMOrchestrator
from frontieratlas.resolver.entity_resolver import EntityResolver
from frontieratlas.storage import StorageEngine


def setup_logging(log_file: str = "logs/pipeline.log") -> None:
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file, encoding="utf-8")
        ]
    )


def parse_targets(target_str: str) -> Dict[str, int]:
    targets = {"startups": 1000, "products": 1000, "research": 1000, "signals": 50}
    if not target_str:
        return targets
    for part in target_str.split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            k = k.strip().lower()
            try:
                targets[k] = int(v.strip())
            except ValueError:
                pass
    return targets


async def run_pipeline(mode: str, targets: Dict[str, int], db_path: str = "data/intelligence.db") -> None:
    logger = logging.getLogger("frontieratlas.cli")
    logger.info("Initializing FrontierAtlas Intelligence Pipeline (Mode: %s)", mode)

    storage = StorageEngine(db_path)
    http_client = AsyncHTTPClient()
    llm = LLMOrchestrator()
    resolver = EntityResolver()
    exporter = IntelligenceExporter(storage)

    if mode in ("startups", "all"):
        logger.info("=== Phase I: Startups Vertical (Target: %d) ===", targets["startups"])
        adapter = StartupsAdapter(http_client, llm, resolver, storage)
        await adapter.fetch(target_count=targets["startups"])

    if mode in ("products", "all"):
        logger.info("=== Phase I: Products Vertical (Target: %d) ===", targets["products"])
        adapter = ProductsAdapter(http_client, llm, resolver, storage)
        await adapter.fetch(target_count=targets["products"])

    if mode in ("research", "all"):
        logger.info("=== Phase I: Research Papers Vertical (Target: %d) ===", targets["research"])
        adapter = ResearchAdapter(http_client, llm, resolver, storage)
        await adapter.fetch(target_count=targets["research"])

    if mode in ("signals", "all"):
        logger.info("=== Phase II: High-Fidelity Fresh News Signals ===")
        news_adapter = NewsAdapter(http_client, llm, resolver, storage)
        await news_adapter.fetch(target_count=targets.get("signals", 50))

        logger.info("=== Phase II: High-Fidelity Fresh Job Signals ===")
        jobs_adapter = JobsAdapter(http_client, llm, resolver, storage)
        await jobs_adapter.fetch(target_count=targets.get("signals", 50))

    if mode == "export" or mode in ("all", "startups", "products", "research", "signals"):
        logger.info("=== Exporting 6-Tab Intelligence Deliverables ===")
        summary = exporter.export_all()
        logger.info("Export completed successfully: %s", summary)

    counts = storage.get_counts()
    logger.info("Current Database Totals: %s", counts)


def main() -> None:
    parser = argparse.ArgumentParser(description="FrontierAtlas AI Intelligence Ingestion Pipeline")
    parser.add_argument(
        "--mode",
        choices=["startups", "products", "research", "signals", "all", "export"],
        default="all",
        help="Pipeline execution mode"
    )
    parser.add_argument(
        "--targets",
        default="startups=1000,products=1000,research=1000",
        help="Target quotas e.g. startups=1000,products=1000,research=1000"
    )
    parser.add_argument(
        "--db",
        default="data/intelligence.db",
        help="Path to SQLite database"
    )
    parser.add_argument(
        "--export",
        action="store_true",
        help="Run export immediately"
    )

    args = parser.parse_args()
    setup_logging()

    mode = "export" if args.export else args.mode
    targets = parse_targets(args.targets)

    asyncio.run(run_pipeline(mode, targets, db_path=args.db))


if __name__ == "__main__":
    main()
