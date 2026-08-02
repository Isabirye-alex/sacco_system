from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.database import RetryingSession


class DummySerializationFailure(Exception):
    pass


def test_retrying_session_retries_serialization_failure(monkeypatch):
    engine = create_engine("sqlite://")
    session = RetryingSession(bind=engine)

    calls = {"count": 0}
    real_commit = Session.commit

    def flaky_commit(self):
        calls["count"] += 1
        if calls["count"] == 1:
            raise OperationalError(
                "UPDATE members SET last_activity_at=?",
                {"last_activity_at": None},
                orig=DummySerializationFailure("restart transaction"),
            )
        return real_commit(self)

    monkeypatch.setattr(Session, "commit", flaky_commit)

    session.commit()

    assert calls["count"] == 2
