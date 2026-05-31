# Campos Extraídos por Servicio

Total de campos en el esquema: **105**

---

## Campos Globales (Todos los servicios)

Estos campos son consumidos por **todos** los servicios para registro, rastreo y seguridad.

### Metadata & Tracing (10)

| # | Campo | Faker |
|---|---|---|
| 1 | `trace_id` | `uuid4` |
| 2 | `request_id` | `uuid4` |
| 3 | `source_system` | `random_element` |
| 4 | `api_version` | `version` |
| 5 | `environment` | `random_element` |
| 6 | `timestamp_utc` | `iso8601` |
| 7 | `correlation_token` | `sha1` |
| 8 | `client_ip` | `ipv4` |
| 9 | `user_agent` | `user_agent` |
| 10 | `tenant_id` | `bothify` |

### Risk & Security (10)

| # | Campo | Faker |
|---|---|---|
| 1 | `security.fraud_score` | `pyint` |
| 2 | `security.session_id` | `uuid4` |
| 3 | `security.device_fingerprint` | `sha1` |
| 4 | `security.ip_geolocation.city` | `city` |
| 5 | `security.ip_geolocation.country` | `country_code` |
| 6 | `security.is_authenticated` | `boolean` |
| 7 | `security.auth_method` | `random_element` |
| 8 | `security.mfa_verified` | `boolean` |
| 9 | `security.vpn_detected` | `boolean` |
| 10 | `security.request_node_id` | `bothify` |

---

## order-service (Orchestrator)

Campos propios + campos que consume de otras categorías.

### Campos propios – Logistics & Metadata (10)

| # | Campo | Faker |
|---|---|---|
| 1 | `order.id` | `bothify` |
| 2 | `order.internal_status` | `random_element` |
| 3 | `order.priority` | `random_element` |
| 4 | `order.is_gift` | `boolean` |
| 5 | `order.gift_message` | `sentence` |
| 6 | `order.special_instructions` | `text` |
| 7 | `order.estimated_delivery_at` | `future_datetime` |
| 8 | `order.warehouse_dispatch_id` | `uuid4` |
| 9 | `order.carrier_service_level` | `random_element` |
| 10 | `order.return_policy_accepted` | `boolean` |

### Campos que consume de otras categorías

| Campo | Uso |
|---|---|
| `items[].weight_kg` | Calcula peso total para decidir transportista |
| `items[].dimensions.*` | Calcula dimensiones totales |
| `order.carrier_service_level` | Decide si requiere transportista especial |
| `security.fraud_score` | Verifica umbral antes de llamar a payment-service |
| `order.warehouse_dispatch_id` | Enriquece basándose en `warehouse_id` del inventario |

---

## user-service

### Campos propios – Customer Profile (20)

| # | Campo | Faker |
|---|---|---|
| 1 | `customer.id` | `random_number` |
| 2 | `customer.first_name` | `first_name` |
| 3 | `customer.last_name` | `last_name` |
| 4 | `customer.suffix` | `suffix` |
| 5 | `customer.email` | `email` |
| 6 | `customer.phone_number` | `phone_number` |
| 7 | `customer.dob` | `date_of_birth` |
| 8 | `customer.gender` | `random_element` |
| 9 | `customer.loyalty_tier` | `random_element` |
| 10 | `customer.loyalty_points` | `pyint` |
| 11 | `customer.account_created_at` | `past_datetime` |
| 12 | `customer.is_vip` | `boolean` |
| 13 | `customer.language_preference` | `language_code` |
| 14 | `customer.timezone` | `timezone` |
| 15 | `customer.last_login_at` | `past_datetime` |
| 16 | `customer.shipping_address.street` | `street_address` |
| 17 | `customer.shipping_address.city` | `city` |
| 18 | `customer.shipping_address.state` | `state` |
| 19 | `customer.shipping_address.zip` | `postcode` |
| 20 | `customer.shipping_address.country` | `country_code` |

### Campos que consume de otras categorías

| Campo | Uso |
|---|---|
| `customer.loyalty_tier` | Cruza referencias con puntos históricos |
| `client_ip` | Compara con `customer.timezone` para detectar discrepancias |
| `customer.timezone` | Verificación de seguridad geográfica |

---

## inventory-service

### Campos propios – Inventory & Product Details (25)

| # | Campo | Faker |
|---|---|---|
| 1 | `items[].product_id` | `random_number` |
| 2 | `items[].name` | `catch_phrase` |
| 3 | `items[].category` | `random_element` |
| 4 | `items[].quantity` | `pyint` |
| 5 | `items[].unit_price` | `pyfloat` |
| 6 | `items[].weight_kg` | `pyfloat` |
| 7 | `items[].dimensions.length` | `pyfloat` |
| 8 | `items[].dimensions.width` | `pyfloat` |
| 9 | `items[].dimensions.height` | `pyfloat` |
| 10 | `items[].is_fragile` | `boolean` |
| 11 | `items[].requires_refrigeration` | `boolean` |
| 12 | `items[].warehouse_id` | `bothify` |
| 13 | `items[].supplier_id` | `bothify` |
| 14 | `items[].discount_applied` | `pyfloat` |
| 15 | `items[].tax_rate` | `pyfloat` |
| 16 | `items[].currency` | `currency_code` |
| 17 | `items[].manufacturer` | `company` |
| 18 | `items[].ean13` | `ean13` |
| 19 | `items[].stock_at_ordering` | `pyint` |
| 20 | `items[].estimated_restock_date` | `future_date` |
| 21 | `items[].material` | `random_element` |
| 22 | `items[].color` | `color_name` |
| 23 | `items[].size` | `random_element` |
| 24 | `items[].warranty_period_months` | `pyint` |
| 25 | `items[].is_subscription` | `boolean` |

### Campos que consume de otras categorías

| Campo | Uso |
|---|---|
| `items[].dimensions.*` | Valida si caben en la capacidad del almacén |
| `items[].warehouse_id` | Referencia de ubicación de inventario |
| `items[].unit_price` | Guardia de precios vs. registro maestro |
| `items[].product_id` | Referencia para validación de precios |

---

## payment-service

### Campos propios – Payment & Billing (15)

| # | Campo | Faker |
|---|---|---|
| 1 | `payment.order_total` | `pyfloat` |
| 2 | `payment.subtotal` | `pyfloat` |
| 3 | `payment.tax_amount` | `pyfloat` |
| 4 | `payment.shipping_cost` | `pyfloat` |
| 5 | `payment.currency` | `currency_code` |
| 6 | `payment.method` | `random_element` |
| 7 | `payment.provider` | `company` |
| 8 | `payment.card_last_four` | `credit_card_number` |
| 9 | `payment.card_expiry` | `credit_card_expire` |
| 10 | `payment.card_network` | `credit_card_provider` |
| 11 | `payment.billing_address.street` | `street_address` |
| 12 | `payment.billing_address.city` | `city` |
| 13 | `payment.billing_address.zip` | `postcode` |
| 14 | `payment.coupon_code` | `lexify` |
| 15 | `payment.installment_count` | `random_int` |

### Campos que consume de otras categorías

| Campo | Uso |
|---|---|
| `security.device_fingerprint` | Integración de fraude – aprobar/rechazar transacción |
| `security.vpn_detected` | Integración de fraude – señal de riesgo |
| `payment.coupon_code` | Cálculo simulado de descuento |
| `payment.order_total` | Verificación de que el total coincide tras aplicar cupón |

---

## notification-service

### Campos propios – Notifications & Marketing (10)

| # | Campo | Faker |
|---|---|---|
| 1 | `notifications.enable_email` | `boolean` |
| 2 | `notifications.enable_sms` | `boolean` |
| 3 | `notifications.enable_push` | `boolean` |
| 4 | `notifications.preferred_channel` | `random_element` |
| 5 | `notifications.marketing_opt_in` | `boolean` |
| 6 | `notifications.template_id` | `bothify` |
| 7 | `notifications.tracking_pixel_id` | `uuid4` |
| 8 | `notifications.campaign_id` | `bothify` |
| 9 | `notifications.referral_code` | `lexify` |
| 10 | `notifications.link_shortener_key` | `lexify` |

### Campos que consume de otras categorías

| Campo | Uso |
|---|---|
| `notifications.preferred_channel` | Decide qué proveedor de envío simular |
| `customer.first_name` | Personalización del mensaje |
| `customer.language_preference` | Idioma del mensaje |
| `order.gift_message` | Incluido en el cuerpo del mensaje final |

---

## Resumen por Servicio

| Servicio | Campos Propios | Campos Consumidos de Otros | Total |
|---|---|---|---|
| **Globales** (todos) | 20 | — | 20 |
| **order-service** | 10 | 5 | 15 |
| **user-service** | 20 | 3 | 23 |
| **inventory-service** | 25 | 4 | 29 |
| **payment-service** | 15 | 4 | 19 |
| **notification-service** | 10 | 4 | 14 |
| **Total campos únicos** | **105** | | |
