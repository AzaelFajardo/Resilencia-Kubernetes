from contextlib import asynccontextmanager
from datetime import datetime, timezone
import asyncio
import logging
import os
import random
import uuid
from typing import Optional

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy.ext.asyncio import AsyncSession

from database import Base, NotificationRecord, engine, get_db
from tracing import setup_tracing


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(title="notification-service", lifespan=lifespan)
setup_tracing(app, "notification-service")
Instrumentator().instrument(app).expose(app)

FAILURE_RATE = float(os.getenv("FAILURE_RATE", "0.0"))
LATENCY_MS = int(os.getenv("LATENCY_MS", "0"))
TIMEOUT_RATE = float(os.getenv("TIMEOUT_RATE", "0.0"))
USER_SERVICE_URL = os.getenv("USER_SERVICE_URL", "http://user-service:8000")


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


class NotificationDetails(BaseModel):
    enable_email: bool
    enable_sms: bool
    enable_push: bool
    preferred_channel: str
    marketing_opt_in: bool
    template_id: str
    tracking_pixel_id: str
    campaign_id: str
    referral_code: Optional[str]
    link_shortener_key: str


class NotificationRequest(BaseModel):
    order_id: int
    amount: float
    user_id: int
    customer: Optional[dict] = None
    preferred_channel: Optional[str] = None
    first_name: Optional[str] = None
    language_preference: Optional[str] = None
    gift_message: Optional[str] = None

    class Config:
        extra = "allow"


class ChaosConfig(BaseModel):
    FAILURE_RATE: Optional[float] = None
    LATENCY_MS: Optional[int] = None
    TIMEOUT_RATE: Optional[float] = None


class HealthResponse(BaseModel):
    status: str
    service: str


class NotificationResponse(BaseModel):
    metadata: RequestMetadata
    security: SecurityContext
    status: str
    message: str
    notification: NotificationDetails
    delivery: dict


def build_metadata(request: Request) -> RequestMetadata:
    return RequestMetadata(
        trace_id=str(uuid.uuid4()),
        request_id=str(uuid.uuid4()),
        source_system="notification-service",
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
        fraud_score=0,
        session_id=str(uuid.uuid4()),
        device_fingerprint=uuid.uuid4().hex,
        ip_geolocation=IpGeolocation(city="Ciudad de Mexico", country="MX"),
        is_authenticated=True,
        auth_method="service_account",
        mfa_verified=False,
        vpn_detected=False,
        request_node_id="NODE-NTF-01",
    )


async def apply_chaos_latency_and_timeout():
    if LATENCY_MS > 0:
        await asyncio.sleep(LATENCY_MS / 1000.0)

    if TIMEOUT_RATE > 0 and random.random() < TIMEOUT_RATE:
        await asyncio.sleep(30)


def should_simulate_failure() -> bool:
    return FAILURE_RATE > 0 and random.random() < FAILURE_RATE


async def fetch_customer_context(user_id: int) -> dict:
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{USER_SERVICE_URL}/users/{user_id}", timeout=2.0)
        if response.status_code == 200:
            payload = response.json()
            return payload.get("customer", {})
    except Exception as exc:
        logger.warning("Could not fetch user context for notification: %s", exc)

    return {}


def build_notification_details(preferred_channel: Optional[str], customer_data: dict) -> NotificationDetails:
    channel = preferred_channel or "email"
    template_id = {
        "email": "TPL-CONF-01",
        "sms": "TPL-SMS-01",
        "push": "TPL-PUSH-01",
        "in_app": "TPL-INAPP-01",
    }.get(channel, "TPL-CONF-01")
    referral_code = None
    if customer_data.get("is_vip"):
        referral_code = f"REF-VIP-{customer_data.get('id', '000')}"

    return NotificationDetails(
        enable_email=True,
        enable_sms=channel == "sms",
        enable_push=channel in {"push", "in_app"},
        preferred_channel=channel,
        marketing_opt_in=bool(customer_data.get("is_vip", False)),
        template_id=template_id,
        tracking_pixel_id=str(uuid.uuid4()),
        campaign_id="CMP-ORDER-2026",
        referral_code=referral_code,
        link_shortener_key=f"shrt-{uuid.uuid4().hex[:6]}",
    )


def simulate_delivery(
    notification: NotificationDetails,
    first_name: str,
    language: str,
    gift_message: Optional[str],
) -> dict:
    provider_map = {
        "email": "SendGrid",
        "sms": "Twilio",
        "push": "Firebase Cloud Messaging",
        "in_app": "Internal Notification Hub",
    }
    greeting = "Hola" if language == "es" else "Hello"
    return {
        "channel_used": notification.preferred_channel,
        "provider": provider_map.get(notification.preferred_channel, "unknown"),
        "personalized_greeting": f"{greeting} {first_name}",
        "language_used": language,
        "gift_message_included": bool(gift_message),
        "template_rendered": notification.template_id,
        "tracking_pixel_embedded": True,
        "short_link_generated": f"https://rsil.ink/{notification.link_shortener_key}",
        "campaign_tracked": notification.campaign_id,
        "delivery_attempt": 1,
    }


async def persist_notification(
    db: AsyncSession,
    req: NotificationRequest,
    notification: NotificationDetails,
    status: str,
):
    sent_at = datetime.now(timezone.utc) if status == "sent" else None
    record = NotificationRecord(
        order_id=req.order_id,
        user_id=req.user_id,
        enable_email=notification.enable_email,
        enable_sms=notification.enable_sms,
        enable_push=notification.enable_push,
        preferred_channel=notification.preferred_channel,
        marketing_opt_in=notification.marketing_opt_in,
        template_id=notification.template_id,
        tracking_pixel_id=uuid.UUID(notification.tracking_pixel_id),
        campaign_id=notification.campaign_id,
        referral_code=notification.referral_code,
        link_shortener_key=notification.link_shortener_key,
        status=status,
        sent_at=sent_at,
    )
    db.add(record)
    await db.commit()


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="notification-service")


@app.post("/notify")
async def send_notification(
    req: NotificationRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> NotificationResponse:
    await apply_chaos_latency_and_timeout()

    metadata = build_metadata(request)
    security = build_security(request)
    customer_data = req.customer or {}

    if not customer_data:
        customer_data = await fetch_customer_context(req.user_id)

    first_name = req.first_name or customer_data.get("first_name", "Cliente")
    language = req.language_preference or customer_data.get("language_preference", "es")
    notification = build_notification_details(req.preferred_channel, customer_data)
    delivery = simulate_delivery(notification, first_name, language, req.gift_message)

    if should_simulate_failure():
        response_status = "error"
        message = "Notification delivery failed"
        persistence_status = "failed"
        delivery = {
            **delivery,
            "delivery_attempt": 3,
            "last_error": "provider_timeout",
        }
    else:
        response_status = "sent"
        message = "Notification delivered successfully"
        persistence_status = "sent"

    try:
        await persist_notification(db, req, notification, persistence_status)
    except Exception as exc:
        await db.rollback()
        logger.exception("Notification persistence failed for order %s", req.order_id)
        raise HTTPException(status_code=500, detail=f"Notification persistence failed: {exc}") from exc

    return NotificationResponse(
        metadata=metadata,
        security=security,
        status=response_status,
        message=message,
        notification=notification,
        delivery=delivery,
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
