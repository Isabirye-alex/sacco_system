def test_register_and_login(client):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "jane@sacco.test", "full_name": "Jane Doe", "password": "SuperSecret123", "role": "teller"},
    )
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["email"] == "jane@sacco.test"
    assert "hashed_password" not in data

    login_response = client.post(
        "/api/v1/auth/login", data={"username": "jane@sacco.test", "password": "SuperSecret123"}
    )
    assert login_response.status_code == 200
    tokens = login_response.json()
    assert "access_token" in tokens and "refresh_token" in tokens


def test_login_wrong_password_fails(client):
    client.post(
        "/api/v1/auth/register",
        json={"email": "bob@sacco.test", "full_name": "Bob", "password": "CorrectPass123", "role": "teller"},
    )
    response = client.post("/api/v1/auth/login", data={"username": "bob@sacco.test", "password": "WrongPass"})
    assert response.status_code == 401


def test_duplicate_registration_conflicts(client):
    payload = {"email": "dup@sacco.test", "full_name": "Dup", "password": "CorrectPass123", "role": "teller"}
    first = client.post("/api/v1/auth/register", json=payload)
    assert first.status_code == 201
    second = client.post("/api/v1/auth/register", json=payload)
    assert second.status_code == 409


def test_me_requires_authentication(client):
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_me_returns_current_user(client, admin_headers):
    response = client.get("/api/v1/auth/me", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["role"] == "admin"


def test_refresh_token_flow(client):
    client.post(
        "/api/v1/auth/register",
        json={"email": "ref@sacco.test", "full_name": "Ref", "password": "CorrectPass123", "role": "teller"},
    )
    login = client.post("/api/v1/auth/login", data={"username": "ref@sacco.test", "password": "CorrectPass123"})
    refresh_token = login.json()["refresh_token"]
    response = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert response.status_code == 200
    assert "access_token" in response.json()
