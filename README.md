# toc-this

Adds a clickable table of contents (the bookmarks sidebar) to a PDF that has none. It works on born-digital and scanned PDFs.

```
uv tool install toc-this              # or: pipx install toc-this
toc-this book.pdf                     # writes book.toc.pdf
```

To run it once without installing, use `uvx toc-this book.pdf`. It needs Python 3.9 or newer. Scanned PDFs also need Tesseract (see [Scanned PDFs](#scanned-pdfs)).

## How it finds the headings

1. **The book's printed Contents page.** The titles and the nesting (from indentation) come from the Contents page. If the Contents lines link to their pages, as Word and LaTeX exports usually do, those links give the pages. Otherwise, each title is found in the book itself. The search goes forward from the previous entry and tolerates OCR typos. The printed page numbers are not used, because OCR misreads them next to dot leaders, and front matter often uses separate numbering.
2. **Font sizes.** This is used when there is no Contents page. Lines in a larger font than the body text become headings.
3. **Your own list.** This is used when the guess is wrong:

```
toc-this book.pdf --print > toc.txt   # write what it found, then edit it
toc-this book.pdf --from toc.txt      # use your list
```

In `toc.txt`, each level is indented two more spaces, and the page number goes last:

```
Chapter 1 Getting started  5
  1.1 Install  6
```

`--offset N` adds N to every page in `--from`. Use it when you type page numbers from the printed book and printed page 1 is PDF page 1+N.

## Scanned PDFs

When most pages have no text, toc-this OCRs every page on all CPU cores with [Tesseract](https://github.com/tesseract-ocr/tesseract). A 469-page book took about 2 minutes on an 8-core Mac. Install Tesseract first:

```
brew install tesseract        # macOS
sudo apt install tesseract-ocr  # Debian/Ubuntu
```

Use `--lang` for books that are not in English, for example `--lang deu` or `--lang eng+fra`. The language data must be installed too. OCR only feeds heading detection. The output PDF is still an image PDF and cannot be searched. To get a searchable PDF, run [OCRmyPDF](https://github.com/ocrmypdf/OCRmyPDF) first, then run toc-this on its output.

## Limits

- PDFs that already have a ToC are refused.
- On scans, OCR sometimes garbles a Contents line beyond recognition, often short ones next to dense dot leaders. Those entries are left out of the PDF. `--print` shows each one as a `# ` line in its place. To add one back, delete the `# `, fix the title, add the page number, and pass the file with `--from`.
- On scans, a title is taken from the matching heading in the body when that heading is the same length, because body headings are larger and OCR more cleanly. Otherwise the Contents wording is kept.
- toc-this looks for a Contents page only in the first 30 pages.
- When the fallback guesses from font sizes, it misses subheadings set in the same size as body text. Use `--from` for those.

## Development

```
uv run python test_toc.py                       # self-check, runs the OCR case when tesseract is on PATH
uv run python check_sample.py some.pdf [count]  # every entry's title must appear on its page
```

To release, bump `version` in `pyproject.toml`, commit, and push a tag `v<version>`. The `publish` workflow runs the tests (with Tesseract) and uploads to PyPI.

Run `check_sample.py` on a long scanned book before changing how titles are matched. One rule is covered only there: short, generic titles such as "Summary" may not move the search forward. The unit fixture is too short to show the cascade that rule prevents.

## License

AGPL-3.0-or-later. toc-this depends on [PyMuPDF](https://pymupdf.readthedocs.io), which is AGPL.
