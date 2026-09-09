// payments.js — Pagos: resumen, recientes y CRUD.

import { API } from '../api.js';
import { card, table, esc } from '../ui.js';
import { mountCrud } from '../crud.js';

export function render(view) {
  view.innerHTML = `
    <div class="grid">
      ${card('Resumen de pagos',
        'Total de pagos persistidos (tabla payments).',
        table(['Métrica', 'Valor'], [])
          .replace('<tbody></tbody>', '<tbody id="p-count"></tbody>'))}
      ${card('Pagos recientes',
        'Últimos pagos registrados, con su estado (completed / declined / failed).',
        table(['ID', 'Orden', 'Estado', 'Total', 'Método'], [])
          .replace('<tbody></tbody>', '<tbody id="p-recent"></tbody>'))}
    </div>
  `;

  mountCrud(view, 'payments', 'Pagos');

  refresh();

  async function refresh() {
    try {
      const c = await API.counts();
      view.querySelector('#p-count').innerHTML =
        `<tr><td>total</td><td>${esc(c.payment ?? '—')}</td></tr>`;
    } catch (_) {}
    try {
      const r = await API.recent('payments', 12);
      view.querySelector('#p-recent').innerHTML = r.map((p) =>
        `<tr><td>${p.id}</td><td>${p.order_id}</td><td>${esc(p.status)}</td><td>${p.order_total}</td><td>${esc(p.method)}</td></tr>`
      ).join('') || `<tr><td colspan="5" class="muted">sin pagos todavía</td></tr>`;
    } catch (_) {}
  }
}
