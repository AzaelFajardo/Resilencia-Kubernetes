// ui.js — shared UI helpers (escapes, badges, cards, tables, toasts, states).

export function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

export function badge(text, cls = '') {
  return `<span class="badge ${cls}">${esc(text)}</span>`;
}

export function dot(up) {
  return `<span class="dot ${up ? 'up' : 'down'}"></span>`;
}

export function help(tip) {
  return `<span class="help" data-tip="${esc(tip)}">?</span>`;
}

export function card(title, tip, body, opts = {}) {
  const cls = opts.full ? 'card full' : opts.small ? 'card small' : 'card';
  const headerExtra = opts.headerExtra ? `<div class="card-h-extra">${opts.headerExtra}</div>` : '';
  return `<section class="${cls}"><header class="card-h"><div class="card-h-title"><h2>${esc(title)}</h2>` +
    (tip ? help(tip) : '') +
    `</div>${headerExtra}</header><div class="card-b">${body}</div></section>`;
}

export function table(head, rows) {
  const thead = `<thead><tr>${head.map((h) => `<th>${esc(h)}</th>`).join('')}</tr></thead>`;
  const tbody = `<tbody>${rows.map((r) =>
    `<tr>${r.map((c) => `<td>${c == null || c === '' ? '<span class="muted">—</span>' : esc(c)}</td>`).join('')}</tr>`
  ).join('')}</tbody>`;
  return `<table class="tbl">${thead}${tbody}</table>`;
}

export function empty(msg = 'Sin datos') {
  return `<div class="empty">${esc(msg)}</div>`;
}

export function spin() {
  return `<div class="loading"><span class="spin"></span> cargando…</div>`;
}

export function toast(msg, type = 'ok') {
  const box = document.getElementById('toasts');
  if (!box) return;
  const t = document.createElement('div');
  t.className = `toast ${type}`;
  t.textContent = msg;
  box.appendChild(t);
  setTimeout(() => t.remove(), 4200);
}

// Custom confirmation dialog (replaces the native browser confirm()).
export function confirmDialog(message) {
  return new Promise((resolve) => {
    document.getElementById('confirm-overlay')?.remove();
    const overlay = document.createElement('div');
    overlay.id = 'confirm-overlay';
    overlay.className = 'confirm-overlay';
    overlay.innerHTML = `
      <div class="confirm-box">
        <p>${esc(message)}</p>
        <div class="row" style="justify-content:flex-end;margin:0">
          <button class="btn secondary" id="cf-cancel">Cancelar</button>
          <button class="btn danger" id="cf-ok">Confirmar</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);
    const close = (val) => { overlay.remove(); resolve(val); };
    overlay.querySelector('#cf-cancel').addEventListener('click', () => close(false));
    overlay.querySelector('#cf-ok').addEventListener('click', () => close(true));
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(false); });
  });
}

export function fmt(v, d = 3) {
  return v == null ? '—' : Number(v).toFixed(d);
}
