// interval.js — per-tab auto-refresh control (interval input + manual button).

export function mountRefreshControl(container, { onRefresh, initial = 5 } = {}) {
  let timer = null;
  let seconds = Math.max(1, Math.floor(Number(initial) || 5));

  const wrap = document.createElement('div');
  wrap.className = 'refresh-ctl';
  wrap.innerHTML = `
    <span class="lbl">refresco</span>
    <input type="number" min="1" step="1" value="${seconds}" data-tip="Intervalo de auto-refresco de esta pestaña, en segundos (mínimo 1).">
    <span class="lbl">s</span>
    <button class="btn sm secondary" data-tip="Actualizar ahora">⟳ Actualizar</button>
  `;
  container.insertBefore(wrap, container.firstChild);

  const input = wrap.querySelector('input');
  const btn = wrap.querySelector('button');

  function start() {
    clearInterval(timer);
    timer = setInterval(onRefresh, seconds * 1000);
  }

  input.addEventListener('change', () => {
    seconds = Math.max(1, Math.floor(Number(input.value) || 1));
    input.value = seconds;
    start();
    if (onRefresh) onRefresh();
  });
  btn.addEventListener('click', () => onRefresh && onRefresh());

  start();

  return () => clearInterval(timer);
}
