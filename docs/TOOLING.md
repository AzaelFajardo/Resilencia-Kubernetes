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

## Resource sampling and OTel overhead toggle (Phase 5)

`scripts/collect_resource_metrics.sh <output.csv> <interval_seconds>
<iterations>` samples `docker stats --no-stream` for every
`resilencia-kubernetes-*` container and appends CSV rows. Note: each
`docker stats --no-stream` call itself takes ~5-6s on Windows/Docker
Desktop regardless of the requested interval — size `iterations` around
that real cadence (`test_duration_seconds / ~6`), not the interval
argument alone.

`OTEL_SDK_DISABLED` (standard OpenTelemetry env var, default `false`) is
now wired into `compose.yml`/`.env.example` for all 5 microservices. The
Python SDK already honors it with zero code changes to `tracing.py` —
`TracerProvider.get_tracer()` returns a `NoOpTracer()` when set, so
setting it and recreating the affected containers (`docker compose up -d
--no-deps <service...>`) is enough for a clean A/B latency comparison with
OTel instrumentation on vs. off. See `docs/tests/resources-observability-results.md`
for the measured overhead (+35-42% median/p95 latency in this stack).

## Targeting `cli.py` at the Kubernetes cluster instead of Compose (Phase 6+)

`cli.py` resolves every service URL from `http://{CLI_HOST}:{<SERVICE>_PORT}`
(env vars, defaulting to the Compose host ports in `.env.example`) — no code
change is needed to point it at a Kubernetes cluster instead. In Kubernetes,
Services are ClusterIP-only (no host port), so `kubectl port-forward` each
one to a free local port and pass those as env var overrides on invocation.
Using a `+10000` offset from the Compose defaults keeps both stacks reachable
side by side without a port clash, which matters for Phase 7 (same faults
run against both environments for comparison):

```bash
# One-time, per service, kept running in the background:
kubectl port-forward svc/order-service        18100:8000 &
kubectl port-forward svc/user-service         18101:8000 &
kubectl port-forward svc/inventory-service    18102:8000 &
kubectl port-forward svc/payment-service      18103:8000 &
kubectl port-forward svc/notification-service 18104:8000 &

# Then any cli.py command, pointed at the cluster instead of Compose:
ORDER_SERVICE_PORT=18100 USER_SERVICE_PORT=18101 \
INVENTORY_SERVICE_PORT=18102 PAYMENT_SERVICE_PORT=18103 \
NOTIFICATION_SERVICE_PORT=18104 \
  python cli.py chaos set payment-service --failure-rate 1.0 --yes
```

Verified working end to end against the Phase 6 cluster: `status`,
`chaos set`/`reset` (both `--failure-rate` and `--latency-ms`), and
`circuit-breaker status` all behave identically to the Compose invocation —
same JSON shapes, same effect on a subsequent `POST /orders`. The
Kubernetes `db-configmap.yaml` seed is the small hand-written dataset (3
users/3 products, not the 50k-user Faker seed — there's no `data-seeder`
equivalent in `k8s/base/` yet), so the same product-1 stock-bump caveat
from Phase 1 applies (`kubectl exec` into the `postgres` pod instead of
`docker compose exec`).

`kubectl port-forward` is fine for chaos control and single requests, but
is itself a throughput bottleneck under a real load test (confirmed during
Phase 6's HPA validation — see `docs/tests/kubernetes-results.md`).
Load-generating faults (CPU saturation) against the cluster inherit that
caveat; treat absolute latency numbers from a port-forwarded load test as
directional, not a clean apples-to-apples comparison with Compose's numbers.

## Grafana dashboard (Phase 8)

`observability/grafana/dashboards/resilencia-overview.json` has 12 panels
across the proposal's 4 metric sectors (Performance, Resilience, Resources,
Observability), all backed by metrics the services already expose via
`prometheus_client` on `/metrics` (`http_request_duration_seconds`,
`http_requests_total`, `process_cpu_seconds_total`,
`process_resident_memory_bytes`, `circuit_breaker_state`) - no new
instrumentation was added.

**Gotcha found while building it, fix now permanent:**
`observability/grafana/provisioning/datasources/prometheus.yml` didn't pin
an explicit `uid:` on the Prometheus datasource, so Grafana auto-generates
a random one on first provisioning (e.g. `PBFA97CFB590B2093`). Every panel
in the dashboard JSON hardcodes `"datasource": {"uid": "prometheus"}` -
without the pin, that never matches, and **every panel silently shows "No
data"**, including the two pre-Phase-8 panels that always existed. Fixed by
adding `uid: prometheus` to the datasource provisioning file. If the
`grafana-data` Docker volume is ever wiped and this pin is somehow removed
again, this is the first thing to check.

The OTel *metrics* pipeline (`otel-collector.yaml`'s `metrics` pipeline,
exporting to `:8889`) is wired but always empty - every service's
`tracing.py` only sends traces, never OTel metrics. Don't confuse it with
the Prometheus scrape of each service's own `:8000/metrics`, which is what
every dashboard panel actually reads.

See `docs/RESULTS.md` for the consolidated analysis this dashboard feeds
into.

## Control-panel backend endpoints (frontend refactor)

The `control-panel` service (`:8105`) is a thin proxy/aggregation layer over
the microservices and Prometheus. During the frontend refactor the following
endpoints were added (proxies are exposed under `/api/*`, the real logic lives
in each service):

- `POST /users/faker?count=N` (user-service) and
  `POST /inventory/faker?count=N` (inventory-service) — generate N Faker
  records on demand (ids after the current max). Field definitions live in
  `services/*/faker_utils.py` (mirrors `scripts/generate_data.py`).
- `GET /users`, `GET /inventory`, `GET /orders`, `GET /payments`,
  `GET /notifications` — now support pagination (`offset`/`limit`) and
  `?search=` (id/name/email/status depending on the entity). `GET /orders`
  (paginated) is new; previously only `/orders/recent` existed.
- `POST /orders/generate` (order-service) — bulk-generates orders through the
  real flow. Body: `count`, optional `user_id`, `clients`,
  `orders_per_client`, `quantity`, `product_id`.
- `POST /orders/simulate/start` / `POST /orders/simulate/stop` /
  `GET /orders/simulate/status` (order-service) — a continuous background
  task (asyncio) that places random orders at a configurable rate (`rate`
  req/s, `quantity`, `clients`, optional `duration`). Status reports
  `running/sent/success/failed/rate`.
- `GET /resilience/retries` / `POST /resilience/retries` (order-service) —
  read/toggle `RETRY_ENABLED`/`RETRY_COUNT`/`RETRY_DELAY_MS` at runtime
  (previously only settable via env vars at boot).
- `GET /chaos/config` (all 5 services) — read the current
  `FAILURE_RATE`/`LATENCY_MS`/`TIMEOUT_RATE` (previously write-only).
- `POST /api/services/{service}/{action}` (control-panel) — **stop/start a
  microservice container for real** via the Docker SDK (socket mounted `rw`).
  Stopping a service is reflected across the stack (health, order flow, etc.).
- `GET /api/throughput` (control-panel) — per-service req/s and 5xx error rate
  from Prometheus.
- `GET /api/targets` (control-panel) — Prometheus scrape targets and health.

## Kubernetes cluster operations (Phase 6 / Fase 5 E2E)

The smaller truth of living with a minikube cluster while the shared
orchestrator module (Fase 4) and the control-panel evolve:

### Arranque y parada asistidos

Dos helpers en `scripts/` dejan el entorno listo de forma reproducible y
ordenada. Se invocan tambien desde la raiz como `./run.sh k8s` y
`./run.sh stop` (solo macOS/Linux; requieren Docker, y para Kubernetes tambien
`minikube` y `kubectl` en el `PATH`).

`./scripts/up.sh` (`./run.sh k8s`) hace, en orden:

1. Asegura `minikube` (driver docker). Si la VM estaba apagada, detiene antes
   `control-panel` para liberar `192.168.49.2` (evita `Address already in use`)
   y habilita el addon `metrics-server` (necesario para el HPA).
2. Construye las imagenes de los 5 microservicios + `data-seeder` y las carga
   al cluster (`minikube image load`, con `rmi` previo para no cachear capas).
3. Comprueba `k8s/certs/` y aplica `k8s/base/` + `k8s/resilience/hpa.yaml`.
4. Espera los rollouts de todos los deployments y el `job/data-seeder`.
5. Levanta el stack Docker Compose (control-panel + observabilidad).
6. Reactiva el modo Kubernetes del control-panel (el toggle vive en memoria y
   se resetea en cada arranque del contenedor).

Opciones: `--compose-only`, `--k8s-only`, `--no-build`, `--reset` (borra
volumenes Compose y manifiestos antes de arrancar).

`./scripts/down.sh` (`./run.sh stop`) detiene todo sin forzar nada:

1. `docker compose stop -t 30` (SIGTERM con 30s de gracia; no borra los
   contenedores, se reanudan con `up.sh`).
2. `minikube stop` (apagado ordenado de la VM; pods y PVCs persisten).

No borra datos por defecto. Opciones: `--compose-only`, `--k8s-only`,
`--keep-cluster` (detiene solo Compose) y `--purge` (ademas elimina volumenes
Compose y manifiestos del cluster).

### Rebuild + redeploy a service image (after editing `shared/` or a service)

The microservice images bake in `services/shared/orchestrator.py`, so a code
change there requires a full rebuild + reload into the cluster node:

```bash
for s in order user inventory payment notification; do
  docker build -q -t ${s}-service:latest -f services/${s}-service/Dockerfile services
  minikube ssh "docker rmi ${s}-service:latest"        # force reload, avoids stale layer cache
  minikube image load ${s}-service:latest
done
kubectl rollout restart deployment $(kubectl get deploy -o name | grep -E 'order|user|inventory|payment|notification')
```

The HPA will fight a `kubectl scale ... --replicas=` down to *below* the
autoscaler's `minReplicas` (minikube's HPA rejects `minReplicas: 0` unless an
Object/External metric exists), so to fully stop a service for a failover demo,
either delete its HPA first (remember to re-apply `k8s/resilience/hpa.yaml`
afterwards) or scale to its min.

### Rebuild + restart the control-panel

`main.py` is baked into the image; the static JS rides a volume (`ro`) and does
**not** need a rebuild. `docker compose up -d --build control-panel`, then
re-enable the Kubernetes runtime mode — it is an in-memory toggle that resets
to Compose mode on every container start:

```bash
curl -s -X POST -H 'Content-Type: application/json' \
  -d '{"mode":"kubernetes"}' http://localhost:8105/api/runtime-mode
```

### minikube came back Stopped / "Address already in use" on start

The control-panel container joins the external `minikube` Docker bridge
(`compose.yml` `networks.minikube`). That subnet is `192.168.49.0/24` and the
kube-apiserver lives at node IP `192.168.49.2`; if the VM is down when the
container restarts, Docker assigns the control-panel the *same* `192.168.49.2`
and `docker start minikube` fails (`Address already in use`). Recovery order:

```bash
docker compose stop control-panel   # release the stolen 192.168.49.2
docker start minikube               # VM takes 192.168.49.2 back
minikube start                      # bring kubelet/apiserver up (pod states persist)
docker compose start control-panel  # joins the bridge on a fresh DHCP address
```

### Leader pod routing (why the panel no longer 503s)

With replicas running, only the pod holding the leadership lease serves the
guarded order endpoints; the rest answer `503 "not the current
orchestrator leader"`. Routing through a Service proxy round-robins across all
replicas (hits siblings), and even "route to the leader pod" was wrong when the
`node` came from whichever random pod answered discovery — a follower reports
its **own** pod name. The panel now:

- reads `node` (pod name) from each `/orchestrator/leader` response
  (`LeaderElection` exposes it via `HOSTNAME` in `services/shared/orchestrator.py`);
- if the discovery answer was not `is_leader: true`, lists the leader service's
  pods (`?labelSelector=app=<service>`, `_k8s_leader_pod()`) and probes each
  one directly until it finds the lease holder;
- targets that exact pod with `…/api/v1/namespaces/default/pods/<pod>:8000/proxy`.

Only leaders respond positively to a *deterministic pod probe*, so this is
self-consistent even mid-failover; the `_ORCHESTRATOR_CACHE` (5s TTL) absorbs
the transition.

### E2E evidence (Fase 5, run against this stack)

- Scale up/down, delete pod → ReplicaSet self-heals (readiness probes).
- Load simulation `POST /api/orders/simulate/start {"rate":40,"clients":10}`:
  625 orders sent, 605 success; `order-service-hpa` scaled 1 → 3 (70% CPU).
- Stop the leader: scale `order-service` to 0 (HPA removed temporarily) →
  leadership moves to `payment-service` within ~1 lease; `POST /api/orders`
  and `/api/counts` keep working through the new leader pod. Restore the
  deployment (re-apply HPA, scale to 1) → leadership returns to `order-service`
  automatically (priority 100 > 80).

### PostgreSQL replication (Fase 6: primary + hot-standby)

`k8s/base/postgres*.yaml` run a classic streaming-replication setup with no
operator:

- `postgres.yaml` — primary, PGDATA on `postgres-primary-pvc`; `args` override
  CMD (not ENTRYPOINT) so `docker-entrypoint.sh` still runs `initdb` +
  `init.sql` on first boot; flags make the PG16 defaults explicit
  (`wal_level=replica`, 5 senders/slots) and pin `hba_file`.
- `postgres-hba.yaml` — auth in one place: app lines + `host replication
  replicator` for `pg_basebackup`/WAL streaming.
- `postgres-replica.yaml` — an initContainer runs `pg_basebackup -R` (writes
  `standby.signal` + `primary_conninfo`) when `PGDATA` is empty, then the pod
  starts as hot standby on `postgres-replica-pvc`.
- `init.sql` (db-configmap) creates the `replicator` LOGIN REPLICATION role.

Importantly the 5 microservices never change: `DATABASE_URL` still points at
`postgres:5432`, and the `postgres` **Service** is the switch that moves app
traffic in a failover.

**Status/parity:** `scripts/postgres_replication_status.sh` prints
`pg_is_in_recovery()` (expect `f` on primary, `t` on standby) and the order
count on both, plus the WAL sender (`state=streaming`).

**Failover (killed-primary demo, verified):**
```bash
kubectl scale deployment postgres --replicas=0   # primary gone, stays gone
kubectl exec deploy/postgres-replica -- sh -c \
  'export PGPASSWORD=resilencia_secret; psql -U resilencia -d resilencia_db \
   -h localhost -Atc "SELECT count(*) FROM orders"'   # data survived
./scripts/promote_postgres.sh                        # pg_promote + repoint Service
```
`promote_postgres.sh` runs `SELECT pg_promote(true)` on the standby, removes
`standby.signal` (so the pod stays primary across restarts) and patches the
`postgres` Service selector to `app: postgres-replica`. After it, `POST
/api/orders` and `/api/counts` keep working through the promoted node (verified).

**Failback / rebuilding a standby:** the old primary is a burned node after a
failover (its PVC has no `standby.signal`, so restarting it would create a
split brain). To restore redundancy, retarget the base backup at the new
primary instead: scale the old Deployment out, wipe its PVC, and re-run the
replica recipe — i.e. clone a new standby *against* the promoted primary
(`pg_basebackup -h <promoted-primary-ip> ...`), then point `postgres-replica`
at it with `-R`.

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
