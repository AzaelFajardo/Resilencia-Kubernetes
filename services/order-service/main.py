"""
order-service  –  Central order orchestrator microservice.

Acts as the main orchestrator for the order flow, coordinating all
downstream services (user, inventory, payment, notification).

Owns 10 order-specific fields (logistics & metadata) and consumes
fields from other categories:
  - items[].weight_kg        → calculates total weight for carrier
  - items[].dimensions.*     → calculates total dimensions
  - order.carrier_service_level → decides if special carrier needed
  - security.fraud_score     → verifies threshold before payment
  - order.warehouse_dispatch_id → enriched from inventory warehouse_id

Every response includes the 20 global fields (metadata + security).
"""

from fastapi import FastAPI, Request
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta
import uuid
import os
import asyncio
from contextlib import asynccontextmanager
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from database import engine, Base, Order, get_db
# This library automatically collects metrics such as request count, latency, and errors.
from prometheus_fastapi_instrumentator import Instrumentator
import httpx


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield

# ── FastAPI application ────────────────────────────────────────────────
app = FastAPI(title="order-service", lifespan=lifespan)

# Instrument the FastAPI application to automatically collect metrics.
# It tracks HTTP requests, response status codes, and request duration.
# The metrics are exposed at the "/metrics" endpoint for Prometheus to scrape.
Instrumentator().instrument(app).expose(app)

# Base URLs for dependent services.
# They are loaded from Compose or fall back to local defaults.
USER_SERVICE_URL = os.getenv("USER_SERVICE_URL", "http://user-service:8000")
INVENTORY_SERVICE_URL = os.getenv("INVENTORY_SERVICE_URL", "http://inventory-service:8000")
PAYMENT_SERVICE_URL = os.getenv("PAYMENT_SERVICE_URL", "http://payment-service:8000")
NOTIFICATION_SERVICE_URL = os.getenv("NOTIFICATION_SERVICE_URL", "http://notification-service:8000")

# Resilience settings loaded from environment variables.
# These values control retry behavior and outbound request timeouts.
RETRY_ENABLED = os.getenv("RETRY_ENABLED", "false").lower() == "true"
RETRY_COUNT = int(os.getenv("RETRY_COUNT", "3"))
RETRY_DELAY_MS = int(os.getenv("RETRY_DELAY_MS", "100"))
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "5.0"))

# Fraud score threshold — orders above this value are held for review.
FRAUD_THRESHOLD = int(os.getenv("FRAUD_THRESHOLD", "70"))


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
# ORDER-SERVICE MODELS  –  Logistics & Metadata (10 fields)
# ═══════════════════════════════════════════════════════════════════════

class OrderDetails(BaseModel):
    """10 order-specific fields as defined in the spec."""
    id: str
    internal_status: str
    priority: str
    is_gift: bool
    gift_message: Optional[str]
    special_instructions: Optional[str]
    estimated_delivery_at: str
    warehouse_dispatch_id: str
    carrier_service_level: str
    return_policy_accepted: bool


# ── Response models ────────────────────────────────────────────────────

class OrderRequest(BaseModel):
    user_id: int
    product_id: int
    quantity: int

class HealthResponse(BaseModel):
    """Confirms that the service is up and available."""
    status: str
    service: str


class OrderResponse(BaseModel):
    """Full order response envelope with global fields and all downstream data."""
    metadata: RequestMetadata
    security: SecurityContext
    status: str
    message: str
    order: OrderDetails
    downstream: dict


# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════

def build_metadata(request: Request) -> RequestMetadata:
    """Generates the 10 metadata/tracing fields from the incoming request."""
    return RequestMetadata(
        trace_id=str(uuid.uuid4()),
        request_id=str(uuid.uuid4()),
        source_system="order-service",
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
        fraud_score=15,
        session_id=str(uuid.uuid4()),
        device_fingerprint=uuid.uuid4().hex,
        ip_geolocation=IpGeolocation(city="Ciudad de México", country="MX"),
        is_authenticated=True,
        auth_method="bearer_token",
        mfa_verified=True,
        vpn_detected=False,
        request_node_id="NODE-ORD-01",
    )


def build_order_details(
    inv_data: dict,
    security: SecurityContext,
) -> OrderDetails:
    """Builds the 10 order-specific fields, consuming data from other categories.

    Consumes:
      - items[].weight_kg         → calculates carrier requirements
      - items[].dimensions.*      → calculates total dimensions
      - order.carrier_service_level → decides if special carrier needed
      - security.fraud_score      → verified before proceeding to payment
      - inventory.warehouse_id    → enriches warehouse_dispatch_id
    """
    # Extract item data from inventory response to calculate logistics.
    item = inv_data.get("item", {})
    weight_kg = item.get("weight_kg", 0)
    dimensions = item.get("dimensions", {})
    warehouse_id = item.get("warehouse_id", "WH-UNKNOWN")

    # Decide carrier service level based on weight and fragility.
    is_heavy = weight_kg > 5.0
    is_fragile = item.get("is_fragile", False)
    if is_heavy or is_fragile:
        carrier = "specialized"
    else:
        carrier = "standard"

    # Calculate estimated delivery based on carrier level.
    if carrier == "specialized":
        eta = datetime.utcnow() + timedelta(days=5)
    else:
        eta = datetime.utcnow() + timedelta(days=3)

    # Calculate total volume from dimensions.
    total_volume_cm3 = (
        dimensions.get("length", 0)
        * dimensions.get("width", 0)
        * dimensions.get("height", 0)
    )

    return OrderDetails(
        id=f"ORD-{uuid.uuid4().hex[:12].upper()}",
        internal_status="awaiting_validation",
        priority="high" if security.fraud_score < 20 else "normal",
        is_gift=False,
        gift_message=None,
        special_instructions=f"Total volume: {total_volume_cm3:.1f} cm³. Handle with {'care' if is_fragile else 'standard procedure'}.",
        estimated_delivery_at=eta.isoformat() + "Z",
        warehouse_dispatch_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, warehouse_id)),
        carrier_service_level=carrier,
        return_policy_accepted=True,
    )


async def call_service(client: httpx.AsyncClient, method: str, url: str, retries: int = 0, json_data: dict = None) -> httpx.Response:
    """Performs an HTTP request to a service with optional retries."""
    last_error = None
    attempts = retries + 1 if RETRY_ENABLED else 1

    for i in range(attempts):
        try:
            resp = await client.request(method, url, timeout=HTTP_TIMEOUT, json=json_data)
            return resp
        except Exception as e:
            last_error = e
            if i < attempts - 1:
                await asyncio.sleep(RETRY_DELAY_MS / 1000.0)

    raise last_error


# ═══════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════

@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Health endpoint for basic checks."""
    return HealthResponse(status="ok", service="order-service")


@app.post("/orders")
async def create_order(req: OrderRequest, request: Request, db: AsyncSession = Depends(get_db)) -> OrderResponse:
    """Executes the full order flow orchestrating all downstream services.

    Steps:
      1. Build global fields (metadata + security with fraud_score).
      2. Validate the user via user-service (gets 20 customer fields).
      3. Check inventory via inventory-service (gets 25 item fields).
      4. Verify fraud_score threshold before proceeding.
      5. Build order details consuming cross-service fields.
      6. Process payment via payment-service (gets 15 payment fields).
      7. Send notification via notification-service (gets 10 notification fields).
      8. Return full response with all fields from all services.
    """
    metadata = build_metadata(request)
    security = build_security(request)

    downstream = {
        "user": None,
        "inventory": None,
        "payment": None,
        "notification": None,
    }

    async with httpx.AsyncClient() as client:
        # ── Step 1: Validate the user ──────────────────────────────────
        try:
            user_resp = await call_service(
                client, "GET", f"{USER_SERVICE_URL}/users/{req.user_id}/validate", RETRY_COUNT
            )
            user_data = user_resp.json()
            downstream["user"] = user_data

            if not user_data.get("valid"):
                return OrderResponse(
                    metadata=metadata,
                    security=security,
                    status="error",
                    message="User validation failed — customer is inactive",
                    order=OrderDetails(
                        id="N/A", internal_status="rejected", priority="none",
                        is_gift=False, gift_message=None, special_instructions=None,
                        estimated_delivery_at="N/A", warehouse_dispatch_id="N/A",
                        carrier_service_level="none", return_policy_accepted=False,
                    ),
                    downstream=downstream,
                )
        except Exception:
            return OrderResponse(
                metadata=metadata,
                security=security,
                status="error",
                message="User service unavailable",
                order=OrderDetails(
                    id="N/A", internal_status="service_error", priority="none",
                    is_gift=False, gift_message=None, special_instructions=None,
                    estimated_delivery_at="N/A", warehouse_dispatch_id="N/A",
                    carrier_service_level="none", return_policy_accepted=False,
                ),
                downstream=downstream,
            )

        # ── Step 2: Check inventory ────────────────────────────────────
        try:
            inv_resp = await call_service(
                client, "GET", f"{INVENTORY_SERVICE_URL}/inventory/{req.product_id}/availability", RETRY_COUNT
            )
            inv_data = inv_resp.json()
            downstream["inventory"] = inv_data

            if not inv_data.get("available") or inv_data.get("item", {}).get("quantity", 0) < req.quantity:
                return OrderResponse(
                    metadata=metadata,
                    security=security,
                    status="error",
                    message="Product not available — out of stock",
                    order=OrderDetails(
                        id="N/A", internal_status="out_of_stock", priority="none",
                        is_gift=False, gift_message=None, special_instructions=None,
                        estimated_delivery_at="N/A", warehouse_dispatch_id="N/A",
                        carrier_service_level="none", return_policy_accepted=False,
                    ),
                    downstream=downstream,
                )
        except Exception:
            return OrderResponse(
                metadata=metadata,
                security=security,
                status="error",
                message="Inventory service unavailable",
                order=OrderDetails(
                    id="N/A", internal_status="service_error", priority="none",
                    is_gift=False, gift_message=None, special_instructions=None,
                    estimated_delivery_at="N/A", warehouse_dispatch_id="N/A",
                    carrier_service_level="none", return_policy_accepted=False,
                ),
                downstream=downstream,
            )

        # ── Step 3: Fraud threshold check (consumes security.fraud_score) ─
        if security.fraud_score > FRAUD_THRESHOLD:
            return OrderResponse(
                metadata=metadata,
                security=security,
                status="held",
                message=f"Order held for manual review — fraud_score {security.fraud_score} exceeds threshold {FRAUD_THRESHOLD}",
                order=build_order_details(inv_data, security),
                downstream=downstream,
            )

        # ── Step 4: Reserve inventory ──────────────────────────────────
        try:
            reserve_resp = await call_service(
                client, "POST", f"{INVENTORY_SERVICE_URL}/inventory/{req.product_id}/reserve", RETRY_COUNT,
                {"quantity": req.quantity}
            )
            if reserve_resp.status_code != 200:
                return OrderResponse(
                    metadata=metadata,
                    security=security,
                    status="error",
                    message="Failed to reserve inventory",
                    order=build_order_details(inv_data, security),
                    downstream=downstream,
                )
        except Exception:
            return OrderResponse(
                metadata=metadata,
                security=security,
                status="error",
                message="Inventory service unavailable during reservation",
                order=build_order_details(inv_data, security),
                downstream=downstream,
            )

        # ── Step 5: Build order details consuming cross-service fields ─
        order = build_order_details(inv_data, security)
        order.internal_status = "payment_pending"

        # ── Step 6: Process payment ────────────────────────────────────
        unit_price = inv_data.get("item", {}).get("unit_price", 0)
        total_amount = unit_price * req.quantity

        payment_failed = False
        try:
            pay_resp = await call_service(
                client, "POST", f"{PAYMENT_SERVICE_URL}/pay", RETRY_COUNT,
                {"order_id": order.id, "amount": total_amount, "user_id": str(req.user_id)}
            )
            pay_data = pay_resp.json()
            downstream["payment"] = pay_data

            if pay_data.get("status") != "success":
                payment_failed = True
        except Exception:
            payment_failed = True
            
        if payment_failed:
            order.internal_status = "payment_failed"
            # Compensating transaction: Release inventory
            try:
                await call_service(
                    client, "POST", f"{INVENTORY_SERVICE_URL}/inventory/{req.product_id}/release", 0,
                    {"quantity": req.quantity}
                )
            except Exception:
                pass # Log release failure in a real app

            return OrderResponse(
                metadata=metadata,
                security=security,
                status="error",
                message="Payment failed, inventory released",
                order=order,
                downstream=downstream,
            )

        order.internal_status = "payment_verified"

        # ── Step 7: Send notification ──────────────────────────────────
        try:
            notif_resp = await call_service(
                client, "POST", f"{NOTIFICATION_SERVICE_URL}/notify", RETRY_COUNT,
                {"order_id": order.id, "amount": total_amount, "user_id": str(req.user_id)}
            )
            notif_data = notif_resp.json()
            downstream["notification"] = notif_data
        except Exception:
            order.internal_status = "completed_notification_failed"

        # ── Step 8: Save order to DB ───────────────────────────────────
        if order.internal_status == "payment_verified":
            order.internal_status = "completed"
            
        try:
            db_order = Order(
                id=order.id,
                user_id=req.user_id,
                product_id=req.product_id,
                quantity=req.quantity,
                status=order.internal_status,
                data=order.model_dump() if hasattr(order, "model_dump") else order.dict()
            )
            db.add(db_order)
            await db.commit()
        except Exception:
            pass # Depending on requirements we might log this or fail

        if order.internal_status == "completed_notification_failed":
            return OrderResponse(
                metadata=metadata,
                security=security,
                status="warning",
                message="Order completed but notification failed",
                order=order,
                downstream=downstream,
            )

    return OrderResponse(
        metadata=metadata,
        security=security,
        status="success",
        message="Order completed successfully",
        order=order,
        downstream=downstream,
    )
