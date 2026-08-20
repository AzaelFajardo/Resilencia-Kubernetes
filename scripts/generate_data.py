"""
generate_data.py - Faker-based data generator for Resilencia-Kubernetes.

Supported entities:
  - users
  - products
  - all

Examples:
  python scripts/generate_data.py --entity users --count 10 --format sql
  python scripts/generate_data.py --entity products --count 25 --format json
  python scripts/generate_data.py --entity all --count 5 --dry-run
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
import uuid

from faker import Faker


fake = Faker(["es_MX", "en_US"])
Faker.seed(42)


def to_utc_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def gen_customer(user_id: int) -> dict:
    account_created_at = fake.date_time_between(start_date="-3y", end_date="-30d")
    last_login_at = None
    suffix = fake.suffix() if fake.boolean(chance_of_getting_true=30) else None

    if suffix is not None and not str(suffix).strip():
        suffix = None

    if fake.boolean(chance_of_getting_true=85):
        last_login_at = fake.date_time_between(start_date=account_created_at, end_date="now")

    return {
        "id": user_id,
        "first_name": fake.first_name(),
        "last_name": fake.last_name(),
        "suffix": suffix,
        "email": f"user_bulk_{user_id}@example.com",
        "phone_number": fake.phone_number(),
        "dob": fake.date_of_birth(minimum_age=18, maximum_age=75).isoformat(),
        "gender": fake.random_element(["male", "female", "non_binary", "prefer_not_to_say"]),
        "loyalty_tier": fake.random_element(["bronze", "silver", "gold", "platinum", "diamond"]),
        "loyalty_points": fake.pyint(min_value=0, max_value=50000),
        "account_created_at": to_utc_iso(account_created_at),
        "is_vip": fake.boolean(chance_of_getting_true=15),
        "language_preference": fake.random_element(["es", "en", "pt", "fr", "de"]),
        "timezone": fake.timezone(),
        "last_login_at": to_utc_iso(last_login_at),
        "shipping_address": {
            "street": fake.street_address(),
            "city": fake.city(),
            "state": fake.state(),
            "zip": fake.postcode(),
            "country": fake.country_code(),
        },
        "active": True,
    }


def gen_product(product_id: int) -> dict:
    categories = [
        "electronics",
        "clothing",
        "home_garden",
        "sports",
        "toys",
        "food_beverage",
        "books",
        "automotive",
    ]
    materials = [
        "aluminum",
        "steel",
        "plastic",
        "wood",
        "glass",
        "ceramic",
        "recycled_plastic",
        "carbon_fiber",
        "cotton",
        "leather",
    ]
    colors = [
        "matte_black",
        "silver",
        "space_gray",
        "white",
        "navy_blue",
        "forest_green",
        "crimson_red",
        "gold",
        "rose_gold",
    ]
    sizes = ["XS", "S", "M", "L", "XL", "XXL", "compact", "standard", "full_size", "oversized"]
    quantity = fake.pyint(min_value=0, max_value=500)

    return {
        "product_id": product_id,
        "name": fake.catch_phrase(),
        "category": fake.random_element(categories),
        "quantity": quantity,
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
        "currency": "MXN",
        "manufacturer": fake.company(),
        "ean13": fake.ean13(),
        "stock_at_ordering": quantity,
        "estimated_restock_date": (
            fake.future_date(end_date="+120d").isoformat()
            if fake.boolean(chance_of_getting_true=70)
            else None
        ),
        "material": fake.random_element(materials),
        "color": fake.random_element(colors),
        "size": fake.random_element(sizes),
        "warranty_period_months": fake.random_element([0, 3, 6, 12, 24, 36, 60]),
        "is_subscription": fake.boolean(chance_of_getting_true=10),
    }


def iter_user_records(count: int, start_id: int):
    for user_id in range(start_id, start_id + count):
        yield gen_customer(user_id)


def iter_product_records(count: int, start_id: int):
    for product_id in range(start_id, start_id + count):
        yield gen_product(product_id)


def gen_entity_records(entity: str, count: int, start_id: int):
    if entity == "users":
        return list(iter_user_records(count, start_id))
    if entity == "products":
        return list(iter_product_records(count, start_id))
    if entity == "all":
        return {
            "users": list(iter_user_records(count, start_id)),
            "products": list(iter_product_records(count, start_id)),
        }
    raise ValueError(f"Unsupported entity: {entity}")


def gen_users_sql(count: int, start_id: int) -> list[str]:
    lines = [
        "-- Users",
        "",
    ]
    for record in iter_user_records(count, start_id):
        payload = json.dumps(record, ensure_ascii=False).replace("'", "''")
        lines.append(f"INSERT INTO users (id, data) VALUES ({record['id']}, '{payload}'::jsonb);")
    lines.append("")
    lines.append("SELECT setval('users_id_seq', (SELECT MAX(id) FROM users));")
    return lines


def gen_products_sql(count: int, start_id: int) -> list[str]:
    lines = [
        "-- Products",
        "",
    ]
    for record in iter_product_records(count, start_id):
        payload = json.dumps(record, ensure_ascii=False).replace("'", "''")
        lines.append(
            "INSERT INTO products (id, quantity, data) "
            f"VALUES ({record['product_id']}, {record['quantity']}, '{payload}'::jsonb);"
        )
    lines.append("")
    lines.append("SELECT setval('products_id_seq', (SELECT MAX(id) FROM products));")
    return lines


def gen_sql(entity: str, count: int, start_id: int) -> str:
    lines = [
        "-- =============================================================",
        f"-- Generated entity set: {entity}",
        f"-- Records per entity: {count}",
        f"-- Generated at: {to_utc_iso(datetime.now(timezone.utc))}",
        "-- =============================================================",
        "",
    ]

    if entity in {"users", "all"}:
        lines.extend(gen_users_sql(count, start_id))
        lines.append("")

    if entity in {"products", "all"}:
        lines.extend(gen_products_sql(count, start_id))

    return "\n".join(lines).rstrip()


def count_fields(obj) -> int:
    total = 0
    if isinstance(obj, dict):
        for value in obj.values():
            if isinstance(value, (dict, list)):
                total += count_fields(value)
            else:
                total += 1
    elif isinstance(obj, list):
        for item in obj:
            total += count_fields(item)
    return total


def build_dry_run_sample(entity: str, start_id: int):
    if entity == "users":
        return next(iter_user_records(1, start_id))
    if entity == "products":
        return next(iter_product_records(1, start_id))
    if entity == "all":
        return {
            "users": [next(iter_user_records(1, start_id))],
            "products": [next(iter_product_records(1, start_id))],
        }
    raise ValueError(f"Unsupported entity: {entity}")


def main():
    parser = argparse.ArgumentParser(
        description="Generate realistic Faker-based test data compatible with the repo schema."
    )
    parser.add_argument(
        "--entity",
        choices=["users", "products", "all"],
        default="users",
        help="Entity set to generate.",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=5,
        help="Number of records to generate per entity (default: 5).",
    )
    parser.add_argument(
        "--format",
        choices=["json", "sql"],
        default="json",
        help="Output format.",
    )
    parser.add_argument(
        "--start-id",
        type=int,
        default=4,
        help="Starting numeric id for generated records (default: 4 to avoid seed data).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print a sample record set and exit.",
    )
    args = parser.parse_args()

    if args.start_id < 1:
        raise ValueError("--start-id must be 1 or greater")
    if args.count < 1:
        raise ValueError("--count must be 1 or greater")

    if args.dry_run:
        sample = build_dry_run_sample(args.entity, args.start_id)
        print(json.dumps(sample, indent=2, ensure_ascii=False, default=str))
        print(f"\n--- Total fields (including nested): {count_fields(sample)} ---")
        return

    if args.format == "json":
        print(json.dumps(gen_entity_records(args.entity, args.count, args.start_id), indent=2, ensure_ascii=False))
        return

    print(gen_sql(args.entity, args.count, args.start_id))


if __name__ == "__main__":
    main()
