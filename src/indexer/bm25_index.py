import json
import pickle
from pathlib import Path
from rank_bm25 import BM25Okapi


class BM25Index:
    def __init__(self, index_path: str = "data/bm25_index.pkl"):
        self.index_path = Path(index_path)
        self.bm25 = None
        self.chunks = []

    def build(self, jsonl_paths: list):
        self.chunks = []
        for path in jsonl_paths:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        self.chunks.append(json.loads(line))
        tokenized = [self._tokenize(c["text"]) for c in self.chunks]
        self.bm25 = BM25Okapi(tokenized)
        self._save()
        print(f"[BM25] 构建完成，共 {len(self.chunks)} 条")

    def load(self):
        with open(self.index_path, "rb") as f:
            data = pickle.load(f)
        self.bm25 = data["bm25"]
        self.chunks = data["chunks"]

    def search(self, query: str, top_k: int = 20) -> list:
        if self.bm25 is None:
            self.load()
        tokens = self._tokenize(query)
        scores = self.bm25.get_scores(tokens)
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
        return [{"score": float(scores[i]), **self.chunks[i]} for i in top_indices if scores[i] > 0]

    def _tokenize(self, text: str) -> list:
        tokens = []
        for char in text:
            if '一' <= char <= '鿿':
                tokens.append(char)
            elif char.strip():
                tokens.append(char)
        return tokens

    def _save(self):
        self.index_path.parent.mkdir(exist_ok=True)
        with open(self.index_path, "wb") as f:
            pickle.dump({"bm25": self.bm25, "chunks": self.chunks}, f)
