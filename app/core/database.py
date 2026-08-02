"""
SQLAlchemy engine, session factory, and declarative base.
"""
import time

from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

db_url = (settings.ONLINE_DATABASE_URL or settings.DATABASE_URL or "sqlite:///./sacco.db").strip()
connect_args = {"check_same_thread": False} if db_url.startswith("sqlite") else {}

engine = create_engine(db_url, connect_args=connect_args, pool_pre_ping=True)


class RetryingSession(Session):
    """Retry serializable transaction failures for CockroachDB-like backends."""

    def commit(self):
        retries = 0
        while True:
            try:
                return super().commit()
            except OperationalError as exc:
                if not _is_retryable_serialization_error(exc):
                    raise
                if retries >= 3:
                    raise
                self.rollback()
                retries += 1
                time.sleep(0.05 * (2**retries))


def _is_retryable_serialization_error(exc: OperationalError) -> bool:
    text = str(exc).lower()
    if "restart transaction" in text or "write too old" in text or "transactionretry" in text:
        return True
    orig = getattr(exc, "orig", None)
    if orig is not None:
        orig_text = str(orig).lower()
        if "restart transaction" in orig_text or "write too old" in orig_text or "transactionretry" in orig_text:
            return True
    return False


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, class_=RetryingSession)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency that yields a DB session and guarantees closure."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
