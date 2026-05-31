"""
user-service  –  Customer profile microservice.

Manages the full customer profile with 20 fields including nested
shipping address, loyalty program data, and demographic information.
Every response is wrapped with the 20 global fields (metadata + security)
to simulate a production-grade Amazon-like system.
"""

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, date
import uuid
# This library automatically collects metrics such as request count, latency, and errors.
from prometheus_fastapi_instrumentator import Instrumentator


# ── FastAPI application ────────────────────────────────────────────────
app = FastAPI(title="user-service")

# Instrument the FastAPI application to automatically collect metrics.
# It tracks HTTP requests, response status codes, and request duration.
# The metrics are exposed at the "/metrics" endpoint for Prometheus to scrape.
Instrumentator().instrument(app).expose(app)


# ═══════════════════════════════════════════════════════════════════════
# GLOBAL MODELS  –  Metadata & Tracing (10) + Risk & Security (10)
# These 20 fields are included in EVERY response from EVERY service.
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
# USER-SERVICE MODELS  –  Customer Profile (20 fields)
# ═══════════════════════════════════════════════════════════════════════

class ShippingAddress(BaseModel):
    """Nested shipping address with 5 fields."""
    street: str
    city: str
    state: str
    zip: str
    country: str


class Customer(BaseModel):
    """Full customer profile with 20 fields as defined in the spec."""
    id: int
    first_name: str
    last_name: str
    suffix: Optional[str]
    email: str
    phone_number: str
    dob: str
    gender: str
    loyalty_tier: str
    loyalty_points: int
    account_created_at: str
    is_vip: bool
    language_preference: str
    timezone: str
    last_login_at: Optional[str]
    shipping_address: ShippingAddress
    active: bool


# ── Response model for the health endpoint ─────────────────────────────
class HealthResponse(BaseModel):
    """Confirms that the service is up and available."""
    status: str
    service: str


# ── Response model wrapping customer data with global fields ───────────
class CustomerResponse(BaseModel):
    """Full response envelope including metadata, security, and customer data."""
    metadata: RequestMetadata
    security: SecurityContext
    customer: Customer


class CustomerValidationResponse(BaseModel):
    """Validation response with global fields and result details."""
    metadata: RequestMetadata
    security: SecurityContext
    valid: bool
    user_id: int
    message: str
    customer: Customer


# ═══════════════════════════════════════════════════════════════════════
# SIMULATED IN-MEMORY DATA  –  3 customers with all 20 fields
# ═══════════════════════════════════════════════════════════════════════

CUSTOMERS: dict[int, Customer] = {
    1: Customer(
        id=1,
        first_name="Alice",
        last_name="Rodríguez",
        suffix="Sra.",
        email="alice.admin@example.com",
        phone_number="+52-555-0101",
        dob="1988-03-15",
        gender="female",
        loyalty_tier="platinum",
        loyalty_points=15420,
        account_created_at="2024-01-10T08:00:00Z",
        is_vip=True,
        language_preference="es",
        timezone="America/Mexico_City",
        last_login_at="2026-05-28T10:30:00Z",
        shipping_address=ShippingAddress(
            street="Av. Paseo de la Reforma 505, Piso 32",
            city="Ciudad de México",
            state="CDMX",
            zip="06500",
            country="MX",
        ),
        active=True,
    ),
    2: Customer(
        id=2,
        first_name="Carlos",
        last_name="Mendoza",
        suffix=None,
        email="carlos.cliente@example.com",
        phone_number="+52-33-1234-5678",
        dob="1995-07-22",
        gender="male",
        loyalty_tier="gold",
        loyalty_points=4300,
        account_created_at="2025-03-18T12:00:00Z",
        is_vip=False,
        language_preference="es",
        timezone="America/Guadalajara",
        last_login_at="2026-05-29T14:00:00Z",
        shipping_address=ShippingAddress(
            street="Calle Independencia 456, Col. Centro",
            city="Guadalajara",
            state="Jalisco",
            zip="44100",
            country="MX",
        ),
        active=True,
    ),
    3: Customer(
        id=3,
        first_name="Inés",
        last_name="García",
        suffix="Dra.",
        email="ines.inactiva@example.com",
        phone_number="+52-81-9876-5432",
        dob="1979-11-03",
        gender="female",
        loyalty_tier="bronze",
        loyalty_points=120,
        account_created_at="2025-11-01T09:00:00Z",
        is_vip=False,
        language_preference="en",
        timezone="America/Monterrey",
        last_login_at=None,
        shipping_address=ShippingAddress(
            street="Blvd. Antonio L. Rodríguez 789",
            city="Monterrey",
            state="Nuevo León",
            zip="64000",
            country="MX",
        ),
        active=False,
    ),
}


# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════

def build_metadata(request: Request) -> RequestMetadata:
    """Generates the 10 metadata/tracing fields from the incoming request."""
    return RequestMetadata(
        trace_id=str(uuid.uuid4()),
        request_id=str(uuid.uuid4()),
        source_system="user-service",
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
    client_ip = request.client.host if request.client else "0.0.0.0"
    return SecurityContext(
        fraud_score=12,
        session_id=str(uuid.uuid4()),
        device_fingerprint=uuid.uuid4().hex,
        ip_geolocation=IpGeolocation(city="Ciudad de México", country="MX"),
        is_authenticated=True,
        auth_method="bearer_token",
        mfa_verified=True,
        vpn_detected=False,
        request_node_id="NODE-USR-01",
    )


def get_customer_or_404(customer_id: int) -> Customer:
    """Centralizes lookup by ID. Returns 404 if not found."""
    customer = CUSTOMERS.get(customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


# ═══════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════

@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Health endpoint for Kubernetes probes or basic checks."""
    return HealthResponse(status="ok", service="user-service")


@app.get("/users/{user_id}", response_model=CustomerResponse)
def get_user(user_id: int, request: Request) -> CustomerResponse:
    """Retrieves a specific customer by identifier with full profile and global fields."""
    customer = get_customer_or_404(user_id)
    return CustomerResponse(
        metadata=build_metadata(request),
        security=build_security(request),
        customer=customer,
    )


@app.get("/users/{user_id}/validate", response_model=CustomerValidationResponse)
def validate_user(user_id: int, request: Request) -> CustomerValidationResponse:
    """Validates whether a customer exists and is active.
    Returns 200 OK even for inactive users because the validation was resolved.
    Returns 404 only when the customer does not exist."""
    customer = get_customer_or_404(user_id)

    if customer.active:
        return CustomerValidationResponse(
            metadata=build_metadata(request),
            security=build_security(request),
            valid=True,
            user_id=user_id,
            message="Customer is valid and active",
            customer=customer,
        )

    return CustomerValidationResponse(
        metadata=build_metadata(request),
        security=build_security(request),
        valid=False,
        user_id=user_id,
        message="Customer exists but is inactive",
        customer=customer,
    )
