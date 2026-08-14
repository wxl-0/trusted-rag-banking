import json
import stat
from types import SimpleNamespace

from openpyxl import Workbook
from qdrant_client.models import PointStruct

from scripts.ingest import parse_manifest_entry
from scripts.update_documents import (
    make_point_id,
    prepare_document_updates,
    replace_file_preserving_mode,
    replace_qdrant_document,
    rewrite_jsonl_documents,
    scroll_qdrant_document,
)


def _chunk(doc_id: str, chunk_id: str, text: str) -> dict:
    return {
        "doc_id": doc_id,
        "chunk_id": chunk_id,
        "text": text,
        "chunk_type": "table_row",
    }


def test_rewrite_jsonl_documents_only_replaces_requested_docs(tmp_path):
    source = tmp_path / "table_chunks.jsonl"
    source.write_text(
        "\n".join(
            json.dumps(chunk, ensure_ascii=False)
            for chunk in [
                _chunk("D1", "D1#old-1", "旧内容一"),
                _chunk("D2", "D2#stable", "保持不变"),
                _chunk("D1", "D1#old-2", "旧内容二"),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = rewrite_jsonl_documents(
        source,
        {"D1": [
            _chunk("D1", "D1#new-1", "新内容一"),
            _chunk("D1", "D1#new-2", "新内容二"),
        ]},
    )

    rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()]
    assert rows == [
        _chunk("D1", "D1#new-1", "新内容一"),
        _chunk("D1", "D1#new-2", "新内容二"),
        _chunk("D2", "D2#stable", "保持不变"),
    ]
    assert summary == {"D1": {"before": 2, "after": 2}}


def test_rewrite_jsonl_documents_preserves_non_target_lines_byte_for_byte(tmp_path):
    source = tmp_path / "table_chunks.jsonl"
    stable_line = '{"doc_id":"D2", "chunk_id":"D2#stable", "text":"保持原格式"}'
    source.write_text(
        json.dumps(_chunk("D1", "D1#old", "旧内容"), ensure_ascii=False)
        + "\n"
        + stable_line
        + "\n",
        encoding="utf-8",
    )

    rewrite_jsonl_documents(
        source,
        {"D1": [_chunk("D1", "D1#new", "新内容")]},
    )

    assert stable_line in source.read_text(encoding="utf-8").splitlines()


def test_make_point_id_is_stable_and_scoped():
    first = make_point_id("tables", "D1", "D1#cell-B6")

    assert first == make_point_id("tables", "D1", "D1#cell-B6")
    assert first != make_point_id("regulations", "D1", "D1#cell-B6")
    assert first != make_point_id("tables", "D2", "D1#cell-B6")


def test_parse_manifest_entry_returns_target_collection(tmp_path):
    workbook_path = tmp_path / "sample.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "季度数据"
    sheet.append(["指标", "一季度"])
    sheet.append(["总资产", 100])
    workbook.save(workbook_path)

    collection, chunks = parse_manifest_entry({
        "doc_id": "D-TABLE",
        "title": "季度测试表",
        "notice_title": "2023年季度测试",
        "issuer": "测试机构",
        "doc_no": "",
        "publish_date": "2023-01-01",
        "source_url": "",
        "local_path": str(workbook_path),
        "parse_profile": "data",
    })

    assert collection == "tables"
    assert len(chunks) == 1
    assert chunks[0].doc_id == "D-TABLE"
    assert chunks[0].source_title == "2023年季度测试"
    assert chunks[0].raw_value == "100"


class _MemoryQdrant:
    def __init__(self, records):
        self.records = list(records)
        self.upsert_batches = []

    @staticmethod
    def _doc_id(qdrant_filter):
        return qdrant_filter.must[0].match.value

    def scroll(self, collection_name, scroll_filter, offset=None, **kwargs):
        doc_id = self._doc_id(scroll_filter)
        records = [record for record in self.records if record.payload["doc_id"] == doc_id]
        return records, None

    def delete(self, collection_name, points_selector, wait):
        doc_id = self._doc_id(points_selector.filter)
        self.records = [record for record in self.records if record.payload["doc_id"] != doc_id]

    def upsert(self, collection_name, points, wait):
        self.upsert_batches.append(list(points))
        self.records.extend(
            SimpleNamespace(id=point.id, payload=point.payload, vector=point.vector)
            for point in points
        )


def test_replace_qdrant_document_keeps_other_documents():
    client = _MemoryQdrant([
        SimpleNamespace(id=1, payload=_chunk("D1", "D1#old", "旧内容"), vector=[0.1]),
        SimpleNamespace(id=2, payload=_chunk("D2", "D2#stable", "保持不变"), vector=[0.2]),
    ])
    new_point = PointStruct(
        id=make_point_id("tables", "D1", "D1#new"),
        vector=[0.3],
        payload=_chunk("D1", "D1#new", "新内容"),
    )

    summary = replace_qdrant_document(client, "tables", "D1", [new_point])

    assert summary == {"before": 1, "after": 1}
    assert [point["payload"]["chunk_id"] for point in scroll_qdrant_document(
        client, "tables", "D1",
    )] == ["D1#new"]
    assert [record.payload["chunk_id"] for record in client.records if record.payload["doc_id"] == "D2"] == ["D2#stable"]


def test_replace_qdrant_document_upserts_large_updates_in_batches():
    client = _MemoryQdrant([])
    points = [
        PointStruct(
            id=make_point_id("tables", "D1", f"D1#new-{index}"),
            vector=[float(index)],
            payload=_chunk("D1", f"D1#new-{index}", f"new content {index}"),
        )
        for index in range(130)
    ]

    summary = replace_qdrant_document(client, "tables", "D1", points)

    assert summary == {"before": 0, "after": 130}
    assert [len(batch) for batch in client.upsert_batches] == [64, 64, 2]


def test_replace_qdrant_document_allows_empty_replacement():
    client = _MemoryQdrant([
        SimpleNamespace(id=1, payload=_chunk("D1", "D1#old", "old content"), vector=[0.1]),
        SimpleNamespace(id=2, payload=_chunk("D2", "D2#stable", "stable content"), vector=[0.2]),
    ])

    summary = replace_qdrant_document(client, "tables", "D1", [])

    assert summary == {"before": 1, "after": 0}
    assert client.upsert_batches == []
    assert [record.payload["doc_id"] for record in client.records] == ["D2"]


def test_prepare_document_updates_selects_scope_and_avoids_global_text_duplicates(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps([
        {"doc_id": "D1", "local_path": "unused.xlsx"},
        {"doc_id": "D2", "local_path": "unused.xlsx"},
    ]), encoding="utf-8")
    clause_path = tmp_path / "clause_chunks.jsonl"
    clause_path.write_text("", encoding="utf-8")
    table_path = tmp_path / "table_chunks.jsonl"
    table_path.write_text(
        json.dumps(_chunk("D1", "D1#old", "旧内容"), ensure_ascii=False)
        + "\n"
        + json.dumps(_chunk("D2", "D2#stable", "已由其他文档保留"), ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )

    def parse_entry(entry):
        assert entry["doc_id"] == "D1"
        return "tables", [
            SimpleNamespace(to_dict=lambda: _chunk("D1", "D1#duplicate", "已由其他文档保留")),
            SimpleNamespace(to_dict=lambda: _chunk("D1", "D1#new", "新增内容")),
        ]

    updates = prepare_document_updates(
        ["D1"],
        manifest_path=manifest_path,
        clause_path=clause_path,
        table_path=table_path,
        parse_entry=parse_entry,
    )

    assert updates == {
        "D1": {
            "collection": "tables",
            "chunks": [_chunk("D1", "D1#new", "新增内容")],
            "skipped_duplicate_texts": 1,
        },
    }


def test_replace_file_preserving_mode_handles_read_only_destination(tmp_path):
    destination = tmp_path / "index.pkl"
    destination.write_text("old", encoding="utf-8")
    destination.chmod(stat.S_IREAD)
    source = tmp_path / "index.pkl.tmp"
    source.write_text("new", encoding="utf-8")

    replace_file_preserving_mode(source, destination)

    assert destination.read_text(encoding="utf-8") == "new"
    assert not destination.stat().st_mode & stat.S_IWRITE
