"""Precision Date Normalization and 24-Hour Freshness Engine.

Extracts, normalizes, and validates publication dates across diverse formats
(ISO-8601, RFC-2822, relative strings like '2 hours ago', and HTML meta tags),
enforcing strict 24-hour freshness gating for News and Jobs.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class FreshnessGate:
    """Validates and filters records according to strict 24-hour freshness criteria."""

    RELATIVE_TIME_PATTERNS = [
        (re.compile(r"(\d+)\s*(?:m|min|mins|minute|minutes)\s+ago", re.I), lambda m: timedelta(minutes=int(m.group(1)))),
        (re.compile(r"(\d+)\s*(?:h|hr|hrs|hour|hours)\s+ago", re.I), lambda m: timedelta(hours=int(m.group(1)))),
        (re.compile(r"(\d+)\s*(?:d|day|days)\s+ago", re.I), lambda m: timedelta(days=int(m.group(1)))),
        (re.compile(r"yesterday", re.I), lambda _: timedelta(days=1)),
        (re.compile(r"just\s+now|moments?\s+ago", re.I), lambda _: timedelta(seconds=10)),
    ]

    META_TAG_PATTERNS = [
        re.compile(r'<meta[^>]+(?:property|name)=["\'](?:article:published_time|datePublished|pubdate|DC\.date\.issued|date)["\'][^>]+content=["\']([^"\']+)["\']', re.I),
        re.compile(r'<time[^>]+datetime=["\']([^"\']+)["\']', re.I),
        re.compile(r'["\']datePublished["\']:\s*["\']([^"\']+)["\']', re.I)
    ]

    @staticmethod
    def parse_relative_date(date_str: str, reference_time: Optional[datetime] = None) -> Optional[datetime]:
        """Convert relative strings ('2 hours ago', 'yesterday') into UTC datetime."""
        ref = reference_time or datetime.now(timezone.utc)
        clean = date_str.strip()
        for pat, delta_func in FreshnessGate.RELATIVE_TIME_PATTERNS:
            match = pat.search(clean)
            if match:
                delta = delta_func(match)
                return ref - delta
        return None

    @classmethod
    def normalize_to_utc(
        cls,
        date_input: Optional[str],
        reference_time: Optional[datetime] = None,
        html_content: Optional[str] = None
    ) -> Tuple[Optional[datetime], str]:
        """Normalize any date representation to timezone-aware UTC datetime.
        
        Returns:
            Tuple[Optional[datetime], str]: (parsed_datetime_utc, provenance_source)
        """
        ref = reference_time or datetime.now(timezone.utc)

        # 1. Try direct string parsing if provided
        if date_input and date_input.strip():
            raw = date_input.strip()

            # A. Check relative time pattern
            rel_dt = cls.parse_relative_date(raw, ref)
            if rel_dt:
                return rel_dt.astimezone(timezone.utc), "RELATIVE_EXPRESSION"

            # B. Try RFC-2822 (standard in RSS feeds, e.g. 'Mon, 23 Nov 2026 12:00:00 GMT')
            try:
                rfc_dt = parsedate_to_datetime(raw)
                if rfc_dt:
                    if rfc_dt.tzinfo is None:
                        rfc_dt = rfc_dt.replace(tzinfo=timezone.utc)
                    return rfc_dt.astimezone(timezone.utc), "RFC_2822"
            except Exception:
                pass

            # C. Try ISO-8601 variants
            try:
                # Handle trailing Z
                iso_str = raw.replace("Z", "+00:00")
                iso_dt = datetime.fromisoformat(iso_str)
                if iso_dt.tzinfo is None:
                    iso_dt = iso_dt.replace(tzinfo=timezone.utc)
                return iso_dt.astimezone(timezone.utc), "ISO_8601"
            except Exception:
                pass

            # D. Try common standard date formats
            common_formats = [
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M",
                "%Y-%m-%d",
                "%b %d, %Y",
                "%B %d, %Y",
                "%d %b %Y %H:%M:%S",
                "%d %b %Y"
            ]
            for fmt in common_formats:
                try:
                    dt = datetime.strptime(raw, fmt)
                    dt = dt.replace(tzinfo=timezone.utc)
                    return dt, f"FORMAT_{fmt}"
                except ValueError:
                    continue

        # 2. Try HTML meta tag extraction if html_content provided
        if html_content:
            for pat in cls.META_TAG_PATTERNS:
                match = pat.search(html_content)
                if match:
                    extracted_str = match.group(1).strip()
                    parsed, _ = cls.normalize_to_utc(extracted_str, ref)
                    if parsed:
                        return parsed, "HTML_META_TAG"

        return None, "UNRESOLVED"

    @classmethod
    def is_within_24_hours(
        cls,
        date_input: Optional[str],
        reference_time: Optional[datetime] = None,
        html_content: Optional[str] = None
    ) -> Tuple[bool, Optional[str], str]:
        """Check if record was published strictly within the last 24 hours.
        
        Returns:
            Tuple[bool, Optional[str], str]: (is_fresh, iso_timestamp, provenance)
        """
        ref = reference_time or datetime.now(timezone.utc)
        dt_utc, provenance = cls.normalize_to_utc(date_input, ref, html_content)

        if not dt_utc:
            # Per assignment: missing/ambiguous dates do NOT qualify as guaranteed fresh
            return False, None, provenance

        time_diff = ref - dt_utc
        total_seconds = time_diff.total_seconds()

        # Strict 24-hour gate (allowing small forward clock drift up to 10 minutes)
        if -600 <= total_seconds <= 86400:
            return True, dt_utc.isoformat(), provenance

        return False, dt_utc.isoformat(), provenance
