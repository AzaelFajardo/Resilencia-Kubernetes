"""
control-panel - Phase 12 Monitor + Operate web interface.

Local study tool, no auth (see docs/ACTION-PLAN.md Phase 12). Talks to the
5 microservices and Prometheus over the internal Docker network. This is a
thin aggregation/proxy layer only - it adds no chaos or business logic of
its own, mirroring cli.py's own "no new HTTP-facing control surface on the
services themselves" rule.

Scope note: covers Monitor (health, resource usage, circuit breaker) and
Operate (place orders, generate data, view recent records, order history,
chaos control) using APIs that already exist. Full CRUD edit/delete for
users/products/orders/payments/notifications was NOT implemented - none of
the 5 microservices expose PUT/DELETE routes today, and adding them was
out of scope for this pass. See README note in this service's directory.
"""
import asyncio
import os
import urllib.parse
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional

app = FastAPI(title="control-panel")

SERVICES = {
    "order": os.getenv("ORDER_SERVICE_URL", "http://order-service:8000"),
    "user": os.getenv("USER_SERVICE_URL", "http://user-service:8000"),
    "inventory": os.getenv("INVENTORY_SERVICE_URL", "http://inventory-service:8000"),
    "payment": os.getenv("PAYMENT_SERVICE_URL", "http://payment-service:8000"),
    "notification": os.getenv("NOTIFICATION_SERVICE_URL", "http://notification-service:8000"),
}
PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://prometheus:9090")
GRAFANA_PUBLIC_URL = os.getenv("GRAFANA_PUBLIC_URL", "http://localhost:3001")
K8S_API_SERVER = os.getenv("K8S_API_SERVER")
K8S_CA = os.getenv("K8S_CA_FILE", "/kube/ca.crt")
K8S_CERT = (
    os.getenv("K8S_CLIENT_CERT_FILE", "/kube/client.crt"),
    os.getenv("K8S_CLIENT_KEY_FILE", "/kube/client.key"),
)

# Runtime target: "compose" talks to the local Docker Compose stack; "kubernetes"
# routes the same service calls through the cluster's API server proxy (services
# and Prometheus are reached via /api/v1/namespaces/default/services/.../proxy).
RUNTIME_MODE = "compose"

_NAMESPACE = "default"


def service_base(key: str) -> str:
    if RUNTIME_MODE == "kubernetes":
        if not K8S_API_SERVER:
            raise HTTPException(status_code=503, detail="Kubernetes not configured")
        return f"{K8S_API_SERVER}/api/v1/namespaces/{_NAMESPACE}/services/{key}-service:8000/proxy"
    return SERVICES[key]


def prometheus_base() -> str:
    if RUNTIME_MODE == "kubernetes":
        if not K8S_API_SERVER:
            raise HTTPException(status_code=503, detail="Kubernetes not configured")
        return f"{K8S_API_SERVER}/api/v1/namespaces/{_NAMESPACE}/services/prometheus:9090/proxy"
    return PROMETHEUS_URL


def _client(**kwargs):
    """HTTP client for service/Prometheus calls, with cluster certs in K8s mode."""
    if RUNTIME_MODE == "kubernetes":
        # verify=False: the cluster cert is issued for the minikube hostname, not
        # for host.docker.internal (local dev cluster, not a real trust boundary).
        return httpx.AsyncClient(cert=K8S_CERT, verify=False, **kwargs)
    return httpx.AsyncClient(**kwargs)


try:
    import docker as docker_sdk
    _docker = docker_sdk.from_env()
except Exception:
    _docker = None


async def _get(client: httpx.AsyncClient, url: str, timeout: float = 5.0):
    try:
        r = await client.get(url, timeout=timeout)
        return r.status_code, (r.json() if r.content else {})
    except Exception as e:
        return 0, {"error": str(e)}


@app.get("/api/health")
async def health():
    """Health of all 5 services, queried in parallel with a short timeout.

    Checking services sequentially meant a single stopped container (whose
    Docker DNS lookup times out rather than refusing the connection) would
    stall the whole snapshot for its full timeout and skew the state of every
    other node. Parallel + short timeout keeps each service's status accurate
    and independent."""
    async with _client() as client:

        async def one(key: str):
            code, body = await _get(client, f"{service_base(key)}/health", timeout=2.0)
            return key, {"up": code == 200, "detail": body}

        results = await asyncio.gather(*(one(key) for key in SERVICES))
        return dict(results)


@app.get("/api/counts")
async def counts():
    endpoints = {"order": "/orders/count", "user": "/users/count", "inventory": "/inventory/count",
                 "payment": "/payments/count", "notification": "/notifications/count"}
    async with _client() as client:

        async def one(key: str):
            code, body = await _get(client, f"{service_base(key)}{endpoints[key]}")
            return key, body.get("count") if code == 200 else None

        results = await asyncio.gather(*(one(key) for key in endpoints))
        return dict(results)


@app.get("/api/resources")
async def resources():
    """Per-service CPU (cores) and RSS memory (MiB), same metrics/queries
    as the Grafana 'Resilencia Overview' dashboard's Resources row."""
    queries = {
        "cpu": 'rate(process_cpu_seconds_total{job="microservices"}[1m])',
        "mem": 'process_resident_memory_bytes{job="microservices"}',
    }
    async with _client() as client:
        results = {}
        for name, q in queries.items():
            code, body = await _get(client, f"{prometheus_base()}/api/v1/query?query={q}")
            results[name] = body.get("data", {}).get("result", []) if code == 200 else []

        by_instance: dict[str, dict] = {}
        for r in results["cpu"]:
            inst = r["metric"].get("instance", "?")
            by_instance.setdefault(inst, {})["cpu_cores"] = float(r["value"][1])
        for r in results["mem"]:
            inst = r["metric"].get("instance", "?")
            by_instance.setdefault(inst, {})["mem_mib"] = round(float(r["value"][1]) / (1024 * 1024), 1)
        return by_instance


@app.get("/api/throughput")
async def throughput():
    """Per-service request rate (req/s) and 5xx error rate, from Prometheus."""
    queries = {
        "rps": 'sum by (instance) (rate(http_requests_total{job="microservices"}[1m]))',
        "errors": 'sum by (instance) (rate(http_requests_total{job="microservices",status=~"5.."}[1m]))',
    }
    async with _client() as client:
        results = {}
        for name, q in queries.items():
            r = await client.get(f"{prometheus_base()}/api/v1/query", params={"query": q}, timeout=5.0)
            body = r.json() if r.status_code == 200 else {}
            results[name] = body.get("data", {}).get("result", [])

        by_inst: dict[str, dict] = {}
        for s in results["rps"]:
            inst = s["metric"].get("instance", "?").split(":")[0]
            by_inst.setdefault(inst, {})["rps"] = round(float(s["value"][1]), 2)
        for s in results["errors"]:
            inst = s["metric"].get("instance", "?").split(":")[0]
            by_inst.setdefault(inst, {})["errors"] = round(float(s["value"][1]), 2)
        for v in by_inst.values():
            rps = v.get("rps", 0) or 0
            errs = v.get("errors", 0) or 0
            v["error_rate"] = round((errs / rps) * 100, 2) if rps else 0.0
        return by_inst


@app.get("/api/targets")
async def targets():
    """Prometheus scrape targets and their health (up/down)."""
    async with _client() as client:
        r = await client.get(f"{prometheus_base()}/api/v1/targets", timeout=5.0)
        if r.status_code != 200:
            raise HTTPException(status_code=502, detail="Prometheus unreachable")
        data = r.json().get("data", {})
        out = []
        for t in data.get("activeTargets", []):
            labels = t.get("labels", {})
            out.append({
                "job": labels.get("job", "?"),
                "instance": labels.get("instance", "?"),
                "health": t.get("health", "unknown"),
            })
        return {"targets": out}


@app.get("/api/config")
async def config():
    return {
        "grafana_url": GRAFANA_PUBLIC_URL,
        "k8s_available": bool(K8S_API_SERVER),
        "runtime_mode": RUNTIME_MODE,
    }


class RuntimeModeRequest(BaseModel):
    mode: str


@app.get("/api/runtime-mode")
def get_runtime_mode():
    return {
        "mode": RUNTIME_MODE,
        "k8s_configured": bool(K8S_API_SERVER),
    }


@app.post("/api/runtime-mode")
def set_runtime_mode(req: RuntimeModeRequest):
    global RUNTIME_MODE
    mode = req.mode.strip().lower()
    if mode not in ("compose", "kubernetes"):
        raise HTTPException(status_code=400, detail="mode must be 'compose' or 'kubernetes'")
    if mode == "kubernetes" and not K8S_API_SERVER:
        raise HTTPException(
            status_code=400,
            detail="Kubernetes not configured (set K8S_API_SERVER and mount certs in k8s/certs/)",
        )
    RUNTIME_MODE = mode
    return get_runtime_mode()


@app.post("/api/services/{service}/{action}")
def service_action(service: str, action: str):
    """Stop/start a microservice container for real (via the Docker socket).

    Sync (not async) on purpose: the Docker SDK calls are blocking, so
    FastAPI runs this endpoint in a worker thread instead of blocking the
    event loop. Stopping a service is reflected across the whole stack
    (health checks fail, the order flow short-circuits, etc.)."""
    if service not in SERVICES:
        raise HTTPException(status_code=400, detail=f"unknown service: {service}")
    if action not in ("stop", "start"):
        raise HTTPException(status_code=400, detail="action must be 'stop' or 'start'")
    if _docker is None:
        raise HTTPException(status_code=503, detail="Docker socket not available")

    name = f"resilencia-kubernetes-{service}-service-1"
    try:
        c = _docker.containers.get(name)
        if action == "stop":
            c.stop()
        else:
            c.start()
        return {"service": service, "action": action, "container": name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{name}: {e}")


@app.get("/api/latency")
async def latency():
    """Per-service latency percentiles (p50/p90/p95/p99/p100) from each
    service's own Prometheus histogram (http_request_duration_seconds).
    p100 is the approximate max (upper bound of the last histogram bucket)."""
    async with _client() as client:
        out = {}
        for key in SERVICES:
            quantiles = {}
            for q, expr in (
                ("p50", f'histogram_quantile(0.50, sum(rate(http_request_duration_seconds_bucket{{job="microservices",instance="{key}-service:8000"}}[5m])) by (le))'),
                ("p90", f'histogram_quantile(0.90, sum(rate(http_request_duration_seconds_bucket{{job="microservices",instance="{key}-service:8000"}}[5m])) by (le))'),
                ("p95", f'histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{{job="microservices",instance="{key}-service:8000"}}[5m])) by (le))'),
                ("p99", f'histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket{{job="microservices",instance="{key}-service:8000"}}[5m])) by (le))'),
                ("p100", f'histogram_quantile(1.0, sum(rate(http_request_duration_seconds_bucket{{job="microservices",instance="{key}-service:8000"}}[5m])) by (le))'),
            ):
                code, body = await _get(client, f"{prometheus_base()}/api/v1/query?query={expr}")
                vals = body.get("data", {}).get("result", []) if code == 200 else []
                quantiles[q] = round(float(vals[0]["value"][1]), 4) if vals else None
            out[key] = quantiles
        return out


@app.get("/api/disk")
def disk():
    """Disk write bytes per service container, read from Docker's own
    blkio cgroup stats via the Docker socket (no Prometheus metric exists
    for this - prometheus_client's ProcessCollector doesn't expose I/O).

    Sync (not async) on purpose: the Docker SDK calls are blocking, so
    FastAPI runs this endpoint in a worker thread instead of blocking the
    event loop (which would stall every other /api/* request)."""
    if _docker is None:
        raise HTTPException(status_code=503, detail="Docker socket not available")
    out = {}
    for svc in SERVICES:
        name = f"resilencia-kubernetes-{svc}-service-1"
        try:
            c = _docker.containers.get(name)
            stats = c.stats(stream=False)
            write_bytes = 0
            entries = (stats.get("blkio_stats", {}) or {}).get("io_service_bytes_recursive") or []
            for e in entries:
                if e.get("op", "").lower() == "write":
                    write_bytes += e.get("value", 0)
            out[svc] = round(write_bytes / (1024 * 1024), 2)
        except Exception:
            out[svc] = None
    return out


@app.get("/api/kubernetes")
async def kubernetes_status():
    if not K8S_API_SERVER:
        raise HTTPException(status_code=503, detail="Kubernetes not configured")
    # verify=False: the cluster cert is issued for the minikube hostname/IP,
    # not for host.docker.internal (the address this container reaches it
    # through) - hostname mismatch is expected here, not a real trust
    # issue, since this is a local-only dev cluster (see docs/00. setup.md).
    async with httpx.AsyncClient(cert=K8S_CERT, verify=False, timeout=5.0) as client:
        try:
            pods_r = await client.get(f"{K8S_API_SERVER}/api/v1/namespaces/default/pods")
            hpa_r = await client.get(f"{K8S_API_SERVER}/apis/autoscaling/v2/namespaces/default/horizontalpodautoscalers")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"cluster unreachable: {e}")

        pods = []
        for item in pods_r.json().get("items", []):
            statuses = item.get("status", {}).get("containerStatuses", [{}])
            cs = statuses[0] if statuses else {}
            ready = cs.get("ready", False)
            restarts = cs.get("restartCount", 0)
            pods.append({
                "name": item["metadata"]["name"],
                "phase": item.get("status", {}).get("phase", "Unknown"),
                "ready": ready,
                "restarts": restarts,
            })

        hpas = []
        for item in hpa_r.json().get("items", []):
            spec = item.get("spec", {})
            status = item.get("status", {})
            current = None
            for m in status.get("currentMetrics", []):
                current = m.get("resource", {}).get("current", {}).get("averageUtilization")
            hpas.append({
                "name": item["metadata"]["name"],
                "minReplicas": spec.get("minReplicas"),
                "maxReplicas": spec.get("maxReplicas"),
                "currentReplicas": status.get("currentReplicas"),
                "currentCPU": current,
                "targetCPU": spec.get("metrics", [{}])[0].get("resource", {}).get("target", {}).get("averageUtilization"),
            })
        return {"pods": pods, "hpas": hpas}


@app.get("/api/alerts")
async def alerts():
    """Prometheus alert rules and their current state (firing/pending/inactive)
    via the /api/v1/rules endpoint."""
    async with _client() as client:
        code, body = await _get(client, f"{prometheus_base()}/api/v1/rules")
        if code != 200:
            return {"groups": [], "error": "Prometheus unreachable"}
        out = []
        for group in body.get("data", {}).get("groups", []):
            for rule in group.get("rules", []):
                if rule.get("type") != "alerting":
                    continue
                out.append({
                    "name": rule.get("name"),
                    "state": rule.get("state"),
                    "health": rule.get("health"),
                    "labels": rule.get("labels", {}),
                    "annotations": rule.get("annotations", {}),
                })
        return {"groups": out}


@app.get("/api/circuit-breaker")
async def circuit_breaker():
    async with _client() as client:
        code, body = await _get(client, f"{service_base('order')}/circuit-breaker/payment")
        if code != 200:
            raise HTTPException(status_code=502, detail="order-service unreachable")
        return body


class ChaosUpdate(BaseModel):
    service: str
    FAILURE_RATE: Optional[float] = None
    LATENCY_MS: Optional[int] = None
    TIMEOUT_RATE: Optional[float] = None


@app.get("/api/chaos/{service}")
async def get_chaos(service: str):
    if service not in SERVICES:
        raise HTTPException(status_code=400, detail=f"unknown service: {service}")
    async with _client() as client:
        r = await client.get(f"{service_base(service)}/chaos/config", timeout=5.0)
        if r.status_code != 200:
            raise HTTPException(status_code=502, detail=f"{service}-service unreachable")
        return r.json()


@app.post("/api/chaos")
async def set_chaos(update: ChaosUpdate):
    if update.service not in SERVICES:
        raise HTTPException(status_code=400, detail=f"unknown service: {update.service}")
    payload = update.model_dump(exclude={"service"}, exclude_none=True)
    async with _client() as client:
        r = await client.post(f"{service_base(update.service)}/chaos/config", json=payload, timeout=5.0)
        return r.json()


@app.get("/api/recent/{entity}")
async def recent(entity: str, limit: int = 10):
    mapping = {
        "users": ("user", "/users/recent"),
        "orders": ("order", "/orders/recent"),
        "payments": ("payment", "/payments/recent"),
        "notifications": ("notification", "/notifications/recent"),
    }
    if entity not in mapping:
        raise HTTPException(status_code=404, detail="unknown entity")
    svc, path = mapping[entity]
    async with _client() as client:
        code, body = await _get(client, f"{service_base(svc)}{path}?limit={limit}")
        if code != 200:
            raise HTTPException(status_code=502, detail=f"{svc}-service unreachable")
        return body


# ── CRUD proxies (Phase 12 completion) ─────────────────────────────────
# Generic write-through proxies to the CRUD endpoints added to each
# microservice (PUT/PATCH/DELETE + paginated list endpoints). The panel is
# still a thin client - all business rules live in the services.

_ENTITY_MAP = {
    "users": "user",
    "products": "inventory",
    "orders": "order",
    "payments": "payment",
    "notifications": "notification",
}


async def _proxy_json(method: str, url: str, body=None, timeout: float = 15.0):
    async with _client() as client:
        r = await client.request(method, url, json=body, timeout=timeout)
    if r.status_code >= 400:
        detail = ""
        try:
            detail = r.json().get("detail", r.text)
        except Exception:
            detail = r.text
        raise HTTPException(status_code=r.status_code, detail=detail)
    try:
        return r.json()
    except Exception:
        return {"raw": r.text}


@app.get("/api/entities/{entity}")
async def list_entity(entity: str, offset: int = 0, limit: int = 20, search: str = ""):
    """Paginated list for an entity, with optional search (id/name/status).
    Uses the paginated+search GET endpoints added in the frontend refactor."""
    svc = _ENTITY_MAP.get(entity)
    if svc is None:
        raise HTTPException(status_code=404, detail="unknown entity")
    qs = f"offset={offset}&limit={limit}"
    if search:
        qs += f"&search={urllib.parse.quote(search)}"
    if entity == "payments":
        path = f"/payments?{qs}"
    elif entity == "notifications":
        path = f"/notifications?{qs}"
    elif entity == "users":
        path = f"/users?{qs}"
    elif entity == "products":
        path = f"/inventory?{qs}"
    else:  # orders
        path = f"/orders?{qs}"
    return await _proxy_json("GET", f"{service_base(svc)}{path}")


@app.post("/api/entities/{entity}")
async def create_entity(entity: str, request: Request):
    svc = _ENTITY_MAP.get(entity)
    if svc is None:
        raise HTTPException(status_code=404, detail="unknown entity")
    body = await request.json()
    path = {"users": "/users", "products": "/inventory", "orders": "/orders"}.get(entity)
    if path is None:
        raise HTTPException(status_code=400, detail=f"manual create not supported for {entity}")
    return await _proxy_json("POST", f"{service_base(svc)}{path}", body=body, timeout=30.0)


@app.patch("/api/entities/{entity}/{item_id}")
async def update_entity(entity: str, item_id: int, request: Request):
    svc = _ENTITY_MAP.get(entity)
    if svc is None:
        raise HTTPException(status_code=404, detail="unknown entity")
    body = await request.json()
    base = f"{service_base(svc)}"
    if entity == "users":
        # UI sends raw profile fields; user-service expects {"data": {...}}.
        path = f"/users/{item_id}"
        body = {"data": body}
    elif entity == "products":
        path = f"/inventory/{item_id}"
        # inventory-service PATCH expects {quantity?, data?}. The UI may send
        # any product field directly: quantity maps to its own column and
        # every other key goes into the JSONB data merge.
        quantity = body.pop("quantity", None)
        patch_body = {"data": body} if body else {}
        if quantity is not None:
            patch_body["quantity"] = quantity
        body = patch_body
    elif entity == "orders":
        # Order edits go through the status endpoint (status/priority/
        # internal_status), the only mutable order fields by design.
        path = f"/orders/{item_id}/status"
    else:
        raise HTTPException(status_code=400, detail=f"edit not supported for {entity}")
    return await _proxy_json("PATCH", f"{base}{path}", body=body)


@app.delete("/api/entities/{entity}/{item_id}")
async def delete_entity(entity: str, item_id: int):
    svc = _ENTITY_MAP.get(entity)
    if svc is None:
        raise HTTPException(status_code=404, detail="unknown entity")
    base = f"{service_base(svc)}"
    path = {
        "users": f"/users/{item_id}",
        "products": f"/inventory/{item_id}",
        "orders": f"/orders/{item_id}",
        "payments": f"/payments/{item_id}",
        "notifications": f"/notifications/{item_id}",
    }[entity]
    return await _proxy_json("DELETE", f"{base}{path}")


@app.get("/api/users/{user_id}/orders")
async def user_orders(user_id: int, limit: int = 20):
    async with _client() as client:
        code, body = await _get(client, f"{service_base('user')}/users/{user_id}/orders?limit={limit}")
        if code == 404:
            raise HTTPException(status_code=404, detail="user not found")
        if code != 200:
            raise HTTPException(status_code=502, detail="user-service unreachable")
        return body


class OrderPlacement(BaseModel):
    user_id: int
    product_id: int
    quantity: int = 1


@app.post("/api/orders")
async def place_order(order: OrderPlacement):
    async with _client() as client:
        r = await client.post(f"{service_base('order')}/orders", json=order.model_dump(), timeout=15.0)
        return r.json()


@app.post("/api/generate/{what}")
async def generate(what: str):
    mapping = {"users": ("user", "/users/generate"), "inventory": ("inventory", "/inventory/generate")}
    if what not in mapping:
        raise HTTPException(status_code=400, detail="must be 'users' or 'inventory'")
    svc, path = mapping[what]
    async with _client() as client:
        r = await client.post(f"{service_base(svc)}{path}", timeout=30.0)
        return r.json()


@app.post("/api/faker/{what}")
async def generate_faker(what: str, count: int = 10):
    """Generate `count` Faker records on demand (users or inventory)."""
    mapping = {"users": ("user", "/users/faker"), "inventory": ("inventory", "/inventory/faker")}
    if what not in mapping:
        raise HTTPException(status_code=400, detail="must be 'users' or 'inventory'")
    svc, path = mapping[what]
    count = max(1, min(count, 100000))
    async with _client() as client:
        r = await client.post(f"{service_base(svc)}{path}?count={count}", timeout=180.0)
        if r.status_code >= 400:
            raise HTTPException(status_code=r.status_code, detail=r.text)
        return r.json()


class OrderGenerate(BaseModel):
    count: int = 1
    user_id: Optional[int] = None
    clients: Optional[int] = None
    orders_per_client: Optional[int] = None
    quantity: int = 1
    product_id: Optional[int] = None


@app.post("/api/orders/generate")
async def generate_orders(gen: OrderGenerate):
    """Bulk-generate orders through the real flow (optionally for one user)."""
    async with _client() as client:
        r = await client.post(
            f"{service_base('order')}/orders/generate", json=gen.model_dump(), timeout=600.0
        )
        if r.status_code >= 400:
            raise HTTPException(status_code=r.status_code, detail=r.text)
        return r.json()


class SimulateStart(BaseModel):
    rate: float = 5.0
    quantity: int = 1
    clients: Optional[int] = None
    duration: Optional[int] = None


@app.get("/api/orders/simulate/status")
async def simulate_status():
    async with _client() as client:
        r = await client.get(f"{service_base('order')}/orders/simulate/status", timeout=5.0)
        if r.status_code != 200:
            raise HTTPException(status_code=502, detail="order-service unreachable")
        return r.json()


@app.post("/api/orders/simulate/start")
async def simulate_start(cfg: SimulateStart):
    async with _client() as client:
        r = await client.post(
            f"{service_base('order')}/orders/simulate/start", json=cfg.model_dump(), timeout=10.0
        )
        if r.status_code >= 400:
            raise HTTPException(status_code=r.status_code, detail=r.text)
        return r.json()


@app.post("/api/orders/simulate/stop")
async def simulate_stop():
    async with _client() as client:
        r = await client.post(f"{service_base('order')}/orders/simulate/stop", timeout=10.0)
        if r.status_code >= 400:
            raise HTTPException(status_code=r.status_code, detail=r.text)
        return r.json()


class RetriesUpdate(BaseModel):
    enabled: Optional[bool] = None
    count: Optional[int] = None
    delay_ms: Optional[int] = None


@app.get("/api/resilience/retries")
async def get_retries():
    async with _client() as client:
        r = await client.get(f"{service_base('order')}/resilience/retries", timeout=5.0)
        if r.status_code != 200:
            raise HTTPException(status_code=502, detail="order-service unreachable")
        return r.json()


@app.post("/api/resilience/retries")
async def set_retries(update: RetriesUpdate):
    async with _client() as client:
        r = await client.post(
            f"{service_base('order')}/resilience/retries",
            json=update.model_dump(exclude_none=True),
            timeout=5.0,
        )
        if r.status_code >= 400:
            raise HTTPException(status_code=r.status_code, detail=r.text)
        return r.json()


class ModeRequest(BaseModel):
    mode: str


@app.get("/api/resilience/mode")
async def get_mode():
    async with _client() as client:
        r = await client.get(f"{service_base('order')}/resilience/mode", timeout=5.0)
        if r.status_code != 200:
            raise HTTPException(status_code=502, detail="order-service unreachable")
        return r.json()


@app.post("/api/resilience/mode")
async def set_mode(req: ModeRequest):
    async with _client() as client:
        r = await client.post(
            f"{service_base('order')}/resilience/mode",
            json=req.model_dump(),
            timeout=5.0,
        )
        if r.status_code >= 400:
            raise HTTPException(status_code=r.status_code, detail=r.text)
        return r.json()


app.mount("/", StaticFiles(directory="static", html=True), name="static")
