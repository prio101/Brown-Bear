"""SQLAlchemy engine, session management and declarative base.

Sync SQLAlchemy on purpose: the proxy records token events *after* the
response has been streamed to the client, off the hot path, so a threadpool
hop costs nothing measurable and keeps Alembic's tooling conventional.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from brownbear.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for every Brown Bear table."""


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
            echo=settings.debug,
        )
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _session_factory


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope: commits on success, rolls back on failure."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    with session_scope() as session:
        yield session


def reset_engine() -> None:
    """Drop cached engine/session factory. Used by tests to reconfigure."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None
