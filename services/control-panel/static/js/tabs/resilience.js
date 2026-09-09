// resilience.js — Resiliencia y caos: circuit breaker, chaos (por servicio y
// global), reintentos, presets y escenarios de prueba.

import { API } from '../api.js';
import { card, badge, toast, esc, table } from '../ui.js';

const SVC_KEYS = ['order', 'user', 'inventory', 'payment', 'notification'];

export function render(view) {
  view.innerHTML = `
    <div class="grid">
      ${card('Circuit breaker (order → payment)',
        'El breaker protege a payment-service: si falla 3 veces seguidas pasa a OPEN y order-service deja de llamarlo (fallo rápido). Tras 15s entra en HALF_OPEN y deja pasar una única petición de prueba; si tiene éxito vuelve a CLOSED, si falla vuelve a OPEN.',
        '<div id="r-cb" class="muted">cargando…</div>')}

      ${card('Reintentos (order-service)',
        'Reintentos automáticos de order-service hacia los servicios downstream cuando fallan. Actívalos para que una petición se reintente N veces con una espera entre intentos. Afecta a las llamadas de usuario, inventario, pago y notificación.',
        `
        <div class="row">
          <label><input type="checkbox" id="r-ret-enabled"> habilitados</label>
          <label>reintentos <input id="r-ret-count" type="number" min="0" max="10" value="3"></label>
          <label>espera (ms) <input id="r-ret-delay" type="number" min="0" value="100"></label>
          <button class="btn sm" id="r-ret-save">Guardar</button>
        </div>
        <div class="msg" id="r-ret-msg"></div>
      `)}

      ${card('Inyección de fallos por servicio (chaos)',
        'Cambia el comportamiento de un servicio concreto en caliente. Selecciona el servicio con los botones y ajusta los valores (pasa el cursor por cada campo para ver qué significa y sus unidades).',
        `
        <div class="seg" id="c-svc">
          ${SVC_KEYS.map((s, i) => `<button type="button" data-svc="${s}" class="${i === 0 ? 'active' : ''}">${s}</button>`).join('')}
        </div>
        <form id="c-form" class="row" style="margin-top:8px">
          <label data-tip="Probabilidad de que el servicio falle en cada petición. Se mide en porcentaje (0 a 100%): 0 = nunca falla, 100 = falla siempre.">
            Tasa de fallo (%) <input id="c-fr" type="number" step="1" min="0" max="100" placeholder="0">
          </label>
          <label data-tip="Retardo artificial añadido a cada petición. Se mide en milisegundos (ms). 0 = sin retardo.">
            Latencia (ms) <input id="c-lm" type="number" step="100" min="0" placeholder="0">
          </label>
          <label data-tip="Probabilidad de que el servicio simule un timeout: se queda esperando 30 segundos antes de responder. Se mide en porcentaje (0 a 100%).">
            Tasa de timeout (%) <input id="c-tr" type="number" step="1" min="0" max="100" placeholder="0">
          </label>
          <button class="btn">Aplicar</button>
        </form>
        <div class="msg" id="c-msg"></div>
      `)}

      ${card('Caos global (todo el sistema)',
        'Inyecta las mismas variables de caos en los 5 servicios a la vez, para estresar el sistema completo. Pasa el cursor por cada campo para ver qué significa y sus unidades.',
        `
        <form id="g-form" class="row">
          <label data-tip="Probabilidad de que cada servicio falle en cada petición. Se mide en porcentaje (0 a 100%).">
            Tasa de fallo (%) <input id="g-fr" type="number" step="1" min="0" max="100" placeholder="0">
          </label>
          <label data-tip="Retardo artificial añadido a cada petición de todos los servicios. Se mide en milisegundos (ms).">
            Latencia (ms) <input id="g-lm" type="number" step="100" min="0" placeholder="0">
          </label>
          <label data-tip="Probabilidad de que cada servicio simule un timeout (espera 30 s). Se mide en porcentaje (0 a 100%).">
            Tasa de timeout (%) <input id="g-tr" type="number" step="1" min="0" max="100" placeholder="0">
          </label>
          <button class="btn">Aplicar a todos</button>
          <button class="btn danger" id="g-reset" type="button">Reset todo</button>
        </form>
        <div class="msg" id="g-msg"></div>
      `)}

      ${card('Presets rápidos',
        'Configuraciones de fallo de un clic para no escribir los valores a mano.',
        `
        <div class="row">
          <button class="btn secondary sm" data-preset="payment-fail">Payment 100% fallo</button>
          <button class="btn secondary sm" data-preset="inventory-latency">Inventory +500ms</button>
          <button class="btn secondary sm" data-preset="order-timeout">Order 20% timeout</button>
          <button class="btn secondary sm" data-preset="user-fail">User 50% fallo</button>
          <button class="btn danger sm" data-preset="reset">Reset todo</button>
        </div>
        <div class="msg" id="r-preset-msg"></div>
      `)}
    </div>

    ${card('Escenarios de prueba',
      'Ejecuta un escenario guiado de resiliencia y observa el resultado: inyecta el fallo, coloca órdenes reales y restaura el estado al final.',
      `
      <div class="row">
        <select id="r-scen">
          <option value="breaker">Circuit breaker (payment al 100%)</option>
          <option value="retries">Reintentos (payment al 30%)</option>
          <option value="latency">Latencia (inventory +500ms)</option>
        </select>
        <button class="btn" id="r-run">Ejecutar escenario</button>
        <span id="r-run-state" class="muted"></span>
      </div>
      <div id="r-results"></div>
      `,
      { full: true })}
  `;

  const $ = (id) => view.querySelector('#' + id);

  // ---- Circuit breaker (live) ----
  const t = setInterval(refreshCB, 3000);
  refreshCB();
  const cleanup = () => clearInterval(t);

  async function refreshCB() {
    try {
      const cb = await API.circuitBreaker();
      $('r-cb').innerHTML =
        `<div style="margin-bottom:8px">${badge(cb.state, cb.state)}</div>` +
        `<div class="muted">fallos: ${cb.failures}/${cb.failure_threshold} · umbral: ${cb.failure_threshold} · recuperación: ${cb.recovery_timeout}s</div>`;
    } catch (_) { $('r-cb').textContent = 'no disponible'; }
  }

  // ---- Chaos por servicio (botones de selección) ----
  let selectedSvc = 'order';
  view.querySelectorAll('#c-svc button').forEach((btn) => {
    btn.addEventListener('click', () => {
      selectedSvc = btn.dataset.svc;
      view.querySelectorAll('#c-svc button').forEach((b) => b.classList.toggle('active', b === btn));
      loadChaosFor(selectedSvc);
    });
  });
  loadChaosFor(selectedSvc);

  async function loadChaosFor(svc) {
    try {
      const c = await API.getChaos(svc);
      $('c-fr').value = c.FAILURE_RATE != null ? Math.round(c.FAILURE_RATE * 100) : '';
      $('c-lm').value = c.LATENCY_MS != null ? c.LATENCY_MS : '';
      $('c-tr').value = c.TIMEOUT_RATE != null ? Math.round(c.TIMEOUT_RATE * 100) : '';
    } catch (_) {
      $('c-fr').value = ''; $('c-lm').value = ''; $('c-tr').value = '';
    }
  }

  $('c-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const cfg = readChaos($('c-fr'), $('c-lm'), $('c-tr'));
    const msg = $('c-msg');
    try {
      await API.chaosSet(selectedSvc, cfg);
      msg.className = 'msg ok';
      msg.textContent = `${selectedSvc}-service: ${formatChaos(cfg)}`;
      toast(`Caos aplicado a ${selectedSvc}-service`, 'ok');
    } catch (err) { msg.className = 'msg err'; msg.textContent = err.message; }
  });

  // ---- Caos global ----
  $('g-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const cfg = readChaos($('g-fr'), $('g-lm'), $('g-tr'));
    const msg = $('g-msg');
    try {
      const res = await API.chaosSetAll(cfg);
      const failed = res.filter((r) => r.error).length;
      msg.className = failed ? 'msg err' : 'msg ok';
      msg.textContent = `Aplicado a los 5 servicios: ${formatChaos(cfg)}${failed ? ` (${failed} con error)` : ''}`;
      toast('Caos aplicado a todos los servicios', failed ? 'err' : 'ok');
    } catch (err) { msg.className = 'msg err'; msg.textContent = err.message; }
  });

  $('g-reset').addEventListener('click', async () => {
    const msg = $('g-msg');
    try { await API.chaosResetAll(); msg.className = 'msg ok'; msg.textContent = 'Caos reseteado en los 5 servicios.'; toast('Caos reseteado', 'ok'); }
    catch (err) { msg.className = 'msg err'; msg.textContent = err.message; }
  });

  // ---- Retries ----
  loadRetries();
  $('r-ret-save').addEventListener('click', async () => {
    const msg = $('r-ret-msg');
    try {
      const r = await API.setRetries({
        enabled: $('r-ret-enabled').checked,
        count: parseInt($('r-ret-count').value) || 0,
        delay_ms: parseInt($('r-ret-delay').value) || 0,
      });
      msg.className = 'msg ok'; msg.textContent = JSON.stringify(r);
      toast('Reintentos actualizados', 'ok');
    } catch (e) { msg.className = 'msg err'; msg.textContent = e.message; }
  });

  async function loadRetries() {
    try {
      const r = await API.getRetries();
      $('r-ret-enabled').checked = !!r.enabled;
      $('r-ret-count').value = r.count;
      $('r-ret-delay').value = r.delay_ms;
    } catch (_) {}
  }

  // ---- Presets ----
  const presets = {
    'payment-fail': () => API.chaosSet('payment', { FAILURE_RATE: 1.0 }),
    'inventory-latency': () => API.chaosSet('inventory', { LATENCY_MS: 500 }),
    'order-timeout': () => API.chaosSet('order', { TIMEOUT_RATE: 0.2 }),
    'user-fail': () => API.chaosSet('user', { FAILURE_RATE: 0.5 }),
    'reset': () => API.chaosResetAll(),
  };
  view.querySelectorAll('[data-preset]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const m = $('r-preset-msg');
      try { await presets[btn.dataset.preset](); m.className = 'msg ok'; m.textContent = 'aplicado'; }
      catch (e) { m.className = 'msg err'; m.textContent = e.message; }
    });
  });

  // ---- Scenarios ----
  $('r-run').addEventListener('click', () => runScenario($('r-scen').value));

  async function runScenario(kind) {
    const state = $('r-run-state');
    const results = $('r-results');
    const btn = $('r-run');
    btn.disabled = true;
    state.textContent = 'ejecutando…';
    results.innerHTML = '<div class="loading"><span class="spin"></span> ejecutando…</div>';
    try {
      const productId = await pickInStockProduct();
      if (productId == null) {
        results.innerHTML = '<div class="msg err">No hay productos con stock. Genera inventario (pestaña Inventario) antes de ejecutar un escenario.</div>';
        return;
      }
      let out;
      if (kind === 'breaker') out = await scenarioBreaker(1, productId);
      else if (kind === 'retries') out = await scenarioRetries(1, productId);
      else out = await scenarioLatency(1, productId);
      results.innerHTML = out;
    } catch (e) {
      results.innerHTML = '<div class="msg err">Error: ' + esc(e.message) + '</div>';
    } finally {
      state.textContent = 'listo';
      btn.disabled = false;
      refreshCB();
    }
  }

  async function pickInStockProduct() {
    const prods = await API.listEntities('products', 0, 50);
    const inStock = (Array.isArray(prods) ? prods : []).filter((p) => (p.quantity ?? 0) > 0);
    return inStock.length ? inStock[0].product_id : null;
  }

  async function scenarioBreaker(uid, pid) {
    await API.chaosResetAll();
    await API.chaosSet('payment', { FAILURE_RATE: 1.0 });
    const rows = [];
    let fastFail = 0, declined = 0;
    for (let i = 0; i < 6; i++) {
      const r = await API.placeOrder(uid, pid, 1);
      const pm = (r.downstream && r.downstream.payment && r.downstream.payment.message) || r.message || '';
      if (pm === 'circuit_breaker_open') fastFail++;
      else declined++;
      rows.push([i + 1, r.status, pm]);
    }
    const cb = await API.circuitBreaker();
    await API.chaosResetAll();
    return `<p class="muted">6 órdenes con payment al 100% de fallo. El breaker se abre tras 3 fallos y rechaza rápido el resto (sin llegar a payment-service).</p>
      ${table(['#', 'Estado', 'Resultado'], rows)}
      <div class="row" style="margin-top:8px">
        <b>Rechazadas rápido (breaker OPEN): ${fastFail}</b>
        <span class="muted">· llegaron a payment (declined): ${declined}</span>
        <span class="muted">· estado final del breaker: ${badge(cb.state, cb.state)}</span>
      </div>`;
  }

  async function scenarioRetries(uid, pid) {
    await API.chaosResetAll();
    await API.setRetries({ enabled: false });
    await API.chaosSet('payment', { FAILURE_RATE: 0.3 });
    await API.setRetries({ enabled: true, count: 3, delay_ms: 100 });
    let ok = 0, fail = 0;
    for (let i = 0; i < 10; i++) {
      const r = await API.placeOrder(uid, pid, 1);
      if (r.status === 'success') ok++; else fail++;
    }
    await API.setRetries({ enabled: false });
    await API.chaosResetAll();
    return `<p class="muted">10 órdenes con payment al 30% de fallo y reintentos activados (3 intentos). Sin reintentos el éxito esperado sería ~70%; con reintentos debe ser mucho mayor.</p>
      <div class="row"><b>Éxito: ${ok}/10</b> <span class="muted">· fallos: ${fail}</span></div>`;
  }

  async function scenarioLatency(uid, pid) {
    await API.chaosResetAll();
    await API.chaosSet('inventory', { LATENCY_MS: 500 });
    const times = [];
    for (let i = 0; i < 3; i++) {
      const r = await API.placeOrder(uid, pid, 1);
      if (r.timings && r.timings.inventory_ms != null) times.push(r.timings.inventory_ms);
    }
    await API.chaosResetAll();
    const avg = times.length ? Math.round(times.reduce((a, b) => a + b, 0) / times.length) : 0;
    return `<p class="muted">3 órdenes con 500ms de latencia artificial en inventory-service. La latencia por salto sale del campo timings de la respuesta.</p>
      <div class="row"><b>Latencia media de inventory: ${avg} ms</b> <span class="muted">(esperado ~500ms)</span></div>`;
  }

  return cleanup;
}

function readChaos(frEl, lmEl, trEl) {
  const cfg = {};
  if (frEl.value !== '') cfg.FAILURE_RATE = Math.max(0, Math.min(100, parseFloat(frEl.value))) / 100;
  if (lmEl.value !== '') cfg.LATENCY_MS = parseInt(lmEl.value);
  if (trEl.value !== '') cfg.TIMEOUT_RATE = Math.max(0, Math.min(100, parseFloat(trEl.value))) / 100;
  return cfg;
}

function formatChaos(cfg) {
  const fr = cfg.FAILURE_RATE != null ? Math.round(cfg.FAILURE_RATE * 100) : 0;
  const lm = cfg.LATENCY_MS != null ? cfg.LATENCY_MS : 0;
  const tr = cfg.TIMEOUT_RATE != null ? Math.round(cfg.TIMEOUT_RATE * 100) : 0;
  return `fallo ${fr}% · latencia ${lm} ms · timeout ${tr}%`;
}
