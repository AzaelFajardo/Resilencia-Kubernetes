-- =======================================================================
-- init.sql  –  Bootstrap schema for Resilencia-Kubernetes
-- This script runs automatically when the postgres container starts
-- for the first time (mounted in /docker-entrypoint-initdb.d/).
-- =======================================================================

-- Enable the pgcrypto extension for gen_random_uuid().
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- -----------------------------------------------------------------------
-- 1. USERS
-- -----------------------------------------------------------------------
-- The "profile" column is JSONB and can store up to 100+ nested fields
-- (address, preferences, metadata, etc.) without altering the schema.
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id          SERIAL       PRIMARY KEY,
    name        VARCHAR(150) NOT NULL,
    email       VARCHAR(255) NOT NULL UNIQUE,
    role        VARCHAR(50)  NOT NULL DEFAULT 'customer',
    active      BOOLEAN      NOT NULL DEFAULT TRUE,
    profile     JSONB        NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Index on JSONB profile for fast key-level lookups.
CREATE INDEX IF NOT EXISTS idx_users_profile ON users USING GIN (profile);

-- -----------------------------------------------------------------------
-- 2. PRODUCTS
-- -----------------------------------------------------------------------
-- Stores the product catalog / inventory.
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS products (
    id          SERIAL         PRIMARY KEY,
    name        VARCHAR(200)   NOT NULL,
    sku         VARCHAR(50)    NOT NULL UNIQUE,
    price       NUMERIC(12,2)  NOT NULL CHECK (price >= 0),
    stock       INTEGER        NOT NULL DEFAULT 0 CHECK (stock >= 0),
    created_at  TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);

-- -----------------------------------------------------------------------
-- 3. ORDERS
-- -----------------------------------------------------------------------
-- Links a user with a product and tracks the lifecycle of the order.
-- -----------------------------------------------------------------------
CREATE TYPE order_status AS ENUM (
    'pending',
    'confirmed',
    'paid',
    'shipped',
    'delivered',
    'cancelled'
);

CREATE TABLE IF NOT EXISTS orders (
    id          SERIAL         PRIMARY KEY,
    user_id     INTEGER        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    product_id  INTEGER        NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    quantity    INTEGER        NOT NULL DEFAULT 1 CHECK (quantity > 0),
    total_price NUMERIC(12,2)  NOT NULL CHECK (total_price >= 0),
    status      order_status   NOT NULL DEFAULT 'pending',
    created_at  TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);

-- Indexes for common query patterns.
CREATE INDEX IF NOT EXISTS idx_orders_user_id    ON orders (user_id);
CREATE INDEX IF NOT EXISTS idx_orders_product_id ON orders (product_id);
CREATE INDEX IF NOT EXISTS idx_orders_status     ON orders (status);

-- =======================================================================
-- SEED DATA  –  matches the in-memory fixtures already present in the
--               user-service and inventory-service microservices.
-- =======================================================================

-- Users (with example JSONB profiles carrying nested fields)
INSERT INTO users (id, name, email, role, active, profile) VALUES
(1, 'Alice Admin',    'alice.admin@example.com',    'admin',    TRUE,  '{
    "phone": "+52-555-0101",
    "address": {
        "street": "Av. Reforma 123",
        "city": "CDMX",
        "state": "CDMX",
        "zip": "06600",
        "country": "MX"
    },
    "preferences": {
        "language": "es",
        "currency": "MXN",
        "notifications": { "email": true, "sms": false, "push": true }
    },
    "metadata": {
        "signup_source": "web",
        "verified_email": true,
        "last_login": "2026-05-28T10:30:00Z"
    }
}'),
(2, 'Carlos Cliente', 'carlos.cliente@example.com', 'customer', TRUE,  '{
    "phone": "+52-555-0202",
    "address": {
        "street": "Calle Independencia 456",
        "city": "Guadalajara",
        "state": "Jalisco",
        "zip": "44100",
        "country": "MX"
    },
    "preferences": {
        "language": "es",
        "currency": "MXN",
        "notifications": { "email": true, "sms": true, "push": false }
    },
    "metadata": {
        "signup_source": "mobile",
        "verified_email": true,
        "last_login": "2026-05-29T14:00:00Z"
    }
}'),
(3, 'Ines Inactiva',  'ines.inactiva@example.com',  'customer', FALSE, '{
    "phone": "+52-555-0303",
    "address": {
        "street": "Blvd. Costero 789",
        "city": "Monterrey",
        "state": "Nuevo León",
        "zip": "64000",
        "country": "MX"
    },
    "preferences": {
        "language": "es",
        "currency": "MXN",
        "notifications": { "email": false, "sms": false, "push": false }
    },
    "metadata": {
        "signup_source": "referral",
        "verified_email": false,
        "last_login": null
    }
}');

-- Reset the sequence so the next INSERT gets id = 4.
SELECT setval('users_id_seq', (SELECT MAX(id) FROM users));

-- Products (match inventory-service fixtures)
INSERT INTO products (id, name, sku, price, stock) VALUES
(1, 'Mechanical Keyboard', 'KB-001', 89.99,  12),
(2, 'Wireless Mouse',      'MS-002', 29.99,   0),
(3, 'USB-C Dock',          'DK-003', 119.50,  4);

SELECT setval('products_id_seq', (SELECT MAX(id) FROM products));

-- Sample orders
INSERT INTO orders (user_id, product_id, quantity, total_price, status) VALUES
(1, 1, 2, 179.98, 'confirmed'),
(2, 3, 1, 119.50, 'pending');

-- =======================================================================
-- Done.  The database is ready for the microservices to connect.
-- =======================================================================
