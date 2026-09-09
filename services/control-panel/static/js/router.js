// router.js — minimal hash router with per-tab lifecycle (cleanup on switch).

const routes = new Map();
let cleanup = null;

export function register(path, render) {
  routes.set(path, render);
}

export function navigate(path) {
  location.hash = '#/' + path;
}

function current() {
  return (location.hash.replace(/^#\//, '').trim()) || 'home';
}

function render() {
  if (typeof cleanup === 'function') { try { cleanup(); } catch (_) {} cleanup = null; }

  const name = current();
  const view = document.getElementById('view');
  if (!view) return;
  view.innerHTML = '';

  document.querySelectorAll('#tabs a').forEach((a) => {
    a.classList.toggle('active', a.dataset.tab === name);
  });

  const fn = routes.get(name) || routes.get('home');
  const out = fn(view);
  if (typeof out === 'function') cleanup = out;
}

export function start() {
  window.addEventListener('hashchange', render);
  render();
}
