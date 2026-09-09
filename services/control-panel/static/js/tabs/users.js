// users.js — Clientes: búsqueda, listado, fakers y edición.

import { mountEntity } from '../entity.js';

export function render(view) {
  mountEntity(view, {
    entity: 'users',
    label: 'Clientes',
    hint: 'Clientes persistidos en PostgreSQL (perfil completo en JSONB). Busca por id, nombre o email. "Generar Clientes" crea registros Faker reales (sin límite). Haz clic en una fila para ver el detalle, editar o borrar.',
    columns: [
      { label: 'ID', key: 'id' },
      { label: 'Nombre', key: 'first_name' },
      { label: 'Apellido', key: 'last_name' },
      { label: 'Email', key: 'email' },
      { label: 'Nivel', key: 'loyalty_tier' },
      { label: 'Activo', key: 'active', render: (r) => `<span class="badge ${r.active ? 'ok' : 'bad'}">${r.active ? 'activo' : 'inactivo'}</span>` },
    ],
    faker: { what: 'users', label: 'Clientes' },
    editFields: [
      { name: 'first_name', label: 'Nombre' },
      { name: 'last_name', label: 'Apellido' },
      { name: 'email', label: 'Email' },
      { name: 'active', label: 'Activo', type: 'select', options: ['true', 'false'] },
    ],
    buildEdit: (d) => ({ first_name: d.first_name, last_name: d.last_name, email: d.email, active: d.active === 'true' }),
  });
}
