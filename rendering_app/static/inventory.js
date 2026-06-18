(() => {
  const form = document.querySelector("#inventory-lot-form");
  const itemPicker = document.querySelector("#inventory-item-picker");
  const itemType = document.querySelector("#inventory-item-type");
  const activeCheckbox = form?.querySelector('input[name="active"]');
  const replaceActive = document.querySelector("#replace-active");
  if (!form || !itemPicker || !itemType || !activeCheckbox || !replaceActive) return;

  const updateVisibleItems = () => {
    const selectedType = itemType.value;
    let visibleCount = 0;
    itemPicker.querySelectorAll(".item-choice").forEach((choice) => {
      const visible = selectedType && choice.dataset.itemCategory === selectedType;
      choice.hidden = !visible;
      if (!visible) {
        const input = choice.querySelector('input[name="item_id"]');
        if (input) input.checked = false;
      } else {
        visibleCount += 1;
      }
    });

    const empty = itemPicker.querySelector("[data-empty-message]");
    if (empty) {
      empty.textContent = selectedType
        ? "No unarchived items found for this type."
        : "Select an item type to show matching active items.";
      empty.hidden = visibleCount > 0;
    }
  };

  itemType.addEventListener("change", updateVisibleItems);
  updateVisibleItems();

  form.addEventListener("submit", (event) => {
    const selectedItem = itemPicker.querySelector('input[name="item_id"]:checked');
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
