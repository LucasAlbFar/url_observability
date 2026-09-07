// Command service-go is the second observed service in the stack.
//
// It exists to prove the observability stack attaches to something that
// is not the FastAPI app, and it serves the same paths that app serves,
// so a route name collides across services — deliberately, and still
// true. What is no longer true is the metric names: this service used to
// publish its own `code`/`method` convention against the app's
// `handler`/`status`, and that disagreement is what the request metrics
// derived from spans replaced.
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"time"

	"github.com/prometheus/client_golang/prometheus/promhttp"
	"go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp"
	"go.opentelemetry.io/otel/propagation"
	"go.opentelemetry.io/otel/sdk/resource"
	"go.opentelemetry.io/otel/sdk/trace"
	// The semantic convention version, pinned in the import path
	// because Go has no other place to pin it. v1.43.0 is the one
	// otelhttp v0.71.0 itself emits, so the attribute this file adds
	// cannot disagree with the ones the middleware adds.
	semconv "go.opentelemetry.io/otel/semconv/v1.43.0"
	oteltrace "go.opentelemetry.io/otel/trace"
)

// The FastAPI app listens on 8002; this one takes the next port. Neither
// is configurable, for the same reason the load generator reads no
// environment: one list of addresses, in one place.
const addr = ":8003"

// The next hop of the chain, and the client that makes it. A var rather
// than a const so a test can point it at a local stub: it is not
// configuration, and this service still reads no environment.
var (
	nextChain = "http://service-node:8004/chain"
	// The transport is what carries the trace across the hop: it writes
	// the traceparent header of the span this request is inside. A plain
	// client makes the same call and starts a second trace on the other
	// side, which is the shape this stack had before it was wrapped.
	chainClient = &http.Client{
		Timeout:   10 * time.Second,
		Transport: otelhttp.NewTransport(http.DefaultTransport),
	}
)

// startTracing configures the global tracer provider and returns
// nothing to close: the process is killed rather than shut down, so the
// batcher's last five seconds of spans are dropped on a restart. That
// is accepted here — the alternative is signal handling in a service
// whose whole point is being small.
//
// Every destination comes from the OTEL_* variables in the compose
// block. `resource.Default` is what reads OTEL_SERVICE_NAME, so the
// name a trace is keyed by is declared beside the label the metrics are
// keyed by, and neither is written here.
func startTracing(ctx context.Context) error {
	exporter, err := otlptracehttp.New(ctx)
	if err != nil {
		return err
	}
	otel.SetTracerProvider(trace.NewTracerProvider(
		trace.WithBatcher(exporter),
		trace.WithResource(resource.Default()),
	))
	// Not a default in this SDK, and the omission is invisible: without
	// a propagator the incoming traceparent is ignored, every request
	// starts its own trace, and the only symptom is three one-service
	// traces where there should be one of three.
	otel.SetTextMapPropagator(propagation.NewCompositeTextMapPropagator(
		propagation.TraceContext{},
		propagation.Baggage{},
	))
	return nil
}

// instrument wraps a handler in the trace, which is now the only pillar
// this service feeds per request: the counters it used to keep were
// replaced by metrics derived from these very spans. The route is passed
// in because otelhttp is handed a mux with no pattern to read, so it
// names every span after the method alone. Setting http.route here is
// the same sentence the Node service writes for the same reason, it
// makes the span name `GET /chain`, and it is the label the derived
// metrics carry — remove it and the route disappears from both pillars
// at once.
func instrument(route string, next http.HandlerFunc) http.Handler {
	routed := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		oteltrace.SpanFromContext(r.Context()).SetAttributes(semconv.HTTPRoute(route))
		next.ServeHTTP(w, r)
	})
	return otelhttp.NewHandler(
		routed,
		route,
		otelhttp.WithSpanNameFormatter(func(_ string, r *http.Request) string {
			return r.Method + " " + route
		}),
	)
}

func writeJSON(w http.ResponseWriter, body string) {
	w.Header().Set("Content-Type", "application/json")
	fmt.Fprintln(w, body)
}

// health is the route that collides: the FastAPI app serves the same
// path, and both healthchecks probe it.
func health(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, `{"status":"ok"}`)
}

func ioBound(w http.ResponseWriter, r *http.Request) {
	time.Sleep(2 * time.Second)
	writeJSON(w, `{"message":"I/O-bound task completed"}`)
}

// cpuBound burns CPU for roughly as long as the FastAPI equivalent does.
// The count is two hundred times that one's ten million because Go runs
// the same loop that much faster: measured here, ten million iterations
// take Python 0.79s and two billion take Go 0.62s. The result is
// returned so the compiler cannot discard the work.
func cpuBound(w http.ResponseWriter, r *http.Request) {
	result := 0
	for i := 0; i < 2_000_000_000; i++ {
		result++
	}
	writeJSON(w, fmt.Sprintf(`{"message":"CPU-bound task completed","result":%d}`, result))
}

// chain calls the next service and returns what it answered, wrapped.
// It is the middle hop: the one that shows a trace context surviving a
// service rather than merely leaving one.
func chain(w http.ResponseWriter, r *http.Request) {
	// The request's context, not the background one: it carries the
	// span this handler is inside, and the client transport reads it to
	// write the traceparent header.
	body, err := call(r.Context(), nextChain)
	if err != nil {
		// 502 rather than 500, for the reason the app returns one: the
		// failure is downstream, and the code says where to look.
		//
		// json.Marshal rather than %q, which is Go quoting and not JSON
		// encoding: an error carrying a non-printable byte comes out as
		// \xNN, which no JSON parser accepts. On the one path where the
		// message is the whole diagnostic.
		detail, _ := json.Marshal(err.Error())
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusBadGateway)
		fmt.Fprintf(w, `{"detail":%s}`+"\n", detail)
		return
	}
	writeJSON(w, fmt.Sprintf(`{"service":"service-go","next":%s}`, body))
}

// call fetches a JSON body, failing on anything but 200 so a downstream
// error is not wrapped as if it were an answer.
func call(ctx context.Context, url string) ([]byte, error) {
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, err
	}
	response, err := chainClient.Do(request)
	if err != nil {
		return nil, err
	}
	defer response.Body.Close()

	if response.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("%s: %s", url, response.Status)
	}
	body, err := io.ReadAll(response.Body)
	if err != nil {
		return nil, err
	}
	return bytes.TrimSpace(body), nil
}

// notFound answers what no route claimed, and exists to be
// instrumented: the mux's own 404 carries neither counter nor span, so
// until this handler was wired an unknown path was absent from both
// pillars. The body is the one the Node service answers with, the way
// /health is identical across the three.
func notFound(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusNotFound)
	fmt.Fprintln(w, `{"detail":"Not Found"}`)
}

func newMux() *http.ServeMux {
	mux := http.NewServeMux()
	mux.Handle("/health", instrument("/health", health))
	mux.Handle("/load/io-bound", instrument("/load/io-bound", ioBound))
	mux.Handle("/load/cpu-bound", instrument("/load/cpu-bound", cpuBound))
	mux.Handle("/chain", instrument("/chain", chain))
	// The default registry, which is the process and Go runtime
	// collectors now that this service counts no request of its own.
	// Untraced: a scrape is not traffic in its own graphs, and at one
	// every five seconds it would be most of what the trace store holds.
	mux.Handle("/metrics", promhttp.Handler())
	// Everything else, under one label value rather than one per path —
	// the same `unmatched` the Node service reports. Registered last and
	// as "/", which every pattern above outranks by being longer, so the
	// scrape is not swallowed by it.
	mux.Handle("/", instrument("unmatched", notFound))
	return mux
}

func main() {
	if err := startTracing(context.Background()); err != nil {
		log.Fatalf("tracing: %v", err)
	}
	log.Printf("service-go listening on %s", addr)
	log.Fatal(http.ListenAndServe(addr, newMux()))
}
