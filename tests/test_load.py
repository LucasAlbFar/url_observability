"""Test load route."""


def test_load_io_bound(client):
    """Confirm that load/io-bound is working."""
    response = client.get("/load/io-bound")
    assert response.status_code == 200
    assert response.json() == {"message": "I/O-bound task completed"}


def test_load_cpu_bound(client):
    """Confirm that load/cpu-bound is working."""
    response = client.get("/load/cpu-bound")
    assert response.status_code == 200
    assert response.json() == {
        "message": "CPU-bound task completed",
        "result": 10000000,
    }


def test_memory_spike(client):
    """Confirm that memory-spike is working."""
    response = client.get("load/memory-spike")
    assert response.status_code == 200
    assert response.json() == {
        "message": "Memory spike simulated",
        "length": 10000000,
    }


def test_cpu_stress(client):
    """Confirm that cpu stress is working."""
    response = client.get("load/stress/2")
    assert response.status_code == 200
    assert response.json() == {"message": "CPU stressed for 2 seconds"}
