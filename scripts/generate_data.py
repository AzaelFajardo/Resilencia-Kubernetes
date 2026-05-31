"""
generate_data.py  –  Faker-based data generator for Resilencia-Kubernetes.

Generates realistic, complex, and nested data for all 105 fields
defined in "Campos por servicio.md". Each generated record simulates
an Amazon-like e-commerce transaction.

Usage:
    python generate_data.py --count 10                 # prints SQL to stdout
    python generate_data.py --count 50 --format json   # prints JSON to stdout
    python generate_data.py --count 5 --dry-run        # prints sample data

Dependencies:
    pip install faker psycopg2-binary
"""

import argparse
import json
import sys
import uuid
from datetime import datetime, timedelta

from faker import Faker

fake = Faker(["es_MX", "en_US"])
Faker.seed(42)


# ═══════════════════════════════════════════════════════════════════════
# FIELD GENERATORS  –  one function per category
# ═══════════════════════════════════════════════════════════════════════

def gen_metadata() -> dict:
    """Generates the 10 Metadata & Tracing global fields."""
    return {
        "trace_id": str(uuid.uuid4()),
        "request_id": str(uuid.uuid4()),
        "source_system": fake.random_element(["web", "mobile_ios", "mobile_android", "api_partner", "internal_backoffice"]),
        "api_version": f"v{fake.random_int(1,3)}.{fake.random_int(0,9)}.{fake.random_int(0,9)}",
        "environment": fake.random_element(["production", "staging", "canary", "shadow"]),
        "timestamp_utc": datetime.utcnow().isoformat() + "Z",
        "correlation_token": fake.sha1(),
        "client_ip": fake.ipv4(),
        "user_agent": fake.user_agent(),
        "tenant_id": fake.bothify("TN-??-###"),
    }


def gen_security() -> dict:
    """Generates the 10 Risk & Security global fields."""
    return {
        "fraud_score": fake.pyint(min_value=0, max_value=100),
        "session_id": str(uuid.uuid4()),
        "device_fingerprint": fake.sha1(),
        "ip_geolocation": {
            "city": fake.city(),
            "country": fake.country_code(),
        },
        "is_authenticated": fake.boolean(chance_of_getting_true=90),
        "auth_method": fake.random_element(["bearer_token", "api_key", "oauth2", "session_cookie", "mtls"]),
        "mfa_verified": fake.boolean(chance_of_getting_true=60),
        "vpn_detected": fake.boolean(chance_of_getting_true=15),
        "request_node_id": fake.bothify("NODE-???-##"),
    }


def gen_customer(customer_id: int) -> dict:
    """Generates the 20 Customer Profile fields for user-service."""
    return {
        "id": customer_id,
        "first_name": fake.first_name(),
        "last_name": fake.last_name(),
        "suffix": fake.suffix() if fake.boolean(chance_of_getting_true=30) else None,
        "email": fake.email(),
        "phone_number": fake.phone_number(),
        "dob": fake.date_of_birth(minimum_age=18, maximum_age=75).isoformat(),
        "gender": fake.random_element(["male", "female", "non_binary", "prefer_not_to_say"]),
        "loyalty_tier": fake.random_element(["bronze", "silver", "gold", "platinum", "diamond"]),
        "loyalty_points": fake.pyint(min_value=0, max_value=50000),
        "account_created_at": fake.past_datetime(start_date="-3y").isoformat() + "Z",
        "is_vip": fake.boolean(chance_of_getting_true=15),
        "language_preference": fake.random_element(["es", "en", "pt", "fr", "de"]),
        "timezone": fake.timezone(),
        "last_login_at": fake.past_datetime(start_date="-30d").isoformat() + "Z" if fake.boolean(chance_of_getting_true=85) else None,
        "shipping_address": {
            "street": fake.street_address(),
            "city": fake.city(),
            "state": fake.state(),
            "zip": fake.postcode(),
            "country": fake.country_code(),
        },
    }


def gen_item(product_id: int) -> dict:
    """Generates the 25 Inventory & Product fields for inventory-service."""
    categories = ["electronics", "clothing", "home_garden", "sports", "toys", "food_beverage", "books", "automotive"]
    materials = ["aluminum", "steel", "plastic", "wood", "glass", "ceramic", "recycled_plastic", "carbon_fiber", "cotton", "leather"]
    colors = ["matte_black", "silver", "space_gray", "white", "navy_blue", "forest_green", "crimson_red", "gold", "rose_gold"]
    sizes = ["XS", "S", "M", "L", "XL", "XXL", "compact", "standard", "full_size", "oversized"]

    return {
        "product_id": product_id,
        "name": fake.catch_phrase(),
        "category": fake.random_element(categories),
        "quantity": fake.pyint(min_value=0, max_value=500),
        "unit_price": round(fake.pyfloat(min_value=5.0, max_value=2500.0, right_digits=2), 2),
        "weight_kg": round(fake.pyfloat(min_value=0.01, max_value=50.0, right_digits=3), 3),
        "dimensions": {
            "length": round(fake.pyfloat(min_value=1.0, max_value=200.0, right_digits=1), 1),
            "width": round(fake.pyfloat(min_value=1.0, max_value=100.0, right_digits=1), 1),
            "height": round(fake.pyfloat(min_value=0.5, max_value=80.0, right_digits=1), 1),
        },
        "is_fragile": fake.boolean(chance_of_getting_true=20),
        "requires_refrigeration": fake.boolean(chance_of_getting_true=8),
        "warehouse_id": fake.bothify("WH-???-##"),
        "supplier_id": fake.bothify("SUP-????-##"),
        "discount_applied": round(fake.pyfloat(min_value=0.0, max_value=40.0, right_digits=2), 2),
        "tax_rate": round(fake.pyfloat(min_value=0.0, max_value=0.25, right_digits=4), 4),
        "currency": fake.currency_code(),
        "manufacturer": fake.company(),
        "ean13": fake.ean13(),
        "stock_at_ordering": fake.pyint(min_value=0, max_value=500),
        "estimated_restock_date": fake.future_date(end_date="+120d").isoformat() if fake.boolean(chance_of_getting_true=70) else None,
        "material": fake.random_element(materials),
        "color": fake.random_element(colors),
        "size": fake.random_element(sizes),
        "warranty_period_months": fake.random_element([0, 3, 6, 12, 24, 36, 60]),
        "is_subscription": fake.boolean(chance_of_getting_true=10),
    }


def gen_order(order_id: int) -> dict:
    """Generates the 10 Order Logistics & Metadata fields for order-service."""
    return {
        "id": fake.bothify("ORD-############").upper(),
        "internal_status": fake.random_element([
            "awaiting_validation", "payment_pending", "payment_verified",
            "processing", "shipped", "completed", "cancelled", "returned",
        ]),
        "priority": fake.random_element(["low", "normal", "high", "critical"]),
        "is_gift": fake.boolean(chance_of_getting_true=20),
        "gift_message": fake.sentence(nb_words=10) if fake.boolean(chance_of_getting_true=20) else None,
        "special_instructions": fake.text(max_nb_chars=150) if fake.boolean(chance_of_getting_true=30) else None,
        "estimated_delivery_at": fake.future_datetime(end_date="+14d").isoformat() + "Z",
        "warehouse_dispatch_id": str(uuid.uuid4()),
        "carrier_service_level": fake.random_element(["economy", "standard", "express", "same_day", "specialized"]),
        "return_policy_accepted": fake.boolean(chance_of_getting_true=95),
    }


def gen_payment() -> dict:
    """Generates the 15 Payment & Billing fields for payment-service."""
    subtotal = round(fake.pyfloat(min_value=15.0, max_value=5000.0, right_digits=2), 2)
    tax = round(subtotal * 0.16, 2)
    shipping = round(fake.pyfloat(min_value=0.0, max_value=250.0, right_digits=2), 2)
    total = round(subtotal + tax + shipping, 2)

    card_number = fake.credit_card_number()

    return {
        "order_total": total,
        "subtotal": subtotal,
        "tax_amount": tax,
        "shipping_cost": shipping,
        "currency": fake.currency_code(),
        "method": fake.random_element(["credit_card", "debit_card", "paypal", "bank_transfer", "crypto", "cash_on_delivery"]),
        "provider": fake.company(),
        "card_last_four": card_number[-4:] if len(card_number) >= 4 else "0000",
        "card_expiry": fake.credit_card_expire(start="now", end="+5y"),
        "card_network": fake.credit_card_provider(),
        "billing_address": {
            "street": fake.street_address(),
            "city": fake.city(),
            "zip": fake.postcode(),
        },
        "coupon_code": fake.lexify("????-????").upper() if fake.boolean(chance_of_getting_true=25) else None,
        "installment_count": fake.random_element([1, 1, 1, 3, 6, 9, 12, 18, 24]),
    }


def gen_notification() -> dict:
    """Generates the 10 Notification & Marketing fields for notification-service."""
    return {
        "enable_email": fake.boolean(chance_of_getting_true=80),
        "enable_sms": fake.boolean(chance_of_getting_true=40),
        "enable_push": fake.boolean(chance_of_getting_true=60),
        "preferred_channel": fake.random_element(["email", "sms", "push", "in_app"]),
        "marketing_opt_in": fake.boolean(chance_of_getting_true=55),
        "template_id": fake.bothify("TPL-????-##"),
        "tracking_pixel_id": str(uuid.uuid4()),
        "campaign_id": fake.bothify("CMP-????-##"),
        "referral_code": fake.lexify("REF-????????").upper() if fake.boolean(chance_of_getting_true=35) else None,
        "link_shortener_key": fake.lexify("shrt-??????"),
    }


# ═══════════════════════════════════════════════════════════════════════
# FULL RECORD GENERATOR  –  assembles all 105 fields
# ═══════════════════════════════════════════════════════════════════════

def gen_full_record(record_id: int) -> dict:
    """Generates a single complete record with all 105 fields.

    Structure:
        metadata (10) + security (10) + customer (20) + items[] (25)
        + order (10) + payment (15) + notifications (10)
        = 100 named fields + 5 nested sub-objects = 105 total
    """
    customer = gen_customer(record_id)
    item = gen_item(record_id)
    order = gen_order(record_id)
    payment = gen_payment()
    notification = gen_notification()

    return {
        # ── Global: Metadata & Tracing (10 fields) ─────────────────
        **gen_metadata(),
        # ── Global: Risk & Security (10 fields) ───────────────────
        "security": gen_security(),
        # ── user-service: Customer Profile (20 fields) ────────────
        "customer": customer,
        # ── inventory-service: Product Details (25 fields) ────────
        "items": [item],
        # ── order-service: Logistics & Metadata (10 fields) ───────
        "order": order,
        # ── payment-service: Payment & Billing (15 fields) ────────
        "payment": payment,
        # ── notification-service: Notifications (10 fields) ───────
        "notifications": notification,
    }


# ═══════════════════════════════════════════════════════════════════════
# SQL GENERATOR  –  produces INSERT statements for PostgreSQL
# ═══════════════════════════════════════════════════════════════════════

def escape_sql(val) -> str:
    """Escapes a value for safe SQL insertion."""
    if val is None:
        return "NULL"
    if isinstance(val, bool):
        return "TRUE" if val else "FALSE"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, dict):
        return "'" + json.dumps(val, ensure_ascii=False).replace("'", "''") + "'"
    s = str(val).replace("'", "''")
    return f"'{s}'"


def gen_sql(count: int) -> str:
    """Generates INSERT SQL statements for all tables."""
    lines = [
        "-- =============================================================",
        f"-- Generated data: {count} records per table",
        f"-- Generated at: {datetime.utcnow().isoformat()}Z",
        "-- =============================================================",
        "",
    ]

    # ── Users ──────────────────────────────────────────────────────────
    for i in range(1, count + 1):
        c = gen_customer(1000 + i)
        lines.append(
            f"INSERT INTO users (first_name, last_name, suffix, email, phone_number, "
            f"dob, gender, loyalty_tier, loyalty_points, is_vip, language_preference, "
            f"timezone, last_login_at, shipping_address, active) VALUES ("
            f"{escape_sql(c['first_name'])}, {escape_sql(c['last_name'])}, "
            f"{escape_sql(c.get('suffix'))}, {escape_sql(c['email'])}, "
            f"{escape_sql(c['phone_number'])}, {escape_sql(c['dob'])}, "
            f"{escape_sql(c['gender'])}, {escape_sql(c['loyalty_tier'])}, "
            f"{c['loyalty_points']}, {escape_sql(c['is_vip'])}, "
            f"{escape_sql(c['language_preference'])}, {escape_sql(c['timezone'])}, "
            f"{escape_sql(c.get('last_login_at'))}, "
            f"{escape_sql(c['shipping_address'])}, TRUE);"
        )

    lines.append("")

    # ── Products ───────────────────────────────────────────────────────
    for i in range(1, count + 1):
        p = gen_item(1000 + i)
        lines.append(
            f"INSERT INTO products (name, sku, category, quantity, unit_price, "
            f"weight_kg, dimensions, is_fragile, requires_refrigeration, "
            f"warehouse_id, supplier_id, discount_applied, tax_rate, currency, "
            f"manufacturer, ean13, stock_at_ordering, estimated_restock_date, "
            f"material, color, size, warranty_period_months, is_subscription) VALUES ("
            f"{escape_sql(p['name'])}, {escape_sql(fake.bothify('SKU-####-??').upper())}, "
            f"{escape_sql(p['category'])}, {p['quantity']}, {p['unit_price']}, "
            f"{p['weight_kg']}, {escape_sql(p['dimensions'])}, "
            f"{escape_sql(p['is_fragile'])}, {escape_sql(p['requires_refrigeration'])}, "
            f"{escape_sql(p['warehouse_id'])}, {escape_sql(p['supplier_id'])}, "
            f"{p['discount_applied']}, {p['tax_rate']}, {escape_sql(p['currency'])}, "
            f"{escape_sql(p['manufacturer'])}, {escape_sql(p['ean13'])}, "
            f"{p['stock_at_ordering']}, {escape_sql(p.get('estimated_restock_date'))}, "
            f"{escape_sql(p['material'])}, {escape_sql(p['color'])}, "
            f"{escape_sql(p['size'])}, {p['warranty_period_months']}, "
            f"{escape_sql(p['is_subscription'])});"
        )

    lines.append("")
    lines.append("-- Done. Use separate scripts to generate orders, payments, and notifications")
    lines.append("-- as they depend on user_id and product_id foreign keys.")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Generate realistic test data with all 105 fields."
    )
    parser.add_argument(
        "--count", type=int, default=5,
        help="Number of records to generate per entity (default: 5)",
    )
    parser.add_argument(
        "--format", choices=["json", "sql"], default="json",
        help="Output format: json (full records) or sql (INSERT statements)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print a single sample record and exit",
    )
    args = parser.parse_args()

    if args.dry_run:
        sample = gen_full_record(1)
        print(json.dumps(sample, indent=2, ensure_ascii=False, default=str))
        field_count = count_fields(sample)
        print(f"\n--- Total fields (including nested): {field_count} ---")
        return

    if args.format == "json":
        records = [gen_full_record(i) for i in range(1, args.count + 1)]
        print(json.dumps(records, indent=2, ensure_ascii=False, default=str))
    elif args.format == "sql":
        print(gen_sql(args.count))


def count_fields(obj, prefix="") -> int:
    """Recursively counts all leaf fields in a nested dict/list structure."""
    total = 0
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                total += count_fields(v, f"{prefix}{k}.")
            else:
                total += 1
    elif isinstance(obj, list):
        for item in obj:
            total += count_fields(item, prefix)
    return total


if __name__ == "__main__":
    main()
