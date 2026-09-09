// refresh.js — global auto-refresh interval + manual refresh trigger.

let intervalMs = 5000;
const intervalListeners = new Set();
const refreshers = new Set();

export function getIntervalSeconds() {
  return intervalMs / 1000;
}

export function setRefreshInterval(seconds) {
  intervalMs = Math.max(1, Math.floor(Number(seconds) || 1)) * 1000;
  intervalListeners.forEach((fn) => fn(intervalMs));
}

export function onIntervalChange(fn) {
  intervalListeners.add(fn);
  return () => intervalListeners.delete(fn);
}

// Creates an interval that follows the global refresh interval, registers `fn`
// for manual refresh, and returns a cleanup function.
export function createTimer(fn) {
  let timer = setInterval(fn, intervalMs);
  refreshers.add(fn);
  const off = onIntervalChange((ms) => { clearInterval(timer); timer = setInterval(fn, ms); });
  return () => { clearInterval(timer); off(); refreshers.delete(fn); };
}

export function refreshNow() {
  refreshers.forEach((fn) => { try { fn(); } catch (_) {} });
}
