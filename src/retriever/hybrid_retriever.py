from src.indexer.qdrant_index import QdrantIndex, COLLECTION_REGULATIONS, COLLECTION_TABLES
from src.indexer.bm25_index import BM25Index
from src.retriever.router import QueryRouter
from src.retriever.reranker import Reranker


class HybridRetriever:
    def __init__(self):
        self.qdrant = QdrantIndex()
        self.bm25 = BM25Index()
        self.router = QueryRouter()
        self.reranker = Reranker()

    def retrieve(self, query: str, query_type: str = None,
                 filters: dict = None, top_k: int = 5) -> list:
        if query_type is None:
            query_type = self.router.route(query)

        if query_type == "out_of_scope":
            return []

        if query_type == "regulation":
            collections = [COLLECTION_REGULATIONS]
        elif query_type == "table":
            collections = [COLLECTION_TABLES]
        else:  # hybrid
            collections = [COLLECTION_REGULATIONS, COLLECTION_TABLES]

        vector_results = []
        for col in collections:
            vector_results += self.qdrant.search(query, col, filters=filters, top_k=20)

        bm25_results = self.bm25.search(query, top_k=20)

        merged = self._rrf_merge(vector_results, bm25_results)

        return self.reranker.rerank(query, merged, top_k=top_k)

    def _rrf_merge(self, list_a: list, list_b: list, k: int = 60) -> list:
        scores = {}
        seen = {}
        for rank, item in enumerate(list_a):
            cid = item.get("chunk_id", str(rank))
            scores[cid] = scores.get(cid, 0) + 1 / (k + rank + 1)
            seen[cid] = item
        for rank, item in enumerate(list_b):
            cid = item.get("chunk_id", str(rank))
            scores[cid] = scores.get(cid, 0) + 1 / (k + rank + 1)
            seen[cid] = item
        sorted_ids = sorted(scores, key=lambda x: scores[x], reverse=True)
        return [seen[cid] for cid in sorted_ids]
