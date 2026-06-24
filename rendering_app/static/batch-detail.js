(() => {
  document.querySelectorAll("[data-batch-state-form]").forEach((form) => {
    const stateSelect = form.querySelector('select[name="state"]');
    const qaOverride = form.querySelector("[data-qa-override]");
    if (!stateSelect) return;

    stateSelect.addEventListener("change", () => {
      if (stateSelect.value === stateSelect.dataset.currentState) return;
      if (qaOverride) qaOverride.value = "false";
      if (stateSelect.value === "PRODUCED" && form.dataset.qaSatisfied !== "true") {
        const required = form.dataset.qaRequired || "0";
        const completed = form.dataset.qaCompleted || "0";
        const confirmed = window.confirm(
          `QA measurements are incomplete.\n\nRequired samples: ${required}\nCompleted samples: ${completed}\n\nTransition to Produced anyway?`
        );
        if (!confirmed) {
          stateSelect.value = stateSelect.dataset.currentState;
          return;
        }
        if (qaOverride) qaOverride.value = "true";
      }
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
