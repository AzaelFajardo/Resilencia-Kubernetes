// notifications.js — Notificaciones: búsqueda, listado y borrado.

import { mountEntity } from '../entity.js';

export function render(view) {
  mountEntity(view, {
    entity: 'notifications',
    label: 'Notificaciones',
    hint: 'Notificaciones persistidas por notification-service (sent = enviada, failed = fallo simulado). Busca por id de orden/usuario, estado o canal. Haz clic en una fila para el detalle o para borrarla.',
    columns: [
      { label: 'ID', key: 'id' },
      { label: 'Orden', key: 'order_id' },
      { label: 'Usuario', key: 'user_id' },
      { label: 'Estado', key: 'status', render: (r) => `<span class="badge ${r.status === 'sent' ? 'ok' : 'bad'}">${r.status}</span>` },
      { label: 'Canal', key: 'preferred_channel' },
    ],
  });
}
