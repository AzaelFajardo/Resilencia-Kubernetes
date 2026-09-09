// crud.js — generic CRUD component (list/create/edit/delete) over /api/entities.
// Temporary raw-JSON UX; Fase F2 replaces it with per-entity field forms.

import { API } from './api.js';
import { card, esc } from './ui.js';

export function mountCrud(container, entity, label) {
  const wrap = document.createElement('div');
  wrap.innerHTML = card(
    `${label} — administrar (CRUD)`,
    'Crea, edita o borra registros de esta entidad. Por ahora se edita con JSON; en la Fase F2 se reemplazará por formularios por campo. El borrado es en cascada según las claves foráneas de la base de datos.',
    `
      <div class="row">
        <label>offset <input id="c-off" type="number" min="0" value="0"></label>
        <label>limit <input id="c-lim" type="number" min="1" max="200" value="20"></label>
        <button id="c-list" class="btn secondary" type="button">Listar</button>
        <span class="msg" id="c-msg"></span>
      </div>
      <div class="row">
        <input id="c-create" style="flex:1;min-width:220px" placeholder='JSON para crear (ej. {"first_name":"Ana"})'>
        <button id="c-create-btn" class="btn secondary" type="button">Crear</button>
      </div>
      <div class="row">
        <input id="c-edit-id" type="number" min="1" placeholder="id a editar">
        <input id="c-edit" style="flex:1;min-width:220px" placeholder='Campos en JSON (ej. {"active":false})'>
        <button id="c-edit-btn" class="btn secondary" type="button">Guardar</button>
      </div>
      <div class="row">
        <input id="c-del-id" type="number" min="1" placeholder="id a borrar">
        <button id="c-del-btn" class="btn danger" type="button">Borrar</button>
      </div>
      <pre class="pre" id="c-out">—</pre>
    `,
    { full: true }
  );
  container.appendChild(wrap);

  const $ = (id) => wrap.querySelector('#' + id);
  const out = $('c-out');
  const msg = $('c-msg');
  const say = (txt, ok = true) => { msg.className = 'msg ' + (ok ? 'ok' : 'err'); msg.textContent = txt; };

  $('c-list').addEventListener('click', async () => {
    const offset = parseInt($('c-off').value) || 0;
    const limit = parseInt($('c-lim').value) || 20;
    out.textContent = 'cargando…';
    try {
      const r = await API.listEntities(entity, offset, limit);
      out.textContent = JSON.stringify(r, null, 2);
      say(`OK — ${Array.isArray(r) ? r.length + ' registros' : 'respuesta recibida'}`);
    } catch (e) { out.textContent = ''; say(e.message, false); }
  });

  $('c-create-btn').addEventListener('click', async () => {
    let body;
    try { body = JSON.parse($('c-create').value); }
    catch (e) { say('JSON inválido: ' + e.message, false); return; }
    try { const r = await API.createEntity(entity, body); out.textContent = JSON.stringify(r, null, 2); say('Creado OK'); }
    catch (e) { say(e.message, false); }
  });

  $('c-edit-btn').addEventListener('click', async () => {
    const id = parseInt($('c-edit-id').value);
    if (!id) { say('Indica un id a editar', false); return; }
    let body;
    try { body = JSON.parse($('c-edit').value); }
    catch (e) { say('JSON inválido: ' + e.message, false); return; }
    try { const r = await API.updateEntity(entity, id, body); out.textContent = JSON.stringify(r, null, 2); say('Guardado OK'); }
    catch (e) { say(e.message, false); }
  });

  $('c-del-btn').addEventListener('click', async () => {
    const id = parseInt($('c-del-id').value);
    if (!id) { say('Indica un id a borrar', false); return; }
    if (!confirm(`¿Borrar ${entity} id=${id}? (borrado en cascada según FK de la BD)`)) return;
    try { const r = await API.deleteEntity(entity, id); out.textContent = JSON.stringify(r, null, 2); say('Borrado OK'); }
    catch (e) { say(e.message, false); }
  });
}

export function crudTable(list) {
  return list.map((r) => `<pre class="pre" style="max-height:140px">${esc(JSON.stringify(r, null, 2))}</pre>`).join('');
}
