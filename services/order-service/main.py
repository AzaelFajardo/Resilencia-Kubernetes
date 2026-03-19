#Logica de el servicio de ordenes
from fastapi import FastAPI
import httpx

app = FastAPI()

PAYMENT_URL = "http://payment-service:8000/pay"
NOTIFICATION_URL = "http://notification-service:8000/notify"

@app.get("/order")
async def create_order():
    async with httpx.AsyncClient() as client:
        try:
            payment = await client.get(PAYMENT_URL, timeout=2.0)
        except:
            return {"status": "error", "message": "Payment service unavailable"}

        if payment.json().get("status") != "success":
            return {"status": "error", "message": "Payment failed"}

        try:
            await client.get(NOTIFICATION_URL)
        except:
            return {"status": "warning", "message": "Order created but notification failed"}

    return {"status": "success", "message": "Order completed"}