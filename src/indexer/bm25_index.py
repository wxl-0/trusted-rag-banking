import json
import hashlib
import pickle
import re
from difflib import SequenceMatcher
from pathlib import Path
from uuid import uuid4

from rank_bm25 import BM25Okapi
from sqlalchemy import text

from src.database import Database, DatabaseNotConfigured, get_database


class BM25Index:
    def __init__(self, index_path: str = "data/bm25_index.pkl"):
        self.index_path = Path(index_path)
        self.bm25 = None
        self.chunks = []

    def build(self, jsonl_paths: list):
        chunks = []
        for path in jsonl_paths:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        chunks.append(json.loads(line))
        self.build_from_chunks(chunks)

    def build_from_chunks(self, chunks: list[dict]):
        self.chunks = list(chunks)
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
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.index_path, "wb") as f:
            pickle.dump({"bm25": self.bm25, "chunks": self.chunks}, f)


class BM25GenerationManager:
    def __init__(
        self,
        database: Database,
        generation_dir: str = "data/bm25_generations",
        legacy_path: str = "data/bm25_index.pkl",
        chunk_paths: tuple[str, ...] = (
            "data/chunks/clause_chunks.jsonl",
            "data/chunks/table_chunks.jsonl",
        ),
    ):
        self.database = database
        self.generation_dir = Path(generation_dir)
        self.legacy_path = Path(legacy_path)
        self.chunk_paths = tuple(Path(path) for path in chunk_paths)

    def build_candidate(
        self,
        document_id,
        version_id,
        chunks: list[dict],
    ) -> dict:
        generation_id = uuid4()
        path = self.generation_dir / f"{generation_id}.pkl"
        baseline = [
            chunk for chunk in self._active_chunks()
            if str(chunk.get("knowledge_document_id", "")) != str(document_id)
        ]
        index = BM25Index(str(path))
        index.build_from_chunks(baseline + chunks)
        return {
            "id": generation_id,
            "artifact_path": str(path),
            "checksum_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "chunk_count": len(index.chunks),
        }

    def validate_candidate(
        self,
        generation: dict,
        version_id,
        expected_count: int,
    ) -> bool:
        path = Path(generation["artifact_path"])
        if not path.is_file():
            return False
        if hashlib.sha256(path.read_bytes()).hexdigest() != generation["checksum_sha256"]:
            return False
        index = BM25Index(str(path))
        index.load()
        version_count = sum(
            str(chunk.get("document_version_id", "")) == str(version_id)
            for chunk in index.chunks
        )
        return (
            len(index.chunks) == generation["chunk_count"]
            and version_count == expected_count
        )

    def _active_chunks(self) -> list[dict]:
        with self.database.session() as session:
            active_path = session.execute(text("""
                SELECT generation.artifact_path
                FROM knowledge_index_state AS state
                JOIN bm25_generations AS generation
                  ON generation.id = state.active_bm25_generation_id
                WHERE state.id = 1
            """)).scalar_one_or_none()
        if active_path and Path(active_path).is_file():
            index = BM25Index(active_path)
            index.load()
            return index.chunks
        if self.legacy_path.is_file():
            index = BM25Index(str(self.legacy_path))
            index.load()
            return index.chunks
        chunks = []
        for path in self.chunk_paths:
            if not path.is_file():
                continue
            with path.open(encoding="utf-8") as source:
                chunks.extend(
                    json.loads(line)
                    for line in source
                    if line.strip()
                )
        return chunks


class PublishedBM25Index:
    """Reload the BM25 generation selected by PostgreSQL when it changes."""

    def __init__(
        self,
        database: Database | None = None,
        legacy_path: str = "data/bm25_index.pkl",
    ):
        self.database = database or get_database()
        self.legacy_path = legacy_path
        self._generation_key = None
        self._index = BM25Index(legacy_path)

    def _refresh(self) -> None:
        try:
            with self.database.session() as session:
                row = session.execute(text("""
                    SELECT generation.id, generation.artifact_path
                    FROM knowledge_index_state AS state
                    JOIN bm25_generations AS generation
                      ON generation.id = state.active_bm25_generation_id
                    WHERE state.id = 1
                      AND generation.published_at IS NOT NULL
                """)).mappings().one_or_none()
        except DatabaseNotConfigured:
            row = None
        key = str(row["id"]) if row else "legacy"
        path = row["artifact_path"] if row else self.legacy_path
        if key == self._generation_key:
            return
        self._index = BM25Index(path)
        self._generation_key = key

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        self._refresh()
        return getattr(self._index, name)
