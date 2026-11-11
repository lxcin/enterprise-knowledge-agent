from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest

from knowledge_agent.citations import validate_citations
from knowledge_agent.documents import load_documents
from knowledge_agent.ingest import import_attachment
from knowledge_agent.retrieval import DocumentTools

try:
    import pdfplumber
    from PIL import Image, ImageDraw
    from reportlab.pdfgen import canvas
except ImportError:
    pdfplumber = None


class ImportTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.corpus = self.root / "corpus"

    def test_markdown_import_and_duplicate_version_protection(self):
        source = self.root / "policy.md"
        source.write_text("# 报销制度\n\n费用发生后 30 天内提交。\n\n"
                          "| 事项 | 期限 |\n| --- | --- |\n| 采购 | 15 天 |\n",
                          encoding="utf-8")
        bundle = import_attachment(source, self.corpus, "D01", "2026-01-01", "报销")
        self.assertEqual((bundle / "source.md").read_bytes(), source.read_bytes())
        self.assertEqual({file.name for file in bundle.iterdir()}, {"source.md", "document.json"})
        evidence = list(load_documents(self.corpus).values())
        self.assertEqual([item.kind for item in evidence], ["text", "table"])
        self.assertEqual(evidence[0].source_file, "D01@2026-01-01/source.md")
        with self.assertRaisesRegex(ValueError, "已导入"):
            import_attachment(source, self.corpus, "D01", "2026-01-01", "报销")

    @unittest.skipUnless(pdfplumber, "需要 PDF 测试依赖 pdfplumber 和 reportlab")
    def test_pdf_body_and_table_are_searchable_and_citable(self):
        source = self.root / "policy.pdf"
        pdf = canvas.Canvas(str(source), pagesize=(400, 400))
        pdf.drawString(40, 365, "Expense claims must be filed within 30 days.")
        for y in (320, 290, 260):
            pdf.line(40, y, 340, y)
        for x in (40, 190, 340):
            pdf.line(x, 260, x, 320)
        for x, y, value in ((50, 300, "Category"), (200, 300, "Deadline"),
                            (50, 270, "Procurement"), (200, 270, "15 days")):
            pdf.drawString(x, y, value)
        pdf.drawString(40, 243, "Note: applies to procurement only.")
        pdf.save()
        bundle = import_attachment(source, self.corpus, "D02", "2026-01-01", "expense")
        tools = DocumentTools(load_documents(self.corpus))
        table = next(item for item in tools.search_docs("procurement deadline") if item.kind == "table")
        text = next(item for item in tools.evidence.values() if item.kind == "text")
        self.assertIn("30 days", text.text)
        self.assertNotIn("15 days", text.text)
        self.assertIn("Note: applies", table.text)
        citation = validate_citations([{"id": table.id, "quote": "Deadline：15 days"}],
                                      {table.id: tools.read_chunk(table.id)})[0]
        self.assertEqual(citation["page"], 1)
        self.assertEqual(citation["source_file"], "D02@2026-01-01/source.pdf")
        self.assertEqual(citation["bbox"], (40, 80, 340, 140))
        self.assertEqual({file.name for file in bundle.iterdir()}, {"source.pdf", "document.json"})

    @unittest.skipUnless(pdfplumber and shutil.which("pdftoppm"), "需要 PDF 测试依赖和 Poppler")
    def test_scan_page_keeps_original_visual_evidence(self):
        source = self.root / "scan.pdf"
        image_path = self.root / "scan.png"
        image = Image.new("RGB", (350, 140), "white")
        ImageDraw.Draw(image).text((20, 20), "Scanned policy", fill="black")
        image.save(image_path)
        pdf = canvas.Canvas(str(source), pagesize=(400, 250))
        pdf.drawImage(str(image_path), 25, 40, width=350, height=140)
        pdf.save()
        import_attachment(source, self.corpus, "D03", "2026-01-01", "scanned policy")
        tools = DocumentTools(load_documents(self.corpus))
        evidence, = tools.search_topic("scanned policy")
        self.assertEqual(evidence.kind, "scan")
        self.assertTrue(tools.read_chunk(evidence.id).image.startswith(b"\x89PNG"))
        self.assertEqual(evidence.asset_path, "D03@2026-01-01/p0001-original.png")

    @unittest.skipUnless(pdfplumber and shutil.which("pdftoppm"), "需要 PDF 测试依赖和 Poppler")
    def test_visual_page_replaces_flattened_chart_text(self):
        source = self.root / "chart.pdf"
        pdf = canvas.Canvas(str(source), pagesize=(400, 250))
        pdf.drawString(40, 200, "Approval workflow")
        pdf.line(60, 180, 160, 180)
        pdf.save()
        import_attachment(source, self.corpus, "D04", "2026-01-01", "approval", visual_pages=[1])
        tools = DocumentTools(load_documents(self.corpus))
        evidence, = tools.search_docs("approval workflow")
        self.assertEqual(evidence.kind, "figure")
        self.assertTrue(tools.read_chunk(evidence.id).image)
