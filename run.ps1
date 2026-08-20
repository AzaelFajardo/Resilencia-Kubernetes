<#
.SYNOPSIS
  Helper de arranque multiplataforma para Resilencia-Kubernetes (Windows).

.DESCRIPTION
  Envuelve `docker compose` para levantar, detener, resetear y depurar el stack.

.EXAMPLE
  .\run.ps1 up       # construye e inicia todo el stack
  .\run.ps1 reset    # borra volumenes y reinicia desde cero
  .\run.ps1 logs     # sigue los logs de todos los servicios
#>

param(
    [Parameter(Position = 0)]
    [ValidateSet("up", "build", "down", "reset", "logs", "ps", "status", "help")]
    [string]$Command = "up"
)

$ErrorActionPreference = "Stop"

function Show-Help {
    Write-Host @"

Resilencia-Kubernetes - arranque rapido (Windows PowerShell)

Uso: .\run.ps1 [comando]

Comandos:
  up      Construye e inicia todo el stack en segundo plano (por defecto)
  build   Reconstruye las imagenes sin cache
  down    Detiene el stack y elimina los contenedores
  reset   Detiene, borra volumenes y vuelve a iniciar desde cero
  logs    Sigue los logs de todos los servicios
  ps      Muestra el estado de los contenedores
  status  Muestra el estado y recuerda las URLs principales
  help    Muestra esta ayuda

Configuracion: copia .env.example a .env para ajustar seed, chaos y DB.
"@
}

function Invoke-Compose {
    param([string[]]$Args)
    & docker compose @Args
    if ($LASTEXITCODE -ne 0) {
        Write-Error "docker compose fallo con codigo $LASTEXITCODE"
        exit $LASTEXITCODE
    }
}

switch ($Command) {
    "help" {
        Show-Help
    }
    "up" {
        Invoke-Compose @("up", "--build", "-d")
        Write-Host "`nStack iniciado. Panel: http://localhost:5180"
    }
    "build" {
        Invoke-Compose @("build", "--no-cache")
    }
    "down" {
        Invoke-Compose @("down")
    }
    "reset" {
        Invoke-Compose @("down", "-v")
        Invoke-Compose @("up", "--build", "-d")
        Write-Host "`nStack reiniciado desde cero. Panel: http://localhost:5180"
    }
    "logs" {
        Invoke-Compose @("logs", "-f")
    }
    "ps" {
        Invoke-Compose @("ps")
    }
    "status" {
        Invoke-Compose @("ps")
        Write-Host @"

URLs utiles:
  Panel:        http://localhost:5180
  Swagger:      http://localhost:8100/docs .. http://localhost:8104/docs
  Prometheus:   http://localhost:9091
  Grafana:      http://localhost:3001  (admin / admin)
  Jaeger:       http://localhost:16687
"@
    }
}
