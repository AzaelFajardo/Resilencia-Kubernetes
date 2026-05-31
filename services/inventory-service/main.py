"""
inventory-service  –  Product catalog and inventory microservice.

Manages the full product catalog with 25 fields including nested
dimensions, supplier info, material details, and subscription flags.
Every response is wrapped with the 20 global fields (metadata + security)
to simulate a production-grade Amazon-like system.
"""

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import uuid
# This library automatically collects metrics such as request count, latency, and errors.
from prometheus_fastapi_instrumentator import Instrumentator


# ── FastAPI application ────────────────────────────────────────────────
app = FastAPI(title="inventory-service")

# Instrument the FastAPI application to automatically collect metrics.
# It tracks HTTP requests, response status codes, and request duration.
# The metrics are exposed at the "/metrics" endpoint for Prometheus to scrape.
Instrumentator().instrument(app).expose(app)


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
# INVENTORY-SERVICE MODELS  –  Product & Inventory (25 fields)
# ═══════════════════════════════════════════════════════════════════════

class Dimensions(BaseModel):
    """Nested product dimensions in centimeters."""
    length: float
    width: float
    height: float


class Product(BaseModel):
    """Full product / inventory item with 25 fields as defined in the spec."""
    product_id: int
    name: str
    category: str
    quantity: int
    unit_price: float
    weight_kg: float
    dimensions: Dimensions
    is_fragile: bool
    requires_refrigeration: bool
    warehouse_id: str
    supplier_id: str
    discount_applied: float
    tax_rate: float
    currency: str
    manufacturer: str
    ean13: str
    stock_at_ordering: int
    estimated_restock_date: Optional[str]
    material: str
    color: str
    size: str
    warranty_period_months: int
    is_subscription: bool


# ── Response models ────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    """Confirms that the service is up and available."""
    status: str
    service: str


class ProductResponse(BaseModel):
    """Full response envelope with global fields and product data."""
    metadata: RequestMetadata
    security: SecurityContext
    item: Product


class ProductAvailabilityResponse(BaseModel):
    """Availability check response with global fields and result details."""
    metadata: RequestMetadata
    security: SecurityContext
    available: bool
    product_id: int
    message: str
    item: Product


# ═══════════════════════════════════════════════════════════════════════
# SIMULATED IN-MEMORY DATA  –  3 products with all 25 fields
# ═══════════════════════════════════════════════════════════════════════

PRODUCTS: dict[int, Product] = {
    1: Product(
        product_id=1,
        name="Teclado Mecánico RGB Pro",
        category="electronics",
        quantity=12,
        unit_price=89.99,
        weight_kg=1.25,
        dimensions=Dimensions(length=44.0, width=14.5, height=3.8),
        is_fragile=False,
        requires_refrigeration=False,
        warehouse_id="WH-CDMX-01",
        supplier_id="SUP-TECH-42",
        discount_applied=0.0,
        tax_rate=0.16,
        currency="MXN",
        manufacturer="KeyTech Industries S.A. de C.V.",
        ean13="7501234567890",
        stock_at_ordering=12,
        estimated_restock_date="2026-07-15",
        material="aluminum",
        color="matte_black",
        size="full_size",
        warranty_period_months=24,
        is_subscription=False,
    ),
    2: Product(
        product_id=2,
        name="Mouse Inalámbrico Ergonómico",
        category="electronics",
        quantity=0,
        unit_price=29.99,
        weight_kg=0.085,
        dimensions=Dimensions(length=12.4, width=6.8, height=4.0),
        is_fragile=False,
        requires_refrigeration=False,
        warehouse_id="WH-GDL-03",
        supplier_id="SUP-PERI-18",
        discount_applied=10.0,
        tax_rate=0.16,
        currency="MXN",
        manufacturer="ErgoPoint Labs",
        ean13="7509876543210",
        stock_at_ordering=0,
        estimated_restock_date="2026-06-20",
        material="recycled_plastic",
        color="silver",
        size="standard",
        warranty_period_months=12,
        is_subscription=False,
    ),
    3: Product(
        product_id=3,
        name="Docking Station USB-C Premium",
        category="electronics",
        quantity=4,
        unit_price=119.50,
        weight_kg=0.34,
        dimensions=Dimensions(length=20.0, width=8.5, height=2.5),
        is_fragile=True,
        requires_refrigeration=False,
        warehouse_id="WH-CDMX-01",
        supplier_id="SUP-TECH-42",
        discount_applied=5.0,
        tax_rate=0.16,
        currency="MXN",
        manufacturer="ConnectPro México",
        ean13="7505551234567",
        stock_at_ordering=4,
        estimated_restock_date="2026-08-01",
        material="aluminum",
        color="space_gray",
        size="compact",
        warranty_period_months=36,
        is_subscription=False,
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
        source_system="inventory-service",
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
        fraud_score=5,
        session_id=str(uuid.uuid4()),
        device_fingerprint=uuid.uuid4().hex,
        ip_geolocation=IpGeolocation(city="Ciudad de México", country="MX"),
        is_authenticated=True,
        auth_method="bearer_token",
        mfa_verified=True,
        vpn_detected=False,
        request_node_id="NODE-INV-01",
    )


def get_product_or_404(product_id: int) -> Product:
    """Centralizes lookup by ID. Returns 404 if not found."""
    product = PRODUCTS.get(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


# ═══════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════

@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Health endpoint for Kubernetes probes or basic checks."""
    return HealthResponse(status="ok", service="inventory-service")


@app.get("/inventory/{product_id}", response_model=ProductResponse)
def get_product(product_id: int, request: Request) -> ProductResponse:
    """Retrieves a product by ID with full details and global fields."""
    product = get_product_or_404(product_id)
    return ProductResponse(
        metadata=build_metadata(request),
        security=build_security(request),
        item=product,
    )


@app.get(
    "/inventory/{product_id}/availability",
    response_model=ProductAvailabilityResponse,
)
def check_availability(
    product_id: int, request: Request
) -> ProductAvailabilityResponse:
    """Checks whether a product exists and has stock available.
    Returns 200 OK even for out-of-stock items because the query was resolved.
    Returns 404 only when the product does not exist."""
    product = get_product_or_404(product_id)

    if product.quantity > 0:
        return ProductAvailabilityResponse(
            metadata=build_metadata(request),
            security=build_security(request),
            available=True,
            product_id=product_id,
            message="Product is available",
            item=product,
        )

    return ProductAvailabilityResponse(
        metadata=build_metadata(request),
        security=build_security(request),
        available=False,
        product_id=product_id,
        message="Product is out of stock",
        item=product,
    )
