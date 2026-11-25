(() => {
  document.querySelectorAll('[data-ingredient-note]').forEach(button => {
    const panel = document.getElementById(button.getAttribute('popovertarget'));
    let dismiss;
    const position = () => {
      const anchor = button.getBoundingClientRect();
      const box = panel.getBoundingClientRect();
      const viewport = document.documentElement;
      const left = Math.max(8, Math.min(anchor.left, viewport.clientWidth - box.width - 8));
      const below = anchor.bottom + 8;
      const top = below + box.height <= viewport.clientHeight - 8 ? below : Math.max(8, anchor.top - box.height - 8);
      panel.style.left = `${left}px`;
      panel.style.top = `${top}px`;
    };
    const show = () => {
      clearTimeout(dismiss);
      if (!panel.matches(':popover-open')) panel.showPopover();
      position();
    };
    const later = () => {
      dismiss = setTimeout(() => {
        if (!panel.matches(':hover') && !button.matches(':hover') && document.activeElement !== button) panel.hidePopover();
      }, 150);
    };
    button.addEventListener('pointerenter', event => { if (event.pointerType !== 'touch') show(); });
    // Focus/hover may already have opened it before the native click toggle.
    button.addEventListener('click', event => { event.preventDefault(); show(); });
    button.addEventListener('focus', show);
    button.addEventListener('pointerleave', later);
    button.addEventListener('blur', later);
    panel.addEventListener('pointerenter', () => clearTimeout(dismiss));
    panel.addEventListener('pointerleave', later);
    panel.addEventListener('toggle', () => {
      const opened = panel.matches(':popover-open');
      button.setAttribute('aria-expanded', String(opened));
      if (opened) position();
    });
    window.addEventListener('resize', () => { if (panel.matches(':popover-open')) position(); });
    window.addEventListener('scroll', () => { if (panel.matches(':popover-open')) position(); }, { passive: true });
  });
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
