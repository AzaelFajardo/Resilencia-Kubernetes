// notifications.js — Notificaciones: resumen, recientes y CRUD.

import { API } from '../api.js';
import { card, table, esc } from '../ui.js';
import { mountCrud } from '../crud.js';

export function render(view) {
  view.innerHTML = `
    <div class="grid">
      ${card('Resumen de notificaciones',
        'Total de notificaciones persistidas (tabla notifications).',
        table(['Métrica', 'Valor'], [])
          .replace('<tbody></tbody>', '<tbody id="n-count"></tbody>'))}
      ${card('Notificaciones recientes',
        'Últimas notificaciones registradas, con canal preferido y estado (sent / failed).',
        table(['ID', 'Orden', 'Usuario', 'Estado', 'Canal'], [])
          .replace('<tbody></tbody>', '<tbody id="n-recent"></tbody>'))}
    </div>
  `;

  mountCrud(view, 'notifications', 'Notificaciones');

  refresh();

  async function refresh() {
    try {
      const c = await API.counts();
      view.querySelector('#n-count').innerHTML =
        `<tr><td>total</td><td>${esc(c.notification ?? '—')}</td></tr>`;
    } catch (_) {}
    try {
      const r = await API.recent('notifications', 12);
      view.querySelector('#n-recent').innerHTML = r.map((n) =>
        `<tr><td>${n.id}</td><td>${n.order_id}</td><td>${n.user_id}</td><td>${esc(n.status)}</td><td>${esc(n.preferred_channel)}</td></tr>`
      ).join('') || `<tr><td colspan="5" class="muted">sin notificaciones todavía</td></tr>`;
    } catch (_) {}
  }
}
