#!/usr/bin/env bash
# =====================================================================
# scripts/up.sh - Arranque completo de Resilencia-Kubernetes
#
# Deja el proyecto listo de forma reproducible y rapida:
#   1. Asegura el cluster minikube (driver docker) + metrics-server
#   2. Construye las imagenes de los servicios y las carga al cluster
#   3. Aplica los manifiestos k8s (base + HPA) y espera los rollouts
#   4. Levanta el stack Docker Compose (control-panel + observabilidad)
#   5. Activa el modo Kubernetes del control-panel
#
# Uso:
#   ./scripts/up.sh                 # todo (Kubernetes + Compose)
#   ./scripts/up.sh --compose-only  # solo Docker Compose
#   ./scripts/up.sh --k8s-only      # solo el cluster Kubernetes
#   ./scripts/up.sh --no-build      # no reconstruir imagenes
#   ./scripts/up.sh --reset         # borra volumenes/manifiestos y arranca limpio
#   ./scripts/up.sh --help
#
# Nota: el control-panel guarda el modo runtime en memoria; este script lo
# re-activa a "kubernetes" en cada arranque.
# =====================================================================

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# ---------------------------------------------------------------------
# Salida con color (solo si hay terminal)
# ---------------------------------------------------------------------
if [[ -t 1 ]]; then
  C_RESET=$'\033[0m'; C_BLUE=$'\033[34m'; C_GREEN=$'\033[32m'
  C_YEL=$'\033[33m'; C_RED=$'\033[31m'
else
  C_RESET=; C_BLUE=; C_GREEN=; C_YEL=; C_RED=
fi

step() { printf '\n%s==>%s %s\n' "$C_BLUE" "$C_RESET" "$*"; }
ok()   { printf '%s[ok]%s %s\n' "$C_GREEN" "$C_RESET" "$*"; }
warn() { printf '%s[!]%s %s\n' "$C_YEL" "$C_RESET" "$*"; }
err()  { printf '%s[x]%s %s\n' "$C_RED" "$C_RESET" "$*" >&2; }

# ---------------------------------------------------------------------
# Argumentos
# ---------------------------------------------------------------------
DO_K8S=1
DO_COMPOSE=1
DO_BUILD=1
DO_RESET=0

usage() {
  sed -n '3,21p' "$0" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --compose-only) DO_K8S=0 ;;
    --k8s-only)     DO_COMPOSE=0 ;;
    --no-build)     DO_BUILD=0 ;;
    --reset)        DO_RESET=1 ;;
    -h|--help)      usage; exit 0 ;;
    *) err "Argumento desconocido: $1"; echo; usage; exit 1 ;;
  esac
  shift
done

# ---------------------------------------------------------------------
# Configuracion
# ---------------------------------------------------------------------
SERVICES=(order user inventory payment notification)
IMAGES=()
for s in "${SERVICES[@]}"; do IMAGES+=("${s}-service:latest"); done
IMAGES+=(data-seeder:latest)

DEPLOYMENTS=(
  postgres postgres-replica
  user-service inventory-service payment-service notification-service order-service
  otel-collector prometheus grafana jaeger
)

if [[ -f .env ]]; then
  CONTROL_PANEL_PORT="$(grep -E '^CONTROL_PANEL_PORT=' .env | tail -1 | cut -d= -f2- | tr -d '"' || true)"
fi
CONTROL_PANEL_PORT="${CONTROL_PANEL_PORT:-8105}"

# ---------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------
need() { command -v "$1" >/dev/null 2>&1 || { err "Falta '$1' en el PATH"; exit 1; }; }

step "Comprobando requisitos"
need docker
docker compose version >/dev/null 2>&1 || { err "Docker Compose v2 no esta disponible"; exit 1; }
need curl
if [[ "$DO_K8S" == 1 ]]; then need minikube; need kubectl; fi
ok "docker, docker compose y curl presentes"
[[ "$DO_K8S" == 1 ]] && ok "minikube y kubectl presentes"

if [[ ! -f .env ]]; then
  warn ".env no existe; copiando desde .env.example"
  cp .env.example .env
  warn "Revisa .env (K8S_API_SERVER, puertos) antes de continuar"
fi

# ---------------------------------------------------------------------
# Reset opcional (volumenes + manifiestos)
# ---------------------------------------------------------------------
if [[ "$DO_RESET" == 1 && "$DO_COMPOSE" == 1 ]]; then
  step "Reset: borrando stack Compose y sus volumenes"
  docker compose down -v --remove-orphans
fi
if [[ "$DO_RESET" == 1 && "$DO_K8S" == 1 ]]; then
  step "Reset: borrando manifiestos del cluster"
  kubectl delete -f k8s/resilience/hpa.yaml --ignore-not-found
  kubectl delete -f k8s/base/ --ignore-not-found
fi

# ---------------------------------------------------------------------
# 1. Cluster minikube
# ---------------------------------------------------------------------
ensure_minikube() {
  step "Asegurando cluster minikube"
  if minikube status >/dev/null 2>&1; then
    ok "minikube ya esta corriendo"
  else
    # Cuando la VM esta apagada, el control-panel (unido a la red externa
    # "minikube") puede haberse quedado con 192.168.49.2 y bloquear el
    # arranque. Se libera antes de levantar la VM.
    warn "minikube detenido: liberando 192.168.49.2 del control-panel"
    docker compose stop control-panel >/dev/null 2>&1 || true
    minikube start --driver=docker
  fi
  if minikube addons enable metrics-server >/dev/null 2>&1; then
    ok "addon metrics-server habilitado (necesario para el HPA)"
  else
    warn "no se pudo habilitar metrics-server (el HPA no leera CPU%)"
  fi
}

# ---------------------------------------------------------------------
# 2. Imagenes
# ---------------------------------------------------------------------
build_images() {
  step "Construyendo imagenes de los servicios"
  for s in "${SERVICES[@]}"; do
    docker build -q -t "${s}-service:latest" -f "services/${s}-service/Dockerfile" services
    ok "${s}-service:latest"
  done
  docker build -q -t data-seeder:latest -f services/data-seeder/Dockerfile .
  ok "data-seeder:latest"
}

load_images() {
  step "Cargando imagenes en minikube (imagePullPolicy: Never)"
  for img in "${IMAGES[@]}"; do
    # rmi previo evita capas cacheadas y quedarnos con una version vieja.
    minikube ssh "docker rmi $img" >/dev/null 2>&1 || true
    minikube image load "$img"
    ok "$img"
  done
}

ensure_certs() {
  step "Comprobando certificados del cluster para el control-panel"
  local missing=0
  for f in ca.crt client.crt client.key; do
    [[ -f "k8s/certs/$f" ]] || { warn "falta k8s/certs/$f"; missing=1; }
  done
  if [[ "$missing" == 0 ]]; then
    ok "k8s/certs/ completo"
  else
    warn "sin certificados el control-panel devolvera 503 al hablar con la API"
  fi
}

# ---------------------------------------------------------------------
# 3. Manifiestos Kubernetes
# ---------------------------------------------------------------------
apply_k8s() {
  step "Aplicando manifiestos Kubernetes"
  kubectl apply -f k8s/base/
  kubectl apply -f k8s/resilience/hpa.yaml
  ok "manifiestos aplicados"
}

wait_k8s() {
  step "Esperando rollouts del cluster"
  for d in "${DEPLOYMENTS[@]}"; do
    if kubectl rollout status "deployment/$d" --timeout=180s >/dev/null 2>&1; then
      ok "deployment/$d listo"
    else
      warn "deployment/$d no quedo listo a tiempo (kubectl describe deployment/$d)"
    fi
  done
  if kubectl wait --for=condition=complete job/data-seeder --timeout=180s >/dev/null 2>&1; then
    ok "job/data-seeder completado"
  else
    warn "job/data-seeder no completo (kubectl logs job/data-seeder)"
  fi
}

# ---------------------------------------------------------------------
# 4. Stack Docker Compose
# ---------------------------------------------------------------------
compose_up() {
  step "Levantando stack Docker Compose"
  local args=(-d --remove-orphans)
  [[ "$DO_BUILD" == 1 ]] && args+=(--build)
  docker compose up "${args[@]}"
  ok "contenedores iniciados"

  step "Esperando al control-panel en http://localhost:${CONTROL_PANEL_PORT}"
  local i
  for i in $(seq 1 60); do
    if curl -fsS "http://localhost:${CONTROL_PANEL_PORT}/api/runtime-mode" >/dev/null 2>&1; then
      ok "control-panel responde"
      return 0
    fi
    sleep 2
  done
  warn "el control-panel no respondio a tiempo (docker compose logs control-panel)"
}

# ---------------------------------------------------------------------
# 5. Modo runtime Kubernetes
# ---------------------------------------------------------------------
set_runtime_mode() {
  step "Activando modo Kubernetes en el control-panel"
  if curl -fsS -X POST -H 'Content-Type: application/json' \
      -d '{"mode":"kubernetes"}' \
      "http://localhost:${CONTROL_PANEL_PORT}/api/runtime-mode" >/dev/null 2>&1; then
    ok "control-panel en modo kubernetes"
  else
    warn "no se pudo activar el modo kubernetes (revisa K8S_API_SERVER y k8s/certs/)"
  fi
}

# ---------------------------------------------------------------------
# Ejecucion
# ---------------------------------------------------------------------
if [[ "$DO_K8S" == 1 ]]; then
  ensure_minikube
  [[ "$DO_BUILD" == 1 ]] && build_images
  load_images
  ensure_certs
  apply_k8s
  wait_k8s
fi

if [[ "$DO_COMPOSE" == 1 ]]; then
  compose_up
  [[ "$DO_K8S" == 1 ]] && set_runtime_mode
fi

# ---------------------------------------------------------------------
# Resumen
# ---------------------------------------------------------------------
step "Listo"
cat <<EOF

URLs utiles:
  Control-panel: http://localhost:${CONTROL_PANEL_PORT}
  Swagger:       http://localhost:8100/docs .. http://localhost:8104/docs
  Prometheus:    http://localhost:9091
  Grafana:       http://localhost:3001  (admin / admin)
  Jaeger:        http://localhost:16687

Comandos utiles:
  docker compose ps
  kubectl get pods,svc,hpa
  minikube dashboard
  ./scripts/up.sh --reset     # arranque limpio
EOF
