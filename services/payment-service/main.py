"""payment-service: simulates and persists payments for orders, including
tax/subtotal computation, a lightweight fraud check, chaos-injection
(latency/timeout/failure) for resilience testing, and the leader-election
orchestrator hook shared across services."""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import asyncio
import logging
import os
import random
import uuid
from typing import Optional

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from pydantic import BaseModel
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import delete, desc, func, select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from database import Base, PaymentRecord, engine, get_db, AsyncSessionLocal
from tracing import setup_tracing

from shared.orchestrator import (
    OrchestratorConfig,
    build_router,
    configure,
    start_leader_loop,
    stop_leader_loop,
)


logger = logging.getLogger(__name__)
TAX_RATE = Decimal("0.16")
ZERO_MONEY = Decimal("0.00")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Creates tables on startup and registers this service with the shared
    orchestrator (leader election) for the duration of the app's lifetime."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    configure(
        OrchestratorConfig(
            service_name="payment-service",
            priority=int(os.getenv("ORCHESTRATOR_PRIORITY", "80")),
            get_db=get_db,
            session_factory=AsyncSessionLocal,
        )
    )
    app.include_router(build_router())
    await start_leader_loop()
    yield
    await stop_leader_loop()


app = FastAPI(title="payment-service", lifespan=lifespan)
setup_tracing(app, "payment-service")
Instrumentator().instrument(app).expose(app)

# Chaos-injection knobs, mutable at runtime via /chaos/config for resilience testing.
FAILURE_RATE = float(os.getenv("FAILURE_RATE", "0.0"))
LATENCY_MS = int(os.getenv("LATENCY_MS", "0"))
TIMEOUT_RATE = float(os.getenv("TIMEOUT_RATE", "0.0"))
USER_SERVICE_URL = os.getenv("USER_SERVICE_URL", "http://user-service:8000")


class IpGeolocation(BaseModel):
    """Nested geolocation derived from the client IP address."""

    city: str
    country: str


class SecurityContext(BaseModel):
    """Security and risk-assessment fields attached to every payment response."""

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
    """Request metadata and tracing fields attached to every payment response."""

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


class BillingAddress(BaseModel):
    """Billing address rendered in the payment response."""

    street: str
    city: str
    zip: str


class PaymentDetails(BaseModel):
    """Simulated payment details returned to the caller and persisted to the database."""

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


class PaymentRequest(BaseModel):
    """Incoming payment request; extra fields are accepted (not validated) so
    upstream callers can pass additional context without breaking this schema."""

    order_id: int
    amount: float
    user_id: int
    customer: Optional[dict] = None
    security: Optional[dict] = None
    device_fingerprint: Optional[str] = None
    vpn_detected: Optional[bool] = None
    coupon_code: Optional[str] = None

    class Config:
        extra = "allow"


class ChaosConfig(BaseModel):
    FAILURE_RATE: Optional[float] = None
    LATENCY_MS: Optional[int] = None
    TIMEOUT_RATE: Optional[float] = None


class HealthResponse(BaseModel):
    """Confirms that the service is up and available."""

    status: str
    service: str


class PaymentResponse(BaseModel):
    """Full response envelope: metadata, security context, fraud check, and payment details."""

    metadata: RequestMetadata
    security: SecurityContext
    status: str
    message: str
    payment: PaymentDetails
    fraud_check: dict


class CountResponse(BaseModel):
    count: int


class PaymentRecordSummary(BaseModel):
    id: int
    order_id: int
    status: str
    order_total: float
    method: str
    created_at: Optional[str]


def model_dump_compat(model) -> dict:
    """Supports both Pydantic v2 (`model_dump`) and v1 (`dict`) APIs."""
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def serialize_datetime(value: Optional[datetime]) -> Optional[str]:
    """Formats a datetime as UTC ISO-8601 with a trailing 'Z', or None if unset."""
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def serialize_payment_record(record: PaymentRecord) -> PaymentRecordSummary:
    """Converts a persisted PaymentRecord row into its API summary representation."""
    return PaymentRecordSummary(
        id=int(record.id),
        order_id=int(record.order_id),
        status=record.status,
        order_total=float(record.order_total),
        method=record.method,
        created_at=serialize_datetime(record.created_at),
    )


def build_metadata(request: Request) -> RequestMetadata:
    """Generates request metadata/tracing fields from the incoming request."""
    return RequestMetadata(
        trace_id=str(uuid.uuid4()),
        request_id=str(uuid.uuid4()),
        source_system="payment-service",
        api_version="v1.2.0",
        environment="production",
        timestamp_utc=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        correlation_token=uuid.uuid4().hex,
        client_ip=request.client.host if request.client else "0.0.0.0",
        user_agent=request.headers.get("user-agent", "unknown"),
        tenant_id="TN-MX-001",
    )


def build_security(request: Request, security_data: Optional[dict] = None) -> SecurityContext:
    """Builds a simulated security context, then overlays any caller-supplied
    security_data fields (e.g. propagated from order/user-service) on top."""
    security = SecurityContext(
        fraud_score=random.randint(0, 30),
        session_id=str(uuid.uuid4()),
        device_fingerprint=uuid.uuid4().hex,
        ip_geolocation=IpGeolocation(city="Ciudad de Mexico", country="MX"),
        is_authenticated=True,
        auth_method="bearer_token",
        mfa_verified=True,
        vpn_detected=False,
        request_node_id="NODE-PAY-01",
    )

    if not security_data:
        return security

    # Overwrite only the fields explicitly provided by the caller, leaving
    # simulated defaults in place for anything omitted.
    for field in (
        "fraud_score",
        "session_id",
        "device_fingerprint",
        "is_authenticated",
        "auth_method",
        "mfa_verified",
        "vpn_detected",
        "request_node_id",
    ):
        if security_data.get(field) is not None:
            setattr(security, field, security_data[field])

    geo = security_data.get("ip_geolocation") or {}
    if geo:
        security.ip_geolocation = IpGeolocation(
            city=geo.get("city", security.ip_geolocation.city),
            country=geo.get("country", security.ip_geolocation.country),
        )

    return security


async def apply_chaos_latency_and_timeout():
    """Injects configured artificial latency and, probabilistically, a long
    stall (simulated timeout) before the request is handled."""
    if LATENCY_MS > 0:
        await asyncio.sleep(LATENCY_MS / 1000.0)

    if TIMEOUT_RATE > 0 and random.random() < TIMEOUT_RATE:
        await asyncio.sleep(30)


def should_simulate_failure() -> bool:
    """Rolls the dice for a chaos-injected payment failure based on FAILURE_RATE."""
    return FAILURE_RATE > 0 and random.random() < FAILURE_RATE


async def fetch_customer_context(user_id: int) -> tuple[dict, dict]:
    """Fetches customer/security context from user-service. Best-effort: any
    failure (timeout, non-200, network error) degrades to empty dicts rather
    than failing the payment."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{USER_SERVICE_URL}/users/{user_id}", timeout=2.0)
        if response.status_code == 200:
            payload = response.json()
            return payload.get("customer", {}), payload.get("security", {})
    except Exception as exc:
        logger.warning("Could not fetch user context for payment: %s", exc)

    return {}, {}


def build_payment_details(order_total: float, customer_data: dict, coupon_code: Optional[str]) -> PaymentDetails:
    """Derives simulated payment details from the order total: backs out
    subtotal/tax assuming order_total is tax-inclusive at TAX_RATE, and
    deterministically derives a fake card/provider from the total and
    customer id so the same inputs always produce the same "card"."""
    order_total_decimal = Decimal(str(order_total)).quantize(Decimal("0.01"))
    # order_total is tax-inclusive; recover subtotal by dividing out (1 + TAX_RATE).
    subtotal = (order_total_decimal / (Decimal("1.00") + TAX_RATE)).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )
    tax_amount = (order_total_decimal - subtotal).quantize(Decimal("0.01"))
    customer_id = int(customer_data.get("id", 0) or 0)
    billing_source = customer_data.get("shipping_address") or {}
    # Deterministic pseudo-random card/expiry derived from amount + customer id
    # (not a real PAN), so repeated requests for the same order look consistent.
    card_seed = int(order_total_decimal * 100) + customer_id
    card_last_four = f"{4000 + (card_seed % 5000):04d}"
    expiry_month = (customer_id % 12) + 1
    expiry_year = 27 + (customer_id % 4)
    method = "credit_card" if order_total_decimal >= Decimal("50.00") else "debit_card"
    provider = "Banorte Pagos Digitales" if method == "credit_card" else "BBVA Bancomer"
    card_network = "visa" if method == "credit_card" else "mastercard"

    return PaymentDetails(
        order_total=float(order_total_decimal),
        subtotal=float(subtotal),
        tax_amount=float(tax_amount),
        shipping_cost=float(ZERO_MONEY),
        currency="MXN",
        method=method,
        provider=provider,
        card_last_four=card_last_four,
        card_expiry=f"{expiry_month:02d}/{expiry_year}",
        card_network=card_network,
        billing_address=BillingAddress(
            street=billing_source.get("street", "Calle sin datos"),
            city=billing_source.get("city", "Ciudad sin datos"),
            zip=billing_source.get("zip", "00000"),
        ),
        coupon_code=coupon_code,
        installment_count=1,
    )


def run_fraud_check(security: SecurityContext, payment: PaymentDetails) -> dict:
    """Evaluates a small set of simulated fraud heuristics; approval requires
    zero triggered risk signals."""
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


async def persist_payment(
    db: AsyncSession,
    req: PaymentRequest,
    payment: PaymentDetails,
    status: str,
):
    """Persists a payment attempt (success, decline, or failure) as a new row;
    every outcome is recorded, not just successful payments."""
    payment_record = PaymentRecord(
        order_id=req.order_id,
        order_total=Decimal(str(payment.order_total)),
        subtotal=Decimal(str(payment.subtotal)),
        tax_amount=Decimal(str(payment.tax_amount)),
        shipping_cost=Decimal(str(payment.shipping_cost)),
        currency=payment.currency,
        method=payment.method,
        provider=payment.provider,
        card_last_four=payment.card_last_four,
        card_expiry=payment.card_expiry,
        card_network=payment.card_network,
        billing_address=model_dump_compat(payment.billing_address),
        coupon_code=payment.coupon_code,
        installment_count=payment.installment_count,
        status=status,
    )
    db.add(payment_record)
    await db.commit()


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Health endpoint for Kubernetes probes or basic checks."""
    return HealthResponse(status="ok", service="payment-service")


@app.get("/payments/count", response_model=CountResponse)
async def count_payments(db: AsyncSession = Depends(get_db)) -> CountResponse:
    """Returns the total number of persisted payment records."""
    await apply_chaos_latency_and_timeout()
    total = await db.scalar(select(func.count()).select_from(PaymentRecord))
    return CountResponse(count=int(total or 0))


@app.get("/payments/recent", response_model=list[PaymentRecordSummary])
async def recent_payments(
    limit: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> list[PaymentRecordSummary]:
    """Returns the most recently created payments, newest first."""
    await apply_chaos_latency_and_timeout()
    result = await db.execute(
        select(PaymentRecord)
        .order_by(desc(PaymentRecord.created_at), desc(PaymentRecord.id))
        .limit(limit)
    )
    records = result.scalars().all()
    return [serialize_payment_record(record) for record in records]


@app.get("/payments", response_model=list[PaymentRecordSummary])
async def list_payments(
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=200),
    search: Optional[str] = Query(None, description="Busca por id de orden, estado o método"),
    db: AsyncSession = Depends(get_db),
) -> list[PaymentRecordSummary]:
    """Lists payments with pagination and an optional free-text search across
    id, order id, status, and method."""
    await apply_chaos_latency_and_timeout()
    stmt = select(PaymentRecord).order_by(PaymentRecord.id.asc())
    if search:
        q = f"%{search}%"
        clauses = [
            PaymentRecord.status.ilike(q),
            PaymentRecord.method.ilike(q),
        ]
        if search.isdigit():
            clauses.append(PaymentRecord.id == int(search))
            clauses.append(PaymentRecord.order_id == int(search))
        stmt = stmt.where(or_(*clauses))
    stmt = stmt.offset(offset).limit(limit)
    result = await db.execute(stmt)
    records = result.scalars().all()
    return [serialize_payment_record(record) for record in records]


@app.delete("/payments")
async def delete_all_payments(db: AsyncSession = Depends(get_db)) -> dict:
    """Deletes ALL payment records."""
    await apply_chaos_latency_and_timeout()
    await db.execute(delete(PaymentRecord))
    await db.commit()
    return {"message": "All payments deleted successfully"}


@app.delete("/payments/{payment_id}")
async def delete_payment(
    payment_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Deletes a single payment by id."""
    await apply_chaos_latency_and_timeout()
    result = await db.execute(
        select(PaymentRecord).where(PaymentRecord.id == payment_id)
    )
    record = result.scalars().first()
    if record is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    await db.delete(record)
    await db.commit()
    return {"message": "Payment deleted successfully", "payment_id": payment_id}


@app.get("/payments/by-order/{order_id}", response_model=PaymentRecordSummary)
async def get_payment_by_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
) -> PaymentRecordSummary:
    """Returns the most recent payment for a given order id."""
    await apply_chaos_latency_and_timeout()
    result = await db.execute(
        select(PaymentRecord)
        .where(PaymentRecord.order_id == order_id)
        .order_by(desc(PaymentRecord.created_at), desc(PaymentRecord.id))
        .limit(1)
    )
    record = result.scalars().first()
    if record is None:
        raise HTTPException(status_code=404, detail="Payment not found for order")
    return serialize_payment_record(record)


@app.post("/pay")
async def process_payment(
    req: PaymentRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> PaymentResponse:
    """Processes a payment for an order: builds payment/security details, runs
    the fraud check and chaos-injected failure roll, then persists the outcome
    regardless of whether it succeeded, was declined, or failed. Fraud decline
    takes priority over the simulated processor failure."""
    await apply_chaos_latency_and_timeout()

    customer_data = req.customer or {}
    security_data = req.security or {}

    # Prefer caller-supplied context; only call out to user-service for
    # whichever piece (customer/security) wasn't already provided.
    if not customer_data or not security_data:
        fetched_customer, fetched_security = await fetch_customer_context(req.user_id)
        if not customer_data:
            customer_data = fetched_customer
        if not security_data:
            security_data = fetched_security

    metadata = build_metadata(request)
    security = build_security(request, security_data)

    if req.device_fingerprint is not None:
        security.device_fingerprint = req.device_fingerprint
    if req.vpn_detected is not None:
        security.vpn_detected = req.vpn_detected

    payment = build_payment_details(req.amount, customer_data, req.coupon_code)
    fraud_result = run_fraud_check(security, payment)
    simulated_failure = should_simulate_failure()

    # Fraud decline is checked first so it isn't masked by a chaos-injected failure.
    if not fraud_result["approved"]:
        response_status = "error"
        message = "Payment declined by fraud rules"
        persistence_status = "declined"
    elif simulated_failure:
        response_status = "error"
        message = "Payment declined by processor"
        persistence_status = "failed"
    else:
        response_status = "success"
        message = "Payment processed successfully"
        persistence_status = "completed"

    try:
        await persist_payment(db, req, payment, persistence_status)
    except Exception as exc:
        await db.rollback()
        logger.exception("Payment persistence failed for order %s", req.order_id)
        raise HTTPException(status_code=500, detail=f"Payment persistence failed: {exc}") from exc

    return PaymentResponse(
        metadata=metadata,
        security=security,
        status=response_status,
        message=message,
        payment=payment,
        fraud_check=fraud_result,
    )


@app.get("/chaos/config")
def get_chaos_config():
    """Returns the current chaos-injection configuration."""
    return {
        "FAILURE_RATE": FAILURE_RATE,
        "LATENCY_MS": LATENCY_MS,
        "TIMEOUT_RATE": TIMEOUT_RATE,
    }


@app.post("/chaos/config")
def update_chaos_config(config: ChaosConfig):
    """Updates chaos-injection settings at runtime; only fields present in the
    request body are changed, others keep their current value."""
    global FAILURE_RATE, LATENCY_MS, TIMEOUT_RATE

    if config.FAILURE_RATE is not None:
        FAILURE_RATE = config.FAILURE_RATE
    if config.LATENCY_MS is not None:
        LATENCY_MS = config.LATENCY_MS
    if config.TIMEOUT_RATE is not None:
        TIMEOUT_RATE = config.TIMEOUT_RATE

    return {
        "message": "Chaos configuration updated",
        "config": {
            "FAILURE_RATE": FAILURE_RATE,
            "LATENCY_MS": LATENCY_MS,
            "TIMEOUT_RATE": TIMEOUT_RATE,
        },
    }
