"""Sample route."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/example")
def get_example():
    """Sample route."""
    return {"message": "Example Test Endpoint"}
