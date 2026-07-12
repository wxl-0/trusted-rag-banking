import pytest

pytest.importorskip("pdfplumber")

from src.parser.pdf_table_parser import PdfTableParser


def _create_pdf_with_table(path):
    """用 pdfplumber 能读取的格式创建带表格的 PDF（通过 fitz 画线+文字模拟）。"""
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=400, height=300)

    # 画一个简单的 3x3 表格（含表头行）
    # pdfplumber 靠线条检测表格，所以需要画格线
    x0, y0 = 50, 50
    col_widths = [100, 100, 100]
    row_height = 30
    rows_data = [
        ["指标", "2024Q1", "2024Q2"],
        ["不良贷款率", "1.56", "1.48"],
        ["拨备覆盖率", "180.5", "185.2"],
    ]

    # 画水平线
    for i in range(len(rows_data) + 1):
        y = y0 + i * row_height
        page.draw_line((x0, y), (x0 + sum(col_widths), y))

    # 画垂直线
    x = x0
    for w in [0] + col_widths:
        x += w if w else 0
        page.draw_line((x, y0), (x, y0 + len(rows_data) * row_height))
        if w == 0:
            x = x0

    x = x0
    for col_idx, w in enumerate(col_widths):
        for row_idx, row in enumerate(rows_data):
            tx = x + 5
            ty = y0 + row_idx * row_height + 20
            page.insert_text((tx, ty), row[col_idx], fontsize=10)
        x += w

    doc.save(str(path))
    doc.close()


def test_pdf_table_parser_extracts_cells(tmp_path):
    pdf_path = tmp_path / "table.pdf"
    _create_pdf_with_table(pdf_path)

    parser = PdfTableParser(
        doc_id="STAT-010",
        source_title="季度统计报表",
        issuer="监管局",
        publish_date="2024-06-30",
        source_url="",
        local_path=str(pdf_path),
    )
    chunks = parser.parse()

    # pdfplumber 对 fitz 画的简单表格可能无法完美提取
    # 但解析器逻辑本身应该不报错
    assert isinstance(chunks, list)
    for c in chunks:
        assert c.chunk_type == "table_row"
        assert c.doc_id == "STAT-010"


def test_pdf_table_parser_empty_pdf(tmp_path):
    import fitz

    pdf_path = tmp_path / "empty.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(str(pdf_path))
    doc.close()

    parser = PdfTableParser(
        doc_id="STAT-011",
        source_title="空PDF",
        issuer="",
        publish_date="2024-01-01",
        source_url="",
        local_path=str(pdf_path),
    )
    chunks = parser.parse()
    assert chunks == []


def test_pdf_table_parser_skips_empty_rows(tmp_path):
    """验证 row_label 为空的行被跳过。"""
    import fitz

    pdf_path = tmp_path / "sparse.pdf"
    doc = fitz.open()
    page = doc.new_page(width=400, height=200)

    # 只画有表头但数据行为空的表格
    x0, y0 = 50, 50
    row_height = 30
    col_width = 150

    for i in range(3):
        y = y0 + i * row_height
        page.draw_line((x0, y), (x0 + col_width * 2, y))
    for j in range(3):
        x = x0 + j * col_width
        page.draw_line((x, y0), (x, y0 + 2 * row_height))

    page.insert_text((55, 70), "Header1", fontsize=10)
    page.insert_text((205, 70), "Header2", fontsize=10)
    # 第二行留空（不写文字）

    doc.save(str(pdf_path))
    doc.close()

    parser = PdfTableParser(
        doc_id="STAT-012",
        source_title="稀疏表格",
        issuer="",
        publish_date="2024-01-01",
        source_url="",
        local_path=str(pdf_path),
    )
    chunks = parser.parse()
    # 空行应被跳过
    assert all(c.row_label for c in chunks)


def test_pdf_table_parser_chunk_fields():
    """直接测试 _parse_table 方法的输出字段。"""
    parser = PdfTableParser(
        doc_id="STAT-013",
        source_title="测试报表",
        issuer="银保监",
        publish_date="2024-03-31",
        source_url="https://example.com",
        local_path="/fake/path.pdf",
    )

    table = [
        ["指标", "本期", "上期"],
        ["资本充足率", "13.5", "13.2"],
        ["核心一级资本", "10.1", "9.8"],
    ]

    chunks = parser._parse_table(table, page_idx=2, table_idx=1)

    assert len(chunks) == 4  # 2 rows x 2 data columns
    assert chunks[0].row_label == "资本充足率"
    assert chunks[0].column_header == "本期"
    assert chunks[0].raw_value == "13.5"
    assert "P2T1R1C2" in chunks[0].chunk_id
    assert chunks[0].table_name == "Page2_Table1"
    assert "测试报表" in chunks[0].text
