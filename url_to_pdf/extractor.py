"""Page fetching (Playwright, JS-rendered) and main-body text extraction."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

import subprocess
import sys

import trafilatura
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, Page as PWPage, Browser, Frame

from .utils import normalise_url, is_ad_url, same_domain, is_ad_class


def _ensure_browser_installed() -> None:
    """Install Playwright's Chromium browser if it isn't already present."""
    try:
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        pw.chromium.launch(headless=True).close()
        pw.stop()
    except Exception:
        print("Playwright browser not found — installing Chromium (one-time setup)...")
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=True,
        )
        print("Chromium installed successfully.\n")

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Page:
    url: str
    title: str
    text: str                        # main body text (plain)
    child_links: list[tuple[str, str]] = field(default_factory=list)
    # Each entry is (url, display_text).  display_text is the anchor text
    # visible to the user; it equals the url only when the url was explicitly
    # shown as text on the page.
    depth: int = 0


# ---------------------------------------------------------------------------
# Browser context manager
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Site-wide navigation link filtering
# ---------------------------------------------------------------------------

# URL path suffixes that are site-wide navigation, not content links.
# Matching is done against the path component of crawled links.
_NAV_PATHS: frozenset[str] = frozenset([
    "/",
    "/articles/",
    "/articles/alfabet-releases",
    "/articles/horizzon-help",
    "/articles/knowledge-base",
    "/articles/unify-help",
    "/login/",
    "/search/",
    "/forgot-password/",
    "/home/",
])

# Anchor texts that indicate site-wide navigation rather than content links.
_NAV_ANCHOR_TEXTS: frozenset[str] = frozenset([
    "horizzon help", "unify help", "bizzdesign knowledge base",
    "admin login", "hopex community", "search entire portal",
    "alfabet help", "knowledge base", "horizzon help",
    "bizzdesign support", "documentation", "releases",
    "contact support", "training courses",
])


def _is_nav_link(url: str, anchor_text: str) -> bool:
    """Return True if this link is site-wide navigation rather than content."""
    from urllib.parse import urlparse
    path = urlparse(url).path.rstrip("/") + "/"
    # Match known navigation paths exactly
    for nav in _NAV_PATHS:
        nav_norm = nav.rstrip("/") + "/"
        if path == nav_norm:
            return True
    # Match by anchor text (case-insensitive)
    if anchor_text.strip().lower() in _NAV_ANCHOR_TEXTS:
        return True
    return False


# ---------------------------------------------------------------------------
# Frame filtering
# ---------------------------------------------------------------------------

# Language names that reliably appear in translation-widget frames
_LANG_SELECTOR_LANGUAGES = frozenset([
    "Abkhaz", "Acehnese", "Acholi", "Afrikaans", "Albanian", "Amharic",
    "Azerbaijani", "Belarusian", "Bulgarian", "Cantonese", "Catalan",
    "Cebuano", "Croatian", "Czech", "Danish", "Estonian", "Filipino",
    "Finnish", "Galician", "Georgian", "Gujarati", "Hausa", "Hebrew",
    "Hungarian", "Icelandic", "Indonesian", "Japanese", "Javanese",
    "Kannada", "Kazakh", "Khmer", "Kinyarwanda", "Korean", "Kyrgyz",
    "Latvian", "Lithuanian", "Macedonian", "Malagasy", "Malayalam",
    "Marathi", "Mongolian", "Nepali", "Norwegian", "Punjabi", "Romanian",
    "Serbian", "Sinhala", "Slovak", "Slovenian", "Somali", "Swahili",
    "Tajik", "Tamil", "Telugu", "Turkish", "Turkmen", "Ukrainian",
    "Uzbek", "Vietnamese", "Zulu",
])


def _is_widget_frame(html: str) -> bool:
    """Return True if *html* looks like a UI widget frame to skip.

    Detects:
    - Google Translate language-selector dropdowns
    - Any frame whose visible text is >60 % known language names
    """
    # Quick keyword check — "Select Language" heading is a reliable signal
    if "Select Language" in html and "Abkhaz" in html:
        return True

    # Count language-name hits in a plain-text excerpt
    text_sample = html[:8000]
    hits = sum(1 for lang in _LANG_SELECTOR_LANGUAGES if lang in text_sample)
    if hits >= 20:
        return True

    return False


# ---------------------------------------------------------------------------
# Browser session
# ---------------------------------------------------------------------------


class BrowserSession:
    """Wraps a Playwright browser for re-use across many fetches."""

    def __init__(self, timeout: float = 20.0):
        _ensure_browser_installed()
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

            # Collect HTML from every frame (catches srcdoc / inline iframes).
            # Skip widget frames such as the Google Translate language selector.
            frame_htmls: list[str] = []
            for frame in pw_page.frames:
                try:
                    fhtml = frame.content()
                    if fhtml and len(fhtml) > 200 and not _is_widget_frame(fhtml):
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


# ---------------------------------------------------------------------------
# Google Translate noise scrubber
# ---------------------------------------------------------------------------

import re as _re

# Phrases that appear as a block wherever Google Translate injects its widget.
# Matched as a contiguous run so partial appearances (e.g. mid-sentence) are
# not over-zealously stripped.
_GT_BLOCK_RE = _re.compile(
    r"("
    r"re-load the page to view the content\.?"
    r"|Original text"
    r"|Rate this translation"
    r"|Your feedback will be used to help improve Google Translate\.?"
    r")"
    r"[\s\S]{0,200}?"          # optional bridge between adjacent phrases
    r"(?="                     # look-ahead for the next phrase or end
    r"Original text"
    r"|Rate this translation"
    r"|Your feedback will be used"
    r"|$)",
    _re.IGNORECASE,
)

# Simpler per-sentence scrub for phrases that survive as isolated sentences
_GT_LINE_RE = _re.compile(
    r"^\s*("
    r"re-?load the page to view the content\.?"
    r"|Original text"
    r"|Rate this translation"
    r"|Your feedback will be used[\w\s,\.]*"
    r"|Google Translate"
    r")\s*$",
    _re.IGNORECASE | _re.MULTILINE,
)


def _scrub_google_translate(text: str) -> str:
    """Remove Google Translate widget phrases from extracted body text."""
    text = _GT_BLOCK_RE.sub("", text)
    text = _GT_LINE_RE.sub("", text)
    # Collapse runs of blank lines left behind
    text = _re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------


def _extract_links(html: str, base_url: str, base_domain: str) -> list[tuple[str, str]]:
    """Pull same-domain links from an HTML snippet.

    Returns list of (url, display_text) tuples.  display_text is the
    visible anchor text; it falls back to the URL when the anchor text is
    empty or is itself a URL.
    """
    soup = BeautifulSoup(html, "lxml")
    links: list[tuple[str, str]] = []
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
        anchor_text = a.get_text(separator=" ", strip=True)
        # Use anchor text only when it adds meaning beyond the URL itself
        if not anchor_text or anchor_text.startswith("http"):
            display = href          # URL was explicitly shown or no text
        else:
            display = anchor_text
        # Skip site-wide navigation links
        if _is_nav_link(href, display):
            continue
        links.append((href, display))
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
            text = _scrub_google_translate(text)
            if text:
                combined_text_parts.append(text)

    full_text = "\n\n".join(combined_text_parts)

    # Collect links from all frames
    all_links: list[tuple[str, str]] = []
    for fhtml in frame_htmls:
        all_links.extend(_extract_links(fhtml, base_url=url, base_domain=base_domain))

    # Deduplicate by URL while preserving order
    seen: set[str] = set()
    unique_links: list[tuple[str, str]] = []
    for lnk_url, lnk_text in all_links:
        if lnk_url not in seen:
            seen.add(lnk_url)
            unique_links.append((lnk_url, lnk_text))

    return Page(url=url, title=title, text=full_text, child_links=unique_links)
