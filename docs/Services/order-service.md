# Microservice: Order Service

## 1. Description

The Order Service is the main microservice in the system. It is responsible for managing order creation and coordinating communication with other services.

## 2. Objective

Orchestrate the full order flow, integrating payment processing and notification delivery.

## 3. Functionality

This service performs:

- Receipt of order requests
- Communication with the Payment Service
- Communication with the Notification Service
- Error handling

## 4. Available Endpoint

`GET /order`

Description:

Creates an order and executes the full system flow.

## 5. Operation Flow

- The request is received
- A request is sent to the Payment Service
- If the payment fails, an error is returned
- If the payment succeeds, a notification is sent
- The final result is returned

## 6. Possible Responses

Order completed:

```json
{
  "status": "success",
  "message": "Order completed"
}
```

Payment failure:

```json
{
  "status": "error",
  "message": "Payment failed"
}
```

Notification failure:

```json
{
  "status": "warning",
  "message": "Order created but notification failed"
}
```

## 7. Technologies Used

- Python
- FastAPI
- Uvicorn
- HTTPX

## 8. Execution

Local:

```bash
python -m uvicorn main:app --reload --port 8003
```

Docker:

It runs as a container and communicates with other services through the internal network.

## 9. Role in the Architecture

It is the core of the system, responsible for coordinating all processes and ensuring that the business flow runs correctly.

## 10. Error Handling

- Detects failures in the payment service
- Handles communication errors
- Allows partial results
