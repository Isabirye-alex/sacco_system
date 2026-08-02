"""
Unit tests for Sacco News API endpoints.
"""

def test_list_published_news_empty(client):
    res = client.get("/api/v1/news")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_create_and_manage_news(client, admin_headers):
    # 1. Create a news item as admin
    payload = {
        "title": "Annual General Meeting 2026",
        "content": "All members are invited to attend the AGM on August 30th.",
        "category": "EVENT",
        "priority": "HIGH",
        "icon": "fa-bell",
        "is_published": True,
    }
    create_res = client.post("/api/v1/news", json=payload, headers=admin_headers)
    assert create_res.status_code == 201, create_res.text
    news_data = create_res.json()
    news_id = news_data["id"]
    assert news_data["title"] == payload["title"]
    assert news_data["category"] == "EVENT"
    assert news_data["priority"] == "HIGH"

    # 2. Get published news (should include the new item)
    pub_res = client.get("/api/v1/news")
    assert pub_res.status_code == 200
    published_items = pub_res.json()
    assert any(n["id"] == news_id for n in published_items)

    # 3. List all news via admin endpoint
    admin_list_res = client.get("/api/v1/news/admin/all", headers=admin_headers)
    assert admin_list_res.status_code == 200
    assert any(n["id"] == news_id for n in admin_list_res.json())

    # 4. Patch/Update news item
    patch_res = client.patch(
        f"/api/v1/news/{news_id}",
        json={"title": "AGM 2026 Updated Venue", "priority": "URGENT"},
        headers=admin_headers,
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["title"] == "AGM 2026 Updated Venue"
    assert patch_res.json()["priority"] == "URGENT"

    # 5. Delete news item
    del_res = client.delete(f"/api/v1/news/{news_id}", headers=admin_headers)
    assert del_res.status_code == 204

    # 6. Verify deletion
    get_res = client.get(f"/api/v1/news/{news_id}")
    assert get_res.status_code == 404
