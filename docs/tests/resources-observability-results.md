# Test Name

Resource usage and observability overhead (Action Plan Phase 5) — CPU/RAM
under load, a rough per-request CPU cost, OpenTelemetry instrumentation
overhead, and a span-loss check, using the existing `stress-test.js` and
`baseline.js` scripts.

# When It Was Run

2026-09-04, local Docker Compose stack, fresh volumes.

# Description

Goal: cover the proposal's "Recursos" (CPU, RAM, cost per request) and
"Observabilidad" (OTel overhead, span loss, sampling impact) metric
sectors.

## Setup

1. Fresh boot, `cli.py status` healthy, product 1 stock bumped to
   **1,000,000** (the usual 100,000 wasn't enough headroom for
   `stress-test.js`'s ~5,000+ requests at up to 200 VUs).
2. Added `scripts/collect_resource_metrics.sh` — samples `docker stats
   --no-stream` for every `resilencia-kubernetes-*` container on an
   interval and appends to a CSV (`timestamp,container,cpu_percent,
   mem_usage_mib,mem_percent`). Each `docker stats` call itself takes
   ~5-6s on this machine regardless of the requested interval, so treat
   the interval argument as a lower bound, not exact cadence.
3. Fixed `scripts/k6/stress-test.js`'s check the same way `baseline.js`/
   `with-retries.js`/`with-circuit-breaker.js` were fixed in earlier
   phases (business-level `status === 'success'` check, `p(99)` in
   `summaryTrendStats`) — same root cause, same fix.
4. Ran `scripts/k6/stress-test.js` (30s@10 VUs → 2m@200 VUs → 1m@200 VUs →
   30s ramp-down, ~4 minutes total) in the background while
   `collect_resource_metrics.sh` sampled every ~6s throughout.
5. For the OTel overhead comparison: discovered that
   `OTEL_SDK_DISABLED=true` is a standard OpenTelemetry env var that the
   Python SDK already honors — `TracerProvider.get_tracer()` returns a
   `NoOpTracer()` when set, with **no code change needed** in
   `services/*/tracing.py`. The only gap was that `compose.yml` didn't
   forward it into the containers (compose does not pass through
   arbitrary host env vars unless a service's `environment:` block
   declares them). Added `OTEL_SDK_DISABLED: ${OTEL_SDK_DISABLED:-false}`
   to all 5 microservices in `compose.yml` and documented it in
   `.env.example` (default `false` — no behavior change unless a team
   member deliberately sets it for this kind of test).
6. Ran `baseline.js` twice back-to-back on the already-stressed stack (to
   control for any lingering load/GC effects from the stress test rather
   than comparing against a separately-timed fresh-boot run): once with
   OTel enabled (default), then recreated all 5 services with
   `OTEL_SDK_DISABLED=true` and ran it again immediately after.
7. Span-loss check: compared `orders/count` before/after the stress test
   against the number of traces Jaeger has recorded for `order-service` in
   that same wall-clock window (`GET /api/traces?service=order-service&
   start=...&end=...`, bounds taken from the resource CSV's first/last
   timestamps).
8. Restored `OTEL_SDK_DISABLED` to `false` (default) before tearing down.

# Results

## Resource usage under stress (200 VUs, ~4 min, 45 samples)

| Container | CPU avg | CPU max | Mem avg | Mem max |
| --- | --- | --- | --- | --- |
| **order-service** | **82.96%** | **110.22%** | 220.7 MiB | 319.1 MiB |
| inventory-service | 33.07% | 82.15% | 79.0 MiB | 83.4 MiB |
| postgres | 20.48% | 50.82% | 192.8 MiB | 219.8 MiB |
| payment-service | 13.79% | 28.77% | 76.4 MiB | 78.6 MiB |
| notification-service | 13.20% | 33.70% | 75.9 MiB | 79.3 MiB |
| user-service | 12.93% | 48.01% | 76.8 MiB | 80.8 MiB |
| jaeger | 1.31% | 5.00% | 312.0 MiB | 570.7 MiB |
| otel-collector | 0.95% | 2.03% | 70.4 MiB | 78.9 MiB |
| prometheus | 0.17% | 0.85% | 23.0 MiB | 24.3 MiB |
| grafana | 0.07% | 0.46% | 51.0 MiB | 57.9 MiB |

Idle (no load, 5 samples over ~26s, for comparison): every microservice
sat under 1% CPU and ~70-72 MiB memory; postgres ~121 MiB.

**`order-service` is the clear bottleneck** — it's the only container that
saturates a full CPU core (max 110%, i.e. more than one core's worth of a
single-threaded-ish async workload) and its memory nearly tripled under
load (72 MiB idle → up to 319 MiB). It's also the only service making 4
downstream HTTP calls plus a DB write per request, so this matches the
architecture. `jaeger`'s memory grew substantially too (16 MiB idle → up
to 571 MiB) from ingesting the trace volume.

**System degradation under load** (this stack has no autoscaling — plain
Docker Compose, single Uvicorn worker per service): `stress-test.js`
itself reported severe latency growth under the 200-VU stage — p50 rose to
2.95s, p95 to 13.98s, p99 to 22s (vs. sub-300ms p95 at 10 VUs in every
other phase). 99.86% of orders still completed successfully (business
status) despite the latency blowup — the system slows down heavily rather
than dropping requests. This is exactly the "degradación del sistema" /
"autoescalado" comparison point the proposal wants Phase 6 (Kubernetes +
HPA) to improve on.

## Rough CPU cost per request

Estimated as `(avg CPU% / 100) × test duration (249s) / total requests
(5159)` — a relative proxy for which service costs the most CPU per order,
**not** a real monetary cost (no cloud billing model on a local machine):

| Service | CPU-seconds (whole test) | Per-request |
| --- | --- | --- |
| order-service | 206.6 | **40.0 ms** |
| inventory-service | 82.3 | 16.0 ms |
| postgres | 51.0 | 9.9 ms |
| payment-service | 34.3 | 6.7 ms |
| notification-service | 32.9 | 6.4 ms |
| user-service | 32.2 | 6.2 ms |

`order-service` costs roughly as much CPU per order as all four downstream
services combined — consistent with it being the orchestrator (every call
it makes to a downstream service also costs that downstream service its
own CPU, on top of order-service's own request handling and async
fan-out/fan-in overhead).

## OpenTelemetry overhead

Back-to-back `baseline.js` runs (10 VUs, 30s, no chaos), OTel enabled vs.
`OTEL_SDK_DISABLED=true`:

| | OTel enabled | OTel disabled | Difference |
| --- | --- | --- | --- |
| p50 (med) | 239.64ms | 139.80ms | **-99.8ms (-42%)** |
| p95 | 506.01ms | 295.50ms | **-210.5ms (-42%)** |
| avg | 253.56ms | 164.66ms | **-88.9ms (-35%)** |
| Throughput | 7.95 req/s | 8.55 req/s | +7.5% |
| p99 | 813.61ms | 1.00s | *(noisy, ~250 samples — see note)* |

OpenTelemetry instrumentation (5 services' worth of span creation, context
propagation across every HTTP hop, SQLAlchemy query spans, and batch
export) adds roughly **35-42% to this system's median/p95 request
latency**. This is a substantial, genuine cost worth knowing — not a
rounding error.

p99 does not follow the same direction (813ms enabled vs 1.0s disabled)
which looks contradictory; with ~250-260 requests per run, the top 1%
is only 2-3 samples, so a single slow outlier (cold TCP connection, GC
pause, host scheduling jitter) swings that number more than the underlying
effect - p50/p95/avg (each backed by more samples) are the numbers to trust
here, not p99.

## Span loss

Comparing the stress-test window: `orders/count` grew by 5,144 during the
run (k6 itself reported 5,159 requests, 5,152 business successes).
Querying Jaeger for `order-service` traces in that same wall-clock window
returned **5,218 traces** — at or above the request count, not below it
(the small excess is window-boundary imprecision, not proof of extra
traces). **No span loss was observed at this load level.**

This isn't a strong stress test of the tracing pipeline specifically,
though: `order-service` itself became the bottleneck (CPU-saturated, see
above) well before the OTel export pipeline showed any sign of strain —
peak throughput here was ~21-43 req/s, which is not a large volume for a
batched OTLP exporter + collector. A test that actually finds the tracing
pipeline's breaking point would need either a much higher request rate
(more than this stack's own `order-service` can currently sustain) or
horizontal scaling of `order-service` first (Phase 6) so throughput isn't
capped by the orchestrator before the trace volume gets interesting.

## Sampling impact

**Not measured.** `services/*/tracing.py` always samples 100% of traces
(no `OTEL_TRACES_SAMPLER`/`OTEL_TRACES_SAMPLER_ARG` support exists), and
the Action Plan explicitly treats adding that as optional, separate work
("if sampling needs to be tuned to observe its impact... this is new work,
not a Phase 0 bug fix"). Deliberately not implemented in this pass, to
avoid adding new instrumentation-config surface across 5 services without
a clear need for it yet. If a future phase wants this: `tracing.py`'s
`setup_tracing()` would need to pass a `sampler=` to `TracerProvider(...)`,
built from `sampling._get_from_env_or_default()` (already imported
transitively — this is what the SDK uses internally when no explicit
sampler is passed, and it already reads `OTEL_TRACES_SAMPLER`/
`OTEL_TRACES_SAMPLER_ARG` from the environment on its own, so this might
be as simple as *not* overriding the default at all and just setting those
two env vars — worth verifying before assuming code changes are needed).

# Notes for later phases

- `docker stats --no-stream` costs ~5-6s per call on this machine
  regardless of requested interval — `collect_resource_metrics.sh`'s
  `interval_seconds` argument is a floor, not the real cadence. Budget
  iterations accordingly (`duration_seconds / ~6` , not
  `duration_seconds / interval_seconds`).
- `OTEL_SDK_DISABLED` is now a permanent, documented, default-`false` knob
  in `compose.yml`/`.env.example` — reuse it directly for Phase 8's
  dashboards or any later re-measurement, no more plumbing needed.
- The stress-test degradation numbers here (p95 up to 13.98s at 200 VUs)
  are the direct "before" comparison Phase 6 needs for its HPA validation
  — the same load pattern against a horizontally-scaled `order-service`
  in Kubernetes should show materially better latency at the same VU count.
