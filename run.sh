#!/usr/bin/env bash
# =====================================================================
# run.sh  –  Helper de arranque para Resilencia-Kubernetes (macOS/Linux)
#
# Uso:
#   ./run.sh up       # construye e inicia todo el stack
#   ./run.sh reset    # borra volumenes y reinicia desde cero
#   ./run.sh logs     # sigue los logs de todos los servicios
# =====================================================================

set -euo pipefail

COMMAND="${1:-up}"

show_help() {
  cat <<'EOF'
Resilencia-Kubernetes - arranque rapido (macOS / Linux)

Uso: ./run.sh [comando]

Comandos:
  up      Construye e inicia todo el stack en segundo plano (por defecto)
  k8s     Levanta todo contemplando Kubernetes (minikube + manifiestos + Compose)
  stop    Detiene todo de forma ordenada y sin forzar (Compose + minikube)
  build   Reconstruye las imagenes sin cache
  down    Detiene el stack y elimina los contenedores
  reset   Detiene, borra volumenes y vuelve a iniciar desde cero
  logs    Sigue los logs de todos los servicios
  ps      Muestra el estado de los contenedores
  status  Muestra el estado y recuerda las URLs principales
  help    Muestra esta ayuda

Atajos de Kubernetes (delegan en scripts/):
  ./run.sh k8s     -> scripts/up.sh    (opciones: --compose-only, --k8s-only, --no-build, --reset)
  ./run.sh stop    -> scripts/down.sh  (opciones: --compose-only, --k8s-only, --keep-cluster, --purge)

Configuracion: copia .env.example a .env para ajustar seed, chaos y DB.
EOF
}

case "$COMMAND" in
  help)
    show_help
    ;;
  k8s)
    shift
    exec "$(dirname "$0")/scripts/up.sh" "$@"
    ;;
  stop)
    shift
    exec "$(dirname "$0")/scripts/down.sh" "$@"
    ;;
  up)
    docker compose up --build -d --remove-orphans
    echo ""
    echo "Stack iniciado."
    ;;
  build)
    docker compose build --no-cache
    ;;
  down)
    docker compose down --remove-orphans
    ;;
  reset)
    docker compose down -v --remove-orphans
    docker compose up --build -d --remove-orphans
    echo ""
    echo "Stack reiniciado desde cero."
    ;;
  logs)
    docker compose logs -f
    ;;
  ps)
    docker compose ps
    ;;
  status)
    docker compose ps
    cat <<'EOF'

URLs utiles:
  Swagger:      http://localhost:8100/docs .. http://localhost:8104/docs
  Prometheus:   http://localhost:9091
  Grafana:      http://localhost:3001  (admin / admin)
  Jaeger:       http://localhost:16687
EOF
    ;;
  *)
    echo "Comando desconocido: $COMMAND"
    echo ""
    show_help
    exit 1
    ;;
esac
