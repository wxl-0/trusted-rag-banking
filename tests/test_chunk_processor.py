import pytest
from src.parser.base import Chunk
from src.parser.chunk_processor import process_chunks, split_sub_clauses, split_by_max_length


def _make_clause(text: str, doc_id: str = "T-001", section_path=None) -> Chunk:
    return Chunk(
        doc_id=doc_id,
        chunk_id=f"{doc_id}#body",
        text=text,
        chunk_type="clause",
        source_title="测试文件",
        issuer="测试",
        doc_no="",
        publish_date="2024-01-01",
        section_path=section_path or [],
        source_url="",
        local_path="",
    )


def _make_table_row(text: str) -> Chunk:
    return Chunk(
        doc_id="T-001",
        chunk_id="T-001#Sheet1#R1",
        text=text,
        chunk_type="table_row",
        source_title="测试表",
        issuer="测试",
        doc_no="",
        publish_date="2024-01-01",
        section_path=[],
        source_url="",
        local_path="",
        table_name="Sheet1",
        row_label="指标A",
    )


class TestProcessChunksRegulation:
    def test_sub_clause_split_enabled(self):
        text = "（一）第一款内容。（二）第二款内容。"
        chunks = process_chunks([_make_clause(text)], profile="regulation")
        texts = [c.text for c in chunks]
        assert any("第一款" in t for t in texts)
        assert any("第二款" in t for t in texts)

    def test_long_text_split_at_600(self):
        text = "本条规定如下。" * 200  # > 600 chars
        chunks = process_chunks([_make_clause(text)], profile="regulation")
        assert all(len(c.text) <= 700 for c in chunks)  # 600 + overlap margin

    def test_table_row_passed_through(self):
        table = _make_table_row("表格数据")
        clause = _make_clause("条款内容短")
        result = process_chunks([clause, table], profile="regulation")
        table_results = [c for c in result if c.chunk_type == "table_row"]
        assert len(table_results) == 1
        assert table_results[0].text == "表格数据"

    def test_min_length_filter(self):
        short = _make_clause("短")
        normal = _make_clause("这是一条足够长的正常条款内容。")
        result = process_chunks([short, normal], profile="regulation")
        clause_results = [c for c in result if c.chunk_type == "clause"]
        assert all(len(c.text) >= 10 for c in clause_results)


class TestProcessChunksReport:
    def test_no_sub_clause_split(self):
        text = "（一）第一段落。（二）第二段落。"
        chunks = process_chunks([_make_clause(text)], profile="report")
        clause_chunks = [c for c in chunks if c.chunk_type == "clause"]
        # report profile 不切子条款，所以输出仍包含完整文本
        combined = "".join(c.text for c in clause_chunks)
        assert "第一段落" in combined and "第二段落" in combined

    def test_long_text_split_at_800(self):
        text = "本年度报告内容。" * 200  # > 800 chars
        chunks = process_chunks([_make_clause(text)], profile="report")
        assert all(len(c.text) <= 900 for c in chunks)  # 800 + overlap margin

    def test_english_punctuation_split(self):
        # report profile 支持英文句号作为切分点
        text = "This is a long annual report sentence. " * 30
        chunks = process_chunks([_make_clause(text)], profile="report")
        if len(text) > 800:
            assert len(chunks) >= 2


class TestContextEnrichment:
    def test_prefix_includes_source_title(self):
        chunk = _make_clause("条款正文", section_path=["第一章"])
        result = process_chunks([chunk], profile="regulation")
        clause_results = [c for c in result if c.chunk_type == "clause"]
        assert any("《测试文件》" in c.text for c in clause_results)

    def test_prefix_includes_section_path(self):
        chunk = _make_clause("条款正文内容足够长度通过过滤器。", section_path=["第一章", "第一节"])
        result = process_chunks([chunk], profile="regulation")
        clause_results = [c for c in result if c.chunk_type == "clause"]
        assert any("第一章 > 第一节" in c.text for c in clause_results)
