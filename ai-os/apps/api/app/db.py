"""Database bootstrap (Phase 0).

Kept deliberately thin for the MVP: a SQLAlchemy engine + the append-only
audit_logs table. The API boots even if Postgres is unreachable — DB init is
best-effort so the Phase 1 UI works before infra is fully up.
"""
from __future__ import annotations

import logging

from sqlalchemy import Column, DateTime, Integer, String, Text, create_engine, func
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

log = logging.getLogger("aios.db")


class Base(DeclarativeBase):
    pass


class AuditLogRow(Base):
    __tablename__ = "audit_logs"  # append-only

    id = Column(Integer, primary_key=True, autoincrement=True)
    at = Column(DateTime(timezone=True), server_default=func.now())
    kind = Column(String(64), nullable=False)
    actor = Column(String(128), nullable=False)
    risk = Column(Integer, default=0)
    summary = Column(Text, nullable=False)


_engine = None
SessionLocal = None


def init_db() -> bool:
    """Create tables if the DB is reachable. Returns True on success."""
    global _engine, SessionLocal
    try:
        _engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
        Base.metadata.create_all(_engine)
        SessionLocal = sessionmaker(bind=_engine, autoflush=False, future=True)
        log.info("database initialized")
        return True
    except Exception as exc:  # noqa: BLE001 — boot must survive a missing DB
        log.warning("database unavailable, continuing without persistence: %s", exc)
        return False
