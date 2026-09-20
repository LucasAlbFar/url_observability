// service-node is the third observed service in the stack.
//
// It exists to prove a service joins the observability stack by
// declaring labels on its own container, with no edit to prometheus.yml,
// and it serves the same paths the other two services serve, so a route
// name collides across three services — deliberately, and still true.
// What is no longer true is the labelling: this service used to name a
// request `route`/`status_code`/`method`, agreeing with neither of the
// other two, and that measured disagreement is what the request metrics
// derived from spans replaced.
import http from "node:http";

import { trace } from "@opentelemetry/api";
import { logs, SeverityNumber } from "@opentelemetry/api-logs";
import client from "prom-client";

// The third pillar. The API, not a logging library: this service has no
// framework and needs none here either. `emit` reads the active context
// itself, so a record made inside a request carries that request's
// trace id without this file ever naming one. With no provider
// registered the API is a no-op, which is how the tests run.
//
// The logger is resolved per call rather than held in a const: the API
// binds one to whichever provider is registered at that moment, and a
// module-level const would bind to the noop provider for any load order
// where the SDK starts second.
function logError(message, attributes) {
  logs.getLogger("service-node").emit({
    severityNumber: SeverityNumber.ERROR,
    severityText: "ERROR",
    body: message,
    attributes,
  });
  // Beside it, never instead of it. The OTLP record is the only one
  // carrying the trace id and the only one that goes nowhere when the
  // Collector is down — the exporter does not dial on start, so it
  // batches, retries and drops in silence. This leaves `docker logs`
  // something to show when the telemetry path is the thing that broke.
  console.error(message, attributes);
}

// The FastAPI app listens on 8002 and the Go service on 8003; this one
// takes the next port. None is configurable, for the same reason the
// load generator reads no environment: one list of addresses, in one
// place.
const PORT = 8004;

// The default registry already carries the process collectors, and
// process_cpu_seconds_total and process_resident_memory_bytes are what
// the dashboard's resource panels read. They arrive from this one call.
client.collectDefaultMetrics();

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

// chain is where the crossing ends: this service calls nobody, so the
// last span of a trace is the one that closes it. The other two hops
// wrap what they receive; this one only names itself.
function chain(response) {
  writeJSON(response, 200, '{"service":"service-node"}');
}

const routes = {
  "/health": health,
  "/load/io-bound": ioBound,
  "/load/cpu-bound": cpuBound,
  "/chain": chain,
};

// Every request is labelled by the route that matched, never by the path
// that arrived — one label value for every unmatched path rather than
// one per URL somebody tried. What carries that value now is the span
// alone: this service keeps no counter of its own, and the request
// metrics are derived from these spans in the Collector.
//
// The 499-on-close convention left with the counter. It existed so a
// request the client abandoned was not counted as the 200 it never
// sent, and counting is no longer done here; what the derived metrics
// see is whatever status the span carries.
function instrument(route, handler) {
  return (request, response) => {
    // Without this the trace shows `GET` and no route at all: there is
    // no framework here for the instrumentation to read a route
    // template from, so the one place that knows it is this function.
    // It is also the label the derived metrics group by, so removing it
    // empties the route from both pillars at once. The span is absent
    // when the SDK is not loaded, which is how the tests run.
    const span = trace.getActiveSpan();
    if (span) {
      span.setAttribute("http.route", route);
      span.updateName(`${request.method} ${route}`);
    }

    handler(response);
  };
}

function notFound(response) {
  writeJSON(response, 404, '{"detail":"Not Found"}');
}

// /metrics is served by the library and is not instrumented, matching
// the Go service: a scrape should not be traffic in its own graphs.
// What it carries is the default registry — the process and runtime
// collectors, which no span can produce.
// Nothing here rejects: an unhandled rejection ends the process on
// current Node, and writing the header before awaiting would leave a
// scrape hanging until Prometheus times out if a collector threw.
async function metrics(response) {
  try {
    const body = await client.register.metrics();
    response.writeHead(200, { "Content-Type": client.register.contentType });
    response.end(body);
  } catch (error) {
    logError("metrics collection failed", { "error.type": error.name });
    response.writeHead(500, { "Content-Type": "text/plain" });
    response.end(`${error}\n`);
  }
}

// The label a request reports under: the route that matched, or one
// fixed value for every path nobody serves. Exported because it is the
// property worth asserting and the only place it is decided — what it
// returns reaches the span, and from there the derived request metrics.
// Returning `path` here is the cardinality failure this service would
// otherwise demonstrate the wrong way.
export function routeFor(path) {
  return path in routes ? path : "unmatched";
}

export function createServer() {
  return http.createServer((request, response) => {
    const path = new URL(request.url, "http://localhost").pathname;

    if (path === "/metrics") {
      metrics(response);
      return;
    }

    // A handler throwing is an uncaught exception on current Node,
    // which ends the process: nothing above this catches it, because
    // the server callback is where the stack starts. So the line and
    // the 500 are both written here, the way the app writes them in an
    // exception handler.
    //
    // Synchronous throws only, which is what the four routes below do.
    // `ioBound` writes from a `setTimeout` callback, on a stack this
    // never sees — a throw there still ends the process. `/metrics`
    // returns above this and carries its own try/catch.
    try {
      instrument(routeFor(path), routes[path] ?? notFound)(request, response);
    } catch (error) {
      logError("unhandled exception", {
        "error.type": error.name,
        "http.request.method": request.method,
        "url.path": path,
      });
      if (!response.headersSent) {
        response.writeHead(500, { "Content-Type": "text/plain" });
        response.end("Internal Server Error\n");
      }
    }
  });
}

// Skipped when the module is imported by the tests, which bind their own
// port instead.
if (process.argv[1]?.endsWith("main.js")) {
  createServer().listen(PORT, () => {
    console.log(`service-node listening on :${PORT}`);
  });
}
