# Test Name

Kubernetes hardening & Helm packaging (Action Plan Phase 10).

# When It Was Run

2026-09-06/07, same minikube cluster used since Phase 6.

# Description

Goal: close every Kubernetes-side code gap found during the Phases 0-9
audit. All five items below were implemented and verified live against
the running cluster.

# Results

## 1. `initContainer` fixes the cold-boot restart

Added a `wait-for-postgres` `initContainer` (busybox polling `nc -z
postgres 5432`) to all 5 microservice Deployments. Verified by deleting
all 5 pods at once and watching the rollout: **all 5 new pods reached
`1/1 Running` with 0 restarts** - previously this was a guaranteed 1
restart per service (`docs/tests/kubernetes-results.md`).

## 2. Liveness probe retune stops the self-restart under saturation

`order-service`'s liveness probe: `timeoutSeconds` 3→10, `periodSeconds`
10→15, `failureThreshold` 3→4 (readiness `timeoutSeconds` 3→5, unchanged
otherwise). Re-ran `scripts/k6/stress-test.js` (same 200-VU load that
previously triggered a self-restart): HPA scaled 1→3 replicas again (CPU
saturation reproduced), but **all 3 `order-service` pods showed 0
restarts** this time. Business success rate also improved, 64% (758/1184)
vs. the original run's 19.68% - likely because pods weren't losing time to
self-inflicted restarts on top of the real overload.

## 3. Grafana provisioning in Kubernetes - plus two newly found bugs

Added ConfigMaps (`k8s/base/grafana-provisioning-configmap.yaml`) for the
datasource, dashboard provider, and the dashboard JSON itself, mounted
into the `grafana` Deployment. Verified via the live API: 12 panels,
correct `uid: prometheus` datasource - same result as Compose (Phase 8).

**While verifying panels actually had data, found two real,
previously-undetected bugs** (all prior K8s testing had only ever
checked Compose's Prometheus/Jaeger, never K8s's own):

- **K8s Prometheus was never scraping anything but itself.** Its
  Deployment had no volume mount for `observability/prometheus.yml` -
  confirmed live (`/api/v1/targets` showed only the `prometheus` job).
  Fixed: added a `prometheus-config` ConfigMap (verbatim copy of
  `observability/prometheus.yml` - K8s Service DNS names already match
  Compose's) mounted at `/etc/prometheus/prometheus.yml`. Re-verified:
  `microservices` (5 targets) and `otel-collector` both `up`.
- **K8s Jaeger's Service never exposed port 4317 (OTLP gRPC).**
  `otel-collector`'s config sends traces to `jaeger:4317`, but neither the
  Jaeger Deployment's `containerPort` list nor its Service's `ports` had
  an entry for 4317 - Kubernetes Services only proxy declared ports
  (unlike Compose, where any container on the network can reach any port
  the target container listens on). Result: every trace export failed
  with `i/o timeout` (confirmed in `otel-collector` logs), and
  `GET /api/services` on Jaeger returned an empty list. Fixed: added
  `containerPort: 4317`/`4318` to the Deployment and an `otlp-grpc` port
  (4317) to the Service. Re-verified: placed an order, `GET
  /api/services` returned all 5 services.

Also added a matching `otel-collector-config` ConfigMap (verbatim copy of
`observability/otel-collector.yaml`) - the collector had the same
never-configured problem as Prometheus, just less visible since the
`debug` exporter was still logging spans locally even while the Jaeger
export silently failed.

## 4. 50k-user seed as a Kubernetes Job

`k8s/base/seed-job.yaml` runs the same `data-seeder` image Compose uses.
Built and loaded the image, applied the Job, confirmed completion and
`cli.py status` showing 50,000 users in `user-service` (previously capped
at the 3-user `db-configmap.yaml` seed).

## 5. Helm chart (`charts/resilencia/`)

Full chart: `Chart.yaml`, `values.yaml` (image tags, resource limits, both
probe configs, HPA thresholds, seed toggle), and templates covering every
resource above (microservices via a `range` loop, `order-service`
separately since its env/probes differ, postgres, the full observability
stack with the two bug fixes baked in, HPA, seed Job). `helm lint`: 0
failures. `helm template` renders 1292 lines that pass a server-side
`kubectl apply --dry-run=client` against the real API.

**Real end-to-end install, not just template validation:** `helm install
resilencia charts/resilencia -n resilencia-helm-test` into a fresh,
isolated namespace. **All 11 resources (10 Deployments + the seed Job)
reached `Running`/`Completed` with 0 restarts on the very first try** -
confirms the `initContainer` fix works from a genuinely cold start, not
just the one time it was manually verified in item 1. Placed a test order
against the Helm release: `"status":"success"`. Cleaned up
(`kubectl delete namespace`) after verification - this was a throwaway
proof, not a second permanent environment.

# Exit criteria

Met: a fresh Helm install boots with zero cold-boot restarts (verified
twice - once via raw manifests, once via the chart in an isolated
namespace); Grafana dashboard renders with live data in-cluster (after
fixing the two real bugs that were blocking it); the seed Job populates
50k users; HPA and probes still work with no regression (re-ran the exact
Phase 6/7 stress test and pod-kill scenarios).

# Notes for Phase 11

- The two Prometheus/Jaeger config bugs found here were **never caught in
  Phases 6-9** because every prior K8s test queried Compose's Prometheus
  (port 9091) or never checked Jaeger in K8s at all - a blind spot in the
  audit methodology, not just the manifests. Worth remembering when
  auditing anything Kubernetes-specific: always port-forward to the K8s
  service being tested, don't assume the already-open Compose port is the
  one you're hitting.
- The default namespace's live cluster now has all Phase 10 fixes applied
  directly (not just in the Helm chart) - both are kept in sync manually;
  if they drift, the chart's `templates/observability.yaml` is the
  source of truth for the config content (verbatim copies noted inline).

# Audit addendum (2026-09-07)

An independent audit found the Helm chart had drifted from the plain
manifests in two ways, both fixed:

1. **Volume names differed** between `charts/resilencia/templates/observability.yaml`
   (generic `config`/`datasource`) and `k8s/base/deployment.yaml`
   (`otel-collector-config`/`prometheus-config`/`datasource-provisioning`)
   for otel-collector, prometheus, and grafana - same ConfigMap, same
   mount path, no functional bug, but `helm template | kubectl apply
   --dry-run=client` showed 3 "configured" (diff) instead of "unchanged"
   against the live cluster because of it. Renamed to match exactly.
2. **The chart never got Phase 11's alert rules** - `prometheus-config`
   in the chart had no `rule_files`, and there was no `prometheus-alerts`
   ConfigMap at all, unlike `k8s/base/`. Added both (`files/alerts.yml`
   copied from `observability/alerts.yml`, mounted the same way).

Re-validated after the fix: `helm lint` 0 failures, `helm template |
kubectl apply --dry-run=client` now reports **every** Deployment/Service/
ConfigMap as `unchanged` against the live cluster (previously 3
`configured`).
