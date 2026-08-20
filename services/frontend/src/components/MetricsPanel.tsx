import { useEffect, useState } from "react";
import { api, type PrometheusQueryResponse } from "../api/client";
import { MetricCard } from "./MetricCard";
import { StatusBadge } from "./StatusBadge";

const QUERY_UP = 'up{job=~"microservices|otel-collector"}';
const QUERY_REQUESTS_5M = 'sum(increase(http_requests_total{job="microservices"}[5m]))';
const QUERY_ERRORS_5M = 'sum(increase(http_requests_total{job="microservices", status=~"5.."}[5m]))';
const QUERY_LATENCY = [
  "sum(rate(http_request_duration_seconds_sum{job=\"microservices\"}[5m]))",
  "/",
  "clamp_min(sum(rate(http_request_duration_seconds_count{job=\"microservices\"}[5m])), 1e-9)",
].join(" ");

interface ServiceMetricRow {
  service: string;
  up: boolean;
  requests5m: number;
  errors5m: number;
}

interface MetricsSummary {
  healthyTargets: number | null;
  totalTargets: number | null;
  requests5m: number | null;
  errors5m: number | null;
  avgLatencyMs: number | null;
}

function scalarOf(response: PrometheusQueryResponse | null): number | null {
  if (!response || response.status !== "success" || response.data.result.length === 0) {
    return null;
  }
  const value = Number(response.data.result[0].value[1]);
  return Number.isFinite(value) ? value : null;
}

function serviceRowsOf(upResponse: PrometheusQueryResponse | null): ServiceMetricRow[] {
  if (!upResponse || upResponse.status !== "success") {
    return [];
  }

  return upResponse.data.result.map((sample) => {
    const instance = sample.metric.instance ?? "unknown";
    const service = instance.replace(/:\d+$/, "");

    return {
      service,
      up: sample.value[1] === "1",
      requests5m: 0,
      errors5m: 0,
    };
  });
}

function formatLatency(seconds: number | null): string {
  if (seconds === null) {
    return "—";
  }
  if (seconds < 1) {
    return `${Math.round(seconds * 1000)} ms`;
  }
  return `${seconds.toFixed(2)} s`;
}

export function MetricsPanel() {
  const [summary, setSummary] = useState<MetricsSummary>({
    healthyTargets: null,
    totalTargets: null,
    requests5m: null,
    errors5m: null,
    avgLatencyMs: null,
  });
  const [services, setServices] = useState<ServiceMetricRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  async function refreshMetrics() {
    setRefreshing(true);

    const [upResult, requestsResult, errorsResult, latencyResult] = await Promise.allSettled([
      api.queryPrometheus(QUERY_UP),
      api.queryPrometheus(QUERY_REQUESTS_5M),
      api.queryPrometheus(QUERY_ERRORS_5M),
      api.queryPrometheus(QUERY_LATENCY),
    ]);

    if (
      upResult.status === "rejected" ||
      requestsResult.status === "rejected" ||
      errorsResult.status === "rejected" ||
      latencyResult.status === "rejected"
    ) {
      setError(
        "No se pudieron consultar las métricas de Prometheus. Revisa que prometheus esté activo.",
      );
      setRefreshing(false);
      return;
    }

    const upResponse = upResult.value;
    const rows = serviceRowsOf(upResponse);

    const nextRequests = new Map<string, number>();
    const nextErrors = new Map<string, number>();

    if (requestsResult.value.status === "success") {
      for (const sample of requestsResult.value.data.result) {
        const service = (sample.metric.instance ?? "unknown").replace(/:\d+$/, "");
        nextRequests.set(service, Number(sample.value[1]) || 0);
      }
    }

    if (errorsResult.value.status === "success") {
      for (const sample of errorsResult.value.data.result) {
        const service = (sample.metric.instance ?? "unknown").replace(/:\d+$/, "");
        nextErrors.set(service, Number(sample.value[1]) || 0);
      }
    }

    setServices(
      rows.map((row) => ({
        ...row,
        requests5m: nextRequests.get(row.service) ?? 0,
        errors5m: nextErrors.get(row.service) ?? 0,
      })),
    );

    const totalTargets = rows.length;
    const healthyTargets = rows.filter((row) => row.up).length;
    const latencySeconds = scalarOf(latencyResult.value);

    setSummary({
      healthyTargets,
      totalTargets,
      requests5m: scalarOf(requestsResult.value),
      errors5m: scalarOf(errorsResult.value),
      avgLatencyMs: latencySeconds,
    });

    setError(null);
    setRefreshing(false);
  }

  useEffect(() => {
    void refreshMetrics();
    const timer = window.setInterval(() => {
      void refreshMetrics();
    }, 15000);
    return () => window.clearInterval(timer);
  }, []);

  const errorRate =
    summary.requests5m && summary.errors5m !== null
      ? `${((summary.errors5m / Math.max(summary.requests5m, 1)) * 100).toFixed(2)}%`
      : "—";

  return (
    <div className="metrics-panel">
      <div className="metrics-panel__toolbar">
        <p className="metrics-panel__hint">
          Métricas Prometheus agregadas. Los conteos de tráfico tardan unos minutos en poblarse.
        </p>
        <button
          className="button button--secondary"
          onClick={() => void refreshMetrics()}
          disabled={refreshing}
        >
          {refreshing ? "Actualizando..." : "Refrescar métricas"}
        </button>
      </div>

      {error ? <p className="inline-error">{error}</p> : null}

      <div className="metrics-mini-grid">
        <MetricCard
          title="Targets saludables"
          value={
            summary.healthyTargets !== null
              ? `${summary.healthyTargets} / ${summary.totalTargets ?? "—"}`
              : "—"
          }
          hint="Servicios con scrape up en Prometheus"
        />
        <MetricCard
          title="Requests (5 min)"
          value={summary.requests5m !== null ? Math.round(summary.requests5m).toLocaleString("es-MX") : "—"}
          hint="Incremento de http_requests_total"
        />
        <MetricCard
          title="Errores 5xx (5 min)"
          value={summary.errors5m !== null ? Math.round(summary.errors5m).toLocaleString("es-MX") : "—"}
          hint="Respuestas con status 5xx"
        />
        <MetricCard title="Tasa de error" value={errorRate} hint="Errores / requests (5 min)" />
        <MetricCard
          title="Latencia media"
          value={formatLatency(summary.avgLatencyMs)}
          hint="Promedio de http_request_duration_seconds"
        />
      </div>

      {services.length > 0 ? (
        <div className="table-wrapper">
          <table className="data-table">
            <thead>
              <tr>
                <th>Servicio</th>
                <th>Estado</th>
                <th className="table-align-right">Requests (5 min)</th>
                <th className="table-align-right">Errores (5 min)</th>
              </tr>
            </thead>
            <tbody>
              {services.map((service) => (
                <tr key={service.service}>
                  <td>{service.service}</td>
                  <td>
                    <StatusBadge
                      label={service.up ? "up" : "down"}
                      tone={service.up ? "success" : "error"}
                    />
                  </td>
                  <td className="table-align-right">{service.requests5m.toLocaleString("es-MX")}</td>
                  <td className="table-align-right">{service.errors5m.toLocaleString("es-MX")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        !error ? <p className="inline-warning">No hay targets de microservicios registrados aún.</p> : null
      )}
    </div>
  );
}
