"""Readiness route."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def get_health():
    """Readiness route.

    Both services serve this path and both healthchecks probe it, so
    the body is the one the Go service returns as well.
    """
    return {"status": "ok"}
