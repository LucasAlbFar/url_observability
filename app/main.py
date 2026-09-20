"""Main route."""

import logging

from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import PlainTextResponse

from app.api.endpoints.chain import router as chain_router
from app.api.endpoints.example import router as example_route
from app.api.endpoints.health import router as health_router
from app.api.endpoints.load import router as load_router

app = FastAPI()

# The third pillar. Nothing configures a handler here: the SDK attaches
# one to the root logger, so a record made with the standard library
# leaves as OTLP carrying the trace id of the span it was made inside.
# That id is the whole point — it is what joins a line to the request
# that produced it.
logger = logging.getLogger(__name__)


# The exposition, and nothing that measures a request. The HTTP metrics
# this app used to publish under `handler`/`status` are derived from its
# spans now, in the Collector, alongside the other two services under one
# convention. What is left here is the default registry, whose process
# and runtime collectors no span can produce.
#
# A route rather than `app.mount`: a mount redirects /metrics to
# /metrics/ with a 307, which every scrape would pay a round trip for —
# and which a test using a redirect-following client cannot see.
@app.get("/metrics")
def metrics():
    """Serve the default registry in the exposition format."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.exception_handler(Exception)
async def log_unhandled_exception(request: Request, error: Exception):
    """Record what escaped before answering, and answer as before.

    The response is the same plain 500 Starlette sends with no handler
    registered; what registering one adds is the line. Returning it
    rather than re-raising is deliberate: re-raising from here skips
    the response Starlette would have sent.
    """
    logger.exception(
        "unhandled exception",
        extra={
            "http.request.method": request.method,
            "url.path": request.url.path,
        },
    )
    return PlainTextResponse("Internal Server Error", status_code=500)


app.include_router(chain_router)
app.include_router(example_route)
app.include_router(health_router)
app.include_router(load_router, prefix="/load", tags=["Load Testing"])


@app.get("/")
def main_root():
    """Main route."""
    return {"message": "Hello, FastAPI!"}
