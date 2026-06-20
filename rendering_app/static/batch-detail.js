(() => {
  document.querySelectorAll("[data-batch-state-form]").forEach((form) => {
    const stateSelect = form.querySelector('select[name="state"]');
    if (!stateSelect) return;

    stateSelect.addEventListener("change", () => {
      if (stateSelect.value === stateSelect.dataset.currentState) return;
      form.submit();
    });
  });

  document.querySelectorAll("[data-garmin-import-form]").forEach((form) => {
    const fileInput = form.querySelector('input[type="file"]');
    if (!fileInput) return;

    fileInput.addEventListener("change", () => {
      if (!fileInput.files.length) return;
      form.submit();
    });
  });
})();
