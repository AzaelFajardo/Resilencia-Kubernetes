Microservicio: Payment Service
1. Descripción

El Payment Service es un microservicio encargado de simular el procesamiento de pagos dentro del sistema. Este servicio incluye mecanismos para simular fallos y latencia, lo cual es fundamental para pruebas de resiliencia.

2. Objetivo

Simular un servicio crítico que puede fallar, permitiendo evaluar el comportamiento del sistema ante errores.

3. Funcionalidad

Este servicio permite:

Procesar solicitudes de pago
Simular retrasos en la respuesta
Generar fallos aleatorios
4. Endpoint disponible
GET /pay
Descripción:

Procesa una solicitud de pago de manera simulada.

Comportamiento:
Existe una probabilidad del 30% de fallo
Se introduce una latencia aleatoria
Respuestas:

Éxito:

{
  "status": "success",
  "message": "Payment processed"
}

Error:

{
  "status": "error",
  "message": "Payment failed"
}
5. Tecnologías utilizadas
Python
FastAPI
Uvicorn
6. Ejecución
Local:
python -m uvicorn main:app --reload --port 8002
Docker:

Se ejecuta en un contenedor con puerto interno 8000.

7. Rol en la arquitectura

Este servicio es utilizado por el Order Service para validar y procesar pagos antes de completar una orden.

8. Características de resiliencia
Fallos simulados
Latencia artificial
Comportamiento no determinista