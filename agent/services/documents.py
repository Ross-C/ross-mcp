"""Document conversion service — MD to PDF/DOCX."""

import logging
import subprocess
from pathlib import Path

import markdown

logger = logging.getLogger("agent.documents")

PDF_CSS = """
@page { size: A4; margin: 2cm 2.5cm; }
body { font-family: Calibri, "Segoe UI", Helvetica, Arial, sans-serif; font-size: 11pt; line-height: 1.65; color: #2c2c2c; }
h1 { font-size: 22pt; color: #1a1a1a; border-bottom: 3px solid #1a1a1a; padding-bottom: 10px; margin-bottom: 6px; }
h2 { font-size: 15pt; color: #1a1a1a; margin-top: 32px; margin-bottom: 10px; border-bottom: 1px solid #ddd; padding-bottom: 4px; }
h3 { font-size: 12pt; color: #333; margin-top: 20px; }
p { margin: 8px 0; }
strong { color: #1a1a1a; }
code { background: #f5f5f5; padding: 2px 6px; border-radius: 3px; font-family: "Cascadia Code", Consolas, monospace; font-size: 9.5pt; color: #c7254e; }
pre { background: #f5f5f5; padding: 14px 16px; border-radius: 6px; border: 1px solid #e0e0e0; overflow-x: auto; font-size: 9pt; font-family: "Cascadia Code", Consolas, monospace; line-height: 1.5; margin: 12px 0; page-break-inside: avoid; }
pre code { background: none; padding: 0; color: #2c2c2c; }
table { border-collapse: collapse; width: 100%; margin: 14px 0; page-break-inside: avoid; }
th, td { border: 1px solid #ccc; padding: 8px 12px; text-align: left; font-size: 10pt; }
th { background: #f0f0f0; font-weight: 600; color: #1a1a1a; }
tr:nth-child(even) td { background: #fafafa; }
hr { border: none; border-top: 1px solid #ddd; margin: 28px 0; }
ol, ul { padding-left: 24px; margin: 8px 0; }
li { margin-bottom: 5px; }
blockquote { border-left: 4px solid #4a90d9; background: #f0f6ff; padding: 10px 16px; margin: 12px 0; border-radius: 0 4px 4px 0; font-style: italic; }
blockquote p { margin: 0; }
"""

PDF_HTML_WRAPPER = '''<!DOCTYPE html>
<html><head>
<meta charset="UTF-8">
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
<style>{css}</style>
</head><body>{body}</body></html>'''


class DocumentService:
    """Convert markdown files to PDF and DOCX."""

    def convert_md_to_pdf(self, md_path: str, output_path: str | None = None) -> dict:
        """Convert a Markdown file to PDF.

        Args:
            md_path: Path to the .md file
            output_path: Optional output path (defaults to same name with .pdf)
        """
        src = Path(md_path)
        if not src.exists():
            return {"error": f"File not found: {md_path}"}

        if not output_path:
            output_path = str(src.with_suffix(".pdf"))

        md_text = src.read_text(encoding="utf-8")
        html_body = markdown.markdown(md_text, extensions=["tables", "fenced_code"])
        html_doc = PDF_HTML_WRAPPER.format(css=PDF_CSS, body=html_body)

        tmp_html = Path("/tmp/md_to_pdf_export.html")
        tmp_html.write_text(html_doc, encoding="utf-8")

        try:
            subprocess.run(
                ["wkhtmltopdf", "--quiet", "--enable-local-file-access",
                 "--encoding", "UTF-8",
                 "--page-size", "A4",
                 "--margin-top", "20mm", "--margin-bottom", "20mm",
                 "--margin-left", "25mm", "--margin-right", "25mm",
                 str(tmp_html), output_path],
                capture_output=True, text=True, timeout=30, check=True,
            )
        except FileNotFoundError:
            return {"error": "wkhtmltopdf not installed. Run: brew install wkhtmltopdf"}
        except subprocess.CalledProcessError as e:
            return {"error": f"PDF conversion failed: {e.stderr[:200]}"}

        out = Path(output_path)
        return {
            "path": output_path,
            "size_bytes": out.stat().st_size,
            "status": "converted",
        }

    def convert_md_to_docx(self, md_path: str, output_path: str | None = None) -> dict:
        """Convert a Markdown file to DOCX.

        Args:
            md_path: Path to the .md file
            output_path: Optional output path (defaults to same name with .docx)
        """
        src = Path(md_path)
        if not src.exists():
            return {"error": f"File not found: {md_path}"}

        if not output_path:
            output_path = str(src.with_suffix(".docx"))

        reference = Path(__file__).parent / "reference.docx"
        cmd = ["pandoc", str(src), "-o", output_path]
        if reference.exists():
            cmd.extend(["--reference-doc", str(reference)])

        try:
            subprocess.run(
                cmd,
                capture_output=True, text=True, timeout=30, check=True,
            )
        except FileNotFoundError:
            return {"error": "pandoc not installed. Run: brew install pandoc"}
        except subprocess.CalledProcessError as e:
            return {"error": f"DOCX conversion failed: {e.stderr[:200]}"}

        out = Path(output_path)
        return {
            "path": output_path,
            "size_bytes": out.stat().st_size,
            "status": "converted",
        }
