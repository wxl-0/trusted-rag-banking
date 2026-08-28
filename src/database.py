import os
from collections.abc import Generator
from contextlib import contextmanager
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


class DatabaseNotConfigured(RuntimeError):
    pass


class Database:
    def __init__(self, url: str | None = None):
        self.url = url or os.getenv("DATABASE_URL")
        self._engine: Engine | None = None
        self._session_factory: sessionmaker[Session] | None = None

        if self.url:
            self._engine = create_engine(self.url, pool_pre_ping=True)
            self._session_factory = sessionmaker(
                bind=self._engine,
                expire_on_commit=False,
            )

    @property
    def engine(self) -> Engine:
        if self._engine is None:
            raise DatabaseNotConfigured("DATABASE_URL is not configured")
        return self._engine

    def ping(self) -> None:
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    @contextmanager
    def session(self) -> Generator[Session, None, None]:
        if self._session_factory is None:
            raise DatabaseNotConfigured("DATABASE_URL is not configured")
        with self._session_factory() as session:
            yield session

    def dispose(self) -> None:
        if self._engine is not None:
            self._engine.dispose()


@lru_cache(maxsize=1)
def get_database() -> Database:
    return Database()


def get_session(
    database: Annotated[Database, Depends(get_database)],
) -> Generator[Session, None, None]:
    with database.session() as session:
        yield session
