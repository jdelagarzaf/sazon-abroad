(() => {
  document.querySelectorAll('[data-purchase-check]').forEach(input => {
    const key = 'sazon-purchase:' + input.dataset.purchaseCheck;
    try { input.checked = localStorage.getItem(key) === '1'; } catch (_) { /* Private browsing may restrict storage. */ }
    const update = () => input.closest('li').classList.toggle('purchased', input.checked);
    update();
    input.addEventListener('change', () => {
      update();
      try {
        if (input.checked) localStorage.setItem(key, '1');
        else localStorage.removeItem(key);
      } catch (_) { /* Checking still works for this page. */ }
    });
  });
})();
