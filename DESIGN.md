# toc-this design

## Problem

Add a clickable table of contents to PDFs that have none, born-digital or scanned, as an open-source CLI. These PDFs carry no structure tags, so headings must be recovered from the printed page. Scans add OCR noise. Recovery will sometimes be incomplete, so the user needs a cheap correction path.

## Usage (caller's view)

```
toc-this book.pdf                          # writes book.toc.pdf
toc-this book.pdf --print > toc.txt        # inspect or edit
toc-this book.pdf --from toc.txt --offset 12
toc-this scan.pdf --lang eng+deu           # scanned: OCR via Tesseract
```

## Shape

The data shape is `[level, title, page]`, with 1-based pages, which is exactly what PyMuPDF's `set_toc` takes. Every source produces it, and `normalize` then `set_toc` is the only sink.

`line_reader(doc, lang)` is the only text access. It returns `Line(x0, y0, y1, size, text)` per page. For a mostly scanned book it OCRs every page up front across all cores. Otherwise it extracts lazily and caches. The sources never know whether the text came from OCR.

The sources are tried in order:

1. **`contents()`, the printed Contents page.** It takes titles and indent levels from the Contents lines. Each page comes from the line's GOTO link if there is one. Otherwise `heading_page` finds the title in the body. The search is forward from the previous entry and fuzzy (`difflib`, ratio ≥ 0.8). A line counts only if no different Contents title matches it better. Short, generic titles search 20 pages and never move the search forward.
2. **`detect()`, font sizes.** It runs only when no Contents page is found.
3. **`parse()`, the user's text.** It is the inverse of `dump()`, and this round-trip is the correction path.

## Evidence that shaped it

The sample is a 469-page Word export. It has a linked Contents page with 72 entries.

- **Font sizes alone.** These produced bylines, pull quotes and page headers as entries. They became the fallback, not the main source.
- **Links.** These gave 72 of 72 entries, with each title found on its page.
- **Links removed.** Title search gave 71 of 71, the same pages as the links except section entries. Those landed on the section divider page, which is where the title is printed.
- **Scanned copy (200 dpi, JPEG).** Tesseract read 11 of 72 printed page numbers next to dot leaders, even on a clean 300 dpi render. That ruled out the first design, which mapped printed numbers to pages through a voted offset. Title search found 52 of 71 entries, all with the correct page and level. The 19 misses are Contents lines that OCR garbled ("SUNN ALY" for "Summary").
- **Parallel OCR.** OCR on 8 cores took 1:48, against 8:22 sequential.

## Tradeoffs accepted

- **Single dependency on PyMuPDF.** In exchange, the project is AGPL-3.0-or-later. Going permissive would need pypdf, pdfminer.six, pypdfium2 and a separate OCR binding.
- **Tesseract is a system install.** The output stays an image PDF, and OCRmyPDF covers making it searchable.
- **A scanned book is OCR'd in full up front.** Title search and the font fallback need nearly every page anyway.
- **The Contents page is searched for only in the first 30 pages.**
- **A missed entry is skipped and reported on stderr,** never guessed.

## Alternatives considered

- **Printed page numbers plus an offset.** Rejected because of the OCR evidence above. It also needed roman-numeral and page-label handling, which title search makes unnecessary.
- **Rendered ToC page inserted at the front.** Rejected because it shifts every page number.
- **Tagged-PDF structure (H1..H6).** Rejected because tags are rare in PDFs that lack outlines.
- **Pure-pip OCR (RapidOCR).** Rejected because it is a large dependency to avoid one `brew` or `apt` line.

## Implementation reconciliation

- **Not-found entries** (accepted by the user). `contents()` keeps them with page `None`. `dump` renders them as `# <indent>title` lines, so deleting `# ` and adding a page makes the line valid. `main` leaves them out of the written outline and counts them on stderr.
- **Body heading titles on scans** (accepted by the user, narrowed by measurement). Replacing every title made the scanned sample worse, at 24 exact titles against 29, because the 1-3 matched lines often include a running header or stop mid-heading. The shipped rule replaces a title only when the body heading is the same length (within 5%) and doesn't end in a hyphen. That gives 35 exact titles. 15 titles improved, and 2 lost a colon that the body heading doesn't print.

## Open questions and risks

- 6 of the scan's 71 entries never become an entry or a `# ` line. In one case, OCR merged two Contents lines into one ("The Progtamme ot the Part… A Critique of the Draft…"). The other 5 haven't been traced.
