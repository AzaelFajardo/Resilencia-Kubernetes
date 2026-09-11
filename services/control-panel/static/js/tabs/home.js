// home.js — Inicio: flujo de servicios en vivo (árbol vertical), controles de
// ciclo de vida por servicio y resumen del sistema.

import { API } from '../api.js';
import { card, table, badge, dot, empty, esc, toast, confirmDialog } from '../ui.js';
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
      'Así trabaja el sistema en conjunto: order-service orquesta a los otros 4 servicios. Cada salto muestra su latencia (campo timings) y su estado (verde = ok, rojo = fallo, gris punteado = no alcanzado). En Modo Reintentos, si un salto falla order-service lo reintenta (reintentos × espera ms configurados en Pruebas): el nodo parpadea mostrando "intento i/N" y al final verás cuántos intentos necesitó. Con "Detener / Levantar" apagas y enciendes cada servicio de verdad (afecta a todo el stack).',
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
      {
        full: true,
        headerExtra: `
          <div class="seg" id="mode-seg">
            <button type="button" data-mode="baseline" data-tip="Sin resiliencia: ni reintentos ni circuit breaker. Bajo mucha carga el sistema se satura.">Baseline</button>
            <button type="button" data-mode="retries" data-tip="Reintenta automáticamente los pedidos que fallan.">Reintentos</button>
            <button type="button" data-mode="breaker" data-tip="Si un servicio falla varias veces, deja de llamarlo (evita cascadas de fallos).">Circuit breaker</button>
            <button type="button" data-mode="kubernetes" data-tip="Cambia al cluster Kubernetes: usa HPA (autoescala) y liveness probes (reinicio automático).">Kubernetes</button>
          </div>
        `
      })}

    <div class="grid">
      ${card('Salud de servicios',
        'Estado en tiempo real de los 5 microservicios. Cada punto indica si responde a GET /health (verde = responde, rojo = caído).',
        table(['Servicio', 'Estado'], [])
          .replace('<tbody></tbody>', '<tbody id="home-health"></tbody>'))}
      ${card('Conteos de registros',
        'Número total de registros persistidos en PostgreSQL para cada entidad. Usa "Limpiar Todo" para vaciar la base de datos.',
        table(['Entidad', 'Cantidad'], [])
          .replace('<tbody></tbody>', '<tbody id="home-counts"></tbody>') +
        `<div class="row" style="justify-content:flex-end;margin-top:10px">
          <button class="btn danger sm" id="home-clear-all-counts">Limpiar Todo</button>
         </div>`
      )}
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
  let alertsInFlight = false;
  let retryDelay = 400;
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
  loadRetryConfig();
  refreshAlerts();
  const alertsTimer = setInterval(refreshAlerts, 1000);

  async function handleClearAll() {
    if (!(await confirmDialog('¿Estás seguro de ELIMINAR TODOS LOS REGISTROS de TODAS las pestañas (Órdenes, Clientes, Inventario, Pagos, Notificaciones) de la BD? Esta acción es irreversible.'))) return;
    try {
      await API.clearAllData();
      toast('Se han eliminado todos los registros de todas las pestañas de la BD', 'ok');
      refresh();
    } catch (e) {
      toast('Error al limpiar datos: ' + e.message, 'err');
    }
  }

  $('f-run').addEventListener('click', runFlow);
  $('home-clear-all-counts')?.addEventListener('click', handleClearAll);
  $('f-auto').addEventListener('change', () => {
    if ($('f-auto').checked) { autoTimer = setInterval(runFlow, 3000); runFlow(); }
    else { clearInterval(autoTimer); autoTimer = null; }
  });

  // ---- Modo de resiliencia ----
  let runtime = 'compose';
  let strategy = 'baseline';

  async function loadModeState() {
    try { strategy = (await API.getMode()).mode || 'baseline'; } catch (_) {}
    try { runtime = (await API.getRuntimeMode()).mode || 'compose'; } catch (_) {}
    renderModeState();
  }

  function renderModeState() {
    view.querySelectorAll('#mode-seg button').forEach((b) => {
      const isActive = b.dataset.mode === 'kubernetes'
        ? runtime === 'kubernetes'
        : (runtime === 'compose' && b.dataset.mode === strategy);
      b.classList.toggle('active', isActive);
    });
    const stateEl = $('mode-state');
    if (stateEl) {
      const env = runtime === 'kubernetes' ? 'Kubernetes' : 'Compose';
      stateEl.innerHTML = `Estrategia: <b>${strategy}</b> · Entorno: <b>${env}</b>`;
    }
  }

  view.querySelectorAll('#mode-seg button').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const mode = btn.dataset.mode;
      try {
        if (mode === 'kubernetes') {
          const r = await API.getRuntimeMode();
          if (!r.k8s_configured) {
            toast('Kubernetes no está configurado (K8S_API_SERVER + certs en k8s/certs)', 'err');
            return;
          }
          if (runtime !== 'kubernetes') {
            if (!(await confirmDialog('Cambiar al cluster Kubernetes? El panel enrutará todas las llamadas al cluster (requiere minikube + stack desplegado).'))) return;
            await API.setRuntimeMode('kubernetes');
            toast('Entorno cambiado a Kubernetes', 'ok');
          }
        } else {
          if (runtime === 'kubernetes') {
            await API.setRuntimeMode('compose');
          }
          await API.setMode(mode);
          toast('Estrategia aplicada: ' + mode, 'ok');
        }
        await loadModeState();
      } catch (e) { toast('Error: ' + e.message, 'err'); }
    });
  });

  loadModeState();

  // ---- Stop/start de servicios (real) ----
  view.querySelectorAll('.svc-btn').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const svc = btn.dataset.svc;
      const action = btn.dataset.action;
      if (action === 'stop' && !(await confirmDialog(`¿Detener ${LABELS[svc]}? Afectará a todo el sistema (salud, flujo de órdenes, métricas).`))) return;
      btn.disabled = true;
      try {
        const r = await API.serviceAction(svc, action);
        toast(`${r.container} ${action === 'stop' ? 'detenido' : 'levantado'}`, 'ok');
        setTimeout(refresh, 1500);
      } catch (e) { toast('Error: ' + e.message, 'err'); }
      btn.disabled = false;
    });
  });

  async function loadRetryConfig() {
    try {
      const rc = await API.getRetries();
      if (rc.delay_ms > 0) retryDelay = rc.delay_ms;
    } catch (_) {}
  }

  async function runFlow() {
    const msg = $('f-msg');
    try {
      setFlowClass('order', 'pending');
      HOPS.forEach((k) => { setFlowClass(k, 'pending'); $('f-' + k + '-lat').textContent = '…'; });

      const counts = await API.counts().catch(() => ({}));
      if (!counts.user) {
        msg.textContent = 'No hay usuarios registrados. Crea al menos un usuario desde la pestaña de Entidades.';
        toast('No hay usuarios en la base de datos', 'err');
        setFlowClass('order', 'done-err');
        if ($('f-auto').checked) { $('f-auto').checked = false; clearInterval(autoTimer); autoTimer = null; }
        return;
      }
      if (!counts.inventory) {
        msg.textContent = 'No hay productos en inventario. Crea registros de inventario desde la pestaña de Entidades.';
        toast('No hay inventario en la base de datos', 'err');
        setFlowClass('order', 'done-err');
        if ($('f-auto').checked) { $('f-auto').checked = false; clearInterval(autoTimer); autoTimer = null; }
        return;
      }

      const pid = await pickInStockProduct();
      if (pid == null) {
        msg.textContent = 'Sin productos con stock (todos agotados). Repone el inventario desde Entidades.';
        toast('Todos los productos están agotados', 'err');
        setFlowClass('order', 'done-err');
        if ($('f-auto').checked) { $('f-auto').checked = false; clearInterval(autoTimer); autoTimer = null; }
        return;
      }
      const r = await API.placeOrder(1, pid, 1);
      const oid = r.order && r.order.id != null ? r.order.id : null;
      msg.textContent = 'orden #' + (oid ?? '?') + ' · status: ' + r.status;
      if (r.status === 'success') {
        if (oid != null) markHighlight(oid);
      } else {
        toast(`No se completó la orden: ${r.message || r.status}`, 'err');
      }
      animateFlow(r);
      refresh();
    } catch (e) {
      msg.textContent = 'error: ' + e.message;
      toast('No se pudo enviar la orden (¿algún servicio está detenido?): ' + e.message, 'err');
    }
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
    HOPS.forEach((k) => { setFlowClass(k, 'pending'); $('f-' + k + '-lat').textContent = '…'; });
    const attempts = (r && r.attempts) || {};
    const t = r.timings || {};
    const step = Math.max(retryDelay, 700);
    HOPS.forEach((k, i) => {
      const list = attempts[k] || [];
      const n = Math.max(list.length, 1);
      let acc = 450 + i * (n > 1 ? 250 : 500);
      for (let x = 0; x < n; x++) {
        const isLast = x === n - 1;
        animTimers.push(setTimeout(() => {
          if (n > 1 && !isLast) {
            setFlowClass(k, 'retrying');
            $('f-' + k + '-lat').textContent = 'intento ' + (x + 1) + '/' + n;
          } else {
            const st = hopState(r, k);
            const lastOk = list.length ? list[list.length - 1].ok : true;
            const cls = (st === 'skip' && n > 1 && !lastOk)
              ? 'done-err'
              : st === 'ok' ? 'done-ok' : st === 'err' ? 'done-err' : 'skipped';
            setFlowClass(k, cls);
            const lat = t[k + '_ms'];
            const extra = n > 1 ? ' · ×' + n + ' intentos' : '';
            $('f-' + k + '-lat').textContent = (st === 'skip' ? 'no ejecutado' : (lat != null ? lat + ' ms' : '—')) + extra;
          }
        }, acc));
        acc += step;
      }
    });
  }

  function setFlowClass(key, cls) {
    const n = $('f-' + key);
    if (!n) return;
    n.classList.remove('pending', 'done-ok', 'done-err', 'skipped', 'retrying', 'down');
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
    let prods;
    try {
      prods = await API.listEntities('products', 0, 50);
    } catch (_) {
      // Fallback: si inventory-service está caído no se puede consultar el stock;
      // usamos el producto 1 para que la orden llegue a reintentar igualmente.
      return 1;
    }
    const inStock = (Array.isArray(prods) ? prods : []).filter((p) => (p.quantity ?? 0) > 0);
    if (inStock.length) return inStock[0].product_id;
    return null;
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
      const recent = await API.recent('orders', 8);
      $('home-recent').innerHTML = recent.map((o) =>
        `<tr class="${o.id === highlightId ? 'highlight' : ''}"><td>${o.id}</td><td>${o.user_id}</td><td>${o.product_id}</td><td>${o.quantity}</td><td>${esc(o.status)}</td></tr>`
      ).join('') || `<tr><td colspan="5" class="muted">sin órdenes todavía</td></tr>`;
    } catch (_) {}
  }

  // Alerts are polled on their own fast interval so they update immediately
  // when a rule fires or clears, without waiting for the general refresh.
  async function refreshAlerts() {
    if (alertsInFlight) return;
    alertsInFlight = true;
    try {
      const a = await API.alerts();
      const rules = a.groups || [];
      const firing = rules.filter((r) => r.state === 'firing');
      $('home-alerts').innerHTML = rules.length
        ? (firing.length ? `<div style="margin-bottom:6px">${badge(firing.length + ' en FIRING', 'bad')}</div>` : '') +
          rules.map((r) => `<span class="chip ${r.state}">${esc(r.name)}</span>`).join('')
        : empty('sin reglas de alerta cargadas');
    } catch (_) { $('home-alerts').textContent = 'no disponible'; }
    finally { alertsInFlight = false; }
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
        // When healthy, clear any stale flow state (e.g. "skipped"/"done-err"
        // left by an order that failed while a dependency was down) so the
        // node doesn't stay looking "off" after the service recovers.
        nodeEl.classList.remove('down', 'pending', 'done-ok', 'done-err', 'skipped', 'retrying');
      } else {
        dotEl.className = 'dot down';
        if (btn) { btn.textContent = 'Levantar'; btn.dataset.action = 'start'; }
        nodeEl.classList.add('down');
      }
    });
  }

  return () => { refreshCleanup(); clearInterval(autoTimer); clearInterval(alertsTimer); clearTimeout(highlightTimer); animTimers.forEach(clearTimeout); };
}
