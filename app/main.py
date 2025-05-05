"""Main route."""

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from app.api.endpoints.example import router as example_route
from app.api.endpoints.load import router as load_router

app = FastAPI()

Instrumentator().instrument(app).expose(app)
app.include_router(example_route)
app.include_router(load_router, prefix="/load", tags=["Load Testing"])


@app.get("/")
def main_root():
    """Main route."""
    return {"message": "Hello, FastAPI!"}
