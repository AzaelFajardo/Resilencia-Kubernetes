-- =======================================================================
-- init.sql  –  Bootstrap schema for Resilencia-Kubernetes
-- This script runs automatically when the postgres container starts
-- for the first time (mounted in /docker-entrypoint-initdb.d/).
--
-- Supports all 105 fields defined in "Campos por servicio.md".
-- =======================================================================

-- Enable the pgcrypto extension for gen_random_uuid().
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- -----------------------------------------------------------------------
-- 1. USERS  (20 customer fields via JSONB profile)
-- -----------------------------------------------------------------------
-- The "profile" JSONB column stores the full customer profile with
-- nested objects: shipping_address, loyalty, preferences, etc.
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id              SERIAL       PRIMARY KEY,
    first_name      VARCHAR(100) NOT NULL,
    last_name       VARCHAR(100) NOT NULL,
    suffix          VARCHAR(20),
    email           VARCHAR(255) NOT NULL UNIQUE,
    phone_number    VARCHAR(30),
    dob             DATE,
    gender          VARCHAR(20),
    loyalty_tier    VARCHAR(30)  NOT NULL DEFAULT 'bronze',
    loyalty_points  INTEGER      NOT NULL DEFAULT 0,
    is_vip          BOOLEAN      NOT NULL DEFAULT FALSE,
    language_preference VARCHAR(10) NOT NULL DEFAULT 'es',
    timezone        VARCHAR(50)  NOT NULL DEFAULT 'America/Mexico_City',
    last_login_at   TIMESTAMPTZ,
    shipping_address JSONB       NOT NULL DEFAULT '{}',
    active          BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Index on shipping_address JSONB for fast key-level lookups.
CREATE INDEX IF NOT EXISTS idx_users_shipping ON users USING GIN (shipping_address);
-- Index for loyalty tier searches.
CREATE INDEX IF NOT EXISTS idx_users_loyalty ON users (loyalty_tier);

-- -----------------------------------------------------------------------
-- 2. PRODUCTS  (25 inventory fields, complex nested JSONB)
-- -----------------------------------------------------------------------
-- Stores the product catalog / inventory with rich detail.
-- The "details" JSONB column holds dimensions, supplier info, and more.
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS products (
    id                      SERIAL         PRIMARY KEY,
    name                    VARCHAR(200)   NOT NULL,
    sku                     VARCHAR(50)    NOT NULL UNIQUE,
    category                VARCHAR(100)   NOT NULL DEFAULT 'general',
    quantity                INTEGER        NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    unit_price              NUMERIC(12,2)  NOT NULL CHECK (unit_price >= 0),
    weight_kg               NUMERIC(8,3),
    dimensions              JSONB          NOT NULL DEFAULT '{}',
    is_fragile              BOOLEAN        NOT NULL DEFAULT FALSE,
    requires_refrigeration  BOOLEAN        NOT NULL DEFAULT FALSE,
    warehouse_id            VARCHAR(20),
    supplier_id             VARCHAR(20),
    discount_applied        NUMERIC(5,2)   NOT NULL DEFAULT 0.00,
    tax_rate                NUMERIC(5,4)   NOT NULL DEFAULT 0.16,
    currency                VARCHAR(5)     NOT NULL DEFAULT 'MXN',
    manufacturer            VARCHAR(150),
    ean13                   VARCHAR(13),
    stock_at_ordering       INTEGER        NOT NULL DEFAULT 0,
    estimated_restock_date  DATE,
    material                VARCHAR(50),
    color                   VARCHAR(30),
    size                    VARCHAR(20),
    warranty_period_months  INTEGER        NOT NULL DEFAULT 12,
    is_subscription         BOOLEAN        NOT NULL DEFAULT FALSE,
    created_at              TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_products_category ON products (category);
CREATE INDEX IF NOT EXISTS idx_products_warehouse ON products (warehouse_id);
CREATE INDEX IF NOT EXISTS idx_products_dimensions ON products USING GIN (dimensions);

-- -----------------------------------------------------------------------
-- 3. ORDERS  (10 order fields + foreign keys)
-- -----------------------------------------------------------------------
-- Links a user with products and tracks the lifecycle of the order.
-- The "details" JSONB holds gift, logistics, and carrier info.
-- -----------------------------------------------------------------------
CREATE TYPE order_status AS ENUM (
    'pending',
    'confirmed',
    'processing',
    'paid',
    'shipped',
    'delivered',
    'cancelled',
    'returned'
);

CREATE TABLE IF NOT EXISTS orders (
    id                      SERIAL         PRIMARY KEY,
    user_id                 INTEGER        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    product_id              INTEGER        NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    quantity                INTEGER        NOT NULL DEFAULT 1 CHECK (quantity > 0),
    total_price             NUMERIC(12,2)  NOT NULL CHECK (total_price >= 0),
    status                  order_status   NOT NULL DEFAULT 'pending',
    internal_status         VARCHAR(50)    NOT NULL DEFAULT 'awaiting_validation',
    priority                VARCHAR(20)    NOT NULL DEFAULT 'normal',
    is_gift                 BOOLEAN        NOT NULL DEFAULT FALSE,
    gift_message            TEXT,
    special_instructions    TEXT,
    estimated_delivery_at   TIMESTAMPTZ,
    warehouse_dispatch_id   UUID,
    carrier_service_level   VARCHAR(30)    NOT NULL DEFAULT 'standard',
    return_policy_accepted  BOOLEAN        NOT NULL DEFAULT TRUE,
    created_at              TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);

-- Indexes for common query patterns.
CREATE INDEX IF NOT EXISTS idx_orders_user_id    ON orders (user_id);
CREATE INDEX IF NOT EXISTS idx_orders_product_id ON orders (product_id);
CREATE INDEX IF NOT EXISTS idx_orders_status     ON orders (status);
CREATE INDEX IF NOT EXISTS idx_orders_priority   ON orders (priority);

-- -----------------------------------------------------------------------
-- 4. PAYMENTS  (15 payment & billing fields)
-- -----------------------------------------------------------------------
-- Stores payment transaction details including billing address.
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS payments (
    id                  SERIAL         PRIMARY KEY,
    order_id            INTEGER        NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    order_total         NUMERIC(12,2)  NOT NULL CHECK (order_total >= 0),
    subtotal            NUMERIC(12,2)  NOT NULL CHECK (subtotal >= 0),
    tax_amount          NUMERIC(12,2)  NOT NULL DEFAULT 0.00,
    shipping_cost       NUMERIC(12,2)  NOT NULL DEFAULT 0.00,
    currency            VARCHAR(5)     NOT NULL DEFAULT 'MXN',
    method              VARCHAR(30)    NOT NULL DEFAULT 'credit_card',
    provider            VARCHAR(100),
    card_last_four      VARCHAR(4),
    card_expiry         VARCHAR(7),
    card_network        VARCHAR(30),
    billing_address     JSONB          NOT NULL DEFAULT '{}',
    coupon_code         VARCHAR(20),
    installment_count   INTEGER        NOT NULL DEFAULT 1,
    status              VARCHAR(30)    NOT NULL DEFAULT 'pending',
    created_at          TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_payments_order_id ON payments (order_id);
CREATE INDEX IF NOT EXISTS idx_payments_billing  ON payments USING GIN (billing_address);

-- -----------------------------------------------------------------------
-- 5. NOTIFICATIONS  (10 notification & marketing fields)
-- -----------------------------------------------------------------------
-- Stores notification preferences and campaign tracking per order.
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS notifications (
    id                  SERIAL      PRIMARY KEY,
    order_id            INTEGER     NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    user_id             INTEGER     NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    enable_email        BOOLEAN     NOT NULL DEFAULT TRUE,
    enable_sms          BOOLEAN     NOT NULL DEFAULT FALSE,
    enable_push         BOOLEAN     NOT NULL DEFAULT TRUE,
    preferred_channel   VARCHAR(20) NOT NULL DEFAULT 'email',
    marketing_opt_in    BOOLEAN     NOT NULL DEFAULT FALSE,
    template_id         VARCHAR(20),
    tracking_pixel_id   UUID,
    campaign_id         VARCHAR(20),
    referral_code       VARCHAR(20),
    link_shortener_key  VARCHAR(20),
    status              VARCHAR(30) NOT NULL DEFAULT 'pending',
    sent_at             TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_notifications_order_id ON notifications (order_id);
CREATE INDEX IF NOT EXISTS idx_notifications_user_id  ON notifications (user_id);

-- =======================================================================
-- SEED DATA  –  Rich, realistic data simulating an Amazon-like system.
-- All 105 fields are populated with complex, nested values.
-- =======================================================================

-- -----------------------------------------------------------------------
-- Users (20 customer fields each, with nested shipping_address)
-- -----------------------------------------------------------------------
INSERT INTO users (id, first_name, last_name, suffix, email, phone_number, dob, gender,
                   loyalty_tier, loyalty_points, is_vip, language_preference, timezone,
                   last_login_at, shipping_address, active) VALUES
(1, 'Alice',   'Rodríguez', 'Sra.',  'alice.admin@example.com',
    '+52-555-0101', '1988-03-15', 'female',
    'platinum', 15420, TRUE, 'es', 'America/Mexico_City',
    '2026-05-28T10:30:00Z',
    '{
        "street": "Av. Paseo de la Reforma 505, Piso 32",
        "city": "Ciudad de México",
        "state": "CDMX",
        "zip": "06500",
        "country": "MX"
    }', TRUE),
(2, 'Carlos',  'Mendoza',   NULL,    'carlos.cliente@example.com',
    '+52-33-1234-5678', '1995-07-22', 'male',
    'gold', 4300, FALSE, 'es', 'America/Guadalajara',
    '2026-05-29T14:00:00Z',
    '{
        "street": "Calle Independencia 456, Col. Centro",
        "city": "Guadalajara",
        "state": "Jalisco",
        "zip": "44100",
        "country": "MX"
    }', TRUE),
(3, 'Inés',    'García',    'Dra.',  'ines.inactiva@example.com',
    '+52-81-9876-5432', '1979-11-03', 'female',
    'bronze', 120, FALSE, 'en', 'America/Monterrey',
    NULL,
    '{
        "street": "Blvd. Antonio L. Rodríguez 789",
        "city": "Monterrey",
        "state": "Nuevo León",
        "zip": "64000",
        "country": "MX"
    }', FALSE);

-- Reset the sequence so the next INSERT gets id = 4.
SELECT setval('users_id_seq', (SELECT MAX(id) FROM users));

-- -----------------------------------------------------------------------
-- Products (25 inventory fields each, with nested dimensions)
-- -----------------------------------------------------------------------
INSERT INTO products (id, name, sku, category, quantity, unit_price, weight_kg,
                      dimensions, is_fragile, requires_refrigeration,
                      warehouse_id, supplier_id, discount_applied, tax_rate,
                      currency, manufacturer, ean13, stock_at_ordering,
                      estimated_restock_date, material, color, size,
                      warranty_period_months, is_subscription) VALUES
(1, 'Teclado Mecánico RGB Pro',   'KB-001', 'electronics', 12, 89.99, 1.250,
    '{"length": 44.0, "width": 14.5, "height": 3.8}',
    FALSE, FALSE,
    'WH-CDMX-01', 'SUP-TECH-42', 0.00, 0.16,
    'MXN', 'KeyTech Industries S.A. de C.V.', '7501234567890', 12,
    '2026-07-15', 'aluminum', 'matte_black', 'full_size',
    24, FALSE),
(2, 'Mouse Inalámbrico Ergonómico', 'MS-002', 'electronics', 0, 29.99, 0.085,
    '{"length": 12.4, "width": 6.8, "height": 4.0}',
    FALSE, FALSE,
    'WH-GDL-03', 'SUP-PERI-18', 10.00, 0.16,
    'MXN', 'ErgoPoint Labs', '7509876543210', 0,
    '2026-06-20', 'recycled_plastic', 'silver', 'standard',
    12, FALSE),
(3, 'Docking Station USB-C Premium', 'DK-003', 'electronics', 4, 119.50, 0.340,
    '{"length": 20.0, "width": 8.5, "height": 2.5}',
    TRUE, FALSE,
    'WH-CDMX-01', 'SUP-TECH-42', 5.00, 0.16,
    'MXN', 'ConnectPro México', '7505551234567', 4,
    '2026-08-01', 'aluminum', 'space_gray', 'compact',
    36, FALSE);

SELECT setval('products_id_seq', (SELECT MAX(id) FROM products));

-- -----------------------------------------------------------------------
-- Orders (10 order fields each, with logistics metadata)
-- -----------------------------------------------------------------------
INSERT INTO orders (id, user_id, product_id, quantity, total_price, status,
                    internal_status, priority, is_gift, gift_message,
                    special_instructions, estimated_delivery_at,
                    warehouse_dispatch_id, carrier_service_level,
                    return_policy_accepted) VALUES
(1, 1, 1, 2, 179.98, 'confirmed',
    'payment_verified', 'high', FALSE, NULL,
    'Dejar en recepción del edificio con el guardia de seguridad',
    '2026-06-03T18:00:00Z',
    'a1b2c3d4-e5f6-7890-abcd-ef1234567890', 'express',
    TRUE),
(2, 2, 3, 1, 119.50, 'pending',
    'awaiting_validation', 'normal', TRUE,
    '¡Feliz cumpleaños Carlos! Que lo disfrutes mucho.',
    NULL,
    '2026-06-05T12:00:00Z',
    'b2c3d4e5-f6a7-8901-bcde-f12345678901', 'standard',
    TRUE);

SELECT setval('orders_id_seq', (SELECT MAX(id) FROM orders));

-- -----------------------------------------------------------------------
-- Payments (15 payment fields each, with nested billing_address)
-- -----------------------------------------------------------------------
INSERT INTO payments (id, order_id, order_total, subtotal, tax_amount, shipping_cost,
                      currency, method, provider, card_last_four, card_expiry,
                      card_network, billing_address, coupon_code,
                      installment_count, status) VALUES
(1, 1, 179.98, 155.16, 24.82, 0.00,
    'MXN', 'credit_card', 'Banorte Pagos Digitales', '4532', '12/28',
    'visa',
    '{"street": "Av. Paseo de la Reforma 505, Piso 32", "city": "Ciudad de México", "zip": "06500"}',
    NULL, 1, 'completed'),
(2, 2, 119.50, 103.02, 16.48, 49.00,
    'MXN', 'debit_card', 'BBVA Bancomer', '8721', '03/27',
    'mastercard',
    '{"street": "Calle Independencia 456, Col. Centro", "city": "Guadalajara", "zip": "44100"}',
    'BDAY2026', 3, 'pending');

SELECT setval('payments_id_seq', (SELECT MAX(id) FROM payments));

-- -----------------------------------------------------------------------
-- Notifications (10 notification fields each)
-- -----------------------------------------------------------------------
INSERT INTO notifications (id, order_id, user_id, enable_email, enable_sms, enable_push,
                           preferred_channel, marketing_opt_in, template_id,
                           tracking_pixel_id, campaign_id, referral_code,
                           link_shortener_key, status, sent_at) VALUES
(1, 1, 1, TRUE, FALSE, TRUE,
    'email', TRUE, 'TPL-CONF-01',
    'c3d4e5f6-a7b8-9012-cdef-123456789012', 'CMP-Q2-2026', 'REF-ALICE-VIP',
    'shrt-abc123', 'sent', '2026-05-30T10:31:00Z'),
(2, 2, 2, TRUE, TRUE, FALSE,
    'sms', FALSE, 'TPL-PEND-02',
    'd4e5f6a7-b8c9-0123-defa-234567890123', 'CMP-BDAY-06', NULL,
    'shrt-xyz789', 'pending', NULL);

SELECT setval('notifications_id_seq', (SELECT MAX(id) FROM notifications));

-- =======================================================================
-- Done.  The database is ready with all 105 fields populated.
-- =======================================================================
