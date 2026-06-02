"""Optional GUI for ContextCrawler (customtkinter)."""

from __future__ import annotations

import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog
from typing import Callable

try:
    import customtkinter as ctk
except ImportError:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "customtkinter", "-q"], check=True)
    import customtkinter as ctk


# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------

ctk.set_appearance_mode("System")          # follows OS light/dark
ctk.set_default_color_theme("blue")


# ---------------------------------------------------------------------------
# Helper: redirect print() into a queue for the log panel
# ---------------------------------------------------------------------------

class _QueueWriter:
    """File-like object that puts lines into a queue."""
    def __init__(self, q: queue.Queue):
        self._q = q
        self._buf = ""

    def write(self, text: str):
        self._buf += text
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._q.put(line)
        if self._buf:
            self._q.put("\r" + self._buf)

    def flush(self):
        if self._buf.strip():
            self._q.put(self._buf)
            self._buf = ""


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("ContextCrawler")
        self.geometry("800x680")
        self.minsize(680, 580)
        self.resizable(True, True)

        self._log_q: queue.Queue = queue.Queue()
        self._running = False
        self._estimate_done = False   # True once estimate has run

        self._build_ui()
        self._poll_log()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        # ---- Title bar ----
        header = ctk.CTkFrame(self, corner_radius=0, height=52)
        header.pack(fill="x", side="top")
        ctk.CTkLabel(
            header,
            text="  ContextCrawler",
            font=ctk.CTkFont(size=20, weight="bold"),
            anchor="w",
        ).pack(side="left", padx=16, pady=10)

        # ---- Tab view ----
        self._tabs = ctk.CTkTabview(self, corner_radius=8)
        self._tabs.pack(fill="both", expand=False, padx=14, pady=(8, 0))

        self._tabs.add("Crawl to PDF")
        self._tabs.add("Crawl to Markdown")
        self._tabs.add("Convert PDF → Markdown")

        self._build_crawl_tab(self._tabs.tab("Crawl to PDF"))
        self._build_md_crawl_tab(self._tabs.tab("Crawl to Markdown"))
        self._build_convert_tab(self._tabs.tab("Convert PDF → Markdown"))

        # ---- Log panel ----
        log_frame = ctk.CTkFrame(self, corner_radius=8)
        log_frame.pack(fill="both", expand=True, padx=14, pady=(6, 10))

        ctk.CTkLabel(log_frame, text="Output", anchor="w",
                     font=ctk.CTkFont(size=12, weight="bold")).pack(
            anchor="w", padx=10, pady=(6, 0))

        self._log_box = ctk.CTkTextbox(
            log_frame,
            font=ctk.CTkFont(family="Courier New", size=11),
            state="disabled",
            wrap="word",
        )
        self._log_box.pack(fill="both", expand=True, padx=8, pady=(2, 8))

    # ---- Crawl tab ----

    def _build_crawl_tab(self, parent):
        parent.columnconfigure(1, weight=1)

        row = 0

        # ── Step 1: URL + Estimate ────────────────────────────────────
        step1 = ctk.CTkFrame(parent, corner_radius=6)
        step1.grid(row=row, column=0, columnspan=2, padx=4, pady=(6, 4), sticky="ew")
        step1.columnconfigure(1, weight=1)
        row += 1

        ctk.CTkLabel(step1, text="Step 1 — Enter URL and estimate site size",
                     font=ctk.CTkFont(weight="bold"), anchor="w").grid(
            row=0, column=0, columnspan=3, padx=10, pady=(8, 4), sticky="w")

        ctk.CTkLabel(step1, text="Starting URL:", anchor="w").grid(
            row=1, column=0, padx=(10, 4), pady=6, sticky="w")
        self._url_var = tk.StringVar()
        self._url_var.trace_add("write", self._on_url_changed)
        ctk.CTkEntry(step1, textvariable=self._url_var,
                     placeholder_text="https://example.com").grid(
            row=1, column=1, padx=4, pady=6, sticky="ew")

        self._estimate_btn = ctk.CTkButton(
            step1, text="Estimate site size", width=160,
            command=self._run_estimate,
        )
        self._estimate_btn.grid(row=1, column=2, padx=(4, 10), pady=6)

        # Estimate result label
        self._estimate_label = ctk.CTkLabel(
            step1, text="", anchor="w",
            font=ctk.CTkFont(size=12),
            text_color=("gray40", "gray70"),
        )
        self._estimate_label.grid(row=2, column=0, columnspan=3,
                                   padx=10, pady=(0, 8), sticky="w")

        # ── Step 2: Depth + options (locked until estimate done) ──────
        self._step2_frame = ctk.CTkFrame(parent, corner_radius=6)
        self._step2_frame.grid(row=row, column=0, columnspan=2, padx=4, pady=4, sticky="ew")
        self._step2_frame.columnconfigure(1, weight=1)
        row += 1

        ctk.CTkLabel(self._step2_frame,
                     text="Step 2 — Choose crawl depth and options",
                     font=ctk.CTkFont(weight="bold"), anchor="w").grid(
            row=0, column=0, columnspan=2, padx=10, pady=(8, 4), sticky="w")

        # Depth
        ctk.CTkLabel(self._step2_frame, text="Max depth:", anchor="w").grid(
            row=1, column=0, padx=(10, 4), pady=6, sticky="w")
        depth_frame = ctk.CTkFrame(self._step2_frame, fg_color="transparent")
        depth_frame.grid(row=1, column=1, padx=4, pady=6, sticky="w")

        self._depth_var = tk.StringVar(value="2")
        self._depth_menu = ctk.CTkOptionMenu(
            depth_frame,
            values=["0", "1", "2", "3", "4", "5", "Unlimited"],
            variable=self._depth_var,
            width=120,
            state="disabled",
        )
        self._depth_menu.pack(side="left")

        self._images_var = tk.BooleanVar(value=False)
        self._images_cb = ctk.CTkCheckBox(
            depth_frame, text="Include image captions / alt text",
            variable=self._images_var, state="disabled",
        )
        self._images_cb.pack(side="left", padx=16)

        # Delay
        ctk.CTkLabel(self._step2_frame, text="Request delay (s):", anchor="w").grid(
            row=2, column=0, padx=(10, 4), pady=6, sticky="w")
        self._delay_var = tk.StringVar(value="0.5")
        self._delay_entry = ctk.CTkEntry(
            self._step2_frame, textvariable=self._delay_var,
            width=80, state="disabled",
        )
        self._delay_entry.grid(row=2, column=1, padx=4, pady=6, sticky="w")

        # Output path
        ctk.CTkLabel(self._step2_frame, text="Output PDF:", anchor="w").grid(
            row=3, column=0, padx=(10, 4), pady=6, sticky="w")
        out_frame = ctk.CTkFrame(self._step2_frame, fg_color="transparent")
        out_frame.grid(row=3, column=1, padx=4, pady=6, sticky="ew")
        out_frame.columnconfigure(0, weight=1)
        self._crawl_output_var = tk.StringVar()
        self._crawl_output_entry = ctk.CTkEntry(
            out_frame, textvariable=self._crawl_output_var,
            placeholder_text="(auto-generated from URL)", state="disabled",
        )
        self._crawl_output_entry.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self._browse_pdf_btn = ctk.CTkButton(
            out_frame, text="Browse…", width=80,
            command=self._browse_pdf_save, state="disabled",
        )
        self._browse_pdf_btn.grid(row=0, column=1)

        # ── Step 3: Start crawl ───────────────────────────────────────
        self._crawl_btn = ctk.CTkButton(
            parent, text="▶  Start Crawl", width=200,
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._start_crawl,
            state="disabled",
        )
        self._crawl_btn.grid(row=row, column=0, columnspan=2, pady=12)

    # ---- Convert tab ----

    # ---- Crawl to Markdown tab ----

    def _build_md_crawl_tab(self, parent):
        parent.columnconfigure(1, weight=1)
        row = 0

        # ── Step 1: URL + Estimate ────────────────────────────────────
        step1 = ctk.CTkFrame(parent, corner_radius=6)
        step1.grid(row=row, column=0, columnspan=2, padx=4, pady=(6, 4), sticky="ew")
        step1.columnconfigure(1, weight=1)
        row += 1

        ctk.CTkLabel(step1, text="Step 1 — Enter URL and estimate site size",
                     font=ctk.CTkFont(weight="bold"), anchor="w").grid(
            row=0, column=0, columnspan=3, padx=10, pady=(8, 4), sticky="w")

        ctk.CTkLabel(step1, text="Starting URL:", anchor="w").grid(
            row=1, column=0, padx=(10, 4), pady=6, sticky="w")
        self._md_url_var = tk.StringVar()
        self._md_url_var.trace_add("write", self._on_md_url_changed)
        ctk.CTkEntry(step1, textvariable=self._md_url_var,
                     placeholder_text="https://example.com").grid(
            row=1, column=1, padx=4, pady=6, sticky="ew")

        self._md_estimate_btn = ctk.CTkButton(
            step1, text="Estimate site size", width=160,
            command=self._run_md_estimate,
        )
        self._md_estimate_btn.grid(row=1, column=2, padx=(4, 10), pady=6)

        self._md_estimate_label = ctk.CTkLabel(
            step1, text="", anchor="w",
            font=ctk.CTkFont(size=12),
            text_color=("gray40", "gray70"),
        )
        self._md_estimate_label.grid(row=2, column=0, columnspan=3,
                                      padx=10, pady=(0, 8), sticky="w")

        # ── Step 2: Depth + output dir ────────────────────────────────
        self._md_step2 = ctk.CTkFrame(parent, corner_radius=6)
        self._md_step2.grid(row=row, column=0, columnspan=2, padx=4, pady=4, sticky="ew")
        self._md_step2.columnconfigure(1, weight=1)
        row += 1

        ctk.CTkLabel(self._md_step2, text="Step 2 — Choose depth and output",
                     font=ctk.CTkFont(weight="bold"), anchor="w").grid(
            row=0, column=0, columnspan=2, padx=10, pady=(8, 4), sticky="w")

        ctk.CTkLabel(self._md_step2, text="Max depth:", anchor="w").grid(
            row=1, column=0, padx=(10, 4), pady=6, sticky="w")
        self._md_depth_var = tk.StringVar(value="2")
        self._md_depth_menu = ctk.CTkOptionMenu(
            self._md_step2,
            values=["0", "1", "2", "3", "4", "5", "Unlimited"],
            variable=self._md_depth_var,
            width=120,
            state="disabled",
        )
        self._md_depth_menu.grid(row=1, column=1, padx=4, pady=6, sticky="w")

        # Output mode toggle
        ctk.CTkLabel(self._md_step2, text="Output mode:", anchor="w").grid(
            row=2, column=0, padx=(10, 4), pady=6, sticky="w")
        mode_frame = ctk.CTkFrame(self._md_step2, fg_color="transparent")
        mode_frame.grid(row=2, column=1, padx=4, pady=6, sticky="w")
        self._md_split_var = tk.BooleanVar(value=True)   # default: multiple files
        self._md_split_var.trace_add("write", self._on_md_split_changed)
        ctk.CTkRadioButton(mode_frame, text="Single .md file",
                           variable=self._md_split_var, value=False,
                           state="disabled").pack(side="left")
        ctk.CTkRadioButton(mode_frame, text="Multiple files by topic",
                           variable=self._md_split_var, value=True,
                           state="disabled").pack(side="left", padx=16)
        # Keep references so we can enable/disable them
        self._md_mode_frame = mode_frame

        # Dynamic output label + field (switches between file and folder)
        self._md_output_label = ctk.CTkLabel(self._md_step2, text="Output folder:", anchor="w")
        self._md_output_label.grid(row=3, column=0, padx=(10, 4), pady=6, sticky="w")
        out_frame = ctk.CTkFrame(self._md_step2, fg_color="transparent")
        out_frame.grid(row=3, column=1, padx=4, pady=6, sticky="ew")
        out_frame.columnconfigure(0, weight=1)
        self._md_outdir_var = tk.StringVar()
        self._md_outdir_entry = ctk.CTkEntry(
            out_frame, textvariable=self._md_outdir_var,
            placeholder_text="(auto-generated from URL)", state="disabled",
        )
        self._md_outdir_entry.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self._md_browse_btn = ctk.CTkButton(
            out_frame, text="Browse…", width=80,
            command=self._browse_md_outdir, state="disabled",
        )
        self._md_browse_btn.grid(row=0, column=1)

        # ── Step 3: Start ─────────────────────────────────────────────
        self._md_crawl_btn = ctk.CTkButton(
            parent, text="▶  Crawl to Markdown", width=200,
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._start_md_crawl,
            state="disabled",
        )
        self._md_crawl_btn.grid(row=row, column=0, columnspan=2, pady=12)

    def _on_md_url_changed(self, *_):
        url = self._md_url_var.get().strip()
        if not url:
            self._md_outdir_var.set("")
        else:
            self._update_md_output_suggestion()
        # Reset estimate label and button if the URL changes after an estimate
        self._md_estimate_label.configure(text="", text_color=("gray40", "gray70"))
        self._md_estimate_btn.configure(text="Estimate site size")

    def _browse_md_outdir(self):
        from tkinter import filedialog
        path = filedialog.askdirectory(title="Select output folder")
        if path:
            self._md_outdir_var.set(path)

    def _run_md_estimate(self):
        url = self._md_url_var.get().strip()
        if not url:
            self._log("⚠  Please enter a starting URL.")
            return
        if not url.startswith("http"):
            url = "https://" + url
            self._md_url_var.set(url)

        self._md_estimate_label.configure(text="Scanning…", text_color=("gray40", "gray70"))
        self._set_md_step2_state("disabled")

        def _run():
            from .crawler import estimate_link_count
            from .utils import normalise_url
            count = estimate_link_count(normalise_url(url), max_depth=2)
            self._last_md_estimate = count

        def _after():
            count = getattr(self, "_last_md_estimate", 0)
            self._md_estimate_label.configure(
                text=f"✓  ~{count} pages found — choose depth below, then click Start Crawl",
                text_color=("#1a7a3f", "#4caf75"),   # green in light/dark mode
            )
            self._md_estimate_btn.configure(text="Re-estimate")
            self._set_md_step2_state("normal")

        self._run_in_thread(_run, self._md_estimate_btn, "Estimate site size",
                            clear_log=True, on_done=_after)

    def _on_md_split_changed(self, *_):
        """Switch the output field label and browse dialog between file and folder."""
        if self._md_split_var.get():
            self._md_output_label.configure(text="Output folder:")
            self._md_browse_btn.configure(command=self._browse_md_outdir)
        else:
            self._md_output_label.configure(text="Output file:")
            self._md_browse_btn.configure(command=self._browse_md_file_save)
        self._md_outdir_var.set("")   # clear stale suggestion when mode changes
        self._update_md_output_suggestion()

    def _update_md_output_suggestion(self):
        """Re-suggest output path based on current URL and split mode."""
        from .utils import url_to_filename, normalise_url
        url = self._md_url_var.get().strip()
        if not url:
            return
        if not url.startswith("http"):
            url = "https://" + url
        try:
            stem = url_to_filename(normalise_url(url))
            suggested = stem + ("_md" if self._md_split_var.get() else ".md")
        except Exception:
            return
        self._md_outdir_var.set(suggested)

    def _browse_md_file_save(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".md",
            filetypes=[("Markdown files", "*.md"), ("All files", "*.*")],
            title="Save Markdown as…",
        )
        if path:
            self._md_outdir_var.set(path)

    def _set_md_step2_state(self, state: str):
        self._md_depth_menu.configure(state=state)
        for widget in self._md_mode_frame.winfo_children():
            widget.configure(state=state)
        self._md_outdir_entry.configure(state=state)
        self._md_browse_btn.configure(state=state)
        self._md_crawl_btn.configure(state=state)
        if state == "normal":
            self._update_md_output_suggestion()

    def _start_md_crawl(self):
        url = self._md_url_var.get().strip()
        if not url.startswith("http"):
            url = "https://" + url

        depth_str = self._md_depth_var.get()
        depth_arg = None if depth_str == "Unlimited" else int(depth_str)
        output_path = self._md_outdir_var.get().strip() or None
        split = self._md_split_var.get()

        def _run():
            from .crawler import crawl
            from .utils import normalise_url, url_to_filename

            start_url = normalise_url(url)

            print(f"Crawling {start_url} …")
            pages = crawl(start_url, max_depth=depth_arg, delay=0.5)
            if not pages:
                print("No pages could be crawled.")
                return
            print(f"  Done — {len(pages)} page(s) crawled.")

            if split:
                from .md_writer import write_markdown_dir
                out_dir = output_path or (url_to_filename(start_url) + "_md")
                print(f"\nWriting Markdown files → {out_dir}/")
                write_markdown_dir(pages, start_url=start_url, output_dir=out_dir)
            else:
                from .md_writer import write_single_markdown
                out_file = output_path or (url_to_filename(start_url) + ".md")
                print(f"\nWriting Markdown → {out_file}")
                write_single_markdown(pages, start_url=start_url, output_path=out_file)
            print("✓  Complete.")

        self._run_in_thread(_run, self._md_crawl_btn, "▶  Crawl to Markdown")

    def _build_convert_tab(self, parent):
        parent.columnconfigure(1, weight=1)

        row = 0

        ctk.CTkLabel(parent, text="Input PDF:", anchor="w").grid(
            row=row, column=0, padx=(8, 4), pady=6, sticky="w")
        in_frame = ctk.CTkFrame(parent, fg_color="transparent")
        in_frame.grid(row=row, column=1, padx=4, pady=6, sticky="ew")
        in_frame.columnconfigure(0, weight=1)
        self._pdf_input_var = tk.StringVar()
        self._pdf_input_var.trace_add("write", self._on_pdf_input_changed)
        ctk.CTkEntry(in_frame, textvariable=self._pdf_input_var,
                     placeholder_text="Select a PDF file…").grid(
            row=0, column=0, sticky="ew", padx=(0, 4))
        ctk.CTkButton(in_frame, text="Browse…", width=80,
                      command=self._browse_pdf_open).grid(row=0, column=1)
        row += 1

        ctk.CTkLabel(parent, text="Output Markdown:", anchor="w").grid(
            row=row, column=0, padx=(8, 4), pady=6, sticky="w")
        out_frame = ctk.CTkFrame(parent, fg_color="transparent")
        out_frame.grid(row=row, column=1, padx=4, pady=6, sticky="ew")
        out_frame.columnconfigure(0, weight=1)
        self._md_output_var = tk.StringVar()
        ctk.CTkEntry(out_frame, textvariable=self._md_output_var,
                     placeholder_text="(same folder as PDF, .md extension)").grid(
            row=0, column=0, sticky="ew", padx=(0, 4))
        ctk.CTkButton(out_frame, text="Browse…", width=80,
                      command=self._browse_md_save).grid(row=0, column=1)
        row += 1

        # Output mode — single file or split by topic
        ctk.CTkLabel(parent, text="Output mode:", anchor="w").grid(
            row=row, column=0, padx=(8, 4), pady=6, sticky="w")
        mode_frame = ctk.CTkFrame(parent, fg_color="transparent")
        mode_frame.grid(row=row, column=1, padx=4, pady=6, sticky="w")
        self._split_var = tk.BooleanVar(value=False)
        self._split_var.trace_add("write", self._on_split_changed)
        ctk.CTkRadioButton(mode_frame, text="Single .md file",
                           variable=self._split_var, value=False).pack(side="left")
        ctk.CTkRadioButton(mode_frame, text="Multiple files by topic",
                           variable=self._split_var, value=True).pack(side="left", padx=16)
        row += 1

        # Split output directory (visible only when split mode is on)
        self._split_dir_label = ctk.CTkLabel(parent, text="Output folder:", anchor="w")
        self._split_dir_label.grid(row=row, column=0, padx=(8, 4), pady=6, sticky="w")
        split_frame = ctk.CTkFrame(parent, fg_color="transparent")
        split_frame.grid(row=row, column=1, padx=4, pady=6, sticky="ew")
        split_frame.columnconfigure(0, weight=1)
        self._split_dir_var = tk.StringVar()
        self._split_dir_entry = ctk.CTkEntry(
            split_frame, textvariable=self._split_dir_var,
            placeholder_text="(auto-named from PDF)")
        self._split_dir_entry.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self._split_browse_btn = ctk.CTkButton(
            split_frame, text="Browse…", width=80,
            command=self._browse_split_dir)
        self._split_browse_btn.grid(row=0, column=1)
        # Hide split dir row initially
        self._split_dir_label.grid_remove()
        split_frame.grid_remove()
        self._split_dir_frame = split_frame
        row += 1

        ctk.CTkLabel(parent, text="Options:", anchor="w").grid(
            row=row, column=0, padx=(8, 4), pady=6, sticky="w")
        self._clean_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            parent,
            text="Clean for LLM use  (removes TOC noise, page numbers, boilerplate)",
            variable=self._clean_var,
        ).grid(row=row, column=1, padx=4, pady=6, sticky="w")
        row += 1

        self._convert_btn = ctk.CTkButton(
            parent, text="▶  Convert to Markdown", width=200,
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._start_convert,
        )
        self._convert_btn.grid(row=row, column=0, columnspan=2, pady=14)

    def _on_split_changed(self, *_):
        if self._split_var.get():
            self._split_dir_label.grid()
            self._split_dir_frame.grid()
            # Hide the single-file output row label/entry
            self._md_output_var.set("")
        else:
            self._split_dir_label.grid_remove()
            self._split_dir_frame.grid_remove()

    def _browse_split_dir(self):
        path = filedialog.askdirectory(title="Select output folder")
        if path:
            self._split_dir_var.set(path)

    # ------------------------------------------------------------------
    # File dialogs
    # ------------------------------------------------------------------

    def _browse_pdf_save(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
            title="Save PDF as…",
        )
        if path:
            self._crawl_output_var.set(path)

    def _browse_pdf_open(self):
        path = filedialog.askopenfilename(
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
            title="Select PDF to convert",
        )
        if path:
            self._pdf_input_var.set(path)

    def _browse_md_save(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".md",
            filetypes=[("Markdown files", "*.md"), ("All files", "*.*")],
            title="Save Markdown as…",
        )
        if path:
            self._md_output_var.set(path)

    # ------------------------------------------------------------------
    # Log panel
    # ------------------------------------------------------------------

    def _log(self, text: str):
        self._log_box.configure(state="normal")
        if text.startswith("\r"):
            self._log_box.delete("end-2l", "end-1l")
            self._log_box.insert("end", text.lstrip("\r") + "\n")
        else:
            self._log_box.insert("end", text + "\n")
        self._log_box.see("end")
        self._log_box.configure(state="disabled")

    def _poll_log(self):
        try:
            while True:
                line = self._log_q.get_nowait()
                self._log(line)
        except queue.Empty:
            pass
        self.after(100, self._poll_log)

    # ------------------------------------------------------------------
    # Background task runner
    # ------------------------------------------------------------------

    def _run_in_thread(
        self,
        fn: Callable,
        btn: ctk.CTkButton,
        btn_label: str,
        clear_log: bool = True,
        on_done: Callable | None = None,
    ):
        if self._running:
            self._log("⚠  Another task is already running.")
            return
        self._running = True
        btn.configure(state="disabled", text="Running…")
        if clear_log:
            self._log_box.configure(state="normal")
            self._log_box.delete("1.0", "end")
            self._log_box.configure(state="disabled")

        old_stdout, old_stderr = sys.stdout, sys.stderr
        writer = _QueueWriter(self._log_q)
        sys.stdout = writer
        sys.stderr = writer

        def _target():
            try:
                fn()
            except SystemExit:
                pass
            except Exception as exc:
                self._log_q.put(f"ERROR: {exc}")
            finally:
                sys.stdout = old_stdout
                sys.stderr = old_stderr
                self._running = False
                self.after(0, lambda: btn.configure(state="normal", text=btn_label))
                if on_done:
                    self.after(0, on_done)

        threading.Thread(target=_target, daemon=True).start()

    # ------------------------------------------------------------------
    # URL change → update default output filename
    # ------------------------------------------------------------------

    def _on_url_changed(self, *_):
        from .utils import url_to_filename, normalise_url
        url = self._url_var.get().strip()
        if not url:
            self._crawl_output_var.set("")
            return
        if not url.startswith("http"):
            url = "https://" + url
        try:
            suggested = url_to_filename(normalise_url(url)) + ".pdf"
        except Exception:
            suggested = ""
        # Only overwrite if the user hasn't typed a custom path
        current = self._crawl_output_var.get()
        if not current or current.endswith(".pdf") and "/" not in current and "\\" not in current:
            self._crawl_output_var.set(suggested)
        # Reset estimate label and button if the URL changes after an estimate
        self._estimate_label.configure(text="", text_color=("gray40", "gray70"))
        self._estimate_btn.configure(text="Estimate site size")

    def _on_pdf_input_changed(self, *_):
        from pathlib import Path
        pdf_path = self._pdf_input_var.get().strip()
        if not pdf_path:
            self._md_output_var.set("")
            self._split_dir_var.set("")
            return
        try:
            p = Path(pdf_path)
            suggested_md = str(p.with_suffix(".md"))
            suggested_dir = str(p.parent / p.stem)  # e.g. my_doc/ next to my_doc.pdf
        except Exception:
            return
        # Single-file output suggestion
        current_md = self._md_output_var.get()
        if not current_md or (current_md.endswith(".md") and current_md == str(Path(current_md))):
            self._md_output_var.set(suggested_md)
        # Split-dir suggestion
        current_dir = self._split_dir_var.get()
        if not current_dir or current_dir == str(Path(current_dir)):
            self._split_dir_var.set(suggested_dir)

    # ------------------------------------------------------------------
    # Step 1: Run estimate
    # ------------------------------------------------------------------

    def _run_estimate(self):
        url = self._url_var.get().strip()
        if not url:
            self._log("⚠  Please enter a starting URL.")
            return
        if not url.startswith("http"):
            url = "https://" + url
            self._url_var.set(url)

        # Reset state
        self._estimate_done = False
        self._estimate_label.configure(text="Scanning…", text_color=("gray40", "gray70"))
        self._set_step2_state("disabled")

        def _run():
            from .crawler import estimate_link_count
            from .utils import normalise_url
            start_url = normalise_url(url)
            print(f"Scanning {start_url} …")
            count = estimate_link_count(start_url, max_depth=2)
            # Pass count back to UI thread via a captured variable
            self._last_estimate = count

        def _after():
            count = getattr(self, "_last_estimate", 0)
            self._estimate_label.configure(
                text=f"✓  ~{count} pages found — choose depth below, then click Start Crawl",
                text_color=("#1a7a3f", "#4caf75"),   # green in light/dark mode
            )
            self._estimate_btn.configure(text="Re-estimate")
            self._estimate_done = True
            self._set_step2_state("normal")

        self._run_in_thread(
            _run,
            self._estimate_btn,
            "Estimate site size",
            clear_log=True,
            on_done=_after,
        )

    def _set_step2_state(self, state: str):
        """Enable or disable all Step 2 controls."""
        self._depth_menu.configure(state=state)
        self._images_cb.configure(state=state)
        self._delay_entry.configure(state=state)
        self._crawl_output_entry.configure(state=state)
        self._browse_pdf_btn.configure(state=state)
        self._crawl_btn.configure(state=state)

    # ------------------------------------------------------------------
    # Step 3: Start crawl
    # ------------------------------------------------------------------

    def _start_crawl(self):
        url = self._url_var.get().strip()
        if not url.startswith("http"):
            url = "https://" + url

        depth_str = self._depth_var.get()
        depth_arg = None if depth_str == "Unlimited" else int(depth_str)

        try:
            delay = float(self._delay_var.get())
        except ValueError:
            delay = 0.5

        output = self._crawl_output_var.get().strip() or None
        images = self._images_var.get()

        def _run():
            from .crawler import crawl
            from .pdf_builder import build_pdf
            from .utils import get_domain, url_to_filename, normalise_url

            start_url = normalise_url(url)
            domain = get_domain(start_url)
            depth_label = "unlimited" if depth_arg is None else depth_arg
            print(f"ContextCrawler  |  domain: {domain}")
            print(f"Crawl depth: {depth_label}")
            print(f"\nCrawling {start_url} …")

            pages = crawl(start_url, max_depth=depth_arg,
                          delay=delay, include_images=images)
            if not pages:
                print("No pages could be crawled.")
                return

            print(f"  Done — {len(pages)} page(s) crawled.")
            out_path = output or (url_to_filename(start_url) + ".pdf")
            print(f"\nGenerating PDF: {out_path}")
            build_pdf(pages, output_path=out_path, start_url=start_url)
            print("✓  Complete.")

        self._run_in_thread(_run, self._crawl_btn, "▶  Start Crawl")

    # ------------------------------------------------------------------
    # Convert action
    # ------------------------------------------------------------------

    def _start_convert(self):
        pdf_path = self._pdf_input_var.get().strip()
        if not pdf_path:
            self._log("⚠  Please select a PDF file.")
            return

        clean = self._clean_var.get()
        split = self._split_var.get()

        if split:
            out_dir = self._split_dir_var.get().strip() or None

            def _run():
                from .pdf_converter import pdf_to_markdown_dir
                pdf_to_markdown_dir(pdf_path, output_dir=out_dir, clean=clean)
                print("✓  Complete.")
        else:
            md_path = self._md_output_var.get().strip() or None

            def _run():
                from .pdf_converter import pdf_to_markdown
                pdf_to_markdown(pdf_path, output_path=md_path, clean=clean)
                print("✓  Complete.")

        self._run_in_thread(_run, self._convert_btn, "▶  Convert to Markdown")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def launch():
    app = App()
    app.mainloop()
