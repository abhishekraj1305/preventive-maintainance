(() => {
  'use strict';
  const body = document.body;
  let serverOrigin = Date.parse(body.dataset.serverNow || '') || Date.now();
  let monotonicOrigin = performance.now();
  const serverNow = () => serverOrigin + performance.now() - monotonicOrigin;
  const labels = {pending:'Pending',submitted:'Awaiting approval',rejected:'Rejected',approved:'Approved',open:'Open',repair:'In repair',closed:'Closed'};
  function updateTimers() {
    document.querySelectorAll('[data-timer]').forEach(el => {
      const target = Date.parse(el.dataset.timer);
      if (!Number.isFinite(target)) return;
      const now = el.dataset.end ? Date.parse(el.dataset.end) : serverNow();
      const countdown = el.dataset.mode === 'countdown';
      const delta = countdown ? target - now : Math.max(0, now - target);
      const minutes = Math.floor(Math.abs(delta) / 60000);
      const days = Math.floor(minutes / 1440), hours = Math.floor(minutes % 1440 / 60), mins = minutes % 60;
      el.textContent = `${days ? days + 'd ' : ''}${hours}h ${String(mins).padStart(2,'0')}m${countdown ? (delta < 0 ? ' overdue' : ' left') : ''}`;
      el.classList.toggle('late', countdown && delta < 0);
    });
  }
  updateTimers();
  setInterval(updateTimers, 1000);
  const toggle = document.getElementById('menu-toggle');
  function menu(open) {
    document.getElementById('sidebar')?.classList.toggle('open', open);
    document.getElementById('sidebar-shade')?.classList.toggle('open', open);
    toggle?.setAttribute('aria-expanded', String(open));
  }
  toggle?.addEventListener('click', () => menu(toggle.getAttribute('aria-expanded') !== 'true'));
  document.getElementById('sidebar-shade')?.addEventListener('click', () => menu(false));
  document.addEventListener('keydown', event => { if(event.key === 'Escape') menu(false); });
  document.querySelectorAll('[data-auto-submit]').forEach(el => el.addEventListener('change', () => el.form.requestSubmit()));
  document.querySelectorAll('[data-save-form]').forEach(form => form.addEventListener('submit', event => {
    if(!navigator.onLine) {
      event.preventDefault();
      const state = form.querySelector('.save-state');
      if (state) state.textContent = 'You are offline. Reconnect before saving.';
      connection(false);
      return;
    }
    if (form.dataset.saving) { event.preventDefault(); return; }
    form.dataset.saving = '1';
    const state = form.querySelector('.save-state');
    if (state) state.textContent = 'Saving… Waiting for confirmation.';
    form.querySelectorAll('button[type="submit"],button:not([type])').forEach(button => button.disabled = true);
  }));
  window.addEventListener('pageshow', () => {
    document.querySelectorAll('[data-save-form]').forEach(form => {
      delete form.dataset.saving;
      form.querySelectorAll('button').forEach(button => button.disabled = false);
      const state = form.querySelector('.save-state');
      if(state) state.textContent = '';
    });
  });
  function connection(ok) {
    const warning = document.getElementById('connection-warning');
    if (warning) warning.hidden = ok;
    const state = document.getElementById('connection-state');
    if (state) state.textContent = ok ? '● Live workspace' : '● Reconnecting';
  }
  function updateRecord(row, kind) {
    document.querySelectorAll(`[data-${kind}-id="${row.id}"]`).forEach(el => {
      if (Number(el.dataset.version) !== row.version) {
        el.querySelectorAll('.record-updated').forEach(note => note.hidden = false);
      }
      const badge = el.querySelector('[data-record-status]');
      if (badge) { badge.className = `pill status-${row.status}`; badge.textContent = labels[row.status] || row.status; }
      if (kind === 'pm' && row.status === 'approved') {
        el.querySelectorAll('[data-timer]').forEach(timer => { delete timer.dataset.timer; timer.textContent = 'Complete'; timer.classList.remove('late'); });
        el.querySelectorAll('[data-urgency-label]').forEach(label => label.remove());
      }
      if (kind === 'breakdown' && row.repair_end) el.querySelectorAll('[data-timer]').forEach(timer => timer.dataset.end = row.repair_end);
    });
  }
  let refreshing = false;
  async function refresh() {
    if (document.hidden || refreshing || !body.dataset.statusUrl) return;
    refreshing = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(body.dataset.statusUrl, {credentials:'same-origin',cache:'no-store',headers:{Accept:'application/json'},signal:controller.signal});
      if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) throw new Error('Refresh unavailable');
      const data = await response.json();
      serverOrigin = Date.parse(data.server_now);
      monotonicOrigin = performance.now();
      document.querySelectorAll('[data-count]').forEach(el => { if(data[el.dataset.count] !== undefined) el.textContent = data[el.dataset.count]; });
      data.pm_states?.forEach(row => updateRecord(row, 'pm'));
      data.breakdown_states?.forEach(row => updateRecord(row, 'breakdown'));
      connection(true);
      updateTimers();
    } catch (_) { connection(false); }
    finally { clearTimeout(timeout); refreshing = false; }
  }
  setInterval(refresh, 30000);
  document.addEventListener('visibilitychange', () => { if(!document.hidden) refresh(); });
  window.addEventListener('online', refresh);
  window.addEventListener('offline', () => connection(false));
  window.addEventListener('focus', refresh);
})();
