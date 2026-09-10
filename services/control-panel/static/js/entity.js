// entity.js — reusable data-list component: search, pagination, table,
// row detail, per-field edit, delete, and optional faker/bulk generation.

import { API } from './api.js';
import { card, esc, toast, empty, confirmDialog } from './ui.js';

function idOf(row) {
  return row.id ?? row.product_id ?? row.order_id;
}

export function mountEntity(container, cfg) {
  const state = { offset: 0, limit: 20, search: '' };

  const wrap = document.createElement('div');
  wrap.innerHTML = `
    ${card(`${cfg.label} — listado y administración`, cfg.hint, `
      <div class="row">
        <input id="e-search" placeholder="buscar por id, nombre, estado…" style="flex:1;min-width:150px">
        <button class="btn" id="e-search-btn">Buscar</button>
        <button class="btn secondary" id="e-clear">Limpiar</button>
        ${cfg.faker ? `
          <input id="e-faker-count" type="number" min="1" max="100000" value="100" title="cantidad de registros Faker">
          <button class="btn secondary" id="e-faker">Generar ${cfg.faker.label}</button>` : ''}
        ${cfg.bulkOrders ? `
          <input id="e-bulk-count" type="number" min="1" max="1000" value="10" title="cantidad de órdenes">
          <input id="e-bulk-user" type="number" min="1" placeholder="user_id (opcional)" title="si se indica, todas las órdenes son para ese cliente">
          <button class="btn secondary" id="e-bulk">Generar órdenes</button>` : ''}
      </div>
      <div id="e-table"></div>
      <div class="row" style="justify-content:space-between;margin-top:10px">
        <span class="muted" id="e-info"></span>
        <span>
          <button class="btn secondary sm" id="e-prev">← Anterior</button>
          <button class="btn secondary sm" id="e-next">Siguiente →</button>
        </span>
      </div>
    `, { full: true })}
    <div id="e-detail"></div>
  `;
  container.appendChild(wrap);

  const $ = (id) => wrap.querySelector('#' + id);

  function renderTable(rows) {
    if (!rows.length) { $('e-table').innerHTML = empty('sin resultados'); return; }
    const head = `<thead><tr>${cfg.columns.map((c) => `<th>${esc(c.label)}</th>`).join('')}</tr></thead>`;
    const body = `<tbody>${rows.map((r, i) =>
      `<tr class="clickable" data-i="${i}">${cfg.columns.map((c) =>
        `<td>${c.render ? c.render(r) : (r[c.key] == null || r[c.key] === '' ? '<span class="muted">—</span>' : esc(r[c.key]))}</td>`
      ).join('')}</tr>`
    ).join('')}</tbody>`;
    $('e-table').innerHTML = `<table class="tbl">${head}${body}</table>`;
    $('e-table').querySelectorAll('tr[data-i]').forEach((tr) =>
      tr.addEventListener('click', () => showDetail(rows[+tr.dataset.i]))
    );
  }

  async function load() {
    $('e-table').innerHTML = '<div class="loading"><span class="spin"></span> cargando…</div>';
    try {
      const rows = await API.listEntities(cfg.entity, state.offset, state.limit, state.search);
      renderTable(rows);
      $('e-info').textContent = `${rows.length} registro(s) · offset ${state.offset}`;
    } catch (e) { $('e-table').innerHTML = empty('error: ' + e.message); }
  }

  function buildForm(fields, row) {
    return `<div class="row">` + fields.map((f) => {
      const val = row ? (row[f.name] ?? f.default ?? '') : (f.default ?? '');
      if (f.type === 'select') {
        return `<label>${esc(f.label)} <select data-name="${esc(f.name)}">${f.options.map((o) =>
          `<option value="${esc(o)}" ${String(o) === String(val) ? 'selected' : ''}>${esc(o)}</option>`
        ).join('')}</select></label>`;
      }
      return `<label>${esc(f.label)} <input data-name="${esc(f.name)}" type="${f.type || 'text'}" value="${esc(val)}" placeholder="${esc(f.placeholder || '')}"></label>`;
    }).join('') + `<button class="btn sm" id="d-edit">Guardar cambios</button></div>`;
  }

  function readForm(root) {
    const out = {};
    root.querySelectorAll('[data-name]').forEach((el) => {
      if (el.tagName === 'SELECT') out[el.dataset.name] = el.value;
      else if (el.type === 'number') out[el.dataset.name] = el.value === '' ? null : Number(el.value);
      else out[el.dataset.name] = el.value;
    });
    return out;
  }

  function showDetail(row) {
    const d = $('e-detail');
    d.innerHTML = '';
    const box = document.createElement('div');
    box.innerHTML = card('Detalle del registro',
      'Datos completos del registro. Edita los campos disponibles o bórralo (el borrado es en cascada según las claves foráneas de la BD).',
      `<div class="row" style="justify-content:space-between">
         <span class="muted">id: ${esc(idOf(row))}</span>
         <button class="btn danger sm" id="d-del">Borrar</button>
       </div>
       ${cfg.editFields ? buildForm(cfg.editFields, row) : ''}
       <pre class="pre" style="max-height:240px">${esc(JSON.stringify(row, null, 2))}</pre>`,
      { full: true });
    d.appendChild(box);

    box.querySelector('#d-del').addEventListener('click', async () => {
      const id = idOf(row);
      if (!(await confirmDialog(`¿Borrar ${cfg.label.toLowerCase()} id=${id}? (cascada según FK de la BD)`))) return;
      try { await API.deleteEntity(cfg.entity, id); toast('Borrado', 'ok'); d.innerHTML = ''; load(); }
      catch (e) { toast('Error: ' + e.message, 'err'); }
    });

    if (cfg.editFields) {
      box.querySelector('#d-edit').addEventListener('click', async () => {
        const data = readForm(box);
        const id = idOf(row);
        try {
          await API.updateEntity(cfg.entity, id, cfg.buildEdit ? cfg.buildEdit(data) : data);
          toast('Guardado OK', 'ok');
          d.innerHTML = '';
          load();
        } catch (e) { toast('Error: ' + e.message, 'err'); }
      });
    }
  }

  $('e-search-btn').addEventListener('click', () => { state.search = $('e-search').value.trim(); state.offset = 0; load(); });
  $('e-clear').addEventListener('click', () => { $('e-search').value = ''; state.search = ''; state.offset = 0; load(); });
  $('e-search').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); state.search = $('e-search').value.trim(); state.offset = 0; load(); } });
  $('e-prev').addEventListener('click', () => { state.offset = Math.max(0, state.offset - state.limit); load(); });
  $('e-next').addEventListener('click', () => { state.offset += state.limit; load(); });

  if (cfg.faker) {
    $('e-faker').addEventListener('click', async () => {
      const count = parseInt($('e-faker-count').value) || 100;
      try { const r = await API.faker(cfg.faker.what, count); toast(JSON.stringify(r), 'ok'); load(); }
      catch (e) { toast('Error: ' + e.message, 'err'); }
    });
  }

  if (cfg.bulkOrders) {
    $('e-bulk').addEventListener('click', async () => {
      const count = parseInt($('e-bulk-count').value) || 10;
      const u = $('e-bulk-user').value;
      try {       const r = await API.generateOrders({ count, user_id: u ? parseInt(u) : null }); toast(JSON.stringify(r), 'ok'); load(); }
      catch (e) { toast('Error: ' + e.message, 'err'); }
    });
  }

  load();
}
