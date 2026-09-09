// home.js — Inicio: resumen del sistema.

import { API } from '../api.js';
import { card, table, badge, dot, empty, esc } from '../ui.js';

export function render(view) {
  view.innerHTML = `
    <div class="grid">
      ${card('Salud de servicios',
        'Estado en tiempo real de los 5 microservicios. Cada punto indica si responde a GET /health (verde = responde, rojo = caído).',
        table(['Servicio', 'Estado'], [])
          .replace('<tbody></tbody>', '<tbody id="home-health"></tbody>'))}
      ${card('Conteos de registros',
        'Número total de registros persistidos en PostgreSQL para cada entidad.',
        table(['Entidad', 'Cantidad'], [])
          .replace('<tbody></tbody>', '<tbody id="home-counts"></tbody>'))}
      ${card('Circuit breaker (order → payment)',
        'Mecanismo de resiliencia: si payment-service falla 3 veces seguidas, order-service deja de llamarlo (OPEN) y responde rápido en lugar de esperar. Tras 15s prueba con una sola petición (HALF_OPEN) y se cierra si tiene éxito.',
        '<div id="home-cb" class="muted">cargando…</div>')}
      ${card('Alertas activas',
        'Reglas de alerta de Prometheus. Se marcan en rojo (firing) cuando se incumple la condición durante el umbral de tiempo.',
        '<div id="home-alerts" class="muted">cargando…</div>')}
    </div>
    ${card('Actividad reciente (órdenes)',
      'Últimas órdenes procesadas por order-service, con su estado de negocio (paid, cancelled, etc.).',
      table(['ID', 'Usuario', 'Producto', 'Cant.', 'Estado'], [])
        .replace('<tbody></tbody>', '<tbody id="home-recent"></tbody>'),
      { full: true })}
  `;

  const t = setInterval(refresh, 5000);
  refresh();
  return () => clearInterval(t);

  async function refresh() {
    try {
      const h = await API.health();
      document.getElementById('home-health').innerHTML = Object.entries(h).map(([k, v]) =>
        `<tr><td>${dot(v.up)}${esc(k)}-service</td><td>${v.up ? badge('UP', 'ok') : badge('DOWN', 'bad')}</td></tr>`
      ).join('');
    } catch (_) {}

    try {
      const c = await API.counts();
      document.getElementById('home-counts').innerHTML = Object.entries(c).map(([k, v]) =>
        `<tr><td>${esc(k)}</td><td>${esc(v ?? '—')}</td></tr>`
      ).join('');
    } catch (_) {}

    try {
      const cb = await API.circuitBreaker();
      document.getElementById('home-cb').innerHTML =
        `${badge(cb.state, cb.state)} <span class="muted">fallos: ${cb.failures}/${cb.failure_threshold} · recuperación: ${cb.recovery_timeout}s</span>`;
    } catch (_) { document.getElementById('home-cb').textContent = 'no disponible'; }

    try {
      const a = await API.alerts();
      const rules = a.groups || [];
      const firing = rules.filter((r) => r.state === 'firing');
      document.getElementById('home-alerts').innerHTML = rules.length
        ? (firing.length ? `<div style="margin-bottom:6px">${badge(firing.length + ' en FIRING', 'bad')}</div>` : '') +
          rules.map((r) => `<span class="chip ${r.state}">${esc(r.name)}</span>`).join('')
        : empty('sin reglas de alerta cargadas');
    } catch (_) { document.getElementById('home-alerts').textContent = 'no disponible'; }

    try {
      const recent = await API.recent('orders', 8);
      document.getElementById('home-recent').innerHTML = recent.map((o) =>
        `<tr><td>${o.id}</td><td>${o.user_id}</td><td>${o.product_id}</td><td>${o.quantity}</td><td>${esc(o.status)}</td></tr>`
      ).join('') || `<tr><td colspan="5" class="muted">sin órdenes todavía</td></tr>`;
    } catch (_) {}
  }
}
