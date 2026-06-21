(() => {
  const iterationsInput = document.querySelector("#iterations");
  if (!iterationsInput) return;

  const updateRequirements = () => {
    const iterations = Number.parseInt(iterationsInput.value, 10);
    document.querySelectorAll(".allocation").forEach((row) => {
      const output = row.querySelector(".batch-component-required");
      const lotSelect = row.querySelector('select[name$="_lot"]:not([data-replacement-select])');
      const selectedLot = lotSelect?.selectedOptions?.[0];
      const available = Number.parseFloat(selectedLot?.dataset.available || "");
      const replacementRow = row.querySelector("[data-replacement-row]");
      const replacementSelect = row.querySelector("[data-replacement-select]");
      const replacementRequired = row.querySelector("[data-replacement-required]");
      const quantity = Number.parseFloat(row.dataset.componentQuantity);
      const unit = row.dataset.componentUnit;
      if (!Number.isInteger(iterations) || iterations < 1 || !Number.isFinite(quantity)) {
        output.textContent = "Enter cartridge count";
        if (replacementRow) replacementRow.hidden = true;
        if (replacementSelect) {
          replacementSelect.disabled = true;
          replacementSelect.required = false;
        }
        if (replacementRequired) replacementRequired.textContent = "Enter cartridge count";
        return;
      }
      const required = quantity * iterations;
      output.textContent = `${required.toLocaleString(undefined, {
        maximumFractionDigits: 6,
      })} ${unit}`;
      const needsReplacement = Number.isFinite(available) && available < required;
      if (replacementRow) replacementRow.hidden = !needsReplacement;
      if (replacementSelect) {
        replacementSelect.disabled = !needsReplacement;
        replacementSelect.required = needsReplacement;
        if (!needsReplacement) replacementSelect.value = "";
      }
      if (replacementRequired) {
        const remaining = Math.max(required - (Number.isFinite(available) ? available : 0), 0);
        replacementRequired.textContent = needsReplacement
          ? `${remaining.toLocaleString(undefined, { maximumFractionDigits: 6 })} ${unit}`
          : "No replacement needed";
      }
    });
  };

  iterationsInput.addEventListener("input", updateRequirements);
  document.querySelectorAll(".allocation select").forEach((select) => {
    select.addEventListener("change", updateRequirements);
  });
  updateRequirements();
})();
