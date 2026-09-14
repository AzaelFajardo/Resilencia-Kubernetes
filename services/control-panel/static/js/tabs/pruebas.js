// pruebas.js — Pruebas: pedidos en lote, tráfico continuo, resiliencia y caos.

import { API } from '../api.js';
import { card, badge, toast, esc, confirmDialog, table, fmt } from '../ui.js';

const SVC_KEYS = ['order', 'user', 'inventory', 'payment', 'notification'];

export function render(view) {
  view.innerHTML = `
    <div class="row" style="justify-content:flex-end;margin-bottom:12px">
      <a href="#/observability" target="_blank" class="btn">Ver métricas</a>
    </div>

    <div class="grid">
      ${card('Tráfico continuo',
        'Envía pedidos sin parar, uno tras otro, a la velocidad que elijas, hasta que lo detengas. Ideal para simular el uso normal del sistema y ver las métricas en vivo.',
        `
        <form id="s-form" class="row">
          <label data-tip="Cuántos pedidos se envían cada segundo.">Pedidos por segundo <input id="s-rate-input" type="number" min="0.1" step="0.5" value="5"></label>
          <label data-tip="Cuántos artículos compra cada pedido.">Artículos por pedido <input id="s-qty" type="number" min="1" value="1"></label>
          <label data-tip="Reparte el tráfico entre esta cantidad de clientes (opcional; vacío = todos).">Nº de clientes <input id="s-clients" type="number" min="1" placeholder="opcional"></label>
          <label data-tip="Detiene el tráfico después de esta duración (opcional; vacío = hasta que pulses Detener).">Duración (segundos) <input id="s-dur" type="number" min="1" placeholder="opcional"></label>
        </form>
        <div class="row">
          <button class="btn" id="s-start">Empezar tráfico</button>
          <button class="btn danger" id="s-stop">Detener</button>
          <span id="s-state" class="muted"></span>
        </div>
        <table class="tbl">
          <thead><tr><th>Pedidos enviados</th><th>Exitosos</th><th>Fallidos</th><th>Velocidad</th></tr></thead>
          <tbody><tr>
            <td id="s-sent">—</td><td id="s-success">—</td><td id="s-failed">—</td><td id="s-rate">—</td>
          </tr></tbody>
        </table>
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

      ${card('Pedidos en lote',
        'Crea de una sola vez una cantidad fija de pedidos. Cada pedido recorre el flujo real completo (valida cliente → reserva inventario → paga → notifica).',
        `
        <form id="b-form" class="row">
          <label data-tip="Cuántos pedidos se crean en total.">Cantidad de pedidos <input id="b-count" type="number" min="1" value="100"></label>
          <label data-tip="Reparte los pedidos entre esta cantidad de clientes (opcional).">Nº de clientes <input id="b-clients" type="number" min="1" placeholder="opcional"></label>
          <label data-tip="Si indicas clientes, cuántos pedidos recibe cada uno (opcional).">Pedidos por cliente <input id="b-per" type="number" min="1" placeholder="opcional"></label>
          <label data-tip="Cuántos artículos compra cada pedido.">Artículos por pedido <input id="b-qty" type="number" min="1" value="1"></label>
        </form>
        <div class="row">
          <label data-tip="Fija todos los pedidos a un cliente por su id (opcional).">Cliente concreto <input id="b-user" type="number" min="1" placeholder="opcional"></label>
          <label data-tip="Fija todos los pedidos a un producto por su id (opcional).">Producto concreto <input id="b-prod" type="number" min="1" placeholder="opcional"></label>
          <button class="btn" id="b-go">Crear pedidos</button>
        </div>
        <div class="msg" id="b-msg"></div>
        <pre class="pre" id="b-out" style="max-height:160px">—</pre>
      `)}
      ${card('REINTENTOS (CONFIGURACION)',
        'Parámetros de reintento de order-service cuando el sistema está en Modo Reintentos. Permite ajustar el número de reintentos y el tiempo de espera entre intentos.',
        `
        <div id="r-ret-notice" class="msg warn" style="display:none;margin-bottom:10px;padding:8px 12px;border-radius:8px;background:var(--warn-bg,#3a2f0f);color:var(--warn-fg,#f5a623);font-size:12px"></div>
        <div class="row">
          <label>reintentos <input id="r-ret-count" type="number" min="0" max="10" value="3"></label>
          <label>espera (ms) <input id="r-ret-delay" type="number" min="0" value="100"></label>
          <button class="btn sm" id="r-ret-save">Guardar</button>
        </div>
        <div class="msg" id="r-ret-msg"></div>
      `)}
    </div>
  `;

  const $ = (id) => view.querySelector('#' + id);
  const intOr = (id) => { const v = $(id).value; return v === '' ? null : parseInt(v); };

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
    if ($('r-ret-save').disabled) return;
    try {
      const r = await API.setRetries({
        count: parseInt($('r-ret-count').value) || 0,
        delay_ms: parseInt($('r-ret-delay').value) || 0,
      });
      msg.className = 'msg ok'; msg.textContent = JSON.stringify(r);
      toast('Reintentos actualizados', 'ok');
    } catch (e) { msg.className = 'msg err'; msg.textContent = e.message; }
  });

  async function loadRetries() {
    try {
      const modeData = await API.getMode();
      const runtimeData = await API.getRuntimeMode().catch(() => ({ mode: 'compose' }));
      const isRetriesMode = runtimeData.mode === 'compose' && modeData.mode === 'retries';
      const retriesConfig = modeData.retries || (await API.getRetries());

      $('r-ret-count').value = retriesConfig.count ?? 3;
      $('r-ret-delay').value = retriesConfig.delay_ms ?? 100;

      const noticeEl = $('r-ret-notice');
      const countEl = $('r-ret-count');
      const delayEl = $('r-ret-delay');
      const saveBtn = $('r-ret-save');

      if (!isRetriesMode) {
        countEl.disabled = true;
        delayEl.disabled = true;
        saveBtn.disabled = true;
        noticeEl.style.display = 'block';
        noticeEl.innerHTML = 'El sistema no está en <b>Modo Reintentos</b>. Cambia al modo <b>Reintentos</b> desde la pestaña de <b>Inicio</b> para usar esta configuración.';
      } else {
        countEl.disabled = false;
        delayEl.disabled = false;
        saveBtn.disabled = false;
        noticeEl.style.display = 'none';
      }
    } catch (_) {}
  }



  // ---- Pedidos en lote ----
  $('b-go').addEventListener('click', async () => {
    const cfg = { count: intOr('b-count') || 1 };
    const clients = intOr('b-clients'); if (clients) cfg.clients = clients;
    const per = intOr('b-per'); if (per) cfg.orders_per_client = per;
    const qty = intOr('b-qty'); if (qty) cfg.quantity = qty;
    const user = intOr('b-user'); if (user) cfg.user_id = user;
    const prod = intOr('b-prod'); if (prod) cfg.product_id = prod;
    const msg = $('b-msg'); const out = $('b-out');
    out.textContent = 'enviando…';
    try {
      const r = await API.generateOrders(cfg);
      msg.className = 'msg ok'; msg.textContent = `creados: ${r.generated} · fallidos: ${r.failed}`;
      out.textContent = JSON.stringify(r, null, 2);
      toast(`Pedidos creados: ${r.generated} (${r.failed} fallidos)`, r.failed ? 'err' : 'ok');
    } catch (e) { msg.className = 'msg err'; msg.textContent = e.message; out.textContent = ''; toast('Error: ' + e.message, 'err'); }
  });

  // ---- Tráfico continuo ----
  let pollTimer = null;
  let statusInFlight = false;

  async function refreshStatus() {
    if (statusInFlight) return true;
    statusInFlight = true;
    try {
      const s = await API.simulateStatus();
      $('s-state').innerHTML = s.running ? badge('EN EJECUCIÓN', 'ok') : badge('detenido', 'bad');
      $('s-sent').textContent = s.sent;
      $('s-success').textContent = s.success;
      $('s-failed').textContent = s.failed;
      $('s-rate').textContent = s.rate + ' req/s';
      return s.running;
    } catch (e) { $('s-state').textContent = 'no disponible'; return false; }
    finally { statusInFlight = false; }
  }

  $('s-start').addEventListener('click', async () => {
    const cfg = { rate: parseFloat($('s-rate-input').value) || 5 };
    const qty = intOr('s-qty'); if (qty) cfg.quantity = qty;
    const clients = intOr('s-clients'); if (clients) cfg.clients = clients;
    const dur = intOr('s-dur'); if (dur) cfg.duration = dur;
    try {
      await API.simulateStart(cfg);
      toast('Tráfico continuo iniciado', 'ok');
    } catch (e) { toast('Error: ' + e.message, 'err'); }
    if (!pollTimer) pollTimer = setInterval(async () => { const running = await refreshStatus(); if (!running) { clearInterval(pollTimer); pollTimer = null; } }, 2000);
    refreshStatus();
  });

  $('s-stop').addEventListener('click', async () => {
    try { await API.simulateStop(); toast('Tráfico detenido', 'ok'); }
    catch (e) { toast('Error: ' + e.message, 'err'); }
    refreshStatus();
  });

  refreshStatus().then((running) => {
    if (running && !pollTimer) {
      pollTimer = setInterval(async () => {
        const running = await refreshStatus();
        if (!running) { clearInterval(pollTimer); pollTimer = null; }
      }, 2000);
    }
  });

  return () => { if (pollTimer) clearInterval(pollTimer); };
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
