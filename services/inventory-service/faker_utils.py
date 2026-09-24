"""faker_utils.py - Faker-based product generation for inventory-service.

Field structure mirrors scripts/generate_data.py's gen_product() and the
Product model in main.py (25 fields, nested dimensions).
"""

from faker import Faker

_fake = Faker(["es_MX", "en_US"])

_CATEGORIES = ["electronics", "clothing", "home_garden", "sports", "toys", "food_beverage", "books", "automotive"]
_MATERIALS = ["aluminum", "steel", "plastic", "wood", "glass", "ceramic", "recycled_plastic", "carbon_fiber", "cotton", "leather"]
_COLORS = ["matte_black", "silver", "space_gray", "white", "navy_blue", "forest_green", "crimson_red", "gold", "rose_gold"]
_SIZES = ["XS", "S", "M", "L", "XL", "XXL", "compact", "standard", "full_size", "oversized"]


def gen_product(product_id: int) -> dict:
    quantity = _fake.pyint(min_value=0, max_value=500)
    return {
        "product_id": product_id,
        "name": _fake.catch_phrase(),
        "category": _fake.random_element(_CATEGORIES),
        "quantity": quantity,
        "unit_price": round(_fake.pyfloat(min_value=5.0, max_value=2500.0, right_digits=2), 2),
        "weight_kg": round(_fake.pyfloat(min_value=0.01, max_value=50.0, right_digits=3), 3),
        "dimensions": {
            "length": round(_fake.pyfloat(min_value=1.0, max_value=200.0, right_digits=1), 1),
            "width": round(_fake.pyfloat(min_value=1.0, max_value=100.0, right_digits=1), 1),
            "height": round(_fake.pyfloat(min_value=0.5, max_value=80.0, right_digits=1), 1),
        },
        "is_fragile": _fake.boolean(chance_of_getting_true=20),
        "requires_refrigeration": _fake.boolean(chance_of_getting_true=8),
        "warehouse_id": _fake.bothify("WH-???-##"),
        "supplier_id": _fake.bothify("SUP-????-##"),
        "discount_applied": round(_fake.pyfloat(min_value=0.0, max_value=40.0, right_digits=2), 2),
        "tax_rate": round(_fake.pyfloat(min_value=0.0, max_value=0.25, right_digits=4), 4),
        "currency": "MXN",
        "manufacturer": _fake.company(),
        "ean13": _fake.ean13(),
        "stock_at_ordering": quantity,
        "estimated_restock_date": _fake.future_date(end_date="+120d").isoformat() if _fake.boolean(chance_of_getting_true=70) else None,
        "material": _fake.random_element(_MATERIALS),
        "color": _fake.random_element(_COLORS),
        "size": _fake.random_element(_SIZES),
        "warranty_period_months": _fake.random_element([0, 3, 6, 12, 24, 36, 60]),
        "is_subscription": _fake.boolean(chance_of_getting_true=10),
    }


def iter_product_records(count: int, start_id: int):
    for product_id in range(start_id, start_id + count):
        yield gen_product(product_id)
