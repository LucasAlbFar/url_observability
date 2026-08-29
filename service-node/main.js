// service-node is the third observed service in the stack.
//
// It exists to prove a service joins the observability stack by
// declaring labels on its own container, with no edit to prometheus.yml.
// Two consequences of that purpose are visible here and are deliberate:
// it serves the same paths the other two services serve, so a route name
// collides across three services; and it labels a request the way this
// library leaves the author to label it, which agrees with neither of
// the other two. The disagreement is the measurement this service was
// added to produce, not an oversight to tidy up.
import http from "node:http";
import client from "prom-client";

// The FastAPI app listens on 8002 and the Go service on 8003; this one
// takes the next port. None is configurable, for the same reason the
// load generator reads no environment: one list of addresses, in one
// place.
const PORT = 8004;

// The default registry already carries the process collectors, and
// process_cpu_seconds_total and process_resident_memory_bytes are what
// the dashboard's resource panels read. They arrive from this one call.
client.collectDefaultMetrics();

// prom-client does not instrument HTTP, so unlike client_golang and the
// FastAPI instrumentator it hands the author the label names. These are
// a third convention on purpose: `handler`/`status` would imitate the
// app and `code`/`method` the Go service, and either would defeat the
// reason this service exists. The metric names are the shared part —
// they are the Prometheus convention, which both other libraries follow.
const requests = new client.Counter({
  name: "http_requests_total",
  help: "Requests served, by route, response code and method.",
  labelNames: ["route", "status_code", "method"],
});

const duration = new client.Histogram({
  name: "http_request_duration_seconds",
  help: "Request duration in seconds, by route, response code and method.",
  labelNames: ["route", "status_code", "method"],
});

function writeJSON(response, statusCode, body) {
  response.writeHead(statusCode, { "Content-Type": "application/json" });
  response.end(body + "\n");
}

// health is the route that collides: all three services serve this path
// and all three healthchecks probe it.
function health(response) {
  writeJSON(response, 200, '{"status":"ok"}');
}

function ioBound(response) {
  setTimeout(() => {
    writeJSON(response, 200, '{"message":"I/O-bound task completed"}');
  }, 2000);
}

// cpuBound burns CPU for roughly as long as the other two do. The count
// is a tenth of the Go service's two billion because that is what makes
// the durations comparable: measured on node:24.20.0, a billion
// iterations take 0.81s against Go's 0.62s for two billion and Python's
// 0.79s for ten million. The result is returned so the optimiser cannot
// discard the work.
function cpuBound(response) {
  let result = 0;
  for (let i = 0; i < 1_000_000_000; i++) {
    result++;
  }
  writeJSON(
    response,
    200,
    `{"message":"CPU-bound task completed","result":${result}}`,
  );
}

const routes = {
  "/health": health,
  "/load/io-bound": ioBound,
  "/load/cpu-bound": cpuBound,
};

// Every request is labelled by the route that matched, never by the path
// that arrived. An unmatched path is one label value rather than one per
// URL somebody tried — the difference between a bounded series count and
// the cardinality failure a later feature exists to prevent.
function instrument(route, handler) {
  return (request, response) => {
    const end = duration.startTimer();
    response.on("finish", () => {
      const labels = {
        route,
        status_code: response.statusCode,
        method: request.method,
      };
      end(labels);
      requests.inc(labels);
    });
    handler(response);
  };
}

function notFound(response) {
  writeJSON(response, 404, '{"detail":"Not Found"}');
}

// /metrics is served by the library and is not instrumented, matching
// the Go service: a scrape should not be traffic in its own graphs.
async function metrics(response) {
  response.writeHead(200, { "Content-Type": client.register.contentType });
  response.end(await client.register.metrics());
}

export function createServer() {
  return http.createServer((request, response) => {
    const path = new URL(request.url, "http://localhost").pathname;

    if (path === "/metrics") {
      metrics(response);
      return;
    }

    const handler = routes[path];
    if (handler) {
      instrument(path, handler)(request, response);
      return;
    }
    instrument("unmatched", notFound)(request, response);
  });
}

// Skipped when the module is imported by the tests, which bind their own
// port instead.
if (process.argv[1]?.endsWith("main.js")) {
  createServer().listen(PORT, () => {
    console.log(`service-node listening on :${PORT}`);
  });
}
