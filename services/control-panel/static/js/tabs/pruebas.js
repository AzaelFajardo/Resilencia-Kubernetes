// pruebas.js — Pruebas: pedidos en lote y tráfico continuo, con enlace a métricas.

import { API } from '../api.js';
import { card, badge, toast, esc } from '../ui.js';

export function render(view) {
  view.innerHTML = `
    <div class="grid">
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
    </div>
    ${card('Ver el efecto en las métricas',
      'Estos pedidos reales alimentan Prometheus. Abre las métricas en otra ventana y ejecuta una prueba aquí para ver al momento cómo cambian la latencia, el número de peticiones y los recursos.',
      `<div class="row">
        <a href="#/observability" target="_blank" class="btn">Ver métricas en otra ventana</a>
        <a href="http://localhost:3001" target="_blank" class="btn secondary">Abrir Grafana</a>
      </div>`,
      { full: true })}
  `;

  const $ = (id) => view.querySelector('#' + id);
  const intOr = (id) => { const v = $(id).value; return v === '' ? null : parseInt(v); };

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

  async function refreshStatus() {
    try {
      const s = await API.simulateStatus();
      $('s-state').innerHTML = s.running ? badge('EN EJECUCIÓN', 'ok') : badge('detenido', 'bad');
      $('s-sent').textContent = s.sent;
      $('s-success').textContent = s.success;
      $('s-failed').textContent = s.failed;
      $('s-rate').textContent = s.rate + ' req/s';
      return s.running;
    } catch (e) { $('s-state').textContent = 'no disponible'; return false; }
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

  refreshStatus();
}
