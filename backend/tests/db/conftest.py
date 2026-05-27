"""Disposable-Postgres fixtures for DB integration tests.

Tests in this package require Docker (testcontainers).  If Docker is
unavailable the entire module is skipped gracefully.
"""
from __future__ import annotations

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


# ---------------------------------------------------------------------------
# Session-scoped Postgres container
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def db_url() -> str:
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        pytest.skip("testcontainers not installed")

    try:
        with PostgresContainer("postgres:16-alpine") as pg:
            # testcontainers returns a psycopg2 URL; swap driver to psycopg3
            url: str = pg.get_connection_url().replace("+psycopg2", "+psycopg")
            yield url
    except Exception as exc:
        pytest.skip(f"Docker unavailable ({exc})")


@pytest.fixture(scope="session")
def db_engine(db_url: str):
    """Engine with migrations applied once per session."""
    engine = create_engine(db_url, pool_pre_ping=True)

    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)
    command.upgrade(alembic_cfg, "head")

    yield engine
    engine.dispose()


# ---------------------------------------------------------------------------
# Per-test transaction rollback — keeps tests isolated without recreating DB
# ---------------------------------------------------------------------------


@pytest.fixture
def session(db_engine):
    """
    Yields a Session wrapping a rolled-back transaction after each test.
    This avoids table-truncation overhead while keeping full isolation.
    """
    connection = db_engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection, autocommit=False, autoflush=False)
    sess = Session()

    yield sess

    sess.close()
    transaction.rollback()
    connection.close()
