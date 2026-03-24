# Microservice: Payment Service

## 1. Description

The Payment Service is a microservice responsible for simulating payment processing within the system. This service includes mechanisms to simulate failures and latency, which is essential for resilience testing.

## 2. Objective

Simulate a critical service that can fail, allowing evaluation of the system behavior when errors occur.

## 3. Functionality

This service allows:

- Processing payment requests
- Simulating delayed responses
- Generating random failures

## 4. Available Endpoint

`GET /pay`

Description:

Processes a payment request in a simulated way.

Behavior:

- There is a 30% probability of failure
- Random latency is introduced

Responses:

Success:

```json
{
  "status": "success",
  "message": "Payment processed"
}
```

Error:

```json
{
  "status": "error",
  "message": "Payment failed"
}
```

## 5. Technologies Used

- Python
- FastAPI
- Uvicorn

## 6. Execution

Local:

```bash
python -m uvicorn main:app --reload --port 8002
```

Docker:

It runs in a container with internal port 8000.

## 7. Role in the Architecture

This service is used by the Order Service to validate and process payments before completing an order.

## 8. Resilience Features

- Simulated failures
- Artificial latency
- Non-deterministic behavior
