"""Command-line interface for ContextCrawler."""

from __future__ import annotations

import argparse
import sys

from .crawler import crawl, estimate_link_count
from .pdf_builder import build_pdf
from .utils import get_domain, url_to_filename, normalise_url


def main(argv: list[str] | None = None) -> None:
    # No arguments → launch GUI
    if argv is None and len(sys.argv) == 1:
        from .gui import launch
        launch()
        return

    parser = argparse.ArgumentParser(
        prog="contextcrawler",
        description=(
            "Crawl a website and generate a book-like PDF,\n"
            "or convert an existing PDF to Markdown."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # ---- Mutually exclusive modes ----------------------------------------
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--gui",
        action="store_true",
        help="Launch the graphical interface (default when no arguments given)",
    )
    mode.add_argument(
        "--to-md",
        metavar="PDF_FILE",
        help="Convert an existing PDF to a Markdown (.md) file and exit",
    )
    mode.add_argument(
        "--md-dir",
        metavar="OUTPUT_DIR",
        nargs="?",
        const="",          # flag present but no value → auto-generate dir name
        help="Crawl a URL and write topic-grouped Markdown files directly "
             "(no PDF). Each topic section becomes its own .md file inside "
             "OUTPUT_DIR (auto-generated from URL if omitted). "
             "Faster and cleaner than crawl-to-PDF-to-Markdown for LLM use.",
    )

    # ---- Crawl arguments (used when not in --to-md mode) -----------------
    parser.add_argument(
        "url",
        nargs="?",
        help="Starting URL to crawl (required unless --to-md is used)",
    )
    parser.add_argument(
        "-o", "--output",
        default=None,
        help="Output file path (PDF when crawling; .md when using --to-md)",
    )
    parser.add_argument(
        "-d", "--depth",
        type=int,
        default=None,
        metavar="N",
        help="Maximum crawl depth (default: ask interactively)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        metavar="SECONDS",
        help="Politeness delay between requests (default: 0.5s)",
    )
    parser.add_argument(
        "--images",
        action="store_true",
        help="Include image alt text and captions in PDF (default: text only; actual images are never embedded)",
    )
    parser.add_argument(
        "--no-estimate",
        action="store_true",
        help="Skip the shallow link-count estimate",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="When used with --to-md: strip TOC noise, page markers, boilerplate "
             "and reflow paragraphs for optimal LLM ingestion",
    )
    parser.add_argument(
        "--split",
        metavar="DIR",
        nargs="?",
        const="",          # flag present but no value -> auto-generate dir name
        help="When used with --to-md: split output into topic-grouped .md files "
             "in DIR (auto-named from the PDF if omitted) instead of a single file. "
             "Produces one .md per topic section plus an index.md.",
    )
    parser.add_argument(
        "--single",
        action="store_true",
        help="When used with --md-dir: write all pages to a single .md file "
             "instead of topic-grouped files. Output path set with -o.",
    )
    parser.add_argument(
        "--group-depth",
        type=int,
        default=1,
        metavar="N",
        help="URL path depth used for topic grouping with --md-dir "
             "(default: 1 — group by first path segment after the start URL)",
    )

    args = parser.parse_args(argv)

    # ------------------------------------------------------------------
    # Mode: GUI
    # ------------------------------------------------------------------
    if args.gui:
        from .gui import launch
        launch()
        return

    # ------------------------------------------------------------------
    # Mode: URL → topic-grouped Markdown files (direct, no PDF)
    # ------------------------------------------------------------------
    if args.md_dir is not None:
        if not args.url:
            parser.error("a URL is required with --md-dir")
        start_url = normalise_url(args.url)
        if not start_url.startswith("http"):
            print("Error: URL must start with http:// or https://", file=sys.stderr)
            sys.exit(1)

        # Auto-generate output directory name from URL if not specified
        output_dir = args.md_dir or (url_to_filename(start_url) + "_md")

        print(f"\nContextCrawler  |  mode: direct Markdown  |  domain: {get_domain(start_url)}")
        print("-" * 60)

        if not args.no_estimate:
            print("Estimating site size (shallow scan, depth 2)…")
            estimate_link_count(start_url, max_depth=2)
            print("  Scan complete.")

        if args.depth is not None:
            max_depth: int | None = args.depth
            print(f"Crawl depth: {max_depth}")
        else:
            print("\nHow deep should the crawler go?")
            print("  [0] Homepage only")
            print("  [1] Homepage + direct links")
            print("  [2] Two levels deep")
            print("  [3] Three levels deep")
            print("  [F] Full depth (unlimited — may be very large)")
            choice = input("Your choice [default=2]: ").strip().upper() or "2"
            if choice == "F":
                max_depth = None
            else:
                try:
                    max_depth = int(choice)
                except ValueError:
                    max_depth = 2
            print(f"Crawl depth: {'unlimited' if max_depth is None else max_depth}")

        print(f"\nCrawling {start_url} …")
        pages = crawl(start_url, max_depth=max_depth, delay=args.delay,
                      include_images=args.images)
        if not pages:
            print("No pages could be crawled. Exiting.", file=sys.stderr)
            sys.exit(1)
        print(f"  Done — {len(pages)} page(s) crawled.")

        if getattr(args, "single", False):
            # Single-file mode: --md-dir used with --single flag
            out_file = args.output or (url_to_filename(start_url) + ".md")
            print(f"\nWriting Markdown → {out_file}")
            from .md_writer import write_single_markdown
            write_single_markdown(pages, start_url=start_url, output_path=out_file)
        else:
            print(f"\nWriting Markdown files → {output_dir}/")
            from .md_writer import write_markdown_dir
            written = write_markdown_dir(pages, start_url=start_url, output_dir=output_dir)
            print(f"  {len(written)} section file(s) + index.md written.")
        print("Complete.")
        return

    # ------------------------------------------------------------------
    # Mode: PDF → Markdown conversion
    # ------------------------------------------------------------------
    if args.to_md:
        if args.split is not None:
            # Split into topic-grouped files in a directory
            from .pdf_converter import pdf_to_markdown_dir
            out_dir = args.split or args.output or None
            pdf_to_markdown_dir(args.to_md, output_dir=out_dir, clean=args.clean)
        else:
            from .pdf_converter import pdf_to_markdown
            pdf_to_markdown(args.to_md, output_path=args.output, clean=args.clean)
        return

    # ------------------------------------------------------------------
    # Mode: URL → PDF crawl
    # ------------------------------------------------------------------
    if not args.url:
        parser.error("a URL is required (or use --to-md PDF_FILE to convert a PDF)")

    start_url = normalise_url(args.url)
    if not start_url.startswith("http"):
        print("Error: URL must start with http:// or https://", file=sys.stderr)
        sys.exit(1)

    domain = get_domain(start_url)
    print(f"\nContextCrawler  |  domain: {domain}")
    print("-" * 50)

    # ------------------------------------------------------------------
    # Optional estimate pass
    # ------------------------------------------------------------------
    if not args.no_estimate:
        print("Estimating site size (shallow scan, depth 2)...")
        estimate_link_count(start_url, max_depth=2)
        print(f"  Scan complete.")

    # ------------------------------------------------------------------
    # Depth selection
    # ------------------------------------------------------------------
    if args.depth is not None:
        max_depth: int | None = args.depth
        print(f"Crawl depth: {max_depth}")
    else:
        print("\nHow deep should the crawler go?")
        print("  [0] Homepage only")
        print("  [1] Homepage + direct links")
        print("  [2] Two levels deep")
        print("  [3] Three levels deep")
        print("  [F] Full depth (unlimited — may be very large)")
        choice = input("Your choice [default=2]: ").strip().upper() or "2"
        if choice == "F":
            max_depth = None
            print("Crawling at unlimited depth.")
        else:
            try:
                max_depth = int(choice)
            except ValueError:
                max_depth = 2
        print(f"Crawl depth: {'unlimited' if max_depth is None else max_depth}")

    # ------------------------------------------------------------------
    # Crawl
    # ------------------------------------------------------------------
    print(f"\nCrawling {start_url} ...")
    pages = crawl(
        start_url,
        max_depth=max_depth,
        delay=args.delay,
        include_images=args.images,
    )

    if not pages:
        print("No pages could be crawled. Exiting.", file=sys.stderr)
        sys.exit(1)

    print(f"  Done — {len(pages)} page(s) crawled.")

    # ------------------------------------------------------------------
    # PDF generation
    # ------------------------------------------------------------------
    output_path = args.output or (url_to_filename(start_url) + ".pdf")
    print(f"\nGenerating PDF: {output_path}")
    build_pdf(pages, output_path=output_path, start_url=start_url)
    print("Complete.")


if __name__ == "__main__":
    main()
