from __future__ import annotations

import os
import sys
import time
from typing import Iterable

import psycopg
from psycopg.types.json import Jsonb

import generate_data


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://resilencia:resilencia_secret@postgres:5432/resilencia_db",
)
SEED_ENABLED = os.getenv("SEED_ENABLED", "true").strip().lower() == "true"
SEED_USERS_COUNT = int(os.getenv("SEED_USERS_COUNT", "50000"))
SEED_PRODUCTS_COUNT = int(os.getenv("SEED_PRODUCTS_COUNT", "0"))
CONNECT_RETRIES = int(os.getenv("SEED_CONNECT_RETRIES", "30"))
CONNECT_DELAY_SECONDS = float(os.getenv("SEED_CONNECT_DELAY_SECONDS", "2"))
BATCH_SIZE = int(os.getenv("SEED_BATCH_SIZE", "1000"))


def log(message: str):
    print(f"[seed] {message}", flush=True)


def validate_config():
    if SEED_USERS_COUNT < 0:
        raise ValueError("SEED_USERS_COUNT must be 0 or greater")
    if SEED_PRODUCTS_COUNT < 0:
        raise ValueError("SEED_PRODUCTS_COUNT must be 0 or greater")
    if BATCH_SIZE < 1:
        raise ValueError("SEED_BATCH_SIZE must be 1 or greater")


def wait_for_postgres():
    last_error = None

    for attempt in range(1, CONNECT_RETRIES + 1):
        try:
            with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1;")
            log("PostgreSQL ready")
            return
        except Exception as exc:
            last_error = exc
            log(f"Waiting for PostgreSQL ({attempt}/{CONNECT_RETRIES})...")
            time.sleep(CONNECT_DELAY_SECONDS)

    raise RuntimeError(f"PostgreSQL did not become ready: {last_error}")


def fetch_count_and_max_id(cur, table_name: str) -> tuple[int, int]:
    cur.execute(f"SELECT COUNT(*), COALESCE(MAX(id), 0) FROM {table_name};")
    current_count, max_id = cur.fetchone()
    return int(current_count), int(max_id)


def chunked(iterable: Iterable[tuple], size: int):
    batch = []
    for item in iterable:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def seed_users(cur):
    current_count, max_id = fetch_count_and_max_id(cur, "users")
    target_count = SEED_USERS_COUNT
    missing_count = max(target_count - current_count, 0)

    log(f"Current users: {current_count}")
    log(f"Target users: {target_count}")
    log(f"Missing users: {missing_count}")

    if target_count == 0 or missing_count == 0:
        final_count = current_count
        log("Users already satisfy target; skipping user generation")
        log(f"Final users count: {final_count}")
        return

    start_id = max_id + 1
    log("Generating users with Faker...")

    rows = (
        (record["id"], Jsonb(record))
        for record in generate_data.iter_user_records(missing_count, start_id)
    )
    for batch in chunked(rows, BATCH_SIZE):
        cur.executemany("INSERT INTO users (id, data) VALUES (%s, %s);", batch)

    cur.execute("SELECT setval('users_id_seq', (SELECT MAX(id) FROM users));")
    cur.execute("SELECT COUNT(*) FROM users;")
    final_count = int(cur.fetchone()[0])
    log("Import completed")
    log(f"Final users count: {final_count}")


def seed_products(cur):
    current_count, max_id = fetch_count_and_max_id(cur, "products")
    target_count = SEED_PRODUCTS_COUNT
    missing_count = max(target_count - current_count, 0)

    log(f"Current products: {current_count}")
    log(f"Target products: {target_count}")
    log(f"Missing products: {missing_count}")

    if target_count == 0 or missing_count == 0:
        final_count = current_count
        log("Products already satisfy target; skipping product generation")
        log(f"Final products count: {final_count}")
        return

    start_id = max_id + 1
    log("Generating products with Faker...")

    rows = (
        (record["product_id"], record["quantity"], Jsonb(record))
        for record in generate_data.iter_product_records(missing_count, start_id)
    )
    for batch in chunked(rows, BATCH_SIZE):
        cur.executemany(
            "INSERT INTO products (id, quantity, data) VALUES (%s, %s, %s);",
            batch,
        )

    cur.execute("SELECT setval('products_id_seq', (SELECT MAX(id) FROM products));")
    cur.execute("SELECT COUNT(*) FROM products;")
    final_count = int(cur.fetchone()[0])
    log("Product import completed")
    log(f"Final products count: {final_count}")


def main():
    validate_config()

    if not SEED_ENABLED:
        log("Seeder disabled (SEED_ENABLED=false). Skipping.")
        return

    wait_for_postgres()

    with psycopg.connect(DATABASE_URL, autocommit=False) as conn:
        with conn.cursor() as cur:
            seed_users(cur)
            seed_products(cur)
        conn.commit()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log(f"Seeder failed: {exc}")
        sys.exit(1)
