def test_health_reports_ok_and_environment(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "environment": "dev"}
