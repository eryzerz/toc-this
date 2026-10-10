import shutil
import tempfile
from pathlib import Path

import pymupdf

import toc_this

CHAPTERS = [("Chapter One", "Setup"), ("Chapter Two", "Usage"), ("Chapter Three 3", "Wrap Up")]
EXPECTED = [[1, "Chapter One", 1], [2, "Setup", 1], [1, "Chapter Two", 2], [2, "Usage", 2], [1, "Chapter Three 3", 3], [2, "Wrap Up", 3]]


def book(with_contents):
    doc = pymupdf.open()
    if with_contents:  # printed page n is physical page n + 1, and there are no links
        page = doc.new_page()
        page.insert_text((72, 60), "Contents", fontsize=20)
        for i, (lvl, title, n) in enumerate(EXPECTED + [[1, "Glossary", 4]]):  # dot leaders on even rows, a wide gap on odd rows
            y = 100 + 20 * i
            page.insert_text((72 + 18 * (lvl - 1), y), title + (" " + "." * 30 if i % 2 == 0 else ""), fontsize=12)
            page.insert_text((400, y), str(n), fontsize=12)
    for n, (chapter, section) in enumerate(CHAPTERS, 1):
        page = doc.new_page()
        page.insert_text((72, 40), "My Book", fontsize=14)
        page.insert_text((72, 80), chapter, fontsize=20)
        page.insert_text((72, 110), section, fontsize=14)
        for i in range(30):
            page.insert_text((72, 140 + 14 * i), "body text " * 8, fontsize=10)
        page.insert_text((300, 800), str(n), fontsize=10)
        if n == 1:
            page.insert_text((20, 700), "arXiv:1234 stamp", fontsize=30, rotate=90)
            for i in range(3):
                page.insert_text((72, 600 + 16 * i), "large notice paragraph " * 3, fontsize=14)
    return doc


def scanned(doc):
    out = pymupdf.open()
    for page in doc:
        out.new_page(width=page.rect.width, height=page.rect.height).insert_image(page.rect, pixmap=page.get_pixmap(dpi=300))
    return out


plain = book(with_contents=False)
lines_of = toc_this.line_reader(plain, "eng")
assert toc_this.contents(plain, lines_of) == [], "no contents page"
found = toc_this.detect(lines_of, plain.page_count)
assert found == EXPECTED, found
assert toc_this.parse(toc_this.dump(found), 0, plain.page_count) == found, "dump/parse round-trip"
assert toc_this.normalize([[2, "a", 1], [4, "b", 1]]) == [[1, "a", 1], [2, "b", 1]]
listed = toc_this.dump([[1, "A", 1], [2, "B", None]])
assert listed == "A  1\n#   B", "not-found entry is a '# ' line"
assert toc_this.parse(listed.replace("# ", "") + "  1", 0, 1) == [[1, "A", 1], [2, "B", 1]], "un-commented line parses"

printed = book(with_contents=True)
shifted = [[lvl, title, page + 1] for lvl, title, page in EXPECTED]
found = toc_this.contents(printed, toc_this.line_reader(printed, "eng"))
assert found == shifted + [[1, "Glossary", None]], found

if shutil.which("tesseract"):
    scan = scanned(printed)
    found = toc_this.contents(scan, toc_this.line_reader(scan, "eng"), body_titles=True)
    assert found[:-1] == shifted and found[-1][2] is None, f"OCR: {found}"
else:
    print("skip OCR: tesseract not on PATH")

with tempfile.TemporaryDirectory() as d:
    src, out, toc_txt = Path(d, "in.pdf"), Path(d, "out.pdf"), Path(d, "toc.txt")
    plain.save(src)
    toc_txt.write_text("Intro  0\n  Detail  1\n")
    toc_this.main([str(src), "--from", str(toc_txt), "--offset", "1", "-o", str(out)])
    assert pymupdf.open(out).get_toc() == [[1, "Intro", 1], [2, "Detail", 2]], "written outline"
    printed.save(src_printed := Path(d, "printed.pdf"))
    toc_this.main([str(src_printed), "-o", str(out_printed := Path(d, "printed.toc.pdf"))])
    assert pymupdf.open(out_printed).get_toc() == shifted, "not-found entries are left out of the outline"
    for argv, why in (([str(src), "--from", str(toc_txt), "--offset", "9"], "out-of-range page"), ([str(out)], "PDF that already has a ToC")):
        try:
            toc_this.main(argv)
            raise AssertionError(f"accepted {why}")
        except SystemExit:
            pass

print("ok")
