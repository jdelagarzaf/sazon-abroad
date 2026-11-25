(() => {
  const dialogs = document.querySelectorAll('.recipe-dialog');
  const open = (dialog) => {
    if (!dialog || dialog.open) return;
    dialog.showModal();
    document.documentElement.classList.add('recipe-modal-open');
  };
  document.querySelectorAll('[data-open-dialog]').forEach(button => {
    button.addEventListener('click', () => open(document.getElementById(button.dataset.openDialog)));
  });
  dialogs.forEach(dialog => {
    dialog.querySelectorAll('[data-close-dialog]').forEach(button => button.addEventListener('click', () => dialog.close()));
    dialog.addEventListener('click', event => {
      if (event.target !== dialog) return;
      const box = dialog.getBoundingClientRect();
      if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) dialog.close();
    });
    dialog.addEventListener('close', () => {
      dialog.querySelector('form').reset();
      dialog.dispatchEvent(new Event('recipe-reset'));
      document.documentElement.classList.remove('recipe-modal-open');
      if (new URL(location.href).searchParams.has('edit')) {
        const url = new URL(location.href);
        url.searchParams.delete('edit');
        history.replaceState(null, '', url);
      }
    });
    const form = dialog.querySelector('[data-ingredient-form]');
    const picker = form?.querySelector('[data-proposal-picker]');
    if (picker) {
      const update = () => {
        const changed = [...form.querySelectorAll('[data-proposal-context]')].some(input => input.value !== input.defaultValue);
        picker.querySelectorAll('option:not([value="original"])').forEach(option => { option.disabled = changed; });
        if (changed) picker.value = 'original';
        form.querySelector('[data-proposals-stale]').hidden = !changed;
        form.querySelectorAll('[data-choice-detail]').forEach(panel => { panel.hidden = panel.dataset.choiceDetail !== picker.value; });
        form.querySelector('[data-substitute-amount]').hidden = picker.value === 'original';
      };
      form.querySelectorAll('[data-proposal-context]').forEach(input => input.addEventListener('input', update));
      picker.addEventListener('change', () => {
        const amount = form.querySelector('[name=sub_amount]');
        amount.value = picker.value === picker.dataset.savedChoice ? amount.defaultValue : '';
        update();
      });
      dialog.addEventListener('recipe-reset', update);
      update();
    }
    if (dialog.hasAttribute('data-auto-open')) open(dialog);
  });
})();
