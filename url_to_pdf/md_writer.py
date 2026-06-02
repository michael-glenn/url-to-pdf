"""Direct crawl → topic-grouped Markdown files (no PDF intermediate).

Instead of crawl → PDF → Markdown, this module writes the crawled Page
objects directly to .md files, grouped by URL topic.  This avoids all the
PDF layout artefacts (dot leaders, running headers, merged nav blocks, etc.)
that the cleaning pass has to fight when converting from PDF.

Output layout
-------------
  <output_dir>/
    index.md          — table of contents (one line per group)
    <group-1>.md      — all pages whose URL path falls under group 1
    <group-2>.md      — ...
    ...

Grouping strategy
-----------------
Pages are grouped by the first "meaningful" URL path segment after the
start-URL prefix.  For example, given start URL

    https://help.example.com/articles/

the page

    https://help.example.com/articles/horizzon-help/navigating-a-site

is placed in the group "horizzon-help", while

    https://help.example.com/articles/

itself (or any page with no further path) goes into the special group
"_root".

If the start URL has no useful sub-path (e.g. it is the domain root
https://example.com/) then pages are grouped by their own first path
segment.

Within each group, pages are ordered by crawl order (BFS, so shallower
pages come first).
"""

from __future__ import annotations

import os
import re
from collections import defaultdict
from urllib.parse import urlparse

from .extractor import Page
from .utils import url_to_filename


# ---------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------


def _path_segments(url: str) -> list[str]:
    return [p for p in urlparse(url).path.split("/") if p]


def _group_key(page: Page, start_url: str) -> str:
    """Return the group key for a page relative to the start URL."""
    start_segs = _path_segments(start_url)
    page_segs = _path_segments(page.url)

    # Strip the common prefix shared with the start URL
    prefix_len = 0
    for a, b in zip(start_segs, page_segs):
        if a == b:
            prefix_len += 1
        else:
            break

    remaining = page_segs[prefix_len:]
    if not remaining:
        return "_root"
    # Use the first remaining segment as the group key
    return remaining[0]


def group_pages(pages: list[Page], start_url: str) -> dict[str, list[Page]]:
    """Return an ordered dict mapping group key → list of Pages."""
    groups: dict[str, list[Page]] = defaultdict(list)
    for page in pages:
        key = _group_key(page, start_url)
        groups[key].append(page)
    # Move _root to front if present
    ordered: dict[str, list[Page]] = {}
    if "_root" in groups:
        ordered["_root"] = groups.pop("_root")
    ordered.update(groups)
    return ordered


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

def _slugify(text: str) -> str:
    """Convert a group key or title to a safe filename stem."""
    text = re.sub(r"[^\w\-]", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text[:60] or "section"


def _render_page(page: Page) -> str:
    """Render a single Page as Markdown text."""
    lines: list[str] = []

    # Page heading
    lines.append(f"## {page.title}")
    lines.append(f"*Source: {page.url}*")
    lines.append("")

    body = page.text.strip()
    if body:
        # Apply lightweight inline cleaning
        body = _clean_body(body)
        lines.append(body)
    else:
        lines.append("*(No content extracted from this page.)*")

    lines.append("")
    return "\n".join(lines)


def _clean_body(text: str) -> str:
    """Quick inline cleaning of extracted body text for direct MD output.

    This is lighter than the full pdf_cleaner pipeline (there's nothing to
    clean from PDF artefacts) but still removes Google Translate noise and
    collapses excessive blank lines.
    """
    import re as _re

    # Google Translate widget phrases
    _gt = _re.compile(
        r"(re-?load the page to view the content\.?"
        r"|Original text\s*"
        r"|Rate this translation\s*"
        r"|Your feedback will be used[\w\s,\.]*"
        r"|Google Translate\.?)",
        _re.IGNORECASE,
    )
    text = _gt.sub("", text)

    # Collapse 3+ blank lines to 2
    text = _re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def _render_group(
    group_key: str,
    pages: list[Page],
    start_url: str,
) -> str:
    """Render all pages in a group as a single Markdown document."""
    # Human-readable title
    if group_key == "_root":
        title = urlparse(start_url).netloc
    else:
        title = group_key.replace("-", " ").replace("_", " ").title()

    header = [
        f"# {title}",
        "",
        f"*{len(pages)} page(s) — source: {start_url}*",
        "",
        "---",
        "",
    ]

    body = "\n\n".join(_render_page(p) for p in pages)
    return "\n".join(header) + "\n" + body


def _render_index(
    groups: dict[str, list[Page]],
    start_url: str,
    filenames: dict[str, str],
) -> str:
    """Render a top-level index.md that links to every group file."""
    domain = urlparse(start_url).netloc
    lines = [
        f"# {domain} — Content Index",
        "",
        f"Crawled from: {start_url}",
        "",
        "| Section | Pages | File |",
        "|---|---|---|",
    ]
    for key, pages in groups.items():
        title = "Root" if key == "_root" else key.replace("-", " ").replace("_", " ").title()
        fname = filenames[key]
        lines.append(f"| {title} | {len(pages)} | [{fname}]({fname}) |")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def write_single_markdown(
    pages: list[Page],
    start_url: str,
    output_path: str,
) -> str:
    """Write all crawled pages to a single Markdown file.

    Pages are rendered in crawl order (BFS, shallower first), separated by
    horizontal rules.  Returns the output path written.
    """
    from urllib.parse import urlparse
    domain = urlparse(start_url).netloc

    header = [
        f"# {domain}",
        "",
        f"*Crawled from: {start_url} — {len(pages)} page(s)*",
        "",
        "---",
        "",
    ]

    body = "\n\n---\n\n".join(_render_page(p) for p in pages)
    content = "\n".join(header) + "\n" + body

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"  Written {len(pages)} page(s) → {output_path}")
    return output_path


def write_markdown_dir(
    pages: list[Page],
    start_url: str,
    output_dir: str,
) -> dict[str, str]:
    """Write topic-grouped Markdown files to *output_dir*.

    Returns a dict mapping group key → file path written.
    """
    os.makedirs(output_dir, exist_ok=True)

    groups = group_pages(pages, start_url)

    # Build filename map (ensure no collisions)
    filenames: dict[str, str] = {}
    used: set[str] = set()
    for key in groups:
        stem = "root" if key == "_root" else _slugify(key)
        fname = f"{stem}.md"
        # Handle collision
        n = 2
        while fname in used:
            fname = f"{stem}_{n}.md"
            n += 1
        filenames[key] = fname
        used.add(fname)

    written: dict[str, str] = {}

    # Write group files
    for key, page_list in groups.items():
        content = _render_group(key, page_list, start_url)
        path = os.path.join(output_dir, filenames[key])
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        written[key] = path

    # Write index
    index_content = _render_index(groups, start_url, filenames)
    index_path = os.path.join(output_dir, "index.md")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(index_content)

    print(f"  Written {len(groups)} section file(s) + index.md → {output_dir}")
    return written
