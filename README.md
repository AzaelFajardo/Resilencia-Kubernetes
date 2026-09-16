# Resilencia-Kubernetes

Plataforma de microservicios para simular un flujo de ordenes en tiempo real con:

- `order-service`
- `user-service`
- `inventory-service`
- `payment-service`
- `notification-service`
- PostgreSQL
- Prometheus
- Grafana
- Jaeger

La fuente de verdad del proyecto es:

- `compose.yml`
- `db/init.sql`
- `services/*/main.py`

## Arquitectura real

Los puertos son configurables via `.env` (ver `.env.example`). Valores por defecto:

| Servicio | Puerto local | Rol |
| --- | --- | --- |
| `order-service` | `8100` | Orquesta la orden completa |
| `user-service` | `8101` | Valida usuarios desde PostgreSQL |
| `inventory-service` | `8102` | Consulta, reserva y libera inventario |
| `payment-service` | `8103` | Simula y persiste pagos |
| `notification-service` | `8104` | Simula y persiste notificaciones |
| `control-panel` | `8105` | Panel web para monitorizar, operar y probar el sistema |
| `data-seeder` | n/a | Genera y carga datos Faker automaticamente al arrancar |
| `postgres` | `5434` | Base de datos principal |
| `prometheus` | `9091` | Scraping de metricas |
| `grafana` | `3001` | Visualizacion de metricas |
| `jaeger` | `16687` | Visualizacion de trazas |

## Arranque rapido

Hay un helper multiplataforma en la raiz del repo:

- **Windows (PowerShell):** `.\run.ps1 up`
- **macOS / Linux:** `./run.sh up`

Comandos disponibles: `up`, `build`, `down`, `reset`, `logs`, `ps`, `status` y `help`.

Equivalente directo con Docker Compose:

```powershell
docker compose down -v
docker compose up --build -d
docker compose ps
```

Configuracion opcional:

```powershell
Copy-Item .env.example .env   # Windows
cp .env.example .env          # macOS / Linux
```

Con la configuracion por defecto, `docker compose up --build -d` tambien ejecuta `data-seeder`:

- `SEED_ENABLED=true`
- `SEED_USERS_COUNT=50000`
- `SEED_PRODUCTS_COUNT=0`

El seeder es idempotente:

- Si ya existen `50000` usuarios o mas, no inserta duplicados.
- Si existen menos, solo genera los faltantes.

Si Docker Desktop muestra un error de BuildKit similar a `parent snapshot ... does not exist`, usa:

```powershell
docker compose build --no-cache
docker compose up -d
```

Para cambiar la cantidad o desactivar el seed desde PowerShell:

```powershell
$env:SEED_USERS_COUNT="10000"
$env:SEED_ENABLED="true"
docker compose up --build -d
```

```powershell
$env:SEED_ENABLED="false"
docker compose up --build -d
```

## URLs utiles

- Swagger:
  - `http://localhost:8100/docs`
  - `http://localhost:8101/docs`
  - `http://localhost:8102/docs`
  - `http://localhost:8103/docs`
  - `http://localhost:8104/docs`
- Prometheus: `http://localhost:9091`
- Grafana: `http://localhost:3001`
- Jaeger: `http://localhost:16687`
- Panel de control: `http://localhost:8105`

Credenciales de Grafana:

- usuario: `admin`
- contrasena: `admin`

## Panel de control (web)

El stack incluye `control-panel`, un panel web en `http://localhost:8105` para
monitorizar, operar y probar todo el sistema sin usar la terminal. Está
organizado en pestañas:

- **Inicio** — salud de los 5 servicios, conteos, circuit breaker, alertas y un
  diagrama vertical del flujo de servicios en tiempo real (con latencia por
  salto). Permite **detener/levantar cada servicio** de verdad y colocar órdenes
  de prueba (con resaltado de la orden generada).
- **Órdenes** — colocar orden, historial por usuario, listado con búsqueda y
  paginación, edición (estado/prioridad) y borrado.
- **Pruebas** — ráfagas masivas de pedidos configurables (por cliente, artículos
  por pedido) y **simulación continua** de tráfico (iniciar/detener, con estado
  en vivo) para ver el efecto en las métricas.
- **Clientes / Inventario** — búsqueda por id/nombre/email, paginación, edición,
  borrado y **generación de datos Faker ilimitada** (con cantidad).
- **Pagos / Notificaciones** — búsqueda, listado paginado y borrado.
- **Resiliencia** — inyección de fallos por servicio (en %, ms y %) y **global**,
  reintentos en runtime, circuit breaker en vivo, presets de fallo y **escenarios
  de prueba** con resultados.
- **Observabilidad** — latencia p50/p95/p99, throughput y errores, recursos
  CPU/RAM/disco, objetivos de Prometheus, alertas y Grafana embebido.
- **Kubernetes** — pods y HPA del cluster (solo lectura, opcional).

Cada pestaña con datos en vivo tiene su propio control de **auto-refresco**
(intervalo en segundos, mínimo 1) y botón de actualización manual.

## Control por terminal

Ademas del panel web, existe `cli.py` en la raiz del repo (Python estandar, sin
dependencias nuevas) como control por terminal:

```powershell
python cli.py status
python cli.py users generate
python cli.py inventory generate
python cli.py order place --user-id 1 --product-id 1 --quantity 1
python cli.py chaos set order-service --failure-rate 0.2
python cli.py chaos reset --all
python cli.py circuit-breaker status
python cli.py --help
```

Los comandos que alteran el estado compartido del stack (`chaos set`, `chaos reset`)
piden confirmacion antes de ejecutarse; usa `--yes` para saltarla en scripts.

## Endpoints read-only

Se agregaron endpoints de lectura para consultar el estado sin tocar la logica transaccional:

- `user-service`
  - `GET /users` (paginado, `?offset/limit/search`)
  - `GET /users/count`
  - `GET /users/recent?limit=10`
- `inventory-service`
  - `GET /inventory?limit=10` (con `?search=`)
  - `GET /inventory/stock?limit=10`
  - `GET /inventory/count`
- `order-service`
  - `GET /orders` (paginado, `?offset/limit/search`)
  - `GET /orders/recent?limit=10`
  - `GET /orders/count`
  - `GET /orders/{order_id}`
- `payment-service`
  - `GET /payments` (paginado, `?offset/limit/search`)
  - `GET /payments/recent?limit=10`
  - `GET /payments/count`
  - `GET /payments/by-order/{order_id}`
- `notification-service`
  - `GET /notifications` (paginado, `?offset/limit/search`)
  - `GET /notifications/recent?limit=10`
  - `GET /notifications/count`
  - `GET /notifications/by-order/{order_id}`

Endpoints de operación/prueba añadidos para el panel:

- `POST /users/faker?count=N` y `POST /inventory/faker?count=N` — datos Faker ilimitados.
- `POST /orders/generate` — ráfaga masiva (`count`, `user_id`, `clients`, `orders_per_client`, `quantity`, `product_id`).
- `POST /orders/simulate/start|stop` y `GET /orders/simulate/status` — simulación continua de tráfico.
- `GET/POST /resilience/retries` — reintentos en runtime de `order-service`.
- `GET /chaos/config` — estado actual del caos por servicio.

## Verificacion minima

Seeder:

```powershell
docker compose logs -f data-seeder
docker compose exec postgres psql -U resilencia -d resilencia_db -c "SELECT COUNT(*) FROM users;"
```

Usuario Faker cargado automaticamente:

```powershell
Invoke-RestMethod http://localhost:8101/users/50000/validate
```

Health:

```powershell
Invoke-RestMethod http://localhost:8100/health
Invoke-RestMethod http://localhost:8101/health
Invoke-RestMethod http://localhost:8102/health
Invoke-RestMethod http://localhost:8103/health
Invoke-RestMethod http://localhost:8104/health
```

Orden exitosa:

```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:8100/orders `
  -ContentType 'application/json' `
  -Body '{"user_id":50000,"product_id":1,"quantity":1}'
```

Persistencia de orden:

```powershell
docker compose exec postgres psql -U resilencia -d resilencia_db -c "SELECT id, user_id, product_id, quantity, status, internal_status FROM orders ORDER BY id DESC LIMIT 10;"
docker compose exec postgres psql -U resilencia -d resilencia_db -c "SELECT id, order_id, status, order_total FROM payments ORDER BY id DESC LIMIT 10;"
docker compose exec postgres psql -U resilencia -d resilencia_db -c "SELECT id, order_id, user_id, status FROM notifications ORDER BY id DESC LIMIT 10;"
```

Pruebas negativas utiles:

```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:8100/orders `
  -ContentType 'application/json' `
  -Body '{"user_id":3,"product_id":1,"quantity":1}'

Invoke-RestMethod -Method Post -Uri http://localhost:8100/orders `
  -ContentType 'application/json' `
  -Body '{"user_id":1,"product_id":2,"quantity":1}'
```

Validacion puntual de los endpoints nuevos por servicio:

```powershell
curl.exe -s http://localhost:8101/users/count
curl.exe -s "http://localhost:8101/users/recent?limit=3"
curl.exe -s http://localhost:8102/inventory/count
curl.exe -s "http://localhost:8102/inventory/stock?limit=3"
curl.exe -s http://localhost:8100/orders/count
curl.exe -s "http://localhost:8100/orders/recent?limit=3"
curl.exe -s http://localhost:8100/orders/4
curl.exe -s http://localhost:8103/payments/count
curl.exe -s "http://localhost:8103/payments/by-order/4"
curl.exe -s http://localhost:8104/notifications/count
curl.exe -s "http://localhost:8104/notifications/by-order/4"
```

## Observabilidad

Metricas:

```powershell
Invoke-WebRequest http://localhost:8100/metrics -UseBasicParsing
Invoke-WebRequest http://localhost:8101/metrics -UseBasicParsing
Invoke-WebRequest http://localhost:8102/metrics -UseBasicParsing
Invoke-WebRequest http://localhost:8103/metrics -UseBasicParsing
Invoke-WebRequest http://localhost:8104/metrics -UseBasicParsing
```

Prometheus:

- `Status -> Targets` debe mostrar `microservices` y `otel-collector` en estado `up`.

Grafana:

- El datasource `Prometheus` queda aprovisionado automaticamente con URL `http://prometheus:9090` (uid fijo: `prometheus`).
- Dashboard `Resilencia Overview`: 12 paneles cubriendo los 4 sectores de la propuesta (Desempeno, Resiliencia, Recursos, Observabilidad). Ver `docs/RESULTS.md` para el analisis consolidado y capturas.

Jaeger:

- Despues de crear ordenes, `http://localhost:16687/api/services` debe listar:
  - `order-service`
  - `user-service`
  - `inventory-service`
  - `payment-service`
  - `notification-service`

## Faker y datos masivos

Seed automatico con Docker Compose:

```powershell
docker compose down -v
docker compose up --build -d
docker compose logs -f data-seeder
docker compose exec postgres psql -U resilencia -d resilencia_db -c "SELECT COUNT(*) FROM users;"
```

El seeder corre dentro de Docker, reutiliza `scripts/generate_data.py` y no requiere Python instalado localmente.

Generar SQL manual sigue disponible como alternativa:

Generar SQL de usuarios con Docker, sin Python local:

```powershell
docker run --rm -v "${PWD}:/app" -w /app python:3.12-slim sh -c "pip install Faker >/dev/null && python scripts/generate_data.py --entity users --count 50000 --format sql" > .\generated_users.sql
```

Generar productos:

```powershell
docker run --rm -v "${PWD}:/app" -w /app python:3.12-slim sh -c "pip install Faker >/dev/null && python scripts/generate_data.py --entity products --count 5000 --format sql" > .\generated_products.sql
```

Generar ambos:

```powershell
docker run --rm -v "${PWD}:/app" -w /app python:3.12-slim sh -c "pip install Faker >/dev/null && python scripts/generate_data.py --entity all --count 1000 --format sql" > .\generated_all.sql
```

Importar SQL generado:

```powershell
Get-Content .\generated_users.sql | docker compose exec -T postgres psql -U resilencia -d resilencia_db
```

Verificar usuarios:

```powershell
docker compose exec postgres psql -U resilencia -d resilencia_db -c "SELECT COUNT(*) FROM users;"
docker compose exec postgres psql -U resilencia -d resilencia_db -c "SELECT id, data->>'email' AS email, data->>'first_name' AS first_name FROM users ORDER BY id DESC LIMIT 10;"
```

## k6 con Docker

Obtener la red:

```powershell
docker network ls
```

En este proyecto Compose crea `resilencia-kubernetes_app-net`.

Ejecutar baseline:

```powershell
docker run --rm -i `
  --network resilencia-kubernetes_app-net `
  -e ORDER_URL=http://order-service:8000/orders `
  -v "${PWD}\scripts\k6:/scripts" `
  grafana/k6 run /scripts/baseline.js
```

Ejecutar stress:

```powershell
docker run --rm -i `
  --network resilencia-kubernetes_app-net `
  -e ORDER_URL=http://order-service:8000/orders `
  -v "${PWD}\scripts\k6:/scripts" `
  grafana/k6 run /scripts/stress-test.js
```

Para caos:

- `with-retries.js` y `with-circuit-breaker.js` ya usan `FAILURE_RATE` en mayusculas.
- Los scripts estan pensados para correr dentro de la red Docker, no contra `localhost` desde el contenedor.

## Kubernetes (Fase 6+)

El stack tambien corre en un cluster de Kubernetes (probado con minikube,
driver Docker). Requiere `kubectl` (incluido con Docker Desktop en Windows) y
`minikube` (`winget install -e --id Kubernetes.minikube`):

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

Los 5 microservicios tienen liveness/readiness probes y **leader election** de
fondo (Fase 4): una sola réplica por servicio tiene el "lease" de orquestación
y sirve los endpoints guarded (`/orders`, `/simulate/*`, `/resilience/*`); si
ese pod cae, otra réplica toma el liderazgo (prioridad: order=100, payment=80,
inventory=60, user=40, notification=20). `order-service-hpa` y
`payment-service-hpa` autoescalan (min 1 / max 5 replicas, 70% CPU). El panel
de control expone acciones (escalar, borrar pod) y enruta el tráfico de
orquestación **al pod líder** (no a un Service genérico), eliminando los 503 de
"not the current orchestrator leader" con réplicas. Para usar
`cli.py` contra el cluster en vez de Compose, ver "Targeting `cli.py` at the
Kubernetes cluster" en `docs/TOOLING.md`. Resultados completos (HPA, MTTR,
hallazgos) en `docs/tests/kubernetes-results.md` y `docs/tests/fault-*-results.md`.

### Verificación E2E (Fase 5)

Escenarios verificados contra el panel (`http://localhost:8105`, modo
`kubernetes`):

1. **Escalar ±** — `POST /api/kubernetes/scale {"deployment":"order-service","replicas":N}`; el panel refleja el cambio (el HPA sobreescribe en ~5 min si baja del mínimo).
2. **Borrar pod / self-healing** — `DELETE /api/kubernetes/pod {"deployment":"order-service",...}`; el ReplicaSet lo recrea desde cero (probes readiness/liveness).
3. **Carga + HPA** — `POST /api/orders/simulate/start {"rate":40,"clients":10}` → `order-service-hpa` escala 1→3 (70% CPU). Resultado observado: 625 órdenes enviadas, 605 éxito. Parar con `/api/orders/simulate/stop`.
4. **Takeover del líder** — escalar `order-service` a 0 (con su HPA temporalmente eliminado; el autoscaler no permite min 0): liderazgo pasa a `payment-service` en ~1 lease y `/api/orders` + `/api/counts` siguen funcionando vía el nuevo líder. Al restaurar (`kubectl apply -f k8s/resilience/hpa.yaml` + scale a 1), el liderazgo regresa solo a `order-service`.

### Replicación de datos PostgreSQL (Fase 6)

La base de datos corre como **primario + réplica hot standby** (streaming
replication nativa, imagen `postgres:16-alpine`, sin operador):

- `k8s/base/postgres.yaml` — primario con PVC (`postgres-primary-pvc`), WAL
  disponible (`wal_level=replica`, 5 senders), `hba_file` propio.
- `k8s/base/postgres-replica.yaml` — réplica que arranca con `pg_basebackup`
  del primario (`-R` → `standby.signal` + `primary_conninfo`) sobre su PVC.
- `k8s/base/postgres-hba.yaml` — reglas de auth (app + `host replication
  replicator`). El rol `replicator` se crea en `init.sql`.
- Los 5 microservicios no cambian: siguen apuntando a `DATABASE_URL` =
  `postgres:5432` (el Service hace de conmutador).

**Failover (script):** `scripts/promote_postgres.sh` — `pg_promote()` en la
réplica + re-apunta el Service a `app: postgres-replica`. Verificado en vivo:
datos paridad primario/réplica (órdenes se propagan), matar el primario no
pierde datos y la app sigue escribiendo en el nodo promovido. Health/paridad:
`scripts/postgres_replication_status.sh`.

Caveats (aceptados en lab de estudio): minikube es single-node → la
replicación es **lógica** (los datos existen dos veces en el mismo nodo físico,
no es una copia geográfica); no hay read/write splitting (todo sigue al
primario); tras un failover el primario original queda desconectado (su
Deployment queda a 0) — para recuperar redundancia, re-clonar un standby
siguiendo al nuevo primario (recipe en `docs/TOOLING.md`).

## Configuracion de la base de datos

Todos los microservicios y el seeder leen la variable `DATABASE_URL`. Por defecto apuntan al contenedor `postgres` de Compose:

```
postgresql://resilencia:resilencia_secret@postgres:5432/resilencia_db
```

Para conectar una base de datos externa compatible con PostgreSQL (Neon, RDS/Aurora, Supabase, etc.), define `DATABASE_URL` en `.env`:

```
DATABASE_URL=postgresql://usuario:clave@mi-host:5432/mi_db
```

El esquema (`db/init.sql`) usa tipos especificos de PostgreSQL (JSONB, enums y pgcrypto), por lo que MySQL o SQLite requieren adaptar el schema. Consulta `.env.example` para ver todas las variables disponibles.

## Documentacion relacionada

- `docs/00. setup.md`
- `docs/01.Arquitectura.md`
- `docs/services/*.md`
- `docs/tests/` — un resultado por fase/fault, mas capturas del dashboard en `docs/tests/screenshots/`
- `docs/TOOLING.md` — how `cli.py`, chaos, circuit breaker, k6, JMeter and Kubernetes targeting work
- `docs/ACTION-PLAN.md` — phased plan and progress (Fases 0-8 completadas)
- `docs/RESULTS.md` — documento maestro: los 4 hallazgos esperados de la propuesta, consolidados
