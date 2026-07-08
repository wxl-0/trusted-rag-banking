import pytest

from src.parser.base import Chunk


def test_chunk_preserves_cell_metadata():
    chunk = Chunk(
        doc_id="STAT-001",
        chunk_id="STAT-001#Sheet1#C5",
        text="2025-09, Sheet1 C5: row=Premium, column=YTD, value=123.45 yuan.",
        chunk_type="table_row",
        source_title="Monthly report",
        issuer="NFRA",
        doc_no="",
        publish_date="2025-09-01",
        section_path=[],
        source_url="",
        local_path="data/raw/report.xlsx",
        table_name="Sheet1",
        indicator="Premium",
        period="2025-09",
        unit="unit: yuan",
        row_index=5,
        cell_ref="C5",
        row_label="Premium",
        column_header="YTD",
        raw_value="123.45",
    )

    data = chunk.to_dict()

    assert data["cell_ref"] == "C5"
    assert data["row_label"] == "Premium"
    assert data["column_header"] == "YTD"
    assert data["raw_value"] == "123.45"


def test_chunk_from_dict_ignores_unknown_fields():
    data = {
        "doc_id": "TEST-001",
        "chunk_id": "TEST-001#body",
        "text": "body text",
        "chunk_type": "clause",
        "source_title": "Test",
        "issuer": "NFRA",
        "doc_no": "",
        "publish_date": "2024-01-01",
        "section_path": [],
        "source_url": "",
        "local_path": "",
        "unknown_payload_key": "kept out",
    }

    restored = Chunk.from_dict(data)

    assert restored.doc_id == "TEST-001"
    assert not hasattr(restored, "unknown_payload_key")


def test_excel_parser_returns_cell_level_chunks(tmp_path):
    import openpyxl
    from src.parser.excel_parser import ExcelParser

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Monthly"
    sheet.append(["", "2025 September insurance report", ""])
    sheet.append(["", "", "unit: yuan"])
    sheet.append(["", "metric", "YTD"])
    sheet.append(["", "Premium income", 123.45])
    path = tmp_path / "report.xlsx"
    workbook.save(path)

    chunks = ExcelParser(
        doc_id="STAT-001",
        source_title="2025 September insurance report",
        issuer="NFRA",
        publish_date="2025-09-01",
        source_url="",
        local_path=str(path),
    ).parse()

    assert len(chunks) == 1
    assert chunks[0].chunk_type == "table_row"
    assert chunks[0].cell_ref == "C4"
    assert chunks[0].row_label == "Premium income"
    assert chunks[0].column_header == "YTD"
    assert chunks[0].raw_value == "123.45"
    assert chunks[0].unit == "unit: yuan"


def test_excel_parser_supports_xls_files(tmp_path):
    pytest.importorskip("xlrd")
    xlwt = pytest.importorskip("xlwt")
    from src.parser.excel_parser import ExcelParser

    workbook = xlwt.Workbook()
    sheet = workbook.add_sheet("Legacy")
    rows = [
        ["", "2024 legacy report", ""],
        ["", "", "unit: yuan"],
        ["", "metric", "YTD"],
        ["", "Premium income", 88.5],
    ]
    for row_idx, row in enumerate(rows):
        for col_idx, value in enumerate(row):
            sheet.write(row_idx, col_idx, value)
    path = tmp_path / "legacy.xls"
    workbook.save(str(path))

    chunks = ExcelParser(
        doc_id="STAT-002",
        source_title="2024 legacy report",
        issuer="NFRA",
        publish_date="2024-01-01",
        source_url="",
        local_path=str(path),
    ).parse()

    assert len(chunks) == 1
    assert chunks[0].cell_ref == "C4"
    assert chunks[0].row_label == "Premium income"
    assert chunks[0].column_header == "YTD"
    assert chunks[0].raw_value == "88.5"


def test_word_parser_includes_tables(tmp_path):
    from docx import Document
    from src.parser.word_parser import WordParser

    document = Document()
    document.add_heading("Chapter 1", level=1)
    document.add_paragraph("Paragraph evidence.")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Item"
    table.cell(0, 1).text = "Rule"
    table.cell(1, 0).text = "Retention"
    table.cell(1, 1).text = "Keep for 10 years"
    path = tmp_path / "test.docx"
    document.save(path)

    chunks = WordParser(
        doc_id="DOC-001",
        source_title="Rules",
        issuer="NFRA",
        doc_no="",
        publish_date="2024-01-01",
        source_url="",
        local_path=str(path),
    ).parse()

    assert any(c.chunk_type == "clause" and "Paragraph evidence" in c.text for c in chunks)
    table_chunks = [c for c in chunks if c.chunk_type == "table_row"]
    assert len(table_chunks) == 1
    assert table_chunks[0].row_label == "Retention"
    assert table_chunks[0].column_header == "Item | Rule"
    assert "Keep for 10 years" in table_chunks[0].text


def test_word_parser_rejects_doc_without_converter(tmp_path, monkeypatch):
    from src.parser.word_parser import WordParser

    path = tmp_path / "legacy.doc"
    path.write_bytes(b"\xd0\xcf\x11\xe0")
    parser = WordParser(
        doc_id="DOC-002",
        source_title="Legacy",
        issuer="NFRA",
        doc_no="",
        publish_date="2024-01-01",
        source_url="",
        local_path=str(path),
    )
    monkeypatch.setattr(parser, "_convert_doc_to_docx", lambda _: None)

    with pytest.raises(RuntimeError, match="Unable to convert .doc"):
        parser.parse()


def test_pdf_parser_returns_page_level_paragraphs(tmp_path):
    import fitz
    from src.parser.pdf_parser import PdfParser

    path = tmp_path / "test.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((50, 50), "Chapter 1 General Rules", fontsize=16)
    page.insert_text((50, 95), "Article 1 This paragraph is evidence.", fontsize=12)
    document.save(path)
    document.close()

    chunks = PdfParser(
        doc_id="PDF-001",
        source_title="PDF Rules",
        issuer="NFRA",
        doc_no="",
        publish_date="2024-01-01",
        source_url="",
        local_path=str(path),
    ).parse()

    assert len(chunks) == 1
    assert chunks[0].page_no == 1
    assert chunks[0].section_path == ["Chapter 1 General Rules"]
    assert "Article 1" in chunks[0].text
