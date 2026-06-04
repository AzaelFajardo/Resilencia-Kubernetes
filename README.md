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

| Servicio | Puerto local | Rol |
| --- | --- | --- |
| `order-service` | `8000` | Orquesta la orden completa |
| `user-service` | `8001` | Valida usuarios desde PostgreSQL |
| `inventory-service` | `8002` | Consulta, reserva y libera inventario |
| `payment-service` | `8003` | Simula y persiste pagos |
| `notification-service` | `8004` | Simula y persiste notificaciones |
| `frontend` | `5173` | Panel tecnico React servido con Nginx y reverse proxy interno |
| `data-seeder` | n/a | Genera y carga datos Faker automaticamente al arrancar |
| `postgres` | `5432` | Base de datos principal |
| `prometheus` | `9090` | Scraping de metricas |
| `grafana` | `3000` | Visualizacion de metricas |
| `jaeger` | `16686` | Visualizacion de trazas |

## Arranque rapido

Desde PowerShell en la raiz del repo:

```powershell
docker compose down -v
docker compose up --build -d
docker compose ps
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

- UI tecnica: `http://localhost:5173`
- Swagger:
  - `http://localhost:8000/docs`
  - `http://localhost:8001/docs`
  - `http://localhost:8002/docs`
  - `http://localhost:8003/docs`
  - `http://localhost:8004/docs`
- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3000`
- Jaeger: `http://localhost:16686`

Credenciales de Grafana:

- usuario: `admin`
- contrasena: `admin`

## Frontend tecnico

El stack ahora incluye `frontend`, una UI React + Vite + TypeScript servida por Nginx en `http://localhost:5173`.

- No fue necesario agregar CORS a los microservicios.
- El contenedor `frontend` hace reverse proxy interno a:
  - `/api/user/* -> http://user-service:8000/*`
  - `/api/inventory/* -> http://inventory-service:8000/*`
  - `/api/order/* -> http://order-service:8000/*`
  - `/api/payment/* -> http://payment-service:8000/*`
  - `/api/notification/* -> http://notification-service:8000/*`
- La UI muestra:
  - estado de `user-service`, `inventory-service`, `order-service`, `payment-service`, `notification-service` y `data-seeder`
  - conteos de usuarios, productos, ordenes, pagos y notificaciones
  - tablas de usuarios recientes, ordenes recientes, pagos recientes y notificaciones recientes
  - simulacion de orden contra `POST /orders`
  - accesos rapidos a Prometheus, Grafana y Jaeger

## Endpoints read-only para UI

Se agregaron endpoints de lectura para alimentar la UI sin tocar la logica transaccional:

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
Invoke-RestMethod http://localhost:8001/users/50000/validate
```

Health:

```powershell
Invoke-RestMethod http://localhost:8000/health
Invoke-RestMethod http://localhost:8001/health
Invoke-RestMethod http://localhost:8002/health
Invoke-RestMethod http://localhost:8003/health
Invoke-RestMethod http://localhost:8004/health
```

Orden exitosa:

```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:8000/orders `
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
Invoke-RestMethod -Method Post -Uri http://localhost:8000/orders `
  -ContentType 'application/json' `
  -Body '{"user_id":3,"product_id":1,"quantity":1}'

Invoke-RestMethod -Method Post -Uri http://localhost:8000/orders `
  -ContentType 'application/json' `
  -Body '{"user_id":1,"product_id":2,"quantity":1}'
```

Validacion del frontend y del reverse proxy:

```powershell
curl.exe -s http://localhost:5173/api/user/users/count
curl.exe -s "http://localhost:5173/api/user/users/recent?limit=3"
curl.exe -s "http://localhost:5173/api/order/orders/recent?limit=3"
curl.exe -s "http://localhost:5173/api/payment/payments/recent?limit=3"
curl.exe -s "http://localhost:5173/api/notification/notifications/recent?limit=3"
```

Validacion puntual de los endpoints nuevos por servicio:

```powershell
curl.exe -s http://localhost:8001/users/count
curl.exe -s "http://localhost:8001/users/recent?limit=3"
curl.exe -s http://localhost:8002/inventory/count
curl.exe -s "http://localhost:8002/inventory/stock?limit=3"
curl.exe -s http://localhost:8000/orders/count
curl.exe -s "http://localhost:8000/orders/recent?limit=3"
curl.exe -s http://localhost:8000/orders/4
curl.exe -s http://localhost:8003/payments/count
curl.exe -s "http://localhost:8003/payments/by-order/4"
curl.exe -s http://localhost:8004/notifications/count
curl.exe -s "http://localhost:8004/notifications/by-order/4"
```

## Observabilidad

Metricas:

```powershell
Invoke-WebRequest http://localhost:8000/metrics -UseBasicParsing
Invoke-WebRequest http://localhost:8001/metrics -UseBasicParsing
Invoke-WebRequest http://localhost:8002/metrics -UseBasicParsing
Invoke-WebRequest http://localhost:8003/metrics -UseBasicParsing
Invoke-WebRequest http://localhost:8004/metrics -UseBasicParsing
```

Prometheus:

- `Status -> Targets` debe mostrar `microservices` y `otel-collector` en estado `up`.

Grafana:

- El datasource `Prometheus` queda aprovisionado automaticamente con URL `http://prometheus:9090`.
- Se incluye un dashboard base llamado `Resilencia Overview`.

Jaeger:

- Despues de crear ordenes, `http://localhost:16686/api/services` debe listar:
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

## Documentacion relacionada

- [AUDITORIA_TECNICA.md](/C:/Users/V100/Desktop/Resilencia-Kubernetes/AUDITORIA_TECNICA.md)
- [REPORTE_CORRECCIONES.md](/C:/Users/V100/Desktop/Resilencia-Kubernetes/REPORTE_CORRECCIONES.md)
- [REPORTE_UI.md](/C:/Users/V100/Desktop/Resilencia-Kubernetes/REPORTE_UI.md)
- [usonormal.md](/C:/Users/V100/Desktop/Resilencia-Kubernetes/usonormal.md)
