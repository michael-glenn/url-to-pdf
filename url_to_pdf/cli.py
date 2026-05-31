"""Command-line interface for url-to-pdf."""

from __future__ import annotations

import argparse
import sys

from .crawler import crawl, estimate_link_count
from .pdf_builder import build_pdf
from .utils import get_domain, url_to_filename, normalise_url


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="url-to-pdf",
        description=(
            "Crawl a website and generate a book-like PDF,\n"
            "or convert an existing PDF to Markdown."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # ---- Mutually exclusive modes ----------------------------------------
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--to-md",
        metavar="PDF_FILE",
        help="Convert an existing PDF to a Markdown (.md) file and exit",
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
        help="Include image references in PDF (default: text only)",
    )
    parser.add_argument(
        "--no-estimate",
        action="store_true",
        help="Skip the shallow link-count estimate",
    )

    args = parser.parse_args(argv)

    # ------------------------------------------------------------------
    # Mode: PDF → Markdown conversion
    # ------------------------------------------------------------------
    if args.to_md:
        from .pdf_converter import pdf_to_markdown
        pdf_to_markdown(args.to_md, output_path=args.output)
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
    print(f"\nurl-to-pdf  |  domain: {domain}")
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
