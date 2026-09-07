# Control Panel — Estado de gaps (Fase 12)

> Estado consolidado de `services/control-panel/` (puerto 8105). Este doc
> sustituye la vista rápida de limitaciones por un checklist vivo: cada gap
> identificado, su impacto y si está resuelto. Es la fuente de verdad de
> progreso de la Fase 12; los detalles de implementación de cada corrección
> viven en los commits y en `docs/ACTION-PLAN.md` (Phase 12).

## 1. CRUD real en los 5 microservicios (gap más grande)

Hoy **ningún microservicio exponía `PUT`/`DELETE`** (solo `POST`/`GET`), así
que el panel no podía ofrecer crear/editar/borrar de verdad: era un cliente
sin backend al que llamar.

| Entidad | Endpoints necesarios | Estado |
| --- | --- | --- |
| users | `PATCH /users/<id>` (parcial), `DELETE /users/<id>` | ✅ agregado (user-service) |
| products | `POST /inventory`, `PATCH /inventory/<id>`, `DELETE /inventory/<id>` | ✅ agregado (inventory-service) |
| orders | `PATCH /orders/<id>/status`, `DELETE /orders/<id>` | ✅ agregado (order-service) |
| payments | `GET /payments` paginado, `DELETE /payments/<id>` | ✅ agregado (payment-service) |
| notifications | `GET /notifications` paginado, `DELETE /notifications/<id>` | ✅ agregado (notification-service) |

Validación de negocio mínima por entidad:
- **Borrado en cascada (users/products/orders):** la BD define
  `ON DELETE CASCADE` — borrar un usuario/producto/orden arrastra sus
  dependencias (órdenes → pagos/notificaciones). Decisión de herramienta de
  estudio: **se permite**, documentado en el docstring de cada `DELETE`.
- `PATCH` de productos hace merge superficial de `data`, no reemplazo total.
- `PATCH /orders/<id>/status` valida el status contra los 8 estados del
  enum de la BD.

Pendiente del panel (UI): formularios de edición inline + botón borrar con
confirmación por entidad en las tablas (la API ya existe).

## 2. Paginación + búsqueda en listados

- ✅ `GET /payments`, `GET /notifications`, `GET /users` y `GET /inventory`
  ahora aceptan `offset`/`limit`.
- ⚠️ `/orders/recent`, `/users/recent` etc. siguen sin `offset` y sin
  búsqueda/filtros por campo — para explorar 50k usuarios con filtros
  (nombre/email) hace falta búsqueda en los servicios (pendiente de
  prioridad media).

## 3. Latencia p50/p95/p99 por servicio en el panel

- ✅ El panel expone `GET /api/latency` (percentiles por servicio vía
  Prometheus) y la vista "Latencia por servicio (p50/p95/p99)" en el
  frontend.
- ⚠️ Nota: los histogramas por defecto de Prometheus son gruesos a bajo
  volumen (ver dashboard Phase 8) — los números del panel son orientativos;
  los del reporte salen de k6/JMeter.

## 4. Escritura de disco — aproximada, no instrumentada

- ⚠️ `/api/disk` lee `blkio_stats` del socket Docker (acumulado desde el
  arranque del contenedor, no una tasa). No hay métrica de disco en
  Prometheus (`ProcessCollector` no expone I/O). Si se quiere en
  Grafana/alertas, hace falta `cadvisor` (o `node-exporter`) en Compose +
  Prometheus.

## 5. Kubernetes — solo lectura y no portable

- ⚠️ `/api/kubernetes` lee pods + HPA del API server de minikube pero:
  - sin botones de acción (borrar pod, escalar, logs);
  - `verify=False` (cert emitido para hostname de minikube, no para
    `host.docker.internal`) — aceptable en cluster local de estudio;
  - puerto del API server hardcodeado (`K8S_API_PORT` default 51311) —
    minikube lo asigna dinámicamente en cada `start`;
  - rutas de certs hardcodeadas a `C:\Users\vlaweirna\.minikube\...` en
    `compose.yml` — específico de esta máquina;
  - solo namespace `default`.

## 6. Grafana — embebido pero simplificado

- ⚠️ El iframe carga el dashboard fijo `resilencia-overview`; sin selector
  de otros dashboards.
- ⚠️ `GF_AUTH_ANONYMOUS_ENABLED=true` — cualquiera con acceso a la red ve el
  dashboard sin login (aceptado: herramienta local sin auth por diseño).

## 7. Sin tests automatizados del panel

- ⚠️ Solo verificado con `curl` manual y revisión visual. Falta
  `test_main.py` (pytest + httpx mock).

## 8. Sin manejo de reconexión en el frontend

- ⚠️ Si Prometheus/K8s/un servicio cae, el panel muestra el último estado o
  un error crudo; el poll de 5s es el único reintento.

## 9. El panel no corre en Kubernetes

- ⚠️ Solo existe como servicio de Compose; no hay Deployment/Service en
  `k8s/base/` ni template en `charts/resilencia/`.

## 10. Deuda de proceso de diseño

- ⚠️ La Fase 12 pedía mockups vía `claude-design`/`ui-mockup-screens`/
  `html-mockup-render` renderizados a PNG antes de cablear datos. Se
  construyó directo por restricción de tiempo. Ajuste visual diferido.

## Alertas en el panel

- ✅ El panel expone `GET /api/alerts` (lee `/api/v1/rules` de Prometheus)
  y una vista "Alertas" en el frontend que muestra cada regla con su estado
  (inactive/pending/firing). Prometheus ya carga `observability/alerts.yml`
  (Phase 11): `ServiceDown`, `CircuitBreakerOpen`, `HighOrderLatencyP95`,
  `HighOrderErrorRate`.

## Prioridad

1. ✅ CRUD backend (cerrado en esta pasada).
2. ✅ Proxies CRUD + UI (crear/editar/borrar por entidad) en el panel.
3. ✅ Latencia por servicio + vista de alertas en el panel.
4. Disco real vía cadvisor en Prometheus (hoy: aproximado vía socket Docker).
5. Portabilidad de K8s (env vars en vez de hardcode a esta máquina).
6. Deployment del panel en K8s/Helm.
7. Tests + reconexión del panel.
8. Pase de diseño con las skills de mockups (`claude-design`,
   `ui-mockup-screens`, `html-mockup-render`).
