export class ApiError extends Error {
  status?: number;
  details?: unknown;

  constructor(message: string, status?: number, details?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.details = details;
  }
}

export interface HealthResponse {
  status: string;
  service: string;
}

export interface CountResponse {
  count: number;
}

export interface InventoryCountResponse extends CountResponse {
  in_stock_count: number;
}

export interface RecentUserSummary {
  id: number;
  email: string;
  first_name: string;
  active: boolean;
}

export interface ShippingAddress {
  street: string;
  city: string;
  state: string;
  zip: string;
  country: string;
}

export interface Customer {
  id: number;
  first_name: string;
  last_name: string;
  suffix: string | null;
  email: string;
  phone_number: string;
  dob: string;
  gender: string;
  loyalty_tier: string;
  loyalty_points: number;
  account_created_at: string;
  is_vip: boolean;
  language_preference: string;
  timezone: string;
  last_login_at: string | null;
  shipping_address: ShippingAddress;
  active: boolean;
}

export interface RequestMetadata {
  trace_id: string;
  request_id: string;
  source_system: string;
  api_version: string;
  environment: string;
  timestamp_utc: string;
  correlation_token: string;
  client_ip: string;
  user_agent: string;
  tenant_id: string;
}

export interface SecurityContext {
  fraud_score: number;
  session_id: string;
  device_fingerprint: string;
  ip_geolocation: {
    city: string;
    country: string;
  };
  is_authenticated: boolean;
  auth_method: string;
  mfa_verified: boolean;
  vpn_detected: boolean;
  request_node_id: string;
}

export interface UserResponse {
  metadata: RequestMetadata;
  security: SecurityContext;
  customer: Customer;
}

export interface UserValidationResponse {
  metadata: RequestMetadata;
  security: SecurityContext;
  valid: boolean;
  user_id: number;
  message: string;
  customer: Customer;
}

export interface Product {
  product_id: number;
  name: string;
  category: string;
  quantity: number;
  unit_price: number;
  weight_kg: number;
  dimensions: {
    length: number;
    width: number;
    height: number;
  };
  is_fragile: boolean;
  requires_refrigeration: boolean;
  warehouse_id: string;
  supplier_id: string;
  discount_applied: number;
  tax_rate: number;
  currency: string;
  manufacturer: string;
  ean13: string;
  stock_at_ordering: number;
  estimated_restock_date: string | null;
  material: string;
  color: string;
  size: string;
  warranty_period_months: number;
  is_subscription: boolean;
}

export interface ProductResponse {
  metadata: RequestMetadata;
  security: SecurityContext;
  item: Product;
}

export interface ProductAvailabilityResponse {
  metadata: RequestMetadata;
  security: SecurityContext;
  available: boolean;
  product_id: number;
  message: string;
  item: Product;
}

export interface OrderRecordSummary {
  id: number;
  user_id: number;
  product_id: number;
  quantity: number;
  total_price: number;
  status: string;
  internal_status: string;
  priority: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface PaymentRecordSummary {
  id: number;
  order_id: number;
  status: string;
  order_total: number;
  method: string;
  created_at: string | null;
}

export interface NotificationRecordSummary {
  id: number;
  order_id: number;
  user_id: number;
  status: string;
  preferred_channel: string;
  created_at: string | null;
  sent_at: string | null;
}

export interface OrderFlowDetails {
  id: number | null;
  internal_status: string;
  priority: string;
  is_gift: boolean;
  gift_message: string | null;
  special_instructions: string | null;
  estimated_delivery_at: string | null;
  warehouse_dispatch_id: string | null;
  carrier_service_level: string;
  return_policy_accepted: boolean;
}

export interface OrderCreateResponse {
  metadata: RequestMetadata;
  security: SecurityContext;
  status: string;
  message: string;
  order: OrderFlowDetails;
  downstream: Record<string, unknown>;
}

export interface ChaosConfigPayload {
  FAILURE_RATE: number;
  LATENCY_MS: number;
  TIMEOUT_RATE: number;
}

export interface PrometheusSample {
  metric: Record<string, string>;
  value: [number, string];
}

export interface PrometheusQueryResponse {
  status: string;
  data: {
    resultType: string;
    result: PrometheusSample[];
  };
}

const serviceBases = {
  user: "/api/user",
  inventory: "/api/inventory",
  order: "/api/order",
  payment: "/api/payment",
  notification: "/api/notification",
} as const;

type ServiceBaseKey = keyof typeof serviceBases;

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(init?.headers ?? {}),
    },
  });

  const contentType = response.headers.get("content-type") ?? "";
  const payload = contentType.includes("application/json")
    ? await response.json()
    : await response.text();

  if (!response.ok) {
    throw new ApiError(extractMessage(payload, response.status), response.status, payload);
  }

  return payload as T;
}

function extractMessage(payload: unknown, status: number): string {
  if (typeof payload === "string" && payload.trim()) {
    return payload;
  }

  if (payload && typeof payload === "object") {
    const detail = (payload as Record<string, unknown>).detail;
    if (typeof detail === "string" && detail.trim()) {
      return detail;
    }
    const message = (payload as Record<string, unknown>).message;
    if (typeof message === "string" && message.trim()) {
      return message;
    }
  }

  return `Request failed with status ${status}`;
}

export function getErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Unexpected error";
}

function pathFor(service: ServiceBaseKey, path: string) {
  return `${serviceBases[service]}${path}`;
}

export const api = {
  getUserHealth: () => requestJson<HealthResponse>(pathFor("user", "/health")),
  getInventoryHealth: () => requestJson<HealthResponse>(pathFor("inventory", "/health")),
  getOrderHealth: () => requestJson<HealthResponse>(pathFor("order", "/health")),
  getPaymentHealth: () => requestJson<HealthResponse>(pathFor("payment", "/health")),
  getNotificationHealth: () => requestJson<HealthResponse>(pathFor("notification", "/health")),

  getUsersCount: () => requestJson<CountResponse>(pathFor("user", "/users/count")),
  getRecentUsers: (limit = 10) =>
    requestJson<RecentUserSummary[]>(pathFor("user", `/users/recent?limit=${limit}`)),
  getUserById: (userId: number) =>
    requestJson<UserResponse>(pathFor("user", `/users/${userId}`)),
  validateUserById: (userId: number) =>
    requestJson<UserValidationResponse>(pathFor("user", `/users/${userId}/validate`)),

  getInventoryCount: () =>
    requestJson<InventoryCountResponse>(pathFor("inventory", "/inventory/count")),
  getInventoryList: (limit = 10) =>
    requestJson<Product[]>(pathFor("inventory", `/inventory?limit=${limit}`)),
  getStockProducts: (limit = 10) =>
    requestJson<Product[]>(pathFor("inventory", `/inventory/stock?limit=${limit}`)),
  getProductById: (productId: number) =>
    requestJson<ProductResponse>(pathFor("inventory", `/inventory/${productId}`)),
  getProductAvailability: (productId: number) =>
    requestJson<ProductAvailabilityResponse>(
      pathFor("inventory", `/inventory/${productId}/availability`),
    ),

  getOrdersCount: () => requestJson<CountResponse>(pathFor("order", "/orders/count")),
  getRecentOrders: (limit = 10) =>
    requestJson<OrderRecordSummary[]>(pathFor("order", `/orders/recent?limit=${limit}`)),
  getOrderById: (orderId: number) =>
    requestJson<OrderRecordSummary>(pathFor("order", `/orders/${orderId}`)),
  createOrder: (payload: { user_id: number; product_id: number; quantity: number }) =>
    requestJson<OrderCreateResponse>(pathFor("order", "/orders"), {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  getPaymentsCount: () => requestJson<CountResponse>(pathFor("payment", "/payments/count")),
  getRecentPayments: (limit = 10) =>
    requestJson<PaymentRecordSummary[]>(pathFor("payment", `/payments/recent?limit=${limit}`)),
  getPaymentByOrder: (orderId: number) =>
    requestJson<PaymentRecordSummary>(pathFor("payment", `/payments/by-order/${orderId}`)),

  getNotificationsCount: () =>
    requestJson<CountResponse>(pathFor("notification", "/notifications/count")),
  getRecentNotifications: (limit = 10) =>
    requestJson<NotificationRecordSummary[]>(
      pathFor("notification", `/notifications/recent?limit=${limit}`),
    ),
  getNotificationByOrder: (orderId: number) =>
    requestJson<NotificationRecordSummary>(
      pathFor("notification", `/notifications/by-order/${orderId}`),
    ),

  updateChaosConfig: (
    service: ServiceBaseKey,
    payload: ChaosConfigPayload,
  ) =>
    requestJson<{ message: string; config: ChaosConfigPayload }>(
      pathFor(service, "/chaos/config"),
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
    ),

  generateMockUsers: () =>
    requestJson<{ message: string }>(pathFor("user", "/users/generate"), {
      method: "POST",
    }),

  generateMockProducts: () =>
    requestJson<{ message: string }>(pathFor("inventory", "/inventory/generate"), {
      method: "POST",
    }),

  queryPrometheus: (query: string) =>
    requestJson<PrometheusQueryResponse>(
      `/api/prometheus/api/v1/query?query=${encodeURIComponent(query)}`,
    ),
};
