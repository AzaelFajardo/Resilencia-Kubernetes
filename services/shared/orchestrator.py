"""
shared.orchestrator -- Shared order-orchestration module + leader election.

This module was extracted from order-service/main.py (Fase 4: failover real
del orquestador). It is imported by ALL five microservices so that ANY of
them can host the order-orchestration endpoints when it wins the leadership
lease (order-service has the top priority; if it is scaled to 0 in
Kubernetes, payment -> inventory -> user -> notification take over).

The orchestrator endpoints (`/orders`, `/orders/generate`, `/orders/simulate/*`,
`/resilience/*`, `/circuit-breaker/payment`, `/orchestrator/chaos/config`) are
mounted by every service. Only the current leader actually serves them; when a
service is not the leader they answer 503 including the real leader's identity.

Leader election
---------------
A single shared `service_leader` table (same Postgres instance for all 5
services) holds one row per candidate service. Each process heartbeats its own
row in a background task. The leader is the *alive* candidate (heartbeat
fresher than a lease TTL) with the highest priority, tie-broken by node id.
Only the row's current owner may renew it while its lease is valid, so several
replicas of the same Deployment (e.g. HPA-scaled order-service) elect exactly
one orchestrator without flapping.

Election is only enabled inside a Kubernetes pod (KUBERNETES_SERVICE_HOST is
set). Under plain docker-compose the services keep the classic behaviour: no
election and order-service stays the fixed orchestrator.
"""

import asyncio
import concurrent.futures
import logging
import os
import random
import socket
import time
import urllib.parse
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Callable, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from prometheus_client import Gauge
from sqlalchemy import Boolean, Column, DateTime, Enum as SQLEnum, Integer, Numeric, String, Text, delete, desc, func, or_, select, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared ORM models (mapped onto the same tables each service already shares).
# A dedicated Base keeps them independent of any service's own models while
# using the same engine/sessions (they are passed in via OrchestratorConfig).
# ---------------------------------------------------------------------------

SharedBase = declarative_base()


class OrderStatus(str, Enum):
    pending = "pending"
    confirmed = "confirmed"
    processing = "processing"
    paid = "paid"
    shipped = "shipped"
    delivered = "delivered"
    cancelled = "cancelled"
    returned = "returned"


class Order(SharedBase):
    __tablename__ = "orders"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    product_id = Column(Integer, nullable=False, index=True)
    quantity = Column(Integer, nullable=False, default=1)
    total_price = Column(Numeric(12, 2), nullable=False)
    status = Column(
        SQLEnum(OrderStatus, name="order_status", native_enum=True, create_type=False),
        nullable=False,
        default=OrderStatus.pending,
        server_default=text("'pending'"),
    )
    internal_status = Column(String(50), nullable=False, default="awaiting_validation")
    priority = Column(String(20), nullable=False, default="normal")
    is_gift = Column(Boolean, nullable=False, default=False, server_default=text("FALSE"))
    gift_message = Column(Text)
    special_instructions = Column(Text)
    estimated_delivery_at = Column(DateTime(timezone=True))
    warehouse_dispatch_id = Column(PgUUID(as_uuid=True))
    carrier_service_level = Column(String(30), nullable=False, default="standard")
    return_policy_accepted = Column(Boolean, nullable=False, default=True, server_default=text("TRUE"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))


class User(SharedBase):
    """Read-only mapping onto the shared `users` table (JSONB profile)."""
    __tablename__ = "users"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True)
    data = Column(JSONB, nullable=False)


class Product(SharedBase):
    """Read-only mapping onto the shared `products` table (JSONB catalog)."""
    __tablename__ = "products"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True)
    quantity = Column(Integer, nullable=False)
    data = Column(JSONB, nullable=False)


# ---------------------------------------------------------------------------
# Runtime configuration (set by each service's main.py before serving).
# ---------------------------------------------------------------------------

SERVICE_NAME = "order-service"
PRIORITY = 0
_SESSION_FACTORY: Optional[Callable] = None


@dataclass
class OrchestratorConfig:
    service_name: str
    priority: int = 0
    get_db: Optional[Callable] = None
    session_factory: Optional[Callable] = None


def configure(cfg: OrchestratorConfig) -> None:
    global SERVICE_NAME, PRIORITY, _SESSION_FACTORY
    SERVICE_NAME = cfg.service_name
    PRIORITY = int(cfg.priority or 0)
    _SESSION_FACTORY = cfg.session_factory
    configure_election(cfg)


# ---------------------------------------------------------------------------
# Per-process chaos / retry knobs (owned by the orchestrator endpoints).
# ---------------------------------------------------------------------------

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

# Named resilience strategies. Each mode applies retries + circuit breaker as a
# coherent preset and resets this process's orchestrator chaos so it starts clean.
MODE_PRESETS = {
    "baseline": {"retries_enabled": False, "breaker_enabled": False},
    "retries": {"retries_enabled": True, "retries_count": 3, "retries_delay_ms": 100, "breaker_enabled": False},
    "breaker": {"retries_enabled": False, "breaker_enabled": True, "breaker_threshold": 3, "breaker_recovery": 15.0},
}
current_mode = "breaker"


# ---------------------------------------------------------------------------
# Pydantic request/response models.
# ---------------------------------------------------------------------------

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


class OrderGenerateRequest(BaseModel):
    count: int = 1
    user_id: Optional[int] = None
    clients: Optional[int] = None
    orders_per_client: Optional[int] = None
    quantity: int = 1
    product_id: Optional[int] = None


class SimulateStart(BaseModel):
    rate: float = 5.0
    quantity: int = 1
    clients: Optional[int] = None
    duration: Optional[int] = None


class RetriesConfig(BaseModel):
    enabled: Optional[bool] = None
    count: Optional[int] = None
    delay_ms: Optional[int] = None


class CircuitBreakerConfig(BaseModel):
    enabled: Optional[bool] = None
    failure_threshold: Optional[int] = None
    recovery_timeout: Optional[float] = None


class ModeRequest(BaseModel):
    mode: str


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
    timings: dict = {}
    attempts: dict = Field(default_factory=dict)


class CountResponse(BaseModel):
    count: int


class OrderRecordSummary(BaseModel):
    id: int
    user_id: int
    product_id: int
    quantity: int
    total_price: float
    status: str
    internal_status: str
    priority: str
    created_at: Optional[str]
    updated_at: Optional[str]


class OrderStatusUpdate(BaseModel):
    status: Optional[str] = None
    internal_status: Optional[str] = None
    priority: Optional[str] = None


# ---------------------------------------------------------------------------
# Circuit breaker (guards the payment hop of the orchestration flow).
# ---------------------------------------------------------------------------

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
        self.enabled = True
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.state = CircuitBreakerState.CLOSED
        self.failures = 0
        self.last_failure_time = 0.0
        self._lock = asyncio.Lock()
        self._update_metric()

    def configure(self, enabled=None, failure_threshold=None, recovery_timeout=None):
        if enabled is not None:
            self.enabled = bool(enabled)
        if failure_threshold is not None:
            self.failure_threshold = int(failure_threshold)
        if recovery_timeout is not None:
            self.recovery_timeout = float(recovery_timeout)
        self.state = CircuitBreakerState.CLOSED
        self.failures = 0
        self.last_failure_time = 0.0
        self._update_metric()

    def _update_metric(self):
        if not self.enabled:
            cb_state_gauge.labels(service=self.service_name).set(0)
            return
        value = 0
        if self.state == CircuitBreakerState.HALF_OPEN:
            value = 1
        elif self.state == CircuitBreakerState.OPEN:
            value = 2
        cb_state_gauge.labels(service=self.service_name).set(value)

    async def call(self, func, *args, **kwargs):
        if not self.enabled:
            return await func(*args, **kwargs)

        is_probe = False

        async with self._lock:
            if self.state == CircuitBreakerState.OPEN:
                if time.time() - self.last_failure_time > self.recovery_timeout:
                    self.state = CircuitBreakerState.HALF_OPEN
                    is_probe = True
                    self._update_metric()
                else:
                    raise CircuitBreakerError("Circuit is OPEN")
            elif self.state == CircuitBreakerState.HALF_OPEN:
                raise CircuitBreakerError("Circuit is OPEN")

        try:
            result = await func(*args, **kwargs)
        except Exception as exc:
            async with self._lock:
                self.failures += 1
                self.last_failure_time = time.time()
                if is_probe or self.failures >= self.failure_threshold:
                    self.state = CircuitBreakerState.OPEN
                self._update_metric()
            raise exc

        async with self._lock:
            if is_probe or self.state == CircuitBreakerState.HALF_OPEN:
                self.state = CircuitBreakerState.CLOSED
                self.failures = 0
            elif self.state == CircuitBreakerState.CLOSED:
                self.failures = 0
            self._update_metric()

        return result


payment_cb = AsyncCircuitBreaker(
    service_name="payment_service",
    failure_threshold=3,
    recovery_timeout=15.0,
)


# ---------------------------------------------------------------------------
# Fast URL resolution (same in-memory IP cache that bypasses Docker DNS
# timeouts on stopped containers).
# ---------------------------------------------------------------------------

_IP_CACHE: dict[str, str] = {}
_FAILED_RESOLVE: dict[str, float] = {}
_DNS_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=10)


def _getaddrinfo_sync(hostname: str, port: int) -> Optional[str]:
    try:
        infos = socket.getaddrinfo(hostname, port)
        if infos:
            return infos[0][4][0]
    except Exception:
        pass
    return None


def resolve_url(url: str) -> tuple[str, dict]:
    """Fast URL resolver with in-memory IP caching to bypass Docker DNS timeouts on stopped containers."""
    try:
        parsed = urllib.parse.urlsplit(url)
        hostname = parsed.hostname
        if not hostname or hostname in ("localhost", "127.0.0.1") or hostname.replace(".", "").isdigit():
            return url, {}

        port = parsed.port or (80 if parsed.scheme == "http" else 443)
        cached_ip = _IP_CACHE.get(hostname)

        if cached_ip is None and time.time() - _FAILED_RESOLVE.get(hostname, 0.0) > 2.0:
            ip = _getaddrinfo_sync(hostname, port)
            if ip:
                _IP_CACHE[hostname] = ip
                cached_ip = ip
            else:
                # Cache the DNS failure so callers fail fast instead of waiting
                # for the resolver timeout on a stopped container.
                _FAILED_RESOLVE[hostname] = time.time()

        target_ip = cached_ip or "127.0.0.1"
        target_port = port if cached_ip else 1

        netloc = f"{target_ip}:{target_port}"
        new_url = urllib.parse.urlunsplit(
            (parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment)
        )
        headers = {"Host": parsed.netloc}
        return new_url, headers
    except Exception:
        pass

    return url, {}


async def call_service(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    retries: int = 0,
    json_data: Optional[dict] = None,
    track: Optional[list] = None,
) -> httpx.Response:
    last_error = None
    attempts = (max(retries, 0) + 1) if RETRY_ENABLED else 1
    target_url, headers = resolve_url(url)

    for attempt in range(attempts):
        try:
            response = await client.request(method, target_url, headers=headers, timeout=HTTP_TIMEOUT, json=json_data)
        except Exception as exc:
            last_error = exc
            if track is not None:
                track.append({"i": attempt + 1, "ok": False})
            if attempt < attempts - 1:
                await asyncio.sleep(RETRY_DELAY_MS / 1000.0)
            continue

        if response.status_code >= 500 and attempt < attempts - 1:
            if track is not None:
                track.append({"i": attempt + 1, "ok": False})
            await asyncio.sleep(RETRY_DELAY_MS / 1000.0)
            continue

        if track is not None:
            track.append({"i": attempt + 1, "ok": response.status_code < 500})
        return response

    raise last_error


# ---------------------------------------------------------------------------
# Metadata / chaos helpers.
# ---------------------------------------------------------------------------

def build_metadata(request: Optional[Request]) -> RequestMetadata:
    client_ip = "0.0.0.0"
    user_agent = "unknown"
    if request is not None:
        client_ip = request.client.host if request.client else "0.0.0.0"
        user_agent = request.headers.get("user-agent", "unknown")
    return RequestMetadata(
        trace_id=str(uuid.uuid4()),
        request_id=str(uuid.uuid4()),
        source_system=SERVICE_NAME,
        api_version="v1.2.0",
        environment="production",
        timestamp_utc=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        correlation_token=uuid.uuid4().hex,
        client_ip=client_ip,
        user_agent=user_agent,
        tenant_id="TN-MX-001",
    )


def build_security(request: Optional[Request]) -> SecurityContext:
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


def parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def serialize_datetime(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def serialize_order_record(db_order: Order) -> OrderRecordSummary:
    status = db_order.status.value if hasattr(db_order.status, "value") else str(db_order.status)
    return OrderRecordSummary(
        id=int(db_order.id),
        user_id=int(db_order.user_id),
        product_id=int(db_order.product_id),
        quantity=int(db_order.quantity),
        total_price=float(db_order.total_price),
        status=status,
        internal_status=db_order.internal_status,
        priority=db_order.priority,
        created_at=serialize_datetime(db_order.created_at),
        updated_at=serialize_datetime(db_order.updated_at),
    )


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


# ---------------------------------------------------------------------------
# The orchestration flow itself.
# ---------------------------------------------------------------------------

async def _process_order(
    req: OrderRequest,
    request: Optional[Request],
    db: AsyncSession,
    hop_attempts: Optional[dict] = None,
) -> OrderResponse:
    if hop_attempts is None:
        hop_attempts = {}
    await apply_chaos_latency_and_timeout()

    metadata = build_metadata(request)
    security = build_security(request)
    downstream = {
        "user": None,
        "inventory": None,
        "payment": None,
        "notification": None,
    }
    timings: dict[str, int] = {}

    if should_simulate_failure():
        return OrderResponse(
            metadata=metadata,
            security=security,
            status="error",
            message="Order service simulated failure",
            order=build_placeholder_order("service_error"),
            downstream=downstream,
            timings=timings,
        )

    async with httpx.AsyncClient() as client:
        t_user = time.time()
        user_track: list = []
        try:
            user_response = await call_service(
                client,
                "GET",
                f"{USER_SERVICE_URL}/users/{req.user_id}/validate",
                RETRY_COUNT,
                track=user_track,
            )
        except Exception as exc:
            logger.warning("User validation request failed: %s", exc)
            hop_attempts["user"] = user_track
            return OrderResponse(
                metadata=metadata,
                security=security,
                status="error",
                message="User service unavailable",
                order=build_placeholder_order("service_error"),
                downstream=downstream,
            )
        hop_attempts["user"] = user_track

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
        timings["user_ms"] = int((time.time() - t_user) * 1000)

        if not user_data.get("valid"):
            return OrderResponse(
                metadata=metadata,
                security=security,
                status="error",
                message="User validation failed - customer is inactive",
                order=build_placeholder_order("rejected"),
                downstream=downstream,
            )

        t_inventory = time.time()
        inventory_track: list = []
        try:
            inventory_response = await call_service(
                client,
                "GET",
                f"{INVENTORY_SERVICE_URL}/inventory/{req.product_id}/availability",
                RETRY_COUNT,
                track=inventory_track,
            )
        except Exception as exc:
            logger.warning("Inventory availability request failed: %s", exc)
            hop_attempts["inventory"] = inventory_track
            return OrderResponse(
                metadata=metadata,
                security=security,
                status="error",
                message="Inventory service unavailable",
                order=build_placeholder_order("service_error"),
                downstream=downstream,
            )
        hop_attempts["inventory"] = inventory_track

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

        timings["inventory_ms"] = int((time.time() - t_inventory) * 1000)

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

        t_payment = time.time()
        pay_track: list = []
        try:
            async def do_payment():
                attempts = (max(RETRY_COUNT, 0) + 1) if RETRY_ENABLED else 1
                last_error: Optional[DownstreamServiceError] = None

                for attempt in range(attempts):
                    try:
                        response = await call_service(
                            client,
                            "POST",
                            f"{PAYMENT_SERVICE_URL}/pay",
                            0,
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
                    except Exception as exc:
                        last_error = DownstreamServiceError(str(exc), {"status": "error", "message": str(exc)})
                        pay_track.append({"i": attempt + 1, "ok": False})
                    else:
                        if response.status_code >= 400:
                            last_error = DownstreamServiceError(
                                f"Payment service returned status {response.status_code}",
                                {"status": "error", "message": response.text},
                            )
                            pay_track.append({"i": attempt + 1, "ok": False})
                        else:
                            payload = response.json()
                            if payload.get("status") == "success":
                                pay_track.append({"i": attempt + 1, "ok": True})
                                return payload
                            last_error = DownstreamServiceError(
                                payload.get("message", "Payment was rejected"),
                                payload,
                            )
                            pay_track.append({"i": attempt + 1, "ok": False})

                    if attempt < attempts - 1:
                        await asyncio.sleep(RETRY_DELAY_MS / 1000.0)

                raise last_error

            payment_data = await payment_cb.call(do_payment)
            downstream["payment"] = payment_data
        except CircuitBreakerError:
            downstream["payment"] = {"status": "error", "message": "circuit_breaker_open"}
            pay_track.append({"i": 0, "ok": False, "reason": "circuit_breaker_open"})
            payment_error = "Payment circuit breaker is OPEN"
        except DownstreamServiceError as exc:
            downstream["payment"] = exc.payload or {"status": "error", "message": str(exc)}
            payment_error = str(exc)
        except Exception as exc:
            downstream["payment"] = {"status": "error", "message": str(exc)}
            payment_error = str(exc)
        else:
            payment_error = None

        hop_attempts["payment"] = pay_track
        timings["payment_ms"] = int((time.time() - t_payment) * 1000)

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

        t_notification = time.time()
        notif_track: list = []
        try:
            attempts = (max(RETRY_COUNT, 0) + 1) if RETRY_ENABLED else 1
            notification_data = None
            last_notification_error: Optional[DownstreamServiceError] = None

            for attempt in range(attempts):
                try:
                    notification_response = await call_service(
                        client,
                        "POST",
                        f"{NOTIFICATION_SERVICE_URL}/notify",
                        0,
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
                except Exception as exc:
                    last_notification_error = DownstreamServiceError(str(exc), {"status": "error", "message": str(exc)})
                    notif_track.append({"i": attempt + 1, "ok": False})
                else:
                    if notification_response.status_code >= 400:
                        last_notification_error = DownstreamServiceError(
                            f"Notification service returned status {notification_response.status_code}",
                            {"status": "error", "message": notification_response.text},
                        )
                        notif_track.append({"i": attempt + 1, "ok": False})
                    else:
                        payload = notification_response.json()
                        if payload.get("status") == "sent":
                            notif_track.append({"i": attempt + 1, "ok": True})
                            notification_data = payload
                            break
                        last_notification_error = DownstreamServiceError(
                            payload.get("message", "Notification was not delivered"),
                            payload,
                        )
                        notif_track.append({"i": attempt + 1, "ok": False})

                if attempt < attempts - 1:
                    await asyncio.sleep(RETRY_DELAY_MS / 1000.0)

            if notification_data is not None:
                downstream["notification"] = notification_data
            else:
                raise last_notification_error
        except DownstreamServiceError as exc:
            downstream["notification"] = exc.payload or {"status": "error", "message": str(exc)}
            notification_warning = str(exc)
        except Exception as exc:
            downstream["notification"] = {"status": "error", "message": str(exc)}
            notification_warning = str(exc)

        hop_attempts["notification"] = notif_track
        timings["notification_ms"] = int((time.time() - t_notification) * 1000)

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
                timings=timings,
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
        timings=timings,
    )


# ---------------------------------------------------------------------------
# Simulator.
# ---------------------------------------------------------------------------

class SimulatorState:
    def __init__(self):
        self.running = False
        self.task: Optional[asyncio.Task] = None
        self.sent = 0
        self.success = 0
        self.failed = 0
        self.rate = 0.0


simulator = SimulatorState()


async def _simulate_worker(
    rate: float,
    quantity: int,
    user_ids: list[int],
    product_ids: list[int],
    duration: Optional[int],
):
    started = time.time()
    while simulator.running:
        if duration is not None and (time.time() - started) >= duration:
            break

        req = OrderRequest(
            user_id=random.choice(user_ids),
            product_id=random.choice(product_ids),
            quantity=quantity,
        )
        async with _SESSION_FACTORY() as db:
            resp = await _process_order(req, None, db)
        simulator.sent += 1
        if resp.status == "success":
            simulator.success += 1
        else:
            simulator.failed += 1

        delay = 1.0 / rate
        jitter = random.uniform(0.5, 1.5) * delay
        await asyncio.sleep(jitter)

    simulator.running = False


# ---------------------------------------------------------------------------
# Leader election (lease-based, enabled only inside Kubernetes).
# ---------------------------------------------------------------------------

_ELECTION_TABLE = "service_leader"


class LeaderElection:
    def __init__(self, service_name: str, priority: int, heartbeat_seconds: float = 3.0, lease_seconds: float = 12.0):
        self.service_name = service_name
        self.priority = int(priority or 0)
        self.heartbeat_seconds = heartbeat_seconds
        self.lease_seconds = lease_seconds
        self.node_id = str(uuid.uuid4())
        # Kubernetes sets HOSTNAME to the pod name; lets the control-panel route
        # directly to whichever pod holds the leadership lease.
        self.node = os.environ.get("HOSTNAME") or ""

        explicit = os.environ.get("LEADER_ELECTION", "").strip().lower()
        if explicit in ("1", "true", "yes", "on", "enabled"):
            self.enabled = True
        elif explicit in ("0", "false", "no", "off", "disabled"):
            self.enabled = False
        else:
            # Auto: only run elections inside a Kubernetes pod.
            self.enabled = bool(os.environ.get("KUBERNETES_SERVICE_HOST"))

        self.is_leader = not self.enabled
        self.current_leader_service = None
        self.last_heartbeat_at: Optional[datetime] = None

    def status(self) -> dict:
        return {
            "service": self.service_name,
            "node_id": self.node_id,
            "node": self.node,
            "priority": self.priority,
            "enabled": self.enabled,
            "is_leader": self.is_leader,
            "leader_service": self.current_leader_service,
            "heartbeat_seconds": self.heartbeat_seconds,
            "lease_seconds": self.lease_seconds,
            "last_heartbeat_at": serialize_datetime(self.last_heartbeat_at),
        }


ELECTION: LeaderElection = LeaderElection("order-service", 0)


def configure_election(cfg: OrchestratorConfig) -> None:
    global ELECTION
    ELECTION = LeaderElection(cfg.service_name, cfg.priority)
    logger.info(
        "leader election %s for service %s (priority=%s)",
        "enabled" if ELECTION.enabled else "disabled",
        cfg.service_name,
        cfg.priority,
    )


async def _ensure_leader_table(conn) -> None:
    await conn.execute(text(
        f"CREATE TABLE IF NOT EXISTS {_ELECTION_TABLE} ("
        "service_name VARCHAR(50) PRIMARY KEY,"
        "node_id UUID NOT NULL,"
        "priority INTEGER NOT NULL DEFAULT 0,"
        "lease_expires_at TIMESTAMPTZ NOT NULL,"
        "heard_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),"
        "updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"
        ")"
    ))


async def _heartbeat() -> None:
    st = ELECTION
    now = datetime.now(timezone.utc)
    lease_expires = now + timedelta(seconds=st.lease_seconds)
    node_uuid = uuid.UUID(st.node_id)

    async with _SESSION_FACTORY() as session:
        await _ensure_leader_table(session)
        await session.execute(
            text(
                f"INSERT INTO {_ELECTION_TABLE} "
                "(service_name, node_id, priority, lease_expires_at, heard_at, updated_at) "
                "VALUES (:name, :node, :prio, :lease, :now, :now) "
                "ON CONFLICT (service_name) DO UPDATE SET "
                "node_id = EXCLUDED.node_id, "
                "priority = EXCLUDED.priority, "
                "lease_expires_at = EXCLUDED.lease_expires_at, "
                "heard_at = EXCLUDED.heard_at, "
                "updated_at = EXCLUDED.updated_at "
                "WHERE service_leader.node_id = EXCLUDED.node_id "
                "OR service_leader.lease_expires_at <= :now"
            ),
            {
                "name": st.service_name,
                "node": node_uuid,
                "prio": st.priority,
                "lease": lease_expires,
                "now": now,
            },
        )
        await session.commit()

        rows = (
            await session.execute(
                text(
                    f"SELECT service_name, node_id, priority, heard_at "
                    f"FROM {_ELECTION_TABLE}"
                )
            )
        ).all()

    alive = [
        r
        for r in rows
        if r.heard_at is not None and (now - r.heard_at).total_seconds() <= st.lease_seconds
    ]
    if alive:
        winner = min(alive, key=lambda r: (-int(r.priority), str(r.node_id)))
        st.current_leader_service = winner.service_name
        st.is_leader = st.enabled and str(winner.node_id) == st.node_id
    else:
        st.current_leader_service = None
        st.is_leader = not st.enabled

    st.last_heartbeat_at = now


_LEADER_LOOP_TASK: Optional[asyncio.Task] = None


async def _leader_loop() -> None:
    while True:
        try:
            await _heartbeat()
        except Exception:
            logger.exception("leader election heartbeat failed for %s", ELECTION.service_name)
        await asyncio.sleep(ELECTION.heartbeat_seconds)


async def start_leader_loop() -> None:
    global _LEADER_LOOP_TASK
    if not ELECTION.enabled:
        return
    if _LEADER_LOOP_TASK is not None and not _LEADER_LOOP_TASK.done():
        return
    _LEADER_LOOP_TASK = asyncio.create_task(_leader_loop())


async def stop_leader_loop() -> None:
    global _LEADER_LOOP_TASK
    task = _LEADER_LOOP_TASK
    _LEADER_LOOP_TASK = None
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def _db_dependency():
    sf = _SESSION_FACTORY
    async with sf() as session:
        try:
            yield session
        finally:
            await session.close()


def _ensure_leader() -> None:
    if not ELECTION.enabled:
        return
    if ELECTION.is_leader:
        return
    raise HTTPException(
        status_code=503,
        detail={
            "message": "not the current orchestrator leader",
            "leader_service": ELECTION.current_leader_service,
        },
    )


# ---------------------------------------------------------------------------
# Orchestrator router (mounted by every microservice).
# ---------------------------------------------------------------------------

router = APIRouter()


@router.get("/orchestrator/status")
def orchestrator_status():
    return ELECTION.status()


@router.get("/orchestrator/leader")
def orchestrator_leader():
    return ELECTION.status()


@router.get("/orchestrator/chaos/config")
def get_orchestrator_chaos():
    return {
        "FAILURE_RATE": FAILURE_RATE,
        "LATENCY_MS": LATENCY_MS,
        "TIMEOUT_RATE": TIMEOUT_RATE,
    }


@router.post("/orchestrator/chaos/config")
async def update_orchestrator_chaos(config: ChaosConfig):
    return set_orchestrator_chaos(config)


def set_orchestrator_chaos(config: ChaosConfig) -> dict:
    global FAILURE_RATE, LATENCY_MS, TIMEOUT_RATE
    if config.FAILURE_RATE is not None:
        FAILURE_RATE = config.FAILURE_RATE
    if config.LATENCY_MS is not None:
        LATENCY_MS = config.LATENCY_MS
    if config.TIMEOUT_RATE is not None:
        TIMEOUT_RATE = config.TIMEOUT_RATE
    return {
        "message": "Chaos configuration updated",
        "config": get_orchestrator_chaos(),
    }


@router.get("/orders/count", response_model=CountResponse)
async def count_orders(db: AsyncSession = Depends(_db_dependency)) -> CountResponse:
    _ensure_leader()
    await apply_chaos_latency_and_timeout()
    total = await db.scalar(select(func.count()).select_from(Order))
    return CountResponse(count=int(total or 0))


@router.get("/orders/recent", response_model=list[OrderRecordSummary])
async def recent_orders(
    limit: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(_db_dependency),
) -> list[OrderRecordSummary]:
    _ensure_leader()
    await apply_chaos_latency_and_timeout()
    result = await db.execute(
        select(Order).order_by(desc(Order.created_at), desc(Order.id)).limit(limit)
    )
    orders = result.scalars().all()
    return [serialize_order_record(order) for order in orders]


@router.get("/orders", response_model=list[OrderRecordSummary])
async def list_orders(
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=200),
    search: Optional[str] = Query(None, description="Busca por id, usuario o estado"),
    db: AsyncSession = Depends(_db_dependency),
) -> list[OrderRecordSummary]:
    _ensure_leader()
    await apply_chaos_latency_and_timeout()
    stmt = select(Order).order_by(desc(Order.id))
    if search:
        q = f"%{search}%"
        clauses = [
            Order.status.cast(String).ilike(q),
            Order.internal_status.ilike(q),
        ]
        if search.isdigit():
            clauses.append(Order.id == int(search))
            clauses.append(Order.user_id == int(search))
        stmt = stmt.where(or_(*clauses))
    stmt = stmt.offset(offset).limit(limit)
    result = await db.execute(stmt)
    orders = result.scalars().all()
    return [serialize_order_record(order) for order in orders]


@router.get("/orders/{order_id}", response_model=OrderRecordSummary)
async def get_order(order_id: int, db: AsyncSession = Depends(_db_dependency)) -> OrderRecordSummary:
    _ensure_leader()
    await apply_chaos_latency_and_timeout()
    result = await db.execute(select(Order).where(Order.id == order_id))
    db_order = result.scalars().first()
    if db_order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return serialize_order_record(db_order)


@router.patch("/orders/{order_id}/status", response_model=OrderRecordSummary)
async def update_order_status(
    order_id: int,
    update: OrderStatusUpdate,
    db: AsyncSession = Depends(_db_dependency),
) -> OrderRecordSummary:
    _ensure_leader()
    await apply_chaos_latency_and_timeout()
    result = await db.execute(select(Order).where(Order.id == order_id))
    db_order = result.scalars().first()
    if db_order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    if update.status is not None:
        valid_statuses = [status.value for status in OrderStatus]
        if update.status not in valid_statuses:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid status '{update.status}'. Allowed values: {', '.join(valid_statuses)}",
            )
        db_order.status = OrderStatus(update.status)
    if update.internal_status is not None:
        db_order.internal_status = update.internal_status
    if update.priority is not None:
        db_order.priority = update.priority
    db_order.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(db_order)
    return serialize_order_record(db_order)


@router.delete("/orders")
async def clear_all_orders(db: AsyncSession = Depends(_db_dependency)):
    _ensure_leader()
    await apply_chaos_latency_and_timeout()
    result = await db.execute(select(func.count()).select_from(Order))
    count = result.scalar_one()
    await db.execute(delete(Order))
    await db.commit()
    return {"message": "All orders deleted", "count": count}


@router.delete("/orders/{order_id}")
async def delete_order(order_id: int, db: AsyncSession = Depends(_db_dependency)):
    _ensure_leader()
    await apply_chaos_latency_and_timeout()
    result = await db.execute(select(Order).where(Order.id == order_id))
    db_order = result.scalars().first()
    if db_order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    await db.delete(db_order)
    await db.commit()
    return {"message": f"Order {order_id} deleted (payments and notifications removed in cascade)"}


@router.post("/orders")
async def create_order(
    req: OrderRequest,
    request: Request,
    db: AsyncSession = Depends(_db_dependency),
) -> OrderResponse:
    _ensure_leader()
    hop_attempts: dict = {}
    result = await _process_order(req, request, db, hop_attempts)
    if hasattr(result, "model_copy"):
        return result.model_copy(update={"attempts": hop_attempts})
    return result.copy(update={"attempts": hop_attempts})


@router.post("/orders/generate")
async def generate_orders(
    payload: OrderGenerateRequest,
    db: AsyncSession = Depends(_db_dependency),
):
    _ensure_leader()
    await apply_chaos_latency_and_timeout()
    count = max(1, min(payload.count, 100000))
    quantity = max(1, min(payload.quantity, 1000))

    if payload.user_id is not None:
        chosen = [payload.user_id]
    else:
        result = await db.execute(
            select(User.id).where(User.data["active"].astext == "true")
        )
        all_user_ids = [row[0] for row in result.all()]
        if payload.clients is not None and all_user_ids:
            chosen = random.sample(all_user_ids, min(payload.clients, len(all_user_ids)))
        else:
            chosen = all_user_ids

    if payload.product_id is not None:
        product_ids = [payload.product_id]
    else:
        result = await db.execute(select(Product.id).where(Product.quantity > 0))
        product_ids = [row[0] for row in result.all()]

    if not chosen:
        return {"message": "No active users available", "generated": 0, "failed": 0}
    if not product_ids:
        return {"message": "No products in stock to order", "generated": 0, "failed": 0}

    jobs: list[OrderRequest] = []
    if payload.orders_per_client is not None and payload.user_id is None:
        per = max(1, min(payload.orders_per_client, 1000))
        for uid in chosen:
            for _ in range(per):
                jobs.append(OrderRequest(user_id=uid, product_id=random.choice(product_ids), quantity=quantity))
    else:
        for _ in range(count):
            jobs.append(OrderRequest(user_id=random.choice(chosen), product_id=random.choice(product_ids), quantity=quantity))

    generated = 0
    failed = 0
    for req in jobs:
        resp = await _process_order(req, None, db)
        if resp.status == "success":
            generated += 1
        else:
            failed += 1

    return {"count": len(jobs), "generated": generated, "failed": failed}


@router.get("/orders/simulate/status")
def simulate_status():
    return {
        "running": simulator.running,
        "sent": simulator.sent,
        "success": simulator.success,
        "failed": simulator.failed,
        "rate": simulator.rate,
    }


@router.post("/orders/simulate/start")
async def simulate_start(cfg: SimulateStart, db: AsyncSession = Depends(_db_dependency)):
    _ensure_leader()
    if simulator.running:
        return {"message": "Simulation already running", **simulate_status()}

    rate = max(0.1, cfg.rate)
    quantity = max(1, min(cfg.quantity, 1000))

    if cfg.clients is not None:
        result = await db.execute(
            select(User.id).where(User.data["active"].astext == "true").limit(cfg.clients)
        )
        user_ids = [row[0] for row in result.all()]
    else:
        result = await db.execute(
            select(User.id).where(User.data["active"].astext == "true")
        )
        user_ids = [row[0] for row in result.all()]

    result = await db.execute(select(Product.id).where(Product.quantity > 0))
    product_ids = [row[0] for row in result.all()]

    if not user_ids:
        return {"message": "No active users available", "running": False}
    if not product_ids:
        return {"message": "No products in stock to order", "running": False}

    simulator.sent = 0
    simulator.success = 0
    simulator.failed = 0
    simulator.rate = rate
    simulator.running = True
    simulator.task = asyncio.create_task(
        _simulate_worker(rate, quantity, user_ids, product_ids, cfg.duration)
    )
    return {"message": "Simulation started", **simulate_status()}


@router.post("/orders/simulate/stop")
def simulate_stop():
    simulator.running = False
    if simulator.task is not None:
        simulator.task.cancel()
    return {"message": "Simulation stopped", **simulate_status()}


@router.get("/circuit-breaker/payment")
def get_payment_cb_state():
    _ensure_leader()
    return {
        "state": payment_cb.state.value,
        "enabled": payment_cb.enabled,
        "failures": payment_cb.failures,
        "failure_threshold": payment_cb.failure_threshold,
        "recovery_timeout": payment_cb.recovery_timeout,
    }


@router.get("/resilience/mode")
def get_mode():
    _ensure_leader()
    return {
        "mode": current_mode,
        "retries": {"enabled": RETRY_ENABLED, "count": RETRY_COUNT, "delay_ms": RETRY_DELAY_MS},
        "circuit_breaker": {
            "enabled": payment_cb.enabled,
            "failure_threshold": payment_cb.failure_threshold,
            "recovery_timeout": payment_cb.recovery_timeout,
        },
    }


@router.post("/resilience/mode")
def set_mode(req: ModeRequest):
    _ensure_leader()
    global current_mode, RETRY_ENABLED, RETRY_COUNT, RETRY_DELAY_MS
    global FAILURE_RATE, LATENCY_MS, TIMEOUT_RATE

    mode = req.mode.strip().lower()
    if mode not in MODE_PRESETS:
        raise HTTPException(status_code=400, detail=f"Unknown mode '{req.mode}'. Use baseline, retries or breaker.")
    preset = MODE_PRESETS[mode]

    RETRY_ENABLED = preset.get("retries_enabled", False)
    if "retries_count" in preset:
        RETRY_COUNT = preset["retries_count"]
    if "retries_delay_ms" in preset:
        RETRY_DELAY_MS = preset["retries_delay_ms"]

    payment_cb.configure(
        enabled=preset.get("breaker_enabled", False),
        failure_threshold=preset.get("breaker_threshold"),
        recovery_timeout=preset.get("breaker_recovery"),
    )

    FAILURE_RATE = 0.0
    LATENCY_MS = 0
    TIMEOUT_RATE = 0.0

    current_mode = mode
    return get_mode()


@router.get("/resilience/retries")
def get_retries_config():
    _ensure_leader()
    return {
        "enabled": RETRY_ENABLED,
        "count": RETRY_COUNT,
        "delay_ms": RETRY_DELAY_MS,
    }


@router.post("/resilience/retries")
def set_retries_config(config: RetriesConfig):
    _ensure_leader()
    global RETRY_ENABLED, RETRY_COUNT, RETRY_DELAY_MS
    if config.enabled is not None:
        RETRY_ENABLED = config.enabled
    if config.count is not None:
        RETRY_COUNT = config.count
    if config.delay_ms is not None:
        RETRY_DELAY_MS = config.delay_ms
    return {
        "enabled": RETRY_ENABLED,
        "count": RETRY_COUNT,
        "delay_ms": RETRY_DELAY_MS,
    }


@router.get("/resilience/circuit-breaker")
def get_circuit_breaker_config():
    _ensure_leader()
    return {
        "enabled": payment_cb.enabled,
        "failure_threshold": payment_cb.failure_threshold,
        "recovery_timeout": payment_cb.recovery_timeout,
        "state": payment_cb.state.value,
        "failures": payment_cb.failures,
    }


@router.post("/resilience/circuit-breaker")
def set_circuit_breaker_config(config: CircuitBreakerConfig):
    _ensure_leader()
    payment_cb.configure(
        enabled=config.enabled,
        failure_threshold=config.failure_threshold,
        recovery_timeout=config.recovery_timeout,
    )
    return {
        "enabled": payment_cb.enabled,
        "failure_threshold": payment_cb.failure_threshold,
        "recovery_timeout": payment_cb.recovery_timeout,
        "state": payment_cb.state.value,
        "failures": payment_cb.failures,
    }


def build_router() -> APIRouter:
    return router