// interval.js — per-tab auto-refresh control (interval input + manual button).

export function mountRefreshControl(container, { onRefresh, initial = 5 } = {}) {
  let timer = null;
  let inFlight = false;
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

  // Skip the tick if the previous refresh is still running. Without this, a
  // slow refresh (e.g. a down service stalling its HTTP call) would let the
  // interval pile up overlapping requests and saturate the panel.
  function tick() {
    if (inFlight || !onRefresh) return;
    inFlight = true;
    Promise.resolve(onRefresh()).finally(() => { inFlight = false; });
  }

  function start() {
    clearInterval(timer);
    timer = setInterval(tick, seconds * 1000);
  }

  input.addEventListener('change', () => {
    seconds = Math.max(1, Math.floor(Number(input.value) || 1));
    input.value = seconds;
    start();
    tick();
  });
  btn.addEventListener('click', tick);

  start();

  return () => clearInterval(timer);
}
