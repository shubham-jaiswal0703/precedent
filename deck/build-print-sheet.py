"""Build print.html: every slide of the deck as a page, in presentation order."""
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
SRC = HERE / "composition" / "index.html"
ORDER = ["title", "problem", "insight", "demo", "room", "corpus", "who", "future", "close",
         "arch-1", "arch-2"]

PRINT_CSS = """
      /* One slide per page at the deck's own 16:9 geometry. */
      @page { size: 1920px 1080px; margin: 0; }
      html, body { width: auto; height: auto; overflow: visible; background: #fff; }
      .slide { break-after: page; page-break-after: always; display: block; }
      .slide:last-child { break-after: auto; page-break-after: auto; }
      /* Nothing animates in a PDF, so every element prints at its final state. */
      .clip { visibility: visible !important; opacity: 1 !important; }
      * { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
"""


def slide_blocks(html: str) -> dict:
    """{slide-id: outer html}, walking div depth so nested markup survives."""
    blocks = {}
    for match in re.finditer(r'<div\b[^>]*?id="slide-([\w-]+)"[^>]*>', html, re.S):
        slide_id, start = match.group(1), match.start()
        depth, pos = 0, start
        while pos < len(html):
            nxt_open, nxt_close = html.find("<div", pos), html.find("</div>", pos)
            if nxt_close == -1:
                break
            if nxt_open != -1 and nxt_open < nxt_close:
                depth, pos = depth + 1, nxt_open + 4
            else:
                depth, pos = depth - 1, nxt_close + 6
                if depth == 0:
                    blocks[slide_id] = html[start:pos]
                    break
    return blocks


def main() -> None:
    src = SRC.read_text()
    style = re.search(r"<style>(.*?)</style>", src, re.S).group(1)
    blocks = slide_blocks(src)
    missing = [key for key in ORDER if key not in blocks]
    if missing:
        raise SystemExit(f"slides missing from the composition: {missing}")
    pages = "\n".join(blocks[key] for key in ORDER)
    (HERE / "print.html").write_text(
        f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <title>Precedent: pitch deck</title>
    <style>{style}{PRINT_CSS}</style>
  </head>
  <body>
{pages}
  </body>
</html>
"""
    )
    print(f"print.html: {len(ORDER)} pages")


if __name__ == "__main__":
    main()
