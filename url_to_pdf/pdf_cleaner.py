"""Clean extracted PDF Markdown for optimal LLM consumption.

Removes visual/layout artefacts and low-value content:
  - TOC section
  - Dot-leader lines          (". . . . . 3")
  - Page-number markers       ("--- *Page N*")
  - Running headers/footers   (short lines repeated 3+ times)
  - Cover-page boilerplate    (generated date, page count, etc.)
  - URL-only lines / clusters
  - "Links on this page:" sections
  - "Loading…" / JS-disabled / Google-Translate noise
  - Empty chapters            (chapters whose body is all noise after cleaning)
  - Duplicate headings
  - Excessive blank lines
"""

from __future__ import annotations

import re
from collections import Counter


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def clean_for_llm(markdown: str) -> str:
    """Return a cleaned version of *markdown* suitable for LLM ingestion."""
    lines = markdown.splitlines()

    lines = _remove_toc_section(lines)
    lines = _remove_page_markers(lines)
    lines = _remove_dot_leader_lines(lines)
    lines = _remove_boilerplate_lines(lines)
    lines = _remove_google_translate_blocks(lines)
    lines = _remove_url_clusters(lines)
    lines = _remove_language_selector_blocks(lines)
    lines = _remove_site_navigation_lines(lines)
    lines = _remove_repeated_running_headers(lines)
    lines = _remove_link_dump_sections(lines)
    lines = _remove_duplicate_headings(lines)
    lines = _remove_empty_chapters(lines)
    lines = _collapse_blank_lines(lines)

    text = "\n".join(lines)
    text = _merge_broken_paragraphs(text)
    text = text.strip() + "\n"
    return text


# ---------------------------------------------------------------------------
# Regex constants
# ---------------------------------------------------------------------------

_DOT_LEADER_RE = re.compile(
    r"^[\s.*·•\-]{6,}$"
    r"|"
    r"\.(\s*\.){4,}"
)

_PAGE_MARKER_RE = re.compile(
    r"^---\s*$"
    r"|"
    r"^\*Page\s+\d+\*\s*$"
    r"|"
    r"^-{3,}\s*\*Page\s+\d+\*\s*$"
)

_URL_RE = re.compile(r"https?://\S+")

_BOILERPLATE_RE = re.compile(
    r"^Generated\s+\d{4}-\d{2}-\d{2}\s*$"
    r"|"
    r"^\d+\s+page\(s\)\s+crawled\s*$"
    r"|"
    r"^Copyright\s+©"
    r"|"
    r"^#\s*\(anonymous\)\s*$"
    r"|"
    r"^Log In\s*$"
    r"|"
    r"^Esc\s*$"
    r"|"
    r"^Search Results\s*$"
    r"|"
    r"^Filter by:\s*$"
    r"|"
    r"^Search entire portal\s*$"
    r"|"
    r"^Portal Home Page\s*»?\s*$"
    r"|"
    r"^Remember me\s*$"
    r"|"
    r"^Forgot password\?\s*$"
    r"|"
    r"^Choose your product:\s*$"
    r"|"
    r"^Horizzon Help\s*$"
    r"|"
    r"^Unify Help\s*$"
    r"|"
    r"^Bizzdesign Knowledge Base\s*$"
    r"|"
    r"^Admin login\s*$"
    r"|"
    r"^Hopex Community\s*$"
    r"|"
    r"^Search entire portal\s*$"
    r"|"
    r"^Alfabet Help\s*$"
    r"|"
    r"^Knowledge base\s*$"
    r"|"
    r"^Horizzon help\s*$"
    r"|"
    r"^Unify help\s*$"
    r"|"
    r"^\| \|",                         # table-cell artefacts (even mid-line)
    re.IGNORECASE,
)

# Patterns that indicate junk anywhere within a line (substring match)
_JUNK_SUBSTRING_RE = re.compile(
    r"JavaScript disabled"
    r"|"
    r"Erase the '#!' part"
    r"|"
    r"Loading[…\.]{0,3}"
    r"|"
    r"Rate this translation"
    r"|"
    r"Your feedback will be used to help improve Google Translate"
    r"|"
    r"^\s*Articles\s+Chapter\s+\d+"              # leaked PDF running headers/TOC refs
    r"|"
    r"^Articles\s*$",                            # standalone "Articles" header
    re.IGNORECASE,
)

_MAX_RUNNING_HEADER_LEN = 80
_MIN_REPEAT_COUNT = 3

# A chapter heading in our PDF output looks like "## Chapter N: Title"
_CHAPTER_RE = re.compile(r"^#{1,3}\s*Chapter\s+\d+", re.IGNORECASE)
_ANY_HEADING_RE = re.compile(r"^#{1,6}\s+\S")


# ---------------------------------------------------------------------------
# Individual cleaning passes
# ---------------------------------------------------------------------------


def _remove_toc_section(lines: list[str]) -> list[str]:
    """Drop everything between a TOC heading and the first real chapter."""
    toc_re = re.compile(r"^#{1,3}\s*Table of Contents\s*$", re.IGNORECASE)
    chapter_re = re.compile(r"^#{1,3}\s*(Chapter\s+\d|[A-Z])", re.IGNORECASE)

    in_toc = False
    result: list[str] = []
    for line in lines:
        if toc_re.match(line.strip()):
            in_toc = True
            continue
        if in_toc:
            if chapter_re.match(line.strip()):
                in_toc = False
                result.append(line)
        else:
            result.append(line)
    return result


def _remove_page_markers(lines: list[str]) -> list[str]:
    return [l for l in lines if not _PAGE_MARKER_RE.match(l.strip())]


def _remove_dot_leader_lines(lines: list[str]) -> list[str]:
    result: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            result.append(line)
            continue
        if _DOT_LEADER_RE.search(stripped):
            words = re.sub(r"[.\s·•*\-]+", " ", stripped).strip()
            if len(re.sub(r"\s+", "", words)) < 3:
                continue
        result.append(line)
    return result


def _remove_boilerplate_lines(lines: list[str]) -> list[str]:
    result = []
    for l in lines:
        stripped = l.strip()
        if _BOILERPLATE_RE.match(stripped):
            continue
        if _JUNK_SUBSTRING_RE.search(stripped):
            continue
        result.append(l)
    return result


def _remove_url_clusters(lines: list[str]) -> list[str]:
    """Remove lines that consist only of URLs (possibly space-separated)."""
    result: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            result.append(line)
            continue
        # Strip all URLs and whitespace; if nothing meaningful remains, drop
        without_urls = _URL_RE.sub("", stripped).strip()
        if not without_urls:
            continue  # pure URL line
        # If line is mostly URLs (< 15 non-URL chars), also drop
        if len(without_urls) < 15 and _URL_RE.search(stripped):
            continue
        result.append(line)
    return result


def _remove_google_translate_blocks(lines: list[str]) -> list[str]:
    """Remove Google Translate widget text in all its forms.

    Handles:
    - Standalone lines: "Original text", "Rate this translation", etc.
    - Merged lines where the PDF renderer joined several phrases onto one line.
    - The JS-disabled preamble: "re-load the page to view the content."
    """
    # Phrases that, on their own line, mean the whole line is GT noise
    standalone_re = re.compile(
        r"^\s*("
        r"re-?load the page to view the content\.?"
        r"|Original text"
        r"|Rate this translation"
        r"|Your feedback will be used[\w\s,\.]*"
        r"|Google Translate"
        r")\s*$",
        re.IGNORECASE,
    )

    # Substrings that contaminate a line even when mixed with other text
    contamination_re = re.compile(
        r"re-?load the page to view the content"
        r"|Rate this translation"
        r"|Your feedback will be used to help improve Google Translate"
        r"|Original text\s+Rate this"          # merged form
        r"|Google Translate\.",
        re.IGNORECASE,
    )

    result: list[str] = []
    for line in lines:
        stripped = line.strip()
        if standalone_re.match(stripped):
            continue
        if contamination_re.search(stripped):
            # Strip just the contaminating phrase(s), keep any residual text
            cleaned = contamination_re.sub("", stripped).strip(" .,")
            if cleaned:
                result.append(cleaned)
            # else: nothing left — drop the line
            continue
        result.append(line)
    return result


def _remove_site_navigation_lines(lines: list[str]) -> list[str]:
    """Remove lines that are site-wide navigation boilerplate.

    Handles both:
    - Standalone lines ("Horizzon Help", "Admin login", etc.)
    - Merged lines where the PDF renderer joined several nav items onto one
      long line (the common case after pdf_converter.py's _join_lines pass).
    """
    # Standalone nav anchor texts
    _NAV_TEXTS = frozenset([
        "horizzon help", "unify help", "bizzdesign knowledge base",
        "admin login", "hopex community", "search entire portal",
        "alfabet help", "knowledge base", "horizzon help",
        "bizzdesign support", "analytics and publishing",
        "collaboration", "data integration", "governance",
        "customization", "management and administration",
    ])

    # Nav URL path regex (standalone lines)
    _NAV_URL_RE = re.compile(
        r"^https?://help\.bizzdesign\.com/"
        r"(articles/alfabet-releases|articles/horizzon-help|"
        r"articles/knowledge-base|articles/unify-help|"
        r"login[/?]|search[/?]|forgot-password[/?]|home[/?])?$",
        re.IGNORECASE,
    )

    # Fingerprint: a line is a merged nav block if it contains 3+ of these
    _NAV_FINGERPRINTS = [
        "horizzon help", "unify help", "bizzdesign knowledge base",
        "admin login", "hopex community", "search entire portal",
    ]

    def _is_nav_dump(text: str) -> bool:
        """True if the line is predominantly navigation content."""
        lower = text.lower()
        hits = sum(1 for fp in _NAV_FINGERPRINTS if fp in lower)
        return hits >= 2

    result: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            result.append(line)
            continue
        # Standalone nav anchor text
        if stripped.lower() in _NAV_TEXTS:
            continue
        # Standalone nav URL
        if _NAV_URL_RE.match(stripped):
            continue
        # Merged nav block (PDF-renderer joined multiple nav items)
        if _is_nav_dump(stripped):
            continue
        result.append(line)
    return result


def _remove_language_selector_blocks(lines: list[str]) -> list[str]:
    """Remove language-selector / Google Translate widget text.

    Detects a block by spotting the '› Select Language' marker or a run of
    lines that consist almost entirely of '› <Language name>' entries, then
    drops lines until the block ends (empty line or non-language content).
    """
    # Simple trigger: any line containing the selector header or several
    # consecutive › tokens with known language fragments.
    selector_header_re = re.compile(r"›\s*Select Language", re.IGNORECASE)
    # A language-list line: contains multiple "› Word" groups
    lang_entry_re = re.compile(r"(›\s*[A-Z][a-zA-Z\s\(\)]+){3,}")

    result: list[str] = []
    skip = False

    for line in lines:
        stripped = line.strip()

        if selector_header_re.search(stripped):
            skip = True
            continue

        if skip:
            # Keep skipping while the line looks like language entries or is blank
            if not stripped or lang_entry_re.search(stripped) or stripped.startswith("›"):
                continue
            else:
                skip = False  # real content resumed

        result.append(line)

    return result


def _remove_repeated_running_headers(lines: list[str]) -> list[str]:
    counts: Counter[str] = Counter()
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and len(stripped) <= _MAX_RUNNING_HEADER_LEN:
            counts[stripped] += 1

    repeated = {text for text, cnt in counts.items() if cnt >= _MIN_REPEAT_COUNT}
    return [l for l in lines if l.strip() not in repeated]


def _remove_link_dump_sections(lines: list[str]) -> list[str]:
    link_heading_re = re.compile(r"^#{1,4}\s*Links on this page", re.IGNORECASE)
    url_re = re.compile(r"^\*\*https?://|^https?://")

    result: list[str] = []
    skip = False
    for line in lines:
        stripped = line.strip()
        if link_heading_re.match(stripped):
            skip = True
            continue
        if skip:
            if url_re.match(stripped) or not stripped:
                continue
            else:
                skip = False
        result.append(line)
    return result


def _remove_duplicate_headings(lines: list[str]) -> list[str]:
    result: list[str] = []
    prev_heading = ""
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            if stripped == prev_heading:
                continue
            prev_heading = stripped
        elif stripped:
            prev_heading = ""
        result.append(line)
    return result


def _remove_empty_chapters(lines: list[str]) -> list[str]:
    """Drop chapter sections whose body contains no real prose sentences.

    A 'real' line is non-empty, not a heading, not a URL, and has at least
    one word of 4+ characters (filters out "Esc", "Log In", etc.).
    """
    word_re = re.compile(r"\b\w{4,}\b")

    # Split into sections: list of (heading_line_index, [body_line_indices])
    sections: list[tuple[int | None, list[int]]] = []
    current_heading: int | None = None
    current_body: list[int] = []

    for i, line in enumerate(lines):
        if _CHAPTER_RE.match(line.strip()):
            sections.append((current_heading, current_body))
            current_heading = i
            current_body = []
        else:
            current_body.append(i)
    sections.append((current_heading, current_body))

    def _has_real_content(body_indices: list[int]) -> bool:
        for idx in body_indices:
            line = lines[idx].strip()
            if not line or line.startswith("#") or _URL_RE.match(line):
                continue
            if word_re.search(line):
                return True
        return False

    keep: set[int] = set()
    for heading_idx, body_indices in sections:
        if heading_idx is None:
            # preamble before first chapter — keep
            keep.update(body_indices)
        elif _has_real_content(body_indices):
            keep.add(heading_idx)
            keep.update(body_indices)
        # else: empty chapter — drop heading + body

    return [line for i, line in enumerate(lines) if i in keep]


def _collapse_blank_lines(lines: list[str]) -> list[str]:
    result: list[str] = []
    blank_count = 0
    for line in lines:
        if line.strip() == "":
            blank_count += 1
            if blank_count <= 2:
                result.append(line)
        else:
            blank_count = 0
            result.append(line)
    return result


def _merge_broken_paragraphs(text: str) -> str:
    """Re-join lines split mid-sentence within a paragraph block."""
    block_start_re = re.compile(r"^(#{1,6} |[-*+] |\d+\. |>|\||\s*$)")

    result_paras: list[str] = []
    for para in re.split(r"\n{2,}", text):
        sub_lines = para.splitlines()
        if len(sub_lines) <= 1:
            result_paras.append(para)
            continue
        if all(block_start_re.match(l) for l in sub_lines if l.strip()):
            result_paras.append(para)
            continue

        merged: list[str] = []
        buffer: list[str] = []

        def flush():
            if buffer:
                merged.append(" ".join(buffer))
                buffer.clear()

        for line in sub_lines:
            if block_start_re.match(line):
                flush()
                merged.append(line)
            else:
                buffer.append(line.strip())
        flush()
        result_paras.append("\n".join(merged))

    return "\n\n".join(result_paras)
