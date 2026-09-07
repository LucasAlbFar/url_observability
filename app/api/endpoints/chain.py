"""The route that crosses every service."""

import httpx
from fastapi import APIRouter, HTTPException

router = APIRouter()

# The next hop, written here rather than read from the environment, for
# the reason worker/load_driver.py keeps its own list: one address, in
# one place. It resolves on the compose network only, which makes this
# the one route `uvicorn app.main:app` cannot serve on its own.
NEXT = "http://service-go:8003/chain"
TIMEOUT = 10


@router.get("/chain")
async def chain():
    """Call the next service and return what it answered.

    There is no other edge between these services: everything else is
    driven by the load generator, which nothing observes. This is the
    crossing, and it exists before anything records it.
    """
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(NEXT)
            response.raise_for_status()
            following = response.json()
    except (httpx.HTTPError, ValueError) as error:
        # 502 rather than 500: the failure is downstream, and that
        # difference is what says which service to go and look at.
        # ValueError is in the list for the same reason: a 200 carrying
        # a body that is not JSON is the next service misbehaving, and
        # letting the decode error escape reports it as this one's.
        raise HTTPException(status_code=502, detail=f"{NEXT}: {error}")
    return {"service": "fastapi-app", "next": following}
