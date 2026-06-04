import { useEffect, useMemo, useState } from "react";
import {
  type ChaosConfigPayload,
  type NotificationRecordSummary,
  type OrderCreateResponse,
  type OrderRecordSummary,
  type PaymentRecordSummary,
  type Product,
  type ProductAvailabilityResponse,
  type ProductResponse,
  type RecentUserSummary,
  type UserResponse,
  type UserValidationResponse,
  api,
  getErrorMessage,
} from "../api/client";
import { DataTable } from "../components/DataTable";
import { MetricCard } from "../components/MetricCard";
import { Panel } from "../components/Panel";
import { ServiceCard } from "../components/ServiceCard";
import { StatusBadge } from "../components/StatusBadge";

type ServiceTone = "success" | "error" | "warning" | "neutral" | "info";

interface ServiceStatusCard {
  key: string;
  name: string;
  port: string;
  description: string;
  statusLabel: string;
  tone: ServiceTone;
  lastChecked: string;
  actionLabel: string;
  actionHref?: string;
}

interface CountsState {
  users: number | null;
  products: number | null;
  productsWithStock: number | null;
  orders: number | null;
  payments: number | null;
  notifications: number | null;
}

interface LookupState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
}

interface SectionErrors {
  users?: string;
  inventory?: string;
  orders?: string;
  payments?: string;
  notifications?: string;
  counts?: string;
}

const SERVICE_CONFIG = [
  {
    key: "user-service",
    label: "user-service",
    port: "8001",
    proxyHealth: () => api.getUserHealth(),
    docsHref: "http://localhost:8001/docs",
    description: "Valida usuarios y expone perfiles Faker persistidos.",
  },
  {
    key: "inventory-service",
    label: "inventory-service",
    port: "8002",
    proxyHealth: () => api.getInventoryHealth(),
    docsHref: "http://localhost:8002/docs",
    description: "Consulta disponibilidad y reserva inventario.",
  },
  {
    key: "order-service",
    label: "order-service",
    port: "8000",
    proxyHealth: () => api.getOrderHealth(),
    docsHref: "http://localhost:8000/docs",
    description: "Orquesta el flujo completo de orden.",
  },
  {
    key: "payment-service",
    label: "payment-service",
    port: "8003",
    proxyHealth: () => api.getPaymentHealth(),
    docsHref: "http://localhost:8003/docs",
    description: "Registra pagos y resultados antifraude.",
  },
  {
    key: "notification-service",
    label: "notification-service",
    port: "8004",
    proxyHealth: () => api.getNotificationHealth(),
    docsHref: "http://localhost:8004/docs",
    description: "Persiste notificaciones y su canal final.",
  },
] as const;

const CHAOS_SERVICE_MAP = {
  "user-service": "user",
  "inventory-service": "inventory",
  "order-service": "order",
  "payment-service": "payment",
  "notification-service": "notification",
} as const;

const seedEnabled = (import.meta.env.VITE_SEED_ENABLED ?? "true").toLowerCase() === "true";
const seedUsersTarget = Number(import.meta.env.VITE_SEED_USERS_COUNT ?? "50000");

function formatTimestamp(timestamp: string) {
  return new Date(timestamp).toLocaleTimeString("es-MX", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatCurrency(value: number) {
  return new Intl.NumberFormat("es-MX", {
    style: "currency",
    currency: "MXN",
    maximumFractionDigits: 2,
  }).format(value);
}

function captureError(error: unknown) {
  return getErrorMessage(error);
}

function settle<T>(promise: Promise<T>): Promise<T | Error> {
  return promise.catch((error: unknown) =>
    error instanceof Error ? error : new Error(captureError(error)),
  );
}

export function DashboardPage() {
  const [refreshing, setRefreshing] = useState(false);
  const [counts, setCounts] = useState<CountsState>({
    users: null,
    products: null,
    productsWithStock: null,
    orders: null,
    payments: null,
    notifications: null,
  });
  const [services, setServices] = useState<ServiceStatusCard[]>([]);
  const [recentUsers, setRecentUsers] = useState<RecentUserSummary[]>([]);
  const [stockProducts, setStockProducts] = useState<Product[]>([]);
  const [recentOrders, setRecentOrders] = useState<OrderRecordSummary[]>([]);
  const [recentPayments, setRecentPayments] = useState<PaymentRecordSummary[]>([]);
  const [recentNotifications, setRecentNotifications] = useState<NotificationRecordSummary[]>([]);
  const [sectionErrors, setSectionErrors] = useState<SectionErrors>({});

  const [userIdInput, setUserIdInput] = useState("50000");
  const [userLookup, setUserLookup] = useState<LookupState<UserResponse>>({
    data: null,
    error: null,
    loading: false,
  });
  const [userValidation, setUserValidation] = useState<LookupState<UserValidationResponse>>({
    data: null,
    error: null,
    loading: false,
  });

  const [productIdInput, setProductIdInput] = useState("1");
  const [productLookup, setProductLookup] = useState<LookupState<ProductResponse>>({
    data: null,
    error: null,
    loading: false,
  });
  const [productAvailability, setProductAvailability] = useState<LookupState<ProductAvailabilityResponse>>({
    data: null,
    error: null,
    loading: false,
  });

  const [orderForm, setOrderForm] = useState({
    userId: "50000",
    productId: "1",
    quantity: "1",
  });
  const [orderResult, setOrderResult] = useState<OrderCreateResponse | null>(null);
  const [orderError, setOrderError] = useState<string | null>(null);
  const [orderSubmitting, setOrderSubmitting] = useState(false);

  const [chaosForm, setChaosForm] = useState({
    service: "order-service",
    failureRate: "0",
    latencyMs: "0",
    timeoutRate: "0",
  });
  const [chaosMessage, setChaosMessage] = useState<string | null>(null);
  const [chaosError, setChaosError] = useState<string | null>(null);
  const [chaosSubmitting, setChaosSubmitting] = useState(false);

  useEffect(() => {
    void refreshDashboard();
    const timer = window.setInterval(() => {
      void refreshDashboard();
    }, 15000);
    return () => window.clearInterval(timer);
  }, []);

  async function refreshDashboard() {
    setRefreshing(true);

    const checkedAt = new Date().toISOString();
    const errors: SectionErrors = {};

    const [
      userCountResult,
      inventoryCountResult,
      orderCountResult,
      paymentCountResult,
      notificationCountResult,
      recentUsersResult,
      stockProductsResult,
      recentOrdersResult,
      recentPaymentsResult,
      recentNotificationsResult,
      serviceHealthResults,
    ] = await Promise.all([
      settle(api.getUsersCount()),
      settle(api.getInventoryCount()),
      settle(api.getOrdersCount()),
      settle(api.getPaymentsCount()),
      settle(api.getNotificationsCount()),
      settle(api.getRecentUsers(10)),
      settle(api.getStockProducts(10)),
      settle(api.getRecentOrders(10)),
      settle(api.getRecentPayments(10)),
      settle(api.getRecentNotifications(10)),
      Promise.all(
        SERVICE_CONFIG.map(async (service) => {
          try {
            await service.proxyHealth();
            return {
              ...service,
              statusLabel: "OK",
              tone: "success" as const,
            };
          } catch (error) {
            return {
              ...service,
              statusLabel: captureError(error),
              tone: "error" as const,
            };
          }
        }),
      ),
    ]);

    if (
      userCountResult instanceof Error ||
      inventoryCountResult instanceof Error ||
      orderCountResult instanceof Error ||
      paymentCountResult instanceof Error ||
      notificationCountResult instanceof Error
    ) {
      errors.counts = "No se pudieron cargar todos los conteos del dashboard.";
    }

    const nextUsersCount = userCountResult instanceof Error ? null : userCountResult.count;
    const nextProductsCount =
      inventoryCountResult instanceof Error ? null : inventoryCountResult.count;
    const nextProductsWithStock =
      inventoryCountResult instanceof Error ? null : inventoryCountResult.in_stock_count;
    const nextOrdersCount = orderCountResult instanceof Error ? null : orderCountResult.count;
    const nextPaymentsCount =
      paymentCountResult instanceof Error ? null : paymentCountResult.count;
    const nextNotificationsCount =
      notificationCountResult instanceof Error ? null : notificationCountResult.count;

    setCounts({
      users: nextUsersCount,
      products: nextProductsCount,
      productsWithStock: nextProductsWithStock,
      orders: nextOrdersCount,
      payments: nextPaymentsCount,
      notifications: nextNotificationsCount,
    });

    if (recentUsersResult instanceof Error) {
      errors.users = captureError(recentUsersResult);
      setRecentUsers([]);
    } else {
      setRecentUsers(recentUsersResult);
    }

    if (stockProductsResult instanceof Error) {
      errors.inventory = captureError(stockProductsResult);
      setStockProducts([]);
    } else {
      setStockProducts(stockProductsResult);
    }

    if (recentOrdersResult instanceof Error) {
      errors.orders = captureError(recentOrdersResult);
      setRecentOrders([]);
    } else {
      setRecentOrders(recentOrdersResult);
    }

    if (recentPaymentsResult instanceof Error) {
      errors.payments = captureError(recentPaymentsResult);
      setRecentPayments([]);
    } else {
      setRecentPayments(recentPaymentsResult);
    }

    if (recentNotificationsResult instanceof Error) {
      errors.notifications = captureError(recentNotificationsResult);
      setRecentNotifications([]);
    } else {
      setRecentNotifications(recentNotificationsResult);
    }

    setSectionErrors(errors);
    setServices([
      ...serviceHealthResults.map((service) => ({
        key: service.key,
        name: service.label,
        port: service.port,
        description: service.description,
        statusLabel: service.statusLabel,
        tone: service.tone,
        lastChecked: `Última revisión ${formatTimestamp(checkedAt)}`,
        actionLabel: "Swagger",
        actionHref: service.docsHref,
      })),
      {
        key: "data-seeder",
        name: "data-seeder",
        port: "job",
        description: seedEnabled
          ? "Seeder automático de usuarios Faker al iniciar Compose."
          : "Seeder desactivado por configuración.",
        statusLabel: seedEnabled
          ? nextUsersCount !== null && nextUsersCount >= seedUsersTarget
            ? "Completado"
            : "Pendiente"
          : "Desactivado",
        tone: seedEnabled
          ? nextUsersCount !== null && nextUsersCount >= seedUsersTarget
            ? "success"
            : "warning"
          : "neutral",
        lastChecked: `Objetivo ${seedUsersTarget.toLocaleString("es-MX")} usuarios`,
        actionLabel: "No API",
      },
    ]);

    setRefreshing(false);
  }

  async function handleUserLookup(mode: "search" | "validate") {
    const parsed = Number(userIdInput);
    if (!Number.isInteger(parsed) || parsed < 1) {
      const message = "Ingresa un User ID válido.";
      if (mode === "search") {
        setUserLookup({ data: null, error: message, loading: false });
      } else {
        setUserValidation({ data: null, error: message, loading: false });
      }
      return;
    }

    if (mode === "search") {
      setUserLookup({ data: null, error: null, loading: true });
      try {
        const data = await api.getUserById(parsed);
        setUserLookup({ data, error: null, loading: false });
      } catch (error) {
        setUserLookup({ data: null, error: captureError(error), loading: false });
      }
      return;
    }

    setUserValidation({ data: null, error: null, loading: true });
    try {
      const data = await api.validateUserById(parsed);
      setUserValidation({ data, error: null, loading: false });
    } catch (error) {
      setUserValidation({ data: null, error: captureError(error), loading: false });
    }
  }

  async function handleProductLookup(mode: "search" | "availability") {
    const parsed = Number(productIdInput);
    if (!Number.isInteger(parsed) || parsed < 1) {
      const message = "Ingresa un Product ID válido.";
      if (mode === "search") {
        setProductLookup({ data: null, error: message, loading: false });
      } else {
        setProductAvailability({ data: null, error: message, loading: false });
      }
      return;
    }

    if (mode === "search") {
      setProductLookup({ data: null, error: null, loading: true });
      try {
        const data = await api.getProductById(parsed);
        setProductLookup({ data, error: null, loading: false });
      } catch (error) {
        setProductLookup({ data: null, error: captureError(error), loading: false });
      }
      return;
    }

    setProductAvailability({ data: null, error: null, loading: true });
    try {
      const data = await api.getProductAvailability(parsed);
      setProductAvailability({ data, error: null, loading: false });
    } catch (error) {
      setProductAvailability({ data: null, error: captureError(error), loading: false });
    }
  }

  async function submitOrder() {
    const payload = {
      user_id: Number(orderForm.userId),
      product_id: Number(orderForm.productId),
      quantity: Number(orderForm.quantity),
    };

    if (
      !Number.isInteger(payload.user_id) ||
      !Number.isInteger(payload.product_id) ||
      !Number.isInteger(payload.quantity) ||
      payload.user_id < 1 ||
      payload.product_id < 1 ||
      payload.quantity < 1
    ) {
      setOrderError("Completa User ID, Product ID y Quantity con valores válidos.");
      return;
    }

    setOrderSubmitting(true);
    setOrderError(null);

    try {
      const response = await api.createOrder(payload);
      setOrderResult(response);
      setOrderError(null);
      await refreshDashboard();
    } catch (error) {
      setOrderResult(null);
      setOrderError(captureError(error));
    } finally {
      setOrderSubmitting(false);
    }
  }

  async function applyChaos(reset = false) {
    const payload: ChaosConfigPayload = reset
      ? { FAILURE_RATE: 0, LATENCY_MS: 0, TIMEOUT_RATE: 0 }
      : {
          FAILURE_RATE: Number(chaosForm.failureRate),
          LATENCY_MS: Number(chaosForm.latencyMs),
          TIMEOUT_RATE: Number(chaosForm.timeoutRate),
        };

    if (
      payload.FAILURE_RATE < 0 ||
      payload.FAILURE_RATE > 1 ||
      payload.TIMEOUT_RATE < 0 ||
      payload.TIMEOUT_RATE > 1 ||
      payload.LATENCY_MS < 0
    ) {
      setChaosError("FAILURE_RATE y TIMEOUT_RATE deben estar entre 0 y 1. LATENCY_MS debe ser >= 0.");
      return;
    }

    setChaosSubmitting(true);
    setChaosError(null);
    setChaosMessage(null);

    try {
      const serviceKey = chaosForm.service as keyof typeof CHAOS_SERVICE_MAP;
      const result = await api.updateChaosConfig(CHAOS_SERVICE_MAP[serviceKey], payload);
      setChaosMessage(result.message);
      if (reset) {
        setChaosForm((current) => ({
          ...current,
          failureRate: "0",
          latencyMs: "0",
          timeoutRate: "0",
        }));
      }
    } catch (error) {
      setChaosError(captureError(error));
    } finally {
      setChaosSubmitting(false);
    }
  }

  const seederStatus = useMemo(() => {
    if (!seedEnabled) {
      return { label: "Desactivado", tone: "neutral" as const };
    }

    if (counts.users === null) {
      return { label: "Cargando", tone: "warning" as const };
    }

    if (counts.users >= seedUsersTarget) {
      return { label: "Objetivo alcanzado", tone: "success" as const };
    }

    return { label: "Incompleto", tone: "warning" as const };
  }, [counts.users]);

  const orderFlow = useMemo(() => {
    if (!orderResult) {
      return [];
    }

    const downstream = orderResult.downstream ?? {};
    const userValid = Boolean((downstream.user as { valid?: boolean } | undefined)?.valid);
    const inventoryAvailable = Boolean(
      (downstream.inventory as { available?: boolean } | undefined)?.available,
    );
    const paymentSuccess =
      (downstream.payment as { status?: string } | undefined)?.status === "success";
    const notificationSent =
      (downstream.notification as { status?: string } | undefined)?.status === "sent";
    const orderPersisted = Boolean(orderResult.order?.id);

    return [
      {
        label: "Usuario validado",
        tone: userValid ? "success" : "error",
      },
      {
        label: "Inventario confirmado",
        tone: inventoryAvailable ? "success" : "error",
      },
      {
        label: "Pago completado",
        tone: paymentSuccess ? "success" : "error",
      },
      {
        label: "Notificación enviada",
        tone: notificationSent ? "success" : "warning",
      },
      {
        label: "Orden guardada",
        tone: orderPersisted ? "success" : "error",
      },
    ];
  }, [orderResult]);

  return (
    <main className="app-shell">
      <header className="hero">
        <div>
          <p className="hero__eyebrow">Resilencia-Kubernetes</p>
          <h1>Control Panel</h1>
          <p className="hero__copy">
            Dashboard técnico para validar microservicios, datos Faker, flujo de órdenes,
            observabilidad y controles básicos de resiliencia.
          </p>
        </div>
        <div className="hero__actions">
          <button className="button button--primary" onClick={() => void refreshDashboard()}>
            {refreshing ? "Actualizando..." : "Refrescar panel"}
          </button>
          <a className="button button--secondary" href="http://localhost:16686" target="_blank" rel="noreferrer">
            Abrir Jaeger
          </a>
        </div>
      </header>

      <section className="metrics-grid">
        <MetricCard
          title="Usuarios totales"
          value={counts.users?.toLocaleString("es-MX") ?? "—"}
          hint={`Objetivo seed ${seedUsersTarget.toLocaleString("es-MX")}`}
        />
        <MetricCard
          title="Productos"
          value={counts.products?.toLocaleString("es-MX") ?? "—"}
          hint="Conteo total del catálogo"
        />
        <MetricCard
          title="Productos con stock"
          value={counts.productsWithStock?.toLocaleString("es-MX") ?? "—"}
          hint="Disponibles para nuevas órdenes"
        />
        <MetricCard
          title="Órdenes"
          value={counts.orders?.toLocaleString("es-MX") ?? "—"}
          hint="Persistidas en PostgreSQL"
        />
        <MetricCard
          title="Pagos"
          value={counts.payments?.toLocaleString("es-MX") ?? "—"}
          hint="Registros completados o pendientes"
        />
        <MetricCard
          title="Notificaciones"
          value={counts.notifications?.toLocaleString("es-MX") ?? "—"}
          hint="Eventos enviados o pendientes"
        />
      </section>

      <Panel
        title="Estado de servicios"
        subtitle="Health checks del stack principal y estado derivado del data-seeder."
      >
        <div className="services-grid">
          {services.map(({ key, ...service }) => (
            <ServiceCard key={key} {...service} />
          ))}
        </div>
      </Panel>

      <div className="two-column-grid">
        <Panel
          title="Datos Faker y usuarios"
          subtitle="Búsqueda por ID, validación y últimos usuarios cargados por data-seeder."
        >
          <div className="toolbar">
            <div className="toolbar__group">
              <label>
                <span>User ID</span>
                <input
                  value={userIdInput}
                  onChange={(event) => setUserIdInput(event.target.value)}
                  placeholder="50000"
                />
              </label>
              <button
                className="button button--primary"
                onClick={() => void handleUserLookup("search")}
              >
                {userLookup.loading ? "Buscando..." : "Buscar usuario"}
              </button>
              <button
                className="button button--secondary"
                onClick={() => void handleUserLookup("validate")}
              >
                {userValidation.loading ? "Validando..." : "Validar usuario"}
              </button>
            </div>
            <div className="seeder-pill">
              <StatusBadge label={seederStatus.label} tone={seederStatus.tone} />
              <span>
                {seedEnabled ? "SEED_ENABLED=true" : "SEED_ENABLED=false"} | SEED_USERS_COUNT=
                {seedUsersTarget}
              </span>
            </div>
          </div>

          {userLookup.error ? <p className="inline-error">{userLookup.error}</p> : null}
          {userLookup.data ? (
            <div className="result-card">
              <div>
                <p className="result-card__title">
                  {userLookup.data.customer.first_name} {userLookup.data.customer.last_name}
                </p>
                <p className="result-card__meta">{userLookup.data.customer.email}</p>
              </div>
              <StatusBadge
                label={userLookup.data.customer.active ? "Activo" : "Inactivo"}
                tone={userLookup.data.customer.active ? "success" : "warning"}
              />
            </div>
          ) : null}

          {userValidation.error ? <p className="inline-error">{userValidation.error}</p> : null}
          {userValidation.data ? (
            <div className="result-card">
              <div>
                <p className="result-card__title">Validación de usuario #{userValidation.data.user_id}</p>
                <p className="result-card__meta">{userValidation.data.message}</p>
              </div>
              <StatusBadge
                label={userValidation.data.valid ? "Válido" : "No activo"}
                tone={userValidation.data.valid ? "success" : "warning"}
              />
            </div>
          ) : null}

          {sectionErrors.users ? <p className="inline-error">{sectionErrors.users}</p> : null}
          <DataTable
            columns={[
              { header: "ID", cell: (row: RecentUserSummary) => row.id },
              { header: "Email", cell: (row: RecentUserSummary) => row.email },
              { header: "First Name", cell: (row: RecentUserSummary) => row.first_name },
              {
                header: "Active",
                cell: (row: RecentUserSummary) => (
                  <StatusBadge
                    label={row.active ? "true" : "false"}
                    tone={row.active ? "success" : "warning"}
                  />
                ),
              },
            ]}
            rows={recentUsers}
            keyExtractor={(row) => row.id}
            emptyMessage="No se pudieron cargar usuarios recientes."
          />
        </Panel>

        <Panel
          title="Inventario"
          subtitle="Productos con stock, consulta por ID y verificación de disponibilidad."
        >
          <div className="toolbar">
            <div className="toolbar__group">
              <label>
                <span>Product ID</span>
                <input
                  value={productIdInput}
                  onChange={(event) => setProductIdInput(event.target.value)}
                  placeholder="1"
                />
              </label>
              <button
                className="button button--primary"
                onClick={() => void handleProductLookup("search")}
              >
                {productLookup.loading ? "Consultando..." : "Buscar producto"}
              </button>
              <button
                className="button button--secondary"
                onClick={() => void handleProductLookup("availability")}
              >
                {productAvailability.loading ? "Validando..." : "Ver disponibilidad"}
              </button>
            </div>
          </div>

          {productLookup.error ? <p className="inline-error">{productLookup.error}</p> : null}
          {productLookup.data ? (
            <div className="result-card">
              <div>
                <p className="result-card__title">{productLookup.data.item.name}</p>
                <p className="result-card__meta">
                  ID {productLookup.data.item.product_id} | {formatCurrency(productLookup.data.item.unit_price)}
                </p>
              </div>
              <StatusBadge
                label={`Stock ${productLookup.data.item.quantity}`}
                tone={productLookup.data.item.quantity > 0 ? "success" : "warning"}
              />
            </div>
          ) : null}

          {productAvailability.error ? (
            <p className="inline-error">{productAvailability.error}</p>
          ) : null}
          {productAvailability.data ? (
            <div className="result-card">
              <div>
                <p className="result-card__title">Disponibilidad del producto #{productAvailability.data.product_id}</p>
                <p className="result-card__meta">{productAvailability.data.message}</p>
              </div>
              <StatusBadge
                label={productAvailability.data.available ? "Disponible" : "Sin stock"}
                tone={productAvailability.data.available ? "success" : "warning"}
              />
            </div>
          ) : null}

          {sectionErrors.inventory ? <p className="inline-error">{sectionErrors.inventory}</p> : null}
          <DataTable
            columns={[
              { header: "ID", cell: (row: Product) => row.product_id },
              { header: "Nombre", cell: (row: Product) => row.name },
              { header: "Cantidad", cell: (row: Product) => row.quantity, align: "right" },
              {
                header: "Precio",
                cell: (row: Product) => formatCurrency(row.unit_price),
                align: "right",
              },
              {
                header: "Estado",
                cell: (row: Product) => (
                  <StatusBadge
                    label={row.quantity > 0 ? "Disponible" : "Sin stock"}
                    tone={row.quantity > 0 ? "success" : "warning"}
                  />
                ),
              },
            ]}
            rows={stockProducts}
            keyExtractor={(row) => row.product_id}
            emptyMessage="No se pudieron cargar productos con stock."
          />
        </Panel>
      </div>

      <Panel
        title="Simulación de orden"
        subtitle="Formulario mínimo para ejecutar POST /orders y revisar cada paso del flujo."
      >
        <div className="order-grid">
          <div className="order-form">
            <label>
              <span>User ID</span>
              <input
                value={orderForm.userId}
                onChange={(event) =>
                  setOrderForm((current) => ({ ...current, userId: event.target.value }))
                }
              />
            </label>
            <label>
              <span>Product ID</span>
              <input
                value={orderForm.productId}
                onChange={(event) =>
                  setOrderForm((current) => ({ ...current, productId: event.target.value }))
                }
              />
            </label>
            <label>
              <span>Quantity</span>
              <input
                value={orderForm.quantity}
                onChange={(event) =>
                  setOrderForm((current) => ({ ...current, quantity: event.target.value }))
                }
              />
            </label>
            <div className="order-form__actions">
              <button className="button button--primary" onClick={() => void submitOrder()}>
                {orderSubmitting ? "Creando..." : "Crear orden"}
              </button>
              <button
                className="button button--secondary"
                onClick={() =>
                  setOrderForm({
                    userId: "50000",
                    productId: "1",
                    quantity: "1",
                  })
                }
              >
                Restablecer ejemplo
              </button>
            </div>
            {orderError ? <p className="inline-error">{orderError}</p> : null}
          </div>

          <div className="order-result">
            {orderResult ? (
              <>
                <div className="result-card">
                  <div>
                    <p className="result-card__title">Orden #{orderResult.order.id ?? "N/A"}</p>
                    <p className="result-card__meta">{orderResult.message}</p>
                  </div>
                  <StatusBadge
                    label={orderResult.status}
                    tone={orderResult.status === "success" ? "success" : orderResult.status === "warning" ? "warning" : "error"}
                  />
                </div>

                <div className="flow-grid">
                  {orderFlow.map((step) => (
                    <div key={step.label} className="flow-step">
                      <StatusBadge label={step.label} tone={step.tone as ServiceTone} />
                    </div>
                  ))}
                </div>

                <div className="result-details">
                  <p><strong>internal_status:</strong> {orderResult.order.internal_status}</p>
                  <p><strong>priority:</strong> {orderResult.order.priority}</p>
                  <p><strong>carrier:</strong> {orderResult.order.carrier_service_level}</p>
                  <p><strong>ETA:</strong> {orderResult.order.estimated_delivery_at ?? "N/A"}</p>
                  <p>
                    <strong>payment status:</strong>{" "}
                    {String((orderResult.downstream.payment as { status?: string } | undefined)?.status ?? "N/A")}
                  </p>
                  <p>
                    <strong>notification status:</strong>{" "}
                    {String((orderResult.downstream.notification as { status?: string } | undefined)?.status ?? "N/A")}
                  </p>
                </div>
              </>
            ) : (
              <div className="empty-card">
                <p>Ejecuta una orden para ver el detalle del flujo y la persistencia.</p>
              </div>
            )}
          </div>
        </div>
      </Panel>

      <div className="three-column-grid">
        <Panel title="Órdenes recientes" subtitle="Máximo 10 registros, ordenados por created_at desc.">
          {sectionErrors.orders ? <p className="inline-error">{sectionErrors.orders}</p> : null}
          <DataTable
            columns={[
              { header: "ID", cell: (row: OrderRecordSummary) => row.id },
              { header: "User", cell: (row: OrderRecordSummary) => row.user_id },
              { header: "Product", cell: (row: OrderRecordSummary) => row.product_id },
              { header: "Qty", cell: (row: OrderRecordSummary) => row.quantity, align: "right" },
              {
                header: "Total",
                cell: (row: OrderRecordSummary) => formatCurrency(row.total_price),
                align: "right",
              },
              { header: "Status", cell: (row: OrderRecordSummary) => row.status },
              { header: "Internal", cell: (row: OrderRecordSummary) => row.internal_status },
            ]}
            rows={recentOrders}
            keyExtractor={(row) => row.id}
            emptyMessage="No se pudieron cargar órdenes recientes."
          />
        </Panel>

        <Panel title="Pagos recientes" subtitle="Últimos pagos persistidos en PostgreSQL.">
          {sectionErrors.payments ? <p className="inline-error">{sectionErrors.payments}</p> : null}
          <DataTable
            columns={[
              { header: "ID", cell: (row: PaymentRecordSummary) => row.id },
              { header: "Order", cell: (row: PaymentRecordSummary) => row.order_id },
              { header: "Status", cell: (row: PaymentRecordSummary) => row.status },
              {
                header: "Total",
                cell: (row: PaymentRecordSummary) => formatCurrency(row.order_total),
                align: "right",
              },
              { header: "Method", cell: (row: PaymentRecordSummary) => row.method },
            ]}
            rows={recentPayments}
            keyExtractor={(row) => row.id}
            emptyMessage="No se pudieron cargar pagos recientes."
          />
        </Panel>

        <Panel title="Notificaciones recientes" subtitle="Registros emitidos por notification-service.">
          {sectionErrors.notifications ? (
            <p className="inline-error">{sectionErrors.notifications}</p>
          ) : null}
          <DataTable
            columns={[
              { header: "ID", cell: (row: NotificationRecordSummary) => row.id },
              { header: "Order", cell: (row: NotificationRecordSummary) => row.order_id },
              { header: "User", cell: (row: NotificationRecordSummary) => row.user_id },
              { header: "Status", cell: (row: NotificationRecordSummary) => row.status },
              {
                header: "Channel",
                cell: (row: NotificationRecordSummary) => row.preferred_channel,
              },
            ]}
            rows={recentNotifications}
            keyExtractor={(row) => row.id}
            emptyMessage="No se pudieron cargar notificaciones recientes."
          />
        </Panel>
      </div>

      <div className="two-column-grid">
        <Panel title="Observabilidad" subtitle="Accesos directos al stack de métricas y trazas.">
          <div className="link-grid">
            <a className="link-card" href="http://localhost:9090" target="_blank" rel="noreferrer">
              <strong>Prometheus</strong>
              <span>Métricas y targets del stack.</span>
            </a>
            <a className="link-card" href="http://localhost:3000" target="_blank" rel="noreferrer">
              <strong>Grafana</strong>
              <span>Dashboards y datasource aprovisionado.</span>
            </a>
            <a className="link-card" href="http://localhost:16686" target="_blank" rel="noreferrer">
              <strong>Jaeger</strong>
              <span>Trazas distribuidas del flujo de órdenes.</span>
            </a>
          </div>
        </Panel>

        <Panel title="Resilience / Chaos Testing" subtitle="Aplica FAILURE_RATE, LATENCY_MS y TIMEOUT_RATE a un servicio.">
          <div className="chaos-grid">
            <label>
              <span>Servicio</span>
              <select
                value={chaosForm.service}
                onChange={(event) =>
                  setChaosForm((current) => ({ ...current, service: event.target.value }))
                }
              >
                {Object.keys(CHAOS_SERVICE_MAP).map((service) => (
                  <option key={service} value={service}>
                    {service}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>FAILURE_RATE</span>
              <input
                value={chaosForm.failureRate}
                onChange={(event) =>
                  setChaosForm((current) => ({ ...current, failureRate: event.target.value }))
                }
              />
            </label>
            <label>
              <span>LATENCY_MS</span>
              <input
                value={chaosForm.latencyMs}
                onChange={(event) =>
                  setChaosForm((current) => ({ ...current, latencyMs: event.target.value }))
                }
              />
            </label>
            <label>
              <span>TIMEOUT_RATE</span>
              <input
                value={chaosForm.timeoutRate}
                onChange={(event) =>
                  setChaosForm((current) => ({ ...current, timeoutRate: event.target.value }))
                }
              />
            </label>
          </div>
          {(Number(chaosForm.failureRate) > 0 || Number(chaosForm.timeoutRate) > 0) && (
            <p className="inline-warning">
              Advertencia: esta configuración puede degradar o bloquear llamadas del flujo real.
            </p>
          )}
          <div className="toolbar toolbar--spaced">
            <button className="button button--primary" onClick={() => void applyChaos()}>
              {chaosSubmitting ? "Aplicando..." : "Aplicar caos"}
            </button>
            <button className="button button--secondary" onClick={() => void applyChaos(true)}>
              Resetear
            </button>
          </div>
          {chaosMessage ? <p className="inline-success">{chaosMessage}</p> : null}
          {chaosError ? <p className="inline-error">{chaosError}</p> : null}
        </Panel>
      </div>
    </main>
  );
}
