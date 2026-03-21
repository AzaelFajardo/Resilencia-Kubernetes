Microservicio: Notification Service 

1. Descripción 

El Notification Service es un microservicio encargado de simular el envío de notificaciones dentro del sistema. Su función principal es confirmar eventos generados por otros servicios, como la creación de órdenes. 

 

2. Objetivo 

Proveer un mecanismo simple para el envío de notificaciones, permitiendo completar el flujo de comunicación entre microservicios. 

 

3. Funcionalidad 

Este servicio expone un endpoint HTTP que permite: 

Enviar una notificación 

Retornar una respuesta indicando que la notificación fue entregada 

 

4. Endpoint disponible 

GET /notify 

Descripción: 

Simula el envío de una notificación. 

Respuesta: 

{ 
 "status": "sent", 
 "message": "Notification delivered" 
} 

 

5. Tecnologías utilizadas 

Python 

FastAPI 

Uvicorn 

 

6. Ejecución 

Local: 

python -m uvicorn main:app --reload --port 8001 

Docker: 

El servicio se ejecuta dentro de un contenedor y expone el puerto 8000 internamente. 

 

7. Rol en la arquitectura 

Este microservicio es utilizado por el Order Service para notificar al usuario cuando una orden ha sido procesada. 

 

8. Consideraciones 

No maneja lógica compleja 

No presenta fallos simulados 

Su propósito es representar un servicio externo simple 

 