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

  document.querySelectorAll("[data-lot-filter-form]").forEach((form) => {
    const sourceSelect = form.querySelector("[data-lot-source-select]");
    const dependentSelect = form.querySelector("[data-dependent-lot-select]");
    const optionTemplate = form.querySelector("template[data-dependent-lot-options]");
    if (!sourceSelect || !dependentSelect || !optionTemplate) return;

    const defaultOption = dependentSelect.querySelector("option");
    if (!defaultOption) return;
    const lotOptions = Array.from(optionTemplate.content.querySelectorAll("option"));
    const syncDependentLots = () => {
      const selectedSource = sourceSelect.selectedOptions[0];
      const itemId = selectedSource ? selectedSource.dataset.itemId : "";
      const previousValue = dependentSelect.value;
      while (dependentSelect.firstChild) {
        dependentSelect.removeChild(dependentSelect.firstChild);
      }
      dependentSelect.appendChild(defaultOption.cloneNode(true));

      if (itemId) {
        lotOptions
          .filter((option) => option.dataset.itemId === itemId)
          .forEach((option) => dependentSelect.appendChild(option.cloneNode(true)));
      }

      const stillAvailable = Array.from(dependentSelect.options).some((option) => option.value === previousValue);
      dependentSelect.value = stillAvailable ? previousValue : "";
      dependentSelect.disabled = !itemId;
    };

    sourceSelect.addEventListener("change", syncDependentLots);
    syncDependentLots();
  });
})();
