# Logica del servicio de notificaciones
from fastapi import FastAPI
import os
import random
import asyncio

app = FastAPI(title="notification-service")

# Variables para inyeccion de fallos desde el compose
FAILURE_RATE = float(os.getenv("FAILURE_RATE", "0.0"))
LATENCY_MS = int(os.getenv("LATENCY_MS", "0"))


@app.get("/health")
def health():
    return {"status": "ok", "service": "notification-service"}


@app.get("/notify")
async def send_notification():
    # Latencia artificial si se configuro
    if LATENCY_MS > 0:
        await asyncio.sleep(LATENCY_MS / 1000.0)

    # Simular fallo controlado por env var
    if FAILURE_RATE > 0 and random.random() < FAILURE_RATE:
        return {"status": "error", "message": "Notification failed"}

    return {"status": "sent", "message": "Notification delivered"}