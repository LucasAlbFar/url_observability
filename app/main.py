"""Main route."""

from fastapi import FastAPI

from app.api.endpoints.example import router as example_route

app = FastAPI()
app.include_router(example_route)


@app.get("/")
def main_root():
    """Main route."""
    return {"message": "Hello, FastAPI!"}
