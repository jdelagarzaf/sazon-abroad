// No recipe content leaves the local application during status polling.
(() => {
  const script = document.currentScript;
  const target = document.getElementById('job-progress');
  const poll = async () => {
    try {
      const response = await fetch(script.dataset.statusUrl, {cache: 'no-store'});
      if (!response.ok) throw new Error('status');
      const data = await response.json();
      if (data.status !== 'working') { window.location.reload(); return; }
      target.textContent = data.progress || 'En espera…';
    } catch (_) {
      target.textContent = 'No pudimos consultar el estado. Reintentando…';
    }
    setTimeout(poll, 2500);
  };
  setTimeout(poll, 1000);
})();
