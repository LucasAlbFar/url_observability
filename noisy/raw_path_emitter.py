"""A service that emits raw paths on purpose.

Every other service in this stack is immune to the failure the
cardinality guard prevents, and immune deliberately: the FastAPI app
labels by route template and files every unmatched path under
`handler="none"`, the Node service labels every unmatched path
`route="unmatched"`, and the Go service exports no path label at all.
So there is nothing here to guard against, and a guard nobody has
watched fire is a guard nobody has tested.

This module is the missing bad citizen. It reports one series per user
id — `/users/1`, `/users/2`, `/users/3` — and reports more of them on
every scrape, so the target's series count is a ramp rather than a
step. It joins the scrape by the same four labels every other service
declares, which is the secondary point: opting in is not a privilege
anyone vets, and that is why the ceiling has to exist.

It runs on the app's image with a different command, so it costs no
Dockerfile, no CI job and no dependency, and it stays behind its own
compose profile so its series only reach prometheus_data when someone
asks for them.
"""

from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = 8005
# The first scrape reports FIRST distinct paths and each one after it
# reports STEP more. At the stack's 5s scrape interval that is ten new
# series a second, which crosses a few hundred inside a minute — fast
# enough to watch happen, slow enough to read the ramp on a graph.
FIRST = 50
STEP = 50
# The app's convention, on purpose. The drop rule selects on the shape
# of a path-carrying label's value, and `handler` is one of the two
# this stack has; a service inventing a third name here would test the
# rule against a label the rule was not written for.
SAMPLE = 'http_requests_total{{handler="/users/{id}",method="GET",status="200"}} 1'
CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


class RawPathMetrics:
    """The exposition body, one scrape at a time.

    The count lives on the instance rather than in a module global so
    that a test binding its own server starts from a known number
    instead of from whatever ran before it.
    """

    def __init__(self, first=FIRST, step=STEP):
        self._paths = first
        self._step = step

    def render(self):
        """Return the body for one scrape, then widen the next one."""
        lines = [
            "# HELP http_requests_total Requests served, by handler.",
            "# TYPE http_requests_total counter",
        ]
        lines.extend(SAMPLE.format(id=index) for index in range(self._paths))
        self._paths += self._step
        return "\n".join(lines) + "\n"


class Handler(BaseHTTPRequestHandler):
    """Serve /metrics and nothing else."""

    # The camel case is BaseHTTPRequestHandler's dispatch contract, not
    # a style choice: the base class looks up "do_" + the method name.
    def do_GET(self):
        if self.path != "/metrics":
            self.send_response(404)
            self.end_headers()
            return
        body = self.server.metrics.render().encode()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPE)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        """Stay quiet: at a 5s scrape interval the default log is noise."""


def create_server(port=PORT):
    """Return a server that has not started listening yet."""
    server = HTTPServer(("", port), Handler)
    server.metrics = RawPathMetrics()
    return server


if __name__ == "__main__":  # pragma: no cover
    create_server().serve_forever()
