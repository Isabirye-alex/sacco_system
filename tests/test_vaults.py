from app.models.member import Member

def test_create_and_manage_target_vault(client, admin_headers, db_session):
    # Create test member
    member = Member(
        member_number="MB-VLT-001",
        first_name="Vault",
        last_name="Tester",
        national_id="CM990011223344",
        phone_number="+256700000099",
    )
    db_session.add(member)
    db_session.commit()
    db_session.refresh(member)

    # 1. Create Target Vault
    payload = {
        "member_id": member.id,
        "name": "Land Goal Vault",
        "vault_type": "GOAL",
        "target_amount": 500000.00,
        "lock_period_months": 6,
        "interest_rate_annual": 5.00,
        "early_withdrawal_penalty_pct": 2.50
    }
    res = client.post("/api/v1/vaults/", json=payload, headers=admin_headers)
    assert res.status_code == 201, res.text
    vault = res.json()
    vault_id = vault["id"]
    assert vault["name"] == "Land Goal Vault"
    assert vault["current_balance"] == "0.00"
    assert vault["is_locked"] is True

    # 2. Deposit into Vault
    dep_res = client.post(f"/api/v1/vaults/{vault_id}/deposit", json={"amount": 100000.00}, headers=admin_headers)
    assert dep_res.status_code == 200
    updated_vault = dep_res.json()
    assert updated_vault["current_balance"] == "100000.00"

    # 3. Withdraw without force flag (blocked by early penalty warning)
    w_blocked = client.post(f"/api/v1/vaults/{vault_id}/withdraw", json={"amount": 50000.00, "force_early_withdrawal": False}, headers=admin_headers)
    assert w_blocked.status_code == 400
    assert "Early withdrawal incurs" in w_blocked.json()["detail"]

    # 4. Withdraw with force_early_withdrawal = True
    w_force = client.post(f"/api/v1/vaults/{vault_id}/withdraw", json={"amount": 50000.00, "force_early_withdrawal": True}, headers=admin_headers)
    assert w_force.status_code == 200
    w_vault = w_force.json()
    assert w_vault["current_balance"] == "50000.00"
    assert w_vault["status"] == "BROKEN"

    # 5. List Vaults
    list_res = client.get(f"/api/v1/vaults/?member_id={member.id}", headers=admin_headers)
    assert list_res.status_code == 200
    assert len(list_res.json()) >= 1
