(() => {
  document.querySelectorAll("[data-batch-state-form]").forEach((form) => {
    const stateSelect = form.querySelector('select[name="state"]');
    if (!stateSelect) return;

    stateSelect.addEventListener("change", () => {
      if (stateSelect.value === stateSelect.dataset.currentState) return;
      form.submit();
    });
  });
})();
