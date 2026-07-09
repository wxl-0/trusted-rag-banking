import os
import json
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct, Filter,
    FieldCondition, MatchValue,
)
from dotenv import load_dotenv
from src.indexer.embedder import Embedder

load_dotenv()

COLLECTION_REGULATIONS = "regulations"
COLLECTION_TABLES = "tables"
VECTOR_SIZE = 1024  # BAAI/bge-large-zh-v1.5


class QdrantIndex:
    def __init__(self):
        self.client = QdrantClient(
            host=os.environ.get("QDRANT_HOST", "localhost"),
            port=int(os.environ.get("QDRANT_PORT", 6333)),
        )
        self.embedder = Embedder()

    def create_collections(self):
        for name in [COLLECTION_REGULATIONS, COLLECTION_TABLES]:
            if not self.client.collection_exists(name):
                self.client.create_collection(
                    collection_name=name,
                    vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
                )
                print(f"[创建] Collection: {name}")

    def index_chunks(self, jsonl_path: str, collection_name: str, batch_size: int = 50):
        chunks = []
        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    chunks.append(json.loads(line))

        for i in range(0, len(chunks), batch_size):
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
        query_vec = self.embedder.embed(query)
        qdrant_filter = self._build_filter(filters) if filters else None
        results = self.client.search(
            collection_name=collection_name,
            query_vector=query_vec,
            query_filter=qdrant_filter,
            limit=top_k,
        )
        return [{"score": r.score, **r.payload} for r in results]

    def _build_filter(self, filters: dict) -> Filter:
        conditions = []
        for key, value in filters.items():
            if value:
                conditions.append(FieldCondition(key=key, match=MatchValue(value=value)))
        return Filter(must=conditions) if conditions else None
