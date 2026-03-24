# Logica del servicio de ordenes - orquestador central
from fastapi import FastAPI
import httpx
import os
import asyncio

app = FastAPI(title="order-service")

# URLs de los servicios, se leen del compose o se usan defaults
USER_SERVICE_URL = os.getenv("USER_SERVICE_URL", "http://user-service:8000")
INVENTORY_SERVICE_URL = os.getenv("INVENTORY_SERVICE_URL", "http://inventory-service:8000")
PAYMENT_SERVICE_URL = os.getenv("PAYMENT_SERVICE_URL", "http://payment-service:8000")
NOTIFICATION_SERVICE_URL = os.getenv("NOTIFICATION_SERVICE_URL", "http://notification-service:8000")

# Config de resiliencia desde env vars
RETRY_ENABLED = os.getenv("RETRY_ENABLED", "false").lower() == "true"
RETRY_COUNT = int(os.getenv("RETRY_COUNT", "3"))
RETRY_DELAY_MS = int(os.getenv("RETRY_DELAY_MS", "100"))
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "5.0"))


async def call_service(client, url, retries=0):
    """Hace GET a un servicio con reintentos opcionales."""
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


@app.get("/health")
def health():
    return {"status": "ok", "service": "order-service"}


@app.get("/order")
async def create_order():
    async with httpx.AsyncClient() as client:
        # 1. Validar usuario
        try:
            user_resp = await call_service(client, f"{USER_SERVICE_URL}/users/1/validate", RETRY_COUNT)
            user_data = user_resp.json()
            if not user_data.get("valid"):
                return {"status": "error", "message": "User validation failed"}
        except Exception:
            return {"status": "error", "message": "User service unavailable"}

        # 2. Verificar inventario
        try:
            inv_resp = await call_service(client, f"{INVENTORY_SERVICE_URL}/inventory/1/availability", RETRY_COUNT)
            inv_data = inv_resp.json()
            if not inv_data.get("available"):
                return {"status": "error", "message": "Product not available"}
        except Exception:
            return {"status": "error", "message": "Inventory service unavailable"}

        # 3. Procesar pago
        try:
            pay_resp = await call_service(client, f"{PAYMENT_SERVICE_URL}/pay", RETRY_COUNT)
            pay_data = pay_resp.json()
            if pay_data.get("status") != "success":
                return {"status": "error", "message": "Payment failed"}
        except Exception:
            return {"status": "error", "message": "Payment service unavailable"}

        # 4. Enviar notificacion
        try:
            await call_service(client, f"{NOTIFICATION_SERVICE_URL}/notify", RETRY_COUNT)
        except Exception:
            return {"status": "warning", "message": "Order created but notification failed"}

    return {"status": "success", "message": "Order completed"}