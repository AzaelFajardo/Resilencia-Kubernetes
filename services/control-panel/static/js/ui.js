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
  const cls = opts.full ? 'card full' : 'card';
  return `<section class="${cls}"><header class="card-h"><h2>${esc(title)}</h2>` +
    (tip ? help(tip) : '') +
    `</header><div class="card-b">${body}</div></section>`;
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

export function fmt(v, d = 3) {
  return v == null ? '—' : Number(v).toFixed(d);
}
