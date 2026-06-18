(() => {
  const iterationsInput = document.querySelector("#iterations");
  if (!iterationsInput) return;

  const updateRequirements = () => {
    const iterations = Number.parseInt(iterationsInput.value, 10);
    document.querySelectorAll(".allocation").forEach((row) => {
      const output = row.querySelector(".batch-component-required");
      const quantity = Number.parseFloat(row.dataset.componentQuantity);
      const unit = row.dataset.componentUnit;
      if (!Number.isInteger(iterations) || iterations < 1 || !Number.isFinite(quantity)) {
        output.textContent = "Enter cartridge count";
        return;
      }
      const required = quantity * iterations;
      output.textContent = `${required.toLocaleString(undefined, {
        maximumFractionDigits: 6,
      })} ${unit}`;
    });
  };

  iterationsInput.addEventListener("input", updateRequirements);
  updateRequirements();
})();
