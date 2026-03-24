# Main notification-service logic.
# This service simulates the delivery of outbound notifications.
from fastapi import FastAPI
import os
import random
import asyncio

# Initializes the FastAPI application for the notification microservice.
# It only exposes health and notification endpoints in this baseline version.
app = FastAPI(title="notification-service")

# Failure-injection variables loaded from Compose.
# They control simulated errors and added latency.
FAILURE_RATE = float(os.getenv("FAILURE_RATE", "0.0"))
LATENCY_MS = int(os.getenv("LATENCY_MS", "0"))


# Health endpoint for probes or basic checks.
# It returns a minimal payload to confirm the service is available.
@app.get("/health")
def health():
    return {"status": "ok", "service": "notification-service"}


# Endpoint that simulates notification delivery.
# It can add latency or fail based on the configured environment values.
@app.get("/notify")
async def send_notification():
    # Apply artificial latency when configured.
    if LATENCY_MS > 0:
        await asyncio.sleep(LATENCY_MS / 1000.0)

    # Simulate a controlled failure based on the environment variable.
    if FAILURE_RATE > 0 and random.random() < FAILURE_RATE:
        return {"status": "error", "message": "Notification failed"}

    return {"status": "sent", "message": "Notification delivered"}
