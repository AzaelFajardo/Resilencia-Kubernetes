# Usage Guide

*[Leer en español: GUIA_DE_USO.md](GUIA_DE_USO.md)*

English, beginner-friendly companion to this repository. The canonical, most
detailed documentation is still in Spanish in `README.md` and `docs/` — this
guide is a map to get you running quickly and to explain what each piece is
for, without duplicating every detail already written down there.

## 1. Project Overview

**Resilencia-Kubernetes** is a microservices lab project that simulates a
real-time order flow (place an order → validate the user → check/reserve
inventory → charge a payment → send a notification) so that resilience
mechanisms — retries, a circuit breaker, chaos/fault injection, Kubernetes
self-healing, autoscaling, leader election, and PostgreSQL replication — can
be studied and measured under controlled conditions.

Tech stack:

- **Backend:** Python 3.12, FastAPI, SQLAlchemy (async), PostgreSQL 16
- **Observability:** Prometheus, Grafana, Jaeger, OpenTelemetry (traces only)
- **Runtime:** Docker Compose (default) or Kubernetes (minikube), with an
  experimental Helm chart under `charts/resilencia/`
- **Tooling:** a Python CLI (`cli.py`), a web control panel
  (`services/control-panel`), k6 and JMeter load-testing scripts

The project has no separate frontend framework: `control-panel` serves a
small static HTML/JS/CSS app directly.

## 2. Project Structure

```
Resilencia-Kubernetes/
├── services/                  # One folder per microservice (source of truth)
│   ├── order-service/         # Orchestrates the order flow (the classic leader)
│   ├── user-service/          # Validates users against the `users` table
│   ├── inventory-service/     # Checks/reserves/releases product stock
│   ├── payment-service/       # Simulates and persists payments
│   ├── notification-service/  # Simulates and persists notifications
│   ├── control-panel/         # Web UI: monitor, operate and test the stack
│   ├── data-seeder/           # One-shot job: loads Faker data on startup
│   └── shared/                # orchestrator.py: shared order logic + leader election,
│                               # imported by all 5 microservices (baked into every image)
├── db/init.sql                # Database schema (source of truth)
├── compose.yml                # Docker Compose stack definition
├── run.sh / run.ps1           # Cross-platform start/stop helpers (delegate to scripts/)
├── scripts/                   # up.sh/down.sh, load-test scripts (k6, JMeter),
│                               # Faker data generation, Postgres replication helpers
├── k8s/                       # Plain Kubernetes manifests (base/ + resilience/hpa.yaml)
├── charts/resilencia/         # Experimental Helm packaging of the same k8s/ manifests
├── observability/             # Prometheus, Grafana and OTel Collector configuration
├── cli.py                     # Terminal control surface (no extra dependencies)
└── docs/                      # Detailed Spanish documentation (architecture, phases,
                                # per-service notes, test results, tooling internals)
```

**Why this layout is kept as-is:** paths here are load-bearing. `compose.yml`
builds each service with context `./services` so `COPY shared/ ...` in every
Dockerfile can bake in the shared orchestrator module; `scripts/up.sh` and the
Kubernetes manifests hardcode these same paths; and the existing `docs/` tree
is cross-linked from the README. Moving files would require touching Docker
build contexts, Kubernetes ConfigMaps and Helm templates all at once for no
functional benefit — so this guide documents the structure rather than
changing it.

## 3. Installation / Setup

**Required (Docker Compose only, this covers most of the project):**

- Docker Desktop (includes Docker Compose)
- PowerShell (Windows) or bash (macOS/Linux)

No local Python or Node installation is required — the seeder, the services
and the load-test tools all run inside containers.

**Optional (only if you want to run the Kubernetes deployment):**

- `kubectl` (already bundled with Docker Desktop on Windows)
- `minikube` (`winget install -e --id Kubernetes.minikube`)
- `helm`, only if you want to try the experimental chart in `charts/resilencia/`

**Configuration:**

```powershell
Copy-Item .env.example .env   # Windows
cp .env.example .env          # macOS / Linux
```

`.env` is optional — every variable has a sane default baked into
`compose.yml`. Edit it only if a default port is already taken on your
machine, or you want to change seed size / chaos defaults. See
[Configuration Options](#6-configuration-options) below for the full list.

## 4. How to Run

### Docker Compose (default, recommended first run)

```powershell
.\run.ps1 up        # Windows
./run.sh up         # macOS / Linux
```

Equivalent direct command:

```powershell
docker compose up --build -d
docker compose ps
```

This also starts `data-seeder`, which loads 50,000 Faker users automatically
(idempotent — safe to re-run, it only inserts what's missing).

**Stopping:**

```powershell
.\run.ps1 stop       # or: ./run.sh stop
```

This stops containers without deleting data. To wipe volumes and start clean,
use `docker compose down -v` or `run.sh up --reset`.

**If Docker Desktop shows a BuildKit "parent snapshot ... does not exist"
error:**

```powershell
docker compose build --no-cache
docker compose up -d
```

### Kubernetes (optional, minikube)

```bash
./run.sh k8s     # automates everything below
```

Manual equivalent:

```powershell
minikube start --driver=docker
minikube addons enable metrics-server
foreach ($svc in "user-service","inventory-service","payment-service","notification-service","order-service") {
  docker build -t "${svc}:latest" ".\services\$svc"
  minikube image load "${svc}:latest"
}
kubectl apply -f k8s/base/
kubectl apply -f k8s/resilience/hpa.yaml
```

Full options (`--compose-only`, `--k8s-only`, `--no-build`, `--reset`,
`--keep-cluster`, `--purge`) are documented in
[`docs/TOOLING.md`](docs/TOOLING.md#arranque-y-parada-asistidos).

### Placing your first order

```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:8100/orders `
  -ContentType 'application/json' `
  -Body '{"user_id":50000,"product_id":1,"quantity":1}'
```

Or with the CLI:

```powershell
python cli.py order place --user-id 50000 --product-id 1 --quantity 1
```

Or from the control panel at `http://localhost:8105`.

### URLs and ports (Compose defaults)

| Service | URL | Purpose |
| --- | --- | --- |
| order-service | http://localhost:8100/docs | Orchestrates the order flow |
| user-service | http://localhost:8101/docs | Validates users |
| inventory-service | http://localhost:8102/docs | Stock availability/reservation |
| payment-service | http://localhost:8103/docs | Payment simulation |
| notification-service | http://localhost:8104/docs | Notification simulation |
| control-panel | http://localhost:8105 | Web UI for everything below |
| Prometheus | http://localhost:9091 | Metrics |
| Grafana | http://localhost:3001 (admin/admin) | Dashboards |
| Jaeger | http://localhost:16687 | Traces |

## 5. Key Components & Their Functions

- **The 5 FastAPI microservices** (`services/{order,user,inventory,payment,notification}-service`)
  each own one step of the order flow, expose `/health` and `/metrics`
  (Prometheus format), and support runtime chaos injection via
  `POST /chaos/config` (`FAILURE_RATE`, `LATENCY_MS`, `TIMEOUT_RATE`).
- **`services/shared/orchestrator.py`** — the order-orchestration endpoints
  (`/orders`, `/orders/generate`, `/orders/simulate/*`, `/resilience/*`) and a
  lease-based **leader election** system. It is imported by all 5 services so
  that, in Kubernetes, any of them can take over orchestration if
  `order-service` is scaled to zero (priority order: order → payment →
  inventory → user → notification). Under plain Docker Compose, election is
  disabled and `order-service` is always the orchestrator.
- **`order-service`'s circuit breaker** — wraps calls to `payment-service`
  with a `CLOSED → OPEN → HALF_OPEN` state machine (see
  `docs/TOOLING.md#circuit-breaker-mechanism-order-service--payment-service`).
- **`services/control-panel`** — a web UI (`http://localhost:8105`) to
  monitor health/metrics, place and manage orders, inject chaos, run load
  bursts and continuous traffic simulation, and (optionally) inspect/scale
  Kubernetes pods.
- **`cli.py`** — a dependency-free terminal client over the same HTTP APIs
  the panel uses (`python cli.py --help`). Destructive/shared-state commands
  (`chaos set`, `chaos reset`) ask for confirmation unless `--yes` is passed.
- **`services/data-seeder`** — a one-shot container that loads Faker-generated
  users/products via `scripts/generate_data.py` and `scripts/seed_database.py`.
- **Observability stack** (`observability/`) — Prometheus scrapes every
  service's `/metrics`; traces go through the OTel Collector into Jaeger;
  Grafana ships a pre-built "Resilencia Overview" dashboard (12 panels across
  performance, resilience, resources and observability).

For deep dives (how leader election chooses the winner, exact retry/circuit
breaker semantics, k6/JMeter internals), see `docs/TOOLING.md` and
`docs/01.Arquitectura.md`.

## 6. Configuration Options

All variables are optional (defaults live in `compose.yml`/services); copy
`.env.example` to `.env` to override any of them.

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | Compose `postgres` container | PostgreSQL connection string used by every service and the seeder |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `resilencia` / `resilencia_secret` / `resilencia_db` | Credentials for the Compose Postgres container |
| `*_SERVICE_PORT`, `POSTGRES_PORT`, `PROMETHEUS_PORT`, `GRAFANA_PORT`, `JAEGER_PORT` | see `.env.example` | Host-published ports, change if one collides locally |
| `SEED_ENABLED` | `true` | Run the Faker seeder on startup |
| `SEED_USERS_COUNT` / `SEED_PRODUCTS_COUNT` | `50000` / `0` | Target row counts (seeder is idempotent — only inserts what's missing) |
| `SEED_CONNECT_RETRIES` / `SEED_CONNECT_DELAY_SECONDS` / `SEED_BATCH_SIZE` | `30` / `2` / `1000` | Seeder connection retry and batching tuning |
| `FAILURE_RATE` / `LATENCY_MS` / `TIMEOUT_RATE` | `0.0` / `0` / `0.0` | Startup chaos-injection defaults per service (also settable live via `POST /chaos/config`) |
| `RETRY_ENABLED` / `RETRY_COUNT` / `RETRY_DELAY_MS` | `false` / `3` / `100` | `order-service`'s retries toward downstream services |
| `HTTP_TIMEOUT` | `5.0` | HTTP timeout (seconds) between services |
| `FRAUD_THRESHOLD` | `70` | Score above which an order is held for manual review |
| `OTEL_SDK_DISABLED` | `false` | Fully disable OpenTelemetry (useful only to measure its overhead) |
| `OTEL_TRACES_SAMPLER` / `OTEL_TRACES_SAMPLER_ARG` | `parentbased_always_on` / `1.0` | Trace sampling strategy |
| `K8S_API_SERVER` (+ `K8S_CA_FILE`, `K8S_CLIENT_CERT_FILE`, `K8S_CLIENT_KEY_FILE`) | empty (disabled) | Lets `control-panel` talk to a real Kubernetes cluster; see `.env.example` for the full setup recipe |
| `SERVICE_NAME`, `ORCHESTRATOR_PRIORITY`, `LEADER_ELECTION` | set per pod in `k8s/base/deployment.yaml` | Only relevant inside Kubernetes; not needed for Compose |

## 7. Troubleshooting

- **`docker compose up` fails with a BuildKit "parent snapshot ... does not
  exist" error** → `docker compose build --no-cache` then `docker compose up -d`.
- **Seeder seems stuck or you're not sure it finished** →
  `docker compose logs -f data-seeder`, then confirm with
  `docker compose exec postgres psql -U resilencia -d resilencia_db -c "SELECT COUNT(*) FROM users;"`.
- **A request returns `503 "not the current orchestrator leader"`** — only
  happens in Kubernetes with multiple replicas; it means you hit a pod that
  isn't the current leader. The control panel routes to the leader pod
  automatically; if calling a service directly, check `/orchestrator/leader`
  first. See `docs/TOOLING.md#leader-pod-routing-why-the-panel-no-longer-503s`.
- **A port is already in use on your machine** — override the matching
  `*_PORT` variable in `.env` and re-run `docker compose up --build -d`.
- **Jaeger shows no services** — traces only appear after you place at least
  one order; then check `http://localhost:16687/api/services`.
- **Grafana dashboard shows "No data" on every panel** — the Prometheus
  datasource must have `uid: prometheus` pinned (already set in this repo's
  provisioning file); if the `grafana-data` volume was ever wiped and the pin
  lost, see `docs/TOOLING.md#grafana-dashboard-phase-8`.
- **minikube comes back `Stopped` or start fails with "Address already in
  use"** — see the recovery sequence in
  `docs/TOOLING.md#minikube-came-back-stopped--address-already-in-use-on-start`.
- **`minikube image load` doesn't pick up code changes** — rebuild and
  reload the image, then `kubectl rollout restart`; the exact commands are in
  `docs/TOOLING.md#rebuild--redeploy-a-service-image-after-editing-shared-or-a-service`.

## 8. Known Issues / Suggested Improvements (found during this review)

These were found while analyzing the project for this guide. Nothing here was
changed — they're flagged for you to decide whether/when to fix:

- **Helm chart drift:** `charts/resilencia/files/init.sql` is missing the
  `service_leader` table that `db/init.sql` defines and
  `services/shared/orchestrator.py`'s leader election relies on — a fresh
  `helm install` would fail leader election in Kubernetes. Separately,
  `charts/resilencia/files/grafana-dashboard.json` has drifted from
  `observability/grafana/dashboards/resilencia-overview.json` (52 lines
  different). `docs/tests/kubernetes-hardening-results.md` already documents
  that these two copies must be kept in sync manually and has fixed drift
  before — this is a recurrence of that same known risk.
- **Duplicated `tracing.py`:** all 5 services ship a nearly identical
  `tracing.py` (user-service and inventory-service are byte-for-byte
  identical; the others differ by a handful of lines). Since every
  Dockerfile already copies `services/shared/` into the image, this file
  could be consolidated there in a future refactor — left untouched here to
  avoid changing import paths and Dockerfiles as part of a documentation pass.
- **`Campos por servicio.md`** lives at the repository root instead of under
  `docs/`. It's referenced from SQL comments and a Kubernetes ConfigMap, so
  moving it would require updating those references too — left in place.

## 9. Further Reading

- [`README.md`](README.md) — the primary (Spanish) reference, most detailed and current
- [`docs/00. setup.md`](docs/00.%20setup.md) — setup requirements
- [`docs/01.Arquitectura.md`](docs/01.Arquitectura.md) — architecture, internal ports, database
- [`docs/TOOLING.md`](docs/TOOLING.md) — how `cli.py`, chaos, circuit breaker, k6/JMeter, and Kubernetes operations work internally
- [`docs/services/`](docs/services/) — one document per microservice
- [`docs/ACTION-PLAN.md`](docs/ACTION-PLAN.md) — phased history of what was built and validated
- [`docs/RESULTS.md`](docs/RESULTS.md) — consolidated findings across all test phases
- [`docs/tests/`](docs/tests/) — per-phase/per-fault raw results and dashboard screenshots
