from app.core.enums import NotificationChannel
from app.models.notification import Notification


def _create_member(client, headers, national_id="NID-SV"):
    payload = {
        "first_name": "Peter",
        "last_name": "Okello",
        "national_id": national_id,
        "phone_number": "+256700000010",
        "email": f"{national_id.lower()}@example.com",
    }
    return client.post("/api/v1/members", json=payload, headers=headers).json()


def _create_product(client, headers):
    payload = {
        "name": "Regular Savings",
        "product_type": "regular",
        "interest_rate_annual": "5.0",
        "minimum_balance": "10000",
    }
    return client.post("/api/v1/savings/products", json=payload, headers=headers).json()


def test_open_account_and_deposit(client, teller_headers, manager_headers):
    member = _create_member(client, teller_headers)
    product = _create_product(client, manager_headers)

    account = client.post(
        "/api/v1/savings/accounts",
        json={"member_id": member["id"], "product_id": product["id"]},
        headers=teller_headers,
    ).json()
    assert account["balance"] == "0.00" or float(account["balance"]) == 0

    deposit = client.post(
        f"/api/v1/savings/accounts/{account['id']}/transactions",
        json={"txn_type": "deposit", "amount": "50000", "narrative": "Initial deposit"},
        headers=teller_headers,
    )
    assert deposit.status_code == 201, deposit.text
    assert float(deposit.json()["balance_after"]) == 50000.0


def test_withdrawal_below_minimum_balance_rejected(client, teller_headers, manager_headers):
    member = _create_member(client, teller_headers, "NID-SV2")
    product = _create_product(client, manager_headers)
    account = client.post(
        "/api/v1/savings/accounts",
        json={"member_id": member["id"], "product_id": product["id"]},
        headers=teller_headers,
    ).json()
    client.post(
        f"/api/v1/savings/accounts/{account['id']}/transactions",
        json={"txn_type": "deposit", "amount": "15000"},
        headers=teller_headers,
    )
    response = client.post(
        f"/api/v1/savings/accounts/{account['id']}/transactions",
        json={"txn_type": "withdrawal", "amount": "10000"},
        headers=teller_headers,
    )
    # Balance would drop to 5000, below the 10000 minimum -> rejected
    assert response.status_code == 422


def test_member_role_cannot_open_account(client, teller_headers, manager_headers, member_user_headers):
    member = _create_member(client, teller_headers, "NID-SV3")
    product = _create_product(client, manager_headers)
    response = client.post(
        "/api/v1/savings/accounts",
        json={"member_id": member["id"], "product_id": product["id"]},
        headers=member_user_headers,
    )
    assert response.status_code == 403


def test_withdrawal_records_sms_and_email_events_for_client(client, teller_headers, manager_headers, db_session):
    member = _create_member(client, teller_headers, "NID-SV4")
    product = _create_product(client, manager_headers)

    account = client.post(
        "/api/v1/savings/accounts",
        json={"member_id": member["id"], "product_id": product["id"]},
        headers=teller_headers,
    ).json()

    client.post(
        f"/api/v1/savings/accounts/{account['id']}/transactions",
        json={"txn_type": "deposit", "amount": "25000", "narrative": "Initial deposit"},
        headers=teller_headers,
    )

    response = client.post(
        f"/api/v1/savings/accounts/{account['id']}/transactions",
        json={"txn_type": "withdrawal", "amount": "10000", "narrative": "Routine withdrawal"},
        headers=teller_headers,
    )

    assert response.status_code == 201, response.text

    sms_event = db_session.query(Notification).filter(
        Notification.member_id == member["id"],
        Notification.channel == NotificationChannel.SMS,
        Notification.event_type == "savings_withdrawal",
    ).first()
    email_event = db_session.query(Notification).filter(
        Notification.member_id == member["id"],
        Notification.channel == NotificationChannel.EMAIL,
        Notification.event_type == "savings_withdrawal",
    ).first()

    assert sms_event is not None
    assert email_event is not None
