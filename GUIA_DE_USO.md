# Guía de Uso

*[Read in English: USAGE_GUIDE.md](USAGE_GUIDE.md)*

Guía en español, pensada para principiantes, como acompañamiento de este
repositorio. La documentación canónica y más detallada sigue estando en
español en `README.md` y `docs/`; esta guía es un mapa para arrancar rápido
y entender para qué sirve cada pieza, sin duplicar cada detalle que ya está
escrito allí.

## 1. Descripción general del proyecto

**Resilencia-Kubernetes** es un proyecto de laboratorio de microservicios
que simula un flujo de órdenes en tiempo real (colocar una orden → validar
al usuario → verificar/reservar inventario → cobrar un pago → enviar una
notificación) para poder estudiar y medir, bajo condiciones controladas,
mecanismos de resiliencia como reintentos, circuit breaker, inyección de
fallos (chaos engineering), auto-recuperación de Kubernetes, autoescalado,
elección de líder y replicación de PostgreSQL.

Stack tecnológico:

- **Backend:** Python 3.12, FastAPI, SQLAlchemy (async), PostgreSQL 16
- **Observabilidad:** Prometheus, Grafana, Jaeger, OpenTelemetry (solo trazas)
- **Runtime:** Docker Compose (por defecto) o Kubernetes (minikube), con un
  chart de Helm experimental en `charts/resilencia/`
- **Herramientas:** un CLI en Python (`cli.py`), un panel de control web
  (`services/control-panel`), scripts de carga con k6 y JMeter

El proyecto no tiene un framework de frontend separado: `control-panel` sirve
directamente una pequeña app estática de HTML/JS/CSS.

## 2. Estructura del proyecto

```
Resilencia-Kubernetes/
├── services/                  # Una carpeta por microservicio (fuente de verdad)
│   ├── order-service/         # Orquesta el flujo de la orden (el líder clásico)
│   ├── user-service/          # Valida usuarios contra la tabla `users`
│   ├── inventory-service/     # Consulta, reserva y libera stock de productos
│   ├── payment-service/       # Simula y persiste pagos
│   ├── notification-service/  # Simula y persiste notificaciones
│   ├── control-panel/         # UI web: monitorear, operar y probar el stack
│   ├── data-seeder/           # Job de un solo uso: carga datos Faker al iniciar
│   └── shared/                # orchestrator.py: lógica de orden compartida +
│                               # elección de líder, importado por los 5 servicios
│                               # (se incluye dentro de cada imagen)
├── db/init.sql                # Esquema de la base de datos (fuente de verdad)
├── compose.yml                # Definición del stack de Docker Compose
├── run.sh / run.ps1           # Helpers multiplataforma de arranque/parada
│                               # (delegan en scripts/)
├── scripts/                   # up.sh/down.sh, scripts de carga (k6, JMeter),
│                               # generación de datos Faker, helpers de replicación
├── k8s/                       # Manifiestos de Kubernetes en YAML plano
│                               # (base/ + resilience/hpa.yaml)
├── charts/resilencia/         # Empaquetado experimental en Helm de esos mismos
│                               # manifiestos de k8s/
├── observability/             # Configuración de Prometheus, Grafana y OTel Collector
├── cli.py                     # Superficie de control por terminal (sin dependencias extra)
└── docs/                      # Documentación detallada en español (arquitectura,
                                # fases, notas por servicio, resultados de pruebas,
                                # detalles internos de las herramientas)
```

**Por qué esta estructura se mantiene tal cual:** las rutas aquí son
estructurales, no cosméticas. `compose.yml` construye cada servicio con
contexto `./services` para que el `COPY shared/ ...` de cada Dockerfile pueda
incluir el módulo orquestador compartido; `scripts/up.sh` y los manifiestos
de Kubernetes tienen esas mismas rutas escritas de forma fija; y el árbol de
`docs/` ya está enlazado desde el README. Mover archivos obligaría a tocar a
la vez los contextos de build de Docker, los ConfigMaps de Kubernetes y las
plantillas de Helm, sin ningún beneficio funcional real — por eso esta guía
documenta la estructura en vez de cambiarla.

## 3. Instalación / Configuración

**Requisitos obligatorios (solo para Docker Compose, cubre la mayor parte
del proyecto):**

- Docker Desktop (incluye Docker Compose)
- PowerShell (Windows) o bash (macOS/Linux)

No hace falta instalar Python ni Node localmente — el seeder, los servicios
y las herramientas de carga corren todos dentro de contenedores.

**Opcionales (solo si querés correr el despliegue en Kubernetes):**

- `kubectl` (ya viene incluido con Docker Desktop en Windows)
- `minikube` (`winget install -e --id Kubernetes.minikube`)
- `helm`, solo si querés probar el chart experimental de `charts/resilencia/`

**Configuración:**

```powershell
Copy-Item .env.example .env   # Windows
cp .env.example .env          # macOS / Linux
```

El archivo `.env` es opcional — cada variable tiene un valor por defecto
razonable definido en `compose.yml`. Editalo solo si algún puerto por
defecto ya está en uso en tu máquina, o si querés cambiar el tamaño del seed
o los valores de chaos por defecto. Ver
[Opciones de configuración](#6-opciones-de-configuración) más abajo para el
listado completo.

## 4. Cómo ejecutarlo

### Docker Compose (por defecto, recomendado para la primera corrida)

```powershell
.\run.ps1 up        # Windows
./run.sh up         # macOS / Linux
```

Comando directo equivalente:

```powershell
docker compose up --build -d
docker compose ps
```

Esto también arranca `data-seeder`, que carga 50.000 usuarios Faker de forma
automática (es idempotente — se puede volver a ejecutar sin problema, solo
inserta lo que falte).

**Para detenerlo:**

```powershell
.\run.ps1 stop       # o: ./run.sh stop
```

Esto detiene los contenedores sin borrar datos. Para vaciar los volúmenes y
arrancar desde cero, usá `docker compose down -v` o `run.sh up --reset`.

**Si Docker Desktop muestra un error de BuildKit tipo "parent snapshot ...
does not exist":**

```powershell
docker compose build --no-cache
docker compose up -d
```

### Kubernetes (opcional, minikube)

```bash
./run.sh k8s     # automatiza todos los pasos de abajo
```

Equivalente manual:

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

Todas las opciones (`--compose-only`, `--k8s-only`, `--no-build`, `--reset`,
`--keep-cluster`, `--purge`) están documentadas en
[`docs/TOOLING.md`](docs/TOOLING.md#arranque-y-parada-asistidos).

### Colocar tu primera orden

```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:8100/orders `
  -ContentType 'application/json' `
  -Body '{"user_id":50000,"product_id":1,"quantity":1}'
```

O con el CLI:

```powershell
python cli.py order place --user-id 50000 --product-id 1 --quantity 1
```

O desde el panel de control en `http://localhost:8105`.

### URLs y puertos (valores por defecto de Compose)

| Servicio | URL | Función |
| --- | --- | --- |
| order-service | http://localhost:8100/docs | Orquesta el flujo de la orden |
| user-service | http://localhost:8101/docs | Valida usuarios |
| inventory-service | http://localhost:8102/docs | Disponibilidad/reserva de stock |
| payment-service | http://localhost:8103/docs | Simulación de pagos |
| notification-service | http://localhost:8104/docs | Simulación de notificaciones |
| control-panel | http://localhost:8105 | UI web para todo lo anterior |
| Prometheus | http://localhost:9091 | Métricas |
| Grafana | http://localhost:3001 (admin/admin) | Dashboards |
| Jaeger | http://localhost:16687 | Trazas |

## 5. Componentes clave y sus funciones

- **Los 5 microservicios FastAPI** (`services/{order,user,inventory,payment,notification}-service`)
  cada uno maneja un paso del flujo de la orden, exponen `/health` y
  `/metrics` (formato Prometheus), y soportan inyección de fallos en tiempo
  de ejecución vía `POST /chaos/config` (`FAILURE_RATE`, `LATENCY_MS`,
  `TIMEOUT_RATE`).
- **`services/shared/orchestrator.py`** — los endpoints de orquestación de
  la orden (`/orders`, `/orders/generate`, `/orders/simulate/*`,
  `/resilience/*`) y un sistema de **elección de líder** basado en lease.
  Es importado por los 5 servicios para que, en Kubernetes, cualquiera de
  ellos pueda tomar el rol de orquestador si `order-service` se escala a
  cero (orden de prioridad: order → payment → inventory → user →
  notification). En Docker Compose plano, la elección está deshabilitada y
  `order-service` siempre es el orquestador.
- **El circuit breaker de `order-service`** — envuelve las llamadas a
  `payment-service` con una máquina de estados
  `CLOSED → OPEN → HALF_OPEN` (ver
  `docs/TOOLING.md#circuit-breaker-mechanism-order-service--payment-service`).
- **`services/control-panel`** — una UI web (`http://localhost:8105`) para
  monitorear salud/métricas, colocar y gestionar órdenes, inyectar chaos,
  correr ráfagas de carga y simulación continua de tráfico, y (opcionalmente)
  inspeccionar/escalar pods de Kubernetes.
- **`cli.py`** — un cliente de terminal sin dependencias sobre las mismas
  APIs HTTP que usa el panel (`python cli.py --help`). Los comandos
  destructivos o que afectan el estado compartido (`chaos set`,
  `chaos reset`) piden confirmación salvo que se pase `--yes`.
- **`services/data-seeder`** — un contenedor de un solo uso que carga
  usuarios/productos generados con Faker vía `scripts/generate_data.py` y
  `scripts/seed_database.py`.
- **Stack de observabilidad** (`observability/`) — Prometheus scrapea el
  `/metrics` de cada servicio; las trazas pasan por el OTel Collector hacia
  Jaeger; Grafana trae un dashboard "Resilencia Overview" ya armado (12
  paneles que cubren desempeño, resiliencia, recursos y observabilidad).

Para profundizar (cómo elige el ganador la elección de líder, la semántica
exacta de reintentos/circuit breaker, detalles internos de k6/JMeter), ver
`docs/TOOLING.md` y `docs/01.Arquitectura.md`.

## 6. Opciones de configuración

Todas las variables son opcionales (los valores por defecto viven en
`compose.yml`/los servicios); copiá `.env.example` a `.env` para sobrescribir
cualquiera de ellas.

| Variable | Por defecto | Función |
| --- | --- | --- |
| `DATABASE_URL` | Contenedor `postgres` de Compose | Cadena de conexión a PostgreSQL usada por todos los servicios y el seeder |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `resilencia` / `resilencia_secret` / `resilencia_db` | Credenciales del contenedor Postgres de Compose |
| `*_SERVICE_PORT`, `POSTGRES_PORT`, `PROMETHEUS_PORT`, `GRAFANA_PORT`, `JAEGER_PORT` | ver `.env.example` | Puertos publicados en el host; cambiar si alguno choca localmente |
| `SEED_ENABLED` | `true` | Ejecuta el seeder de Faker al iniciar |
| `SEED_USERS_COUNT` / `SEED_PRODUCTS_COUNT` | `50000` / `0` | Cantidad objetivo de filas (el seeder es idempotente — solo inserta lo que falta) |
| `SEED_CONNECT_RETRIES` / `SEED_CONNECT_DELAY_SECONDS` / `SEED_BATCH_SIZE` | `30` / `2` / `1000` | Ajuste de reintentos de conexión y tamaño de lote del seeder |
| `FAILURE_RATE` / `LATENCY_MS` / `TIMEOUT_RATE` | `0.0` / `0` / `0.0` | Valores por defecto de inyección de fallos al arrancar cada servicio (también configurables en vivo vía `POST /chaos/config`) |
| `RETRY_ENABLED` / `RETRY_COUNT` / `RETRY_DELAY_MS` | `false` / `3` / `100` | Reintentos de `order-service` hacia los servicios downstream |
| `HTTP_TIMEOUT` | `5.0` | Timeout HTTP (segundos) entre servicios |
| `FRAUD_THRESHOLD` | `70` | Puntaje por encima del cual una orden queda retenida para revisión manual |
| `OTEL_SDK_DISABLED` | `false` | Desactiva por completo OpenTelemetry (útil solo para medir su overhead) |
| `OTEL_TRACES_SAMPLER` / `OTEL_TRACES_SAMPLER_ARG` | `parentbased_always_on` / `1.0` | Estrategia de muestreo de trazas |
| `K8S_API_SERVER` (+ `K8S_CA_FILE`, `K8S_CLIENT_CERT_FILE`, `K8S_CLIENT_KEY_FILE`) | vacío (desactivado) | Permite que `control-panel` se conecte a un cluster de Kubernetes real; ver `.env.example` para la receta completa |
| `SERVICE_NAME`, `ORCHESTRATOR_PRIORITY`, `LEADER_ELECTION` | definidas por pod en `k8s/base/deployment.yaml` | Solo relevantes dentro de Kubernetes; no hacen falta en Compose |

## 7. Solución de problemas

- **`docker compose up` falla con un error de BuildKit tipo "parent
  snapshot ... does not exist"** → `docker compose build --no-cache` y luego
  `docker compose up -d`.
- **El seeder parece colgado o no sabés si terminó** →
  `docker compose logs -f data-seeder`, y confirmá con
  `docker compose exec postgres psql -U resilencia -d resilencia_db -c "SELECT COUNT(*) FROM users;"`.
- **Una petición devuelve `503 "not the current orchestrator leader"`** —
  solo pasa en Kubernetes con múltiples réplicas; significa que le pegaste a
  un pod que no es el líder actual. El panel de control enruta al pod líder
  automáticamente; si llamás a un servicio directamente, revisá primero
  `/orchestrator/leader`. Ver
  `docs/TOOLING.md#leader-pod-routing-why-the-panel-no-longer-503s`.
- **Un puerto ya está en uso en tu máquina** — sobrescribí la variable
  `*_PORT` correspondiente en `.env` y volvé a correr
  `docker compose up --build -d`.
- **Jaeger no muestra servicios** — las trazas solo aparecen después de
  colocar al menos una orden; luego revisá
  `http://localhost:16687/api/services`.
- **El dashboard de Grafana muestra "No data" en todos los paneles** — el
  datasource de Prometheus necesita tener fijado `uid: prometheus` (ya está
  configurado así en el archivo de aprovisionamiento de este repo); si el
  volumen `grafana-data` se borró alguna vez y ese fijado se perdió, ver
  `docs/TOOLING.md#grafana-dashboard-phase-8`.
- **minikube vuelve en estado `Stopped` o falla al iniciar con "Address
  already in use"** — ver la secuencia de recuperación en
  `docs/TOOLING.md#minikube-came-back-stopped--address-already-in-use-on-start`.
- **`minikube image load` no toma los cambios de código** — reconstruí y
  recargá la imagen, y después hacé `kubectl rollout restart`; los comandos
  exactos están en
  `docs/TOOLING.md#rebuild--redeploy-a-service-image-after-editing-shared-or-a-service`.

## 8. Problemas conocidos / Mejoras sugeridas (encontrados durante esta revisión)

Esto se encontró al analizar el proyecto para armar esta guía. No se cambió
nada — queda señalado para que decidas si y cuándo corregirlo:

- **Desincronización del chart de Helm:** a `charts/resilencia/files/init.sql`
  le falta la tabla `service_leader` que sí define `db/init.sql` y de la que
  depende la elección de líder en `services/shared/orchestrator.py` — un
  `helm install` nuevo fallaría en la elección de líder dentro de
  Kubernetes. Por separado, `charts/resilencia/files/grafana-dashboard.json`
  se desincronizó de
  `observability/grafana/dashboards/resilencia-overview.json` (52 líneas de
  diferencia). `docs/tests/kubernetes-hardening-results.md` ya documenta que
  estas dos copias deben mantenerse sincronizadas a mano y que este mismo
  tipo de desincronización ya se corrigió antes — esto es una reaparición de
  ese mismo riesgo conocido.
- **`tracing.py` duplicado:** los 5 servicios tienen un `tracing.py` casi
  idéntico (user-service e inventory-service son idénticos byte a byte; los
  demás difieren en un puñado de líneas). Como cada Dockerfile ya copia
  `services/shared/` dentro de la imagen, este archivo podría consolidarse
  ahí en un futuro refactor — se dejó sin tocar acá para no cambiar rutas de
  importación ni Dockerfiles como parte de una pasada de documentación.
- **`Campos por servicio.md`** está en la raíz del repositorio en vez de
  estar bajo `docs/`. Está referenciado desde comentarios SQL y un ConfigMap
  de Kubernetes, así que moverlo también requeriría actualizar esas
  referencias — se dejó en su lugar.

## 9. Más información

- [`README.md`](README.md) — la referencia principal (en español), la más detallada y actualizada
- [`docs/00. setup.md`](docs/00.%20setup.md) — requisitos de configuración
- [`docs/01.Arquitectura.md`](docs/01.Arquitectura.md) — arquitectura, puertos internos, base de datos
- [`docs/TOOLING.md`](docs/TOOLING.md) — cómo funcionan internamente `cli.py`, chaos, circuit breaker, k6/JMeter y las operaciones de Kubernetes
- [`docs/services/`](docs/services/) — un documento por microservicio
- [`docs/ACTION-PLAN.md`](docs/ACTION-PLAN.md) — historial por fases de lo que se construyó y validó
- [`docs/RESULTS.md`](docs/RESULTS.md) — hallazgos consolidados de todas las fases de prueba
- [`docs/tests/`](docs/tests/) — resultados crudos por fase/fallo y capturas del dashboard
