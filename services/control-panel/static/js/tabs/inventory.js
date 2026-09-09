// inventory.js — Inventario: búsqueda, listado, fakers y edición.

import { mountEntity } from '../entity.js';

export function render(view) {
  mountEntity(view, {
    entity: 'products',
    label: 'Inventario',
    hint: 'Productos del catálogo (25 campos en JSONB + columna de stock). Busca por id o nombre. "Generar Productos" crea registros Faker reales (sin límite). Haz clic en una fila para detalle, editar stock/precio/nombre o borrar.',
    columns: [
      { label: 'ID', key: 'product_id' },
      { label: 'Nombre', key: 'name' },
      { label: 'Categoría', key: 'category' },
      { label: 'Stock', key: 'quantity' },
      { label: 'Precio', key: 'unit_price' },
    ],
    faker: { what: 'inventory', label: 'Productos' },
    editFields: [
      { name: 'name', label: 'Nombre' },
      { name: 'unit_price', label: 'Precio', type: 'number' },
      { name: 'quantity', label: 'Stock', type: 'number' },
    ],
    buildEdit: (d) => ({ name: d.name, unit_price: d.unit_price, quantity: d.quantity }),
  });
}
