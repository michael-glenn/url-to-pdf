"""BFS crawler with depth control, deduplication, and live progress."""

from __future__ import annotations

from collections import deque
from typing import Optional

from bs4 import BeautifulSoup

from .extractor import Page, fetch_and_extract, BrowserSession
from .utils import get_domain, normalise_url, is_ad_url, same_domain


# ---------------------------------------------------------------------------
# Shallow estimate
# ---------------------------------------------------------------------------


def estimate_link_count(start_url: str, max_depth: int = 2) -> int:
    """Quick BFS to estimate total reachable pages (JS-rendered)."""
    domain = get_domain(start_url)
    visited: set[str] = set()
    queue: deque[tuple[str, int]] = deque([(start_url, 0)])
    visited.add(start_url)

    session = BrowserSession(timeout=15.0)
    count = 0

    try:
        while queue:
            url, depth = queue.popleft()
            count += 1
            print(
                f"\r  Scanning depth {depth:2d} | pages found: {count:4d} | queue: {len(queue):4d}  ",
                end="",
                flush=True,
            )
            if depth >= max_depth:
                continue
            frame_htmls = session.get_page_data(url)
            if not frame_htmls:
                continue
            for html in frame_htmls:
                soup = BeautifulSoup(html, "lxml")
                for a in soup.find_all("a", href=True):
                    href = normalise_url(a["href"], base=url)
                    if not href.startswith("http"):
                        continue
                    if is_ad_url(href):
                        continue
                    if not same_domain(href, domain):
                        continue
                    if href not in visited:
                        visited.add(href)
                        queue.append((href, depth + 1))
    finally:
        print()  # newline after progress
        session.close()

    return count


# ---------------------------------------------------------------------------
# Main crawl
# ---------------------------------------------------------------------------


def crawl(
    start_url: str,
    max_depth: Optional[int],
    delay: float = 0.5,
    include_images: bool = False,
) -> list[Page]:
    """BFS crawl returning ordered list of Pages (root first).

    *max_depth* of None means unlimited.
    """
    domain = get_domain(start_url)
    visited: set[str] = set()
    queue: deque[tuple[str, int]] = deque([(start_url, 0)])
    visited.add(start_url)
    pages: list[Page] = []

    session = BrowserSession()

    try:
        while queue:
            url, depth = queue.popleft()

            print(
                f"\r  Crawling depth {depth:2d} | pages found: {len(pages):4d} | queue: {len(queue):4d}  ",
                end="",
                flush=True,
            )

            page = fetch_and_extract(
                url,
                session=session,
                base_domain=domain,
                include_images=include_images,
                delay=delay,
            )
            if page is None:
                continue
            page.depth = depth
            pages.append(page)

            if max_depth is not None and depth >= max_depth:
                continue

            for child_url in page.child_links:
                if child_url not in visited:
                    visited.add(child_url)
                    queue.append((child_url, depth + 1))
    finally:
        session.close()
        print()  # newline after progress

    return pages
