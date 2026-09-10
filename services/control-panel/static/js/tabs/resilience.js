// resilience.js — Resiliencia y caos: circuit breaker, chaos (por servicio y
// global), reintentos, presets y escenarios de prueba.

import { API } from '../api.js';
import { card, badge, toast, esc, table } from '../ui.js';
import { mountRefreshControl } from '../interval.js';

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
    </div>
  `;

  const $ = (id) => view.querySelector('#' + id);

  // ---- Circuit breaker (live) ----
  const refreshCleanup = mountRefreshControl(view, { onRefresh: refreshCB, initial: 3 });
  refreshCB();
  const cleanup = () => refreshCleanup();

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

  return cleanup;erado ~500ms)</span></div>`;
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
