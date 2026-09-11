#!/usr/bin/env python3
"""Build the Omarchy hotkeys cheat sheet PDF from the official manual.

The script reads https://omarchy.org/manual/hotkeys/, extracts every hotkey table and
renders a two-page A4 cheat sheet. The script holds no shortcut content of its own, so
each run produces the current bindings.

The manual has more rows than a two-page sheet holds at full size. The script therefore
reduces the font scale in small steps until the content fits the target page count.

Prerequisites:
    pip install -r requirements.txt

Usage:
    python generate_cheatsheet.py                    # fetch the manual, write the PDF
    python generate_cheatsheet.py -o sheet.pdf       # write to a different path
    python generate_cheatsheet.py --source page.html # read a local file instead
    python generate_cheatsheet.py --pages 3          # allow three pages
    python generate_cheatsheet.py --dry-run          # report the result, write nothing
    python generate_cheatsheet.py --debug            # verbose logging
"""

import argparse
import logging
import sys
from datetime import date
from functools import cache
from html.parser import HTMLParser
from io import BytesIO
from types import SimpleNamespace
from xml.sax.saxutils import escape

import requests
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

log = logging.getLogger(__name__)

MANUAL_URL = "https://omarchy.org/manual/hotkeys/"
SOURCE_LABEL = MANUAL_URL.split("://", 1)[1].rstrip("/")
DEFAULT_OUTPUT = "omarchy-hotkeys.pdf"
TARGET_PAGES = 2
SUBTITLE_MIN_CHARS = 30
HTTP_TIMEOUT = 20

# The script tries these font scales in order and keeps the first one that fits.
FONT_SCALES = [1.0, 0.96, 0.92, 0.88, 0.84, 0.80, 0.76, 0.72, 0.68, 0.64, 0.60]

# A section with more rows than this limit can break across two columns.
# The build keeps a shorter section together in one column.
KEEP_TOGETHER_MAX_ROWS = 14

# Helvetica cannot show these characters, so the script replaces them.
REPLACEMENTS = {"‘": "'", "’": "'", "“": '"', "”": '"',
                "–": "-", "—": "--", " ": " "}


def clean(text: str) -> str:
    """Return text that Helvetica can show and reportlab can parse.

    The manual contains typographic quotes and emoji. Helvetica has no emoji, so the
    script removes every character outside the font encoding.
    """
    for bad, good in REPLACEMENTS.items():
        text = text.replace(bad, good)
    text = text.encode("cp1252", "ignore").decode("cp1252")
    return escape(" ".join(text.split()))


class ManualParser(HTMLParser):  # pylint: disable=abstract-method
    """Read the headings, the notes and the hotkey tables from the manual.

    The parser reads the article element only. The page navigation sits outside that
    element, so the parser ignores it.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.subtitle = ""
        self.blocks: list[dict] = []
        self._article = False
        self._block: dict | None = None
        self._buf: list[str] | None = None
        self._cells: list[str] | None = None
        self._in_body = False

    def _flush(self) -> None:
        # The Tmux section puts its note before the first h3, so a block can hold a note
        # and no rows. Keep that block; the page navigation sits outside the article.
        if self._block and (self._block["rows"] or self._block["notes"]):
            self.blocks.append(self._block)
        self._block = None

    def _text(self) -> str:
        text = clean("".join(self._buf or []))
        self._buf = None
        return text

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag == "article":
            self._article = True
        if not self._article:
            return
        if tag in ("h2", "h3", "p"):
            self._buf = []
        elif tag == "tbody":
            self._in_body = True
        elif tag == "tr" and self._in_body:
            self._cells = []
        elif tag in ("td", "th") and self._cells is not None:
            self._buf = []

    def handle_endtag(self, tag: str) -> None:
        if not self._article:
            return
        if tag == "article":
            self._flush()
            self._article = False
        elif tag in ("h2", "h3"):
            title = self._text().rstrip("#").strip()
            self._flush()
            self._block = {"level": int(tag[1]), "title": title, "notes": [], "rows": []}
        elif tag == "p":
            note = self._text()
            if self._block is None:
                # Skip the breadcrumb, which is one short word before the introduction.
                if not self.subtitle and len(note) > SUBTITLE_MIN_CHARS:
                    self.subtitle = note
            elif note:
                self._block["notes"].append(note)
        elif tag in ("td", "th") and self._cells is not None:
            self._cells.append(self._text())
        elif tag == "tr" and self._cells is not None:
            # The emoji table carries the glyph in a middle column. Helvetica cannot
            # show it, so the script keeps the key and the description only.
            cells = [self._cells[0], self._cells[-1]] if len(self._cells) > 2 else self._cells
            if self._block and len(cells) == 2 and any(cells):
                self._block["rows"].append((cells[0], cells[1]))
            self._cells = None
        elif tag == "tbody":
            self._in_body = False

    def handle_data(self, data: str) -> None:
        if self._buf is not None:
            self._buf.append(data)


def fetch(source: str) -> str:
    """Return the manual HTML. The source is a URL or a local file path."""
    if not source.startswith(("http://", "https://")):
        log.debug("reading %s", source)
        with open(source, encoding="utf-8") as fh:
            return fh.read()
    log.debug("GET %s", source)
    try:
        resp = requests.get(source, timeout=HTTP_TIMEOUT,
                            headers={"User-Agent": "omarchy-hotkeys-cheatsheet"})
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"could not reach {source}: {exc}") from exc

    # The server sends the manual as "text/html" without a charset. The requests library
    # then decodes the page as ISO-8859-1, because RFC 2616 requires that fallback. That
    # result corrupts every emoji and every curly quote. Use the charset from the header
    # if the server declares one. Otherwise decode the page as utf-8.
    declared = "charset=" in resp.headers.get("content-type", "").lower()
    encoding = resp.encoding if declared else "utf-8"
    try:
        return resp.content.decode(encoding)
    except (UnicodeDecodeError, LookupError) as exc:
        raise RuntimeError(f"could not decode {source} as {encoding}: {exc}") from exc


def parse(html: str) -> tuple[str, list[dict]]:
    """Return the page subtitle and one block per manual section."""
    parser = ManualParser()
    parser.feed(html)
    if not parser.blocks:
        raise RuntimeError("found no hotkey tables; the manual layout changed")
    return parser.subtitle, parser.blocks


@cache
def layout(scale: float) -> SimpleNamespace:
    """Return the page geometry and the paragraph styles at the given font scale."""
    w, h = A4
    m = 12 * mm
    gutter = 7 * mm
    col_w = (w - 2 * m - gutter) / 2
    ink = colors.HexColor("#1a1b26")
    accent = colors.HexColor("#2f5d8a")
    grey = colors.HexColor("#666666")
    key_w = col_w * 0.44

    def style(name: str, size: float, **kw) -> ParagraphStyle:
        return ParagraphStyle(name, fontSize=size * scale, leading=size * scale * 1.19, **kw)

    return SimpleNamespace(
        W=w, H=h, M=m, GUTTER=gutter, COL_W=col_w, SCALE=scale,
        GREY=grey, LINE=colors.HexColor("#d8d8d8"), ALT=colors.HexColor("#f2f4f7"),
        KEY_W=key_w, VAL_W=col_w - key_w,
        st_title=style("t", 15, fontName="Helvetica-Bold", textColor=ink),
        st_sub=style("s", 7.5, fontName="Helvetica", textColor=grey),
        st_sec=style("sec", 8, fontName="Helvetica-Bold", textColor=colors.white,
                     backColor=accent, borderPadding=(2, 3, 2, 3),
                     spaceBefore=5 * scale, spaceAfter=2, keepWithNext=1),
        st_sub2=style("sub2", 7, fontName="Helvetica-Bold", textColor=accent,
                      spaceBefore=3 * scale, spaceAfter=1, keepWithNext=1),
        st_key=style("k", 6.4, fontName="Helvetica-Bold", textColor=ink),
        st_val=style("v", 6.4, fontName="Helvetica", textColor=ink),
        st_note=style("n", 6.2, fontName="Helvetica-Oblique", textColor=grey,
                      spaceBefore=1, spaceAfter=2),
    )


def table(rows: list[tuple[str, str]], lay: SimpleNamespace) -> Table:
    """Return a two-column table that lists the key combinations and the functions."""
    data = [[Paragraph(k, lay.st_key), Paragraph(v, lay.st_val)] for k, v in rows]
    t = Table(data, colWidths=[lay.KEY_W, lay.VAL_W], repeatRows=0)
    pad = 1.3 * lay.SCALE
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), pad),
        ("BOTTOMPADDING", (0, 0), (-1, -1), pad),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, lay.LINE),
    ]
    for i in range(len(data)):
        if i % 2 == 1:
            style.append(("BACKGROUND", (0, i), (-1, i), lay.ALT))
    t.setStyle(TableStyle(style))
    return t


def build_story(subtitle: str, blocks: list[dict], lay: SimpleNamespace) -> list:
    """Return the flowables for one render pass.

    reportlab consumes the flowables during the build, so each pass needs a new list.
    """
    story: list = [Paragraph("Omarchy Hotkeys", lay.st_title)]
    if subtitle:
        story.append(Paragraph(subtitle, lay.st_sub))
    story.append(Spacer(1, 4))
    for block in blocks:
        head = lay.st_sec if block["level"] == 2 else lay.st_sub2
        group = [Paragraph(block["title"], head)]
        for note in block["notes"]:
            group.append(Paragraph(note, lay.st_note))
        if block["rows"]:
            group.append(table(block["rows"], lay))
        story.extend(group if len(block["rows"]) > KEEP_TOGETHER_MAX_ROWS
                     else [KeepTogether(group)])
    return story


def render(target, subtitle: str, blocks: list[dict], scale: float, total_pages: int) -> int:
    """Render the sheet to a file path or to a file object. Return the page count."""
    lay = layout(scale)
    stamp = date.today().isoformat()

    def footer(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 6)
        canvas.setFillColor(lay.GREY)
        canvas.drawString(lay.M, lay.M * 0.55,
                          f"Source: {SOURCE_LABEL}  |  generated {stamp}")
        canvas.drawRightString(lay.W - lay.M, lay.M * 0.55,
                               f"Page {doc.page} of {total_pages}")
        canvas.restoreState()

    doc = BaseDocTemplate(target, pagesize=(lay.W, lay.H),
                          leftMargin=lay.M, rightMargin=lay.M,
                          topMargin=lay.M, bottomMargin=lay.M,
                          title="Omarchy Hotkeys Cheat Sheet",
                          author="Omarchy Hotkeys Cheat Sheet",
                          subject=f"Source: {MANUAL_URL}")
    fh = lay.H - 2 * lay.M
    frames = [
        Frame(lay.M, lay.M, lay.COL_W, fh, id="c1",
              leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0),
        Frame(lay.M + lay.COL_W + lay.GUTTER, lay.M, lay.COL_W, fh, id="c2",
              leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0),
    ]
    doc.addPageTemplates([PageTemplate(id="two", frames=frames, onPage=footer)])
    doc.build(build_story(subtitle, blocks, lay))
    return doc.page


def fit(subtitle: str, blocks: list[dict], target_pages: int) -> tuple[float, int]:
    """Return the largest font scale that fits the target page count."""
    for scale in FONT_SCALES:
        pages = render(BytesIO(), subtitle, blocks, scale, target_pages)
        log.debug("scale %.2f gives %d page(s)", scale, pages)
        if pages <= target_pages:
            return scale, pages
    raise RuntimeError(
        f"content does not fit {target_pages} page(s) at any supported font scale")


def parse_args() -> argparse.Namespace:
    """Return the command line arguments."""
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("-o", "--output", default=DEFAULT_OUTPUT, help="output PDF path")
    p.add_argument("--source", default=MANUAL_URL,
                   help="manual URL, or a local HTML file")
    p.add_argument("--pages", type=int, default=TARGET_PAGES, help="target page count")
    p.add_argument("--dry-run", action="store_true",
                   help="report the result and write nothing")
    p.add_argument("--debug", action="store_true", help="verbose logging")
    return p.parse_args()


def main() -> int:
    """Build the sheet and return the process exit code."""
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    log.info("=== Script started ===")
    try:
        subtitle, blocks = parse(fetch(args.source))
        rows = sum(len(b["rows"]) for b in blocks)
        log.info("read %d sections and %d rows from %s", len(blocks), rows, args.source)
        scale, pages = fit(subtitle, blocks, args.pages)
        log.info("fits %d page(s) at font scale %.2f", pages, scale)
        if args.dry_run:
            log.info("dry run, not writing %s", args.output)
        else:
            render(args.output, subtitle, blocks, scale, pages)
            log.info("wrote %s", args.output)
    except (RuntimeError, OSError) as exc:
        log.error("%s", exc)
        return 1
    log.info("=== Done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
