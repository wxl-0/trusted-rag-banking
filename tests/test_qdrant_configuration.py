from unittest.mock import MagicMock

from src.indexer.qdrant_index import (
    COLLECTION_REGULATIONS,
    COLLECTION_TABLES,
    QdrantIndex,
)


def test_create_collections_applies_optimizer_and_payload_indexes(monkeypatch):
    monkeypatch.setenv("QDRANT_INDEXING_THRESHOLD_KB", "5000")
    monkeypatch.setenv("QDRANT_DEFAULT_SEGMENT_NUMBER", "2")
    index = QdrantIndex.__new__(QdrantIndex)
    index.client = MagicMock()
    index.client.collection_exists.side_effect = [True, False]

    index.create_collections()

    index.client.create_collection.assert_called_once()
    assert index.client.create_collection.call_args.kwargs["collection_name"] == (
        COLLECTION_TABLES
    )
    assert [
        call.kwargs["collection_name"]
        for call in index.client.update_collection.call_args_list
    ] == [COLLECTION_REGULATIONS, COLLECTION_TABLES]
    for call in index.client.update_collection.call_args_list:
        optimizer = call.kwargs["optimizers_config"]
        assert optimizer.indexing_threshold == 5000
        assert optimizer.default_segment_number == 2

    assert index.client.create_payload_index.call_count == 8
    assert {
        call.kwargs["field_name"]
        for call in index.client.create_payload_index.call_args_list
    } == {
        "source_title",
        "chunk_type",
        "knowledge_document_id",
        "document_version_id",
    }
    assert all(
        call.kwargs["wait"] is True
        for call in index.client.create_payload_index.call_args_list
    )
