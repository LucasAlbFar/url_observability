"""The route that fails on purpose."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/fail")
def fail():
    """Raise, so the unhandled-exception handler has something to answer.

    The other two services serve this path as well. It exists so an
    error — span, status and log line — can be produced with no service
    stopped, and it is deliberately absent from the load generator's
    URLS: driven, it would make the 5xx panel a constant.
    """
    raise RuntimeError("failed on purpose")
