import pytest

def test_list_branches(client, admin_headers):
    response = client.get("/api/v1/branches", headers=admin_headers)
    assert response.status_code == 200
    assert isinstance(response.json(), list)

def test_dashboard_trends(client, admin_headers):
    response = client.get("/api/v1/reports/dashboard-trends?months=7", headers=admin_headers)
    assert response.status_code == 200
    assert "months" in response.json() or isinstance(response.json(), dict)
