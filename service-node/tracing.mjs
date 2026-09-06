// Loaded by `node --import` before main.js, so node:http is patched
// before the server imports it.
//
// Two things are needed, and the second is the one that is easy to
// miss. `register` installs the resolver hook that makes an ES module's
// `import http from "node:http"` see the patched module: with the SDK
// alone the instrumentation patches the CommonJS require and this
// service, which is ESM, produces no spans at all — no error, no
// warning, an empty trace store.
//
// The SDK is assembled here rather than pulled in through
// @opentelemetry/auto-instrumentations-node, which would install some
// forty instrumentations for frameworks and databases this service does
// not have. It is also the only place a scrape can be kept out of the
// trace store: unlike the Python SDK, this one has no environment
// variable for excluding a URL, and one trace every five seconds would
// be most of what the store holds.
import { register } from "node:module";

import { HttpInstrumentation } from "@opentelemetry/instrumentation-http";
import { NodeSDK } from "@opentelemetry/sdk-node";

register("@opentelemetry/instrumentation/hook.mjs", import.meta.url);

// Everything else — the service name, the endpoint, the protocol, which
// signals are exported — comes from the OTEL_* variables in this
// service's compose block. Nothing about the destination is written
// here.
const sdk = new NodeSDK({
  instrumentations: [
    new HttpInstrumentation({
      ignoreIncomingRequestHook: (request) =>
        new URL(request.url, "http://localhost").pathname === "/metrics",
    }),
  ],
});

sdk.start();
