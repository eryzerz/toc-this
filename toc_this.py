"""Add a clickable table of contents (PDF outline / bookmarks) to a PDF that has none.

  toc-this book.pdf                          find headings, write book.toc.pdf
  toc-this book.pdf --print > toc.txt        dump the found ToC for editing
  toc-this book.pdf --from toc.txt -o x.pdf  use a hand-written or edited ToC

Headings come from the book's printed Contents page when it has one, else from
font sizes. Scanned pages are OCR'd with Tesseract (install it separately).

ToC text format: one entry per line, two spaces of indent per level,
the page number last. Blank lines and lines starting with # are ignored.

  Chapter 1 Getting started  5
    1.1 Install  6
"""
import argparse
import functools
import re
import sys
from collections import Counter, defaultdict, namedtuple
from concurrent.futures import ProcessPoolExecutor
from difflib import SequenceMatcher
from itertools import repeat
from pathlib import Path

import pymupdf

Line = namedtuple("Line", "x0 y0 y1 size text")
Printed = namedtuple("Printed", "x0 title target")

ENTRY = re.compile(r"^( *)(.+?)\s+(\d+)\s*$")
# A Contents line: a title, then dot leaders, OCR's version of them ("ceeeccsee..."), or a wide gap.
LEADER = re.compile(r"^(.*?[^\W\d_].*?)\s*(?:[.·…_]{3,}|\w{20,}|\s{3,}|[.·…]\s*(?:\d+|[ivxlcdm]+)$).*$", re.I)


def page_lines(page, lang=None):
    textpage = None
    if lang and not page.get_text().strip() and page.get_images():
        textpage = page.get_textpage_ocr(language=lang, dpi=300, full=True)
    out = []
    for block in page.get_text("dict", textpage=textpage)["blocks"]:
        for line in block.get("lines", []):
            spans = [s for s in line["spans"] if s["text"].strip()]
            if not spans or line["dir"] != (1.0, 0.0):  # rotated text is margin stamps, not headings
                continue
            text = spans[0]["text"]
            for a, b in zip(spans, spans[1:]):  # a wide gap becomes a leader, for ToCs without dots
                gap = b["bbox"][0] - a["bbox"][2]
                text += ("    " if gap > 2 * a["size"] else " " if gap > 0.15 * a["size"] else "") + b["text"]
            x0, y0, _, y1 = line["bbox"]
            out.append(Line(x0, y0, y1, round(max(s["size"] for s in spans)), " ".join(text.split())))
    return out


def ocr_pages(path, lang, pnos):
    doc = pymupdf.open(path)
    return [page_lines(doc[p], lang) for p in pnos]


def is_scanned(doc):
    return sum(bool(p.get_text().strip()) for p in doc) < doc.page_count / 2


def line_reader(doc, lang):
    """Return pno (0-based) -> [Line]. When most of the book is scanned, OCR every page up front on all cores."""
    scanned = is_scanned(doc)
    if scanned and doc.name:
        chunks = [range(i, min(i + 8, doc.page_count)) for i in range(0, doc.page_count, 8)]
        lines = []
        with ProcessPoolExecutor() as pool:
            for part in pool.map(ocr_pages, repeat(doc.name), repeat(lang), chunks):
                lines += part
                print(f"\rOCR {len(lines)}/{doc.page_count} pages", end="", file=sys.stderr)
        return lines.__getitem__
    return functools.lru_cache(maxsize=None)(lambda pno: page_lines(doc[pno], lang if scanned else None))


def plausible(text):
    return len(text) <= 120 and re.search(r"[^\W\d_]", text)


def key(text):
    return re.sub(r"[\W_]", "", text.lower())


def printed_entries(doc, lines_of, pno):
    links = [l for l in doc[pno].get_links() if l["kind"] == pymupdf.LINK_GOTO]
    rows = []  # OCR splits a far-right page number into its own line on the same row
    for ln in lines_of(pno):
        r = rows[-1] if rows else None
        if r and ln.x0 > r.x0 and min(ln.y1, r.y1) - max(ln.y0, r.y0) > 0.5 * min(ln.y1 - ln.y0, r.y1 - r.y0):
            rows[-1] = r._replace(text=f"{r.text}    {ln.text}")
        else:
            rows.append(ln)
    out, prev = [], None
    for ln in rows:
        if re.fullmatch(r"\d+|[ivxlcdm]+", ln.text, re.I):  # the page's own number, never part of a title
            continue
        adjacent = prev and ln.y0 - prev.y1 < 0.5 * (ln.y1 - ln.y0)
        m = LEADER.match(ln.text)
        if not m:  # maybe the first line(s) of a wrapped entry
            prev = prev._replace(y1=ln.y1, text=f"{prev.text} {ln.text}") if adjacent else ln
            continue
        first, title = (prev, f"{prev.text} {m[1]}") if adjacent and plausible(prev.text) else (ln, m[1])
        mid = (ln.y0 + ln.y1) / 2
        target = next((l["page"] + 1 for l in links if l["from"].y0 <= mid <= l["from"].y1), None)
        title = re.sub(r"\s+[.0o]*\.[.0o]*$", "", title)  # OCR leftovers of a leader: " .0", " 0.", " ..00"
        out.append(Printed(first.x0, re.sub(r"\s+", " ", title).strip(), target))
        prev = None
    return out


def find_heading(title, titles, start, lines_of, end):
    """(page, heading text) of the first line (or 2-3 wrapped lines) from `start` reading like `title`,
    tolerating OCR typos, else (None, None).

    A line that another Contents title matches better is that title's heading, not ours
    ("Preface to the Third Edition" is not "Preface to the First Edition").
    """
    want = key(title)
    rivals = [k for k in map(key, titles) if SequenceMatcher(None, k, want).ratio() < 0.9]  # not repeats like "Summary"
    for pno in range(start - 1, end):
        lines = lines_of(pno)
        keys = [key(l.text) for l in lines]
        for i in range(len(keys)):
            for n in (1, 2, 3):
                got = "".join(keys[i:i + n])
                score = SequenceMatcher(None, want, got).ratio()
                if score >= 0.8 and all(SequenceMatcher(None, k, got).ratio() <= score for k in rivals):
                    return pno + 1, " ".join(l.text for l in lines[i:i + n])
                if len(got) > len(want):
                    break
    return None, None


def contents(doc, lines_of, body_titles=False, search=30):
    """Entries from the printed Contents page(s), or [] if there are none. An entry whose
    heading is not found keeps page None. With body_titles, a found entry takes the matched
    heading's text, which OCRs more cleanly than the small Contents print."""
    raw, pages = [], []
    for pno in range(min(search, doc.page_count)):  # ponytail: only the front of the book; end-of-book ToCs fall back to fonts
        found = printed_entries(doc, lines_of, pno)
        if pages:  # a continued Contents page keeps the same indents; margin noise does not
            found = [e for e in found if any(abs(e.x0 - r.x0) <= 6 for r in raw)]
        if len(found) >= (2 if pages else 5):
            raw += found
            pages.append(pno)
        elif pages:
            break
    if not raw:
        return []

    indents = sorted({round(e.x0) for e in raw})
    level_of, level = {}, 0
    for i, x in enumerate(indents):
        level += i == 0 or x - indents[i - 1] > 6
        level_of[x] = level

    # Printed page numbers are not trusted (OCR mangles them next to dot leaders). Each title is
    # found in the body instead, searching forward from the previous entry so repeats like
    # "Summary" land in their own section.
    entries, start, titles = [], pages[-1] + 2, [e.title for e in raw]
    # A generic title ("Summary", "Notes") can match far ahead and drag the search past
    # everything in between, so it only looks nearby and never moves the search forward.
    for e in raw:
        distinctive = len(key(e.title)) >= 12
        end = doc.page_count if distinctive else min(doc.page_count, start + 20)
        page, heading = (e.target, None) if e.target else find_heading(e.title, titles, start, lines_of, end)
        # The body heading only replaces the title when it is the same length: longer means a running
        # header got glued on, shorter (or a trailing hyphen) means the heading wraps past the matched lines.
        same = heading and not heading.endswith("-") and abs(len(key(heading)) - len(key(e.title))) <= max(2, len(key(e.title)) // 20)
        entries.append([level_of[round(e.x0)], heading if body_titles and same else e.title, page])
        if page and (distinctive or e.target):
            start = max(start, page)
    return entries


def detect(lines_of, npages, levels=3):
    """Entries from font sizes: lines larger than the body text, biggest first."""
    lines, chars, pages_of = [], Counter(), defaultdict(set)
    for pno in range(npages):
        for ln in lines_of(pno):
            chars[ln.size] += len(ln.text)
            pages_of[ln.text].add(pno)
            lines.append((ln.size, ln.text, pno + 1))
    if not chars:
        return []
    body = chars.most_common(1)[0][0]

    # ponytail: font size is the only signal; bold/numbering/position would catch same-size headings.
    def heading(size, text):
        return size > body and plausible(text) and len(pages_of[text]) < 3  # <3 pages: drops running headers

    sizes = sorted({s for s, t, _ in lines if heading(s, t)}, reverse=True)[:levels]
    level = {s: i for i, s in enumerate(sizes, 1)}
    entries, prev = [], None
    for size, text, page in lines:
        if size not in level or not heading(size, text):
            prev = None
            continue
        if prev == (size, page):  # heading wrapped onto a second line
            entries[-1][1] += " " + text
        else:
            entries.append([level[size], text, page])
        prev = (size, page)
    return [e for e in entries if plausible(e[1])]  # a long merged run is a large-font paragraph


def parse(text, offset, npages):
    entries = []
    for n, raw in enumerate(text.splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        m = ENTRY.match(raw.expandtabs(2))
        if not m:
            sys.exit(f"line {n}: expected '<indent>title page', got {raw!r}")
        page = int(m[3]) + offset
        if not 1 <= page <= npages:
            sys.exit(f"line {n}: page {page} outside 1..{npages}")
        entries.append([len(m[1]) // 2 + 1, m[2], page])
    return entries


def dump(entries):
    """Not-found entries (page None) become '# ' lines: delete the '# ' and add the page to use them."""
    return "\n".join(
        "  " * (lvl - 1) + f"{title}  {page}" if page else "# " + "  " * (lvl - 1) + title for lvl, title, page in entries
    )


def normalize(entries):
    """PDF outlines must start at level 1 and never skip a level going down."""
    out, prev = [], 0
    for lvl, title, page in entries:
        prev = max(1, min(lvl, prev + 1))
        out.append([prev, title, page])
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="toc-this", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf", type=Path)
    ap.add_argument("-o", "--out", type=Path, help="default: <pdf>.toc.pdf")
    ap.add_argument("--from", dest="src", type=Path, help="ToC text file instead of auto-detection")
    ap.add_argument("--offset", type=int, default=0, help="added to every --from page (printed page 1 is PDF page 1+offset)")
    ap.add_argument("--levels", type=int, default=3, help="max heading levels when guessing from font sizes")
    ap.add_argument("--lang", default="eng", help="Tesseract language(s) for scanned pages, e.g. eng+deu")
    ap.add_argument("--print", action="store_true", help="print the ToC instead of writing a PDF")
    a = ap.parse_args(argv)

    doc = pymupdf.open(a.pdf)
    if doc.needs_pass:
        sys.exit(f"{a.pdf}: encrypted, decrypt it first")
    if doc.get_toc():
        sys.exit(f"{a.pdf}: already has a ToC")
    try:
        lines_of = line_reader(doc, a.lang)
        if a.src:
            entries, source = parse(a.src.read_text(), a.offset, doc.page_count), str(a.src)
        else:
            entries, source = contents(doc, lines_of, body_titles=is_scanned(doc)), "printed contents page"
            if not any(page for _, _, page in entries):
                entries, source = detect(lines_of, doc.page_count, a.levels), "font sizes"
    except RuntimeError as e:  # PyMuPDF raises this when Tesseract or its language data is missing
        sys.exit(f"\nOCR failed ({e}). Install Tesseract (brew/apt install tesseract) and the --lang data.")
    found = [e for e in entries if e[2]]
    if not found:
        sys.exit("no headings found, pass --from")
    missing = len(entries) - len(found)
    note = f", {missing} not found (shown as '# ' lines by --print)" if missing else ""
    print(f"\r{len(found)} entries from {source}{note}", file=sys.stderr)

    if a.print:
        print(dump(normalize(entries)))
        return
    out = a.out or a.pdf.with_suffix(".toc.pdf")
    doc.set_toc(normalize(found))
    doc.save(out, garbage=3, deflate=True)
    print(out)


if __name__ == "__main__":
    main()
