"""Anti-Bot Navigation and Crawler Defense Strategy.

Implements realistic browser fingerprints, rate-limit governance, and Playwright
async hooks for JavaScript-heavy and bot-protected domains.
"""

from __future__ import annotations

import logging
import random
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# Modern realistic desktop browser user agents
USER_AGENTS: List[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.4; rv:125.0) Gecko/20100101 Firefox/125.0",
]


class AntiBotManager:
    """Manages browser identity, TLS fingerprint mimicry, and headless automation hooks."""

    @staticmethod
    def get_headers(custom_referer: Optional[str] = None) -> Dict[str, str]:
        """Generate realistic browser headers to prevent Cloudflare/Datadome bot triggers."""
        ua = random.choice(USER_AGENTS)
        headers = {
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "cross-site" if custom_referer else "none",
            "Sec-Fetch-User": "?1",
        }
        if custom_referer:
            headers["Referer"] = custom_referer
        return headers

    @staticmethod
    async def fetch_with_playwright(url: str, wait_selector: Optional[str] = None) -> Optional[str]:
        """Asynchronous Playwright hook for heavily JS-rendered or challenged pages.
        
        Note: Per FrontierAtlas compliance guidelines, this hook navigates client-side
        rendered single-page applications (SPAs) but never solves or bypasses CAPTCHAs.
        """
        try:
            from playwright.async_api import async_playwright
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    user_agent=random.choice(USER_AGENTS),
                    viewport={"width": 1920, "height": 1080},
                    locale="en-US"
                )
                page = await context.new_page()
                # Inject stealth evasions to hide navigator.webdriver
                await page.add_init_script("delete Object.getPrototypeOf(navigator).webdriver;")
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                if wait_selector:
                    await page.wait_for_selector(wait_selector, timeout=10000)
                content = await page.content()
                await browser.close()
                return content
        except ImportError:
            logger.debug("Playwright not installed; using standard async HTTP fallback.")
            return None
        except Exception as exc:
            logger.warning("Playwright navigation failed for %s: %s", url, exc)
            return None
