import json
import pickle
import re
from difflib import SequenceMatcher
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

    def search(self, query: str, top_k: int = 20, filters: dict = None) -> list:
        if self.bm25 is None:
            self.load()
        tokens = self._tokenize(query)
        scores = self.bm25.get_scores(tokens)
        candidate_indices = [
            i for i, chunk in enumerate(self.chunks)
            if self._matches_filters(chunk, filters)
        ]
        top_indices = sorted(candidate_indices, key=lambda i: scores[i], reverse=True)[:top_k]
        return [{"score": float(scores[i]), **self.chunks[i]} for i in top_indices if scores[i] > 0]

    def resolve_source_titles(self, title_hint: str) -> tuple[list[str], str]:
        if self.bm25 is None:
            self.load()
        normalized_hint = self._normalize_title(title_hint)
        if not normalized_hint:
            return [], "none"

        titles = list(dict.fromkeys(
            chunk.get("source_title", "") for chunk in self.chunks
            if chunk.get("source_title")
        ))
        exact = [title for title in titles if self._normalize_title(title) == normalized_hint]
        if exact:
            return exact, "exact"

        near = [
            title for title in titles
            if normalized_hint in self._normalize_title(title)
            or self._normalize_title(title) in normalized_hint
        ]
        near.sort(key=lambda title: abs(len(self._normalize_title(title)) - len(normalized_hint)))
        if near:
            return near[:5], "near"

        alias_hint = self._normalize_title_alias(title_hint)
        alias_matches = [
            title for title in titles
            if self._titles_overlap(alias_hint, self._normalize_title_alias(title))
        ]
        if len(alias_matches) == 1:
            return alias_matches, "alias"

        scored = sorted(
            (
                SequenceMatcher(
                    None,
                    alias_hint,
                    self._normalize_title_alias(title),
                ).ratio(),
                title,
            )
            for title in titles
        )
        if scored:
            best_score, best_title = scored[-1]
            second_score = scored[-2][0] if len(scored) > 1 else 0
            if best_score >= 0.78 and best_score - second_score >= 0.08:
                return [best_title], "alias"
        return [], "none"

    def chunks_for_source_titles(self, titles: list, filters: dict = None,
                                 max_chunks: int = 20) -> list:
        if self.bm25 is None:
            self.load()
        if not titles:
            return []
        scoped_filters = dict(filters or {})
        scoped_filters["source_title"] = titles
        matches = []
        seen = set()
        for chunk in self.chunks:
            if not self._matches_filters(chunk, scoped_filters):
                continue
            chunk_id = chunk.get("chunk_id")
            if chunk_id and chunk_id in seen:
                continue
            if chunk_id:
                seen.add(chunk_id)
            matches.append(chunk)
            if len(matches) > max_chunks:
                return []
        return matches

    def related_chunks(self, chunks: list, max_extra: int = 2) -> list:
        if self.bm25 is None:
            self.load()
        index_by_id = {
            chunk.get("chunk_id"): index
            for index, chunk in enumerate(self.chunks)
            if chunk.get("chunk_id")
        }
        selected_ids = {chunk.get("chunk_id") for chunk in chunks}
        related = []
        for chunk in chunks:
            index = index_by_id.get(chunk.get("chunk_id"))
            if index is None:
                continue
            for offset in (-1, 1, -2, 2):
                neighbor_index = index + offset
                if not 0 <= neighbor_index < len(self.chunks):
                    continue
                neighbor = self.chunks[neighbor_index]
                if neighbor.get("chunk_id") in selected_ids:
                    continue
                if not self._same_context(chunk, neighbor):
                    continue
                related.append(neighbor)
                selected_ids.add(neighbor.get("chunk_id"))
                if len(related) >= max_extra:
                    return related
        return related

    def _matches_filters(self, chunk: dict, filters: dict = None) -> bool:
        if not filters:
            return True
        for key, expected in filters.items():
            if expected in (None, "", []):
                continue
            actual = chunk.get(key)
            if isinstance(actual, (list, tuple, set)):
                if isinstance(expected, (list, tuple, set)):
                    if not set(actual).intersection(expected):
                        return False
                elif expected not in actual:
                    return False
            elif isinstance(expected, (list, tuple, set)):
                if actual not in expected:
                    return False
            elif actual != expected:
                return False
        return True

    def _same_context(self, chunk: dict, neighbor: dict) -> bool:
        if chunk.get("doc_id") != neighbor.get("doc_id"):
            return False
        parent_id = chunk.get("parent_chunk_id")
        if parent_id and parent_id == neighbor.get("parent_chunk_id"):
            return True
        section_path = chunk.get("section_path")
        return bool(section_path and section_path == neighbor.get("section_path"))

    def _normalize_title(self, title: str) -> str:
        return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(title).lower())

    def _normalize_title_alias(self, title: str) -> str:
        normalized = self._normalize_title(title)
        normalized = re.sub(r"20\d{2}年版", "", normalized)
        normalized = normalized.replace("财产保险公司", "财产险公司")
        normalized = normalized.replace("人身保险公司", "人身险公司")
        return re.sub(r"(?:pdf|word|excel|docx?|xlsx?)$", "", normalized)

    def _titles_overlap(self, left: str, right: str) -> bool:
        return bool(
            min(len(left), len(right)) >= 8
            and (left in right or right in left)
        )

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
