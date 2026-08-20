"""Test health route."""


def test_health(client):
    """Confirm the route both healthchecks probe answers."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
