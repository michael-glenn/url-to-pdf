"""Convert an existing PDF file to plain Markdown.

Two output modes:
  Single file  — pdf_to_markdown()      writes one .md file
  Split by topic — pdf_to_markdown_dir() groups chapters and writes one
                   .md file per topic into a directory, plus an index.md
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse


# ---------------------------------------------------------------------------
# Public API — single file
# ---------------------------------------------------------------------------

def pdf_to_markdown(
    input_path: str,
    output_path: str | None = None,
    clean: bool = False,
) -> str:
    """Read *input_path* PDF and write Markdown to *output_path*.

    If *clean* is True, run an LLM-optimisation pass before writing.
    Returns the output file path used.
    """
    src, doc, page_count = _open_pdf(input_path)
    dest = Path(output_path) if output_path else src.with_suffix(".md")

    print(f"Converting: {src}")
    print(f"       To:  {dest}")

    markdown = _extract_markdown(doc)
    doc.close()

    markdown = _clean_markdown(markdown)
    if clean:
        from .pdf_cleaner import clean_for_llm
        print("Cleaning for LLM use...")
        markdown = clean_for_llm(markdown)

    dest.write_text(markdown, encoding="utf-8")
    print(f"Done — {page_count} page(s) converted.")
    return str(dest)


# ---------------------------------------------------------------------------
# Public API — split into topic-grouped directory
# ---------------------------------------------------------------------------

def pdf_to_markdown_dir(
    input_path: str,
    output_dir: str | None = None,
    clean: bool = False,
) -> dict[str, str]:
    """Convert a PDF to topic-grouped Markdown files in *output_dir*.

    Each chapter group gets its own .md file; an index.md links them all.
    Grouping is based on the source URL embedded in each chapter (if present),
    falling back to the chapter title when no URL is found.

    Returns a dict mapping group name -> file path written.
    """
    src, doc, page_count = _open_pdf(input_path)

    if output_dir:
        out_dir = Path(output_dir)
    else:
        out_dir = src.parent / src.stem

    print(f"Converting: {src}")
    print(f"  To dir:   {out_dir}/")

    markdown = _extract_markdown(doc)
    doc.close()

    markdown = _clean_markdown(markdown)
    if clean:
        from .pdf_cleaner import clean_for_llm
        print("Cleaning for LLM use...")
        markdown = clean_for_llm(markdown)

    # Split into chapters and group by topic
    chapters = _split_chapters(markdown)
    groups = _group_chapters(chapters)

    out_dir.mkdir(parents=True, exist_ok=True)

    # Write group files
    written: dict[str, str] = {}
    filenames: dict[str, str] = {}
    used: set[str] = set()

    for group_key in groups:
        stem = _slugify(group_key)
        fname = f"{stem}.md"
        n = 2
        while fname in used:
            fname = f"{stem}_{n}.md"
            n += 1
        used.add(fname)
        filenames[group_key] = fname

    for group_key, chapter_texts in groups.items():
        title = group_key.replace("-", " ").replace("_", " ").title()
        content = f"# {title}\n\n" + "\n\n---\n\n".join(chapter_texts)
        path = out_dir / filenames[group_key]
        path.write_text(content, encoding="utf-8")
        written[group_key] = str(path)

    # Write index
    index_lines = [
        f"# {src.stem} — Content Index",
        "",
        "| Section | File |",
        "|---|---|",
    ]
    for group_key, fname in filenames.items():
        title = group_key.replace("-", " ").replace("_", " ").title()
        index_lines.append(f"| {title} | [{fname}]({fname}) |")
    index_lines.append("")
    (out_dir / "index.md").write_text("\n".join(index_lines), encoding="utf-8")

    print(f"Done — {page_count} page(s) → {len(groups)} section file(s) + index.md")
    return written


# ---------------------------------------------------------------------------
# Chapter splitting and grouping
# ---------------------------------------------------------------------------

# Matches headings like "## Chapter 3: Bizzdesign Support - Navigating a site"
_CHAPTER_HEADING_RE = re.compile(
    r"^#{1,3}\s*Chapter\s+\d+[:\.]?\s*(.+)$",
    re.IGNORECASE | re.MULTILINE,
)

# Matches a URL line anywhere in a chapter's first 300 chars
_URL_RE = re.compile(r"https?://\S+")


def _split_chapters(markdown: str) -> list[str]:
    """Split markdown into a list of chapter texts."""
    # Find all chapter heading positions
    positions = [m.start() for m in _CHAPTER_HEADING_RE.finditer(markdown)]
    if not positions:
        return [markdown]

    chapters: list[str] = []
    # Preamble before first chapter
    if positions[0] > 0:
        pre = markdown[:positions[0]].strip()
        if pre:
            chapters.append(pre)

    for i, pos in enumerate(positions):
        end = positions[i + 1] if i + 1 < len(positions) else len(markdown)
        chapters.append(markdown[pos:end].strip())

    return chapters


def _chapter_group_key(chapter_text: str) -> str:
    """Derive a group key from a chapter's content.

    Prefers the URL path segment (most reliable); falls back to the title.
    """
    # Look for a URL in the first 400 characters
    snippet = chapter_text[:400]
    url_match = _URL_RE.search(snippet)
    if url_match:
        url = url_match.group()
        path_parts = [p for p in urlparse(url).path.split("/") if p]
        if len(path_parts) >= 2:
            return path_parts[-2]   # second-to-last segment = section
        if path_parts:
            return path_parts[0]

    # Fall back to the chapter heading title, simplified
    heading_match = _CHAPTER_HEADING_RE.match(chapter_text)
    if heading_match:
        title = heading_match.group(1)
        # Strip leading "Bizzdesign Support - " or similar prefixes
        title = re.sub(r"^[\w\s]+\s*-\s*", "", title, count=1)
        return _slugify(title)[:40] or "section"

    return "_misc"


def _group_chapters(chapters: list[str]) -> dict[str, list[str]]:
    """Group chapter texts by topic key, preserving insertion order."""
    groups: dict[str, list[str]] = {}
    for chapter in chapters:
        key = _chapter_group_key(chapter)
        groups.setdefault(key, []).append(chapter)
    return groups


def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\-]", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text[:60] or "section"


# ---------------------------------------------------------------------------
# PDF extraction helpers
# ---------------------------------------------------------------------------

def _open_pdf(input_path: str):
    """Open and validate a PDF, returning (Path, fitz.Document, page_count)."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        print("PyMuPDF is not installed. Run:  py -m pip install pymupdf", file=sys.stderr)
        sys.exit(1)

    src = Path(input_path)
    if not src.exists():
        print(f"Error: file not found: {input_path}", file=sys.stderr)
        sys.exit(1)
    if src.suffix.lower() != ".pdf":
        print(f"Error: input file must be a .pdf: {input_path}", file=sys.stderr)
        sys.exit(1)

    doc = fitz.open(str(src))
    return src, doc, doc.page_count


def _extract_markdown(doc) -> str:
    """Extract all pages from an open fitz Document as Markdown text."""
    import fitz
    md_parts: list[str] = []

    meta_title = doc.metadata.get("title", "").strip()
    if meta_title:
        md_parts.append(f"# {meta_title}\n")

    for page_num, page in enumerate(doc, start=1):
        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
        page_lines: list[str] = []

        for block in blocks:
            if block["type"] != 0:
                continue
            for line in block["lines"]:
                spans = line["spans"]
                if not spans:
                    continue
                line_text = "".join(s["text"] for s in spans).strip()
                if not line_text:
                    continue

                max_size = max(s["size"] for s in spans)
                is_bold = any(s["flags"] & 16 for s in spans)

                if max_size >= 20:
                    page_lines.append(f"# {line_text}")
                elif max_size >= 16:
                    page_lines.append(f"## {line_text}")
                elif max_size >= 13:
                    page_lines.append(f"### {line_text}")
                elif is_bold and len(line_text) < 120:
                    page_lines.append(f"**{line_text}**")
                else:
                    page_lines.append(line_text)

        if page_lines:
            md_parts.append(_join_lines(page_lines))
            md_parts.append(f"\n---\n*Page {page_num}*\n")

    return "\n\n".join(md_parts)


def _join_lines(lines: list[str]) -> str:
    """Join lines, merging plain body lines into paragraphs."""
    result: list[str] = []
    para: list[str] = []

    def flush_para():
        if para:
            result.append(" ".join(para))
            para.clear()

    for line in lines:
        if line.startswith(("#", "**", "-", ">", "|")):
            flush_para()
            result.append(line)
        else:
            if para and (line[0].isupper() and para[-1].endswith(".")):
                flush_para()
            para.append(line)

    flush_para()
    return "\n\n".join(result)


def _clean_markdown(text: str) -> str:
    """Remove excessive blank lines and trailing whitespace."""
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    lines = [l.rstrip() for l in text.splitlines()]
    return "\n".join(lines)
