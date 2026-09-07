# Control Panel — Limitaciones y pendientes (Fase 12)

`services/control-panel/`, puerto 8105. Construido bajo restricción severa
de tiempo/contexto — esto documenta honestamente qué falta.

## No tiene CRUD real

No hay crear/editar/borrar para users, products, orders, payments,
notifications. Ninguno de los 5 microservicios expone `PUT`/`DELETE` —
solo `POST`/`GET`. Arreglarlo requiere:
- Agregar rutas `PUT /{entity}/{id}` y `DELETE /{entity}/{id}` a cada
  microservicio (5 servicios, no solo el panel).
- Validación de negocio por entidad (ej. no borrar un usuario con órdenes
  activas, no editar una orden ya pagada).
- El panel es solo un cliente — sin backend nuevo en los servicios, el
  panel no puede ofrecer esto de verdad.

## Kubernetes: solo lectura

`/api/kubernetes` lee pods + HPA vía el API server de minikube, pero:
- **Sin botones de acción** (borrar pod, escalar manualmente, ver logs).
- **Certificado sin verificar** (`verify=False` en `main.py`) — el cert
  del cluster es para el hostname de minikube, no para
  `host.docker.internal` (la ruta real hacia el cluster desde el
  contenedor). Aceptable en un cluster local de estudio, **no
  reproducible en otra máquina** sin ajustar rutas/puertos hardcodeados.
- **Puerto del API server hardcodeado** (`K8S_API_PORT` default `51311`)
  — minikube asigna este puerto dinámicamente en cada `minikube start`;
  si cambia, hay que actualizarlo a mano en `compose.yml` o vía env var.
- **Rutas de certs hardcodeadas** a `C:\Users\vlaweirna\.minikube\...` en
  `compose.yml` — específico de esta máquina, no portable.
- Solo namespace `default`, sin selector de namespace.

## Grafana: embebido pero simplificado

- El iframe carga el dashboard fijo `resilencia-overview` — no hay
  selector para otros dashboards.
- `GF_AUTH_ANONYMOUS_ENABLED=true` en Grafana — cualquiera con acceso a
  la red puede ver el dashboard sin login. Aceptable para herramienta
  local de estudio (sin auth en todo el proyecto por diseño), pero es una
  superficie más si esto se expusiera fuera de `localhost`.

## Disco: aproximado, no instrumentado

`/api/disk` lee `blkio_stats` del socket de Docker (bytes de escritura
acumulados desde que el contenedor arrancó, no una tasa). No hay métrica
de disco en Prometheus (`prometheus_client`'s `ProcessCollector` no
expone I/O) — si se quiere en Grafana/alertas, hay que instrumentarlo de
verdad en cada servicio o agregar `cadvisor`.

## Otras limitaciones

- **Sin autenticación** (decisión de alcance explícita del proyecto, no
  un descuido — ver `docs/ACTION-PLAN.md` Fase 12 "Scope decision").
- **Sin tests automatizados** para el panel mismo — solo se verificó con
  `curl` manual y una revisión visual en el navegador.
- **Sin manejo de reconexión** — si Prometheus/K8s/un servicio cae, el
  panel muestra el último estado o un error crudo, sin reintento
  automático más allá del poll de 5s.
- **No corre en Kubernetes** — solo existe como servicio de Compose; no
  hay Deployment/Service para `control-panel` en `k8s/base/` ni en el
  chart de Helm.
- **Requiere Docker Desktop con socket accesible** y el volumen
  `/var/run/docker.sock` montado — no funciona igual en un host sin
  Docker (ej. si algún día se corre el panel fuera de Compose).
- **Diseño construido directo**, sin el proceso de mockups en HTML/PNG
  que pedía la instrucción original de la Fase 12 (`claude-design`,
  `ui-mockup-screens`) — se priorizó tener algo funcional dado el tiempo.

## Prioridad sugerida si se retoma

1. CRUD real (el gap más grande vs. lo pedido en Fase 12).
2. Portabilidad de las rutas/puertos de Kubernetes (variables de entorno
   en vez de hardcode).
3. Deployment del panel en K8s/Helm.
4. Selector de namespace y acciones básicas (borrar pod) en el panel de K8s.
