# Test Name

Fault injection: CPU saturation (Action Plan Phase 7) — consolidated
comparison of Docker Compose vs. Kubernetes under `scripts/k6/stress-test.js`
(10→200 VUs).

# When It Was Run

Compose data: Phase 5 (`docs/tests/resources-observability-results.md`).
Kubernetes data: Phase 6 (`docs/tests/kubernetes-results.md`), 2026-09-05/06.

# Description

Goal: measure the proposal's "Saturación de CPU" fault — primary metrics
are HPA scale-out behavior and degradation — comparing the two
environments. **This fault was already executed against both environments
as a natural part of Phases 5 and 6** (same load tool, same script, same
target). Rather than re-running an identical 4-minute high-concurrency
test a third time, this document consolidates and directly compares that
already-verified data, as Phase 7 asks for. No new load test was run for
this file; every figure below is sourced from the two results docs cited
above.

# Results

## Docker Compose (no autoscaling — Phase 5)

- `order-service` is the CPU bottleneck: **83% avg / 110% max** CPU (one
  full host core, uncapped — Compose sets no CPU limits), memory
  72→319 MiB.
- **No HPA exists in Compose** — a single fixed-capacity `order-service`
  container absorbs the entire 200-VU load alone. "HPA scale-out behavior"
  is not applicable here by design; that's precisely the gap Kubernetes'
  resilience mechanism is meant to close.
- Degradation: p95 latency reaches **13.98s at 200 VUs**, vs. <300ms at 10
  VUs — the system gets slow under load but **99.9% of orders still
  complete**; it degrades, it doesn't fail.

## Kubernetes (HPA active — Phase 6)

- `order-service-hpa` **scaled 1 → 3 replicas** under the same
  `stress-test.js` load (CPU utilization peaked at 201% of the 70% target
  — confirmed via the `SuccessfulRescale` Kubernetes event).
  `payment-service-hpa` stayed at 1 replica (only 30% max CPU — it's
  loaded indirectly through `order-service`, consistent with the Phase 5
  bottleneck finding).
- Degradation during the same window was **more severe** than Compose's,
  not less: `checks_succeeded` fell to 19.68%, `http_req_duration` avg
  8.56s, p95 45.4s, p99 50.49s (vs. Compose's p95 13.98s at the same VU
  count).
- Additional finding unique to Kubernetes: the liveness probe on the
  original `order-service` pod timed out under the CPU spike and
  **restarted that pod mid-overload** (see `docs/tests/kubernetes-results.md`),
  compounding the disruption for a few seconds before the two new HPA
  replicas came online and started sharing traffic.

## Why Kubernetes looks worse here, and why that's not the real signal

Two confounds specific to this local setup make Kubernetes' raw numbers
look worse than Compose's, even though HPA is a genuine improvement over
"do nothing":

1. **Per-pod CPU is hard-capped at 200m (0.2 of a core)** in
   `k8s/base/deployment.yaml` — a deliberate limit so the HPA's 70%
   target (of the 100m *request*) is reachable without needing dozens of
   VUs. Compose's container has no such cap and can use a full host core
   alone. A single Kubernetes pod is *five times* more CPU-constrained
   than the equivalent Compose container, so of course one pod degrades
   faster — that's the HPA's job to compensate for by adding replicas, but
   replicas take time to schedule, start, and pass their readiness probe
   (matching the ~11-27s MTTR measured in Phase 6/`fault-pod-container-kill-results.md`),
   during which the single original pod is still absorbing 200 VUs alone.
2. **The k6 traffic reached Kubernetes through `kubectl port-forward`**,
   which the same Phase 6 test already identified as adding its own
   latency and throughput ceiling on top of the cluster's real behavior —
   see the methodology caveat in `docs/tests/kubernetes-results.md` and
   the p95 gap observed even for a much lighter fault in
   `fault-artificial-latency-results.md` (500ms×2 injected latency showed
   p95 3.55s in Kubernetes vs. 1.54s in Compose, for identical chaos
   configuration).

**The comparable, trustworthy signal from this fault is the HPA event
itself — `order-service` scaled from 1 to 3 replicas in direct response to
real CPU saturation — not the absolute latency/success-rate numbers, which
are inflated on the Kubernetes side by the tighter CPU cap and the
port-forward tunnel.** A cleaner apples-to-apples comparison would need
either a NodePort/Ingress path into the cluster (not reachable from this
Windows/Docker-driver minikube setup — see `docs/TOOLING.md`) or CPU
limits matched to Compose's effectively-uncapped container, neither of
which was in scope for this phase.

# Exit criteria

Met: CPU-saturation fault documented for both environments (data already
collected during Phases 5-6); HPA scale-out confirmed working; degradation
compared with the confounding factors called out explicitly so the
comparison isn't read as more apples-to-apples than it actually is.
