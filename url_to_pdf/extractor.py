"""Page fetching (Playwright, JS-rendered) and main-body text extraction."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

import trafilatura
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, Page as PWPage, Browser, Frame

from .utils import normalise_url, is_ad_url, same_domain, is_ad_class

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Page:
    url: str
    title: str
    text: str                        # main body text (plain)
    child_links: list[str] = field(default_factory=list)
    depth: int = 0


# ---------------------------------------------------------------------------
# Browser context manager
# ---------------------------------------------------------------------------


class BrowserSession:
    """Wraps a Playwright browser for re-use across many fetches."""

    def __init__(self, timeout: float = 20.0):
        self._pw = sync_playwright().start()
        self._browser: Browser = self._pw.chromium.launch(headless=True)
        self._context = self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        self._timeout_ms = int(timeout * 1000)

    def get_page_data(self, url: str) -> Optional[tuple[str, list[str]]]:
        """Load *url*, collect HTML from all frames.

        Returns (combined_html, list_of_frame_htmls) or None on error.
        """
        try:
            pw_page: PWPage = self._context.new_page()
            pw_page.goto(url, wait_until="networkidle", timeout=self._timeout_ms)
            pw_page.wait_for_timeout(1500)

            # Collect HTML from every frame (catches srcdoc / inline iframes)
            frame_htmls: list[str] = []
            for frame in pw_page.frames:
                try:
                    fhtml = frame.content()
                    if fhtml and len(fhtml) > 200:
                        frame_htmls.append(fhtml)
                except Exception:
                    pass

            pw_page.close()
            return frame_htmls
        except Exception:
            try:
                pw_page.close()
            except Exception:
                pass
            return None

    def close(self):
        try:
            self._context.close()
            self._browser.close()
            self._pw.stop()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def _extract_links(html: str, base_url: str, base_domain: str) -> list[str]:
    """Pull same-domain links from an HTML snippet."""
    soup = BeautifulSoup(html, "lxml")
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        # Skip JS pseudo-links and plain anchors
        if href.startswith("javascript:") or href == "#":
            continue
        # Skip links inside obvious ad containers
        parents_classes = " ".join(
            " ".join(p.get("class", [])) + " " + (p.get("id") or "")
            for p in a.parents
            if hasattr(p, "get")
        )
        if is_ad_class(parents_classes):
            continue
        href = normalise_url(href, base=base_url)
        if not href.startswith("http"):
            continue
        if is_ad_url(href):
            continue
        if not same_domain(href, base_domain):
            continue
        links.append(href)
    return links


def fetch_and_extract(
    url: str,
    session: BrowserSession,
    base_domain: str,
    include_images: bool = False,
    delay: float = 0.5,
) -> Optional[Page]:
    """Fetch *url* via headless browser, extract main body text and child links.

    Collects content from all frames (handles srcdoc iframes).
    Returns None on error or if no meaningful content found.
    """
    time.sleep(delay)

    frame_htmls = session.get_page_data(url)
    if not frame_htmls:
        return None

    # Main frame is first; use it for title
    main_html = frame_htmls[0]
    soup_main = BeautifulSoup(main_html, "lxml")
    title_tag = soup_main.find("title")
    title = title_tag.get_text(strip=True) if title_tag else url

    # Extract body text from each frame, prefer non-empty results
    combined_text_parts: list[str] = []
    for fhtml in frame_htmls:
        text = trafilatura.extract(
            fhtml,
            url=url,
            include_images=include_images,
            include_links=False,
            include_tables=True,
            no_fallback=False,
            favor_recall=True,
        )
        if text and text.strip():
            combined_text_parts.append(text.strip())

    full_text = "\n\n".join(combined_text_parts)

    # Collect links from all frames
    all_links: list[str] = []
    for fhtml in frame_htmls:
        all_links.extend(_extract_links(fhtml, base_url=url, base_domain=base_domain))

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique_links: list[str] = []
    for lnk in all_links:
        if lnk not in seen:
            seen.add(lnk)
            unique_links.append(lnk)

    return Page(url=url, title=title, text=full_text, child_links=unique_links)
