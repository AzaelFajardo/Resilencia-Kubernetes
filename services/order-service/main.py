from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import asyncio
import logging
import os
import random
import time
import uuid
from enum import Enum
from typing import Optional

import httpx
from fastapi import Depends, FastAPI, Request
from pydantic import BaseModel
from prometheus_client import Gauge
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy.ext.asyncio import AsyncSession

from database import Base, Order, OrderStatus, engine, get_db
from tracing import setup_tracing


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(title="order-service", lifespan=lifespan)
setup_tracing(app, "order-service")
Instrumentator().instrument(app).expose(app)

FAILURE_RATE = float(os.getenv("FAILURE_RATE", "0.0"))
LATENCY_MS = int(os.getenv("LATENCY_MS", "0"))
TIMEOUT_RATE = float(os.getenv("TIMEOUT_RATE", "0.0"))

USER_SERVICE_URL = os.getenv("USER_SERVICE_URL", "http://user-service:8000")
INVENTORY_SERVICE_URL = os.getenv("INVENTORY_SERVICE_URL", "http://inventory-service:8000")
PAYMENT_SERVICE_URL = os.getenv("PAYMENT_SERVICE_URL", "http://payment-service:8000")
NOTIFICATION_SERVICE_URL = os.getenv("NOTIFICATION_SERVICE_URL", "http://notification-service:8000")

RETRY_ENABLED = os.getenv("RETRY_ENABLED", "false").lower() == "true"
RETRY_COUNT = int(os.getenv("RETRY_COUNT", "3"))
RETRY_DELAY_MS = int(os.getenv("RETRY_DELAY_MS", "100"))
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "5.0"))
FRAUD_THRESHOLD = int(os.getenv("FRAUD_THRESHOLD", "70"))


class IpGeolocation(BaseModel):
    city: str
    country: str


class SecurityContext(BaseModel):
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


class OrderDetails(BaseModel):
    id: Optional[int]
    internal_status: str
    priority: str
    is_gift: bool
    gift_message: Optional[str]
    special_instructions: Optional[str]
    estimated_delivery_at: Optional[str]
    warehouse_dispatch_id: Optional[str]
    carrier_service_level: str
    return_policy_accepted: bool


class OrderRequest(BaseModel):
    user_id: int
    product_id: int
    quantity: int


class HealthResponse(BaseModel):
    status: str
    service: str


class ChaosConfig(BaseModel):
    FAILURE_RATE: Optional[float] = None
    LATENCY_MS: Optional[int] = None
    TIMEOUT_RATE: Optional[float] = None


class OrderResponse(BaseModel):
    metadata: RequestMetadata
    security: SecurityContext
    status: str
    message: str
    order: OrderDetails
    downstream: dict


class CircuitBreakerState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreakerError(Exception):
    pass


class DownstreamServiceError(Exception):
    def __init__(self, message: str, payload: Optional[dict] = None):
        super().__init__(message)
        self.payload = payload or {}


cb_state_gauge = Gauge(
    "circuit_breaker_state",
    "State of the circuit breaker (0=CLOSED, 1=HALF_OPEN, 2=OPEN)",
    ["service"],
)


class AsyncCircuitBreaker:
    def __init__(self, service_name: str, failure_threshold: int = 3, recovery_timeout: float = 10.0):
        self.service_name = service_name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.state = CircuitBreakerState.CLOSED
        self.failures = 0
        self.last_failure_time = 0.0
        self._update_metric()

    def _update_metric(self):
        value = 0
        if self.state == CircuitBreakerState.HALF_OPEN:
            value = 1
        elif self.state == CircuitBreakerState.OPEN:
            value = 2
        cb_state_gauge.labels(service=self.service_name).set(value)

    async def call(self, func, *args, **kwargs):
        if self.state == CircuitBreakerState.OPEN:
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = CircuitBreakerState.HALF_OPEN
                self._update_metric()
            else:
                raise CircuitBreakerError("Circuit is OPEN")

        try:
            result = await func(*args, **kwargs)
        except Exception as exc:
            self.failures += 1
            self.last_failure_time = time.time()
            if self.failures >= self.failure_threshold:
                self.state = CircuitBreakerState.OPEN
            self._update_metric()
            raise exc

        if self.state == CircuitBreakerState.HALF_OPEN:
            self.state = CircuitBreakerState.CLOSED
            self.failures = 0
            self._update_metric()
        elif self.state == CircuitBreakerState.CLOSED:
            self.failures = 0
            self._update_metric()

        return result


payment_cb = AsyncCircuitBreaker(
    service_name="payment_service",
    failure_threshold=3,
    recovery_timeout=15.0,
)


def build_metadata(request: Request) -> RequestMetadata:
    return RequestMetadata(
        trace_id=str(uuid.uuid4()),
        request_id=str(uuid.uuid4()),
        source_system="order-service",
        api_version="v1.2.0",
        environment="production",
        timestamp_utc=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        correlation_token=uuid.uuid4().hex,
        client_ip=request.client.host if request.client else "0.0.0.0",
        user_agent=request.headers.get("user-agent", "unknown"),
        tenant_id="TN-MX-001",
    )


def build_security(request: Request) -> SecurityContext:
    return SecurityContext(
        fraud_score=15,
        session_id=str(uuid.uuid4()),
        device_fingerprint=uuid.uuid4().hex,
        ip_geolocation=IpGeolocation(city="Ciudad de Mexico", country="MX"),
        is_authenticated=True,
        auth_method="bearer_token",
        mfa_verified=True,
        vpn_detected=False,
        request_node_id="NODE-ORD-01",
    )


def build_placeholder_order(internal_status: str, priority: str = "none") -> OrderDetails:
    return OrderDetails(
        id=None,
        internal_status=internal_status,
        priority=priority,
        is_gift=False,
        gift_message=None,
        special_instructions=None,
        estimated_delivery_at=None,
        warehouse_dispatch_id=None,
        carrier_service_level="standard",
        return_policy_accepted=False,
    )


def build_order_details(order_id: Optional[int], inv_data: dict, security: SecurityContext) -> OrderDetails:
    item = inv_data.get("item", {})
    dimensions = item.get("dimensions", {})
    weight_kg = item.get("weight_kg", 0)
    warehouse_id = item.get("warehouse_id", "WH-UNKNOWN")
    is_fragile = item.get("is_fragile", False)
    is_heavy = weight_kg > 5.0
    carrier = "specialized" if is_heavy or is_fragile else "standard"
    eta = datetime.now(timezone.utc) + timedelta(days=5 if carrier == "specialized" else 3)
    total_volume = (
        float(dimensions.get("length", 0))
        * float(dimensions.get("width", 0))
        * float(dimensions.get("height", 0))
    )

    return OrderDetails(
        id=order_id,
        internal_status="awaiting_validation",
        priority="high" if security.fraud_score < 20 else "normal",
        is_gift=False,
        gift_message=None,
        special_instructions=(
            f"Total volume: {total_volume:.1f} cm3. "
            f"Handle with {'care' if is_fragile else 'standard procedure'}."
        ),
        estimated_delivery_at=eta.isoformat().replace("+00:00", "Z"),
        warehouse_dispatch_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, warehouse_id)),
        carrier_service_level=carrier,
        return_policy_accepted=True,
    )


async def apply_chaos_latency_and_timeout():
    if LATENCY_MS > 0:
        await asyncio.sleep(LATENCY_MS / 1000.0)

    if TIMEOUT_RATE > 0 and random.random() < TIMEOUT_RATE:
        await asyncio.sleep(30)


def should_simulate_failure() -> bool:
    return FAILURE_RATE > 0 and random.random() < FAILURE_RATE


async def call_service(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    retries: int = 0,
    json_data: Optional[dict] = None,
) -> httpx.Response:
    last_error = None
    attempts = (max(retries, 0) + 1) if RETRY_ENABLED else 1

    for attempt in range(attempts):
        try:
            return await client.request(method, url, timeout=HTTP_TIMEOUT, json=json_data)
        except Exception as exc:
            last_error = exc
            if attempt < attempts - 1:
                await asyncio.sleep(RETRY_DELAY_MS / 1000.0)

    raise last_error


def parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def sync_db_order(
    db_order: Order,
    req: OrderRequest,
    order: OrderDetails,
    total_price: Decimal,
    status: OrderStatus,
):
    db_order.user_id = req.user_id
    db_order.product_id = req.product_id
    db_order.quantity = req.quantity
    db_order.total_price = total_price
    db_order.status = status
    db_order.internal_status = order.internal_status
    db_order.priority = order.priority
    db_order.is_gift = order.is_gift
    db_order.gift_message = order.gift_message
    db_order.special_instructions = order.special_instructions
    db_order.estimated_delivery_at = parse_iso_datetime(order.estimated_delivery_at)
    db_order.warehouse_dispatch_id = (
        uuid.UUID(order.warehouse_dispatch_id) if order.warehouse_dispatch_id else None
    )
    db_order.carrier_service_level = order.carrier_service_level
    db_order.return_policy_accepted = order.return_policy_accepted
    db_order.updated_at = datetime.now(timezone.utc)


async def release_inventory(
    client: httpx.AsyncClient,
    product_id: int,
    quantity: int,
) -> Optional[str]:
    try:
        response = await call_service(
            client,
            "POST",
            f"{INVENTORY_SERVICE_URL}/inventory/{product_id}/release",
            0,
            {"quantity": quantity},
        )
        if response.status_code != 200:
            return f"release returned status {response.status_code}: {response.text}"
    except Exception as exc:
        logger.exception("Inventory release failed for product %s", product_id)
        return str(exc)

    return None


async def persist_order_state(
    db: AsyncSession,
    db_order: Order,
    req: OrderRequest,
    order: OrderDetails,
    total_price: Decimal,
    status: OrderStatus,
):
    sync_db_order(db_order, req, order, total_price, status)
    await db.commit()
    await db.refresh(db_order)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="order-service")


@app.get("/circuit-breaker/payment")
def get_payment_cb_state():
    return {
        "state": payment_cb.state.value,
        "failures": payment_cb.failures,
        "failure_threshold": payment_cb.failure_threshold,
        "recovery_timeout": payment_cb.recovery_timeout,
    }


@app.post("/orders")
async def create_order(
    req: OrderRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> OrderResponse:
    await apply_chaos_latency_and_timeout()

    metadata = build_metadata(request)
    security = build_security(request)
    downstream = {
        "user": None,
        "inventory": None,
        "payment": None,
        "notification": None,
    }

    if should_simulate_failure():
        return OrderResponse(
            metadata=metadata,
            security=security,
            status="error",
            message="Order service simulated failure",
            order=build_placeholder_order("service_error"),
            downstream=downstream,
        )

    async with httpx.AsyncClient() as client:
        try:
            user_response = await call_service(
                client,
                "GET",
                f"{USER_SERVICE_URL}/users/{req.user_id}/validate",
                RETRY_COUNT,
            )
        except Exception as exc:
            logger.warning("User validation request failed: %s", exc)
            return OrderResponse(
                metadata=metadata,
                security=security,
                status="error",
                message="User service unavailable",
                order=build_placeholder_order("service_error"),
                downstream=downstream,
            )

        if user_response.status_code != 200:
            return OrderResponse(
                metadata=metadata,
                security=security,
                status="error",
                message=f"User validation failed with status {user_response.status_code}",
                order=build_placeholder_order("service_error"),
                downstream=downstream,
            )

        user_data = user_response.json()
        downstream["user"] = user_data

        if not user_data.get("valid"):
            return OrderResponse(
                metadata=metadata,
                security=security,
                status="error",
                message="User validation failed - customer is inactive",
                order=build_placeholder_order("rejected"),
                downstream=downstream,
            )

        try:
            inventory_response = await call_service(
                client,
                "GET",
                f"{INVENTORY_SERVICE_URL}/inventory/{req.product_id}/availability",
                RETRY_COUNT,
            )
        except Exception as exc:
            logger.warning("Inventory availability request failed: %s", exc)
            return OrderResponse(
                metadata=metadata,
                security=security,
                status="error",
                message="Inventory service unavailable",
                order=build_placeholder_order("service_error"),
                downstream=downstream,
            )

        if inventory_response.status_code != 200:
            return OrderResponse(
                metadata=metadata,
                security=security,
                status="error",
                message=f"Inventory validation failed with status {inventory_response.status_code}",
                order=build_placeholder_order("service_error"),
                downstream=downstream,
            )

        inventory_data = inventory_response.json()
        downstream["inventory"] = inventory_data
        item = inventory_data.get("item", {})

        if not inventory_data.get("available") or int(item.get("quantity", 0)) < req.quantity:
            return OrderResponse(
                metadata=metadata,
                security=security,
                status="error",
                message="Product not available - out of stock",
                order=build_placeholder_order("out_of_stock"),
                downstream=downstream,
            )

        if security.fraud_score > FRAUD_THRESHOLD:
            return OrderResponse(
                metadata=metadata,
                security=security,
                status="held",
                message=(
                    f"Order held for manual review - fraud_score {security.fraud_score} "
                    f"exceeds threshold {FRAUD_THRESHOLD}"
                ),
                order=build_order_details(None, inventory_data, security),
                downstream=downstream,
            )

        try:
            reserve_response = await call_service(
                client,
                "POST",
                f"{INVENTORY_SERVICE_URL}/inventory/{req.product_id}/reserve",
                RETRY_COUNT,
                {"quantity": req.quantity},
            )
        except Exception as exc:
            logger.warning("Inventory reserve request failed: %s", exc)
            return OrderResponse(
                metadata=metadata,
                security=security,
                status="error",
                message="Inventory service unavailable during reservation",
                order=build_placeholder_order("service_error"),
                downstream=downstream,
            )

        if reserve_response.status_code != 200:
            return OrderResponse(
                metadata=metadata,
                security=security,
                status="error",
                message=f"Failed to reserve inventory: {reserve_response.text}",
                order=build_placeholder_order("reservation_failed"),
                downstream=downstream,
            )

        unit_price = Decimal(str(item.get("unit_price", 0))).quantize(Decimal("0.01"))
        total_amount = (unit_price * req.quantity).quantize(Decimal("0.01"))
        order = build_order_details(None, inventory_data, security)
        order.internal_status = "payment_pending"

        db_order = Order()
        sync_db_order(db_order, req, order, total_amount, OrderStatus.confirmed)

        try:
            db.add(db_order)
            await db.commit()
            await db.refresh(db_order)
        except Exception as exc:
            await db.rollback()
            logger.exception("Initial order persistence failed")
            release_error = await release_inventory(client, req.product_id, req.quantity)
            message = f"Order persistence failed before payment: {exc}"
            if release_error:
                message += f". Inventory release also failed: {release_error}"
            return OrderResponse(
                metadata=metadata,
                security=security,
                status="error",
                message=message,
                order=build_placeholder_order("persistence_error"),
                downstream=downstream,
            )

        order.id = db_order.id
        customer_context = user_data.get("customer", {})

        try:
            async def do_payment():
                response = await call_service(
                    client,
                    "POST",
                    f"{PAYMENT_SERVICE_URL}/pay",
                    RETRY_COUNT,
                    {
                        "order_id": order.id,
                        "amount": float(total_amount),
                        "user_id": req.user_id,
                        "customer": customer_context,
                        "security": {
                            "fraud_score": security.fraud_score,
                            "session_id": security.session_id,
                            "device_fingerprint": security.device_fingerprint,
                            "ip_geolocation": {
                                "city": security.ip_geolocation.city,
                                "country": security.ip_geolocation.country,
                            },
                            "is_authenticated": security.is_authenticated,
                            "auth_method": security.auth_method,
                            "mfa_verified": security.mfa_verified,
                            "vpn_detected": security.vpn_detected,
                            "request_node_id": security.request_node_id,
                        },
                    },
                )
                if response.status_code >= 400:
                    raise DownstreamServiceError(
                        f"Payment service returned status {response.status_code}",
                        {"status": "error", "message": response.text},
                    )

                payload = response.json()
                if payload.get("status") != "success":
                    raise DownstreamServiceError(
                        payload.get("message", "Payment was rejected"),
                        payload,
                    )

                return payload

            payment_data = await payment_cb.call(do_payment)
            downstream["payment"] = payment_data
        except CircuitBreakerError:
            downstream["payment"] = {"status": "error", "message": "circuit_breaker_open"}
            payment_error = "Payment circuit breaker is OPEN"
        except DownstreamServiceError as exc:
            downstream["payment"] = exc.payload or {"status": "error", "message": str(exc)}
            payment_error = str(exc)
        except Exception as exc:
            downstream["payment"] = {"status": "error", "message": str(exc)}
            payment_error = str(exc)
        else:
            payment_error = None

        if payment_error is not None:
            order.internal_status = "payment_failed"
            try:
                await persist_order_state(
                    db,
                    db_order,
                    req,
                    order,
                    total_amount,
                    OrderStatus.cancelled,
                )
            except Exception as exc:
                await db.rollback()
                logger.exception("Failed to persist cancelled order state")
                return OrderResponse(
                    metadata=metadata,
                    security=security,
                    status="error",
                    message=(
                        f"Payment failed and order state could not be updated: {exc}. "
                        f"Original payment error: {payment_error}"
                    ),
                    order=order,
                    downstream=downstream,
                )

            release_error = await release_inventory(client, req.product_id, req.quantity)
            message = f"Payment failed, inventory released: {payment_error}"
            if release_error:
                message += f". Inventory release failed: {release_error}"

            return OrderResponse(
                metadata=metadata,
                security=security,
                status="error",
                message=message,
                order=order,
                downstream=downstream,
            )

        order.internal_status = "payment_verified"
        try:
            await persist_order_state(
                db,
                db_order,
                req,
                order,
                total_amount,
                OrderStatus.paid,
            )
        except Exception as exc:
            await db.rollback()
            logger.exception("Failed to persist paid order state")
            return OrderResponse(
                metadata=metadata,
                security=security,
                status="error",
                message=(
                    f"Payment succeeded but order state update failed: {exc}. "
                    "Manual review required."
                ),
                order=order,
                downstream=downstream,
            )

        first_name = customer_context.get("first_name")
        language_preference = customer_context.get("language_preference")
        notification_warning = None

        try:
            notification_response = await call_service(
                client,
                "POST",
                f"{NOTIFICATION_SERVICE_URL}/notify",
                RETRY_COUNT,
                {
                    "order_id": order.id,
                    "amount": float(total_amount),
                    "user_id": req.user_id,
                    "customer": customer_context,
                    "first_name": first_name,
                    "language_preference": language_preference,
                    "gift_message": order.gift_message,
                },
            )
            if notification_response.status_code >= 400:
                raise DownstreamServiceError(
                    f"Notification service returned status {notification_response.status_code}",
                    {"status": "error", "message": notification_response.text},
                )

            notification_data = notification_response.json()
            downstream["notification"] = notification_data
            if notification_data.get("status") != "sent":
                raise DownstreamServiceError(
                    notification_data.get("message", "Notification was not delivered"),
                    notification_data,
                )
        except DownstreamServiceError as exc:
            downstream["notification"] = exc.payload or {"status": "error", "message": str(exc)}
            notification_warning = str(exc)
        except Exception as exc:
            downstream["notification"] = {"status": "error", "message": str(exc)}
            notification_warning = str(exc)

        if notification_warning is not None:
            order.internal_status = "completed_notification_failed"
            try:
                await persist_order_state(
                    db,
                    db_order,
                    req,
                    order,
                    total_amount,
                    OrderStatus.paid,
                )
            except Exception as exc:
                await db.rollback()
                logger.exception("Failed to persist notification warning state")
                return OrderResponse(
                    metadata=metadata,
                    security=security,
                    status="error",
                    message=(
                        f"Order completed but the warning state could not be persisted: {exc}. "
                        f"Notification issue: {notification_warning}"
                    ),
                    order=order,
                    downstream=downstream,
                )

            return OrderResponse(
                metadata=metadata,
                security=security,
                status="warning",
                message=f"Order completed but notification failed: {notification_warning}",
                order=order,
                downstream=downstream,
            )

        order.internal_status = "completed"
        try:
            await persist_order_state(
                db,
                db_order,
                req,
                order,
                total_amount,
                OrderStatus.paid,
            )
        except Exception as exc:
            await db.rollback()
            logger.exception("Failed to persist completed order state")
            return OrderResponse(
                metadata=metadata,
                security=security,
                status="error",
                message=(
                    f"Order processing finished but the final state could not be persisted: {exc}. "
                    "Manual review required."
                ),
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


@app.post("/chaos/config")
def update_chaos_config(config: ChaosConfig):
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
