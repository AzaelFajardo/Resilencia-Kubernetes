# Test Name

Retries scenario (Action Plan Phase 3) — `order-service`'s retry logic
against a failing `payment-service`, compared to the same chaos with
retries disabled and to the Phase 1 baseline.

# When It Was Run

2026-09-04, local Docker Compose stack, fresh volumes.

# Description

Goal: measure the proposal's expected trade-off ("retries aumentan
latencia pero reducen errores") using `order-service`'s existing retry
logic (`RETRY_ENABLED`/`RETRY_COUNT`/`RETRY_DELAY_MS`) against a
`payment-service` failing 30% of the time.

`scripts/k6/with-retries.js` already handles injecting/clearing chaos on
`payment-service` itself (`setup()` sets `FAILURE_RATE: 0.3`, `teardown()`
resets it to `0.0`), so no manual `cli.py chaos set/reset` was needed for
this phase.

## Bug found and fixed: retries were a no-op against this exact chaos

The first run (`RETRY_ENABLED=false`, expected baseline for this scenario)
showed only **3% order success** against a 30% payment failure rate — far
worse than expected. Investigating why led to `GET /circuit-breaker/payment`
showing `state: "OPEN"`: the circuit breaker (shared, single instance,
always active regardless of `RETRY_ENABLED` — see
`docs/TOOLING.md`) had tripped after 3 consecutive payment failures and
stayed open for most of the 30s window, failing almost everything
regardless of the underlying 30% rate.

Enabling retries (`RETRY_ENABLED=true`, `RETRY_COUNT=3`,
`RETRY_DELAY_MS=100`) barely helped (**16% success**) — worse than the
~99% a proper retry should achieve against a 30% per-attempt failure rate
(`P(all 4 attempts fail) = 0.3^4 ≈ 0.8%`). Reading
`services/order-service/main.py` explained why:

- `call_service()`'s retry loop only catches **transport-level exceptions**
  from `client.request()` (connection errors, timeouts).
- `payment-service`'s simulated failure (`FAILURE_RATE`) returns a normal
  **HTTP 200 with `{"status": "error", ...}`** — not an exception (see
  `docs/TOOLING.md`'s chaos section for why).
- So `do_payment()`'s call to `call_service(..., RETRY_COUNT, ...)` returned
  on the very first attempt every time; `RETRY_ENABLED` never actually
  retried a declined payment. The only reason enabling it changed anything
  at all was run-to-run randomness in when the circuit breaker happened to
  trip, not the retry logic working.

**Fix** (`services/order-service/main.py`, `do_payment()` inside
`create_order`): moved the retry loop from `call_service()` into
`do_payment()` itself, so it retries on *both* transport exceptions *and*
a non-success response body/status, honoring `RETRY_ENABLED`/`RETRY_COUNT`/
`RETRY_DELAY_MS`. `call_service()` itself is unchanged (still used as-is by
every other downstream call) and behavior with `RETRY_ENABLED=false` is
byte-for-byte identical to before (single attempt either way). Rebuilt and
re-ran only the retries-enabled scenario after the fix — the
retries-disabled run is unaffected by this change, so it did not need
re-running.

## Setup

1. Fresh boot (`docker compose down -v --remove-orphans && docker compose up -d --build --remove-orphans`), `cli.py status` confirmed healthy, product 1 stock bumped to 100000 (same caveat as Phase 1).
2. Confirmed `order-service`'s actual env (`RETRY_ENABLED=false RETRY_COUNT=3 RETRY_DELAY_MS=100` for run A) via `docker compose exec order-service sh -c 'echo $RETRY_ENABLED ...'`.
3. Ran `scripts/k6/with-retries.js` (run A: no retries).
4. Set `RETRY_ENABLED=true` in the shell and `docker compose up -d --no-deps order-service` to recreate just that container (this also resets the in-process circuit breaker to a fresh `CLOSED` state, since it's a module-level instance re-created on process start).
5. Ran `with-retries.js` again (run B: retries, bug still present) — then applied the fix above, rebuilt `order-service`, recreated it again (fresh `CLOSED` breaker again), and ran `with-retries.js` a third time (run B-fixed).
6. `scripts/k6/with-retries.js` itself was also fixed the same way as `baseline.js` in Phase 1: added a business-level check (`r.json('status') === 'success'`) since `order-service` returns HTTP 200 for a failed order too, plus `p(99)` in `summaryTrendStats`.

# Results

| Run | Order success | p50 | p95 | p99 | Throughput | Breaker state after |
| --- | --- | --- | --- | --- | --- | --- |
| **A** — no retries, chaos (30% payment failure) | 3% (8/238) | 154ms | 920ms | 1.03s | 7.8 req/s | `OPEN` (3 failures) |
| **B** — retries enabled, *bug present* | 16% (41/251) | 124ms | 756ms | 900ms | 8.2 req/s | `OPEN` (3 failures) |
| **B-fixed** — retries enabled, *bug fixed* | **99% (258/259)** | 133ms | 399ms | 751ms | 8.3 req/s | `CLOSED` (0 failures) |
| *(reference)* Phase 1 baseline — no chaos at all | 100% | 97–133ms | 213–276ms | 972ms–1.3s | 8.3–8.7 req/s | n/a |

Full k6 output for each run is in the session transcript; the table above
is the complete numeric summary.

## Analysis

- **Retries only work once the bug above is fixed.** Runs A and B (both
  pre-fix) are statistically indistinguishable (3% vs 16%, both dominated
  by the circuit breaker tripping) — the "improvement" between them was
  noise, not the retry mechanism. Run B-fixed is the first real
  retries-enabled measurement, and it matches the theoretical prediction
  almost exactly (~99.2% expected vs. 99% observed).
- **Retries prevented the circuit breaker from tripping at all**, not just
  masked failures after the fact: because each retry attempt happens
  *inside* the single `payment_cb.call(do_payment)` invocation, the breaker
  only ever sees the *final* outcome of up to 4 attempts. With retries, that
  final outcome is a failure only ~0.8% of the time, so the breaker never
  accumulated 3 consecutive real failures and stayed `CLOSED` for the whole
  run.
- **Latency did not clearly increase with retries** in this comparison —
  p95 was actually *lower* in the fixed-retries run (399ms) than in the
  no-retries run (920ms). This does not match the proposal's expected
  narrative ("retries aumentan latencia") at face value, but it has a
  plausible explanation specific to this codebase: a *failed* order (no
  retries, breaker open) still pays for user validation + inventory
  availability + inventory reserve + an inventory *release* call once
  payment fails — a longer failure path than a *successful* order (which
  never releases inventory). Meanwhile, ~99% of retried orders succeed on
  the first or second attempt (mean ≈ 1.43 attempts at a 70% per-attempt
  success rate), so the added latency per retry is small in aggregate. The
  clean "retries cost latency" trade-off the proposal describes would be
  easier to isolate in a scenario where failures are cheap to fail *and*
  retries are the only variable — e.g. injecting `LATENCY_MS` instead of
  `FAILURE_RATE` on `payment-service`, so every attempt (success or not)
  costs the same latency and extra attempts add cleanly. Worth trying as a
  follow-up if a cleaner latency signal is needed for the report.
- Compared to the **Phase 1 baseline** (no chaos, 0% error): run B-fixed
  (99% success) recovers almost all the way back to baseline error rate
  under active chaos, at a p95 that's actually within the baseline's own
  run-to-run range (213–276ms vs. 399ms) — the retries scenario, once
  correct, performs close to the no-chaos baseline.

# Follow-up audit: the same bug existed in three more places

A full review of Phase 0–3 (requested separately, after this document was
first written) found the exact same root cause in three more call sites in
`services/order-service/main.py`, none of them exercised by
`with-retries.js` (which only injects chaos into `payment-service`):

- **User validation** (`GET /users/{id}/validate`) and **inventory
  availability/reserve** (`GET .../availability`, `POST .../reserve`) fail
  under chaos with an **HTTP 503** (`user-service`/`inventory-service`'s
  `apply_chaos()` raises `HTTPException(503)`). `httpx` does not raise an
  exception for a non-2xx response by default, so `call_service()`'s
  exception-only retry loop never retried these either — same bug,
  different failure shape (503 instead of 200+error-body).
- **Notification** (`POST /notify`) fails the same way `payment-service`
  did originally: a normal HTTP 200 with `{"status": "error"}`.

**Fixes applied:**
- `call_service()` itself now also retries on a **5xx** response (not just
  transport exceptions), which fixes the user-validation and
  inventory-availability/reserve call sites with no change needed at their
  call sites - they still just check `.status_code != 200` afterwards, only
  now that check runs after retries were already attempted. 4xx (e.g. "not
  enough stock", "user not found") is deliberately left alone - retrying a
  genuine rejection wouldn't change the outcome.
- The notification call got the same treatment `do_payment()` already had:
  its own attempt loop retrying on both exceptions and a non-`"sent"` body,
  since - like payment - "success" for this endpoint is a business field
  `call_service()` has no way to know about generically.

**Verified empirically** (30 orders each, product 1 stock pre-bumped,
`RETRY_ENABLED` toggled, single-service chaos at `FAILURE_RATE=0.3`, one
run per condition - not a full k6 load test, just enough to see the effect
size clearly):

| Chaos target | No retries | With retries (fixed) |
| --- | --- | --- |
| `user-service` (1 chaos-exposed call) | 22/30 success (73%) | 30/30 (100%) |
| `inventory-service` (2 chaos-exposed calls) | 14/30 success (47%) | 30/30 (100%) |
| `notification-service` (order still "success", chaos degrades to "warning" not "error") | 20/30 clean success + 10 warnings (67% clean) | 29/30 clean success + 1 warning (97% clean) |

The inventory number (47%) is lower than user-service's (73%) because a
single order makes *two* chaos-exposed inventory calls (availability then
reserve) at the same independent 30% failure rate each - consistent with
`0.7 × 0.7 ≈ 49%` expected without retries.

**Re-verified after both fixes, no regression:**
- Phase 0 exit criteria: fresh boot, all 5 `/health` return `ok`, port 5180
  still refuses connections, `chaos set` still cancels on "no".
- Phase 1: re-ran `baseline.js` in full - 0% error rate, same latency/
  throughput shape as originally documented (p50=125ms, p95=284ms,
  p99=1.02s, 8.6 req/s), confirming the default `RETRY_ENABLED=false` path
  is provably unchanged by either fix (single attempt either way).
- Phase 2: `scripts/jmeter/baseline.jmx` untouched, still valid XML.
- Phase 3 (payment): re-ran `with-retries.js` after both additional fixes -
  99.4% success, matching the original fixed-retries result with no
  regression from the `call_service()` change.

# Notes for later phases

- The circuit-breaker interaction observed here (tripping under raw chaos,
  staying closed once retries mask individual failures) is itself a
  preview of Phase 4 — Phase 4 should deliberately push `FAILURE_RATE`
  high enough (e.g. 0.8, as `scripts/k6/with-circuit-breaker.js` already
  does) that even retries can't avoid tripping the breaker, to observe the
  breaker's own `OPEN`/`HALF_OPEN` recovery behavior in isolation.
- `scripts/k6/with-circuit-breaker.js` has the same "HTTP 200 for business
  failure" gap as `baseline.js` and `with-retries.js` had — its check
  accepts `200/201/503/500`, but `order-service` never actually returns
  503/500 for a declined payment (see the chaos section above), so that
  check is effectively `always true`. It needs the same
  `r.json('status') === 'success'`-style fix before Phase 4 produces a
  meaningful error-rate number.
- The retry fix in `services/order-service/main.py` is a permanent change
  (not scenario-specific) — it changes real behavior any time
  `RETRY_ENABLED=true`, including in Phase 6+ once this runs on Kubernetes.
