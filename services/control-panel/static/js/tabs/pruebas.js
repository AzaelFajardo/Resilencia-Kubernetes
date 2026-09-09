// pruebas.js — Pruebas: ráfagas masivas y simulación continua de tráfico.

import { API } from '../api.js';
import { card, badge, toast, esc } from '../ui.js';

export function render(view) {
  view.innerHTML = `
    <div class="grid">
      ${card('Ráfaga masiva de pedidos',
        'Envía un lote de pedidos a la vez recorriendo el flujo real. Puedes repartirlos entre N clientes (orders_per_client = pedidos por cliente) o fijar un cliente/producto concreto. quantity = artículos por pedido. Observa el efecto en la pestaña Observabilidad o en Grafana.',
        `
        <form id="b-form" class="row">
          <label>total pedidos <input id="b-count" type="number" min="1" value="100"></label>
          <label>clientes <input id="b-clients" type="number" min="1" placeholder="opcional"></label>
          <label>pedidos/cliente <input id="b-per" type="number" min="1" placeholder="opcional"></label>
          <label>artículos/pedido <input id="b-qty" type="number" min="1" value="1"></label>
        </form>
        <div class="row">
          <label>user_id <input id="b-user" type="number" min="1" placeholder="opcional"></label>
          <label>product_id <input id="b-prod" type="number" min="1" placeholder="opcional"></label>
          <button class="btn" id="b-go">Enviar</button>
        </div>
        <div class="msg" id="b-msg"></div>
        <pre class="pre" id="b-out" style="max-height:160px">—</pre>
      `)}
      ${card('Simulación continua (día a día)',
        'Genera pedidos de forma continua y aleatoria (cliente y producto al azar) a una tasa fija, hasta que lo detengas. Úsalo para ver en tiempo real cómo responden los servicios y las métricas (latencia, throughput, errores) en Observabilidad / Grafana.',
        `
        <form id="s-form" class="row">
          <label>tasa (req/s) <input id="s-rate-input" type="number" min="0.1" max="50" step="0.5" value="5"></label>
          <label>artículos/pedido <input id="s-qty" type="number" min="1" value="1"></label>
          <label>clientes <input id="s-clients" type="number" min="1" placeholder="todos"></label>
          <label>duración (s) <input id="s-dur" type="number" min="1" placeholder="hasta detener"></label>
        </form>
        <div class="row">
          <button class="btn" id="s-start">Iniciar</button>
          <button class="btn danger" id="s-stop">Detener</button>
          <span id="s-state" class="muted"></span>
        </div>
        <table class="tbl">
          <thead><tr><th>Enviados</th><th>Éxitos</th><th>Fallos</th><th>Tasa (req/s)</th></tr></thead>
          <tbody><tr>
            <td id="s-sent">—</td><td id="s-success">—</td><td id="s-failed">—</td><td id="s-rate">—</td>
          </tr></tbody>
        </table>
      `)}
    </div>
    ${card('Ver el efecto en métricas',
      'Estos pedidos reales alimentan Prometheus y se reflejan en la pestaña Observabilidad (latencia y recursos por servicio) y en el dashboard de Grafana.',
      `<div class="row">
        <a href="#/observability" class="btn secondary">Ir a Observabilidad</a>
        <a href="http://localhost:3001" target="_blank" class="btn secondary">Abrir Grafana</a>
      </div>`,
      { full: true })}
  `;

  const $ = (id) => view.querySelector('#' + id);
  const intOr = (id) => { const v = $(id).value; return v === '' ? null : parseInt(v); };

  // ---- Ráfaga masiva ----
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
      msg.className = 'msg ok'; msg.textContent = `generados: ${r.generated} · fallidos: ${r.failed}`;
      out.textContent = JSON.stringify(r, null, 2);
    } catch (e) { msg.className = 'msg err'; msg.textContent = e.message; out.textContent = ''; }
  });

  // ---- Simulación continua ----
  let pollTimer = null;

  async function refreshStatus() {
    try {
      const s = await API.simulateStatus();
      $('s-state').innerHTML = s.running ? badge('EN EJECUCIÓN', 'ok') : badge('detenida', 'bad');
      $('s-sent').textContent = s.sent;
      $('s-success').textContent = s.success;
      $('s-failed').textContent = s.failed;
      $('s-rate').textContent = s.rate;
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
      toast('Simulación iniciada', 'ok');
    } catch (e) { toast('Error: ' + e.message, 'err'); }
    if (!pollTimer) pollTimer = setInterval(async () => { const running = await refreshStatus(); if (!running) { clearInterval(pollTimer); pollTimer = null; } }, 2000);
    refreshStatus();
  });

  $('s-stop').addEventListener('click', async () => {
    try { await API.simulateStop(); toast('Simulación detenida', 'ok'); }
    catch (e) { toast('Error: ' + e.message, 'err'); }
    refreshStatus();
  });

  refreshStatus();
}
