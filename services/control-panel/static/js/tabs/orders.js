// orders.js — Órdenes: colocar, historial, recientes y CRUD.

import { API } from '../api.js';
import { card, table, esc } from '../ui.js';
import { mountCrud } from '../crud.js';

export function render(view) {
  view.innerHTML = `
    <div class="grid">
      ${card('Colocar orden',
        'Envía una orden al flujo real: order-service valida al usuario en user-service, reserva inventario en inventory-service, procesa el pago en payment-service y envía la notificación en notification-service. Úsala también para reproducir casos de error (usuario inactivo, sin stock, pago fallido con caos).',
        `
        <form id="o-form" class="row">
          <label>user_id <input id="o-user" type="number" value="1" min="1"></label>
          <label>product_id <input id="o-prod" type="number" value="1" min="1"></label>
          <label>cantidad <input id="o-qty" type="number" value="1" min="1"></label>
          <button class="btn">Colocar</button>
        </form>
        <div class="msg" id="o-msg"></div>
        <pre class="pre" id="o-out">—</pre>
      `)}
      ${card('Historial de pedidos por usuario',
        'Órdenes de un cliente concreto. user-service lee directamente la tabla compartida orders (sin salto de red extra).',
        `
        <form id="h-form" class="row">
          <label>user_id <input id="h-user" type="number" value="1" min="1"></label>
          <button class="btn secondary">Ver</button>
        </form>
        <pre class="pre" id="h-out">—</pre>
      `)}
      ${card('Órdenes recientes',
        'Últimas órdenes registradas, con su estado de negocio y estado interno del flujo.',
        table(['ID', 'Usuario', 'Producto', 'Cant.', 'Estado', 'Interno'], [])
          .replace('<tbody></tbody>', '<tbody id="o-recent"></tbody>'))}
    </div>
  `;

  mountCrud(view, 'orders', 'Órdenes');

  refreshRecent();

  view.querySelector('#o-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const msg = view.querySelector('#o-msg');
    const out = view.querySelector('#o-out');
    try {
      const r = await API.placeOrder(
        parseInt(view.querySelector('#o-user').value),
        parseInt(view.querySelector('#o-prod').value),
        parseInt(view.querySelector('#o-qty').value)
      );
      msg.className = 'msg ' + (r.status === 'success' ? 'ok' : 'err');
      msg.textContent = 'status: ' + r.status + (r.message ? ' — ' + r.message : '');
      out.textContent = JSON.stringify(r, null, 2);
      refreshRecent();
    } catch (err) { msg.className = 'msg err'; msg.textContent = err.message; }
  });

  view.querySelector('#h-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const out = view.querySelector('#h-out');
    try {
      const r = await API.userOrders(parseInt(view.querySelector('#h-user').value), 20);
      out.textContent = JSON.stringify(r, null, 2);
    } catch (err) { out.textContent = 'Error: ' + err.message; }
  });

  async function refreshRecent() {
    try {
      const r = await API.recent('orders', 12);
      view.querySelector('#o-recent').innerHTML = r.map((o) =>
        `<tr><td>${o.id}</td><td>${o.user_id}</td><td>${o.product_id}</td><td>${o.quantity}</td><td>${esc(o.status)}</td><td>${esc(o.internal_status)}</td></tr>`
      ).join('') || `<tr><td colspan="6" class="muted">sin órdenes todavía</td></tr>`;
    } catch (_) {}
  }
}
