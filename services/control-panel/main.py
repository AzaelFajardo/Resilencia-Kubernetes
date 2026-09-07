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
import os
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
K8S_CERT = ("/kube/client.crt", "/kube/client.key")
K8S_CA = "/kube/ca.crt"

try:
    import docker as docker_sdk
    _docker = docker_sdk.from_env()
except Exception:
    _docker = None


async def _get(client: httpx.AsyncClient, url: str):
    try:
        r = await client.get(url, timeout=5.0)
        return r.status_code, (r.json() if r.content else {})
    except Exception as e:
        return 0, {"error": str(e)}


@app.get("/api/health")
async def health():
    async with httpx.AsyncClient() as client:
        out = {}
        for key, base in SERVICES.items():
            code, body = await _get(client, f"{base}/health")
            out[key] = {"up": code == 200, "detail": body}
        return out


@app.get("/api/counts")
async def counts():
    endpoints = {"order": "/orders/count", "user": "/users/count", "inventory": "/inventory/count",
                 "payment": "/payments/count", "notification": "/notifications/count"}
    async with httpx.AsyncClient() as client:
        out = {}
        for key, path in endpoints.items():
            code, body = await _get(client, f"{SERVICES[key]}{path}")
            out[key] = body.get("count") if code == 200 else None
        return out


@app.get("/api/resources")
async def resources():
    """Per-service CPU (cores) and RSS memory (MiB), same metrics/queries
    as the Grafana 'Resilencia Overview' dashboard's Resources row."""
    queries = {
        "cpu": 'rate(process_cpu_seconds_total{job="microservices"}[1m])',
        "mem": 'process_resident_memory_bytes{job="microservices"}',
    }
    async with httpx.AsyncClient() as client:
        results = {}
        for name, q in queries.items():
            code, body = await _get(client, f"{PROMETHEUS_URL}/api/v1/query?query={q}")
            results[name] = body.get("data", {}).get("result", []) if code == 200 else []

        by_instance: dict[str, dict] = {}
        for r in results["cpu"]:
            inst = r["metric"].get("instance", "?")
            by_instance.setdefault(inst, {})["cpu_cores"] = float(r["value"][1])
        for r in results["mem"]:
            inst = r["metric"].get("instance", "?")
            by_instance.setdefault(inst, {})["mem_mib"] = round(float(r["value"][1]) / (1024 * 1024), 1)
        return by_instance


@app.get("/api/config")
async def config():
    return {"grafana_url": GRAFANA_PUBLIC_URL, "k8s_available": bool(K8S_API_SERVER)}


@app.get("/api/latency")
async def latency():
    """Per-service latency percentiles (p50/p95/p99) from each service's own
    Prometheus histogram (http_request_duration_seconds), not just
    order-service's. Query params are URL-encoded inside PromQL; instance
    labels are <service>:8000 per the scrape config."""
    async with httpx.AsyncClient() as client:
        out = {}
        for key in SERVICES:
            quantiles = {}
            for q, expr in (
                ("p50", f'histogram_quantile(0.50, sum(rate(http_request_duration_seconds_bucket{{job="microservices",instance="{key}-service:8000"}}[5m])) by (le))'),
                ("p95", f'histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{{job="microservices",instance="{key}-service:8000"}}[5m])) by (le))'),
                ("p99", f'histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket{{job="microservices",instance="{key}-service:8000"}}[5m])) by (le))'),
            ):
                code, body = await _get(client, f"{PROMETHEUS_URL}/api/v1/query?query={expr}")
                vals = body.get("data", {}).get("result", []) if code == 200 else []
                quantiles[q] = round(float(vals[0]["value"][1]), 4) if vals else None
            out[key] = quantiles
        return out


@app.get("/api/disk")
async def disk():
    """Disk write bytes per service container, read from Docker's own
    blkio cgroup stats via the Docker socket (no Prometheus metric exists
    for this - prometheus_client's ProcessCollector doesn't expose I/O)."""
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
    async with httpx.AsyncClient() as client:
        code, body = await _get(client, f"{PROMETHEUS_URL}/api/v1/rules")
        if code != 200:
            return {"groups": [], "error": "Prometheus unreachable"}
        out = []
        for group in body.get("data", {}).get("groups", []):
            for rule in group.get("rules", []):
                if rule.get("type") != "alert":
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
    async with httpx.AsyncClient() as client:
        code, body = await _get(client, f"{SERVICES['order']}/circuit-breaker/payment")
        if code != 200:
            raise HTTPException(status_code=502, detail="order-service unreachable")
        return body


class ChaosUpdate(BaseModel):
    service: str
    FAILURE_RATE: Optional[float] = None
    LATENCY_MS: Optional[int] = None
    TIMEOUT_RATE: Optional[float] = None


@app.post("/api/chaos")
async def set_chaos(update: ChaosUpdate):
    if update.service not in SERVICES:
        raise HTTPException(status_code=400, detail=f"unknown service: {update.service}")
    payload = update.model_dump(exclude={"service"}, exclude_none=True)
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{SERVICES[update.service]}/chaos/config", json=payload, timeout=5.0)
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
    async with httpx.AsyncClient() as client:
        code, body = await _get(client, f"{SERVICES[svc]}{path}?limit={limit}")
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
    async with httpx.AsyncClient() as client:
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
async def list_entity(entity: str, offset: int = 0, limit: int = 20):
    """Paginated list for an entity. Uses the new paginated GET endpoint on
    services that have one (/payments, /notifications); falls back to the
    service's existing list endpoint where one exists (/users, /inventory)."""
    svc = _ENTITY_MAP.get(entity)
    if svc is None:
        raise HTTPException(status_code=404, detail="unknown entity")
    if entity == "payments":
        path = f"/payments?offset={offset}&limit={limit}"
    elif entity == "notifications":
        path = f"/notifications?offset={offset}&limit={limit}"
    elif entity == "users":
        path = f"/users?offset={offset}&limit={limit}"
    elif entity == "products":
        path = f"/inventory?offset={offset}&limit={limit}"
    else:  # orders
        path = f"/orders/recent?limit={limit}"
    return await _proxy_json("GET", f"{SERVICES[svc]}{path}")


@app.post("/api/entities/{entity}")
async def create_entity(entity: str, request: Request):
    svc = _ENTITY_MAP.get(entity)
    if svc is None:
        raise HTTPException(status_code=404, detail="unknown entity")
    body = await request.json()
    path = {"users": "/users", "products": "/inventory", "orders": "/orders"}.get(entity)
    if path is None:
        raise HTTPException(status_code=400, detail=f"manual create not supported for {entity}")
    return await _proxy_json("POST", f"{SERVICES[svc]}{path}", body=body, timeout=30.0)


@app.patch("/api/entities/{entity}/{item_id}")
async def update_entity(entity: str, item_id: int, request: Request):
    svc = _ENTITY_MAP.get(entity)
    if svc is None:
        raise HTTPException(status_code=404, detail="unknown entity")
    body = await request.json()
    base = f"{SERVICES[svc]}"
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
    base = f"{SERVICES[svc]}"
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
    async with httpx.AsyncClient() as client:
        code, body = await _get(client, f"{SERVICES['user']}/users/{user_id}/orders?limit={limit}")
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
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{SERVICES['order']}/orders", json=order.model_dump(), timeout=15.0)
        return r.json()


@app.post("/api/generate/{what}")
async def generate(what: str):
    mapping = {"users": ("user", "/users/generate"), "inventory": ("inventory", "/inventory/generate")}
    if what not in mapping:
        raise HTTPException(status_code=400, detail="must be 'users' or 'inventory'")
    svc, path = mapping[what]
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{SERVICES[svc]}{path}", timeout=30.0)
        return r.json()


app.mount("/", StaticFiles(directory="static", html=True), name="static")
