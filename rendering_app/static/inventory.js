(() => {
  const form = document.querySelector("#inventory-lot-form");
  const itemPicker = document.querySelector("#inventory-item-picker");
  const itemType = document.querySelector("#inventory-item-type");
  const activeCheckbox = form?.querySelector('input[name="active"]');
  const replaceActive = document.querySelector("#replace-active");
  const activeReplacementWarning = form?.querySelector("[data-active-replacement-warning]");
  if (!form || !itemPicker || !itemType || !activeCheckbox || !replaceActive) return;

  const placeholders = {
    BULLET: {
      manufacturer_lot: "HDY-158-ACT",
      quantity: "500",
      cost: "54.99",
      notes: "HDY-158-ACT Selenium workflow inventory lot.",
    },
    POWDER: {
      manufacturer_lot: "H110-ACT",
      quantity: "1",
      cost: "42.99",
      notes: "H110-ACT Selenium workflow inventory lot.",
    },
    PRIMER: {
      manufacturer_lot: "CCI550-ACT",
      quantity: "1000",
      cost: "89.99",
      notes: "CCI550-ACT Selenium workflow inventory lot.",
    },
    CASE: {
      manufacturer_lot: "STAR-NI-ACT",
      quantity: "1000",
      cost: "209.99",
      notes: "STAR-NI-ACT Selenium workflow inventory lot.",
    },
    OTHER: {
      manufacturer_lot: "MTM-LBL-ACT",
      quantity: "25",
      cost: "6.99",
      notes: "MTM-LBL-ACT Selenium workflow inventory lot.",
    },
  };

  const updatePlaceholders = () => {
    const selectedType = itemType.value;
    const typePlaceholders = placeholders[selectedType] || placeholders.BULLET;
    Object.entries(typePlaceholders).forEach(([name, placeholder]) => {
      const control = form.querySelector(`[name="${name}"]`);
      if (control) control.placeholder = placeholder;
    });
  };

  const updateVisibleItems = () => {
    const selectedType = itemType.value;
    updatePlaceholders();
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
    updateActiveReplacementWarning();
  };

  const selectedItemHasActiveLot = () => {
    const selectedItem = itemPicker.querySelector('input[name="item_id"]:checked');
    return selectedItem?.dataset.hasActiveLot === "true";
  };

  const updateActiveReplacementWarning = () => {
    if (!activeReplacementWarning) return;
    activeReplacementWarning.hidden = !(activeCheckbox.checked && selectedItemHasActiveLot());
  };

  itemType.addEventListener("change", updateVisibleItems);
  itemPicker.addEventListener("change", updateActiveReplacementWarning);
  activeCheckbox.addEventListener("change", updateActiveReplacementWarning);
  updateVisibleItems();

  const askYesNo = (() => {
    const overlay = document.createElement("div");
    overlay.className = "choice-dialog";
    overlay.hidden = true;
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.innerHTML = `
      <div class="choice-dialog-panel">
        <p data-choice-message></p>
        <div class="choice-dialog-actions">
          <button type="button" data-choice-yes>Yes</button>
          <button type="button" class="secondary" data-choice-no>No</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

    const message = overlay.querySelector("[data-choice-message]");
    const yes = overlay.querySelector("[data-choice-yes]");
    const no = overlay.querySelector("[data-choice-no]");

    return (text) => new Promise((resolve) => {
      const close = (answer) => {
        overlay.hidden = true;
        document.removeEventListener("keydown", onKeyDown);
        yes.removeEventListener("click", onYes);
        no.removeEventListener("click", onNo);
        resolve(answer);
      };
      const onYes = () => close(true);
      const onNo = () => close(false);
      const onKeyDown = (event) => {
        if (event.key === "Escape") close(false);
      };

      message.textContent = text;
      overlay.hidden = false;
      yes.addEventListener("click", onYes);
      no.addEventListener("click", onNo);
      document.addEventListener("keydown", onKeyDown);
      yes.focus();
    });
  })();

  form.addEventListener("submit", (event) => {
    if (form.dataset.choiceConfirmed === "true") {
      delete form.dataset.choiceConfirmed;
      return;
    }

    const selectedItem = itemPicker.querySelector('input[name="item_id"]:checked');
    const hasActiveLot = selectedItem?.dataset.hasActiveLot === "true";
    replaceActive.value = "false";

    if (activeCheckbox.checked && hasActiveLot) {
      event.preventDefault();
      askYesNo("This item already has an active consumption lot. Continue and replace the existing active lot?")
        .then((proceed) => {
          if (!proceed) return;
          replaceActive.value = "true";
          form.dataset.choiceConfirmed = "true";
          form.requestSubmit();
        });
    } else if (!activeCheckbox.checked && !hasActiveLot) {
      event.preventDefault();
      askYesNo("This item does not have an active consumption lot. Make this new lot active?")
        .then((makeActive) => {
          if (makeActive) activeCheckbox.checked = true;
          form.dataset.choiceConfirmed = "true";
          form.requestSubmit();
        });
    }
  });
})();
