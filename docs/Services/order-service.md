Microservicio: Order Service
1. Descripción

El Order Service es el microservicio principal del sistema. Se encarga de gestionar la creación de órdenes y coordinar la comunicación con otros servicios.

2. Objetivo

Orquestar el flujo completo de una orden, integrando el procesamiento de pagos y el envío de notificaciones.

3. Funcionalidad

Este servicio realiza:

Recepción de solicitudes de órdenes
Comunicación con el Payment Service
Comunicación con el Notification Service
Manejo de errores
4. Endpoint disponible
GET /order
Descripción:

Crea una orden y ejecuta el flujo completo del sistema.

5. Flujo de operación
Se recibe la solicitud
Se envía petición al Payment Service
Si el pago falla - se retorna error
Si el pago es exitoso - se envía notificación
Se retorna el resultado final
6. Respuestas posibles

Orden completada:

{
  "status": "success",
  "message": "Order completed"
}

Fallo en pago:

{
  "status": "error",
  "message": "Payment failed"
}

Fallo en notificación:

{
  "status": "warning",
  "message": "Order created but notification failed"
}
7. Tecnologías utilizadas
Python
FastAPI
Uvicorn
HTTPX
8. Ejecución
Local:
python -m uvicorn main:app --reload --port 8003
Docker:

Se ejecuta como contenedor y se comunica con otros servicios mediante red interna.

9. Rol en la arquitectura

Es el núcleo del sistema, encargado de coordinar todos los procesos y garantizar que el flujo de negocio se ejecute correctamente.

10. Manejo de errores
Detecta fallos en el servicio de pagos
Maneja errores de comunicación
Permite resultados parciales