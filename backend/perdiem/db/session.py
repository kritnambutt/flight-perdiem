"""SQLAlchemy engine + session factory.

Usage (FastAPI dependency injection):

    from perdiem.db.session import get_session

    @app.get("/runs")
    def list_runs(session: Session = Depends(get_session)):
        ...
"""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from perdiem.config import settings

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,   # validate connections before use (handles idle-timeout drops)
    pool_size=5,
    max_overflow=10,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a DB session and closes it on exit."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
