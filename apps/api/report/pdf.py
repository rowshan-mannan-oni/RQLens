"""Render the Markdown report as a print-ready PDF (Markdown -> HTML -> WeasyPrint)."""

import html

import markdown

CSS = """
@page {
  size: A4;
  margin: 18mm 16mm 20mm;
  @bottom-left { content: "RQ Lens dataset report"; color: #858b98; font-size: 8pt;
                 font-family: "DejaVu Sans", "Helvetica", sans-serif; }
  @bottom-right { content: counter(page) " / " counter(pages); color: #858b98; font-size: 8pt;
                  font-family: "DejaVu Sans", "Helvetica", sans-serif; }
}
body { font-family: "DejaVu Sans", "Helvetica", sans-serif; font-size: 9.5pt; line-height: 1.45;
       color: #111318; }
h1 { font-size: 20pt; margin: 0 0 6pt; color: #111318; letter-spacing: -0.3pt; }
h1 + p { color: #555b67; }
h2 { font-size: 13pt; margin: 18pt 0 6pt; padding-bottom: 3pt; border-bottom: 1.5pt solid #4f46e5;
     color: #111318; page-break-after: avoid; }
h3 { font-size: 10.5pt; margin: 12pt 0 4pt; page-break-after: avoid; }
p, li { margin: 3pt 0; }
code { font-family: "DejaVu Sans Mono", monospace; font-size: 8pt; background: #f2f3f7;
       padding: 0 2pt; border-radius: 2pt; }
table { width: 100%; border-collapse: collapse; margin: 6pt 0 10pt; font-size: 8pt;
        page-break-inside: auto; }
thead { display: table-header-group; }
tr { page-break-inside: avoid; }
th { text-align: left; background: #eef0fe; color: #3730a3; font-weight: 600; }
th, td { padding: 3pt 5pt; border-bottom: 0.5pt solid #e4e7ec; vertical-align: top; }
td em { color: #858b98; }
strong { color: #111318; }
"""


def to_html(markdown_text: str, title: str) -> str:
    body = markdown.markdown(markdown_text, extensions=["tables", "sane_lists"])
    return (
        f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title>"
        f"<style>{CSS}</style></head><body>{body}</body></html>"
    )


def to_pdf(markdown_text: str, title: str) -> bytes:
    # Imported here: WeasyPrint loads system libraries (Pango) that only the report needs.
    from weasyprint import HTML

    pdf: bytes = HTML(string=to_html(markdown_text, title)).write_pdf()
    return pdf
