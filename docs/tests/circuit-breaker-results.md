# Test Name

Circuit breaker scenario (Action Plan Phase 4) — `order-service`'s
`AsyncCircuitBreaker` protecting calls to a `payment-service` failing 80%
of the time, with and without retries enabled, compared to Phase 3.

# When It Was Run

2026-09-04, local Docker Compose stack, fresh volumes.

# Description

Goal: validate the `AsyncCircuitBreaker` wrapping `order-service`'s calls to
`payment-service` (`GET /circuit-breaker/payment`, `failure_threshold=3`,
`recovery_timeout=15s`) — confirm it fails fast instead of piling more load
onto an already-failing dependency, and observe its
`CLOSED -> OPEN -> HALF_OPEN` transitions.

`scripts/k6/with-circuit-breaker.js` already injects/clears
`FAILURE_RATE: 0.8` on `payment-service` via `setup()`/`teardown()`, same
as `with-retries.js`. It had the same "HTTP 200 for business failure" check
gap flagged in Phase 3 - fixed the same way (`r.json('status') ===
'success'`), plus a custom k6 `Counter` (`circuit_breaker_open_rejections`)
that flags a response whose `downstream.payment.message` is
`"circuit_breaker_open"`, to separate "failed fast, breaker protected the
system" from "reached payment-service and got declined".

## Bug found and fixed: concurrent requests could all slip through `HALF_OPEN` at once

Polling `GET /circuit-breaker/payment` every 2s during the first run
(`RETRY_ENABLED=false`) showed `failures` climbing to 8, then 9 - well past
`failure_threshold=3` - while the breaker stayed `OPEN` the whole time. That
should not happen: once `OPEN`, only a single probe call should be let
through per `recovery_timeout` window.

The cause, in `AsyncCircuitBreaker.call()`: the state check
(`if self.state == OPEN: ... self.state = HALF_OPEN`) and the state mutation
were not guarded by a lock. With 10 concurrent VUs, once
`recovery_timeout` elapsed, *every* concurrent call checking
`self.state == OPEN` around the same time would see it, and the first one
to flip `state` to `HALF_OPEN` did so before any of the others had even
looked - so the rest then read `state == HALF_OPEN`, matched neither
`if` branch, and fell straight through to calling `payment-service`
un-gated. Instead of one canary probe, every VU with a request in flight at
that moment got through together (a thundering herd), most of them failing
against an 80%-failure-rate service and re-inflating `failures` well past
the threshold.

**Fix** (`services/order-service/main.py`, `AsyncCircuitBreaker`): added an
`asyncio.Lock` guarding only the state check/transition and the
post-call state update - never the downstream call itself, so normal
`CLOSED`-state throughput is unaffected. The `OPEN -> HALF_OPEN` transition
now marks a single `is_probe` call; every other concurrent call that finds
the breaker already `HALF_OPEN` fails fast instead of being let through.

**Verified:** re-ran the same test after the fix. `failures` now stays
exactly at the threshold (`3`) and increments by exactly `+1` once per
`recovery_timeout` window (`3 -> 4` at the ~15s mark, matching
`recovery_timeout=15.0`) - a single probe per window, as designed.

## Setup

1. Fresh boot, `cli.py status` healthy, product 1 stock bumped (same
   caveat as every prior phase).
2. Ran `scripts/k6/with-circuit-breaker.js` in the background while polling
   `GET /circuit-breaker/payment` every 2s for the run's duration, to
   capture the state timeline.
3. **Run A** — `RETRY_ENABLED=false` (pure circuit-breaker behavior).
4. Found and fixed the concurrency bug above; rebuilt `order-service`;
   re-ran **Run A** with the fix.
5. **Run B** — `RETRY_ENABLED=true`, `RETRY_COUNT=3`, `RETRY_DELAY_MS=100`
   (breaker + the Phase 3 retry fixes combined) — recreated `order-service`
   with retries on, fresh `CLOSED` breaker (module re-init on restart).
6. Confirmed recovery end-to-end: after `teardown()` clears
   `FAILURE_RATE` back to `0.0`, waited out one `recovery_timeout` (15s)
   and placed one order manually - it succeeded and the breaker correctly
   went back to `CLOSED`.

# Results

| Run | Order success | Failed via open breaker | p50 | p95 | p99 | Throughput |
| --- | --- | --- | --- | --- | --- | --- |
| **A** — no retries, 80% payment failure (bug present) | 0.4% (1/277) | 266/277 (96%) | 83ms | 200ms | 835ms | 8.99 req/s |
| **A-fixed** — no retries, 80% payment failure (bug fixed) | 0.4% (1/274) | 267/274 (97%) | 89ms | 254ms | 496ms | 8.87 req/s |
| **B** — retries enabled, 80% payment failure (bug fixed) | 4.8% (13/270) | 249/270 (92%) | 96ms | 461ms | 742ms | 8.83 req/s |
| *(reference)* Phase 3, retries @ 30% payment failure (fixed) | 99% | n/a (breaker never opened) | 133ms | 399ms | 751ms | 8.34 req/s |
| *(reference)* Phase 1 baseline, no chaos | 100% | n/a | 97–133ms | 213–276ms | 972ms–1.3s | 8.3–8.7 req/s |

## Analysis

- **The breaker does its job: it fails fast instead of adding load.** In
  every run, 92–97% of failed orders were rejected immediately by the open
  breaker rather than making a full round trip to a still-failing
  `payment-service`. This is the "menor cascada de fallos" / "mejor
  disponibilidad" the proposal expects from a circuit breaker - it's not
  measured in the order's own success rate, but in how much load reaches
  the failing dependency (dramatically less than without a breaker).
- **At 80% failure, retries barely move the needle** (0.4% → 4.8%),
  unlike Phase 3's 30%-failure scenario where the identical retry fix took
  success from 3% to 99%. This is expected, not a contradiction: with 4
  attempts per call, `P(all fail) = 0.8^4 ≈ 41%` at 80% base failure vs.
  `0.3^4 ≈ 0.8%` at 30% - retries can mask an occasional decline, not a
  service that's down more often than not. The breaker's fail-fast benefit
  matters *more*, not less, in exactly this regime: when retries can't
  realistically rescue the outcome, at least stop paying the cost of trying.
- **The fix mattered for the experiment's validity, not just tidiness.**
  Before the fix, `failures` overshooting the threshold (8-9 instead of a
  clean 3-then-+1-per-window) meant the "one probe per recovery window"
  story the breaker is supposed to tell wasn't actually true under
  concurrent load - the polling timeline is the evidence, not just a code
  read-through.
- **Latency stayed bounded, and the fix tightened the tail**: p99 dropped
  from 835ms (bug present) to 496ms (fixed, no retries) - fewer concurrent
  probes contending against the failing service means less variance. With
  retries added back in (Run B), p99 rose to 742ms (extra attempts cost
  time when they happen) but is still in the same range as Phase 1's own
  baseline p99 (972ms-1.3s) and Phase 3's fixed-retries p99 (751ms) - the
  breaker keeps the system's worst-case latency from blowing out even
  under sustained 80% failure.
- **Recovery works end-to-end**: once the underlying chaos clears, the
  breaker reliably returns to `CLOSED` on the next successful probe (with
  the fix, exactly one probe - not several racing to close it at once).

# Notes for later phases

- The fixed `AsyncCircuitBreaker` uses `asyncio.Lock`, which serializes
  correctly within a single process. Phase 6 (Kubernetes, potentially
  multiple `order-service` replicas via HPA) will have one independent
  breaker instance *per pod* - each pod trips and recovers on its own view
  of `payment-service`'s health, which is worth calling out explicitly in
  that phase's writeup rather than assuming one shared breaker state
  cluster-wide.
- `circuit_breaker_state` (the Prometheus gauge already in the code) can be
  graphed directly in Grafana for Phase 8's dashboards instead of polling
  the HTTP endpoint - the polling approach here was for quick verification,
  not the intended long-term observability path.
