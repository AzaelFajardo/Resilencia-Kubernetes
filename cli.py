#!/usr/bin/env python3
"""
cli.py - Terminal control surface for Resilencia-Kubernetes.

This project is fully headless: there is no web UI. This script is the one
place the team drives the stack from - checking status, seeding mock data,
placing orders through the normal flow, and injecting/resetting chaos on a
running service. It talks to the microservices' existing HTTP APIs on the
host-exposed ports (see .env.example); it does not add any new HTTP-facing
control surface of its own.

Standard library only, no extra runtime dependencies.

Examples:
    python cli.py status
    python cli.py users generate
    python cli.py inventory generate
    python cli.py order place --user-id 1 --product-id 1 --quantity 1
    python cli.py chaos set order-service --failure-rate 0.2
    python cli.py chaos reset --all
    python cli.py circuit-breaker status
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any, Optional

HOST = os.getenv("CLI_HOST", "localhost")

SERVICES: dict[str, dict[str, Any]] = {
    "order": {
        "full_name": "order-service",
        "port": int(os.getenv("ORDER_SERVICE_PORT", "8100")),
    },
    "user": {
        "full_name": "user-service",
        "port": int(os.getenv("USER_SERVICE_PORT", "8101")),
    },
    "inventory": {
        "full_name": "inventory-service",
        "port": int(os.getenv("INVENTORY_SERVICE_PORT", "8102")),
    },
    "payment": {
        "full_name": "payment-service",
        "port": int(os.getenv("PAYMENT_SERVICE_PORT", "8103")),
    },
    "notification": {
        "full_name": "notification-service",
        "port": int(os.getenv("NOTIFICATION_SERVICE_PORT", "8104")),
    },
}

# Accept both the short key ("order") and the full compose service name
# ("order-service") wherever a service is named on the command line.
SERVICE_ALIASES = {v["full_name"]: k for k, v in SERVICES.items()}


class ApiError(Exception):
    pass


def resolve_service(name: str) -> str:
    key = SERVICE_ALIASES.get(name, name)
    if key not in SERVICES:
        valid = sorted(set(SERVICES) | set(SERVICE_ALIASES))
        raise ApiError(f"Unknown service '{name}'. Valid values: {', '.join(valid)}")
    return key


def base_url(service_key: str) -> str:
    return f"http://{HOST}:{SERVICES[service_key]['port']}"


def http_request(method: str, url: str, payload: Optional[dict] = None, timeout: float = 10.0):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, (json.loads(body) if body else {})
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = {"detail": body}
        return exc.code, parsed
    except urllib.error.URLError as exc:
        raise ApiError(f"Could not reach {url}: {exc.reason}") from exc
    except TimeoutError as exc:
        raise ApiError(f"Timed out calling {url}") from exc


def print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def confirm(prompt: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    answer = input(f"{prompt} [y/N] ").strip().lower()
    return answer in ("y", "yes")


# ── status ──────────────────────────────────────────────────────────────

def cmd_status(_args: argparse.Namespace) -> int:
    print("Service health:")
    for key, info in SERVICES.items():
        url = f"{base_url(key)}/health"
        try:
            status, body = http_request("GET", url)
            ok = status == 200 and body.get("status") == "ok"
            print(f"  {info['full_name']:<22} {'UP' if ok else 'DEGRADED':<9} {body}")
        except ApiError as exc:
            print(f"  {info['full_name']:<22} {'DOWN':<9} {exc}")

    print("\nRecord counts:")
    count_endpoints = [
        ("user", "/users/count", "count"),
        ("inventory", "/inventory/count", "count"),
        ("order", "/orders/count", "count"),
        ("payment", "/payments/count", "count"),
        ("notification", "/notifications/count", "count"),
    ]
    for key, path, field in count_endpoints:
        url = f"{base_url(key)}{path}"
        try:
            status, body = http_request("GET", url)
            value = body.get(field, "?") if status == 200 else f"HTTP {status}: {body}"
            print(f"  {SERVICES[key]['full_name']:<22} {value}")
        except ApiError as exc:
            print(f"  {SERVICES[key]['full_name']:<22} {exc}")
    return 0


# ── users ───────────────────────────────────────────────────────────────

def cmd_users_generate(_args: argparse.Namespace) -> int:
    status, body = http_request("POST", f"{base_url('user')}/users/generate")
    print_json(body)
    return 0 if status == 200 else 1


def cmd_users_recent(args: argparse.Namespace) -> int:
    status, body = http_request("GET", f"{base_url('user')}/users/recent?limit={args.limit}")
    print_json(body)
    return 0 if status == 200 else 1


# ── inventory ───────────────────────────────────────────────────────────

def cmd_inventory_generate(_args: argparse.Namespace) -> int:
    status, body = http_request("POST", f"{base_url('inventory')}/inventory/generate")
    print_json(body)
    return 0 if status == 200 else 1


def cmd_inventory_list(args: argparse.Namespace) -> int:
    status, body = http_request("GET", f"{base_url('inventory')}/inventory?limit={args.limit}")
    print_json(body)
    return 0 if status == 200 else 1


def cmd_inventory_stock(args: argparse.Namespace) -> int:
    status, body = http_request("GET", f"{base_url('inventory')}/inventory/stock?limit={args.limit}")
    print_json(body)
    return 0 if status == 200 else 1


# ── orders ──────────────────────────────────────────────────────────────

def cmd_order_place(args: argparse.Namespace) -> int:
    payload = {
        "user_id": args.user_id,
        "product_id": args.product_id,
        "quantity": args.quantity,
    }
    status, body = http_request("POST", f"{base_url('order')}/orders", payload=payload)
    print_json(body)
    return 0 if status == 200 and body.get("status") == "success" else 1


def cmd_orders_recent(args: argparse.Namespace) -> int:
    status, body = http_request("GET", f"{base_url('order')}/orders/recent?limit={args.limit}")
    print_json(body)
    return 0 if status == 200 else 1


def cmd_orders_count(_args: argparse.Namespace) -> int:
    status, body = http_request("GET", f"{base_url('order')}/orders/count")
    print_json(body)
    return 0 if status == 200 else 1


def cmd_orders_get(args: argparse.Namespace) -> int:
    status, body = http_request("GET", f"{base_url('order')}/orders/{args.order_id}")
    print_json(body)
    return 0 if status == 200 else 1


# ── payments ────────────────────────────────────────────────────────────

def cmd_payments_recent(args: argparse.Namespace) -> int:
    status, body = http_request("GET", f"{base_url('payment')}/payments/recent?limit={args.limit}")
    print_json(body)
    return 0 if status == 200 else 1


def cmd_payments_count(_args: argparse.Namespace) -> int:
    status, body = http_request("GET", f"{base_url('payment')}/payments/count")
    print_json(body)
    return 0 if status == 200 else 1


def cmd_payments_by_order(args: argparse.Namespace) -> int:
    status, body = http_request("GET", f"{base_url('payment')}/payments/by-order/{args.order_id}")
    print_json(body)
    return 0 if status == 200 else 1


# ── notifications ───────────────────────────────────────────────────────

def cmd_notifications_recent(args: argparse.Namespace) -> int:
    status, body = http_request(
        "GET", f"{base_url('notification')}/notifications/recent?limit={args.limit}"
    )
    print_json(body)
    return 0 if status == 200 else 1


def cmd_notifications_count(_args: argparse.Namespace) -> int:
    status, body = http_request("GET", f"{base_url('notification')}/notifications/count")
    print_json(body)
    return 0 if status == 200 else 1


def cmd_notifications_by_order(args: argparse.Namespace) -> int:
    status, body = http_request(
        "GET", f"{base_url('notification')}/notifications/by-order/{args.order_id}"
    )
    print_json(body)
    return 0 if status == 200 else 1


# ── chaos ───────────────────────────────────────────────────────────────

def target_services(name: str, apply_all: bool) -> list[str]:
    if apply_all:
        return list(SERVICES.keys())
    return [resolve_service(name)]


def cmd_chaos_set(args: argparse.Namespace) -> int:
    if not args.all and not args.service:
        print("error: specify a service name or --all", file=sys.stderr)
        return 2

    payload = {}
    if args.failure_rate is not None:
        payload["FAILURE_RATE"] = args.failure_rate
    if args.latency_ms is not None:
        payload["LATENCY_MS"] = args.latency_ms
    if args.timeout_rate is not None:
        payload["TIMEOUT_RATE"] = args.timeout_rate

    if not payload:
        print("error: provide at least one of --failure-rate, --latency-ms, --timeout-rate", file=sys.stderr)
        return 2

    targets = target_services(args.service, args.all)
    scope = "ALL services" if args.all else SERVICES[targets[0]]["full_name"]
    if not confirm(f"This will change live chaos configuration on {scope}: {payload}. Continue?", args.yes):
        print("Cancelled.")
        return 1

    exit_code = 0
    for key in targets:
        url = f"{base_url(key)}/chaos/config"
        try:
            status, body = http_request("POST", url, payload=payload)
            print(f"{SERVICES[key]['full_name']}: {body}")
            if status != 200:
                exit_code = 1
        except ApiError as exc:
            print(f"{SERVICES[key]['full_name']}: {exc}")
            exit_code = 1
    return exit_code


def cmd_chaos_reset(args: argparse.Namespace) -> int:
    if not args.all and not args.service:
        print("error: specify a service name or --all", file=sys.stderr)
        return 2

    payload = {"FAILURE_RATE": 0.0, "LATENCY_MS": 0, "TIMEOUT_RATE": 0.0}
    targets = target_services(args.service, args.all)
    scope = "ALL services" if args.all else SERVICES[targets[0]]["full_name"]
    if not confirm(f"This will reset chaos configuration on {scope} to zero. Continue?", args.yes):
        print("Cancelled.")
        return 1

    exit_code = 0
    for key in targets:
        url = f"{base_url(key)}/chaos/config"
        try:
            status, body = http_request("POST", url, payload=payload)
            print(f"{SERVICES[key]['full_name']}: {body}")
            if status != 200:
                exit_code = 1
        except ApiError as exc:
            print(f"{SERVICES[key]['full_name']}: {exc}")
            exit_code = 1
    return exit_code


# ── circuit breaker ─────────────────────────────────────────────────────

def cmd_circuit_breaker_status(_args: argparse.Namespace) -> int:
    status, body = http_request("GET", f"{base_url('order')}/circuit-breaker/payment")
    print_json(body)
    return 0 if status == 200 else 1


# ── argument parser ─────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cli.py",
        description="Terminal control surface for Resilencia-Kubernetes.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Show health and record counts for every service").set_defaults(func=cmd_status)

    users = sub.add_parser("users", help="User-service operations")
    users_sub = users.add_subparsers(dest="users_command", required=True)
    users_sub.add_parser("generate", help="Generate the built-in mock users").set_defaults(func=cmd_users_generate)
    p = users_sub.add_parser("recent", help="List the most recently created users")
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(func=cmd_users_recent)

    inventory = sub.add_parser("inventory", help="Inventory-service operations")
    inventory_sub = inventory.add_subparsers(dest="inventory_command", required=True)
    inventory_sub.add_parser("generate", help="Generate the built-in mock products").set_defaults(func=cmd_inventory_generate)
    p = inventory_sub.add_parser("list", help="List products")
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(func=cmd_inventory_list)
    p = inventory_sub.add_parser("stock", help="List products currently in stock")
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(func=cmd_inventory_stock)

    order = sub.add_parser("order", help="Order-service operations")
    order_sub = order.add_subparsers(dest="order_command", required=True)
    p = order_sub.add_parser("place", help="Place an order through the normal flow")
    p.add_argument("--user-id", type=int, required=True)
    p.add_argument("--product-id", type=int, required=True)
    p.add_argument("--quantity", type=int, default=1)
    p.set_defaults(func=cmd_order_place)
    p = order_sub.add_parser("recent", help="List the most recent orders")
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(func=cmd_orders_recent)
    order_sub.add_parser("count", help="Count all orders").set_defaults(func=cmd_orders_count)
    p = order_sub.add_parser("get", help="Get a single order by id")
    p.add_argument("order_id", type=int)
    p.set_defaults(func=cmd_orders_get)

    payment = sub.add_parser("payments", help="Payment-service operations")
    payment_sub = payment.add_subparsers(dest="payments_command", required=True)
    p = payment_sub.add_parser("recent", help="List the most recent payments")
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(func=cmd_payments_recent)
    payment_sub.add_parser("count", help="Count all payments").set_defaults(func=cmd_payments_count)
    p = payment_sub.add_parser("by-order", help="Get the payment for an order")
    p.add_argument("order_id", type=int)
    p.set_defaults(func=cmd_payments_by_order)

    notification = sub.add_parser("notifications", help="Notification-service operations")
    notification_sub = notification.add_subparsers(dest="notifications_command", required=True)
    p = notification_sub.add_parser("recent", help="List the most recent notifications")
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(func=cmd_notifications_recent)
    notification_sub.add_parser("count", help="Count all notifications").set_defaults(func=cmd_notifications_count)
    p = notification_sub.add_parser("by-order", help="Get the notification for an order")
    p.add_argument("order_id", type=int)
    p.set_defaults(func=cmd_notifications_by_order)

    chaos = sub.add_parser("chaos", help="Inject or reset chaos configuration (FAILURE_RATE/LATENCY_MS/TIMEOUT_RATE)")
    chaos_sub = chaos.add_subparsers(dest="chaos_command", required=True)

    p = chaos_sub.add_parser("set", help="Inject chaos into one service or all of them")
    p.add_argument("service", nargs="?", help="Service name, e.g. order-service or order")
    p.add_argument("--all", action="store_true", help="Apply to every service")
    p.add_argument("--failure-rate", type=float)
    p.add_argument("--latency-ms", type=int)
    p.add_argument("--timeout-rate", type=float)
    p.add_argument("-y", "--yes", action="store_true", help="Skip the confirmation prompt")
    p.set_defaults(func=cmd_chaos_set)

    p = chaos_sub.add_parser("reset", help="Reset chaos configuration to zero on one service or all of them")
    p.add_argument("service", nargs="?", help="Service name, e.g. order-service or order")
    p.add_argument("--all", action="store_true", help="Apply to every service")
    p.add_argument("-y", "--yes", action="store_true", help="Skip the confirmation prompt")
    p.set_defaults(func=cmd_chaos_reset)

    circuit_breaker = sub.add_parser("circuit-breaker", help="Circuit breaker introspection")
    circuit_breaker_sub = circuit_breaker.add_subparsers(dest="circuit_breaker_command", required=True)
    circuit_breaker_sub.add_parser(
        "status", help="Show the payment circuit breaker state on order-service"
    ).set_defaults(func=cmd_circuit_breaker_status)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ApiError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelled.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
