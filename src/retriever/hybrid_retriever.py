import time

from src.indexer.qdrant_index import QdrantIndex, COLLECTION_REGULATIONS, COLLECTION_TABLES
from src.indexer.bm25_index import BM25Index
from src.retriever.router import QueryRouter
from src.retriever.reranker import Reranker

CANDIDATES_PER_CHANNEL = 12
MAX_RERANK_CANDIDATES = 24


class HybridRetriever:
    def __init__(self, qdrant=None, bm25=None, router=None, reranker=None):
        self.qdrant = qdrant or QdrantIndex()
        self.bm25 = bm25 or BM25Index()
        self.router = router or QueryRouter()
        self.reranker = reranker or Reranker()
        self.last_diagnostics = {}

    def retrieve(self, query: str, query_type: str = None,
                 filters: dict = None, top_k: int = 5,
                 title_hint: str = None, full_source: bool = False) -> list:
        total_start = time.perf_counter()
        if query_type is None:
            query_type = self.router.route(query)

        if query_type == "out_of_scope":
            self.last_diagnostics = {
                "route": query_type,
                "strategy": "none",
                "title_hint": title_hint or "",
                "title_match": "none",
                "matched_titles": [],
                "candidate_counts": {"vector": 0, "bm25": 0, "merged": 0, "final": 0},
                "timing_ms": {"total": int((time.perf_counter() - total_start) * 1000)},
            }
            return []

        if query_type == "regulation":
            collections = [COLLECTION_REGULATIONS]
        elif query_type == "table":
            collections = [COLLECTION_TABLES]
        else:  # hybrid
            collections = [COLLECTION_REGULATIONS, COLLECTION_TABLES]

        effective_filters = dict(filters or {})
        matched_titles = []
        title_match = "none"
        if title_hint and "source_title" not in effective_filters:
            matched_titles, title_match = self.bm25.resolve_source_titles(title_hint)
            if matched_titles and title_match in {"exact", "near", "alias"}:
                effective_filters["source_title"] = (
                    matched_titles[0] if len(matched_titles) == 1 else matched_titles
                )

        if full_source and len(matched_titles) == 1:
            source_filters = dict(effective_filters)
            source_filters.pop("source_title", None)
            if query_type == "regulation":
                source_filters["chunk_type"] = "clause"
            elif query_type == "table":
                source_filters["chunk_type"] = "table_row"
            source_chunks = self.bm25.chunks_for_source_titles(
                matched_titles,
                filters=source_filters or None,
                max_chunks=20,
            )
            if source_chunks:
                total_ms = int((time.perf_counter() - total_start) * 1000)
                self.last_diagnostics = {
                    "route": query_type,
                    "strategy": "full_source",
                    "title_hint": title_hint or "",
                    "title_match": title_match,
                    "matched_titles": matched_titles,
                    "filters": {**source_filters, "source_title": matched_titles[0]},
                    "candidate_counts": {
                        "vector": 0,
                        "bm25": 0,
                        "preferred_vector": 0,
                        "preferred_bm25": 0,
                        "merged": len(source_chunks),
                        "context_added": 0,
                        "final": len(source_chunks),
                    },
                    "timing_ms": {
                        "vector": 0,
                        "bm25": 0,
                        "fusion": 0,
                        "rerank": 0,
                        "total": total_ms,
                    },
                }
                return source_chunks

        vector_start = time.perf_counter()
        vector_results = []
        for col in collections:
            vector_results += self.qdrant.search(
                query, col, filters=effective_filters or None,
                top_k=CANDIDATES_PER_CHANNEL,
            )[:CANDIDATES_PER_CHANNEL]
        preferred_vector_results = []
        vector_ms = int((time.perf_counter() - vector_start) * 1000)

        bm25_filters = dict(effective_filters)
        if query_type == "regulation":
            bm25_filters["chunk_type"] = "clause"
        elif query_type == "table":
            bm25_filters["chunk_type"] = "table_row"
        bm25_start = time.perf_counter()
        bm25_results = self.bm25.search(
            query, top_k=CANDIDATES_PER_CHANNEL,
            filters=bm25_filters or None,
        )[:CANDIDATES_PER_CHANNEL]
        preferred_bm25_results = []
        bm25_ms = int((time.perf_counter() - bm25_start) * 1000)

        merge_start = time.perf_counter()
        merged = self._rrf_merge(
            vector_results, bm25_results
        )[:MAX_RERANK_CANDIDATES]
        merge_ms = int((time.perf_counter() - merge_start) * 1000)

        rerank_start = time.perf_counter()
        ranked = self.reranker.rerank(query, merged, top_k=top_k)
        context_chunks = []
        if query_type == "regulation" and ranked and top_k > 1:
            context_limit = min(2, max(1, top_k // 4))
            context_chunks = self.bm25.related_chunks(ranked, max_extra=context_limit)
            if context_chunks:
                direct_limit = max(1, top_k - len(context_chunks))
                ranked = ranked[:direct_limit] + context_chunks
        ranked = ranked[:top_k]
        rerank_ms = int((time.perf_counter() - rerank_start) * 1000)

        self.last_diagnostics = {
            "route": query_type,
            "strategy": "hybrid",
            "title_hint": title_hint or "",
            "title_match": title_match,
            "matched_titles": matched_titles,
            "filters": effective_filters,
            "candidate_counts": {
                "vector": len(vector_results),
                "bm25": len(bm25_results),
                "preferred_vector": len(preferred_vector_results),
                "preferred_bm25": len(preferred_bm25_results),
                "merged": len(merged),
                "context_added": len(context_chunks),
                "final": len(ranked),
            },
            "timing_ms": {
                "vector": vector_ms,
                "bm25": bm25_ms,
                "fusion": merge_ms,
                "rerank": rerank_ms,
                "total": int((time.perf_counter() - total_start) * 1000),
            },
        }
        return ranked

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
