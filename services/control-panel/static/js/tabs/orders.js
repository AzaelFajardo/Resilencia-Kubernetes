// orders.js — Órdenes: colocar, historial, listado/búsqueda y generación masiva.

import { API } from '../api.js';
import { card, esc, toast } from '../ui.js';
import { mountEntity } from '../entity.js';

export function render(view) {
  view.innerHTML = `
    <div class="grid">
      ${card('Colocar orden',
        'Envía una orden al flujo real: order-service valida al usuario, reserva inventario, procesa el pago y envía la notificación. Úsala también para reproducir casos de error (usuario inactivo, sin stock, pago fallido con caos).',
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
    </div>
  `;

  mountEntity(view, {
    entity: 'orders',
    label: 'Órdenes',
    hint: 'Todas las órdenes persistidas por order-service. Busca por id, usuario o estado. "Generar órdenes" recorre el flujo real N veces (opcionalmente para un solo cliente). Haz clic en una fila para detalle, editar estado/prioridad o borrar.',
    columns: [
      { label: 'ID', key: 'id' },
      { label: 'Usuario', key: 'user_id' },
      { label: 'Producto', key: 'product_id' },
      { label: 'Cant.', key: 'quantity' },
      { label: 'Total', key: 'total_price' },
      { label: 'Estado', key: 'status', render: (r) => `<span class="badge ${r.status === 'paid' ? 'ok' : r.status === 'cancelled' ? 'bad' : 'warn'}">${r.status}</span>` },
      { label: 'Interno', key: 'internal_status' },
    ],
    bulkOrders: true,
    editFields: [
      { name: 'status', label: 'Estado', type: 'select', options: ['pending', 'confirmed', 'processing', 'paid', 'shipped', 'delivered', 'cancelled', 'returned'] },
      { name: 'priority', label: 'Prioridad', type: 'select', options: ['normal', 'high', 'low', 'none'] },
    ],
    buildEdit: (d) => ({ status: d.status, priority: d.priority }),
  });

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
      if (r.status !== 'success') {
        toast(`No se completó la orden: ${r.message || r.status}`, 'err');
      }
    } catch (err) {
      msg.className = 'msg err'; msg.textContent = err.message;
      toast('No se pudo enviar la orden (¿algún servicio está detenido?): ' + err.message, 'err');
    }
  });

  view.querySelector('#h-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const out = view.querySelector('#h-out');
    try {
      const r = await API.userOrders(parseInt(view.querySelector('#h-user').value), 20);
      out.textContent = JSON.stringify(r, null, 2);
    } catch (err) { out.textContent = 'Error: ' + err.message; }
  });
}
