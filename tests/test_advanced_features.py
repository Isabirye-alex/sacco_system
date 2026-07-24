import pytest
from app.core.enums import UserRole

def test_credit_score_endpoint(client, admin_headers):
    # Member ID query
    response = client.get("/api/v1/loans/credit-score/test-member-id", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert "score" in data
    assert "rating" in data
    assert "max_eligible_loan" in data

def test_sasra_reports_endpoints(client, admin_headers):
    # Form 1
    f1 = client.get("/api/v1/reports/sasra/form-1", headers=admin_headers)
    assert f1.status_code == 200
    assert "core_capital" in f1.json()

    # Form 2
    f2 = client.get("/api/v1/reports/sasra/form-2", headers=admin_headers)
    assert f2.status_code == 200
    assert "liquid_assets" in f2.json()

    # Form 3
    f3 = client.get("/api/v1/reports/sasra/form-3", headers=admin_headers)
    assert f3.status_code == 200
    assert "classification" in f3.json()
