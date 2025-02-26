"""Test main route."""


def test_main_route(client):
    """Confirm that main root is working."""
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Hello, FastAPI!"}
