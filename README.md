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

Credenciales de Grafana:

- usuario: `admin`
- contrasena: `admin`

## Control por terminal

El proyecto es completamente headless: no hay UI web. El punto de control para el
equipo es `cli.py` en la raiz del repo (Python estandar, sin dependencias nuevas).

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
  - `GET /users/count`
  - `GET /users/recent?limit=10`
- `inventory-service`
  - `GET /inventory?limit=10`
  - `GET /inventory/stock?limit=10`
  - `GET /inventory/count`
- `order-service`
  - `GET /orders/recent?limit=10`
  - `GET /orders/count`
  - `GET /orders/{order_id}`
- `payment-service`
  - `GET /payments/recent?limit=10`
  - `GET /payments/count`
  - `GET /payments/by-order/{order_id}`
- `notification-service`
  - `GET /notifications/recent?limit=10`
  - `GET /notifications/count`
  - `GET /notifications/by-order/{order_id}`

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

- El datasource `Prometheus` queda aprovisionado automaticamente con URL `http://prometheus:9090`.
- Se incluye un dashboard base llamado `Resilencia Overview`.

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
- `docs/tests/ejemplo.md`
