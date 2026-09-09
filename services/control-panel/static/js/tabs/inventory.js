// inventory.js — Inventario: resumen, stock, generación y CRUD.

import { API } from '../api.js';
import { card, table, esc } from '../ui.js';
import { mountCrud } from '../crud.js';

export function render(view) {
  view.innerHTML = `
    <div class="grid">
      ${card('Resumen de inventario',
        'Total de productos y cuántos tienen stock disponible (quantity > 0).',
        table(['Métrica', 'Valor'], [])
          .replace('<tbody></tbody>', '<tbody id="i-count"></tbody>'))}
      ${card('Productos en stock',
        'Productos con stock disponible, ordenados por cantidad descendente.',
        table(['ID', 'Nombre', 'Cant.'], [])
          .replace('<tbody></tbody>', '<tbody id="i-stock"></tbody>'))}
      ${card('Generar datos',
        'Genera los productos de ejemplo integrados. En la Fase F1 se añadirá generación Faker ilimitada con cantidad.',
        '<button id="i-gen" class="btn secondary" type="button">Generar inventario</button><span class="msg" id="i-genmsg"></span>')}
    </div>
  `;

  mountCrud(view, 'inventory', 'Inventario');

  refresh();

  view.querySelector('#i-gen').addEventListener('click', async () => {
    const m = view.querySelector('#i-genmsg');
    try { const r = await API.generate('inventory'); m.className = 'msg ok'; m.textContent = JSON.stringify(r); refresh(); }
    catch (e) { m.className = 'msg err'; m.textContent = e.message; }
  });

  async function refresh() {
    try {
      const c = await API.counts();
      view.querySelector('#i-count').innerHTML =
        `<tr><td>total</td><td>${esc(c.inventory ?? '—')}</td></tr>`;
    } catch (_) {}
    try {
      const r = await API.listEntities('inventory', 0, 10);
      const withStock = Array.isArray(r) ? r.filter((p) => (p.quantity ?? 0) > 0).slice(0, 10) : [];
      view.querySelector('#i-stock').innerHTML = withStock.map((p) =>
        `<tr><td>${p.product_id}</td><td>${esc(p.name)}</td><td>${p.quantity}</td></tr>`
      ).join('') || `<tr><td colspan="3" class="muted">sin productos en stock</td></tr>`;
    } catch (_) {}
  }
}
