"""
Shared pytest fixtures: an isolated in-memory SQLite database per test
session, a TestClient wired to that database, and helper fixtures for
authenticated requests as different roles.
"""
import os

os.environ["ENVIRONMENT"] = "testing"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SECRET_KEY"] = "test-secret-key-not-for-production"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.enums import UserRole
from app.core.security import hash_password
from app.main import app
from app.models.user import User

TEST_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function", autouse=True)
def setup_database():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture()
def db_session():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _create_user_and_login(client, db_session, email: str, role: UserRole, password: str = "TestPass123!"):
    user = User(email=email, full_name="Test User", hashed_password=hash_password(password), role=role)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    endpoint = "/api/v1/auth/member-login" if role == UserRole.MEMBER else "/api/v1/auth/login"
    response = client.post(endpoint, data={"username": email, "password": password})
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]
    return user, {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def admin_headers(client, db_session):
    _, headers = _create_user_and_login(client, db_session, "admin@sacco.org", UserRole.ADMIN)
    return headers


@pytest.fixture()
def manager_headers(client, db_session):
    _, headers = _create_user_and_login(client, db_session, "manager@sacco.org", UserRole.MANAGER)
    return headers


@pytest.fixture()
def teller_headers(client, db_session):
    _, headers = _create_user_and_login(client, db_session, "teller@sacco.org", UserRole.TELLER)
    return headers


@pytest.fixture()
def loan_officer_headers(client, db_session):
    _, headers = _create_user_and_login(client, db_session, "loanofficer@sacco.org", UserRole.LOAN_OFFICER)
    return headers


@pytest.fixture()
def member_user_headers(client, db_session):
    _, headers = _create_user_and_login(client, db_session, "member@sacco.org", UserRole.MEMBER)
    return headers
