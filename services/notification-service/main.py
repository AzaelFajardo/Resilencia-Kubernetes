"""
notification-service  –  Notification delivery microservice.

Manages notification preferences and campaign tracking with 10 fields.
Consumes fields from other services to personalize messages:
  - notifications.preferred_channel → decides delivery provider
  - customer.first_name → message personalization
  - customer.language_preference → message language
  - order.gift_message → included in the final message body
Every response includes the 20 global fields (metadata + security).
"""

from fastapi import FastAPI, Request
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import uuid
import os
import random
import asyncio
import httpx
# This library automatically collects metrics such as request count, latency, and errors.
from prometheus_fastapi_instrumentator import Instrumentator


# ── FastAPI application ────────────────────────────────────────────────
app = FastAPI(title="notification-service")

# Instrument the FastAPI application to automatically collect metrics.
# It tracks HTTP requests, response status codes, and request duration.
# The metrics are exposed at the "/metrics" endpoint for Prometheus to scrape.
Instrumentator().instrument(app).expose(app)

# Failure-injection variables loaded from Compose.
# They control simulated errors and added latency.
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
# NOTIFICATION-SERVICE MODELS  –  Notifications & Marketing (10 fields)
# ═══════════════════════════════════════════════════════════════════════

class NotificationDetails(BaseModel):
    """Full notification record with 10 fields as defined in the spec."""
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
    order_id: str
    amount: float
    user_id: str
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

# ── Response models ────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    """Confirms that the service is up and available."""
    status: str
    service: str


class NotificationResponse(BaseModel):
    """Full notification response envelope with global fields."""
    metadata: RequestMetadata
    security: SecurityContext
    status: str
    message: str
    notification: NotificationDetails
    delivery: dict


# ═══════════════════════════════════════════════════════════════════════
# SIMULATED NOTIFICATION DATA
# ═══════════════════════════════════════════════════════════════════════

# Simulated notification that would be assembled from order context.
SIMULATED_NOTIFICATION = NotificationDetails(
    enable_email=True,
    enable_sms=False,
    enable_push=True,
    preferred_channel="email",
    marketing_opt_in=True,
    template_id="TPL-CONF-01",
    tracking_pixel_id=str(uuid.uuid4()),
    campaign_id="CMP-Q2-2026",
    referral_code="REF-ALICE-VIP",
    link_shortener_key="shrt-abc123",
)


# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════

def build_metadata(request: Request) -> RequestMetadata:
    """Generates the 10 metadata/tracing fields from the incoming request."""
    return RequestMetadata(
        trace_id=str(uuid.uuid4()),
        request_id=str(uuid.uuid4()),
        source_system="notification-service",
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
        fraud_score=0,
        session_id=str(uuid.uuid4()),
        device_fingerprint=uuid.uuid4().hex,
        ip_geolocation=IpGeolocation(city="Ciudad de México", country="MX"),
        is_authenticated=True,
        auth_method="service_account",
        mfa_verified=False,
        vpn_detected=False,
        request_node_id="NODE-NTF-01",
    )


def simulate_delivery(notification: NotificationDetails, first_name: str = "Alice", language: str = "es", gift_message: Optional[str] = None) -> dict:
    """Simulates the delivery process based on the preferred_channel field.

    Consumes fields from other categories:
      - notifications.preferred_channel → decides which provider to simulate
      - customer.first_name → personalization (simulated here)
      - customer.language_preference → message language (simulated here)
      - order.gift_message → included in body (simulated here)
    """
    channel = notification.preferred_channel
    provider_map = {
        "email": "SendGrid",
        "sms": "Twilio",
        "push": "Firebase Cloud Messaging",
    }
    return {
        "channel_used": channel,
        "provider": provider_map.get(channel, "unknown"),
        "personalized_greeting": f"Hola {first_name}",
        "language_used": language,
        "gift_message_included": bool(gift_message),
        "template_rendered": notification.template_id,
        "tracking_pixel_embedded": True,
        "short_link_generated": f"https://rsil.ink/{notification.link_shortener_key}",
        "campaign_tracked": notification.campaign_id,
        "delivery_attempt": 1,
    }


# ═══════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════

@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Health endpoint for probes or basic checks."""
    return HealthResponse(status="ok", service="notification-service")


@app.post("/notify")
async def send_notification(req: NotificationRequest, request: Request) -> NotificationResponse:
    """Simulates notification delivery with all 10 fields and consumed fields.

    Steps:
      1. Apply artificial latency (if configured).
      2. Build global fields (metadata + security).
      3. Simulate delivery using preferred_channel and consumed fields.
      4. Simulate controlled failure (if configured).
      5. Return full response with all notification fields.
    """
    # Apply artificial latency when configured.
    if LATENCY_MS > 0:
        await asyncio.sleep(LATENCY_MS / 1000.0)

    metadata = build_metadata(request)
    security = build_security(request)

    customer_data = req.customer or {}
    
    if not customer_data and req.first_name is None and req.language_preference is None:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"http://user-service:8000/users/{req.user_id}", timeout=2.0)
                if resp.status_code == 200:
                    data = resp.json()
                    customer_data = data.get("customer", {})
        except Exception as e:
            print(f"Error fetching user data: {e}")

    notification = SIMULATED_NOTIFICATION
    if req.preferred_channel is not None:
        notification.preferred_channel = req.preferred_channel

    first_name = req.first_name or customer_data.get("first_name", "Alice")
    language = req.language_preference or customer_data.get("language_preference", "es")
    gift_message = req.gift_message

    delivery = simulate_delivery(notification, first_name=first_name, language=language, gift_message=gift_message)

    # Simulate a controlled failure based on the environment variable.
    if FAILURE_RATE > 0 and random.random() < FAILURE_RATE:
        return NotificationResponse(
            metadata=metadata,
            security=security,
            status="error",
            message="Notification delivery failed",
            notification=notification,
            delivery={**delivery, "delivery_attempt": 3, "last_error": "provider_timeout"},
        )

    return NotificationResponse(
        metadata=metadata,
        security=security,
        status="sent",
        message="Notification delivered successfully",
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
            "TIMEOUT_RATE": TIMEOUT_RATE
        }
    }
