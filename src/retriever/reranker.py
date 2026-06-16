from sentence_transformers import CrossEncoder
import os
from dotenv import load_dotenv

load_dotenv()


class Reranker:
    def __init__(self):
        model_name = os.environ.get("RERANKER_MODEL", "BAAI/bge-reranker-base")
        self.model = CrossEncoder(model_name)

    def rerank(self, query: str, chunks: list, top_k: int = 5) -> list:
        if not chunks:
            return []
        pairs = [(query, c["text"]) for c in chunks]
        scores = self.model.predict(pairs)
        ranked = sorted(zip(scores, chunks), key=lambda x: x[0], reverse=True)
        return [chunk for _, chunk in ranked[:top_k]]
