# Main order-service logic.
# This microservice acts as the central orchestrator for the order flow.
from fastapi import FastAPI
import httpx
import os
import asyncio

# Initializes the FastAPI application for the orchestrator.
# It exposes a health endpoint and the end-to-end order flow.
app = FastAPI(title="order-service")

# Base URLs for dependent services.
# They are loaded from Compose or fall back to local defaults.
USER_SERVICE_URL = os.getenv("USER_SERVICE_URL", "http://user-service:8000")
INVENTORY_SERVICE_URL = os.getenv("INVENTORY_SERVICE_URL", "http://inventory-service:8000")
PAYMENT_SERVICE_URL = os.getenv("PAYMENT_SERVICE_URL", "http://payment-service:8000")
NOTIFICATION_SERVICE_URL = os.getenv("NOTIFICATION_SERVICE_URL", "http://notification-service:8000")

# Resilience settings loaded from environment variables.
# These values control retry behavior and outbound request timeouts.
RETRY_ENABLED = os.getenv("RETRY_ENABLED", "false").lower() == "true"
RETRY_COUNT = int(os.getenv("RETRY_COUNT", "3"))
RETRY_DELAY_MS = int(os.getenv("RETRY_DELAY_MS", "100"))
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "5.0"))


async def call_service(client, url, retries=0):
    """Performs a GET request to a service with optional retries."""
    last_error = None
    attempts = retries + 1 if RETRY_ENABLED else 1

    for i in range(attempts):
        try:
            resp = await client.get(url, timeout=HTTP_TIMEOUT)
            return resp
        except Exception as e:
            last_error = e
            if i < attempts - 1:
                await asyncio.sleep(RETRY_DELAY_MS / 1000.0)

    raise last_error


# Health endpoint for basic checks.
# It returns a minimal payload that identifies this service.
@app.get("/health")
def health():
    return {"status": "ok", "service": "order-service"}


# Endpoint that executes the full order flow.
# It validates the user, checks inventory, processes payment, and sends a notification in sequence.
@app.get("/order")
async def create_order():
    async with httpx.AsyncClient() as client:
        # 1. Validate the user.
        try:
            user_resp = await call_service(client, f"{USER_SERVICE_URL}/users/1/validate", RETRY_COUNT)
            user_data = user_resp.json()
            if not user_data.get("valid"):
                return {"status": "error", "message": "User validation failed"}
        except Exception:
            return {"status": "error", "message": "User service unavailable"}

        # 2. Check inventory.
        try:
            inv_resp = await call_service(client, f"{INVENTORY_SERVICE_URL}/inventory/1/availability", RETRY_COUNT)
            inv_data = inv_resp.json()
            if not inv_data.get("available"):
                return {"status": "error", "message": "Product not available"}
        except Exception:
            return {"status": "error", "message": "Inventory service unavailable"}

        # 3. Process payment.
        try:
            pay_resp = await call_service(client, f"{PAYMENT_SERVICE_URL}/pay", RETRY_COUNT)
            pay_data = pay_resp.json()
            if pay_data.get("status") != "success":
                return {"status": "error", "message": "Payment failed"}
        except Exception:
            return {"status": "error", "message": "Payment service unavailable"}

        # 4. Send notification.
        try:
            await call_service(client, f"{NOTIFICATION_SERVICE_URL}/notify", RETRY_COUNT)
        except Exception:
            return {"status": "warning", "message": "Order created but notification failed"}

    return {"status": "success", "message": "Order completed"}
