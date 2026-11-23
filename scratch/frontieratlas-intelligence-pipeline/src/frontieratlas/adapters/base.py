"""Base adapter contract for FrontierAtlas data sources."""

from __future__ import annotations

import abc
import logging
from typing import Any, Dict, List, Optional

from frontieratlas.crawler.http_client import AsyncHTTPClient
from frontieratlas.llm.orchestrator import LLMOrchestrator
from frontieratlas.resolver.entity_resolver import EntityResolver
from frontieratlas.storage import StorageEngine

logger = logging.getLogger(__name__)


class BaseAdapter(abc.ABC):
    """Abstract base class for all vertical source adapters."""

    def __init__(
        self,
        http_client: AsyncHTTPClient,
        llm_orchestrator: LLMOrchestrator,
        entity_resolver: EntityResolver,
        storage: StorageEngine
    ) -> None:
        self.http = http_client
        self.llm = llm_orchestrator
        self.resolver = entity_resolver
        self.storage = storage

    @abc.abstractmethod
    async def fetch(self, target_count: int = 1000) -> List[Dict[str, Any]]:
        """Fetch, normalize, resolve, and persist records up to target_count."""
        raise NotImplementedError
