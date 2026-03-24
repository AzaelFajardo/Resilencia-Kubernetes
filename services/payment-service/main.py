# Logica del servicio de pagos
from fastapi import FastAPI
import os
import random
import asyncio

app = FastAPI(title="payment-service")

# Variables para inyeccion de fallos desde el compose
FAILURE_RATE = float(os.getenv("FAILURE_RATE", "0.0"))
LATENCY_MS = int(os.getenv("LATENCY_MS", "0"))
TIMEOUT_RATE = float(os.getenv("TIMEOUT_RATE", "0.0"))


@app.get("/health")
def health():
    return {"status": "ok", "service": "payment-service"}


@app.get("/pay")
async def process_payment():
    # Latencia artificial si se configuro
    if LATENCY_MS > 0:
        await asyncio.sleep(LATENCY_MS / 1000.0)

    # Simular timeout si se configuro
    if TIMEOUT_RATE > 0 and random.random() < TIMEOUT_RATE:
        await asyncio.sleep(30)

    # Simular fallo controlado por env var
    if FAILURE_RATE > 0 and random.random() < FAILURE_RATE:
        return {"status": "error", "message": "Payment failed"}

    return {"status": "success", "message": "Payment processed"}