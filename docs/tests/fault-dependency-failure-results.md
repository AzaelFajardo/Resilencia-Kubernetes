# Test Name

Fault injection: dependency failure (Action Plan Phase 7) — `user-service`
at 100% failure rate, measured against both Docker Compose and Kubernetes.

# When It Was Run

2026-09-06, both environments already up.

# Description

Goal: measure the proposal's "Fallas en dependencias" fault — primary
metrics are error cascade in `order-service` and recovery time — using a
dependency that is **not** protected by the circuit breaker (only
`payment-service` has one; see `docs/tests/circuit-breaker-results.md`),
so this specifically exercises the plain fail-fast path rather than the
breaker. `RETRY_ENABLED=false` (the default in both environments), so
retries are not a confounding factor here — this isolates the pure
"downstream dependency is completely down" behavior.

## Setup

- `python cli.py chaos set user-service --failure-rate 1.0 --yes`.
- Manual single-order sanity check first, then `scripts/k6/baseline.js`
  (10 VUs, 30s) for the full-cascade measurement, then `chaos reset --all
  --yes` immediately followed by a second `baseline.js` run to measure how
  fast the system recovers.

# Results

## Error cascade shape (manual check, both environments identical)

```json
{"status":"error","message":"User validation failed with status 503",
 "order":{"id":null,"internal_status":"service_error", ...},
 "downstream":{"user":null,"inventory":null,"payment":null,"notification":null}}
```

HTTP 200 (business failure, not a transport error — consistent with every
other fault in this project). **Finding: this is not actually a
"cascade" of failures — it's a fail-fast short-circuit.** `order-service`
stops at the first failed dependency (user validation, the first call in
the chain) and never calls inventory, payment, or notification at all
(`downstream` is `null` for all three, not `"skipped"` or an error from
each). This is a positive resilience property already present in the
code: a dependency failure early in the chain doesn't waste work calling
services further downstream that would just be rolled back anyway.

## Load test: full cascade under 100% failure

| Metric | Compose | Kubernetes |
| --- | --- | --- |
| Requests | 270 | 208 |
| Success rate | **0%** (0/270) | **0%** (0/208) |
| `http_req_duration` p50 | 101ms | 491ms |
| `http_req_duration` p95 | 180ms | 701ms |
| Throughput | 8.97 req/s | 6.75 req/s |

**0% success in both environments**, exactly as expected — every order
requires a valid user, and `user-service` fails unconditionally. Note
`http_req_duration` here is *faster* than the Phase 1 baseline's full
successful path (101ms vs. 133ms median in Compose): failing fast on the
very first downstream call is cheaper than completing all four. Kubernetes
is slower in absolute terms (491ms vs 101ms median) for the same reason as
every other fault tested against it here — the `kubectl port-forward`
tunnel overhead (see `docs/tests/kubernetes-results.md` and
`fault-artificial-latency-results.md`) — not anything about the fault
itself.

## Recovery time

Immediately after `chaos reset --all --yes`, a fresh `baseline.js` run:

| | Compose | Kubernetes |
| --- | --- | --- |
| Success rate right after reset | **100%** (243/243) | **100%** (121/121) |

**Recovery is effectively instant in both environments** — `FAILURE_RATE`
is a plain in-process module variable (`user-service/main.py`), read fresh
on every request; there's no circuit-breaker state, cache, or connection
pool to drain or re-warm, so the very next request after the config change
lands cleanly. This is a meaningfully different recovery profile than the
Phase 4 circuit-breaker scenario, where recovery (closing the breaker)
takes at least one full `recovery_timeout` (15s) window even after chaos
is reset — a direct, useful contrast for the final report: **stateless
chaos toggles recover instantly; stateful resilience mechanisms (the
breaker) have their own recovery latency by design.**

# Exit criteria

Met: dependency-failure fault executed and documented in both
environments — error cascade shape confirmed identical (and shown to be a
fail-fast short-circuit, not a multi-service cascade), and recovery time
measured as effectively instantaneous in both.
