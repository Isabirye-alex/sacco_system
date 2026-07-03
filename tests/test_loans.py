def _create_member(client, headers, national_id):
    payload = {"first_name": "Loan", "last_name": "Applicant", "national_id": national_id, "phone_number": "+256700000099"}
    return client.post("/api/v1/members", json=payload, headers=headers).json()


def _create_loan_product(client, headers, requires_guarantors=True):
    payload = {
        "name": "Development Loan",
        "interest_rate_annual": "12.0",
        "max_repayment_months": 24,
        "max_amount": "5000000",
        "requires_guarantors": requires_guarantors,
        "min_guarantors": 1,
    }
    return client.post("/api/v1/loans/products", json=payload, headers=headers).json()


def test_full_loan_lifecycle(client, teller_headers, manager_headers, loan_officer_headers):
    borrower = _create_member(client, teller_headers, "NID-LN1")
    guarantor_member = _create_member(client, teller_headers, "NID-LN2")
    product = _create_loan_product(client, manager_headers)

    application = client.post(
        "/api/v1/loans/applications",
        json={
            "member_id": borrower["id"],
            "product_id": product["id"],
            "amount_requested": "1000000",
            "repayment_months": 12,
            "purpose": "School fees",
            "guarantors": [{"guarantor_member_id": guarantor_member["id"], "amount_guaranteed": "1000000"}],
        },
        headers=loan_officer_headers,
    )
    assert application.status_code == 201, application.text
    loan = application.json()
    assert loan["status"] == "pending"
    guarantor_id = loan["guarantors"][0]["id"]

    # Approval should be blocked until the guarantor responds
    blocked = client.post(
        f"/api/v1/loans/applications/{loan['id']}/decision", json={"approve": True}, headers=loan_officer_headers
    )
    assert blocked.status_code == 422

    respond = client.post(
        f"/api/v1/loans/guarantors/{guarantor_id}/respond", json={"accept": True}, headers=teller_headers
    )
    assert respond.status_code == 200

    decision = client.post(
        f"/api/v1/loans/applications/{loan['id']}/decision",
        json={"approve": True, "amount_approved": "1000000"},
        headers=loan_officer_headers,
    )
    assert decision.status_code == 200
    assert decision.json()["status"] == "approved"

    savings_product = client.post(
        "/api/v1/savings/products",
        json={"name": "Regular", "product_type": "regular", "minimum_balance": "0"},
        headers=manager_headers,
    ).json()
    savings_account = client.post(
        "/api/v1/savings/accounts",
        json={"member_id": borrower["id"], "product_id": savings_product["id"]},
        headers=teller_headers,
    ).json()

    disburse = client.post(
        f"/api/v1/loans/applications/{loan['id']}/disburse",
        json={"disbursement_channel": "savings_account", "disbursement_savings_account_id": savings_account["id"]},
        headers=loan_officer_headers,
    )
    assert disburse.status_code == 200, disburse.text
    disbursed_loan = disburse.json()
    assert disbursed_loan["status"] == "active"

    schedule = client.get(f"/api/v1/loans/applications/{loan['id']}/schedule", headers=loan_officer_headers).json()
    assert len(schedule) == 12

    funded_account = client.get(f"/api/v1/savings/accounts/{savings_account['id']}", headers=teller_headers).json()
    assert float(funded_account["balance"]) == 1000000.0

    first_installment_total = float(schedule[0]["principal_due"]) + float(schedule[0]["interest_due"])
    repayment = client.post(
        f"/api/v1/loans/applications/{loan['id']}/repayments",
        json={"amount": str(first_installment_total)},
        headers=teller_headers,
    )
    assert repayment.status_code == 200


def test_loan_amount_exceeding_product_max_rejected(client, teller_headers, manager_headers, loan_officer_headers):
    borrower = _create_member(client, teller_headers, "NID-LN3")
    product = _create_loan_product(client, manager_headers, requires_guarantors=False)
    response = client.post(
        "/api/v1/loans/applications",
        json={
            "member_id": borrower["id"],
            "product_id": product["id"],
            "amount_requested": "999999999",
            "repayment_months": 12,
        },
        headers=loan_officer_headers,
    )
    assert response.status_code == 422


def test_loan_requiring_guarantor_without_one_rejected(client, teller_headers, manager_headers, loan_officer_headers):
    borrower = _create_member(client, teller_headers, "NID-LN4")
    product = _create_loan_product(client, manager_headers, requires_guarantors=True)
    response = client.post(
        "/api/v1/loans/applications",
        json={
            "member_id": borrower["id"],
            "product_id": product["id"],
            "amount_requested": "100000",
            "repayment_months": 6,
        },
        headers=loan_officer_headers,
    )
    assert response.status_code == 422
