def _sample_member_payload(national_id="NID-0001"):
    return {
        "first_name": "Grace",
        "last_name": "Nakato",
        "national_id": national_id,
        "phone_number": "+256700000001",
        "email": "grace@example.com",
        "next_of_kin": [
            {"full_name": "John Nakato", "relationship_type": "spouse", "phone_number": "+256700000002"}
        ],
    }


def test_create_member_requires_staff_role(client, member_user_headers):
    response = client.post("/api/v1/members", json=_sample_member_payload(), headers=member_user_headers)
    assert response.status_code == 403


def test_create_and_get_member(client, teller_headers):
    response = client.post("/api/v1/members", json=_sample_member_payload(), headers=teller_headers)
    assert response.status_code == 201, response.text
    member = response.json()
    assert member["first_name"] == "Grace"
    assert member["member_number"].startswith("MB")
    assert len(member["next_of_kin"]) == 1

    get_response = client.get(f"/api/v1/members/{member['id']}", headers=teller_headers)
    assert get_response.status_code == 200
    assert get_response.json()["national_id"] == "NID-0001"


def test_duplicate_national_id_rejected(client, teller_headers):
    client.post("/api/v1/members", json=_sample_member_payload("NID-DUP"), headers=teller_headers)
    response = client.post("/api/v1/members", json=_sample_member_payload("NID-DUP"), headers=teller_headers)
    assert response.status_code == 409


def test_search_members(client, teller_headers):
    client.post("/api/v1/members", json=_sample_member_payload("NID-SEARCH"), headers=teller_headers)
    response = client.get("/api/v1/members", params={"q": "Grace"}, headers=teller_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1
    assert any(m["first_name"] == "Grace" for m in body["items"])


def test_update_member_status(client, teller_headers, manager_headers):
    created = client.post("/api/v1/members", json=_sample_member_payload("NID-UPD"), headers=teller_headers).json()
    response = client.patch(
        f"/api/v1/members/{created['id']}", json={"status": "suspended"}, headers=manager_headers
    )
    assert response.status_code == 200
    assert response.json()["status"] == "suspended"


def test_exit_member_soft_deletes(client, teller_headers, manager_headers):
    created = client.post("/api/v1/members", json=_sample_member_payload("NID-EXIT"), headers=teller_headers).json()
    response = client.delete(f"/api/v1/members/{created['id']}", headers=manager_headers)
    assert response.status_code == 204

    fetched = client.get(f"/api/v1/members/{created['id']}", headers=teller_headers).json()
    assert fetched["status"] == "exited"
