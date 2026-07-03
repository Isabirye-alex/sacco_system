def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_journal_entry_must_balance(client, manager_headers):
    cash = client.post(
        "/api/v1/accounting/accounts", json={"code": "1000", "name": "Cash", "account_type": "asset"}, headers=manager_headers
    ).json()
    income = client.post(
        "/api/v1/accounting/accounts",
        json={"code": "4000", "name": "Interest Income", "account_type": "income"},
        headers=manager_headers,
    ).json()

    unbalanced = client.post(
        "/api/v1/accounting/journal-entries",
        json={
            "narrative": "Unbalanced test",
            "lines": [
                {"account_id": cash["id"], "debit": "100", "credit": "0"},
                {"account_id": income["id"], "debit": "0", "credit": "50"},
            ],
        },
        headers=manager_headers,
    )
    assert unbalanced.status_code == 422

    balanced = client.post(
        "/api/v1/accounting/journal-entries",
        json={
            "narrative": "Balanced test",
            "lines": [
                {"account_id": cash["id"], "debit": "100", "credit": "0"},
                {"account_id": income["id"], "debit": "0", "credit": "100"},
            ],
        },
        headers=manager_headers,
    )
    assert balanced.status_code == 201, balanced.text

    trial_balance = client.get("/api/v1/accounting/trial-balance", headers=manager_headers)
    assert trial_balance.status_code == 200
    codes = {line["account_code"] for line in trial_balance.json()}
    assert {"1000", "4000"}.issubset(codes)
