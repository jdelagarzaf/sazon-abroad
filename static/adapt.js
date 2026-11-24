const form = document.getElementById('adapt-form');
const submit = document.getElementById('adapt-submit');
const progress = document.getElementById('adapt-progress');
form.addEventListener('submit', () => {
  submit.disabled = true;
  submit.textContent = 'Adaptando…';
  progress.hidden = false;
  form.setAttribute('aria-busy', 'true');
});
window.addEventListener('pageshow', () => {
  submit.disabled = false;
  submit.textContent = 'Adaptar ingrediente';
  progress.hidden = true;
  form.removeAttribute('aria-busy');
});
