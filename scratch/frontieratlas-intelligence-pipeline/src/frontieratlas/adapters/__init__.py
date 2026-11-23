"""Vertical source adapters."""

from frontieratlas.adapters.base import BaseAdapter
from frontieratlas.adapters.startups import StartupsAdapter
from frontieratlas.adapters.products import ProductsAdapter
from frontieratlas.adapters.research import ResearchAdapter
from frontieratlas.adapters.news import NewsAdapter
from frontieratlas.adapters.jobs import JobsAdapter

__all__ = [
    "BaseAdapter",
    "StartupsAdapter",
    "ProductsAdapter",
    "ResearchAdapter",
    "NewsAdapter",
    "JobsAdapter"
]
