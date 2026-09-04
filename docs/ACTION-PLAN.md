# Action Plan — Experimental Evaluation of Resilience Strategies

Source: `1.PROPUESTA COMPLETA DEL PROYECTO.pdf` ("Evaluacion Experimental de
Estrategias de Resiliencia en un Sistema de Microservicios Desplegado en
Kubernetes", Sistemas Distribuidos, UAA). This document is never committed to
the repo (see `.gitignore`); this plan captures everything it requires so the
team can execute without re-reading it.

The proposal asks for four things: (1) build the microservice system, (2)
break it on purpose, (3) measure it with real tooling across four metric
sectors, and (4) make it reproducible via Docker + Kubernetes + a public
GitHub repo. The phases below are ordered so the system, observability and
experiments are proven to work *before* anything resembling a control
interface for the team is rebuilt — that is deliberately the last phase.

## Phase 0 — Headless baseline (done)

**Goal:** remove the web UI, make the terminal the only control surface, and
clear the hygiene issues that would block a later Kubernetes phase.

**Status:** complete in this pass.

- Removed `services/frontend/` and the `frontend` compose service.
- Added `cli.py` (stdlib-only) as the terminal control surface: status,
  users/inventory generation, placing orders, chaos injection/reset,
  circuit-breaker introspection.
- Converted `k8s/base/db-configmap.yaml` from UTF-16LE+BOM+CRLF to clean UTF-8
  (regenerated from `db/init.sql`, the project's source of truth).
- Wired `FRAUD_THRESHOLD` (previously read by `order-service` but absent from
  `compose.yml`/`.env.example`) so it is actually configurable.
- Added `--remove-orphans` to all `docker compose up`/`down` invocations in
  `run.sh`/`run.ps1`.

**Exit criteria:** `docker compose up -d --build --remove-orphans` boots only
backends + postgres + data-seeder + otel-collector + prometheus + grafana +
jaeger; all `/health` return 200; `cli.py status` runs; `cli.py chaos set`
cancels on "no"; a `cli.py order place` completes successfully. All verified.

## Phase 1 — Baseline scenario (no resilience mechanisms)

**Goal:** capture the "Baseline (sistema sin resiliencia)" scenario the
proposal asks for first: no retries, no circuit breaker, no autoscaling.

**Status:** complete. Executed once and independently re-verified end to
end on a second fresh boot (both runs: 0% error rate, all 5 Prometheus
targets and Jaeger services up, order-service's own `/metrics` histogram
consistent with the k6 client-side numbers).

**Steps:**
1. `docker compose up -d --build --remove-orphans` with defaults
   (`RETRY_ENABLED=false`, all `FAILURE_RATE`/`LATENCY_MS`/`TIMEOUT_RATE=0`).
2. Confirm Prometheus `Status -> Targets` shows `microservices` and
   `otel-collector` as `up`, and Jaeger lists all 5 services after a few
   orders via `cli.py order place`.
3. Run `scripts/k6/baseline.js` against `order-service` (see README "k6 con
   Docker" for the exact `docker run` invocation).
4. Record latency p50/p95/p99, throughput (req/s) and error rate from the k6
   summary and from the Grafana `Resilencia Overview` dashboard.

**Files added:** `docs/tests/baseline-results.md` (k6 output, the four
metrics above, the Prometheus/Jaeger cross-checks, and the two fixes
required to get a meaningful run: bumping product 1's seeded stock so the
test doesn't just measure inventory exhaustion, and adding a business-level
success check to `scripts/k6/baseline.js` since `order-service` returns
HTTP 200 for business failures too).

**Exit criteria:** met. Results (first run / re-verification run): 258 / 271
requests, 0% error rate both times, ~8.3–8.7 req/s, p50 97–133ms, p95
213–276ms, p99 972ms–1.3s. Numbers vary run to run as expected for a load
test; the shape (near-zero error rate, sub-300ms p95, all services traced)
is stable and is the comparison point for Phases 3–4.

## Phase 2 — Load-testing tooling (k6 + JMeter)

**Goal:** the proposal explicitly names two load tools — k6 (already present
under `scripts/k6/`) and Apache JMeter (not yet present). Add the missing one
so both traffic-generation styles (k6's high-volume VUs vs. JMeter's
concurrent-user simulation) are available for every later scenario.

**Status:** complete. The plan is authored and documented but deliberately
**not executed** — JMeter itself is not installed in this phase (that
belongs to whoever runs Phase 3 onward); the XML was only validated for
well-formedness, not run end to end. Give it a smoke test before trusting
its numbers.

**Steps:**
1. Author a JMeter test plan (`.jmx`) hitting `POST /orders` on
   `order-service` with a configurable thread group (concurrent users) and
   ramp-up, mirroring `scripts/k6/baseline.js`'s request shape.
2. Document how to run it headless: `jmeter -n -t plan.jmx -l results.jtl`
   (do not install JMeter yet — this phase only authors the plan; installing
   and running it belongs to whoever executes the experiments).

**Files added:** `scripts/jmeter/baseline.jmx` (10 concurrent users, 10s
ramp-up, 30s duration, all overridable via `-J<name>=<value>` - mirrors
k6's `vus: 10, duration: '30s'`; includes the same business-status
assertion as the k6 fix, since `order-service` returns HTTP 200 for
business failures too), `docs/tests/jmeter-usage.md` (parameters, the same
product-1 stock caveat as the k6 baseline, and the exact headless
invocation with HTML report generation).

**Exit criteria:** met. A JMeter plan exists and its usage is documented; k6
remains the primary tool for the automated comparisons in Phases 3–4.

## Phase 3 — Retries scenario

**Goal:** measure the proposal's expected trade-off ("retries aumentan
latencia pero reducen errores") using the retry logic already implemented in
`order-service` (`RETRY_ENABLED`/`RETRY_COUNT`/`RETRY_DELAY_MS`).

**Steps:**
1. Inject failure into a downstream dependency, e.g.
   `python cli.py chaos set payment-service --failure-rate 0.3`.
2. With `RETRY_ENABLED=false` (baseline for this scenario), run
   `scripts/k6/with-retries.js` and record latency/error rate.
3. Set `RETRY_ENABLED=true` (`RETRY_COUNT=3`, `RETRY_DELAY_MS=100` — the
   proposal's own example configuration), restart `order-service`, and repeat
   the same k6 run.
4. Reset chaos: `python cli.py chaos reset payment-service --yes`.

**Files to add:** `docs/tests/retries-results.md` comparing both runs
(latency increase vs. error-rate reduction vs. baseline).

**Exit criteria:** documented before/after showing retries reduce error rate
at the cost of latency, relative to Phase 1's baseline.

## Phase 4 — Circuit breaker scenario

**Goal:** validate the `AsyncCircuitBreaker` already wrapping order-service's
calls to payment-service (`GET /circuit-breaker/payment`,
`failure_threshold=3`, `recovery_timeout=15s`).

**Steps:**
1. Drive payment-service to fail consistently:
   `python cli.py chaos set payment-service --failure-rate 1.0`.
2. Run `scripts/k6/with-circuit-breaker.js` while polling
   `python cli.py circuit-breaker status` to observe the
   `CLOSED -> OPEN -> HALF_OPEN` transitions (the `circuit_breaker_state`
   Prometheus gauge in `order-service/main.py` can also be graphed directly).
3. Compare latency and downstream load against Phase 3 (retries alone): the
   circuit breaker should fail fast instead of retrying into a dead service.
4. Reset chaos: `python cli.py chaos reset payment-service --yes`.

**Files to add:** `docs/tests/circuit-breaker-results.md`.

**Exit criteria:** documented state transitions plus a latency/throughput
comparison showing reduced cascading failure vs. Phase 3.

## Phase 5 — Resource usage and observability overhead

**Goal:** cover the "Recursos" and "Observabilidad" metric sectors: CPU/RAM
usage, estimated cost per request, OpenTelemetry instrumentation overhead,
span loss under load, and sampling impact.

**Steps:**
1. Capture `docker stats` (or a scripted equivalent) for all service
   containers during a Phase 1 baseline run and during a
   `scripts/k6/stress-test.js` run; record CPU/RAM deltas.
2. Compare request latency with the OTel pipeline active (current default)
   against a run with `OTEL_EXPORTER_OTLP_ENDPOINT` pointed at a no-op/black
   hole endpoint, to isolate instrumentation overhead.
3. Under `stress-test.js` load, compare spans received by Jaeger against
   requests actually served (via `orders/count` deltas) to estimate span
   loss.
4. If sampling needs to be tuned to observe its impact, add
   `OTEL_TRACES_SAMPLER`/`OTEL_TRACES_SAMPLER_ARG` support to
   `services/*/tracing.py` (currently always samples 100% — this is new work,
   not a Phase 0 bug fix) and re-run the comparison at a lower sampling
   ratio.

**Files to add:** `docs/tests/resources-observability-results.md`; a small
`scripts/collect_resource_metrics.sh` (or `.ps1`) helper if manual `docker
stats` capture proves too noisy to record by hand.

**Exit criteria:** documented CPU/RAM usage, estimated cost per request,
OTel overhead percentage, and span-loss/sampling findings.

## Phase 6 — Kubernetes deployment and resilience mechanisms

**Goal:** stand up the existing `k8s/base/` + `k8s/resilience/hpa.yaml`
manifests on a local cluster and exercise Kubernetes-native resilience
(HPA, liveness probes) — the proposal's fourth resilience configuration.

**Steps:**
1. Install `minikube` and `kubectl` locally (deferred until this phase by
   design — do not install them earlier).
2. Build each service image and load it into the cluster
   (`minikube image load <service>:latest`), matching the
   `imagePullPolicy: Never` already set in `k8s/base/deployment.yaml`.
3. **Add liveness and readiness probes** to every service Deployment in
   `k8s/base/deployment.yaml` (currently none are defined — the proposal
   explicitly requires liveness probes as a resilience mechanism, e.g.
   `httpGet: {path: /health, port: 8000}`).
4. Apply `k8s/base/*.yaml` then `k8s/resilience/hpa.yaml`.
5. Validate the HPA: generate CPU load against `order-service`/
   `payment-service` (both already have CPU `requests`/`limits` set in
   `deployment.yaml`) via `scripts/k6/stress-test.js` through
   `kubectl port-forward`, and confirm `kubectl get hpa` shows replicas
   scaling toward `maxReplicas: 5` above 70% CPU.
6. Validate liveness-probe recovery: `kubectl delete pod <payment-service pod>`
   and confirm Kubernetes reschedules it automatically; time the MTTR.

**Files to change:** `k8s/base/deployment.yaml` (add probes),
`docs/tests/kubernetes-results.md` (HPA scaling behavior + MTTR).

**Exit criteria:** HPA scales `order-service`/`payment-service` under load;
a manually deleted pod is replaced automatically and MTTR is measured.

## Phase 7 — Full fault-injection suite

**Goal:** systematically run the four fault types the proposal names, each
tied to the metric sector it is meant to stress.

| Fault | How | Primary metric |
| --- | --- | --- |
| Pod kill | `kubectl delete pod <name>` (Phase 6 cluster) | MTTR |
| Artificial latency | `cli.py chaos set <service> --latency-ms N` | Latency p50/p95/p99, throughput |
| CPU saturation | load tool (k6/JMeter) driving high concurrency, or a `stress`-based sidecar if needed | HPA scale-out behavior, degradation |
| Dependency failure | `cli.py chaos set <service> --failure-rate 1.0`, or stop a container/pod entirely | Error cascade in `order-service`, recovery time |

**Steps:** run each fault against both the Docker Compose stack (Phases 1–5
mechanisms) and the Kubernetes cluster (Phase 6 mechanisms), recording the
same four metric sectors each time so results are comparable across
environments.

**Files to add:** one `docs/tests/fault-<name>-results.md` per fault type.

**Exit criteria:** all four faults executed and documented in both
environments where applicable.

## Phase 8 — Metrics consolidation and dashboards

**Goal:** turn Phases 1–7's raw results into the dashboards and comparison
the proposal expects ("los resultados finalmente se representaran en
dashboards y graficas que se generen con grafana").

**Steps:**
1. Extend `observability/grafana/dashboards/resilencia-overview.json` with
   panels for each of the four sectors (Performance, Resilience, Resources,
   Observability), not just the current basic panel set.
2. Export final graphs/screenshots referenced from a top-level results
   document.
3. Write the final comparison: baseline vs. retries vs. circuit breaker vs.
   Kubernetes resilience, matching the "Resultados Esperados" section of the
   proposal (impact of retries on latency, circuit-breaker effectiveness,
   autoscaling benefits under load, overhead of collecting metrics/traces).

**Files to add/change:**
`observability/grafana/dashboards/resilencia-overview.json`,
`docs/RESULTS.md`.

**Exit criteria:** a single results document answering the proposal's four
expected findings, backed by dashboard screenshots and the per-phase result
docs.

## Phase 9 — Team control interface (last, by design)

**Goal:** only once Phases 1–8 prove the system, observability and
experiments genuinely work, decide whether the team needs anything beyond
`cli.py` for day-to-day demos or reporting.

**Steps:**
1. Review whether `cli.py` (Phase 0) is sufficient for the team's remaining
   needs (it already covers status, seeding, ordering, chaos, circuit
   breaker introspection).
2. If a richer view is genuinely needed (e.g. a read-only results/status
   view for demos), design and scope it here — reusing the existing
   read-only endpoints (`/*/count`, `/*/recent`) rather than adding new
   HTTP-facing control surfaces to the services themselves.
3. Any such interface is evaluated against the finished experiments, not the
   other way around — this is deliberately the last phase in this plan.

**Exit criteria:** an explicit team decision (build/skip) recorded here or in
a follow-up note, made only after Phase 8 is complete.

## Reproducible delivery (cross-cutting, ongoing)

Applies across all phases, not a separate phase to "finish":

- **Docker:** already the primary delivery mechanism (`compose.yml`,
  `run.sh`/`run.ps1`). Keep working as new services/config are added.
- **Kubernetes manifests:** `k8s/base/` + `k8s/resilience/` (Phase 6 adds
  probes; later phases may add more resilience manifests as needed).
- **Deploy scripts:** `run.sh`/`run.ps1` for Compose; `kubectl apply -f`
  sequences for Phase 6 (document the exact apply order once probes are
  added).
- **Public GitHub repo:** keep `1.PROPUESTA...pdf`, `2.CARTA...`,
  `4. Esquema de campos...`, `RESUMEN DE LA FASE 1...`, the `.docx` report,
  and any `.env` out of every commit (enforced by `.gitignore` as of
  Phase 0). Verify with `git ls-files | grep -iE '\.pdf$|\.docx$'` returning
  nothing before ever pushing to a public remote.
