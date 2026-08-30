#!/usr/bin/env python
"""Idempotently prepare Qdrant collections and payload indexes."""

from src.indexer.qdrant_index import QdrantIndex


def main() -> None:
    QdrantIndex().create_collections()


if __name__ == "__main__":
    main()
