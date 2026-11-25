// No recipe content leaves the local application during status polling.
(() => {
  const script = document.currentScript;
  const targets = document.querySelectorAll('#job-progress, [data-job-progress]');
  const progress = text => targets.forEach(target => { target.textContent = text; });
  const poll = async () => {
    try {
      const response = await fetch(script.dataset.statusUrl, {cache: 'no-store'});
      if (!response.ok) throw new Error('status');
      const data = await response.json();
      if (data.status !== 'working') { window.location.reload(); return; }
      progress(data.progress || 'En espera…');
    } catch (_) {
      progress('No pudimos consultar el estado. Reintentando…');
    }
    setTimeout(poll, 2500);
  };
  setTimeout(poll, 1000);
})();
