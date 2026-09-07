# Action Plan — Interfaz (Control Panel)

Continuación de `docs/ACTION-PLAN.md` Fase 12. Estado actual del panel
(`services/control-panel/`, puerto 8105) y sus limitaciones: ver
`docs/control-panel-limitations.md` (fuente de este plan, léelo primero).
Este documento define las fases para erradicarlas y dejar la interfaz
completamente intuitiva y utilizable, sin implementarlas todavía —
`docs/control-panel-limitations.md` recomendó iniciar en sesión nueva por
degradación de contexto.

## Fase I1 — CRUD real en los 5 microservicios

**Goal:** cerrar el gap más grande — hoy ningún servicio expone
`PUT`/`DELETE`.

**Steps:**
1. Por servicio (user/inventory/payment/notification/order), agregar
   `PUT /{entity}/{id}` (edición parcial o total) y `DELETE /{entity}/{id}`.
2. Reglas de negocio mínimas antes de borrar/editar (ej. no borrar un
   usuario con órdenes activas — o documentar explícitamente que sí se
   permite, por ser herramienta de estudio).
3. Exponer los 5x2 endpoints nuevos vía proxies en `control-panel/main.py`.
4. UI: formularios de edición inline + botón borrar con confirmación, por
   entidad, en las tablas ya existentes de "recientes".

**Files:** `services/*/main.py` (5), `services/control-panel/main.py`,
`services/control-panel/static/index.html`.

## Fase I2 — Generación y peticiones flexibles

**Goal:** el usuario pide explícitamente poder generar N registros (no un
número fijo) y enviar peticiones de forma flexible desde la UI.

**Steps:**
1. `POST /users/generate` y `POST /inventory/generate` actualmente generan
   un lote fijo (los 3 clientes de ejemplo). Agregar parámetro `count`
   (int, sin tope arbitrario salvo uno razonable de seguridad, ej. 1-200000)
   que genere ese número de registros Faker reales (reusar la lógica de
   `scripts/seed_database.py` si aplica, o extenderla a los propios
   servicios).
2. UI: reemplazar los botones fijos "Generar usuarios/inventario" por un
   input numérico + botón, en ambos.
3. **Constructor de peticiones flexible**: un panel tipo "cliente HTTP"
   dentro de la interfaz — método (GET/POST/PUT/DELETE), servicio destino
   (dropdown de los 5 + control-panel), path libre, body JSON libre, botón
   enviar, respuesta cruda mostrada. Cubre cualquier endpoint presente o
   futuro sin tener que tocar la UI de nuevo.
4. Opcional (si da tiempo): un botón "generar N órdenes" que dispare N
   `POST /orders` en paralelo/secuencia con progreso visible — mini
   generador de carga desde la propia UI, útil para probar la interfaz
   bajo su propio uso.

**Files:** `services/user-service/main.py`, `services/inventory-service/main.py`,
`services/control-panel/main.py`, `services/control-panel/static/index.html`.

## Fase I3 — Kubernetes: portabilidad y acciones

**Goal:** cerrar los gaps de portabilidad y "solo lectura" del panel de K8s.

**Steps:**
1. Quitar rutas/puertos hardcodeados (`C:\Users\vlaweirna\...`,
   `K8S_API_PORT=51311`) — leer el kubeconfig dinámicamente o exponerlo
   100% vía variables de entorno documentadas en `.env.example`.
2. Agregar acción "borrar pod" (botón por fila, con confirmación) y
   selector de namespace (hoy fijo a `default`).
3. Evaluar reemplazar el `verify=False` por una verificación real (usar el
   hostname correcto vía SNI override) si el tiempo lo permite; si no,
   dejarlo documentado como aceptado (cluster local de estudio).

**Files:** `services/control-panel/main.py`, `compose.yml`, `.env.example`.

## Fase I4 — Desplegar el panel también en Kubernetes/Helm

**Goal:** el panel hoy solo existe en Compose.

**Steps:** Deployment + Service para `control-panel` en `k8s/base/`, y su
equivalente en `charts/resilencia/templates/`. Mismas variables de entorno
que Compose, apuntando a los Services internos del cluster en vez de
`host.docker.internal`.

**Files:** nuevo `k8s/base/control-panel.yaml`, nuevo template de Helm.

## Fase I5 — Observabilidad del propio panel

**Goal:** cerrar los gaps de Grafana fijo y disco no instrumentado.

**Steps:**
1. Selector de dashboard en el iframe de Grafana (listar dashboards vía
   su API en vez de la URL fija a `resilencia-overview`).
2. Instrumentar disco de verdad: agregar `cadvisor` a `compose.yml` y a
   los manifiestos de K8s, scrapeado por Prometheus, como métrica real en
   vez de leer `blkio_stats` del socket de Docker en cada request.

**Files:** `compose.yml`, `observability/prometheus.yml`,
`services/control-panel/main.py`, `services/control-panel/static/index.html`.

## Fase I6 — Calidad: tests y resiliencia del panel

**Goal:** el panel mismo no tiene pruebas ni manejo de reconexión.

**Steps:**
1. Tests automatizados básicos para `control-panel/main.py` (pytest +
   httpx mock o contra el stack real vía Compose).
2. Manejo de reconexión/reintento en el frontend cuando Prometheus/K8s/un
   servicio no responde, en vez de mostrar el error crudo sin más.

**Files:** nuevo `services/control-panel/test_main.py`,
`services/control-panel/static/index.html`.

## Fase I7 — Pase de diseño (si aplica)

**Goal:** la Fase 12 original pedía un proceso de mockups
(`claude-design`, `ui-mockup-screens`) que se saltó por tiempo. Revisar la
interfaz ya funcional contra ese proceso y ajustar visualmente si hace
falta, una vez el contenido/funcionalidad de I1-I6 esté cerrado (mismo
orden de prioridad que el resto del proyecto: contenido antes que forma).

## Orden sugerido de ejecución

I1 → I2 → I3 → I4 → I5 → I6 → I7 (I1/I2 son los pedidos explícitos de esta
conversación; I3-I6 vienen de `docs/control-panel-limitations.md`; I7 es
la deuda de proceso original de la Fase 12).
