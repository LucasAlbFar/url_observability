// Command service-go is the second observed service in the stack.
//
// It exists to prove the observability stack attaches to something that
// is not the FastAPI app. Two consequences of that purpose are visible
// here and are deliberate: it serves the same paths the FastAPI app
// serves, so a route name collides across services; and it does not
// imitate that app's metric names, so the two services disagree about
// how a request is labelled. Both are the defect this service was added
// to expose, not oversights to tidy up.
package main

import (
	"fmt"
	"log"
	"net/http"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

// The FastAPI app listens on 8002; this one takes the next port. Neither
// is configurable, for the same reason the load generator reads no
// environment: one list of addresses, in one place.
const addr = ":8003"

// Registered on the default registry, which already carries the process
// and Go runtime collectors. The labels are the ones promhttp fills in
// by itself. There is no route label: client_golang does not have one,
// and adding a `handler` label to match the FastAPI instrumentator would
// defeat the reason this service exists.
var (
	requests = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "http_requests_total",
		Help: "Requests served, by response code and method.",
	}, []string{"code", "method"})

	duration = promauto.NewHistogramVec(prometheus.HistogramOpts{
		Name:    "http_request_duration_seconds",
		Help:    "Request duration in seconds, by response code and method.",
		Buckets: prometheus.DefBuckets,
	}, []string{"code", "method"})
)

func instrument(next http.HandlerFunc) http.Handler {
	return promhttp.InstrumentHandlerCounter(
		requests,
		promhttp.InstrumentHandlerDuration(duration, next),
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

func newMux() *http.ServeMux {
	mux := http.NewServeMux()
	mux.Handle("/health", instrument(health))
	mux.Handle("/load/io-bound", instrument(ioBound))
	mux.Handle("/load/cpu-bound", instrument(cpuBound))
	mux.Handle("/metrics", promhttp.Handler())
	return mux
}

func main() {
	log.Printf("service-go listening on %s", addr)
	log.Fatal(http.ListenAndServe(addr, newMux()))
}
