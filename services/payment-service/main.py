#Logica de el servicio de ordenes

from fastapi import FastAPI
import random
import time

app = FastAPI()

@app.get("/pay")
def process_payment():
    # Simular latencia
    delay = random.uniform(0.1, 2.0)
    time.sleep(delay)

    # Simular fallo (30%)
    if random.random() < 0.3:
        return {"status": "error", "message": "Payment failed"}

    return {"status": "success", "message": "Payment processed"}