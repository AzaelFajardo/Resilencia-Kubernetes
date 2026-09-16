// home.js — Inicio: flujo de servicios en vivo (árbol vertical), controles de
// ciclo de vida por servicio y resumen del sistema.

import { API } from '../api.js';
import { card, table, badge, esc, toast, confirmDialog, fmtCompact } from '../ui.js';
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

// Qué significa que cada regla de alerta de Prometheus esté encendida (firing).
const ALERT_TIPS = {
  ServiceDown:
    'Se enciende cuando Prometheus no ha conseguido rastrear un microservicio durante al menos 1 minuto: el servicio no responde a las métricas, está detenido o no está desplegado.',
  CircuitBreakerOpen:
    'El circuit breaker de order-service hacia el servicio afectado está en OPEN: el servicio falló varias veces seguidas y, para evitar una cascada de fallos, order-service ha dejado de llamarlo (responde rápido con fallo controlado) hasta que se recupere.',
  HighOrderLatencyP95:
    'El p95 del endpoint POST /orders ha estado por encima de 1 segundo durante más de 2 minutos: el 95% de las órdenes tarda más de 1s en completarse. Suele indicar saturación, reintentos o tiempos de espera crecientes.',
  HighOrderErrorRate:
    'La tasa de errores HTTP 5xx de order-service supera el 5%. Solo captura errores reales de transporte/excepciones; los fallos de negocio simulados (pago rechazado, sin stock, fraude) responden HTTP 200 y no activan esta alerta.',
};

export function render(view) {
  view.innerHTML = `
    <div class="stack">
    ${card('Flujo de servicios en tiempo real',
      'Así trabaja el sistema en conjunto: order-service orquesta a los otros 4 servicios. Cada salto muestra su latencia (campo timings) y su estado (verde = ok, rojo = fallo, gris punteado = no alcanzado). En Modo Reintentos, si un salto falla order-service lo reintenta (reintentos × espera ms configurados en Pruebas): el nodo parpadea mostrando "intento i/N" y al final verás cuántos intentos necesitó. Con "Detener / Levantar" apagas y enciendes cada servicio de verdad (afecta a todo el stack).',
      `
      <div class="row">
        <button class="btn" id="f-run">Probar orden</button>
        <label><input type="checkbox" id="f-auto"> auto (cada 3s)</label>
        <span id="f-msg" class="muted"></span>
        <button class="btn danger sm" id="home-clear-all-counts" style="margin-left:auto">Limpiar Todo</button>
      </div>
      <div id="mode-state" class="mode-state"></div>
      <div class="orb-banner" id="f-orb-banner" hidden></div>
      <div class="cb-row" id="home-cb-row" hidden>
        <div id="home-cb" class="cb-badge"></div>
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
      <div class="status-strip">
        <div class="ss-health" id="ss-health"></div>
        <div class="ss-alerts" id="ss-alerts"></div>
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
      ${card('Actividad reciente (órdenes)',
        'Últimas órdenes procesadas por order-service. La fila resaltada es la orden que acabas de generar con "Probar orden".',
        table(['ID', 'Usuario', 'Producto', 'Cant.', 'Estado'], [])
          .replace('<tbody></tbody>', '<tbody id="home-recent"></tbody>'),
        { full: true })}
    </div>
  `;

  const $ = (id) => view.querySelector('#' + id);

  let highlightId = null;
  let highlightTimer = null;
  let autoTimer = null;
  let animTimers = [];
  let alertsInFlight = false;
  let retryDelay = 400;
  const healthMap = {};
  let k8s = { reachable: false, version: null, deployments: [], pods: [], hpas: [] };

function node(key, hub) {
    return `<div class="node ${hub ? 'hub' : ''}" id="f-${key}">
      <span class="deck-badge" id="f-${key}-deck" hidden></span>
      <div class="hop"><span>${LABELS[key]}</span><span class="dot" id="f-${key}-dot"></span></div>
      <div class="ortag" id="f-${key}-ortag"></div>
      <div class="lat" id="f-${key}-lat"></div>
      <div class="count" id="f-${key}-count"></div>
      <div class="deploy-ctl" id="f-${key}-ctl" hidden>
        <span class="dc-lbl">réplicas</span>
        <button class="btn sm secondary sc-down" data-svc="${key}" title="Reducir réplicas">−</button>
        <span class="dc-count" id="f-${key}-replicas">?</span>
        <button class="btn sm secondary sc-up" data-svc="${key}" title="Aumentar réplicas">+</button>
        <span class="dc-ready" id="f-${key}-ready"></span>
      </div>
      <div class="replicas" id="f-${key}-list" hidden></div>
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
  let leader = null;

  async function loadModeState() {
    try { strategy = (await API.getMode()).mode || 'baseline'; } catch (_) {}
    try { runtime = (await API.getRuntimeMode()).mode || 'compose'; } catch (_) {}
    try { leader = await API.leader(); } catch (_) { leader = null; }
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
      const lk = leader && leader.service;
      const leaderTxt = runtime === 'kubernetes'
        ? ` · Orquestador: <b>${lk ? esc(LABELS[lk] || lk) : '—'}</b>`
        : '';
      stateEl.innerHTML = `Estrategia: <b>${esc(strategy)}</b> · Entorno: <b>${env}</b>${leaderTxt}`;
    }
    // Kubernetes shows live replica controls + pod cards under each node.
    const isK8s = runtime === 'kubernetes';
    SVC_KEYS.forEach((key) => {
      const ctl = $('f-' + key + '-ctl');
      if (ctl) ctl.hidden = !isK8s;
      const list = $('f-' + key + '-list');
      if (list) list.hidden = !isK8s;
      if (!isK8s) {
        const nodeEl = $('f-' + key);
        if (nodeEl) { nodeEl.classList.remove('has-deck', 'k8s-clickable'); nodeEl.title = ''; }
        const deckEl = $('f-' + key + '-deck');
        if (deckEl) deckEl.hidden = true;
      }
    });
    renderCbBadge();
    renderOrchestrator();
  }
  // Marca en el diagrama qué servicio actúa ahora como orquestador. En
  // Kubernetes, si order-service cae, otro servicio toma el rol (fallback):
  // se resalta su nodo y se muestra un aviso arriba del flujo.
  function renderOrchestrator() {
    const inK8s = runtime === 'kubernetes';
    const leaderKey = (leader && leader.service) || (inK8s ? null : 'order');
    const fallback = inK8s && leaderKey !== null && leaderKey !== 'order';

    const banner = $('f-orb-banner');
    if (banner) {
      banner.hidden = !fallback;
      if (fallback) {
        banner.innerHTML =
          `<b>⚠ order-service caído</b> — <b>${esc(LABELS[leaderKey] || leaderKey)}</b> está orquestando ahora (fallback automático)`;
      }
    }

    SVC_KEYS.forEach((key) => {
      const el = $('f-' + key);
      const tag = $('f-' + key + '-ortag');
      if (!el || !tag) return;
      el.classList.remove('acting-orch', 'relegated');
      tag.innerHTML = '';
      if (!inK8s) return;
      if (leaderKey === key) {
        el.classList.add('acting-orch');
        tag.innerHTML = key === 'order'
          ? badge('orquestando', 'ok')
          : badge('orquestando (fallback)', 'warn');
      } else if (key === 'order') {
        el.classList.add('relegated');
      }
    });
  }

  // Circuit breaker badge: only visible in Circuit breaker mode (compose), in
  // the top-right corner of the flow card, right below the "Limpiar Todo" row.
  function renderCbBadge() {
    const row = $('home-cb-row');
    if (!row) return;
    row.hidden = !(runtime === 'compose' && strategy === 'breaker');
    if (row.hidden) return;
    API.circuitBreaker()
      .then((cb) => {
        $('home-cb').innerHTML =
          `${badge(cb.state, cb.state)} <span class="muted">fallos: ${cb.failures}/${cb.failure_threshold} · recuperación: ${cb.recovery_timeout}s</span>`;
      })
      .catch(() => { $('home-cb').textContent = 'no disponible'; });
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
        const who = r.deployment || r.container || svc + '-service';
        const verbs = { stop: ['detenido', 'escalado a 0'], start: ['levantado', 'escalado a 1'] };
        const v = verbs[action];
        toast(`${who} ${runtime === 'kubernetes' ? v[1] : v[0]}`, 'ok');
        setTimeout(refresh, 1500);
      } catch (e) { toast('Error: ' + e.message, 'err'); }
      btn.disabled = false;
    });
  });

  // ---- Escalado de réplicas (solo Kubernetes) ----
  async function scaleReplicas(svc, delta) {
    const dep = LABELS[svc];
    const depMeta = k8s.deployments.find((d) => d.name === dep);
    const current = depMeta ? depMeta.replicas : 0;
    const next = Math.max(0, Math.min(10, current + delta));
    if (next === current) return;
    try {
      const r = await API.kubernetesScale(dep, next);
      toast(`${dep} → ${next} réplicas (hpa: ${r.hpa || '—'})`, 'ok');
      refresh();
    } catch (e) { toast('Error: ' + e.message, 'err'); }
  }

  view.querySelectorAll('.sc-down, .sc-up').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const svc = btn.dataset.svc;
      const delta = btn.classList.contains('sc-up') ? 1 : -1;
      btn.disabled = true;
      await scaleReplicas(svc, delta);
      btn.disabled = false;
    });
  });

  // ---- Clic en un servicio (solo Kubernetes) abre el popup de réplicas ----
  // Ignora clics en controles interactivos (botones, inputs) y en el nodo
  // "Cliente", que no es un servicio.
  view.addEventListener('click', (e) => {
    if (runtime !== 'kubernetes') return;
    if (e.target.closest('button, input, a, select')) return;
    const node = e.target.closest('.node');
    if (!node || !node.id || node.id.indexOf('f-') !== 0) return;
    const key = node.id.slice(2);
    if (!SVC_KEYS.includes(key)) return;
    openServiceModal(key);
  });

  function fmtAge(iso) {
    if (!iso) return '—';
    const s = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
    if (s < 60) return s + 's';
    const m = Math.floor(s / 60);
    if (m < 60) return m + 'm ' + (s % 60) + 's';
    const h = Math.floor(m / 60);
    if (h < 24) return h + 'h ' + (m % 60) + 'm';
    return Math.floor(h / 24) + 'd ' + (h % 24) + 'h';
  }

  // Popup de administración de réplicas de un servicio (Kubernetes): lista
  // cada pod por individual con su estado, IP, reinicios y antigüedad, y
  // permite borrarlo (el Deployment lo recrea: prueba liveness/self-healing).
  function openServiceModal(key) {
    const depName = LABELS[key];
    const pods = (k8s.pods || []).filter((p) => p.app === depName);
    const dep = k8s.deployments.find((d) => d.name === depName);
    document.getElementById('pod-modal-overlay')?.remove();
    const overlay = document.createElement('div');
    overlay.id = 'pod-modal-overlay';
    overlay.className = 'confirm-overlay';
    const rows = pods.map((p) => {
      const cls = p.ready ? 'ok' : p.phase === 'Pending' ? 'pending' : 'err';
      return `<div class="pod-row ${cls}">
        <span class="rp-dot ${p.ready ? 'up' : p.phase === 'Pending' ? 'warn' : 'down'}"></span>
        <div class="pod-row-main">
          <div class="pod-row-name" title="${esc(p.name)}">${esc(p.name)}</div>
          <div class="pod-row-meta">${podPhaseBadge(p)} · IP ${esc(p.podIP || '—')} · reinicios ${p.restarts ?? 0} · ${fmtAge(p.startedAt)}</div>
        </div>
        <button class="btn sm danger pod-del" data-pod="${esc(p.name)}" title="Borrar pod (liveness/self-healing)">🗑</button>
      </div>`;
    }).join('') || '<div class="muted sm">sin pods</div>';
    overlay.innerHTML = `
      <div class="confirm-box pod-modal">
        <div class="pod-modal-title">
          <h3>${esc(depName)}</h3>
          <span class="muted">${dep ? dep.readyReplicas + '/' + dep.replicas + ' listos · ' : ''}${pods.length} pod(s)</span>
        </div>
        <div class="pod-rows">${rows}</div>
        <div class="row" style="justify-content:flex-end;margin:0">
          <button class="btn secondary" id="pod-modal-close">Cerrar</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);
    const close = () => overlay.remove();
    overlay.querySelector('#pod-modal-close').addEventListener('click', close);
    overlay.addEventListener('click', (ev) => { if (ev.target === overlay) close(); });
    overlay.querySelectorAll('.pod-del').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const podName = btn.dataset.pod;
        if (!(await confirmDialog(`¿Borrar el pod "${podName}"?\nEl Deployment lo recreará automáticamente (liveness/self-healing).`))) return;
        btn.disabled = true;
        try {
          await API.kubernetesDeletePod(podName);
          toast(`Pod ${podName} borrado — el cluster lo está recreando`, 'ok');
          await refresh();
          openServiceModal(key);
        } catch (err) {
          toast('Error borrando pod: ' + err.message, 'err');
          btn.disabled = false;
        }
      });
    });
  }

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
      $('ss-health').innerHTML = SVC_KEYS.map((key) => {
        const up = !!(h[key] && h[key].up);
        return `<span class="ss-item"><span class="dot ${up ? 'up' : 'down'}"></span><span class="ss-name">${key}-service</span><span class="ss-state ${up ? 'up' : 'down'}">${up ? 'UP' : 'DOWN'}</span></span>`;
      }).join('');
      SVC_KEYS.forEach((key) => {
        const v = h[key];
        healthMap[key] = !!(v && v.up);
      });
      refreshNodeHealth();
    } catch (_) {}

    if (runtime === 'kubernetes') {
      try {
        k8s = await API.kubernetes();
        renderK8s();
      } catch (_) {}
      try { leader = await API.leader(); } catch (_) { leader = null; }
      renderOrchestrator();
    }

    try {
      const c = await API.counts();
      SVC_KEYS.forEach((key) => {
        const el = $('f-' + key + '-count');
        if (el) {
          el.textContent = fmtCompact(c[key]);
          if (c[key] != null) el.title = key + '-service registros: ' + c[key];
        }
      });
    } catch (_) {}

    try {
      const recent = await API.recent('orders', 8);
      $('home-recent').innerHTML = recent.map((o) =>
        `<tr class="${o.id === highlightId ? 'highlight' : ''}"><td>${o.id}</td><td>${o.user_id}</td><td>${o.product_id}</td><td>${o.quantity}</td><td>${esc(o.status)}</td></tr>`
      ).join('') || `<tr><td colspan="5" class="muted">sin órdenes todavía</td></tr>`;
    } catch (_) {}

    renderCbBadge();
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
      $('ss-alerts').innerHTML = rules.length
        ? (firing.length ? `${badge(firing.length + ' en FIRING', 'bad')}` : '') +
          rules.map((r) => {
            const tip = ALERT_TIPS[r.name] || `Alerta ${r.name} activa: revisa la condición que la dispara.`;
            return `<span class="chip ${r.state}" data-tip="${esc(tip)}">${esc(r.name)}</span>`;
          }).join('')
        : '<span class="muted">sin alertas</span>';
    } catch (_) { $('ss-alerts').textContent = 'no disponible'; }
    finally { alertsInFlight = false; }
  }

  function podPhaseBadge(p) {
    if (p.phase === 'Running') return p.ready ? badge('Running', 'ok') : badge('Running', 'warn');
    if (p.phase === 'Pending') return badge('Pending', 'warn');
    if (p.phase === 'Succeeded') return badge('Succeeded', 'ok');
    return badge(p.phase || 'Unknown', 'bad');
  }

  function renderK8s() {
    if (runtime !== 'kubernetes') return;
    SVC_KEYS.forEach((key) => {
      const depName = LABELS[key];
      const dep = k8s.deployments.find((d) => d.name === depName);
      const pods = (k8s.pods || []).filter((p) => p.app === depName);

      const countEl = $('f-' + key + '-replicas');
      const readyEl = $('f-' + key + '-ready');
      const listEl = $('f-' + key + '-list');
      const deckEl = $('f-' + key + '-deck');
      const nodeEl = $('f-' + key);
      const total = dep ? dep.replicas : pods.length;
      // 1 pod: el nodo ya lo representa (nada debajo). ≥2 pods: las tarjetas
      // se apilan tras el nodo y la gestión individual pasa al popup.
      const stacked = total >= 2;
      if (countEl) countEl.textContent = dep ? dep.replicas : '?';
      if (readyEl) readyEl.textContent = dep ? `listos ${dep.readyReplicas}/${dep.replicas}` : '';
      if (nodeEl) {
        nodeEl.classList.toggle('has-deck', stacked);
        nodeEl.classList.add('k8s-clickable');
        nodeEl.title = stacked ? total + ' réplicas — clic para administrar' : '';
      }
      if (deckEl) {
        deckEl.hidden = !stacked;
        deckEl.textContent = stacked ? '×' + total : '';
      }
      if (listEl) {
        listEl.hidden = stacked || total === 1;
        listEl.innerHTML = total === 0 ? '<div class="muted sm">0 réplicas</div>' : '';
      }
    });
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
