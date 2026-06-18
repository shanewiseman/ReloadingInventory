(() => {
  document.querySelectorAll("[data-container-state-form]").forEach((form) => {
    const stateSelect = form.querySelector('select[name="state"]');
    if (!stateSelect) return;

    stateSelect.addEventListener("change", () => {
      if (stateSelect.value === stateSelect.dataset.currentState) return;
      form.submit();
    });
  });

  document.querySelectorAll("[data-container-assignment-form]").forEach((form) => {
    const existingBatchIds = (form.dataset.existingBatchIds || "")
      .split(",")
      .filter(Boolean);
    const batchSelect = form.querySelector('select[name="batch_id"]');
    const acknowledgement = form.querySelector("[data-mixed-batch-ack]");
    const acknowledgementCheckbox = acknowledgement?.querySelector(
      'input[name="acknowledge_mixed_batch"]'
    );

    if (!batchSelect || !acknowledgement || !acknowledgementCheckbox) return;

    const updateAcknowledgement = () => {
      const selectedBatchId = batchSelect.value;
      const requiresAcknowledgement = existingBatchIds.some(
        (batchId) => batchId !== selectedBatchId
      );
      acknowledgement.hidden = !requiresAcknowledgement;
      acknowledgementCheckbox.disabled = !requiresAcknowledgement;
      if (!requiresAcknowledgement) acknowledgementCheckbox.checked = false;
    };

    batchSelect.addEventListener("change", updateAcknowledgement);
    updateAcknowledgement();
  });
})();
