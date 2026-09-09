// home.js — Inicio: flujo de servicios en vivo (árbol vertical), controles de
// ciclo de vida por servicio y resumen del sistema.

import { API } from '../api.js';
import { card, table, badge, dot, empty, esc, toast } from '../ui.js';
import { mountRefreshControl } from '../interval.js';

const SVC_KEYS = ['order', 'user', 'inventory', 'payment', 'notification'];
const HOPS = ['user', 'inventory', 'payment', 'notification'];
const LABELS = {
  order: 'order-service',
  user: 'user-service',
  inventory: 'inventory-service',
  payment: 'payment-service',
  notification: 'notification-service',
};

export function render(view) {
  view.innerHTML = `
    ${card('Flujo de servicios en tiempo real',
      'Así trabaja el sistema en conjunto: order-service orquesta a los otros 4 servicios. Cada salto muestra su latencia (campo timings) y su estado (verde = ok, rojo = fallo, gris punteado = no alcanzado). Con "Detener / Levantar" apagas y enciendes cada servicio de verdad (afecta a todo el stack).',
      `
      <div class="row">
        <button class="btn" id="f-run">Probar orden</button>
        <label><input type="checkbox" id="f-auto"> auto (cada 3s)</label>
        <span id="f-msg" class="muted"></span>
      </div>
      <div class="flow">
        <div class="node client">Cliente</div>
        <div class="arrow-down">↓</div>
        ${node('order', true)}
        <div class="arrow-down">↓</div>
        <div class="branch">
          ${node('user')}
          ${node('inventory')}
          ${node('payment')}
          ${node('notification')}
        </div>
      </div>
      `,
      { full: true })}

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
      'Últimas órdenes procesadas por order-service. La fila resaltada es la orden que acabas de generar con "Probar orden".',
      table(['ID', 'Usuario', 'Producto', 'Cant.', 'Estado'], [])
        .replace('<tbody></tbody>', '<tbody id="home-recent"></tbody>'),
      { full: true })}
  `;

  const $ = (id) => view.querySelector('#' + id);

  let highlightId = null;
  let highlightTimer = null;
  let autoTimer = null;
  let animTimers = [];
  const healthMap = {};

  function node(key, hub) {
    return `<div class="node ${hub ? 'hub' : ''}" id="f-${key}">
      <div class="hop"><span>${LABELS[key]}</span><span class="dot" id="f-${key}-dot"></span></div>
      <div class="lat" id="f-${key}-lat"></div>
      <div class="controls"><button class="btn sm secondary svc-btn" data-svc="${key}" data-action="stop">Detener</button></div>
    </div>`;
  }

  const refreshCleanup = mountRefreshControl(view, { onRefresh: refresh, initial: 5 });
  refresh();

  $('f-run').addEventListener('click', runFlow);
  $('f-auto').addEventListener('change', () => {
    if ($('f-auto').checked) { autoTimer = setInterval(runFlow, 3000); runFlow(); }
    else { clearInterval(autoTimer); autoTimer = null; }
  });

  // ---- Stop/start de servicios (real) ----
  view.querySelectorAll('.svc-btn').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const svc = btn.dataset.svc;
      const action = btn.dataset.action;
      if (action === 'stop' && !confirm(`¿Detener ${LABELS[svc]}? Afectará a todo el sistema (salud, flujo de órdenes, métricas).`)) return;
      btn.disabled = true;
      try {
        const r = await API.serviceAction(svc, action);
        toast(`${r.container} ${action === 'stop' ? 'detenido' : 'levantado'}`, 'ok');
        setTimeout(refresh, 1500);
      } catch (e) { toast('Error: ' + e.message, 'err'); }
      btn.disabled = false;
    });
  });

  async function runFlow() {
    const msg = $('f-msg');
    try {
      const pid = await pickInStockProduct();
      if (pid == null) { msg.textContent = 'sin productos con stock (genera inventario)'; return; }
      const r = await API.placeOrder(1, pid, 1);
      const oid = r.order && r.order.id != null ? r.order.id : null;
      msg.textContent = 'orden #' + (oid ?? '?') + ' · status: ' + r.status;
      if (oid != null) markHighlight(oid);
      animateFlow(r);
      refresh();
    } catch (e) { msg.textContent = 'error: ' + e.message; }
  }

  function markHighlight(id) {
    highlightId = id;
    if (highlightTimer) clearTimeout(highlightTimer);
    highlightTimer = setTimeout(() => { highlightId = null; }, 6000);
  }

  function animateFlow(r) {
    animTimers.forEach(clearTimeout);
    animTimers = [];
    setFlowClass('order', 'done-ok');
    HOPS.forEach((k) => { setFlowClass(k, 'pending'); $('f-' + k + '-lat').textContent = '—'; });
    const t = r.timings || {};
    HOPS.forEach((k, i) => {
      animTimers.push(setTimeout(() => {
        const st = hopState(r, k);
        setFlowClass(k, st === 'ok' ? 'done-ok' : st === 'err' ? 'done-err' : 'skipped');
        const lat = t[k + '_ms'];
        $('f-' + k + '-lat').textContent = st === 'skip' ? 'no ejecutado' : (lat != null ? lat + ' ms' : '—');
      }, 450 + i * 500));
    });
  }

  function setFlowClass(key, cls) {
    const n = $('f-' + key);
    if (!n) return;
    n.classList.remove('pending', 'done-ok', 'done-err', 'skipped');
    if (cls) n.classList.add(cls);
  }

  function hopState(r, key) {
    const d = r.downstream && r.downstream[key];
    if (!d) return 'skip';
    if (key === 'user') return d.valid ? 'ok' : 'err';
    if (key === 'inventory') return d.available ? 'ok' : 'err';
    if (key === 'payment') return d.status === 'success' ? 'ok' : 'err';
    if (key === 'notification') return d.status === 'sent' ? 'ok' : 'err';
    return 'skip';
  }

  async function pickInStockProduct() {
    const prods = await API.listEntities('products', 0, 50);
    const inStock = (Array.isArray(prods) ? prods : []).filter((p) => (p.quantity ?? 0) > 0);
    return inStock.length ? inStock[0].product_id : null;
  }

  async function refresh() {
    try {
      const h = await API.health();
      $('home-health').innerHTML = Object.entries(h).map(([k, v]) =>
        `<tr><td>${dot(v.up)}${esc(k)}-service</td><td>${v.up ? badge('UP', 'ok') : badge('DOWN', 'bad')}</td></tr>`
      ).join('');
      SVC_KEYS.forEach((key) => {
        const v = h[key];
        healthMap[key] = !!(v && v.up);
      });
      refreshNodeHealth();
    } catch (_) {}

    try {
      const c = await API.counts();
      $('home-counts').innerHTML = Object.entries(c).map(([k, v]) =>
        `<tr><td>${esc(k)}</td><td>${esc(v ?? '—')}</td></tr>`
      ).join('');
    } catch (_) {}

    try {
      const cb = await API.circuitBreaker();
      $('home-cb').innerHTML =
        `${badge(cb.state, cb.state)} <span class="muted">fallos: ${cb.failures}/${cb.failure_threshold} · recuperación: ${cb.recovery_timeout}s</span>`;
    } catch (_) { $('home-cb').textContent = 'no disponible'; }

    try {
      const a = await API.alerts();
      const rules = a.groups || [];
      const firing = rules.filter((r) => r.state === 'firing');
      $('home-alerts').innerHTML = rules.length
        ? (firing.length ? `<div style="margin-bottom:6px">${badge(firing.length + ' en FIRING', 'bad')}</div>` : '') +
          rules.map((r) => `<span class="chip ${r.state}">${esc(r.name)}</span>`).join('')
        : empty('sin reglas de alerta cargadas');
    } catch (_) { $('home-alerts').textContent = 'no disponible'; }

    try {
      const recent = await API.recent('orders', 8);
      $('home-recent').innerHTML = recent.map((o) =>
        `<tr class="${o.id === highlightId ? 'highlight' : ''}"><td>${o.id}</td><td>${o.user_id}</td><td>${o.product_id}</td><td>${o.quantity}</td><td>${esc(o.status)}</td></tr>`
      ).join('') || `<tr><td colspan="5" class="muted">sin órdenes todavía</td></tr>`;
    } catch (_) {}
  }

  function refreshNodeHealth() {
    SVC_KEYS.forEach((key) => {
      const up = healthMap[key];
      const nodeEl = $('f-' + key);
      const dotEl = $('f-' + key + '-dot');
      const btn = view.querySelector(`.svc-btn[data-svc="${key}"]`);
      if (!nodeEl || !dotEl) return;
      if (up) {
        dotEl.className = 'dot up';
        if (btn) { btn.textContent = 'Detener'; btn.dataset.action = 'stop'; }
        nodeEl.classList.remove('down');
      } else {
        dotEl.className = 'dot down';
        if (btn) { btn.textContent = 'Levantar'; btn.dataset.action = 'start'; }
        nodeEl.classList.add('down');
      }
    });
  }

  return () => { refreshCleanup(); clearInterval(autoTimer); clearTimeout(highlightTimer); animTimers.forEach(clearTimeout); };
}
