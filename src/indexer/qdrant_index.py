import os
import json
from uuid import NAMESPACE_URL, uuid5

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct, Filter,
    FieldCondition, FilterSelector, MatchAny, MatchValue,
    OptimizersConfigDiff, PayloadSchemaType,
)
from dotenv import load_dotenv
from src.indexer.embedder import Embedder

load_dotenv()

COLLECTION_REGULATIONS = "regulations"
COLLECTION_TABLES = "tables"
VECTOR_SIZE = 1024  # BAAI/bge-large-zh-v1.5
PAYLOAD_INDEX_FIELDS = (
    "source_title",
    "chunk_type",
    "knowledge_document_id",
    "document_version_id",
)


class QdrantIndex:
    def __init__(self):
        self.client = QdrantClient(
            host=os.environ.get("QDRANT_HOST", "localhost"),
            port=int(os.environ.get("QDRANT_PORT", 6333)),
            trust_env=False,
        )
        self._embedder = None

    @property
    def embedder(self):
        if self._embedder is None:
            self._embedder = Embedder()
        return self._embedder

    @embedder.setter
    def embedder(self, value):
        self._embedder = value

    def create_collections(self):
        for name in [COLLECTION_REGULATIONS, COLLECTION_TABLES]:
            if not self.client.collection_exists(name):
                self.client.create_collection(
                    collection_name=name,
                    vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
                )
                print(f"[创建] Collection: {name}")
            self._configure_collection(name)

    def _configure_collection(self, collection_name: str) -> None:
        self.client.update_collection(
            collection_name=collection_name,
            optimizers_config=OptimizersConfigDiff(
                indexing_threshold=int(os.getenv(
                    "QDRANT_INDEXING_THRESHOLD_KB",
                    "5000",
                )),
                default_segment_number=int(os.getenv(
                    "QDRANT_DEFAULT_SEGMENT_NUMBER",
                    "2",
                )),
            ),
        )
        for field_name in PAYLOAD_INDEX_FIELDS:
            self.client.create_payload_index(
                collection_name=collection_name,
                field_name=field_name,
                field_schema=PayloadSchemaType.KEYWORD,
                wait=True,
            )

    def index_chunks(self, jsonl_path: str, collection_name: str, batch_size: int = 50):
        chunks = []
        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    chunks.append(json.loads(line))

        existing = self.client.get_collection(collection_name).points_count
        if existing >= len(chunks):
            print(f"[跳过] {collection_name}: 已有 {existing} 条，无需重建")
            return
        if existing > 0:
            print(f"[续传] {collection_name}: 已有 {existing} 条，从第 {existing + 1} 条继续")

        for i in range(existing, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            texts = [c["text"] for c in batch]
            vectors = self.embedder.embed_batch(texts)
            points = [
                PointStruct(id=idx + i, vector=vec, payload=chunk)
                for idx, (vec, chunk) in enumerate(zip(vectors, batch))
            ]
            self.client.upsert(collection_name=collection_name, points=points)
            print(f"[索引] {collection_name}: {i + len(batch)}/{len(chunks)}")

    def search(self, query: str, collection_name: str,
               filters: dict = None, top_k: int = 20) -> list:
        return self.search_by_vector(
            self.embed_query(query),
            collection_name,
            filters=filters,
            top_k=top_k,
        )

    def embed_query(self, query: str) -> list:
        return self.embedder.embed(query)

    def search_by_vector(self, query_vector: list, collection_name: str,
                         filters: dict = None, top_k: int = 20) -> list:
        qdrant_filter = self._build_filter(filters) if filters else None
        results = self.client.search(
            collection_name=collection_name,
            query_vector=query_vector,
            query_filter=qdrant_filter,
            limit=top_k,
        )
        return [{"score": r.score, **r.payload} for r in results]

    def _build_filter(self, filters: dict) -> Filter:
        conditions = []
        for key, value in filters.items():
            if value:
                if isinstance(value, (list, tuple, set)):
                    conditions.append(FieldCondition(key=key, match=MatchAny(any=list(value))))
                else:
                    conditions.append(FieldCondition(key=key, match=MatchValue(value=value)))
        return Filter(must=conditions) if conditions else None


class DocumentVectorIndex:
    """Write and validate one immutable document version in Qdrant."""

    def __init__(self, index: QdrantIndex | None = None, batch_size: int = 50):
        self.index = index or QdrantIndex()
        self.batch_size = batch_size

    def index_version(self, collection: str, chunks: list[dict]) -> list[str]:
        self.index.create_collections()
        point_ids = []
        for start in range(0, len(chunks), self.batch_size):
            batch = chunks[start:start + self.batch_size]
            vectors = self.index.embedder.embed_batch(
                [chunk["text"] for chunk in batch]
            )
            points = []
            for vector, chunk in zip(vectors, batch):
                point_id = str(uuid5(
                    NAMESPACE_URL,
                    "trusted-rag:"
                    f"{collection}:{chunk['document_version_id']}:{chunk['chunk_id']}",
                ))
                point_ids.append(point_id)
                points.append(PointStruct(
                    id=point_id,
                    vector=vector,
                    payload=chunk,
                ))
            self.index.client.upsert(
                collection_name=collection,
                points=points,
                wait=True,
            )
        return point_ids

    def validate_version(
        self,
        collection: str,
        version_id,
        expected_count: int,
    ) -> bool:
        result = self.index.client.count(
            collection_name=collection,
            count_filter=Filter(must=[FieldCondition(
                key="document_version_id",
                match=MatchValue(value=str(version_id)),
            )]),
            exact=True,
        )
        return result.count == expected_count

    def delete_version(self, version_id) -> None:
        selector = FilterSelector(filter=Filter(must=[FieldCondition(
            key="document_version_id",
            match=MatchValue(value=str(version_id)),
        )]))
        for collection in (COLLECTION_REGULATIONS, COLLECTION_TABLES):
            if self.index.client.collection_exists(collection):
                self.index.client.delete(
                    collection_name=collection,
                    points_selector=selector,
                    wait=True,
                )
