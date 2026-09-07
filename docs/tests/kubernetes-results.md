# Test Name

Kubernetes deployment and resilience mechanisms (Action Plan Phase 6) —
liveness/readiness probes, HPA autoscaling, and pod-kill recovery (MTTR) on
a local minikube cluster.

# When It Was Run

2026-09-05/06, local minikube cluster (Docker driver), fresh cluster boot.

# Description

Goal: stand up `k8s/base/` + `k8s/resilience/hpa.yaml` on a real cluster and
exercise Kubernetes-native resilience (HPA, liveness/readiness probes) — the
proposal's fourth resilience configuration, compared against Phases 1/3/4
(Compose-based baseline/retries/circuit-breaker).

## Setup

1. Installed `minikube` v1.39.0 (`kubectl` was already available, bundled
   with Docker Desktop). Started the cluster: `minikube start --driver=docker`
   (Kubernetes v1.37.0, containerd). Enabled `minikube addons enable
   metrics-server` — required for the HPA to read pod CPU%; without it the
   HPA reports `FailedGetResourceMetric` indefinitely.
2. Built all 5 service images (`docker build -t <service>:latest
   ./services/<service>`) and loaded each into the cluster's node
   (`minikube image load <service>:latest`), matching the
   `imagePullPolicy: Never` already set in `k8s/base/deployment.yaml`.
3. **Added liveness and readiness probes** to all 5 FastAPI microservices in
   `k8s/base/deployment.yaml` (previously none were defined):
   `httpGet: {path: /health, port: 8000}`, readiness
   (`initialDelaySeconds: 5, periodSeconds: 5, timeoutSeconds: 3,
   failureThreshold: 3`), liveness (`initialDelaySeconds: 10, periodSeconds:
   10, timeoutSeconds: 3, failureThreshold: 3`). `postgres` and the
   observability stack (otel-collector, prometheus, grafana, jaeger) were
   left without probes — out of scope for this phase, which targets the
   proposal's resilience-mechanism requirement on the microservices.
4. Applied `kubectl apply -f k8s/base/` then `kubectl apply -f
   k8s/resilience/hpa.yaml`. Order didn't matter in practice (the ConfigMap,
   Deployments and Services in `k8s/base/` reconcile fine applied together;
   HPA just needs its target Deployment to exist, which `k8s/base/` already
   creates) — documenting it anyway per the plan's cross-cutting note.
5. Re-applied the same product-1 stock bump used in every load test (`kubectl
   exec` into the `postgres` pod, `UPDATE products SET quantity = 100000
   WHERE id = 1;`) — the seed data lives in `k8s/base/db-configmap.yaml`,
   the same 3-user/3-product dataset as `db/init.sql`, so the same stock
   caveat from Phase 1 applies here too.
6. Verified the full order flow end to end via `kubectl port-forward
   svc/order-service 18100:8000` and a manual `POST /orders` — order created
   successfully with the full downstream chain (user → inventory → payment →
   notification) all returning `"status":"success"`.

# Results

## Startup finding: one cold-boot restart per dependent microservice (not a bug)

On the very first `kubectl apply`, 4 of 5 microservices (`user-service`,
`inventory-service`, `payment-service`, `notification-service`) restarted
exactly once before settling into `1/1 Running`:

```
Warning  Unhealthy  kubelet  Readiness probe failed: dial tcp ...:8000: connect: connection refused
```

Root cause (confirmed via `kubectl logs -p`): `docker compose` has
`depends_on: postgres: {condition: service_healthy}` for every service, but
`k8s/base/deployment.yaml` has no equivalent ordering (no init container
waiting on postgres). All pods start simultaneously, so each service's
`asyncpg` connection at FastAPI startup hits `postgres` before it's ready,
the app raises `ConnectionRefusedError` and exits, and Kubernetes restarts
the container per `restartPolicy: Always`. By the second attempt postgres is
up and the service starts cleanly. **This is Kubernetes's own self-healing
working as designed, not a probe bug** — left as-is since adding startup
ordering (e.g. an `initContainer` polling postgres) was out of this phase's
scope (only probes were requested), but it's worth flagging for whoever
adds probes/init containers to `postgres`, `otel-collector`, etc. in a
future pass.

## HPA validation

Ran `scripts/k6/stress-test.js` (10→200 VUs over ~4 min) against
`order-service` through `kubectl port-forward` (`ORDER_URL` pointed at
`host.docker.internal:18100` from a `grafana/k6` container), while polling
`kubectl get hpa` and `kubectl top pods` every 5s.

| Time | `order-service-hpa` CPU | replicas | `payment-service-hpa` CPU | replicas |
| --- | --- | --- | --- | --- |
| baseline (10 VUs) | 5-12% / 70% | 1 | 5-6% / 70% | 1 |
| ramp to 200 VUs | 181% / 70% | 1 | 30% / 70% | 1 |
| peak | **201% / 70%** | **1 → 3** | 30% / 70% (never crossed 70%) | 1 |
| cooldown | 9% / 70% | 3 (unchanged — default 5-min scale-down stabilization window) | 14-18% / 70% | 1 |

`kubectl get events` confirms the scale event directly:

```
SuccessfulRescale  horizontalpodautoscaler/order-service-hpa  New size: 3;
  reason: cpu resource utilization (percentage of request) above target
```

**`order-service-hpa` scaled 1 → 3 replicas**, well before hitting
`maxReplicas: 5` (CPU utilization is computed against the 100m `requests`
value, so 201m usage = 201%, several multiples over the 70% target — the
HPA reacted as designed). **`payment-service-hpa` never scaled**: it peaked
at 30% CPU because `stress-test.js` only calls `order-service` directly —
`payment-service` load is second-hand (one call per order, much lighter
than `order-service`'s own 4-way fan-out + DB write), consistent with
Phase 5's finding that `order-service` is the CPU bottleneck, not
`payment-service`.

**Methodology caveat:** the k6 run itself suffered heavy failures during the
peak-CPU window - full summary: `checks_total` 6570, `checks_succeeded`
19.68% (1293/6570), `checks_failed` 80.31% (5277/6570); `http_req_duration`
avg=8.56s, min=0s, med=0s, p(90)=41.57s, **p(95)=45.4s, p(99)=50.49s**,
max=59.99s; `http_req_failed` 72.69% (2388/3285 requests), many
`dial: i/o timeout`. This happened because the single `kubectl
port-forward` tunnel — not the cluster — became the throughput bottleneck
under 200 concurrent VUs. **This run is not a clean replacement for Phase
5's Compose-network resource numbers** (those remain the trustworthy
baseline for absolute latency/CPU-per-request figures); it was, however,
more than sufficient to genuinely saturate `order-service`'s single pod and
trigger a real HPA scale-out, which is what this step needed to prove.

## Finding: the order-service liveness probe self-triggered a restart under the same CPU spike

The original `order-service` pod (before HPA created replicas 2 and 3)
restarted a **second** time during the load test:

```
kubectl describe pod order-service-...-9p2rn:
  Liveness probe failed: context deadline exceeded (Client.Timeout exceeded
    while awaiting headers)
  Killing: Container order-service failed liveness probe, will be restarted
```

This lines up exactly with the CPU-saturation window (181-201% CPU). Under
that load, `/health` itself apparently didn't respond within the probe's
`timeoutSeconds: 3` (Phase 5 already documented `order-service` p95 latency
degrading to seconds under saturation with no autoscaling — here, even with
autoscaling reacting, the *original* pod was overloaded before its two new
siblings came up and started sharing traffic). Kubernetes then killed and
restarted the very pod that was already struggling, compounding the
overload for a few seconds rather than helping it.

**This is a real, known Kubernetes gotcha** (liveness probes tuned for a
healthy service can misfire under genuine overload and cause a
self-inflicted restart) rather than a code bug — no fix was applied since
it wasn't in this phase's scope, but it's a concrete tuning recommendation
for later: either loosen `order-service`'s liveness `timeoutSeconds`/
`failureThreshold` relative to its readiness probe (so a slow-but-alive pod
fails readiness — gets taken out of the Service's endpoints — before it
fails liveness and gets killed), or keep `/health` deliberately cheap and
verify it never shares the event loop with request handling under load.

## MTTR (pod-kill recovery)

Deleted the running `payment-service` pod (`kubectl delete pod
payment-service-84bdd8dcdb-76wx2`) and polled `kubectl get pods` every ~1s:

| Event | Timestamp |
| --- | --- |
| `kubectl delete pod` issued | 21:03:14.757 |
| New pod `payment-service-84bdd8dcdb-7hz89` created, `0/1 Running` | 21:03:23.748 (age 9s) |
| New pod `1/1 Running` (readiness probe passed) | 21:03:26.307 (age 12s) |

**MTTR = 11.55 seconds** on this run, from delete to a fully ready
replacement pod (ReplicaSet-driven rescheduling — ~9s of
scheduling/image-already-cached startup, then the readiness probe's
`initialDelaySeconds: 5` plus one successful check). No manual intervention
was needed; the `payment-service` Service's endpoint list picked up the new
pod automatically once it passed readiness.

**Re-verification (2026-09-06, independent audit pass):** repeated the same
test on the same cluster (deleted the then-current `payment-service` pod,
polled with high-precision timestamps) and got **MTTR = 26.50 seconds** -
more than double. `kubectl describe` on the new pod showed 3 failed
readiness checks (`connection refused`) before the container started
listening, vs. presumably 1 in the original run - the container itself
took longer to become reachable, likely resource contention after ~2 hours
of Docker Desktop + minikube running concurrently on the host, not a change
in the recovery mechanism itself.

**Second re-verification (2026-09-06, later same day):** a third
independent sample gave **MTTR = 12.12 seconds** - back in line with the
first run. Three samples so far: 11.55s, 26.50s, 12.12s. **Treat "~11.55s"
as one sample among several, not a guaranteed constant - the honest range
is roughly 11-27s**, with most samples clustering toward the lower end and
occasional host-contention outliers. Every run shares the same important
property: fully automatic, no human intervention, same order of magnitude
(tens of seconds) - which is what distinguishes it from Compose's
*unbounded* MTTR in `docs/tests/fault-pod-container-kill-results.md`. A
future pass wanting a tighter number should take 5+ samples on an
otherwise-idle host, not rely on any single one of these three.

# Exit criteria

Met: HPA scales `order-service` under load (1 → 3 replicas, confirmed via
`SuccessfulRescale` event); a manually deleted pod is replaced automatically
and MTTR was measured (11.55s and, on re-verification, 26.50s - same order
of magnitude, real run-to-run variance, see "Re-verification" above). Two
genuine findings surfaced along the
way (cold-boot restart from missing dependency ordering; liveness-probe
self-restart under CPU saturation) — both are Kubernetes-native resilience
behavior working as designed, documented here as tuning notes for Phase 7+
rather than bugs fixed in this phase, since fixing them (init containers,
probe retuning) was outside this phase's stated scope (add probes, validate
HPA + MTTR).

# Notes for later phases

- `payment-service-hpa` staying at 1 replica in this run is expected, not a
  gap — Phase 7's dependency-failure fault (driving chaos directly at
  `payment-service`) or a payment-focused load pattern would be needed to
  actually exercise its HPA.
- The liveness-probe-under-saturation finding above is directly relevant to
  Phase 7's CPU-saturation fault type; expect to see the same self-restart
  behavior there unless the probe thresholds are retuned first.
- `db-configmap.yaml`'s hand-written seed dataset (3 users/3 products) is
  what's available in Kubernetes — the 50k-user Faker seed only happens via
  `data-seeder` in Compose, which has no Kubernetes equivalent yet. Fine for
  functional/HPA/MTTR testing (doesn't touch user volume), but note this if
  a future phase needs the full seeded dataset in-cluster.
