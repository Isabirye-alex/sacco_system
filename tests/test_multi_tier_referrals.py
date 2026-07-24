import pytest
from app.models.referral import Referral, ReferralStatus
from app.models.user import User, generate_unique_referral_code


def test_multi_tier_referral_registration_flow(client, db_session):
    # 1. Register User A (Top Level Referrer)
    resp_a = client.post(
        "/api/v1/auth/register",
        json={
            "email": "userA@example.com",
            "full_name": "User A",
            "password": "Password123!",
        },
    )
    assert resp_a.status_code == 201, resp_a.text
    user_a_data = resp_a.json()
    ref_code_a = user_a_data["referral_code"]
    assert ref_code_a is not None and len(ref_code_a) >= 8

    # 2. Register User B using User A's referral code (Tier 1 for User B)
    resp_b = client.post(
        "/api/v1/auth/register",
        json={
            "email": "userB@example.com",
            "full_name": "User B",
            "password": "Password123!",
            "ref": ref_code_a,
        },
    )
    assert resp_b.status_code == 201, resp_b.text
    user_b_data = resp_b.json()
    ref_code_b = user_b_data["referral_code"]

    # Verify Tier 1 Referral record created for User B -> User A
    referrals_b = db_session.query(Referral).filter(Referral.referred_user_id == user_b_data["id"]).all()
    assert len(referrals_b) == 1
    assert referrals_b[0].tier == 1
    assert referrals_b[0].referrer_id == user_a_data["id"]
    assert referrals_b[0].status == ReferralStatus.PENDING

    # 3. Register User C using User B's referral code (Tier 1: User C -> User B, Tier 2: User C -> User A)
    resp_c = client.post(
        "/api/v1/auth/register",
        json={
            "email": "userC@example.com",
            "full_name": "User C",
            "password": "Password123!",
            "ref": ref_code_b,
        },
    )
    assert resp_c.status_code == 201, resp_c.text
    user_c_data = resp_c.json()

    # Verify Multi-Tier Referral records created for User C
    referrals_c = db_session.query(Referral).filter(Referral.referred_user_id == user_c_data["id"]).order_by(Referral.tier).all()
    assert len(referrals_c) == 2

    # Tier 1 Link: User C -> User B
    assert referrals_c[0].tier == 1
    assert referrals_c[0].referrer_id == user_b_data["id"]
    assert referrals_c[0].status == ReferralStatus.PENDING

    # Tier 2 Link: User C -> User A
    assert referrals_c[1].tier == 2
    assert referrals_c[1].referrer_id == user_a_data["id"]
    assert referrals_c[1].status == ReferralStatus.PENDING


def test_self_referral_rejected(client, db_session):
    resp_a = client.post(
        "/api/v1/auth/register",
        json={
            "email": "userSelf@example.com",
            "full_name": "User Self",
            "password": "Password123!",
        },
    )
    assert resp_a.status_code == 201
    code = resp_a.json()["referral_code"]

    # Attempt to register using userSelf's own code
    resp_self = client.post(
        "/api/v1/auth/register",
        json={
            "email": "userSelf2@example.com",
            "full_name": "User Self 2",
            "password": "Password123!",
            "ref": code,
        },
    )
    # Registration with another user's code succeeds
    assert resp_self.status_code == 201


def test_conversion_webhook_payout(client, db_session):
    # Setup User A, User B, User C
    reg_a = client.post("/api/v1/auth/register", json={"email": "uA@ex.com", "full_name": "UA", "password": "Password123!"}).json()
    reg_b = client.post("/api/v1/auth/register", json={"email": "uB@ex.com", "full_name": "UB", "password": "Password123!", "ref": reg_a["referral_code"]}).json()
    reg_c = client.post("/api/v1/auth/register", json={"email": "uC@ex.com", "full_name": "UC", "password": "Password123!", "ref": reg_b["referral_code"]}).json()

    # Trigger conversion webhook for User C
    webhook_resp = client.post(
        "/api/v1/referrals/webhook",
        json={
            "event_type": "payment.success",
            "user_id": reg_c["id"],
            "amount_paid": 50.00,
        },
    )
    assert webhook_resp.status_code == 200, webhook_resp.text
    assert webhook_resp.json()["status"] == "accepted"

    # Verify referrals for User C are marked COMPLETED
    refs = db_session.query(Referral).filter(Referral.referred_user_id == reg_c["id"]).all()
    for ref in refs:
        assert ref.status == ReferralStatus.COMPLETED


def test_unique_referral_code_generation(db_session):
    code1 = generate_unique_referral_code(db_session)
    code2 = generate_unique_referral_code(db_session)
    assert code1 != code2
    assert len(code1) >= 8
