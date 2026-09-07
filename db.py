"""Database engine/session helpers.

SQLite is used by default. Set DATABASE_URL to a PostgreSQL URL for production;
the SQLAlchemy models and queries remain unchanged.
"""

from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from config import Config
from models import Base

_engine = None
_SessionLocal = None


def _ensure_sqlite_dir(url: str) -> None:
    if not url.startswith("sqlite:///"):
        return
    db_file = url.replace("sqlite:///", "", 1)
    if not db_file or db_file == ":memory:":
        return
    Path(db_file).parent.mkdir(parents=True, exist_ok=True)


def get_engine():
    global _engine
    if _engine is None:
        _ensure_sqlite_dir(Config.DATABASE_URL)
        if Config.DATABASE_URL.startswith("sqlite"):
            _engine = sa.create_engine(
                Config.DATABASE_URL,
                connect_args={"check_same_thread": False, "timeout": 30},
                pool_pre_ping=True,
                future=True,
            )
            with _engine.connect() as conn:
                conn.exec_driver_sql("PRAGMA journal_mode=WAL")
                conn.exec_driver_sql("PRAGMA synchronous=NORMAL")
                conn.exec_driver_sql("PRAGMA foreign_keys=ON")
                conn.commit()
        else:
            _engine = sa.create_engine(
                Config.DATABASE_URL,
                pool_pre_ping=True,
                future=True,
            )
        Base.metadata.create_all(_engine)
    return _engine


def get_session() -> Session:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    return _SessionLocal()


def utcnow():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(tzinfo=None)
