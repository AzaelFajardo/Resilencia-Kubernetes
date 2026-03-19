#Logica de el servicio de ordenes
from fastapi import FastAPI

app = FastAPI()

@app.get("/notify")
def send_notification():
    return {"status": "sent", "message": "Notification delivered"}