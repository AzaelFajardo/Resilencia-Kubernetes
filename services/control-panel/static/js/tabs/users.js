// users.js — Clientes: resumen, recientes, generación y CRUD.

import { API } from '../api.js';
import { card, table, esc } from '../ui.js';
import { mountCrud } from '../crud.js';

export function render(view) {
  view.innerHTML = `
    <div class="grid">
      ${card('Resumen de clientes',
        'Total de clientes persistidos en PostgreSQL (tabla users, perfil completo en columna JSONB).',
        table(['Métrica', 'Valor'], [])
          .replace('<tbody></tbody>', '<tbody id="u-count"></tbody>'))}
      ${card('Clientes recientes',
        'Últimos clientes creados (por id descendente).',
        table(['ID', 'Nombre', 'Email', 'Estado'], [])
          .replace('<tbody></tbody>', '<tbody id="u-recent"></tbody>'))}
      ${card('Generar datos',
        'Genera los clientes de ejemplo integrados. En la Fase F1 se añadirá generación Faker ilimitada con cantidad (nombre, email, etc. aleatorios).',
        '<button id="u-gen" class="btn secondary" type="button">Generar usuarios</button><span class="msg" id="u-genmsg"></span>')}
    </div>
  `;

  mountCrud(view, 'users', 'Clientes');

  refresh();

  view.querySelector('#u-gen').addEventListener('click', async () => {
    const m = view.querySelector('#u-genmsg');
    try { const r = await API.generate('users'); m.className = 'msg ok'; m.textContent = JSON.stringify(r); refresh(); }
    catch (e) { m.className = 'msg err'; m.textContent = e.message; }
  });

  async function refresh() {
    try {
      const c = await API.counts();
      view.querySelector('#u-count').innerHTML =
        `<tr><td>total</td><td>${esc(c.user ?? '—')}</td></tr>`;
    } catch (_) {}
    try {
      const r = await API.recent('users', 10);
      view.querySelector('#u-recent').innerHTML = r.map((u) =>
        `<tr><td>${u.id}</td><td>${esc(u.first_name)}</td><td>${esc(u.email)}</td><td>${u.active ? 'activo' : 'inactivo'}</td></tr>`
      ).join('') || `<tr><td colspan="4" class="muted">sin clientes</td></tr>`;
    } catch (_) {}
  }
}
