// payments.js — Pagos: búsqueda, listado y borrado.

import { mountEntity } from '../entity.js';

export function render(view) {
  mountEntity(view, {
    entity: 'payments',
    label: 'Pagos',
    hint: 'Pagos persistidos por payment-service (completed = cobrado, declined = rechazado por fraude, failed = fallo simulado). Busca por id de orden, estado o método. Haz clic en una fila para el detalle o para borrarlo.',
    columns: [
      { label: 'ID', key: 'id' },
      { label: 'Orden', key: 'order_id' },
      { label: 'Estado', key: 'status', render: (r) => `<span class="badge ${r.status === 'completed' ? 'ok' : 'bad'}">${r.status}</span>` },
      { label: 'Total', key: 'order_total' },
      { label: 'Método', key: 'method' },
    ],
  });
}
