# url-to-pdf

A Python tool that crawls a website and converts its content into a clean, book-like PDF — and then optionally converts that PDF into Markdown optimised for use as context in large language models (LLMs).

---

## Why this exists

LLMs like Claude, GPT-4, and others are most useful when they have access to relevant, well-structured context. However, website content is often spread across dozens or hundreds of pages, full of navigation menus, ads, cookie banners, and other noise that wastes context window space and reduces quality.

**url-to-pdf** solves this by:

1. Crawling an entire website (or a portion of it) starting from a URL you provide
2. Extracting only the meaningful body text from each page
3. Structuring everything into a single, book-like PDF — one chapter per page, with a table of contents
4. Optionally converting that PDF to clean Markdown, stripped of all layout artefacts, ready to paste directly into an LLM prompt or upload as a file

Typical use cases include:
- Converting product documentation into a single context file for an AI assistant
- Capturing a help site or knowledge base for offline use or AI ingestion
- Archiving web content in a structured, readable format

---

## Requirements

- Python 3.10 or later
- Install dependencies:

```bash
py -m pip install -r requirements.txt
```

On first run, Playwright's Chromium browser will be downloaded automatically (~300 MB, one-time).

---

## Usage

### GUI (recommended)

Launch with no arguments to open the graphical interface:

```bash
py url-to-pdf.py
```

Or explicitly:

```bash
py url-to-pdf.py --gui
```

The GUI guides you through three steps:

1. **Enter a URL** and click **Estimate site size** — performs a shallow scan and tells you roughly how many pages are reachable
2. **Choose your crawl depth** based on the estimate, set options, and confirm the output path
3. Click **Start Crawl** — progress is shown live in the output panel

A second tab lets you convert any existing PDF to Markdown, with an optional LLM-cleaning pass.

---

### Command line

**Crawl a website to PDF:**

```bash
py url-to-pdf.py https://example.com
```

```bash
# Specify depth and output file
py url-to-pdf.py https://docs.example.com -d 2 -o docs.pdf

# Skip the site-size estimate, unlimited depth, slower crawl
py url-to-pdf.py https://example.com --no-estimate -d 999 --delay 1.0
```

**Convert an existing PDF to Markdown:**

```bash
py url-to-pdf.py --to-md my_document.pdf
```

**Convert and clean for LLM use:**

```bash
py url-to-pdf.py --to-md my_document.pdf --clean
```

---

## Options

| Flag | Default | Description |
|---|---|---|
| `url` | — | Starting URL to crawl |
| `-o`, `--output` | auto-generated | Output file path |
| `-d`, `--depth N` | interactive | Maximum crawl depth (0 = homepage only) |
| `--delay SECONDS` | `0.5` | Politeness delay between requests |
| `--images` | off | Include image alt text and captions in PDF |
| `--no-estimate` | off | Skip the shallow site-size scan |
| `--to-md PDF_FILE` | — | Convert an existing PDF to Markdown instead of crawling |
| `--clean` | off | Strip layout noise from converted Markdown (use with `--to-md`) |
| `--gui` | — | Launch the graphical interface |

---

## How it works

### Crawling
- Uses **Playwright** (headless Chromium) to render each page, including JavaScript-heavy sites
- Collects content from all page frames, including inline `srcdoc` iframes used by some help-centre platforms
- Stays within the original domain; filters known ad networks and tracker domains
- Deduplicates pages so each URL appears only once regardless of how many links point to it
- Shows live progress: depth, pages found, queue size

### Content extraction
- **trafilatura** identifies and extracts the main body text, discarding navigation, headers, footers, and sidebars
- Google Translate widget text and language-selector dropdowns are filtered out at extraction time
- Link text is captured as human-readable anchor text, not raw URLs

### PDF generation
- **reportlab** builds the PDF with a cover page, auto-generated table of contents, one chapter per crawled page, and running headers and page numbers

### Markdown conversion (`--to-md`)
- **PyMuPDF** extracts text from the PDF, using font size and bold flags to detect headings
- The `--clean` pass removes: TOC dot leaders, page-number markers, running headers/footers, boilerplate lines, URL clusters, language-selector blocks, Google Translate phrases, empty chapters, and duplicate headings — leaving clean, continuous prose ready for LLM ingestion

---

## Project structure

```
url-to-pdf.py          Entry point
url_to_pdf/
  cli.py               Argument parsing and mode dispatch
  crawler.py           BFS crawler with progress display
  extractor.py         Playwright fetch + trafilatura extraction
  pdf_builder.py       reportlab PDF generation
  pdf_converter.py     PyMuPDF PDF → Markdown conversion
  pdf_cleaner.py       LLM-optimised Markdown cleaning pass
  utils.py             URL normalisation, domain checks, ad filtering
  gui.py               customtkinter graphical interface
```

---

## Dependencies

| Package | Purpose |
|---|---|
| `playwright` | Headless browser for JS-rendered pages |
| `beautifulsoup4` | HTML parsing for link extraction |
| `trafilatura` | Main-body text extraction |
| `reportlab` | PDF generation |
| `pymupdf` | PDF text extraction (for `--to-md`) |
| `customtkinter` | GUI framework |
| `lxml` | HTML parser backend |

---

## Limitations

- **JavaScript-gated content** — pages that require login or interaction beyond initial load may not render fully
- **Rate limiting** — some sites block automated crawlers; increase `--delay` if you encounter errors
- **Very large sites** — use `-d 1` or `-d 2` for large sites; unlimited depth can produce enormous PDFs
- **Images** — actual images are never embedded in the PDF; only alt text and captions are optionally included
