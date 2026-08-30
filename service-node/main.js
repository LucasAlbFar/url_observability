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

// cpuBound burns CPU for roughly as long as the other two do — Go's
// 0.62s, Python's 0.79s. It is bounded by a **clock**, not by an
// iteration count, and that is not a style choice: Node runs one thread,
// so this loop makes the whole process unresponsive for its duration,
// /health included. A fixed count stretches with the machine — the same
// billion iterations measured 0.81s idle here and 2.24s on a loaded one
// — while the compose healthcheck's timeout does not. A deadline keeps
// the blackout the same length everywhere, comfortably inside that
// budget. The result is returned so the optimiser cannot discard the
// work.
const CPU_BURN_MS = 800;

function cpuBound(response) {
  const deadline = Date.now() + CPU_BURN_MS;
  let result = 0;
  while (Date.now() < deadline) {
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
    let recorded = false;

    const record = () => {
      if (recorded) {
        return;
      }
      recorded = true;
      const labels = {
        route,
        method: request.method,
        // `finish` means the response was sent; `close` alone means the
        // client hung up first. 499 is nginx's code for exactly that,
        // borrowed so an abandoned request cannot be counted as the 200
        // it never sent. Dropping it instead — which listening only for
        // `finish` does — makes a failing request vanish from the
        // graphs, which is the opposite of the point.
        status_code: response.writableFinished ? response.statusCode : 499,
      };
      end(labels);
      requests.inc(labels);
    };

    // Both fire for a response that completes, so the first one wins.
    response.on("finish", record);
    response.on("close", record);
    handler(response);
  };
}

function notFound(response) {
  writeJSON(response, 404, '{"detail":"Not Found"}');
}

// /metrics is served by the library and is not instrumented, matching
// the Go service: a scrape should not be traffic in its own graphs.
// Nothing here rejects: an unhandled rejection ends the process on
// current Node, and writing the header before awaiting would leave a
// scrape hanging until Prometheus times out if a collector threw.
async function metrics(response) {
  try {
    const body = await client.register.metrics();
    response.writeHead(200, { "Content-Type": client.register.contentType });
    response.end(body);
  } catch (error) {
    response.writeHead(500, { "Content-Type": "text/plain" });
    response.end(`${error}\n`);
  }
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
