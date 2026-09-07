FROM python:3.11.15
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir --upgrade pip && pip install -r requirements/base.txt
# Started through `opentelemetry-instrument`, which loads the
# instrumentations before the app imports anything and reads the OTEL_*
# variables the compose block declares. Readiness is untouched: the
# healthcheck still probes /health.
CMD ["opentelemetry-instrument", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
