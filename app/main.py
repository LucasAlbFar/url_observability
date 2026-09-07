"""Main route."""

from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.api.endpoints.chain import router as chain_router
from app.api.endpoints.example import router as example_route
from app.api.endpoints.health import router as health_router
from app.api.endpoints.load import router as load_router

app = FastAPI()


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


app.include_router(chain_router)
app.include_router(example_route)
app.include_router(health_router)
app.include_router(load_router, prefix="/load", tags=["Load Testing"])


@app.get("/")
def main_root():
    """Main route."""
    return {"message": "Hello, FastAPI!"}
