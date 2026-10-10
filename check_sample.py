"""Check toc-this against a real PDF: every entry's title must appear on the page it points to.

  uv run python check_sample.py samples/book.pdf [expected_entry_count]
"""
import sys

import pymupdf

import toc_this

doc = pymupdf.open(sys.argv[1])
lines_of = toc_this.line_reader(doc, "eng")
entries = [e for e in toc_this.contents(doc, lines_of, toc_this.is_scanned(doc)) if e[2]] or toc_this.detect(lines_of, doc.page_count)
page_text = lambda p: toc_this.key(" ".join(l.text for l in lines_of(p - 1)))
misses = [e for e in entries if toc_this.key(e[1])[:20] not in page_text(e[2])]
for lvl, title, page in misses:
    print(f"MISS  p{page}  {title}")
print(f"{len(entries)} entries, {len(misses)} misses")
assert not misses
if len(sys.argv) > 2:
    assert len(entries) == int(sys.argv[2]), f"expected {sys.argv[2]} entries"
