"""Convert an existing PDF file to plain Markdown."""

from __future__ import annotations

import re
import sys
from pathlib import Path


def pdf_to_markdown(
    input_path: str,
    output_path: str | None = None,
    clean: bool = False,
) -> str:
    """Read *input_path* PDF and write Markdown to *output_path*.

    If *clean* is True, run an LLM-optimisation pass before writing
    (strips TOC noise, dot leaders, page markers, boilerplate, etc.).

    Returns the output file path used.
    """
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

    dest = Path(output_path) if output_path else src.with_suffix(".md")

    print(f"Converting: {src}")
    print(f"       To:  {dest}")

    doc = fitz.open(str(src))
    md_parts: list[str] = []

    # Document title from metadata (if available)
    meta_title = doc.metadata.get("title", "").strip()
    if meta_title:
        md_parts.append(f"# {meta_title}\n")

    for page_num, page in enumerate(doc, start=1):
        # Extract text with layout preservation using dict mode
        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]

        page_lines: list[str] = []

        for block in blocks:
            if block["type"] != 0:  # 0 = text block; skip images
                continue

            for line in block["lines"]:
                spans = line["spans"]
                if not spans:
                    continue

                line_text = "".join(s["text"] for s in spans).strip()
                if not line_text:
                    continue

                # Heuristic heading detection based on font size
                # Use the dominant span size in the line
                max_size = max(s["size"] for s in spans)
                is_bold = any(s["flags"] & 16 for s in spans)  # bit 4 = bold

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
            page_md = _join_lines(page_lines)
            md_parts.append(page_md)
            # Page separator (optional — helps readability for long docs)
            md_parts.append(f"\n---\n*Page {page_num}*\n")

    page_count = doc.page_count
    doc.close()

    markdown = "\n\n".join(md_parts)
    markdown = _clean_markdown(markdown)

    if clean:
        from .pdf_cleaner import clean_for_llm
        print("Cleaning for LLM use...")
        markdown = clean_for_llm(markdown)

    dest.write_text(markdown, encoding="utf-8")
    print(f"Done — {page_count} page(s) converted.")
    return str(dest)


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
            # Possible paragraph continuation
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
