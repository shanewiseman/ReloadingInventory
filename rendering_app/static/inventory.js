(() => {
  const form = document.querySelector("#inventory-lot-form");
  const itemSelect = document.querySelector("#inventory-item");
  const activeCheckbox = form?.querySelector('input[name="active"]');
  const replaceActive = document.querySelector("#replace-active");
  if (!form || !itemSelect || !activeCheckbox || !replaceActive) return;

  form.addEventListener("submit", (event) => {
    const selectedItem = itemSelect.selectedOptions[0];
    const hasActiveLot = selectedItem?.dataset.hasActiveLot === "true";
    replaceActive.value = "false";

    if (activeCheckbox.checked && hasActiveLot) {
      const proceed = window.confirm(
        "This item already has an active consumption lot. Continue and replace the existing active lot?"
      );
      if (!proceed) {
        event.preventDefault();
        return;
      }
      replaceActive.value = "true";
    } else if (!activeCheckbox.checked && !hasActiveLot) {
      const makeActive = window.confirm(
        "This item does not have an active consumption lot. Make this new lot active?"
      );
      if (makeActive) activeCheckbox.checked = true;
    }
  });
})();
