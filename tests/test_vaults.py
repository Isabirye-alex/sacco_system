import pytest
from fastapi.testclient import TestClient
from decimal import Decimal

from app.main import app
from app.core.database import Base, engine, SessionLocal
from app.models.user import User
from app.models.member import Member
from app.core.security import hash_password

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    
    # Create test user & member if missing
    user = db.query(User).filter(User.email == "vaultuser@example.com").first()
    if not user:
        user = User(
            id="user-vault-test-id",
            email="vaultuser@example.com",
            hashed_password=hash_password("Password123!"),
            full_name="Vault Test User",
            role="ADMIN",
            is_active=True
        )
        db.add(user)
    
    member = db.query(Member).filter(Member.id == "member-vault-test-id").first()
    if not member:
        member = Member(
            id="member-vault-test-id",
            member_number="MB-VLT-001",
            first_name="Vault",
            last_name="Tester",
            national_id="CM990011223344",
            phone_number="+256700000099",
            status="ACTIVE"
        )
        db.add(member)
    
    db.commit()
    db.close()
    yield

def test_create_and_manage_target_vault():
    # Login to get auth headers if required or override get_current_user
    login_res = client.post("/api/v1/auth/login", data={"username": "vaultuser@example.com", "password": "Password123!"})
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Create Target Vault
    payload = {
        "member_id": "member-vault-test-id",
        "name": "Land Goal Vault",
        "vault_type": "GOAL",
        "target_amount": 500000.00,
        "lock_period_months": 6,
        "interest_rate_annual": 5.00,
        "early_withdrawal_penalty_pct": 2.50
    }
    res = client.post("/api/v1/vaults/", json=payload, headers=headers)
    assert res.status_code == 201, res.text
    vault = res.json()
    vault_id = vault["id"]
    assert vault["name"] == "Land Goal Vault"
    assert vault["current_balance"] == "0.00"
    assert vault["is_locked"] is True

    # 2. Deposit into Vault
    dep_res = client.post(f"/api/v1/vaults/{vault_id}/deposit", json={"amount": 100000.00}, headers=headers)
    assert dep_res.status_code == 200
    updated_vault = dep_res.json()
    assert updated_vault["current_balance"] == "100000.00"

    # 3. Withdraw without force flag (should be blocked by early penalty warning)
    w_blocked = client.post(f"/api/v1/vaults/{vault_id}/withdraw", json={"amount": 50000.00, "force_early_withdrawal": False}, headers=headers)
    assert w_blocked.status_code == 400
    assert "Early withdrawal incurs" in w_blocked.json()["detail"]

    # 4. Withdraw with force_early_withdrawal = True
    w_force = client.post(f"/api/v1/vaults/{vault_id}/withdraw", json={"amount": 50000.00, "force_early_withdrawal": True}, headers=headers)
    assert w_force.status_code == 200
    w_vault = w_force.json()
    assert w_vault["current_balance"] == "50000.00"
    assert w_vault["status"] == "BROKEN"

    # 5. List Vaults
    list_res = client.get("/api/v1/vaults/?member_id=member-vault-test-id", headers=headers)
    assert list_res.status_code == 200
    assert len(list_res.json()) >= 1
