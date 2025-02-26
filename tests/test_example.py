"""Test example route."""


def test_example_root(client):
    """Confirm that main root is working."""
    response = client.get("/example")
    assert response.status_code == 200
    assert response.json() == {"message": "Example Test Endpoint"}
