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

## Phase 1 — Baseline scenario (no resilience mechanisms) (done)

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

**Exit criteria:** met. Results (first run 2026-09-04 / re-verification run
2026-09-05, both fresh boots): 258 / 256 requests, 0% error rate both times,
~8.2–8.3 req/s, p50 133–167ms, p95 276–403ms, p99 1.07–1.30s. Numbers vary
run to run as expected for a load test; the shape (near-zero error rate,
sub-500ms p95, all services traced) is stable and is the comparison point
for Phases 3–4. (A Phase 0-5 audit on 2026-09-05 found this exit criteria
line had previously cited different second-run numbers — 271 requests, p50
97ms, p95 213ms, p99 972ms — that were never recorded in
`docs/tests/baseline-results.md` or anywhere else in the repo. The
re-verification run was repeated for real to close that gap; see
`docs/tests/baseline-results.md` "Second run (re-verification)".)

## Phase 2 — Load-testing tooling (k6 + JMeter) (done)

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

## Phase 3 — Retries scenario (done)

**Goal:** measure the proposal's expected trade-off ("retries aumentan
latencia pero reducen errores") using the retry logic already implemented in
`order-service` (`RETRY_ENABLED`/`RETRY_COUNT`/`RETRY_DELAY_MS`).

**Status:** complete. Found and fixed a real bug along the way:
`call_service()`'s retry loop only caught transport exceptions, never a
declined payment (which `payment-service` returns as a normal HTTP 200 with
`{"status": "error"}`) — so `RETRY_ENABLED` was a no-op against exactly the
chaos this phase measures. Fixed in `do_payment()` inside
`services/order-service/main.py`.

A follow-up full audit of Phases 0–3 (requested separately) found the same
root cause in three more call sites — user validation and inventory
availability/reserve (fail via 503, which `httpx` also doesn't turn into an
exception) and notification (fails the same 200+error-body way payment
did). Fixed generically in `call_service()` (also retries on 5xx) plus a
`do_payment()`-style attempt loop for notification. Verified empirically
per service (30 orders each, one chaos target at a time): user-service
73%→100%, inventory-service 47%→100%, notification 67%→97% clean success.
Re-verified Phases 0–2 and the payment scenario show no regression. Full
detail in `docs/tests/retries-results.md`.

**Steps:**
1. Inject failure into a downstream dependency, e.g.
   `python cli.py chaos set payment-service --failure-rate 0.3`.
2. With `RETRY_ENABLED=false` (baseline for this scenario), run
   `scripts/k6/with-retries.js` and record latency/error rate.
3. Set `RETRY_ENABLED=true` (`RETRY_COUNT=3`, `RETRY_DELAY_MS=100` — the
   proposal's own example configuration), restart `order-service`, and repeat
   the same k6 run.
4. Reset chaos: `python cli.py chaos reset payment-service --yes`.

**Files added:** `docs/tests/retries-results.md` (three runs: no retries,
retries with the bug present, retries fixed — plus the bug writeup and
comparison to Phase 1's baseline).

**Exit criteria:** met, with a caveat. Retries reduce error rate sharply
(97% → <1% failed orders under 30% payment failure) once the bug above is
fixed. Latency did **not** clearly increase with retries in this run (p95
was lower with retries than without) — see `docs/tests/retries-results.md`
"Analysis" for why this codebase's failure path doesn't isolate the
"retries cost latency" trade-off cleanly, and a suggested follow-up
(latency-based chaos instead of failure-rate-based) if a cleaner signal is
needed for the report.

## Phase 4 — Circuit breaker scenario (done)

**Goal:** validate the `AsyncCircuitBreaker` already wrapping order-service's
calls to payment-service (`GET /circuit-breaker/payment`,
`failure_threshold=3`, `recovery_timeout=15s`).

**Status:** complete. Fixed `scripts/k6/with-circuit-breaker.js`'s check
gap as flagged in Phase 3, plus a custom Counter separating "failed fast
via open breaker" from "reached payment-service and got declined". Found
and fixed a real concurrency bug along the way: `AsyncCircuitBreaker`'s
`OPEN -> HALF_OPEN` transition had no lock, so under concurrent load every
in-flight request could see the flipped state and slip through together
(a thundering herd) instead of a single probe — confirmed by polling
`GET /circuit-breaker/payment` every 2s and watching `failures` overshoot
the threshold (8-9 instead of a clean 3, then +1 per recovery window).
Fixed with an `asyncio.Lock` guarding only the state check/transition, not
the downstream call itself (no throughput cost in the normal `CLOSED`
path). Re-verified: `failures` now increments by exactly `+1` per 15s
recovery window. Full writeup: `docs/tests/circuit-breaker-results.md`.

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

**Files added:** `docs/tests/circuit-breaker-results.md` (state timeline,
the concurrency bug, before/after comparison, and full results table
against Phase 1 and Phase 3).

**Exit criteria:** met. 92–97% of failed orders across all runs were
rejected fast by the open breaker rather than reaching `payment-service` —
the reduced-cascading-failure result the proposal expects. At 80% payment
failure, retries barely help (0.4%→4.8% success) unlike Phase 3's 30%
scenario (3%→99%), which is expected given `P(all 4 attempts fail)` is
~41% at 80% vs. ~0.8% at 30% — the breaker's fail-fast benefit matters more
precisely when retries can't realistically rescue the outcome.

## Phase 5 — Resource usage and observability overhead (done)

**Goal:** cover the "Recursos" and "Observabilidad" metric sectors: CPU/RAM
usage, estimated cost per request, OpenTelemetry instrumentation overhead,
span loss under load, and sampling impact.

**Status:** complete, with one item deliberately not measured (sampling
impact — see below). `OTEL_SDK_DISABLED` turned out to be a standard OTel
env var the Python SDK already honors with zero code changes to
`tracing.py`; only `compose.yml` needed a line added per service (plus
`.env.example`) to actually forward it into the containers, since Compose
doesn't pass through arbitrary host env vars. Full detail, all numbers,
and honest caveats about sample sizes:
`docs/tests/resources-observability-results.md`.

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

**Files added:** `docs/tests/resources-observability-results.md`;
`scripts/collect_resource_metrics.sh` (docker-stats-to-CSV sampler, needed
in practice since `docker stats --no-stream` itself takes ~5-6s per call
on this machine); `OTEL_SDK_DISABLED` wired into `compose.yml`/
`.env.example` (default `false`, permanent, reusable for later phases).

**Exit criteria:** met, mostly. CPU/RAM documented (order-service is the
clear bottleneck: 83% avg / 110% max CPU under 200-VU load, vs. <1% for
every other microservice at idle). Rough per-request CPU cost documented
(order-service ≈40ms CPU/request, roughly as much as all four downstream
services combined). OTel overhead measured cleanly: **+35-42% median/p95
latency** with OTel enabled vs. disabled. Span loss: none observed at this
load level (~21-43 req/s peak — order-service's own CPU ceiling was hit
well before the tracing pipeline showed any strain, so this doesn't prove
the pipeline is lossless at higher throughput, just that it wasn't
stressed here). **Sampling impact was not measured** — deliberately
deferred since it requires adding sampler configuration to
`services/*/tracing.py` that doesn't exist yet, which the plan explicitly
treats as optional new work rather than a Phase 0-style bug fix; a
concrete implementation note for whoever picks this up is in the results
doc.

## Phase 6 — Kubernetes deployment and resilience mechanisms (done)

**Goal:** stand up the existing `k8s/base/` + `k8s/resilience/hpa.yaml`
manifests on a local cluster and exercise Kubernetes-native resilience
(HPA, liveness probes) — the proposal's fourth resilience configuration.

**Status:** complete. Installed `minikube` (`kubectl` was already available
via Docker Desktop), enabled the `metrics-server` addon (required for the
HPA to read CPU%), built and loaded all 5 service images, and added
liveness/readiness probes (`GET /health:8000`) to all 5 microservice
Deployments in `k8s/base/deployment.yaml`. HPA validated empirically:
`order-service-hpa` scaled 1 → 3 replicas under `stress-test.js` load
(confirmed via the `SuccessfulRescale` Kubernetes event, CPU utilization
peaking at 201% of the 70% target); `payment-service-hpa` correctly stayed
at 1 replica (only reached 30% CPU — it's exercised second-hand through
`order-service`, consistent with Phase 5's CPU-bottleneck finding).
Pod-kill MTTR measured across three independent runs (11.55s, 26.50s,
12.12s) - always a fully automatic replacement with no manual
intervention, in the tens-of-seconds range. Two genuine Kubernetes-native
findings surfaced
and are documented as tuning notes rather than fixed in this phase (outside
its stated scope of probes + HPA/MTTR validation): (1) 4 of 5 microservices
restart exactly once on a cold cluster boot because `k8s/` has no
Compose-equivalent `depends_on: condition: service_healthy` ordering
against `postgres` — self-heals via `restartPolicy: Always` within
~10-15s; (2) under the same CPU-saturation spike that triggered the HPA
scale-out, `order-service`'s own liveness probe timed out
(`timeoutSeconds: 3`) against its overloaded `/health` and killed+restarted
that pod — a known liveness-probe-under-genuine-load gotcha, not a bug.
Full detail, all timestamps and events: `docs/tests/kubernetes-results.md`.

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

**Files changed:** `k8s/base/deployment.yaml` (probes added to all 5
microservices), `docs/tests/kubernetes-results.md` (HPA scaling behavior +
MTTR, new file).

**Exit criteria:** met. HPA scales `order-service` under load (`payment-service`
did not scale in this run since it was only exercised indirectly — see
results doc); a manually deleted pod is replaced automatically and MTTR is
measured (11.55s / 26.50s across two independent runs - see
`docs/tests/kubernetes-results.md` "Re-verification").

## Phase 7 — Full fault-injection suite (done)

**Goal:** systematically run the four fault types the proposal names, each
tied to the metric sector it is meant to stress.

**Status:** complete. All four faults executed and documented against both
Compose and Kubernetes (CPU saturation reused the load tests already run
in Phases 5-6 against both environments rather than repeating a third
identical 4-minute run — everything else is new). Headline findings:
pod/container kill has **unbounded MTTR in Compose (no `restart:` policy on
any live service) vs. ~11-27s in Kubernetes** (11.55s and 26.50s across
two runs, same order of magnitude) — the core resilience gap the
proposal expects Kubernetes to close; artificial latency (500ms×2 on
`inventory-service`) showed the injected delay landing almost exactly on
the median in both environments, with Kubernetes carrying a wider tail
from the `kubectl port-forward` tunnel used to reach it; dependency
failure (`user-service` at 100%) turned out to be a clean fail-fast
short-circuit rather than a multi-service cascade (`order-service` never
calls inventory/payment/notification once user validation fails) and
recovered instantly in both environments once chaos was reset (no
circuit-breaker-style recovery delay, since `FAILURE_RATE` is a stateless
per-request config read); CPU saturation confirmed the HPA genuinely
scales `order-service` (1→3 replicas) but its raw numbers are not directly
comparable to Compose's due to the 200m per-pod CPU cap and the
port-forward tunnel, both called out explicitly rather than presented as a
clean apples-to-apples result. Full detail in
`docs/tests/fault-pod-container-kill-results.md`,
`docs/tests/fault-artificial-latency-results.md`,
`docs/tests/fault-dependency-failure-results.md`, and
`docs/tests/fault-cpu-saturation-results.md`.

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

**Files added:** `docs/tests/fault-pod-container-kill-results.md`,
`docs/tests/fault-artificial-latency-results.md`,
`docs/tests/fault-dependency-failure-results.md`,
`docs/tests/fault-cpu-saturation-results.md`.

**Exit criteria:** met. All four faults executed and documented in both
environments where applicable.

## Phase 8 — Metrics consolidation and dashboards (done)

**Goal:** turn Phases 1–7's raw results into the dashboards and comparison
the proposal expects ("los resultados finalmente se representaran en
dashboards y graficas que se generen con grafana").

**Status:** complete. Extended `resilencia-overview.json` from 2 basic
panels to 12, covering all four metric sectors (Performance, Resilience,
Resources, Observability), backed entirely by metrics that were already
being exposed (each service's own `prometheus_client` `/metrics`, no new
instrumentation needed). Found and fixed a real, previously-silent bug
while building it: every panel (including the two pre-existing ones)
showed "No data" because `observability/grafana/provisioning/datasources/prometheus.yml`
never pinned an explicit datasource `uid`, so Grafana auto-generated a
random one that didn't match the `"uid": "prometheus"` hardcoded in the
dashboard JSON - fixed by pinning `uid: prometheus` in the provisioning
file. Verified live: generated real traffic (a k6 run with latency chaos
injected), confirmed every panel's PromQL against Prometheus directly, and
screenshotted the populated dashboard via Playwright. Wrote
`docs/RESULTS.md` synthesizing all four of the proposal's expected
findings (retries' latency impact, circuit-breaker effectiveness,
autoscaling benefits, OTel overhead) from the per-phase docs, plus a
cross-sector summary table. Known gap, out of this phase's scope: the
Kubernetes cluster's own Grafana has no dashboard/datasource provisioning
at all (`k8s/base/deployment.yaml` mounts nothing for it) - the dashboard
built here only runs against Compose.

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

**Files changed:**
`observability/grafana/dashboards/resilencia-overview.json` (2 -> 12
panels), `observability/grafana/provisioning/datasources/prometheus.yml`
(pinned `uid: prometheus` - bug fix), `docs/RESULTS.md` (new),
`docs/tests/screenshots/resilencia-overview.png` and
`resilencia-overview-observability.png` (new).

**Exit criteria:** met. `docs/RESULTS.md` answers the proposal's four
expected findings, backed by two dashboard screenshots (captured live,
during an active load test) and every per-phase result doc.

## Phase 9 — Team control interface (last, by design) (done)

**Goal:** only once Phases 1–8 prove the system, observability and
experiments genuinely work, decide whether the team needs anything beyond
`cli.py` for day-to-day demos or reporting.

**Decision (2026-09-06): skip.** `cli.py` (status, seeding, ordering, chaos
injection/reset, circuit-breaker introspection) plus the Grafana
`Resilencia Overview` dashboard (Phase 8, 12 panels across all four metric
sectors) plus `docs/RESULTS.md` (the written comparison) already cover
every need that surfaced across Phases 0–8 — operating the stack, running
demos, and reporting results. No gap requiring a new interface was found
during any phase. Building one now would duplicate `cli.py` and the
dashboard for no identified benefit. This closes the plan: Phases 0–9 are
all complete.

**Steps (historical, kept for context):**
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

## Phase 10 — Kubernetes hardening & parity with Compose (done)

**Goal:** close every Kubernetes-side code gap found during the Phases
0-9 audit so the cluster matches Compose's dependency-ordering,
self-healing and tooling parity, on the way to a Helm-based delivery.

**Status:** complete, all 5 items verified live. `initContainer` (wait for
postgres) added to all 5 microservices - a full pod-sweep restart showed
0/5 restarts (previously a guaranteed 1 each). `order-service` liveness
probe retuned - re-ran the same 200-VU stress test that used to
self-restart it: HPA scaled 1→3 again, 0 restarts this time. Grafana
provisioning added for Kubernetes - and while verifying it, found **two
real, previously undetected bugs**: K8s Prometheus was never scraping the
microservices/otel-collector (no config was ever mounted - it only
scraped itself), and K8s Jaeger's Service never exposed port 4317 so
every trace export from otel-collector silently failed with a timeout.
Both fixed and re-verified (5 Prometheus targets up, all 5 services
visible in Jaeger). Added a Kubernetes Job mirroring Compose's
`data-seeder` - confirmed 50,000 users seeded. Converted everything into a
Helm chart (`charts/resilencia/`) - `helm lint` clean, and a real `helm
install` into an isolated namespace brought up all 11 resources with 0
restarts on the first try, order placement confirmed working, then torn
down. Full detail: `docs/tests/kubernetes-hardening-results.md`.

**Steps:**
1. Add an `initContainer` (busybox polling `nc -z postgres 5432` or
   equivalent) to all 5 microservice Deployments in
   `k8s/base/deployment.yaml`, so they wait for `postgres` before the main
   container starts. Fixes the documented cold-boot restart
   (`docs/tests/kubernetes-results.md`). Verify with a fresh
   `kubectl delete pod` sweep or cluster restart: zero restarts expected.
2. Retune `order-service`'s liveness probe (`timeoutSeconds`/
   `failureThreshold`) so it stops self-restarting under genuine CPU
   saturation (documented finding, same doc). Re-run
   `scripts/k6/stress-test.js` against the cluster and confirm no
   self-inflicted restart this time.
3. Add Grafana provisioning to Kubernetes (ConfigMaps for datasources +
   the `resilencia-overview.json` dashboard, mounted like Compose does) so
   the Phase 8 dashboard also works against the cluster, not just Compose.
4. Add a Kubernetes Job for the 50k-user seed (mirrors Compose's
   `data-seeder`) so the cluster isn't limited to the 3-user/3-product
   `db-configmap.yaml` dataset.
5. Convert `k8s/base/` + `k8s/resilience/` into a Helm chart
   (`charts/resilencia/` or similar) with a `values.yaml` for ports,
   replica counts, probe timings and resource limits - the proposal
   explicitly names Helm and it was never used.

**Files changed:** `k8s/base/deployment.yaml`, `k8s/base/service.yaml`
(jaeger OTLP port fix), new `k8s/base/grafana-provisioning-configmap.yaml`,
new `k8s/base/observability-config-configmap.yaml` (prometheus +
otel-collector configs), new `k8s/base/seed-job.yaml`, new
`charts/resilencia/` (Chart.yaml, values.yaml, templates/, files/), new
`docs/tests/kubernetes-hardening-results.md`.

**Exit criteria:** met. Helm install boots with zero cold-boot restarts
(verified twice, live); Grafana dashboard renders with live data
in-cluster; the seed Job populates 50k users; HPA and probes still work
with no regression (re-ran Phase 6/7's exact stress test and pod-kill
scenarios).

## Phase 11 — Observability completeness & final validation (done)

**Goal:** close the remaining observability code gaps (alerting, sampling),
actually execute the one test tool that was authored but never run
(JMeter), then run a full regression pass across every phase to confirm
the whole system - Compose and the now-hardened Kubernetes cluster - still
meets every previously documented result.

**Status:** complete, all 4 items verified live. `observability/alerts.yml`
added (`ServiceDown`, `CircuitBreakerOpen`, `HighOrderLatencyP95`,
`HighOrderErrorRate`), wired via `rule_files` in both Compose and
Kubernetes; `CircuitBreakerOpen` was driven to an actual `firing` state
live (not just loaded/`ok`) by opening the real breaker and waiting out
the `for: 1m` window - confirmed via `/api/v1/alerts`. HPA-at-`maxReplicas`
was scoped out: it would need `kube-state-metrics` scraped into
Prometheus, which isn't deployed, and adding it was judged out of scope
for an alerting pass; noted as a further gap rather than silently
dropped. `OTEL_TRACES_SAMPLER`/`OTEL_TRACES_SAMPLER_ARG` support added to
all 5 `tracing.py` files (a `_build_sampler()` reading the standard OTel
env vars, since this project constructs `TracerProvider` by hand and
never inherited the SDK's automatic env-reading); measured at 10% vs.
100%: span export volume tracked the ratio (147/1110 ≈ 13.2% of spans
exported, close to the configured 10% given only 30 sampled traces), with
a real-but-modest latency saving distinct from Phase 5's much larger
`OTEL_SDK_DISABLED` effect (sampling still creates and instruments every
span, it just doesn't export the dropped ones). JMeter installed (plain
zip, not the winget package - its bundled-JDK MSI hangs on a UAC prompt in
a non-interactive session) and `scripts/jmeter/baseline.jmx` actually run
for the first time: 215 requests, 0% error, p50/p90/p95 closely matching
k6's Phase 1 numbers (p99 differs - explained, not swept under the rug, in
the results doc). Regression pass across both environments (Compose
retries/circuit-breaker re-triggered live, Kubernetes pods/HPA/order-flow
re-checked) found no regressions from Phase 10's changes. Full detail:
`docs/tests/sampling-results.md`, `docs/tests/jmeter-results.md`; alert
rules covered inline here and in `docs/RESULTS.md`.

**Steps:**
1. Add Prometheus alerting rules (`rule_files`) for signals already
   scraped: high error rate, circuit breaker `OPEN`, high p95 latency, HPA
   pinned at `maxReplicas`. The proposal names this explicitly; it was
   never implemented.
2. Add `OTEL_TRACES_SAMPLER`/`OTEL_TRACES_SAMPLER_ARG` support to
   `services/*/tracing.py` (5 files) and measure the sampling-impact
   comparison Phase 5 deliberately deferred, at 2-3 sampling ratios.
3. Install JMeter and actually run `scripts/jmeter/baseline.jmx` headless
   (`jmeter -n -t ... -l results.jtl`), comparing its numbers against k6's
   Phase 1 baseline - the plan.jmx was authored in Phase 2 but never
   smoke-tested end to end.
4. Full regression: re-run Phase 1 baseline, Phase 3 retries, Phase 4
   circuit breaker, and Phase 7's four faults against both environments
   post-Phase-10-hardening; confirm no regressions and update any results
   doc whose numbers meaningfully shifted.

**Files changed:** `observability/alerts.yml` (new),
`observability/prometheus.yml` (`rule_files` + `evaluation_interval: 15s`),
`compose.yml` (mount `alerts.yml`, `OTEL_TRACES_SAMPLER`/`_ARG` on all 5
microservices), `.env.example`, `k8s/base/observability-config-configmap.yaml`
(+ `prometheus-alerts` ConfigMap), `k8s/base/deployment.yaml` (mount),
`services/*/tracing.py` (5 files, sampler support), new
`docs/tests/sampling-results.md`, new `docs/tests/jmeter-results.md`.

**Exit criteria:** met. Alert rules load and one (`CircuitBreakerOpen`) was
driven to a real `firing` state in both environments; sampling is
configurable and its impact measured; JMeter has a real completed run
comparable to k6's; the regression pass found no behavior changes from
Phase 10.

## Phase 12 — Administration & monitoring control panel

**Status:** partial. Built `services/control-panel/` (FastAPI backend +
single static page), added as a Compose service on port 8105. Delivers
the **Monitor** half in full: service health, per-service CPU/RAM/disk-write
(disk via the Docker socket - `prometheus_client`'s ProcessCollector has no
I/O metric, so this isn't in Prometheus), circuit breaker state, record
counts, a live **Kubernetes** panel (pods + HPA status, read directly from
the minikube API server via mounted client certs, `verify=False` since the
cert is issued for the cluster's own hostname not `host.docker.internal`
- a local-dev-only cluster, not a real trust boundary), and an embedded
**Grafana** dashboard (iframe in kiosk mode; `GF_SECURITY_ALLOW_EMBEDDING`/
`GF_AUTH_ANONYMOUS_ENABLED` added to Grafana's Compose config so the iframe
doesn't need a login). The **Operate** half uses only APIs that already
existed (place orders, generate users/inventory, view recent records,
per-user order history, chaos control per service). **Not delivered:**
real create/edit/delete of existing records - none of the 5 microservices
expose PUT/DELETE routes, and adding them was out of scope (would mean new
endpoints in 5 services, not just a UI); the Kubernetes panel is read-only
(no delete-pod / scale button). Design-skill process (`claude-design`, HTML
mockups rendered to PNG first) was skipped under time constraints - built
directly instead. Verified live: every API route tested via curl (health,
resources, disk, kubernetes, circuit-breaker, chaos, orders, generate,
recent, order history), Grafana iframe and Kubernetes tables confirmed
rendering real data in-browser.

**Goal:** give the team a single web interface that (a) monitors the live
system — metrics, Grafana, Kubernetes, and per-service resource usage —
and (b) administers the data completely and in a controlled way: add,
edit and delete users, products, orders, payments and notifications,
place orders, generate data, and set a failure standard (chaos) per
service. This deliberately **reverses Phase 9's "skip" decision**: the
audit that led to Phase 12 found a real gap the earlier decision missed —
today no surface (cli.py or Grafana) can *edit or delete* records or show
per-service resource usage in one place, so a "team control interface"
that can only read and bulk-generate is incomplete for day-to-day
administration and monitoring.

**Scope decision:** local study tool — **no login/authentication**. The
UI talks to the services over the host-published ports, same as `cli.py`
and the README's curl examples.

**Design instruction (for whoever builds the UI — Claude):** build the
panel as a *Monitor + Operate* interface (dense, glanceable hierarchy;
action affordances; no marketing framing, no decorative metrics). Use the
installed design skills, by name: `claude-design` (design process and
taste, surface-first, anti-slop), `ui-mockup-screens` and
`html-mockup-render` (build the screens as self-contained HTML mockups and
render/verify them to PNG before wiring them to the live data). Follow the
repo's stack (`services/frontend/` was the original UI location; Phase 0
removed it — recreate under `services/control-panel/`). Flat, minimalist,
professional dashboard style; functional graphs with real data, never fake
numbers. No emojis, no gradients/glassmorphism by default.

**Audited baseline the panel must build on (what already exists):**
- Every microservice already exposes `/metrics`
  (`prometheus_fastapi_instrumentator` + `prometheus_client`):
  `http_request_duration_seconds` (histogram), `http_requests_total`,
  `process_cpu_seconds_total`, `process_resident_memory_bytes`; plus a
  `circuit_breaker_state` gauge on `order-service`.
- Grafana `Resilencia Overview` dashboard (Phase 8) already has 12 panels
  across the four sectors: Performance (p50/p95/p99 latency, throughput),
  Resilience (circuit-breaker state, healthy targets), Resources
  (per-service CPU + resident memory), Observability (scrape health).
- Prometheus scrapes all 5 microservices + `otel-collector`.
- **Gaps the panel must close (found in this audit):**
  1. Only `order-service`'s latency histogram is surfaced in Grafana by
     handler; per-service latency for the other four is not shown.
  2. **No disk / block-I/O metrics anywhere** — no cadvisor, no
     node-exporter. To honor "escritura de disco" the stack needs a source
     (add `cadvisor` (or `node-exporter`) to `compose.yml`/Prometheus
     scrape config) so container disk/network I/O can be charted.
  3. No CORS on any service; no CRUD edit/delete endpoints; list endpoints
     cap at `limit <= 100` (no pagination/offset/search).

**Steps (backend first — the UI can't administer what the API can't
change):**

1. Enable **CORS** on all 5 microservices (or serve the panel from an
   origin the APIs allow) so a browser SPA can call the existing and new
   endpoints.
2. Add **pagination + search/filter** (`offset`/`limit`, filters) to the
   list endpoints — today `/*/recent` and list endpoints cap at
   `limit <= 100` and only return the most recent rows, which is unusable
   for exploring a 50k-user dataset. Support sorting and keyword/field
   filters per entity.
3. Add the missing **write endpoints** per service, following each
   service's existing `create_*`/serialization patterns:
   - `user-service`: `PUT`/`PATCH /users/{id}` (edit customer profile),
     `DELETE /users/{id}`.
   - `inventory-service`: `POST /inventory` (create a product by hand),
     `PATCH /products/{id}` (quantity, price, data), `DELETE /products/{id}`.
   - `order-service`: `PATCH /orders/{id}/status` (status, priority,
     internal_status), `DELETE /orders/{id}`.
   - `payment-service`: paginated `GET /payments`, `DELETE /payments/{id}`.
   - `notification-service`: paginated `GET /notifications`,
     `DELETE /notifications/{id}`.
4. Add **per-service latency/error metrics surfacing** in the panel from
   each service's own `/metrics` histogram
   (`http_request_duration_seconds{handler=...}` grouped by service),
   not just order-service's.
5. Add a **host/infrastructure metric source**: add `cadvisor` (or
   `node-exporter`) to `compose.yml` and to Prometheus
   (`observability/prometheus.yml`) so CPU, RAM and **disk write/block I/O**
   per container (and per pod in K8s) can be charted.
6. Provide **guided JSONB editing** of the nested profile/details fields
   (the ~105 fields from `Campos por servicio.md`), not raw JSON — the
   panel exposes concrete fields per entity (name, email, stock, price,
   shipping address, etc.) and serializes them back into the JSONB
   columns. Raw JSON editing only as a power-user fallback. All edits go
   through the API with server-side **validation** (same rules the
   create/order flow enforces) and a confirm/undo affordance in the UI.
7. Build the **frontend panel** (`services/control-panel/`, a static SPA
   served alongside the stack) as **a dashboard root plus one subpage per
   service**, so each microservice has its own dedicated view where you
   monitor, modify, delete and add records in a controlled way. Layout:
   - **Root dashboard**: overall system health, record counts per entity,
     per-service up/down, latency/error summaries, and the four metric
     sectors. Provide a view that **embeds or links the Grafana
     `Resilencia Overview` dashboard** (Phase 8) and, separately, a
     **Kubernetes view** (pods, replicas, HPA, per-pod CPU/RAM/disk)
     for the Phase 6+ cluster.
   - **Per-service subpage** (×5: order, user, inventory, payment,
     notification): that service's own metrics (latency p50/p95/p99,
     throughput, error rate, CPU, RAM, disk I/O) + its CRUD table
     (list/search/page/edit/delete) + its chaos control.
   - **Infrastructure subpage**: Prometheus / Grafana / Jaeger /
     otel-collector status, host CPU/RAM/disk, cadvisor/node-exporter
     panels.
   - **Chaos / fault view**: set and reset a failure standard per service
     (failure rate, latency, timeout — the "estándar de fallo" the
     original UI exposed), with validation and a confirmation step, and
     show circuit-breaker state — moving `cli.py`'s controls into the UI.
   - **Actions view**: place an order, generate users/products, show
     counts (mirrors `cli.py`).
   - **Alerts view**: surface Prometheus alert rules (once Phase 11 adds
     them) and highlight services in a degraded/chaos state, breaker
     `OPEN`, error spikes, or pods restarting.
8. Wire the panel into `compose.yml` (and the Phase 6+ Kubernetes
   manifests once Phase 10's parity work lands) with its own port.

**Files to add/change:** `services/*/main.py` (5 services: CORS,
pagination, CRUD endpoints), new `services/control-panel/` (SPA),
`compose.yml` (+ control-panel service and cadvisor/node-exporter),
`observability/prometheus.yml` (+ cadvisor/node-exporter scrape job),
Grafana dashboard additions if per-service panels are added, docs update
(`docs/TOOLING.md`, `README.md`, `docs/01.Arquitectura.md`).

**Exit criteria:** from the panel (no terminal, no direct DB access) a
user can view live metrics in all four sectors plus per-service and
per-pod CPU/RAM/disk; list/search/page every entity; add, edit and delete
a user, product, order, payment and notification with validation; place
an order; generate users/products; set and reset a failure standard per
service and observe the circuit breaker; see infrastructure status and
alerts — all against the Compose stack (the primary target) and, once
Phase 10 lands, against the hardened Kubernetes cluster without code
changes. UI verified by rendering the mockups (via `ui-mockup-screens` /
`html-mockup-render`) before wiring live data.

## Reproducible delivery (cross-cutting, ongoing)

Applies across all phases, not a separate phase to "finish":

- **Docker:** already the primary delivery mechanism (`compose.yml`,
  `run.sh`/`run.ps1`). Keep working as new services/config are added.
- **Kubernetes manifests:** `k8s/base/` + `k8s/resilience/` (Phase 6 adds
  probes; later phases may add more resilience manifests as needed).
- **Deploy scripts:** `run.sh`/`run.ps1` for Compose; for Phase 6+:
  `minikube start --driver=docker && minikube addons enable metrics-server`,
  then build+`minikube image load` each service, then
  `kubectl apply -f k8s/base/ && kubectl apply -f k8s/resilience/hpa.yaml`
  (order between the two `apply` calls doesn't matter in practice — see
  `docs/tests/kubernetes-results.md`).
- **Public GitHub repo:** keep `1.PROPUESTA...pdf`, `2.CARTA...`,
  `4. Esquema de campos...`, `RESUMEN DE LA FASE 1...`, the `.docx` report,
  and any `.env` out of every commit (enforced by `.gitignore` as of
  Phase 0). Verify with `git ls-files | grep -iE '\.pdf$|\.docx$'` returning
  nothing before ever pushing to a public remote.
