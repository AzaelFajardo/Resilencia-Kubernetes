#!/usr/bin/env bash
# =====================================================================
# scripts/down.sh - Detencion ordenada de Resilencia-Kubernetes
#
# Detiene el proyecto sin forzar nada: envia SIGTERM (parada suave) y da
# tiempo a los procesos a cerrar. No borra datos ni manifiestos salvo que
# se pida explicitamente con --purge.
#
#   1. Detiene el stack Docker Compose con "docker compose stop"
#   2. Detiene el cluster minikube con "minikube stop" (apagado ordenado)
#
# Uso:
#   ./scripts/down.sh                 # detiene Compose y minikube
#   ./scripts/down.sh --compose-only  # solo Docker Compose
#   ./scripts/down.sh --k8s-only      # solo el cluster Kubernetes
#   ./scripts/down.sh --keep-cluster  # detiene Compose y deja minikube arriba
#   ./scripts/down.sh --purge         # ademas borra volumenes y manifiestos
#   ./scripts/down.sh --help
# =====================================================================

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

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

DO_COMPOSE=1
DO_K8S=1
KEEP_CLUSTER=0
DO_PURGE=0

usage() { sed -n '3,18p' "$0" | sed 's/^# \{0,1\}//'; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --compose-only) DO_K8S=0 ;;
    --k8s-only)     DO_COMPOSE=0 ;;
    --keep-cluster) KEEP_CLUSTER=1 ;;
    --purge)        DO_PURGE=1 ;;
    -h|--help)      usage; exit 0 ;;
    *) err "Argumento desconocido: $1"; echo; usage; exit 1 ;;
  esac
  shift
done

need() { command -v "$1" >/dev/null 2>&1 || { err "Falta '$1' en el PATH"; exit 1; }; }

step "Comprobando requisitos"
need docker
docker compose version >/dev/null 2>&1 || { err "Docker Compose v2 no esta disponible"; exit 1; }
if [[ "$DO_K8S" == 1 ]]; then need minikube; need kubectl; fi
ok "herramientas necesarias presentes"

# ---------------------------------------------------------------------
# 1. Docker Compose: parada suave (SIGTERM, 30s de gracia)
# ---------------------------------------------------------------------
if [[ "$DO_COMPOSE" == 1 ]]; then
  step "Deteniendo stack Docker Compose (parada suave, 30s de gracia)"
  docker compose stop -t 30
  ok "contenedores detenidos sin borrarlos (se reanudan con ./scripts/up.sh)"
fi

# ---------------------------------------------------------------------
# 2. Purga opcional (destructiva): se hace con el cluster aun arriba
# ---------------------------------------------------------------------
if [[ "$DO_PURGE" == 1 && "$DO_K8S" == 1 ]]; then
  step "Purga: borrando manifiestos del cluster"
  kubectl delete -f k8s/resilience/hpa.yaml --ignore-not-found
  kubectl delete -f k8s/base/ --ignore-not-found
  ok "manifiestos eliminados"
fi
if [[ "$DO_PURGE" == 1 && "$DO_COMPOSE" == 1 ]]; then
  step "Purga: borrando contenedores y volumenes Compose"
  docker compose down -v --remove-orphans
  ok "volumenes Compose eliminados"
fi

# ---------------------------------------------------------------------
# 3. minikube: apagado ordenado (conserva pods/PVCs para el proximo inicio)
# ---------------------------------------------------------------------
if [[ "$DO_K8S" == 1 ]]; then
  if [[ "$KEEP_CLUSTER" == 1 ]]; then
    step "Dejando minikube en ejecucion (--keep-cluster)"
    ok "cluster intacto"
  elif minikube status >/dev/null 2>&1; then
    step "Deteniendo cluster minikube (apagado ordenado)"
    minikube stop
    ok "minikube detenido; el estado persiste y se reanuda con ./scripts/up.sh"
  else
    warn "minikube no estaba corriendo"
  fi
fi

step "Listo"
cat <<EOF

El proyecto quedo detenido de forma limpia.
Para volver a levantarlo:  ./scripts/up.sh
Con estado desde cero:     ./scripts/up.sh --reset
EOF
