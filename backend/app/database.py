"""
app/database.py – SQLAlchemy engine and session factory.

Uses SQLite by default; the DATABASE_URL can be switched to PostgreSQL
without changing application code (just update the .env file).
"""
from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
connect_args: dict = {}
if settings.database_url.startswith("sqlite"):
    # Enable WAL mode and foreign-key constraints for SQLite
    connect_args["check_same_thread"] = False


engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    echo=settings.is_development,  # SQL logging only in dev
)

# Enable foreign keys and WAL for SQLite connections
if settings.database_url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record):  # noqa: ARG001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ---------------------------------------------------------------------------
# Declarative base
# ---------------------------------------------------------------------------
class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Utility: create all tables
# ---------------------------------------------------------------------------
def init_db() -> None:
    """Create all tables. Safe to call repeatedly (CREATE TABLE IF NOT EXISTS)."""
    # Import models so SQLAlchemy registers them on Base.metadata before create_all.
    import app.models  # noqa: F401 (side-effect import)

    Base.metadata.create_all(bind=engine)


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------
def get_db():
    """Yield a database session and ensure it is closed after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
