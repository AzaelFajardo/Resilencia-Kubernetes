"""faker_utils.py - Faker-based customer generation for user-service.

Field structure mirrors scripts/generate_data.py's gen_customer() and the
Customer model in main.py (20 fields, nested shipping_address).
"""

from datetime import datetime, timezone

from faker import Faker

_fake = Faker(["es_MX", "en_US"])


def _to_utc_iso(dt):
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def gen_customer(user_id: int) -> dict:
    account_created_at = _fake.date_time_between(start_date="-3y", end_date="-30d")
    last_login_at = None
    suffix = _fake.suffix() if _fake.boolean(chance_of_getting_true=30) else None
    if suffix is not None and not str(suffix).strip():
        suffix = None
    if _fake.boolean(chance_of_getting_true=85):
        last_login_at = _fake.date_time_between(start_date=account_created_at, end_date="now")

    return {
        "id": user_id,
        "first_name": _fake.first_name(),
        "last_name": _fake.last_name(),
        "suffix": suffix,
        "email": f"user_bulk_{user_id}@example.com",
        "phone_number": _fake.phone_number(),
        "dob": _fake.date_of_birth(minimum_age=18, maximum_age=75).isoformat(),
        "gender": _fake.random_element(["male", "female", "non_binary", "prefer_not_to_say"]),
        "loyalty_tier": _fake.random_element(["bronze", "silver", "gold", "platinum", "diamond"]),
        "loyalty_points": _fake.pyint(min_value=0, max_value=50000),
        "account_created_at": _to_utc_iso(account_created_at),
        "is_vip": _fake.boolean(chance_of_getting_true=15),
        "language_preference": _fake.random_element(["es", "en", "pt", "fr", "de"]),
        "timezone": _fake.timezone(),
        "last_login_at": _to_utc_iso(last_login_at),
        "shipping_address": {
            "street": _fake.street_address(),
            "city": _fake.city(),
            "state": _fake.state(),
            "zip": _fake.postcode(),
            "country": _fake.country_code(),
        },
        "active": True,
    }


def iter_user_records(count: int, start_id: int):
    for user_id in range(start_id, start_id + count):
        yield gen_customer(user_id)
