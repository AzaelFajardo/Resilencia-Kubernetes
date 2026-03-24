# Main payment-service logic.
# This service simulates payment processing and controlled failure scenarios.
from fastapi import FastAPI
import os
import random
import asyncio

# Initializes the FastAPI application for the payment microservice.
# It keeps the API small because this service only exposes health and payment endpoints.
app = FastAPI(title="payment-service")

# Failure-injection variables loaded from Compose.
# They control simulated errors, added latency, and timeouts.
FAILURE_RATE = float(os.getenv("FAILURE_RATE", "0.0"))
LATENCY_MS = int(os.getenv("LATENCY_MS", "0"))
TIMEOUT_RATE = float(os.getenv("TIMEOUT_RATE", "0.0"))


# Health endpoint for probes or basic checks.
# It returns a minimal response showing that the service is running.
@app.get("/health")
def health():
    return {"status": "ok", "service": "payment-service"}


# Endpoint that simulates payment processing.
# It can add latency, time out, or fail based on environment configuration.
@app.get("/pay")
async def process_payment():
    # Apply artificial latency when configured.
    if LATENCY_MS > 0:
        await asyncio.sleep(LATENCY_MS / 1000.0)

    # Simulate a timeout when configured.
    if TIMEOUT_RATE > 0 and random.random() < TIMEOUT_RATE:
        await asyncio.sleep(30)

    # Simulate a controlled failure based on the environment variable.
    if FAILURE_RATE > 0 and random.random() < FAILURE_RATE:
        return {"status": "error", "message": "Payment failed"}

    return {"status": "success", "message": "Payment processed"}
