"""Document conversion service — MD to PDF/DOCX."""

import logging
import subprocess
from pathlib import Path

import markdown

logger = logging.getLogger("agent.documents")

PDF_CSS = """
body { font-family: -apple-system, Helvetica, Arial, sans-serif; font-size: 11pt; line-height: 1.6; max-width: 780px; margin: 40px auto; color: #222; padding: 0 20px; }
h1 { font-size: 20pt; border-bottom: 2px solid #333; padding-bottom: 8px; }
h2 { font-size: 14pt; margin-top: 28px; color: #333; }
h3 { font-size: 12pt; margin-top: 20px; }
code { background: #f4f4f4; padding: 2px 6px; border-radius: 3px; font-size: 10pt; }
pre { background: #f4f4f4; padding: 12px; border-radius: 4px; overflow-x: auto; font-size: 10pt; }
pre code { background: none; padding: 0; }
table { border-collapse: collapse; width: 100%; margin: 12px 0; }
th, td { border: 1px solid #ddd; padding: 8px; text-align: left; font-size: 10pt; }
th { background: #f4f4f4; font-weight: 600; }
hr { border: none; border-top: 1px solid #ddd; margin: 24px 0; }
ol, ul { padding-left: 24px; }
li { margin-bottom: 4px; }
"""


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

        md_text = src.read_text()
        html_body = markdown.markdown(md_text, extensions=["tables", "fenced_code"])
        html_doc = f"<!DOCTYPE html><html><head><style>{PDF_CSS}</style></head><body>{html_body}</body></html>"

        tmp_html = Path("/tmp/md_to_pdf_export.html")
        tmp_html.write_text(html_doc)

        try:
            subprocess.run(
                ["wkhtmltopdf", "--quiet", "--enable-local-file-access",
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
