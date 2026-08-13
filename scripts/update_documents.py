#!/usr/bin/env python
"""Safely replace selected documents in chunks and retrieval indexes."""

import argparse
import hashlib
import json
import os
import shutil
import stat
import sys
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.models import (
    FieldCondition,
    Filter,
    FilterSelector,
    MatchValue,
    PointStruct,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
load_dotenv(REPO_ROOT / ".env")

MANIFEST_PATH = REPO_ROOT / "data/manifest.json"
CLAUSE_PATH = REPO_ROOT / "data/chunks/clause_chunks.jsonl"
TABLE_PATH = REPO_ROOT / "data/chunks/table_chunks.jsonl"
BM25_PATH = REPO_ROOT / "data/bm25_index.pkl"
BACKUP_ROOT = REPO_ROOT / "data/chunks/document_update_backups"


def make_point_id(collection: str, doc_id: str, chunk_id: str) -> str:
    key = f"trusted-rag-banking/{collection}/{doc_id}/{chunk_id}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, key))


def _doc_filter(doc_id: str) -> Filter:
    return Filter(must=[
        FieldCondition(key="doc_id", match=MatchValue(value=doc_id)),
    ])


def scroll_qdrant_document(client, collection: str, doc_id: str) -> list[dict]:
    records: list[dict] = []
    offset = None
    while True:
        batch, offset = client.scroll(
            collection_name=collection,
            scroll_filter=_doc_filter(doc_id),
            limit=256,
            offset=offset,
            with_payload=True,
            with_vectors=True,
        )
        records.extend({
            "id": record.id,
            "payload": record.payload,
            "vector": record.vector,
        } for record in batch)
        if offset is None:
            return records


def replace_qdrant_document(
    client,
    collection: str,
    doc_id: str,
    points: list[PointStruct],
) -> dict[str, int]:
    before = scroll_qdrant_document(client, collection, doc_id)
    client.delete(
        collection_name=collection,
        points_selector=FilterSelector(filter=_doc_filter(doc_id)),
        wait=True,
    )
    if points:
        client.upsert(collection_name=collection, points=points, wait=True)

    after = scroll_qdrant_document(client, collection, doc_id)
    expected_ids = {point.payload["chunk_id"] for point in points}
    actual_ids = {record["payload"]["chunk_id"] for record in after}
    if len(after) != len(points) or actual_ids != expected_ids:
        raise RuntimeError(
            f"Qdrant verification failed for {doc_id}: "
            f"expected {len(points)}, found {len(after)}"
        )
    return {"before": len(before), "after": len(after)}


def _read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def prepare_document_updates(
    doc_ids: list[str],
    *,
    manifest_path: Path = MANIFEST_PATH,
    clause_path: Path = CLAUSE_PATH,
    table_path: Path = TABLE_PATH,
    parse_entry=None,
) -> dict[str, dict]:
    if not doc_ids or len(set(doc_ids)) != len(doc_ids):
        raise ValueError("doc_ids must be non-empty and unique")
    if parse_entry is None:
        from scripts.ingest import parse_manifest_entry
        parse_entry = parse_manifest_entry

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    target_ids = set(doc_ids)
    entries = [entry for entry in manifest if entry.get("doc_id") in target_ids]
    found_ids = {entry["doc_id"] for entry in entries}
    missing = target_ids - found_ids
    if missing:
        raise ValueError(f"doc_id not found in manifest: {sorted(missing)}")

    clause_rows = _read_jsonl(clause_path)
    table_rows = _read_jsonl(table_path)
    retained_texts = {
        row.get("text", "")
        for row in clause_rows + table_rows
        if row.get("doc_id") not in target_ids
    }
    locations = {
        doc_id: {
            "regulations": sum(row.get("doc_id") == doc_id for row in clause_rows),
            "tables": sum(row.get("doc_id") == doc_id for row in table_rows),
        }
        for doc_id in doc_ids
    }

    updates: dict[str, dict] = {}
    seen_texts = set(retained_texts)
    for entry in entries:
        doc_id = entry["doc_id"]
        collection, parsed_chunks = parse_entry(entry)
        if collection not in {"regulations", "tables"}:
            raise ValueError(f"{doc_id} cannot be indexed: collection={collection}")
        other_collection = "tables" if collection == "regulations" else "regulations"
        if locations[doc_id][other_collection]:
            raise ValueError(
                f"{doc_id} unexpectedly exists in {other_collection}: "
                f"{locations[doc_id][other_collection]} chunks"
            )
        if not locations[doc_id][collection]:
            raise ValueError(f"{doc_id} has no existing chunks in {collection}")

        chunks: list[dict] = []
        skipped = 0
        for chunk in parsed_chunks:
            payload = chunk.to_dict()
            if payload.get("doc_id") != doc_id:
                raise ValueError(f"Parser returned a foreign doc_id for {doc_id}")
            text = payload.get("text", "")
            if text in seen_texts:
                skipped += 1
                continue
            seen_texts.add(text)
            chunks.append(payload)
        if not chunks:
            raise ValueError(f"Parser returned no unique chunks for {doc_id}")
        chunk_ids = [chunk.get("chunk_id") for chunk in chunks]
        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError(f"Parser returned duplicate chunk_id values for {doc_id}")
        updates[doc_id] = {
            "collection": collection,
            "chunks": chunks,
            "skipped_duplicate_texts": skipped,
        }
    return updates


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def replace_file_preserving_mode(source: Path, destination: Path) -> None:
    destination_mode = stat.S_IMODE(destination.stat().st_mode) if destination.exists() else None
    if destination_mode is not None and not destination_mode & stat.S_IWRITE:
        destination.chmod(destination_mode | stat.S_IWRITE)
    try:
        os.replace(source, destination)
    finally:
        if destination.exists() and destination_mode is not None:
            destination.chmod(destination_mode)


def _copy_file_overwrite(source: Path, destination: Path) -> None:
    destination_mode = stat.S_IMODE(destination.stat().st_mode) if destination.exists() else None
    if destination_mode is not None and not destination_mode & stat.S_IWRITE:
        destination.chmod(destination_mode | stat.S_IWRITE)
    try:
        shutil.copy2(source, destination)
    except Exception:
        if destination.exists() and destination_mode is not None:
            destination.chmod(destination_mode)
        raise


def _non_target_digest(path: Path, target_ids: set[str]) -> str:
    digest = hashlib.sha256()
    for raw_line in path.read_bytes().splitlines(keepends=True):
        payload = raw_line.rstrip(b"\r\n")
        if not payload:
            digest.update(raw_line)
            continue
        row = json.loads(payload.decode("utf-8"))
        if row.get("doc_id") not in target_ids:
            digest.update(raw_line)
    return digest.hexdigest()


def _chunk_counts(path: Path, doc_ids: set[str]) -> dict[str, int]:
    counts = Counter(
        row.get("doc_id") for row in _read_jsonl(path)
        if row.get("doc_id") in doc_ids
    )
    return {doc_id: counts[doc_id] for doc_id in doc_ids}


def _new_qdrant_client() -> QdrantClient:
    return QdrantClient(
        host=os.environ.get("QDRANT_HOST", "localhost"),
        port=int(os.environ.get("QDRANT_PORT", 6333)),
        trust_env=False,
    )


def _inspect_qdrant(client, updates: dict[str, dict]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for doc_id, update in updates.items():
        collection = update["collection"]
        other = "tables" if collection == "regulations" else "regulations"
        expected_points = scroll_qdrant_document(client, collection, doc_id)
        unexpected_points = scroll_qdrant_document(client, other, doc_id)
        if unexpected_points:
            raise RuntimeError(
                f"{doc_id} unexpectedly has {len(unexpected_points)} Qdrant points in {other}"
            )
        result[doc_id] = {
            "collection": collection,
            "before": len(expected_points),
            "after": len(update["chunks"]),
        }
    return result


def _create_backup(
    doc_ids: list[str],
    updates: dict[str, dict],
    client,
) -> tuple[Path, dict[str, list[dict]]]:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = BACKUP_ROOT / f"{stamp}-{uuid.uuid4().hex[:8]}"
    backup_dir.mkdir(parents=True)

    shutil.copy2(CLAUSE_PATH, backup_dir / CLAUSE_PATH.name)
    shutil.copy2(TABLE_PATH, backup_dir / TABLE_PATH.name)
    if BM25_PATH.exists():
        shutil.copy2(BM25_PATH, backup_dir / BM25_PATH.name)

    qdrant_backup: dict[str, list[dict]] = {}
    new_chunks_dir = backup_dir / "new_chunks"
    new_chunks_dir.mkdir()
    for doc_id in doc_ids:
        update = updates[doc_id]
        records = scroll_qdrant_document(client, update["collection"], doc_id)
        qdrant_backup[doc_id] = records
        with (new_chunks_dir / f"{doc_id}.jsonl").open(
            "w", encoding="utf-8", newline="\n",
        ) as stream:
            for chunk in update["chunks"]:
                stream.write(json.dumps(chunk, ensure_ascii=False) + "\n")

    (backup_dir / "qdrant_points.json").write_text(
        json.dumps(qdrant_backup, ensure_ascii=False),
        encoding="utf-8",
    )
    metadata = {
        "created_at": datetime.now().astimezone().isoformat(),
        "doc_ids": doc_ids,
        "status": "prepared",
        "before_hashes": {
            "clause_chunks": _file_sha256(CLAUSE_PATH),
            "table_chunks": _file_sha256(TABLE_PATH),
            "bm25": _file_sha256(BM25_PATH) if BM25_PATH.exists() else None,
        },
        "qdrant_before": {
            doc_id: {
                "collection": updates[doc_id]["collection"],
                "count": len(qdrant_backup[doc_id]),
            }
            for doc_id in doc_ids
        },
    }
    (backup_dir / "update_report.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return backup_dir, qdrant_backup


def _build_qdrant_points(updates: dict[str, dict]) -> dict[str, list[PointStruct]]:
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    from src.indexer.embedder import Embedder

    embedder = Embedder()
    points_by_doc: dict[str, list[PointStruct]] = {}
    for doc_id, update in updates.items():
        chunks = update["chunks"]
        print(f"[向量化] {doc_id}: {len(chunks)} chunks", flush=True)
        vectors = embedder.embed_batch([chunk["text"] for chunk in chunks])
        points_by_doc[doc_id] = [
            PointStruct(
                id=make_point_id(update["collection"], doc_id, chunk["chunk_id"]),
                vector=vector,
                payload=chunk,
            )
            for chunk, vector in zip(chunks, vectors)
        ]
    return points_by_doc


def _restore_backup(
    backup_dir: Path,
    updates: dict[str, dict],
    qdrant_backup: dict[str, list[dict]],
    client,
) -> list[str]:
    errors: list[str] = []
    try:
        _copy_file_overwrite(backup_dir / CLAUSE_PATH.name, CLAUSE_PATH)
        _copy_file_overwrite(backup_dir / TABLE_PATH.name, TABLE_PATH)
        bm25_backup = backup_dir / BM25_PATH.name
        if bm25_backup.exists():
            _copy_file_overwrite(bm25_backup, BM25_PATH)
    except Exception as exc:
        errors.append(f"file restore failed: {exc}")

    for doc_id, update in updates.items():
        try:
            old_points = [
                PointStruct(
                    id=record["id"],
                    vector=record["vector"],
                    payload=record["payload"],
                )
                for record in qdrant_backup[doc_id]
            ]
            replace_qdrant_document(
                client, update["collection"], doc_id, old_points,
            )
        except Exception as exc:
            errors.append(f"Qdrant restore failed for {doc_id}: {exc}")
    return errors


def _rebuild_bm25() -> None:
    from src.indexer.bm25_index import BM25Index

    temp_path = BM25_PATH.with_suffix(".pkl.tmp")
    if temp_path.exists():
        temp_path.unlink()
    BM25Index(index_path=str(temp_path)).build([
        str(CLAUSE_PATH), str(TABLE_PATH),
    ])
    replace_file_preserving_mode(temp_path, BM25_PATH)


def run_update(doc_ids: list[str], *, apply: bool = False) -> dict:
    updates = prepare_document_updates(doc_ids)
    target_ids = set(doc_ids)
    file_before = {
        "regulations": _chunk_counts(CLAUSE_PATH, target_ids),
        "tables": _chunk_counts(TABLE_PATH, target_ids),
    }
    client = _new_qdrant_client()
    qdrant_plan = _inspect_qdrant(client, updates)
    for doc_id, plan in qdrant_plan.items():
        file_count = file_before[plan["collection"]][doc_id]
        if file_count != plan["before"]:
            raise RuntimeError(
                f"{doc_id} differs between chunks ({file_count}) and Qdrant ({plan['before']})"
            )

    summary = {
        "mode": "apply" if apply else "dry-run",
        "documents": {
            doc_id: {
                **qdrant_plan[doc_id],
                "skipped_duplicate_texts": updates[doc_id]["skipped_duplicate_texts"],
            }
            for doc_id in doc_ids
        },
    }
    if not apply:
        return summary

    non_target_before = {
        "regulations": _non_target_digest(CLAUSE_PATH, target_ids),
        "tables": _non_target_digest(TABLE_PATH, target_ids),
    }
    collection_totals_before = {
        collection: client.get_collection(collection).points_count
        for collection in ("regulations", "tables")
    }
    backup_dir, qdrant_backup = _create_backup(doc_ids, updates, client)
    summary["backup_dir"] = str(backup_dir)
    try:
        points_by_doc = _build_qdrant_points(updates)
        replacements = {
            "regulations": {
                doc_id: update["chunks"]
                for doc_id, update in updates.items()
                if update["collection"] == "regulations"
            },
            "tables": {
                doc_id: update["chunks"]
                for doc_id, update in updates.items()
                if update["collection"] == "tables"
            },
        }
        file_summaries = {}
        if replacements["regulations"]:
            file_summaries["regulations"] = rewrite_jsonl_documents(
                CLAUSE_PATH, replacements["regulations"],
            )
        if replacements["tables"]:
            file_summaries["tables"] = rewrite_jsonl_documents(
                TABLE_PATH, replacements["tables"],
            )
        if _non_target_digest(CLAUSE_PATH, target_ids) != non_target_before["regulations"]:
            raise RuntimeError("Non-target regulation chunks changed")
        if _non_target_digest(TABLE_PATH, target_ids) != non_target_before["tables"]:
            raise RuntimeError("Non-target table chunks changed")

        qdrant_summaries = {}
        for doc_id in doc_ids:
            update = updates[doc_id]
            qdrant_summaries[doc_id] = replace_qdrant_document(
                client,
                update["collection"],
                doc_id,
                points_by_doc[doc_id],
            )

        _rebuild_bm25()
        collection_totals_after = {
            collection: client.get_collection(collection).points_count
            for collection in ("regulations", "tables")
        }
        expected_totals = dict(collection_totals_before)
        for doc_id, plan in qdrant_plan.items():
            expected_totals[plan["collection"]] += plan["after"] - plan["before"]
        if collection_totals_after != expected_totals:
            raise RuntimeError(
                f"Unexpected Qdrant totals: expected {expected_totals}, "
                f"found {collection_totals_after}"
            )

        summary.update({
            "status": "success",
            "files": file_summaries,
            "qdrant": qdrant_summaries,
            "collection_totals_before": collection_totals_before,
            "collection_totals_after": collection_totals_after,
            "after_hashes": {
                "clause_chunks": _file_sha256(CLAUSE_PATH),
                "table_chunks": _file_sha256(TABLE_PATH),
                "bm25": _file_sha256(BM25_PATH),
            },
        })
        (backup_dir / "update_report.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return summary
    except Exception as exc:
        restore_errors = _restore_backup(
            backup_dir, updates, qdrant_backup, client,
        )
        failure = {
            **summary,
            "status": "rolled_back" if not restore_errors else "rollback_failed",
            "error": str(exc),
            "restore_errors": restore_errors,
        }
        (backup_dir / "update_report.json").write_text(
            json.dumps(failure, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        raise RuntimeError(json.dumps(failure, ensure_ascii=False)) from exc


def rewrite_jsonl_documents(
    path: Path,
    replacements: dict[str, list[dict]],
) -> dict[str, dict[str, int]]:
    raw_lines = path.read_bytes().splitlines(keepends=True)
    line_ending = b"\r\n" if any(line.endswith(b"\r\n") for line in raw_lines) else b"\n"
    before: Counter = Counter()
    inserted: set[str] = set()
    output: list[bytes] = []

    for raw_line in raw_lines:
        payload = raw_line.rstrip(b"\r\n")
        if not payload:
            output.append(raw_line)
            continue
        row = json.loads(payload.decode("utf-8"))
        doc_id = row.get("doc_id")
        before[doc_id] += 1
        if doc_id not in replacements:
            output.append(raw_line)
            continue
        if doc_id not in inserted:
            output.extend(
                json.dumps(chunk, ensure_ascii=False).encode("utf-8") + line_ending
                for chunk in replacements[doc_id]
            )
            inserted.add(doc_id)

    for doc_id, chunks in replacements.items():
        if doc_id not in inserted:
            output.extend(
                json.dumps(chunk, ensure_ascii=False).encode("utf-8") + line_ending
                for chunk in chunks
            )

    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("wb") as stream:
        for raw_line in output:
            if raw_line.endswith((b"\n", b"\r")):
                stream.write(raw_line)
            else:
                stream.write(raw_line + line_ending)
    os.replace(temp_path, path)

    return {
        doc_id: {"before": before[doc_id], "after": len(chunks)}
        for doc_id, chunks in replacements.items()
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--doc-ids", required=True, help="Comma-separated doc_id values")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the update; without this flag only a read-only dry run is performed",
    )
    args = parser.parse_args()
    doc_ids = [value.strip() for value in args.doc_ids.split(",") if value.strip()]
    print(json.dumps(run_update(doc_ids, apply=args.apply), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
