# Tooling reference

How the control and load-testing tools introduced/changed while executing
`docs/ACTION-PLAN.md` actually work under the hood: `cli.py`, the chaos and
circuit-breaker mechanisms it drives, and the k6/JMeter load-testing setup.
This complements the Action Plan (which tracks *what* was done and *when*)
with *how* each piece works technically.

## cli.py — terminal control surface

**Why it exists:** the web UI (`services/frontend/`) was removed to make the
project fully headless (Action Plan Phase 0). `cli.py` is the replacement
control surface — it does not add any new HTTP endpoint anywhere; it is a
thin client over the microservices' existing APIs.

**Design:**
- Standard library only (`argparse`, `json`, `urllib.request`) — no new
  runtime dependency for the team to install.
- `SERVICES` is a small registry mapping a short key (`order`, `user`,
  `inventory`, `payment`, `notification`) to its full compose service name
  and host-exposed port, read from the same env vars as `.env.example`
  (`ORDER_SERVICE_PORT`, etc.), defaulting to the same values. This means
  `cli.py` talks to the stack the same way a developer's browser/curl would
  — over the host-published ports — not over the internal Docker network.
- `http_request()` is the one place that calls `urllib.request`; every
  subcommand funnels through it so error handling (HTTP errors, connection
  errors, timeouts) is consistent everywhere.
- Subcommands are grouped by service (`users`, `inventory`, `order`,
  `payments`, `notifications`) plus two cross-cutting ones (`chaos`,
  `circuit-breaker`) and `status`.
- **Confirmation gating:** `chaos set` and `chaos reset` are the only
  commands that mutate shared, live runtime state that affects everyone
  hitting the same stack (injecting/clearing failure into a running
  service). Both prompt for `y/N` confirmation unless `--yes`/`-y` is
  passed, via the `confirm()` helper. No other command needs this: placing
  an order, seeding mock data, or reading counts do not change how the
  system behaves for other callers.

**Adding a new subcommand:** add a `cmd_<name>` function returning an exit
code (0 success, non-zero failure), then wire it into `build_parser()` with
`sub.add_parser(...).set_defaults(func=cmd_<name>)`. Keep it a thin wrapper
around one HTTP call plus `print_json()` — `cli.py` is intentionally not a
place for business logic, all of that lives in the services themselves.

## Chaos engineering mechanism (`/chaos/config`)

Each service (`order`, `user`, `inventory`, `payment`, `notification`)
keeps three module-level variables — `FAILURE_RATE`, `LATENCY_MS`,
`TIMEOUT_RATE` — initialized from environment variables at process start.
`POST /chaos/config` (present on every service) mutates these `global`s at
runtime; there is no persistence and no restart required. This only works
safely because every service's Dockerfile runs a single Uvicorn process
(no `--workers N`), so there is exactly one copy of that state per
container — with multiple workers, each would have its own independent
chaos config and `cli.py chaos set` would only affect whichever worker
handled that particular request.

Two slightly different failure-injection shapes exist in the codebase:

- `user-service` and `inventory-service` use a single `apply_chaos()`
  helper that applies latency, then timeout, then **raises
  `HTTPException(503)`** on simulated failure — a transport-level error.
- `order-service`, `payment-service` and `notification-service` split this
  into `apply_chaos_latency_and_timeout()` (applies latency/timeout only)
  and a separate `should_simulate_failure()` boolean check, and return a
  normal `200 OK` with a structured `{"status": "error", ...}` body instead
  of raising. This is why `scripts/k6/baseline.js` and
  `scripts/jmeter/baseline.jmx` both had to add a business-level check on
  the response body — the HTTP status code alone cannot tell success from
  failure for these three services.

**Retry semantics (fixed in Phase 3):** `order-service`'s `call_service()`
originally only retried on transport-level exceptions, which meant
`RETRY_ENABLED` never actually retried a 503 from `user-service`/
`inventory-service` (httpx doesn't raise for a non-2xx response) or a
200+error-body decline from `payment-service`/`notification-service`. Fixed
two ways: `call_service()` itself now also retries on 5xx responses
(covers user validation and inventory availability/reserve with no call-site
changes needed), and `do_payment()`/the notification call each got their
own attempt loop that retries on a non-success response body too, since
"success" is a different business field per endpoint that `call_service()`
has no generic way to check. See `docs/tests/retries-results.md` for the
full writeup and before/after numbers per service.

## Circuit breaker mechanism (`order-service` → `payment-service`)

`order-service/main.py` defines `AsyncCircuitBreaker`, a small in-process
state machine wrapping every call to `payment-service`:

- **States:** `CLOSED` (normal) → `OPEN` (failing fast) → `HALF_OPEN`
  (probing recovery) → back to `CLOSED` or `OPEN`.
- **Trip condition:** `failure_threshold=3` consecutive failures (any
  exception from the wrapped call, including a `DownstreamServiceError`
  raised when `payment-service` returns a non-2xx or a
  `{"status": "error"}` body) opens the circuit.
- **Recovery:** after `recovery_timeout=15.0` seconds in `OPEN`, the next
  call is let through as a probe (`HALF_OPEN`); success closes the circuit
  and resets the failure count, another failure re-opens it.
- **Observability:** every transition updates the `circuit_breaker_state`
  Prometheus gauge (`0=CLOSED, 1=HALF_OPEN, 2=OPEN`, labeled
  `service="payment_service"`), and the current state is also readable
  directly via `GET /circuit-breaker/payment` (what
  `cli.py circuit-breaker status` calls).

This is a single global instance (`payment_cb`) per `order-service`
process — same single-worker caveat as the chaos config above (and, later,
one independent instance per pod if `order-service` is ever scaled
horizontally in Kubernetes).

**Concurrency fix (Phase 4):** the `OPEN -> HALF_OPEN` transition is now
guarded by an `asyncio.Lock` so exactly one probe call gets through per
`recovery_timeout` window. Before the fix, every concurrent request in
flight when the timeout elapsed would independently see the flipped state
and slip through together instead of a single canary probe — confirmed by
polling `GET /circuit-breaker/payment` under load and watching `failures`
overshoot `failure_threshold` (8-9 instead of a clean 3, then +1 per
window). The lock only guards the state check/transition and the post-call
state update, never the actual downstream call, so it adds no cost to
normal `CLOSED`-state throughput. See `docs/tests/circuit-breaker-results.md`
for the full before/after.

## k6 (`scripts/k6/`)

`baseline.js`, `stress-test.js`, `with-retries.js` and
`with-circuit-breaker.js` all POST to `order-service`'s `/orders`. They are
meant to run via the official `grafana/k6` image attached to the compose
network (see README "k6 con Docker"), not against `localhost` from inside
the container.

`baseline.js` was fixed while executing Phase 1 (see
`docs/tests/baseline-results.md` for the full rationale and results):

- Added a **business-level check** — `r.json('status') === 'success'` — in
  addition to the original HTTP-status check, because `order-service`
  returns HTTP 200 for business failures too (see the chaos section above).
- Added `summaryTrendStats: [..., 'p(99)', ...]` to the script's `options`
  so the printed summary includes p99 (k6's default summary stops at p95).

`with-retries.js` and `with-circuit-breaker.js` got the same business-check
and `summaryTrendStats` fix in Phases 3-4 (see
`docs/tests/retries-results.md` and `docs/tests/circuit-breaker-results.md`).
`with-circuit-breaker.js` additionally has a custom k6 `Counter`
(`circuit_breaker_open_rejections`) that flags a response whose
`downstream.payment.message` is `"circuit_breaker_open"`, separating
"failed fast, breaker protected the system" from "reached payment-service
and got declined" in the summary.

**Windows/Git Bash gotcha:** running `docker run ... -v "$(pwd)/scripts/k6:/scripts" ... /scripts/baseline.js`
from Git Bash on Windows fails unless prefixed with `MSYS_NO_PATHCONV=1` —
without it, MSYS's automatic path conversion mangles the `/scripts/...`
argument into a bogus Windows path *before* Docker ever sees it, and (if
you're unlucky with the exact argument shape) can even leave a stray empty
directory behind on the host from the mangled path.

## JMeter (`scripts/jmeter/baseline.jmx`)

Authored in Phase 2 as the concurrent-user counterpart to `baseline.js` —
same request, same 1s think time, same "no resilience mechanisms" scenario
— so the team has both traffic-generation styles the proposal asks for.
Full parameter table and run instructions: `docs/tests/jmeter-usage.md`.

Two things worth knowing about how the file itself is built:
- Every tunable (`HOST`, `PORT`, `USER_ID`, `PRODUCT_ID`, `QUANTITY`,
  `USERS`, `RAMP_UP`, `DURATION`) is a Test Plan "User Defined Variable"
  whose value is `${__P(NAME,default)}` — JMeter's `__P` function resolves
  to a `-JNAME=value` command-line property if one was passed, otherwise
  falls back to `default`. This is what makes every run parameterizable
  without editing the XML.
- It carries the same business-status `Response Assertion` (substring
  match on `"status":"success"`) as k6's fix, for the same reason.

**This plan has been authored but not executed** — only validated for
XML well-formedness (`xml.etree.ElementTree`). JMeter itself is not
installed as part of Phase 2 by design; running it for real belongs to
whoever executes Phase 3 onward.

## Process notes (things that would otherwise be re-discovered the hard way)

- **Seed stock is small on purpose** (`db/init.sql` gives product 1 only
  12 units) — realistic seed data, not load-test data. Any load test that
  reuses `product_id=1` needs a one-time stock bump first
  (`UPDATE products SET quantity = 100000 WHERE id = 1;` — only the
  `quantity` column matters, see `construct_product_model` in
  `services/inventory-service/main.py`), or it mostly measures inventory
  exhaustion instead of system performance.
- **Prometheus's default histogram buckets are coarse**
  (`http_request_duration_seconds_bucket` has boundaries at 0.1/0.5/1.0s
  for `/orders`) — good enough to sanity-check k6's client-side
  percentiles, not precise enough to replace them.
- **k6 and server-side metrics measure slightly different things:** k6's
  `http_req_duration` includes client-observed network round-trip;
  `order-service`'s own histogram only times request handling. Expect the
  server-side numbers to run a little faster than k6's.
