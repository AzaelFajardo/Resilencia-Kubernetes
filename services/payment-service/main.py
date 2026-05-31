"""
payment-service  –  Payment processing microservice.

Manages payment transactions with 15 fields including nested billing
address, card details, coupon handling, and installment tracking.
Consumes security fields (device_fingerprint, vpn_detected) for fraud
assessment. Every response includes the 20 global fields.
"""

from fastapi import FastAPI, Request
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import uuid
import os
import random
import asyncio
# This library automatically collects metrics such as request count, latency, and errors.
from prometheus_fastapi_instrumentator import Instrumentator


# ── FastAPI application ────────────────────────────────────────────────
app = FastAPI(title="payment-service")

# Instrument the FastAPI application to automatically collect metrics.
# It tracks HTTP requests, response status codes, and request duration.
# The metrics are exposed at the "/metrics" endpoint for Prometheus to scrape.
Instrumentator().instrument(app).expose(app)

# Failure-injection variables loaded from Compose.
# They control simulated errors, added latency, and timeouts.
FAILURE_RATE = float(os.getenv("FAILURE_RATE", "0.0"))
LATENCY_MS = int(os.getenv("LATENCY_MS", "0"))
TIMEOUT_RATE = float(os.getenv("TIMEOUT_RATE", "0.0"))


# ═══════════════════════════════════════════════════════════════════════
# GLOBAL MODELS  –  Metadata & Tracing (10) + Risk & Security (10)
# ═══════════════════════════════════════════════════════════════════════

class IpGeolocation(BaseModel):
    """Nested geolocation derived from the client IP address."""
    city: str
    country: str


class SecurityContext(BaseModel):
    """10 security and risk-assessment fields attached to every request."""
    fraud_score: int
    session_id: str
    device_fingerprint: str
    ip_geolocation: IpGeolocation
    is_authenticated: bool
    auth_method: str
    mfa_verified: bool
    vpn_detected: bool
    request_node_id: str


class RequestMetadata(BaseModel):
    """10 metadata and tracing fields attached to every request."""
    trace_id: str
    request_id: str
    source_system: str
    api_version: str
    environment: str
    timestamp_utc: str
    correlation_token: str
    client_ip: str
    user_agent: str
    tenant_id: str


# ═══════════════════════════════════════════════════════════════════════
# PAYMENT-SERVICE MODELS  –  Payment & Billing (15 fields)
# ═══════════════════════════════════════════════════════════════════════

class BillingAddress(BaseModel):
    """Nested billing address with 3 fields."""
    street: str
    city: str
    zip: str


class PaymentDetails(BaseModel):
    """Full payment record with 15 fields as defined in the spec."""
    order_total: float
    subtotal: float
    tax_amount: float
    shipping_cost: float
    currency: str
    method: str
    provider: str
    card_last_four: str
    card_expiry: str
    card_network: str
    billing_address: BillingAddress
    coupon_code: Optional[str]
    installment_count: int


# ── Response models ────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    """Confirms that the service is up and available."""
    status: str
    service: str


class PaymentResponse(BaseModel):
    """Full payment response envelope with global fields and payment data."""
    metadata: RequestMetadata
    security: SecurityContext
    status: str
    message: str
    payment: PaymentDetails
    fraud_check: dict


# ═══════════════════════════════════════════════════════════════════════
# SIMULATED PAYMENT DATA
# ═══════════════════════════════════════════════════════════════════════

# Simulated payment details that would normally come from a payment gateway.
SIMULATED_PAYMENT = PaymentDetails(
    order_total=179.98,
    subtotal=155.16,
    tax_amount=24.82,
    shipping_cost=0.00,
    currency="MXN",
    method="credit_card",
    provider="Banorte Pagos Digitales",
    card_last_four="4532",
    card_expiry="12/28",
    card_network="visa",
    billing_address=BillingAddress(
        street="Av. Paseo de la Reforma 505, Piso 32",
        city="Ciudad de México",
        zip="06500",
    ),
    coupon_code=None,
    installment_count=1,
)


# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════

def build_metadata(request: Request) -> RequestMetadata:
    """Generates the 10 metadata/tracing fields from the incoming request."""
    return RequestMetadata(
        trace_id=str(uuid.uuid4()),
        request_id=str(uuid.uuid4()),
        source_system="payment-service",
        api_version="v1.2.0",
        environment="production",
        timestamp_utc=datetime.utcnow().isoformat() + "Z",
        correlation_token=uuid.uuid4().hex,
        client_ip=request.client.host if request.client else "0.0.0.0",
        user_agent=request.headers.get("user-agent", "unknown"),
        tenant_id="TN-MX-001",
    )


def build_security(request: Request) -> SecurityContext:
    """Generates the 10 security/risk fields from the incoming request."""
    return SecurityContext(
        fraud_score=random.randint(0, 30),
        session_id=str(uuid.uuid4()),
        device_fingerprint=uuid.uuid4().hex,
        ip_geolocation=IpGeolocation(city="Ciudad de México", country="MX"),
        is_authenticated=True,
        auth_method="bearer_token",
        mfa_verified=True,
        vpn_detected=False,
        request_node_id="NODE-PAY-01",
    )


def run_fraud_check(security: SecurityContext, payment: PaymentDetails) -> dict:
    """Simulates a fraud assessment using security fields consumed from other categories.

    Consumes:
      - security.device_fingerprint  → integration check
      - security.vpn_detected        → risk signal
      - payment.coupon_code           → simulated discount validation
      - payment.order_total           → verification after coupon applied
    """
    risk_signals = []

    if security.vpn_detected:
        risk_signals.append("vpn_detected")
    if security.fraud_score > 70:
        risk_signals.append("high_fraud_score")
    if payment.coupon_code and payment.order_total < 10.0:
        risk_signals.append("suspicious_coupon_usage")

    approved = len(risk_signals) == 0
    return {
        "approved": approved,
        "risk_level": "low" if approved else "high",
        "risk_signals": risk_signals,
        "device_fingerprint_verified": True,
        "rules_evaluated": 4,
    }


# ═══════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════

@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Health endpoint for probes or basic checks."""
    return HealthResponse(status="ok", service="payment-service")


@app.get("/pay")
async def process_payment(request: Request) -> PaymentResponse:
    """Simulates payment processing with fraud checks and failure injection.

    Steps:
      1. Apply artificial latency (if configured).
      2. Simulate timeout (if configured).
      3. Build global fields (metadata + security).
      4. Run fraud check consuming security fields.
      5. Simulate controlled failure (if configured).
      6. Return full payment response with all 15 fields.
    """
    # Apply artificial latency when configured.
    if LATENCY_MS > 0:
        await asyncio.sleep(LATENCY_MS / 1000.0)

    # Simulate a timeout when configured.
    if TIMEOUT_RATE > 0 and random.random() < TIMEOUT_RATE:
        await asyncio.sleep(30)

    metadata = build_metadata(request)
    security = build_security(request)
    payment = SIMULATED_PAYMENT
    fraud_result = run_fraud_check(security, payment)

    # Simulate a controlled failure based on the environment variable.
    if FAILURE_RATE > 0 and random.random() < FAILURE_RATE:
        return PaymentResponse(
            metadata=metadata,
            security=security,
            status="error",
            message="Payment declined by processor",
            payment=payment,
            fraud_check=fraud_result,
        )

    return PaymentResponse(
        metadata=metadata,
        security=security,
        status="success",
        message="Payment processed successfully",
        payment=payment,
        fraud_check=fraud_result,
    )
